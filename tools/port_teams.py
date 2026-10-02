#!/usr/bin/env python3
"""
Port WorkBuddy expert teams into DSH team definitions.

Three transformations per member brief, so the specialist instructions themselves
survive verbatim:

1. Strip the WorkBuddy frontmatter and prepend a DSH teammate header naming the
   member's `spawn_teammate` id and its handoff marker.
2. Replace the sections that tell the member to use WorkBuddy-only data channels
   (`westock-mcp` connector, `neodata-financial-search`) with the tools DSH
   actually has. Left in place, every member would fail on a missing connector.
3. Rewrite surviving WorkBuddy-only mentions so no brief points at a missing tool.

`product-strategy-team` is NOT handled here: its expert package was never
downloaded to this machine (only a catalog entry exists), so it has no source
briefs to port and its members are authored from the catalog description instead.
"""

import re
from pathlib import Path

HOME = Path.home()
OUT = Path(__file__).resolve().parent.parent / "teams"

HEADER = """# {zh}（{en}）

你是本团队的 **{zh}**，由主理人以 teammate 身份 spawn，名字是 `{member}`。

**职责边界**：只产出你自己的专业结论。不要替其他成员发言，不要越权调度别人，
不要重写别人的报告。主理人负责编排与汇编。

**协作规则**：

- 你与主理人、其他成员**共享同一个工作目录**，你的文件改动对所有人立即可见。
- 完成后必须用 `send_message` 把**完整产出正文**发给 `lead`；只发一句状态等于没交付。
- 产出最后一行必须是产出标记 `{marker}`，主理人靠它识别和转交。
- 如果主理人给你的输入缺了必需的报告，直接说明缺哪一份并要求补齐，不要自行脑补。
- 数据不足时如实说明，不要为了凑满结论而编造。

---

"""

DSH_DATA = """## 数据获取

本会话**没有** WorkBuddy 的腾讯自选股连接器（`westock-mcp`），也没有
`neodata-financial-search`。改用当前会话实际可用的工具取数：

- `web_fetch` — 打开具体页面读原文（交易所公告、公司财报页、权威财经媒体、公开行情接口）
- `web_search` — 检索新闻、政策、研报观点（**本部署可能因未配置搜索密钥而直接报错**）
- `bash` — 需要计算或处理数据时使用；本会话解释器是 `python3`，**没有** `python` 命令

**工具可用性**：`web_search` 在部分部署下不可用。若它报错，不要停下、也不要编造，
改用 `web_fetch` 直接拉取已知的公开行情/公告接口，并在报告中说明你用了哪个来源、哪个工具。

数据纪律（违反即视为报告无效）：

- 每个关键数字都要能追溯到具体来源，并在报告中给出出处与获取时间
- 拿不到的数据必须显式写「未获取到」，**禁止**编造、估算后当作事实
- 多个来源冲突时同时列出，并说明你采信哪一个、为什么
- 历史归历史、实时归实时：档案里的价格是访谈快照，讲「当前」必须用实时数据
"""

DSH_BUDGET = """## 执行预算（铁律）— 防轮次耗尽

你的回合有限。必须按此顺序执行，**禁止边查边扩写、禁止查完还继续补查**：

1. **优先用任务说明里的共享快照**（现价/涨跌/PE 等）；同一标的禁止重复取数
2. **取数合计 ≤ 6 次**（能一次拿到就不要拆开；只取本轮真正需要的字段，不要照单全开）
3. **检索约束**：`web_search` ≤ 2 次（本部署可能不可用）；优先 `web_fetch` 直取已知接口
4. 取数结束后**立即写报告并 `send_message`**，写报告过程中禁止再开任何 tool
5. **报告目标 800–1500 字**：「全」= 你的框架各环节都点到并给出独立判断，不是无限加长；
   砍掉档案复述、长案例堆砌
6. 若回合吃紧：保留「一句话判断 + 关键数据表 + 框架要点 + 免责声明」，
   **优先保证 `send_message` 发出**
"""

DSH_SELFCHECK = """## 数据自查

主理人会传入用户问题和股票代码。**你需要自主获取你框架所需的全部数据**。
本会话没有 `westock-mcp`，用 `web_fetch` / `web_search` / `bash` 取公开数据：

- 代码格式参考：沪市 `sh600519` / 深市 `sz000001` / 港股 `hk00700` / 美股 `usAAPL`
- 大盘走势：取上证指数、沪深 300、恒生指数等公开行情页（宏观感知的核心增量区）
- 个股行情 / 资金流向 / 新闻公告 / 技术指标：用 `web_fetch` 拉公开页面，或用 `bash` 计算

拿不到的结构化字段（如逐笔资金流）显式写「未获取到」，**禁止编造**。
"""

DSH_SEARCH = """## 检索工具使用

- 优先用 `web_fetch` 打开权威来源原文：Gartner / McKinsey / IDC / IEA、政府与行业协会官网、
  交易所与公司公告页
- `web_search` 可用时用它做关键词发现（**本部署可能未配置搜索密钥而不可用**）；
  不可用就改用 `web_fetch` 直取已知的权威站点与检索页
- 学术课题：arXiv / SSRN / Google Scholar 的公开页面
- 每条事实性陈述都要留下可点击的来源链接，并记录获取时间
"""

# member id -> (中文角色名, 英文角色名, 产出标记)
TEAMS = {
    "gpt-researcher-team": {
        "src": HOME / ".workbuddy/plugins/marketplaces/experts/plugins/gpt-researcher-team/agents",
        "members": {
            "research-planner": ("研究编辑", "Research Planner", "[研究大纲]"),
            "topic-researcher": ("课题研究员", "Topic Researcher", "[研究草稿]"),
            "draft-reviewer": ("草稿审稿人", "Draft Reviewer", "[审稿意见]"),
            "draft-reviser": ("内容修订员", "Draft Reviser", "[修订稿]"),
            "report-writer": ("报告撰写人", "Report Writer", "[报告框架]"),
            "report-publisher": ("报告发布员", "Report Publisher", "[终稿]"),
        },
        "sections": {
            "## 搜索工具使用": DSH_SEARCH,
        },
    },
    "stock-partner-team": {
        "src": HOME / ".workbuddy-ai/plugins/marketplaces/experts/plugins/stock-partner-team/agents",
        "members": {
            "industry-strategist": ("产业策略师", "Industry Strategist", "[产业策略报告]"),
            "signal-chief": ("信号派首席", "Signal Chief", "[信号研判报告]"),
            "valuation-analyst": ("估值分析师", "Valuation Analyst", "[估值分析报告]"),
            "contrarian-investor": ("逆向投资人", "Contrarian Investor", "[逆向视角报告]"),
            "fundamental-researcher": ("财报研究员", "Fundamental Researcher", "[财报研究报告]"),
            "shortterm-surfer": ("短线冲浪手", "Short-term Surfer", "[短线节奏报告]"),
        },
        "sections": {
            "## 腾讯自选股连接器（westock-mcp）": DSH_DATA,
            "## 执行预算（铁律）": DSH_BUDGET,
            "## 数据自查": DSH_SELFCHECK,
        },
    },
}

# WorkBuddy-only wording that must not survive into a DSH brief.
INLINE = [
    ("腾讯自选股连接器（westock-mcp）", "公开数据源"),
    ("腾讯自选股连接器", "公开数据源"),
    ("`westock-mcp`", "公开数据源"),
    ("westock-mcp", "公开数据源"),
    ("WebSearch / 联网搜索", "web_search / web_fetch"),
    ("WebSearch", "web_search"),
    ("SendMessage", "send_message"),
    ("skills/westock-data", "公开行情接口"),
    ("skills/westock-tool", "公开行情接口"),
]

RESIDUAL = ["neodata", "westock", "WebSearch", "SendMessage", "腾讯自选股"]


def strip_frontmatter(text: str) -> str:
    m = re.match(r"\s*---\r?\n.*?\r?\n---\r?\n?", text, re.S)
    return text[m.end():] if m else text


def replace_section(body: str, header: str, replacement: str) -> str:
    """
    Swap one `## header…` block (up to the next level-2 heading) for `replacement`.

    The heading is matched as a *prefix* of the line, not the whole line: upstream
    headings carry a trailing qualifier (`## 执行预算（铁律）— 防轮次耗尽`) that a
    bare key would otherwise fail to match, silently leaving the WorkBuddy-only
    section in place.
    """
    pattern = re.compile(rf"^{re.escape(header)}[^\n]*$.*?(?=^## |\Z)", re.S | re.M)
    if pattern.search(body):
        return pattern.sub(replacement.rstrip() + "\n\n", body, count=1)
    return body


def main() -> None:
    total = 0
    for team, cfg in TEAMS.items():
        dst = OUT / team / "members"
        dst.mkdir(parents=True, exist_ok=True)
        print(f"=== {team} ===")
        for member, (zh, en, marker) in cfg["members"].items():
            src = cfg["src"] / f"{member}.md"
            if not src.exists():
                print(f"  !! MISSING SOURCE: {src}")
                continue
            body = strip_frontmatter(src.read_text(encoding="utf-8"))

            # Order matters. Sections are swapped for placeholders first, the
            # inline cleanup runs on what remains, and only then are the
            # placeholders expanded. Cleaning after insertion would rewrite the
            # replacement text itself — that turned "no WorkBuddy connector" into
            # the nonsense "no 公开数据源 (公开数据源)".
            placeholders: dict[str, str] = {}
            for index, (header, replacement) in enumerate(cfg["sections"].items()):
                token = f"\x00SECTION{index}\x00"
                swapped = replace_section(body, header, token)
                if swapped != body:
                    placeholders[token] = replacement
                    body = swapped
                else:
                    print(f"  !! section not found in {member}: {header}")

            for old, new in INLINE:
                body = body.replace(old, new)

            for token, replacement in placeholders.items():
                body = body.replace(token, replacement)

            header = HEADER.format(zh=zh, en=en, member=member, marker=marker)
            out = dst / f"{member}.md"
            out.write_text(header + body.strip() + "\n", encoding="utf-8")
            size = len(header + body)
            total += 1
            print(f"  {member:26} {size:6} bytes")

    print(f"\nwrote {total} member briefs under {OUT}")

    # Verify no WorkBuddy-only tool survived as a *live instruction*: a brief that
    # still tells a teammate to call a missing connector would send it hunting for
    # a tool that is absent. Mentions inside an explicit negation ("there is no
    # `neodata-financial-search` here") are correct and must not be flagged, so the
    # check looks at the preceding context — the negation often sits on the line
    # before the tool name.
    print("\n=== residual WorkBuddy-only tokens (excluding negations) ===")
    negations = ("没有", "未连接", "不可用", "禁止", "不使用", "无 ")
    dirty = False
    for path in sorted(OUT.glob("*/members/*.md")):
        text = path.read_text(encoding="utf-8")
        for tok in RESIDUAL:
            for match in re.finditer(re.escape(tok), text):
                before = text[max(0, match.start() - 160):match.start()]
                if any(neg in before for neg in negations):
                    continue
                line = text.count("\n", 0, match.start()) + 1
                snippet = text[match.start():match.start() + 70].replace("\n", " ")
                dirty = True
                print(f"  {path.parent.parent.name}/{path.name}:{line}: …{snippet}")
    if not dirty:
        print("  none — every brief references only DSH-available tools, or names a")
        print("         WorkBuddy-only tool solely to say it is unavailable")


if __name__ == "__main__":
    main()
