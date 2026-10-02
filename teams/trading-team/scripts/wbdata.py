#!/usr/bin/env python3
"""
wbdata — zero-config real-time market data for the DSH finance teams.

Why this exists
---------------
Every member brief in this plugin used to say "use `web_fetch` / `web_search`".
That is a weak data path: `web_search` needs a search key this deployment does not
have, and scraping quote pages through `web_fetch` returns HTML a model has to
guess its way through — slow, lossy, and easy to hallucinate from.

The endpoints below are public quote/filing APIs that need **no API key, no
token, no login**. They are the same upstreams the major finance sites render
from, so a member can get a real, timestamped number in one command.

Design rules
------------
* **Standard library only.** No `requests`, no `pandas`. A member may run in a
  sandbox where nothing is installed, so the script must never fail on imports.
* **JSON on stdout.** Members parse it; humans can pipe it to `python3 -m json.tool`.
  Progress and errors go to stderr so a redirect never corrupts the payload.
* **Never invent a number.** A source that fails is reported as an `error` entry
  in the payload. Callers are told to write "未获取到" rather than to guess.
* **Timestamp everything.** Each payload carries `fetched_at` and, where the
  upstream provides one, the market's own quote time — a price without a time is
  not usable for a trading decision.

Usage
-----
    python3 wbdata.py quote sh600519 hk00700 usAAPL
    python3 wbdata.py kline sh600519 --period day --count 120
    python3 wbdata.py minute sh600519
    python3 wbdata.py financials 600519
    python3 wbdata.py announcements 600519 --count 10
    python3 wbdata.py research 600519 --count 10
    python3 wbdata.py fundflow sh600519
    python3 wbdata.py billboard --count 10
    python3 wbdata.py margin 600519
    python3 wbdata.py sector --count 10
    python3 wbdata.py northbound
    python3 wbdata.py snapshot sh600519          # one call, everything about a ticker
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone, timedelta

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122 Safari/537.36"
TIMEOUT = 12
CST = timezone(timedelta(hours=8))


def log(msg: str) -> None:
    """Diagnostics go to stderr so stdout stays a clean JSON payload."""
    print(msg, file=sys.stderr)


def fetch(url: str, *, referer: str | None = None, encoding: str = "utf-8",
          attempts: int = 3) -> str:
    """
    GET a URL and return decoded text, retrying transient failures.

    Tencent and Sina serve GBK, so callers pass `encoding="gbk"`; decoding with
    the wrong codec yields mojibake in company names, which then leaks into a
    report as a corrupted name.

    The retry matters in practice: Eastmoney's `push2` endpoints intermittently
    drop the connection (`RemoteDisconnected`) under back-to-back requests, and a
    single flaky GET should not read as "this data does not exist".
    """
    last: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": UA,
                "Accept": "*/*",
                "Connection": "close",
                **({"Referer": referer} if referer else {}),
            })
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                raw = resp.read()
            if not raw.strip():
                raise urllib.error.URLError("empty response body")
            return raw.decode(encoding, errors="replace")
        except Exception as exc:                     # noqa: BLE001 - retried below
            last = exc
            if attempt < attempts:
                time.sleep(0.6 * attempt)
    raise last if last is not None else RuntimeError("fetch failed")


def fetch_json(url: str, *, referer: str | None = None):
    return json.loads(fetch(url, referer=referer))


def now_cst() -> str:
    return datetime.now(CST).strftime("%Y-%m-%d %H:%M:%S%z")


# --------------------------------------------------------------------------
# Symbol handling
# --------------------------------------------------------------------------

def normalize(code: str) -> str:
    """
    Normalize a user-supplied symbol to Tencent's `sh600519` form.

    Accepts `600519`, `SH600519`, `600519.SH`, `sh600519`, `00700`, `hk00700`,
    `AAPL`, `usAAPL`. Getting this wrong is the single most common failure, so it
    is done once, here, rather than in every caller.

    The exchange prefix is lowercased but the **ticker is not**: the quote API
    keys US symbols as `usAAPL`, and lowercasing to `usaapl` makes the upstream
    answer `v_pv_none_match` (no such symbol) rather than an error — a silent
    empty result, which is the worst possible failure mode for a data layer.
    """
    c = code.strip().replace(" ", "")
    low = c.lower()

    m = re.fullmatch(r"(sh|sz|bj|hk|us)([a-z0-9.]+)", low)
    if m:
        prefix, body = m.group(1), m.group(2)
        return prefix + (body.upper() if prefix == "us" else body)

    m = re.fullmatch(r"(\d{6})\.(sh|sz|bj|ss)", low)
    if m:
        return ("sh" if m.group(2) in ("sh", "ss") else m.group(2)) + m.group(1)

    if re.fullmatch(r"\d{6}", low):
        # 6/9 -> Shanghai, 0/2/3 -> Shenzhen, 4/8 -> Beijing
        return ("sh" if low[0] in "69" else "bj" if low[0] in "48" else "sz") + low

    if re.fullmatch(r"\d{5}", low):
        return "hk" + low

    if re.fullmatch(r"[a-z][a-z.\-]{0,9}", low):
        return "us" + low.upper()

    raise ValueError(f"unrecognized symbol: {code!r}")


def eastmoney_secid(code: str) -> str:
    """Eastmoney addresses instruments as `<market>.<code>`."""
    s = normalize(code)
    if s.startswith("sh"):
        return f"1.{s[2:]}"
    if s.startswith("sz"):
        return f"0.{s[2:]}"
    if s.startswith("bj"):
        return f"0.{s[2:]}"
    if s.startswith("hk"):
        return f"116.{s[2:]}"
    return f"105.{s[2:]}"


def eastmoney_plain(code: str) -> str:
    """Eastmoney's data-center APIs want the bare digits for A-shares."""
    s = normalize(code)
    return s[2:] if s[:2] in ("sh", "sz", "bj") else s[2:]


# --------------------------------------------------------------------------
# Quotes
# --------------------------------------------------------------------------

# Tencent's quote payload is a `~`-separated record whose **tail differs per
# market**: A-shares carry PB at [46], while HK and US put a name string there.
# Verified 2026-09-30 against 贵州茅台 (PB 6.26 at [46]) vs 腾讯控股 ('TENCENT')
# and 苹果 ('Apple Inc.'). Reading [46] blindly as PB is therefore only correct
# for A-shares — the shared prefix is indexed once and the tail per market.
_TX_COMMON = {
    "name": 1, "code": 2, "price": 3, "prev_close": 4, "open": 5, "volume": 6,
    "time": 30, "change": 31, "change_pct": 32, "high": 33, "low": 34,
    "amount": 37, "turnover": 38, "pe": 39, "amplitude": 43,
    "float_cap": 44, "total_cap": 45,
}

# Extra indices that are only meaningful for one market family.
_TX_TAIL = {
    "a": {"pb": 46, "limit_up": 47, "limit_down": 48},
    "hk": {},
    "us": {},
}


def _num(value, scale=None):
    """Parse a numeric field, returning None for blanks instead of raising."""
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    if scale is not None:
        out /= scale
    return out


def _market_of(sym: str) -> str:
    """Classify a normalized symbol into the quote payload's market family."""
    if sym.startswith(("sh", "sz", "bj")):
        return "a"
    if sym.startswith("hk"):
        return "hk"
    return "us"


def _clean_time(raw, market: str):
    """
    Normalize the three quote-time spellings: `20260930161458` (A),
    `2026/09/30 16:08:33` (HK), `2026-09-30 16:00:01` (US).
    """
    if not raw:
        return None
    t = raw.strip()
    if re.fullmatch(r"\d{14}", t):
        return f"{t[0:4]}-{t[4:6]}-{t[6:8]} {t[8:10]}:{t[10:12]}:{t[12:14]}"
    if re.fullmatch(r"\d{4}/\d{2}/\d{2} \d{2}:\d{2}:\d{2}", t):
        return t.replace("/", "-")
    return t


def quote(codes: list[str]) -> dict:
    """
    Real-time snapshot for any mix of A-share / HK / US symbols.

    `qt.gtimg.cn` accepts a comma-separated batch, so N symbols cost one request —
    which matters because a member's turn budget is small.

    Symbols the upstream does not recognise come back as `v_pv_none_match`, which
    means "no such symbol" rather than "no data". They are surfaced in a `missing`
    list so a caller can say the ticker was wrong instead of reporting an empty
    market.
    """
    syms = [normalize(c) for c in codes]
    text = fetch("https://qt.gtimg.cn/q=" + ",".join(syms), encoding="gbk")
    rows, missing = [], []
    seen = set()
    for line in text.splitlines():
        line = line.strip()
        if "none_match" in line:
            continue
        m = re.match(r'v_(\w+)="([^"]*)"', line)
        if not m:
            continue
        sym, blob = m.group(1), m.group(2)
        parts = blob.split("~")
        if len(parts) < 49:
            continue
        market = _market_of(sym)
        row = {"symbol": sym, "market": market}
        for key, idx in _TX_COMMON.items():
            if key in ("name", "code", "time"):
                row[key] = parts[idx] or None
            else:
                row[key] = _num(parts[idx])
        for key, idx in _TX_TAIL[market].items():
            row[key] = _num(parts[idx]) if idx < len(parts) else None
        row["quote_time"] = _clean_time(row.pop("time", None), market)
        # A-share caps are absolute prices; HK/US leave them empty.
        rows.append(row)
        seen.add(sym)
    missing = [s for s in syms if s not in seen]
    return {"source": "qt.gtimg.cn", "fetched_at": now_cst(),
            "quotes": rows, "missing": missing}


# --------------------------------------------------------------------------
# K-line
# --------------------------------------------------------------------------

_PERIOD = {"day": "day", "week": "week", "month": "month"}


def kline(code: str, period: str = "day", count: int = 120, adjust: str = "qfq") -> dict:
    """
    OHLCV history, forward-adjusted by default.

    Tencent caps a single response, so `count` is clamped to a sane window and the
    caller is told what it actually got rather than silently receiving fewer rows.
    """
    if period not in _PERIOD:
        raise ValueError(f"period must be one of {sorted(_PERIOD)}")
    sym = normalize(code)
    count = max(1, min(int(count), 640))
    url = (f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
           f"?param={sym},{_PERIOD[period]},,,{count},{adjust}")
    data = fetch_json(url)
    node = (data.get("data") or {}).get(sym) or {}
    # The adjusted series lands under `qfqday`/`hfqday`; unadjusted under `day`.
    series = None
    for key in (f"{adjust}{_PERIOD[period]}", _PERIOD[period]):
        if isinstance(node.get(key), list) and node[key]:
            series = node[key]
            break
    bars = []
    for item in series or []:
        if len(item) < 6:
            continue
        bars.append({
            "date": item[0], "open": _num(item[1]), "close": _num(item[2]),
            "high": _num(item[3]), "low": _num(item[4]), "volume": _num(item[5]),
        })
    return {
        "source": "web.ifzq.gtimg.cn", "symbol": sym, "period": period,
        "adjust": adjust, "requested": count, "returned": len(bars),
        "fetched_at": now_cst(), "bars": bars,
    }


def minute(code: str) -> dict:
    """Intraday 5-minute bars — what a short-term member reads for entry timing."""
    sym = normalize(code)
    url = f"https://ifzq.gtimg.cn/appstock/app/kline/mkline?param={sym},m5,,320"
    data = fetch_json(url)
    node = (data.get("data") or {}).get(sym) or {}
    raw = node.get("m5") or []
    bars = []
    for item in raw:
        if len(item) < 6:
            continue
        bars.append({
            "time": item[0], "open": _num(item[1]), "close": _num(item[2]),
            "high": _num(item[3]), "low": _num(item[4]), "volume": _num(item[5]),
        })
    return {"source": "ifzq.gtimg.cn", "symbol": sym, "interval": "5m",
            "returned": len(bars), "fetched_at": now_cst(), "bars": bars}


# --------------------------------------------------------------------------
# Fundamentals, filings, research
# --------------------------------------------------------------------------

def financials(code: str) -> dict:
    """Main financial indicators from Eastmoney's data center (multi-period)."""
    sec = f"{eastmoney_plain(code)}.{'SH' if normalize(code).startswith('sh') else 'SZ'}"
    filt = urllib.parse.quote(f'(SECUCODE="{sec}")')
    url = ("https://datacenter.eastmoney.com/securities/api/data/v1/get"
           f"?reportName=RPT_F10_FINANCE_MAINFINADATA&columns=ALL&filter={filt}"
           "&pageSize=12&sortColumns=REPORT_DATE&sortTypes=-1")
    data = fetch_json(url, referer="https://emweb.securities.eastmoney.com/")
    result = data.get("result") or {}
    rows = []
    for item in result.get("data") or []:
        rows.append({
            "report_date": (item.get("REPORT_DATE") or "")[:10],
            "report_name": item.get("REPORT_DATE_NAME"),
            "revenue": item.get("TOTALOPERATEREVE"),
            "revenue_yoy": item.get("TOTALOPERATEREVETZ"),
            "net_profit": item.get("PARENTNETPROFIT"),
            "net_profit_yoy": item.get("PARENTNETPROFITTZ"),
            "roe": item.get("ROEJQ"),
            "gross_margin": item.get("XSMLL"),
            "net_margin": item.get("XSJLL"),
            "debt_ratio": item.get("ZCFZL"),
            "eps": item.get("EPSJB"),
            "bps": item.get("BPS"),
            "revenue_per_share": item.get("MGSY"),
        })
    return {"source": "datacenter.eastmoney.com", "symbol": normalize(code),
            "periods": len(rows), "fetched_at": now_cst(), "financials": rows}


def announcements(code: str, count: int = 10) -> dict:
    """Company filings from Eastmoney's announcement feed (exchange-sourced)."""
    url = ("https://np-anotice-stock.eastmoney.com/api/security/ann"
           f"?sr=-1&page_size={max(1, min(int(count), 50))}&page_index=1"
           f"&ann_type=A&client_source=web&stock_list={eastmoney_plain(code)}")
    data = fetch_json(url, referer="https://data.eastmoney.com/")
    rows = []
    for item in (data.get("data") or {}).get("list") or []:
        rows.append({
            "title": item.get("title"),
            "date": (item.get("notice_date") or "")[:10],
            "type": (item.get("columns") or [{}])[0].get("column_name"),
            "url": f"https://data.eastmoney.com/notices/detail/{eastmoney_plain(code)}/{item.get('art_code')}.html",
        })
    return {"source": "np-anotice-stock.eastmoney.com", "symbol": normalize(code),
            "count": len(rows), "fetched_at": now_cst(), "announcements": rows}


def research(code: str, count: int = 10) -> dict:
    """Sell-side analyst reports. Titles carry the rating and the target thesis."""
    today = datetime.now(CST)
    begin = f"{today.year - 1}-01-01"
    end = f"{today.year}-12-31"
    url = ("https://reportapi.eastmoney.com/report/list"
           f"?industryCode=*&pageSize={max(1, min(int(count), 50))}&pageNo=1&qType=0"
           f"&code={eastmoney_plain(code)}&beginTime={begin}&endTime={end}")
    data = fetch_json(url, referer="https://data.eastmoney.com/")
    rows = []
    for item in data.get("data") or []:
        rows.append({
            "title": item.get("title"),
            "org": item.get("orgSName") or item.get("orgName"),
            "date": (item.get("publishDate") or "")[:10],
            "rating": item.get("emRatingName"),
            "eps_this_year": item.get("predictThisYearEps"),
            "pe_this_year": item.get("predictThisYearPe"),
        })
    return {"source": "reportapi.eastmoney.com", "symbol": normalize(code),
            "count": len(rows), "fetched_at": now_cst(), "research": rows}


# --------------------------------------------------------------------------
# Capital flow / positioning
# --------------------------------------------------------------------------

def fundflow(code: str) -> dict:
    """
    Order-size capital flow.

    Sina is the working source here: Eastmoney's `fflow` endpoints are
    unreachable from some networks, and Tencent's `ff` controllers now 404.
    Values are in CNY; r0=super-large, r1=large, r2=medium, r3=small.
    """
    sym = normalize(code)
    url = ("https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/"
           f"MoneyFlow.ssi_ssfx_flzjtj?daima={sym}")
    data = fetch_json(url, referer="https://finance.sina.com.cn")
    buckets = []
    for key, label in (("r0", "超大单"), ("r1", "大单"), ("r2", "中单"), ("r3", "小单")):
        inflow, outflow = _num(data.get(f"{key}_in")), _num(data.get(f"{key}_out"))
        buckets.append({
            "bucket": label,
            "inflow": inflow, "outflow": outflow,
            "net": (inflow - outflow) if inflow is not None and outflow is not None else None,
    })
    return {"source": "vip.stock.finance.sina.com.cn", "symbol": sym,
            "name": data.get("name"), "price": _num(data.get("trade")),
            "fetched_at": now_cst(), "flow": buckets,
            "note": "r0..r3 = super-large / large / medium / small order buckets"}


def billboard(count: int = 10) -> dict:
    """The daily 龙虎榜 — which seats traded what, and how much."""
    url = ("https://datacenter-web.eastmoney.com/api/data/v1/get"
           "?reportName=RPT_DAILYBILLBOARD_DETAILSNEW&columns=ALL"
           f"&pageSize={max(1, min(int(count), 50))}&pageNumber=1"
           "&sortColumns=TRADE_DATE&sortTypes=-1")
    data = fetch_json(url, referer="https://data.eastmoney.com/")
    rows = []
    for item in ((data.get("result") or {}).get("data") or []):
        rows.append({
            "date": (item.get("TRADE_DATE") or "")[:10],
            "code": item.get("SECURITY_CODE"), "name": item.get("SECURITY_NAME_ABBR"),
            "reason": item.get("EXPLANATION"),
            "change_pct": item.get("CHANGE_RATE"),
            "net_buy": item.get("BILLBOARD_NET_AMT"),
            "turnover": item.get("ACCUM_AMOUNT"),
        })
    return {"source": "datacenter-web.eastmoney.com", "count": len(rows),
            "fetched_at": now_cst(), "billboard": rows}


def margin(code: str, count: int = 10) -> dict:
    """Margin trading balance — leverage appetite in one name."""
    filt = urllib.parse.quote(f'(SCODE="{eastmoney_plain(code)}")')
    url = ("https://datacenter-web.eastmoney.com/api/data/v1/get"
           "?reportName=RPTA_WEB_RZRQ_GGMX&columns=ALL"
           f"&filter={filt}&pageSize={max(1, min(int(count), 50))}&pageNumber=1"
           "&sortColumns=DATE&sortTypes=-1")
    data = fetch_json(url, referer="https://data.eastmoney.com/")
    rows = []
    for item in ((data.get("result") or {}).get("data") or []):
        rows.append({
            "date": (item.get("DATE") or "")[:10],
            "close": item.get("CLOSE"),
            "change_pct": item.get("CHANGE_RATE"),
            "financing_balance": item.get("RZYE"),
            "financing_buy": item.get("RZMRE"),
            "short_balance": item.get("RQYE"),
            "total_balance": item.get("RZRQYE"),
        })
    return {"source": "datacenter-web.eastmoney.com", "symbol": normalize(code),
            "count": len(rows), "fetched_at": now_cst(), "margin": rows}


def sector(count: int = 10) -> dict:
    """
    Industry-sector ranking by change — the rotation view.

    Tencent is the primary source, not Eastmoney: Eastmoney's `clist` endpoint
    starts answering `RemoteDisconnected` after a burst of requests and stays
    that way for a while (verified — `kamt` on the same host kept working), so it
    is unusable as a member's routine call. Eastmoney remains the fallback.

    `data.diff` also comes back as a **list** on some Eastmoney responses and a
    **dict** on others; both shapes are accepted, because assuming one crashed
    with `'list' object has no attribute 'values'`.
    """
    n = max(1, min(int(count), 100))
    try:
        # `sort_type=price` is the accepted name for the change-percent ranking;
        # `zdf` / `hsl` are rejected with `参数错误:sort_type error`. Note this API
        # answers HTTP 200 even for a parameter error, so the payload's `code`
        # must be checked — a status-code check alone would pass a broken call.
        url = ("https://proxy.finance.qq.com/cgi/cgi-bin/rank/pt/getRank"
               f"?board_type=hy&sort_type=price&direct=down&offset=0&count={n}")
        data = fetch_json(url, referer="https://gu.qq.com/")
        if data.get("code") not in (0, None):
            raise RuntimeError(f"Tencent sector error: {data.get('msg')}")
        rows = []
        for item in ((data.get("data") or {}).get("rank_list") or []):
            leader = item.get("lzg") or {}
            rows.append({
                "code": item.get("code"), "name": item.get("name"),
                "change_pct": _num(item.get("zdf")),
                "turnover": _num(item.get("turnover")),
                "leader": leader.get("name"), "leader_code": leader.get("code"),
                "leader_change_pct": _num(leader.get("zdf")),
            })
        if rows:
            return {"source": "proxy.finance.qq.com", "count": len(rows),
                    "fetched_at": now_cst(), "sectors": rows}
    except Exception as exc:                         # noqa: BLE001 - fall through
        log(f"[wbdata] Tencent sector failed, falling back to Eastmoney: {exc}")

    url = ("https://push2.eastmoney.com/api/qt/clist/get"
           f"?pn=1&pz={n}&po=1&np=1&fltt=2&invt=2"
           "&fid=f3&fs=m:90+t:2&fields=f12,f14,f2,f3,f62,f104,f105,f128,f140")
    data = fetch_json(url, referer="https://quote.eastmoney.com/")
    diff = ((data.get("data") or {}).get("diff")) or []
    items = list(diff.values()) if isinstance(diff, dict) else list(diff)
    rows = []
    for item in items:
        if not isinstance(item, dict):
            continue
        rows.append({
            "code": item.get("f12"), "name": item.get("f14"),
            "change_pct": item.get("f3"), "main_net_inflow": item.get("f62"),
            "up_count": item.get("f104"), "down_count": item.get("f105"),
            "leader": item.get("f128"),
        })
    return {"source": "push2.eastmoney.com", "count": len(rows),
            "fetched_at": now_cst(), "sectors": rows}


def northbound() -> dict:
    """
    Stock-Connect (northbound) flow — foreign appetite for A-shares.

    The live field is `dayNetAmtIn` (10k CNY), not `netBuyAmt`. `status: 4` means
    the exchange published the day's aggregate without a per-minute breakdown, so
    the value can legitimately be 0.0 — that is reported as-is rather than
    dressed up as a real flow.
    """
    url = ("https://push2.eastmoney.com/api/qt/kamt/get"
           "?fields1=f1,f2,f3,f4&fields2=f51,f52,f53,f54,f55,f56")
    data = fetch_json(url, referer="https://data.eastmoney.com/")
    out = {}
    for key in ("hk2sh", "hk2sz", "sh2hk", "sz2hk"):
        node = (data.get("data") or {}).get(key)
        if isinstance(node, dict):
            out[key] = {
                "status": node.get("status"),
                "net_flow_wan": node.get("dayNetAmtIn"),
                "quota_remain_wan": node.get("dayAmtRemain"),
                "quota_total_wan": node.get("dayAmtThreshold"),
                "day": node.get("date2") or node.get("date"),
            }
    return {"source": "push2.eastmoney.com", "fetched_at": now_cst(),
            "northbound": out,
            "note": ("hk2sh/hk2sz = northbound into Shanghai/Shenzhen; "
                     "sh2hk/sz2hk = southbound. net_flow_wan is in 10k CNY. "
                     "status 4 = aggregate only, no intraday breakdown.")}


# --------------------------------------------------------------------------
# Valuation history, shareholder returns, positioning
# --------------------------------------------------------------------------

def valuation(code: str, count: int = 250) -> dict:
    """
    Valuation history with the percentile a member actually needs.

    Raw PE/PB is not decision-useful on its own — "PE 19.3" means nothing without
    knowing where that sits in the name's own history. This returns the series and
    computes the percentile of the latest value within the window, which is the
    number a valuation member quotes.
    """
    n = max(2, min(int(count), 1000))
    filt = urllib.parse.quote(f'(SECURITY_CODE="{eastmoney_plain(code)}")')
    url = ("https://datacenter-web.eastmoney.com/api/data/v1/get"
           "?reportName=RPT_VALUEANALYSIS_DET&columns=ALL"
           f"&filter={filt}&pageSize={n}&pageNumber=1"
           "&sortColumns=TRADE_DATE&sortTypes=-1")
    data = fetch_json(url, referer="https://data.eastmoney.com/")
    rows = []
    for item in ((data.get("result") or {}).get("data") or []):
        rows.append({
            "date": (item.get("TRADE_DATE") or "")[:10],
            "close": item.get("CLOSE_PRICE"),
            "pe_ttm": item.get("PE_TTM"),
            "pb_mrq": item.get("PB_MRQ"),
            "ps_ttm": item.get("PS_TTM"),
            "peg": item.get("PEG_CAR"),
            "pcf_ocf_ttm": item.get("PCF_OCF_TTM"),
            "total_cap": item.get("TOTAL_MARKET_CAP"),
        })

    def pct(field):
        """Percentile of the newest value within the window (0-100)."""
        vals = [r[field] for r in rows if isinstance(r.get(field), (int, float))]
        if len(vals) < 2:
            return None
        latest = vals[0]
        below = sum(1 for v in vals if v <= latest)
        return round(below / len(vals) * 100, 1)

    return {
        "source": "datacenter-web.eastmoney.com", "symbol": normalize(code),
        "window": len(rows), "fetched_at": now_cst(),
        "latest": rows[0] if rows else None,
        "percentile_in_window": {
            "pe_ttm": pct("pe_ttm"), "pb_mrq": pct("pb_mrq"), "ps_ttm": pct("ps_ttm"),
        },
        "note": ("percentile_in_window = share of the fetched window at or below the "
                 "latest value; 20 means cheaper than 80% of the window. Window size "
                 "is `window`, newest first."),
        "history": rows,
    }


def dividend(code: str, count: int = 20) -> dict:
    """
    Dividend / bonus-share history and the trailing cash yield.

    The newest row is often a **pre-disclosure** (预披露) with no cash figure yet,
    so `cash_per_10` is legitimately null there and the trailing yield is summed
    over implemented rows only. Reporting null as "no dividend" would be wrong;
    `progress` is carried through so a caller can tell the two apart.
    """
    n = max(1, min(int(count), 50))
    filt = urllib.parse.quote(f'(SECURITY_CODE="{eastmoney_plain(code)}")')
    url = ("https://datacenter-web.eastmoney.com/api/data/v1/get"
           "?reportName=RPT_SHAREBONUS_DET&columns=ALL"
           f"&filter={filt}&pageSize={n}&pageNumber=1"
           "&sortColumns=REPORT_DATE&sortTypes=-1")
    data = fetch_json(url, referer="https://data.eastmoney.com/")
    rows = []
    for item in ((data.get("result") or {}).get("data") or []):
        rows.append({
            "report_date": (item.get("REPORT_DATE") or "")[:10],
            "progress": item.get("ASSIGN_PROGRESS"),
            "plan": item.get("IMPL_PLAN_PROFILE"),
            "cash_per_10": item.get("PRETAX_BONUS_RMB"),
            "ex_dividend_date": (item.get("EX_DIVIDEND_DATE") or "")[:10],
            "record_date": (item.get("EQUITY_RECORD_DATE") or "")[:10],
            "notice_date": (item.get("PLAN_NOTICE_DATE") or "")[:10],
        })

    # Trailing cash yield over the last four implemented payouts, priced against
    # the live quote — a yield computed off a stale price is not usable.
    trailing = None
    price = None
    try:
        q = quote([code])["quotes"]
        if q:
            price = q[0].get("price")
    except Exception:                                # noqa: BLE001 - yield is optional
        price = None
    pays = [r["cash_per_10"] for r in rows
            if r.get("cash_per_10") and r.get("progress") == "实施分配"][:4]
    if pays and price:
        trailing = round(sum(pays) / 10 / price * 100, 2)

    return {"source": "datacenter-web.eastmoney.com", "symbol": normalize(code),
            "count": len(rows), "fetched_at": now_cst(),
            "trailing_4_payout_yield_pct": trailing, "price_used": price,
            "dividends": rows,
            "note": ("cash_per_10 is pre-tax CNY per 10 shares. A null value on the "
                     "newest row usually means the plan is still 预披露 (pre-disclosure), "
                     "not that the company skipped the dividend — check `progress`.")}


def holders(code: str, count: int = 10) -> dict:
    """
    Top free-float holders — who owns the float and whether they are adding.

    `IS_HOLDORG` distinguishes institutions from individuals; `HOLD_NUM_CHANGE`
    is the quarter-over-quarter share change, which is the positioning signal.
    """
    sec = f"{eastmoney_plain(code)}.{'SH' if normalize(code).startswith('sh') else 'SZ'}"
    n = max(1, min(int(count), 50))
    filt = urllib.parse.quote(f'(SECUCODE="{sec}")')
    url = ("https://datacenter-web.eastmoney.com/api/data/v1/get"
           "?reportName=RPT_F10_EH_FREEHOLDERS&columns=ALL"
           f"&filter={filt}&pageSize={n}&pageNumber=1"
           "&sortColumns=END_DATE,HOLDER_RANK&sortTypes=-1,1")
    data = fetch_json(url, referer="https://data.eastmoney.com/")
    rows = []
    for item in ((data.get("result") or {}).get("data") or []):
        rows.append({
            "period": (item.get("END_DATE") or "")[:10],
            "rank": item.get("HOLDER_RANK"),
            "holder": item.get("HOLDER_NAME"),
            "shares": item.get("HOLD_NUM"),
            "float_pct": item.get("FREE_HOLDNUM_RATIO"),
            "share_change": item.get("HOLD_NUM_CHANGE"),
            "change_pct": item.get("CHANGE_RATIO"),
            "is_institution": item.get("IS_HOLDORG"),
        })
    return {"source": "datacenter-web.eastmoney.com", "symbol": normalize(code),
            "count": len(rows), "fetched_at": now_cst(), "holders": rows}


# --------------------------------------------------------------------------
# Market breadth, macro, indices
# --------------------------------------------------------------------------

def _pool_price(raw):
    """
    Decode the limit-up/down pool's fixed-point price.

    The upstream emits a scaled integer, and the scale is **1000, not 100** —
    verified by cross-checking the pool against live quotes: 紫竹高科 appears as
    `p=20200` and trades at 20.20, 九阳股份 as `12500` at 12.50. Dividing by 100
    yields 202.0 / 125.0, a silent 10x error that would corrupt every price level
    in a report.
    """
    try:
        return round(float(raw) / 1000, 3)
    except (TypeError, ValueError):
        return None


def limitup(date: str | None = None, count: int = 20) -> dict:
    """
    Limit-up pool with the consecutive-board count and the sealing time.

    `lbc` = consecutive limit-up boards, `fbt` = first seal time as HHMMSS, `zbc`
    = number of times the board broke. Together these are the 短线 strength read.
    """
    day = (date or datetime.now(CST).strftime("%Y%m%d")).replace("-", "")
    n = max(1, min(int(count), 100))
    url = ("https://push2ex.eastmoney.com/getTopicZTPool"
           "?ut=7eea3edcaed734bea9cbfc24409ed989&dpt=wz.ztzt"
           f"&Pageindex=0&pagesize={n}&sort=fbt%3Aasc&date={day}")
    data = fetch_json(url, referer="https://quote.eastmoney.com/")
    pool = ((data.get("data") or {}).get("pool")) or []
    rows = []
    for item in pool:
        rows.append({
            "code": item.get("c"), "name": item.get("n"),
            "price": _pool_price(item.get("p")),
            "change_pct": item.get("zdp"),
            "consecutive_boards": item.get("lbc"),
            "first_seal": _hhmmss(item.get("fbt")),
            "last_seal": _hhmmss(item.get("lbt")),
            "break_count": item.get("zbc"),
            "turnover_pct": item.get("hs"),
            "sector": item.get("hybk"),
            "seal_amount": item.get("fund"),
        })
    return {"source": "push2ex.eastmoney.com", "date": day, "count": len(rows),
            "total": (data.get("data") or {}).get("tc"),
            "fetched_at": now_cst(), "limit_up": rows}


def limitdown(date: str | None = None, count: int = 20) -> dict:
    """Limit-down pool — the mirror of `limitup`, for breadth context."""
    day = (date or datetime.now(CST).strftime("%Y%m%d")).replace("-", "")
    n = max(1, min(int(count), 100))
    url = ("https://push2ex.eastmoney.com/getTopicDTPool"
           "?ut=7eea3edcaed734bea9cbfc24409ed989&dpt=wz.ztzt"
           f"&Pageindex=0&pagesize={n}&sort=fund%3Aasc&date={day}")
    data = fetch_json(url, referer="https://quote.eastmoney.com/")
    pool = ((data.get("data") or {}).get("pool")) or []
    rows = []
    for item in pool:
        rows.append({
            "code": item.get("c"), "name": item.get("n"),
            "price": _pool_price(item.get("p")),
            "change_pct": item.get("zdp"),
            "turnover_pct": item.get("hs"),
            "sector": item.get("hybk"),
            "days_boards": item.get("days"),
        })
    return {"source": "push2ex.eastmoney.com", "date": day, "count": len(rows),
            "total": (data.get("data") or {}).get("tc"),
            "fetched_at": now_cst(), "limit_down": rows}


# Only report names **verified to return rows** are listed. Guessed names that
# happen to look plausible (`RPT_ECONOMY_LPR`, `RPT_ECONOMY_GDPSORT`, …) answer
# `报表配置不存在` and would otherwise surface as a silent zero-row series that
# reads like "nothing was published this period".
_ECONOMY = {
    "gdp": ("RPT_ECONOMY_GDP", "国内生产总值"),
    "cpi": ("RPT_ECONOMY_CPI", "居民消费价格指数"),
    "ppi": ("RPT_ECONOMY_PPI", "工业生产者出厂价格指数"),
    "pmi": ("RPT_ECONOMY_PMI", "采购经理指数"),
    "money": ("RPT_ECONOMY_CURRENCY_SUPPLY", "货币供应量"),
    "retail": ("RPT_ECONOMY_TOTAL_RETAIL", "社会消费品零售总额"),
}

# Report names that look plausible but do **not** exist upstream. They are listed
# so a caller asking for one gets an explicit "not available" instead of a silent
# zero-row result that reads like "no data was published".
_ECONOMY_ABSENT = {
    "lpr": "LPR 未在 datacenter 宏观库中提供（报表配置不存在）；利率请取央行公告原文",
    "social": "社融未在 datacenter 宏观库中提供；请取央行社会融资规模增量统计表",
    "unemployment": "城镇调查失业率未在 datacenter 宏观库中提供；请取国家统计局月度数据",
}


def macro(kind: str = "all", count: int = 6) -> dict:
    """
    Macro series used by the top-down members.

    Each report is fetched independently so one unavailable series degrades to an
    error entry instead of losing the whole macro picture. A series that does not
    exist upstream is reported as `unavailable` with a pointer to where the number
    actually lives — an empty list would read as "published nothing this period",
    which is a different and misleading claim.
    """
    if kind == "all":
        kinds = list(_ECONOMY)
        asked_absent = dict(_ECONOMY_ABSENT)
    elif kind in _ECONOMY_ABSENT:
        kinds, asked_absent = [], {kind: _ECONOMY_ABSENT[kind]}
    else:
        kinds, asked_absent = [kind], {}
    unknown = [k for k in kinds if k not in _ECONOMY]
    if unknown:
        raise ValueError(
            f"unknown macro series {unknown}; choose from "
            f"{sorted(list(_ECONOMY) + list(_ECONOMY_ABSENT))}")

    out = {}
    for key in kinds:
        report, label = _ECONOMY[key]
        url = ("https://datacenter-web.eastmoney.com/api/data/v1/get"
               f"?reportName={report}&columns=ALL"
               f"&pageSize={max(1, min(int(count), 30))}&pageNumber=1"
               "&sortColumns=REPORT_DATE&sortTypes=-1")
        try:
            data = fetch_json(url, referer="https://data.eastmoney.com/")
            if data.get("success") is False:
                out[key] = {"label": label, "unavailable": data.get("message")}
                continue
            rows = ((data.get("result") or {}).get("data")) or []
            out[key] = {"label": label, "periods": len(rows), "data": rows}
        except Exception as exc:                     # noqa: BLE001
            out[key] = {"label": label, "error": f"{type(exc).__name__}: {exc}"}
            log(f"[wbdata] macro {key} failed: {exc}")
    for key, why in asked_absent.items():
        out[key] = {"unavailable": why}
    return {"source": "datacenter-web.eastmoney.com", "fetched_at": now_cst(),
            "macro": out}


_INDEX = {
    "sh": "1.000001", "sz": "0.399001", "cyb": "0.399006",
    "hs300": "1.000300", "sz50": "1.000016", "zz500": "1.000905",
    "zz1000": "1.000852", "kc50": "1.000688",
}

# The same headline indices in Tencent symbol form, used by the primary path.
_INDEX_TX = {
    "sh": "sh000001", "sz": "sz399001", "cyb": "sz399006",
    "hs300": "sh000300", "sz50": "sh000016", "zz500": "sh000905",
    "zz1000": "sh000852", "kc50": "sh000688",
}


def indices(limit: int = 8) -> dict:
    """
    Headline index snapshot — the market-context line of a report.

    Tencent is primary because Eastmoney's `push2` host intermittently answers
    `RemoteDisconnected` (the same instability that forced `sector` off it), and a
    market-context line is fetched on nearly every run. Eastmoney is the fallback.
    """
    keys = list(_INDEX)[:max(1, min(int(limit), len(_INDEX)))]

    try:
        out = quote([_INDEX_TX[k] for k in keys if k in _INDEX_TX])["quotes"]
        if out:
            return {"source": "qt.gtimg.cn", "count": len(out),
                    "fetched_at": now_cst(), "indices": out}
    except Exception as exc:                         # noqa: BLE001 - fall through
        log(f"[wbdata] Tencent indices failed, falling back to Eastmoney: {exc}")

    secids = ",".join(_INDEX[k] for k in keys)
    url = ("https://push2.eastmoney.com/api/qt/ulist.np/get"
           f"?fltt=2&secids={secids}&fields=f2,f3,f4,f12,f14,f6")
    data = fetch_json(url, referer="https://quote.eastmoney.com/")
    diff = ((data.get("data") or {}).get("diff")) or []
    rows = list(diff.values()) if isinstance(diff, dict) else list(diff)
    out = []
    for key, item in zip(keys, rows):
        if not isinstance(item, dict):
            continue
        out.append({
            "key": key, "code": item.get("f12"), "name": item.get("f14"),
            "price": item.get("f2"), "change_pct": item.get("f3"),
            "change": item.get("f4"), "turnover": item.get("f6"),
        })
    return {"source": "push2.eastmoney.com", "count": len(out),
            "fetched_at": now_cst(), "indices": out}


def _hhmmss(value):
    """Convert the upstream's HHMMSS integer (92500) to `09:25:00`."""
    if value is None:
        return None
    try:
        s = f"{int(value):06d}"
    except (TypeError, ValueError):
        return None
    return f"{s[0:2]}:{s[2:4]}:{s[4:6]}"


# --------------------------------------------------------------------------
# Aggregate
# --------------------------------------------------------------------------

def snapshot(code: str, count: int = 60, full: bool = False) -> dict:
    """
    Everything one member needs about one ticker, in a single call.

    Each section is fetched independently, so one dead upstream degrades that
    section to an `error` string instead of failing the whole snapshot.

    `full` adds the slower sections (valuation history, dividends, holders,
    margin, limit-up breadth). They are off by default because they cost extra
    round trips and a member's turn budget is the scarcest resource in a run.
    """
    sections = [
        ("quote", lambda: quote([code])),
        ("kline", lambda: kline(code, "day", count)),
        ("financials", lambda: financials(code)),
        ("announcements", lambda: announcements(code, 8)),
        ("research", lambda: research(code, 8)),
        ("fundflow", lambda: fundflow(code)),
    ]
    if full:
        sections += [
            ("valuation", lambda: valuation(code)),
            ("dividend", lambda: dividend(code, 10)),
            ("holders", lambda: holders(code, 10)),
            ("margin", lambda: margin(code, 6)),
        ]
    out = {"symbol": normalize(code), "fetched_at": now_cst()}
    for key, fn in sections:
        try:
            out[key] = fn()
        except Exception as exc:                     # noqa: BLE001 - report, never raise
            out[key] = {"error": f"{type(exc).__name__}: {exc}"}
            log(f"[wbdata] section {key} failed: {exc}")
    return out


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def main() -> int:
    p = argparse.ArgumentParser(
        prog="wbdata",
        description="Zero-config real-time market data (no API key, no token).",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("quote", help="real-time snapshot, one or more symbols")
    s.add_argument("codes", nargs="+")

    s = sub.add_parser("kline", help="OHLCV history")
    s.add_argument("code")
    s.add_argument("--period", default="day", choices=sorted(_PERIOD))
    s.add_argument("--count", type=int, default=120)
    s.add_argument("--adjust", default="qfq", choices=["qfq", "hfq", ""])

    s = sub.add_parser("minute", help="intraday 5-minute bars")
    s.add_argument("code")

    s = sub.add_parser("financials", help="main financial indicators, multi-period")
    s.add_argument("code")

    s = sub.add_parser("announcements", help="company filings")
    s.add_argument("code")
    s.add_argument("--count", type=int, default=10)

    s = sub.add_parser("research", help="sell-side analyst reports")
    s.add_argument("code")
    s.add_argument("--count", type=int, default=10)

    s = sub.add_parser("fundflow", help="order-size capital flow")
    s.add_argument("code")

    s = sub.add_parser("billboard", help="daily 龙虎榜")
    s.add_argument("--count", type=int, default=10)

    s = sub.add_parser("margin", help="margin-trading balance")
    s.add_argument("code")
    s.add_argument("--count", type=int, default=10)

    s = sub.add_parser("sector", help="industry-sector ranking")
    s.add_argument("--count", type=int, default=10)

    sub.add_parser("northbound", help="Stock-Connect net flow")

    s = sub.add_parser("valuation", help="PE/PB history plus percentile in window")
    s.add_argument("code")
    s.add_argument("--count", type=int, default=250)

    s = sub.add_parser("dividend", help="dividend and bonus-share history")
    s.add_argument("code")
    s.add_argument("--count", type=int, default=20)

    s = sub.add_parser("holders", help="top free-float holders")
    s.add_argument("code")
    s.add_argument("--count", type=int, default=10)

    s = sub.add_parser("limitup", help="limit-up pool with board count")
    s.add_argument("--date", default=None, help="YYYYMMDD or YYYY-MM-DD; default today")
    s.add_argument("--count", type=int, default=20)

    s = sub.add_parser("limitdown", help="limit-down pool")
    s.add_argument("--date", default=None, help="YYYYMMDD or YYYY-MM-DD; default today")
    s.add_argument("--count", type=int, default=20)

    s = sub.add_parser("macro", help="macro series: gdp/cpi/ppi/pmi/lpr/money/social/unemployment")
    s.add_argument("--kind", default="all")
    s.add_argument("--count", type=int, default=6)

    s = sub.add_parser("indices", help="headline index snapshot")
    s.add_argument("--limit", type=int, default=8)

    s = sub.add_parser("snapshot", help="all sections for one symbol")
    s.add_argument("code")
    s.add_argument("--count", type=int, default=60)
    s.add_argument("--full", action="store_true",
                   help="also fetch valuation/dividend/holders/margin (slower)")

    args = p.parse_args()
    try:
        if args.cmd == "quote":
            payload = quote(args.codes)
        elif args.cmd == "kline":
            payload = kline(args.code, args.period, args.count, args.adjust)
        elif args.cmd == "minute":
            payload = minute(args.code)
        elif args.cmd == "financials":
            payload = financials(args.code)
        elif args.cmd == "announcements":
            payload = announcements(args.code, args.count)
        elif args.cmd == "research":
            payload = research(args.code, args.count)
        elif args.cmd == "fundflow":
            payload = fundflow(args.code)
        elif args.cmd == "billboard":
            payload = billboard(args.count)
        elif args.cmd == "margin":
            payload = margin(args.code, args.count)
        elif args.cmd == "sector":
            payload = sector(args.count)
        elif args.cmd == "northbound":
            payload = northbound()
        elif args.cmd == "valuation":
            payload = valuation(args.code, args.count)
        elif args.cmd == "dividend":
            payload = dividend(args.code, args.count)
        elif args.cmd == "holders":
            payload = holders(args.code, args.count)
        elif args.cmd == "limitup":
            payload = limitup(args.date, args.count)
        elif args.cmd == "limitdown":
            payload = limitdown(args.date, args.count)
        elif args.cmd == "macro":
            payload = macro(args.kind, args.count)
        elif args.cmd == "indices":
            payload = indices(args.limit)
        elif args.cmd == "snapshot":
            payload = snapshot(args.code, args.count, args.full)
        else:                                        # pragma: no cover
            p.error(f"unknown command {args.cmd}")
            return 2
    except urllib.error.HTTPError as exc:
        # A structured failure the caller can paste into a report as a gap.
        print(json.dumps({"error": f"HTTP {exc.code}", "url": exc.url,
                          "fetched_at": now_cst()}, ensure_ascii=False, indent=1))
        return 1
    except Exception as exc:                         # noqa: BLE001
        print(json.dumps({"error": f"{type(exc).__name__}: {exc}",
                          "fetched_at": now_cst()}, ensure_ascii=False, indent=1))
        return 1

    print(json.dumps(payload, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
