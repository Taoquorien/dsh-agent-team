#!/usr/bin/env python3
"""Port the WorkBuddy `trading-agent` expert team into a DSH team definition.

Only three transformations are applied to the upstream member briefs, so the
specialist instructions themselves survive verbatim:

1. Strip the WorkBuddy frontmatter and prepend a DSH teammate header that names
   the member's `spawn_teammate` id and its handoff marker.
2. Replace the WorkBuddy `neodata-financial-search` data-acquisition section
   with the tools DSH actually has. `neodata` is a WorkBuddy-only skill; leaving
   the instruction in place would make every analyst fail on a missing script.
3. Rewrite remaining `neodata` mentions so no brief points at a missing skill.
"""

import re
from pathlib import Path

SRC = Path.home() / ".workbuddy/plugins/marketplaces/experts/plugins/trading-agent/agents"
DST = Path(__file__).resolve().parent.parent / "teams/trading-team/members"

# member id -> (中文角色名, 英文角色名, 产出标记)
MEMBERS = {
    "market-analyst": ("技术分析师", "Market Analyst", "[市场技术分析报告]"),
    "fundamentals-analyst": ("基本面分析师", "Fundamentals Analyst", "[基本面分析报告]"),
    "news-analyst": ("新闻分析师", "News Analyst", "[新闻分析报告]"),
    "sentiment-analyst": ("情绪分析师", "Sentiment Analyst", "[情绪分析报告]"),
    "bull-researcher": ("多头研究员", "Bull Researcher", "Bull Analyst: [多头论证]"),
    "bear-researcher": ("空头研究员", "Bear Researcher", "Bear Analyst: [空头论证]"),
    "research-manager": ("研究主管", "Research Manager", "[投资计划]"),
    "trader": ("交易员", "Trader", "[交易员决策]"),
    "aggressive-risk-analyst": ("激进风险分析师", "Aggressive Risk Analyst", "Aggressive Analyst: [激进派论证]"),
    "conservative-risk-analyst": ("保守风险分析师", "Conservative Risk Analyst", "Conservative Analyst: [保守派论证]"),
    "neutral-risk-analyst": ("中性风险分析师", "Neutral Risk Analyst", "Neutral Analyst: [中性派论证]"),
    "risk-manager": ("风险主管", "Risk Manager", "[最终交易决策]"),
}

# Members that read market data directly need a replacement data section.
DATA_SECTION = """## 数据获取

本会话没有 WorkBuddy 的 `neodata-financial-search` skill，改用当前会话可用的工具，
优先取可核验的一手来源：

- `web_search` — 检索行情、财报、公告、研报、资金流向与宏观数据
- `web_fetch` — 打开具体页面读原文（交易所公告、公司财报页、权威财经媒体）
- `bash` — 需要计算或处理数据时使用；本会话的解释器是 `python3`，**没有** `python` 命令

**工具可用性**：`web_search` 在部分部署下会因未配置搜索密钥而直接报错。若它不可用，
不要停下、也不要编造，改用 `web_fetch` 直接拉取已知的公开行情/公告接口，并在报告中
说明你用了哪个来源、哪个工具。

数据纪律（违反即视为报告无效）：

- 每个关键数字都要能追溯到具体来源，并在报告中给出出处与获取时间
- 拿不到的数据必须显式写「未获取到」，**禁止**编造、估算后当作事实
- 多个来源冲突时同时列出，并说明你采信哪一个、为什么
"""

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


def strip_frontmatter(text: str) -> str:
    m = re.match(r"\s*---\r?\n.*?\r?\n---\r?\n?", text, re.S)
    return text[m.end():] if m else text


def replace_data_section(body: str) -> str:
    """Swap the '## 数据获取' block for the DSH-adapted one."""
    pattern = re.compile(r"^## 数据获取\s*$.*?(?=^## )", re.S | re.M)
    if pattern.search(body):
        return pattern.sub(DATA_SECTION + "\n", body, count=1)
    return body


def clean_neodata(body: str) -> str:
    body = body.replace(
        "**优先使用 `neodata-financial-search` skill 获取数据**（文章模式）：",
        "**优先用 `web_search` / `web_fetch` 获取新闻与公告原文**：",
    )
    body = body.replace(
        "如 neodata 文章召回不足，可辅助使用 WebSearch 补充。",
        "如果检索召回不足，换关键词或换来源再试，并在报告中说明覆盖范围。",
    )
    # Any surviving mention of the WorkBuddy-only skill.
    body = re.sub(r"`neodata-financial-search`\s*skill", "本会话可用的检索工具", body)
    body = body.replace("neodata 数据源", "公开数据源")
    body = body.replace("非 neodata 数据源", "未经核验的数据源")
    body = body.replace("非 neodata 数据源", "未经核验的数据源")
    return body


def main() -> None:
    DST.mkdir(parents=True, exist_ok=True)
    written = []
    for member, (zh, en, marker) in MEMBERS.items():
        src = SRC / f"{member}.md"
        body = strip_frontmatter(src.read_text(encoding="utf-8"))
        # Clean upstream wording first, then insert the adapted data section:
        # the reverse order would let the cleanup rewrite the replacement text.
        body = clean_neodata(body)
        body = replace_data_section(body)
        header = HEADER.format(zh=zh, en=en, member=member, marker=marker)
        out = DST / f"{member}.md"
        out.write_text(header + body.strip() + "\n", encoding="utf-8")
        written.append((member, len(header + body)))

    for member, size in written:
        print(f"  {member:30} {size:6} bytes")
    print(f"\nwrote {len(written)} member briefs to {DST}")


if __name__ == "__main__":
    main()
