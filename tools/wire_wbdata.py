#!/usr/bin/env python3
"""
Rewrite the data-acquisition guidance in every member brief.

Why
---
The briefs originally told members to "use `web_fetch` / `web_search`". On this
deployment `web_search` is unavailable, and scraping quote pages through
`web_fetch` is slow and lossy — the model ends up reading HTML and guessing at
numbers. `wbdata.py` returns structured JSON from keyless public APIs.

Guidance is **team-aware**, because the four teams do not need the same data:

* `trading-team` / `stock-partner-team` — securities analysis. Full command set:
  quotes, valuation, capital flow, breadth, macro.
* `gpt-researcher-team` — general research that only touches listed companies
  sometimes. Securities commands are offered as a conditional subset.
* `product-strategy-team` — a *product* team. It researches competitor websites,
  pricing pages and app stores. Handing it A-share commands would be wrong
  guidance, so it keeps a web-research section and only gets a pointer for the
  case where a competitor happens to be listed.

What it replaces
----------------
A block starting `## 数据获取` up to the next level-2 heading. That covers the
original `port_teams.py` block and every earlier revision of this one, so
re-running upgrades in place instead of appending a second section.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent / "teams"

SECURITIES_FULL = """## 数据获取

**首选 `wbdata.py`** —— 零配置实时行情/财务/公告接口，**不需要任何 API key 或 token**。
它在团队目录的 `scripts/` 下，用绝对路径调用：

```bash
# —— 行情与量价（技术面 / 短线）——
python3 <团队目录>/scripts/wbdata.py quote 600519 hk00700 usAAPL   # A/港/美一次批量
python3 <团队目录>/scripts/wbdata.py kline 600519 --period day --count 250
python3 <团队目录>/scripts/wbdata.py minute 600519                 # 5 分钟线
python3 <团队目录>/scripts/wbdata.py indices                       # 大盘指数

# —— 基本面与估值 ——
python3 <团队目录>/scripts/wbdata.py financials 600519             # 多期财务指标
python3 <团队目录>/scripts/wbdata.py valuation 600519 --count 250  # PE/PB + 历史分位
python3 <团队目录>/scripts/wbdata.py dividend 600519               # 分红史 + 近4次股息率
python3 <团队目录>/scripts/wbdata.py holders 600519                # 十大流通股东

# —— 消息面与资金面 ——
python3 <团队目录>/scripts/wbdata.py announcements 600519          # 公司公告
python3 <团队目录>/scripts/wbdata.py research 600519               # 券商研报
python3 <团队目录>/scripts/wbdata.py fundflow 600519               # 超大/大/中/小单
python3 <团队目录>/scripts/wbdata.py margin 600519                 # 融资融券
python3 <团队目录>/scripts/wbdata.py northbound                    # 北向资金

# —— 市场情绪与广度（短线 / 主线）——
python3 <团队目录>/scripts/wbdata.py limitup --count 30            # 涨停池+连板数
python3 <团队目录>/scripts/wbdata.py limitdown --count 30          # 跌停池
python3 <团队目录>/scripts/wbdata.py sector --count 10             # 板块轮动
python3 <团队目录>/scripts/wbdata.py billboard                     # 龙虎榜

# —— 宏观（自上而下）——
python3 <团队目录>/scripts/wbdata.py macro --kind gdp              # gdp/cpi/ppi/pmi/money/retail

# —— 一次拿全（推荐起步）——
python3 <团队目录>/scripts/wbdata.py snapshot 600519               # 6 个核心板块
python3 <团队目录>/scripts/wbdata.py snapshot 600519 --full        # 再加估值/分红/股东/两融
```

输出是 JSON，含 `source` 与 `fetched_at`。**报告里引用的每个数字都要带上这个
`fetched_at` 时间点**——行情没有时间点就无法用于交易判断。

`valuation` 直接给出 `percentile_in_window`（当前值在该窗口的分位），引用「贵/便宜」时
用它，不要凭感觉说高低。`dividend` 的 `trailing_4_payout_yield_pct` 是近四次已实施分红的
滚动股息率。

> 已知缺口：LPR / 社融 / 失业率**不在** datacenter 宏观库里，接口会返回 `unavailable`
> 并说明去哪里取（央行公告 / 统计局）。**不要**因为拿不到就编一个数。

**兜底工具**（仅当 wbdata.py 未覆盖该字段时）：

- `web_fetch` — 打开具体页面读原文（交易所公告、公司财报页、权威财经媒体）
- `web_search` — **本部署不可用**（无搜索密钥），不要依赖它
- `bash` — 需要计算时使用；解释器是 `python3`，**没有** `python` 命令

数据纪律（违反即视为报告无效）：

- 每个关键数字都要能追溯到具体来源，并给出 `fetched_at` / 公告日期
- 拿不到的数据必须显式写「未获取到」，**禁止**编造、估算后当作事实
- 多个来源冲突时同时列出，并说明你采信哪一个、为什么
- 历史归历史、实时归实时：讲「当前」必须用实时接口，不能用记忆里的数字
"""

SECURITIES_SUBSET = """## 数据获取

你的课题大多与上市公司无关，用 `web_fetch` 打开权威来源**原文**即可
（机构报告、政府与行业协会官网、论文与公开数据页）。

**当课题涉及上市公司 / 行情 / 行业数据时**，优先用 `wbdata.py` ——
零配置、免密钥、直接返回结构化 JSON，比抓网页可靠得多。它在团队目录的 `scripts/` 下：

```bash
python3 <团队目录>/scripts/wbdata.py quote 600519          # 实时行情
python3 <团队目录>/scripts/wbdata.py financials 600519     # 多期财务指标
python3 <团队目录>/scripts/wbdata.py valuation 600519      # PE/PB + 历史分位
python3 <团队目录>/scripts/wbdata.py announcements 600519  # 公司公告
python3 <团队目录>/scripts/wbdata.py research 600519       # 券商研报
python3 <团队目录>/scripts/wbdata.py sector --count 10     # 板块轮动
python3 <团队目录>/scripts/wbdata.py snapshot 600519       # 一次拿全
```

`web_search` 在本部署**不可用**（无搜索密钥），**不要依赖它**；
需要关键词发现时用 `web_fetch` 直取已知的权威站点。
解释器是 `python3`，**没有** `python` 命令。

数据纪律（违反即视为报告无效）：

- 每个关键数字都要能追溯到具体来源，并给出 `fetched_at` / 发布日期
- 拿不到的数据必须显式写「未获取到」，**禁止**编造市场规模、用户量或竞品功能
- **区分证据与假设**：标明哪些结论有数据支撑、哪些是待验证假设
- 多个来源冲突时同时列出，并说明你采信哪一个、为什么
"""

WEB_RESEARCH = """## 数据获取

你的数据来源是**公开网页**，不是证券市场接口。用当前会话实际可用的工具：

- `web_fetch` — 打开具体页面读**原文**：竞品官网、产品文档、定价页、应用商店页、
  更新日志（changelog）、公开的行业报告
- `web_search` — **本部署不可用**（无搜索密钥），**不要依赖它**；
  需要关键词发现时用 `web_fetch` 直取已知站点与其站内检索页
- `bash` — 需要计算或整理数据时使用；解释器是 `python3`，**没有** `python` 命令

例外：如果竞品**恰好是上市公司**、且你需要它的营收/估值作为规模参照，可以用
`python3 <团队目录>/scripts/wbdata.py snapshot <代码>` 取结构化财务数据
（零配置、免密钥）。这是可选补充，不是主要手段。

数据纪律（违反即视为产出无效）：

- 竞品功能必须来自**可核验的公开来源**（官网/文档/定价页/更新日志），并给出链接与获取时间
- **禁止编造**竞品的用户量、收入、市占率、市场规模；拿不到就写「未获取到」
- **区分证据与假设**：标明哪些结论有数据支撑、哪些是待验证假设
- 区分「竞品声称」与「你实测/文档确认」——营销话术不能当事实
"""

# Team → which data section it gets. A team absent from this map keeps whatever
# section it already has, so an unlisted team is never silently emptied.
SECTIONS = {
    "trading-team": SECURITIES_FULL,
    "stock-partner-team": SECURITIES_FULL,
    "gpt-researcher-team": SECURITIES_SUBSET,
    "product-strategy-team": WEB_RESEARCH,
}

# The data-acquisition section, in any shape this tool or `port_teams.py` wrote.
# `## 检索工具使用` is the heading the research team's brief was ported with, so
# both spellings are matched and both are replaced by the same canonical section —
# otherwise the two drift apart and only one of them gets future updates.
_OLD_SECTION = re.compile(
    r"^## (?:数据获取|检索工具使用)\s*$.*?(?=^## |\Z)", re.S | re.M)

# Inline wording from the original `port_team.py` header and older briefs.
_INLINE = [
    (re.compile(r"成员必须用 `web_fetch` 取公开数据（`web_search` 在本部署不可用）"),
     "成员必须用 `scripts/wbdata.py` 取数（零配置、免密钥）；它没覆盖的字段再用 `web_fetch`"),
    (re.compile(r"用 `web_fetch` 取公开数据（`web_search` 在本部署不可用）"),
     "用 `scripts/wbdata.py` 取数（零配置、免密钥），未覆盖的字段再用 `web_fetch`"),
    (re.compile(r"用 web_fetch 取公开数据（web_search 在本部署不可用）"),
     "用 scripts/wbdata.py 取数（零配置、免密钥），未覆盖的字段再用 web_fetch"),
    (re.compile(r"本会话\*\*没有\*\* WorkBuddy 的检索栈。成员用 `web_fetch` / `web_search` / `bash`"),
     "成员首选 `scripts/wbdata.py`（零配置免密钥），未覆盖的字段用 `web_fetch` / `bash`"),
    (re.compile(r"本会话没有 WorkBuddy 的检索栈。成员用 `web_fetch` / `web_search` / `bash`"),
     "成员首选 `scripts/wbdata.py`（零配置免密钥），未覆盖的字段用 `web_fetch` / `bash`"),
]


def rewrite(path: Path, section: str) -> tuple[bool, list[str]]:
    original = path.read_text(encoding="utf-8")
    text = original
    notes = []

    if _OLD_SECTION.search(text):
        text = _OLD_SECTION.sub(section + "\n", text, count=1)
        notes.append("section")

    for pattern, repl in _INLINE:
        text, n = pattern.subn(repl, text)
        if n:
            notes.append(f"inline×{n}")

    if text != original:
        path.write_text(text, encoding="utf-8")
        return True, notes
    return False, notes


def main() -> None:
    changed = skipped = unknown = 0
    for path in sorted(ROOT.glob("*/members/*.md")):
        team = path.parent.parent.name
        section = SECTIONS.get(team)
        if section is None:
            # An unmapped team is left untouched rather than guessed at: writing
            # securities guidance into a non-finance team is worse than writing
            # nothing.
            unknown += 1
            continue
        did, notes = rewrite(path, section)
        if did:
            changed += 1
            print(f"  updated  {team}/{path.name:28} {', '.join(notes)}")
        else:
            skipped += 1
    print(f"\n{changed} briefs updated, {skipped} already current"
          + (f", {unknown} in unmapped teams left alone" if unknown else ""))


if __name__ == "__main__":
    main()
