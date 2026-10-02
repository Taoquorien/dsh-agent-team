#!/usr/bin/env python3
"""Generate a consolidated inventory of built-in skills and agent teams
bundled inside the WorkBuddy and WorkBuddy AI desktop apps."""

import json, os, re, glob
from collections import Counter, OrderedDict

APPS = OrderedDict([
    ("WorkBuddy", {
        "path": "/Applications/WorkBuddy.app",
        "home": os.path.expanduser("~/.workbuddy"),
    }),
    ("WorkBuddy AI", {
        "path": "/Applications/WorkBuddy AI.app",
        "home": os.path.expanduser("~/.workbuddy-ai"),
    }),
])


def un(root):
    return os.path.join(root, "Contents/Resources/app.asar.unpacked")


def read_yaml_frontmatter(path):
    try:
        text = open(path, encoding="utf-8", errors="replace").read()
    except OSError:
        return {}
    m = re.match(r"\s*---\r?\n(.*?)\r?\n---", text, re.S)
    if not m:
        return {}
    block = m.group(1)
    out = {}
    for key in ("name", "description"):
        mm = re.search(r"^%s:\s*(.*)$" % key, block, re.M)
        if not mm:
            continue
        val = mm.group(1).strip()
        if val in (">", ">-", "|", "|-", ">+", "|+"):  # folded/literal block
            tail = block[mm.end():]
            lines = []
            for line in tail.splitlines():
                if line.strip() == "" :
                    continue
                if re.match(r"^\S", line):
                    break
                lines.append(line.strip())
            val = " ".join(lines)
        out[key] = val.strip().strip('"').strip("'")
    return out


def clean(s, n=150):
    s = re.sub(r"\s+", " ", (s or "")).strip()
    return (s[: n - 1] + "…") if len(s) > n else s


# ---------------------------------------------------------------- skills
def builtin_skills(app):
    root = os.path.join(un(app["path"]), "resources/plugins/workbuddy-builtin")
    rows = []
    for dirpath, _, files in os.walk(root):
        if "SKILL.md" not in files:
            continue
        rel = os.path.relpath(dirpath, root)
        parts = rel.split(os.sep)
        fm = read_yaml_frontmatter(os.path.join(dirpath, "SKILL.md"))
        if parts[0] == "skills":
            group = "顶层内置 Skill"
        elif parts[0] == "builtin-plugins":
            group = "内置插件 Skill · " + parts[1]
        else:
            group = parts[0]
        rows.append({
            "dir": rel,
            "group": group,
            "name": fm.get("name") or parts[-1],
            "desc": fm.get("description", ""),
        })
    rows.sort(key=lambda r: (r["group"], r["dir"]))
    return rows


# ---------------------------------------------------------------- agents
def builtin_agents(app):
    cli = os.path.join(un(app["path"]), "cli/product.json")
    d = json.load(open(cli, encoding="utf-8"))
    runtime = []
    for a in d.get("agents") or []:
        runtime.append({"name": a.get("name"), "desc": a.get("description", "")})
    sub = []
    for s in d.get("builtInSubagents") or []:
        c = s.get("content", "")
        m = re.match(r"---\n(.*?)\n---", c, re.S)
        fm = m.group(1) if m else ""
        n = re.search(r"^name:\s*(.+)$", fm, re.M)
        de = re.search(r"^description:\s*(.+)$", fm, re.M)
        sub.append({"name": n.group(1).strip() if n else "?", "desc": de.group(1).strip() if de else ""})
    return d.get("productName"), d.get("genieVersion"), runtime, sub, d


def plugin_agents(app):
    root = os.path.join(un(app["path"]), "resources/plugins/workbuddy-builtin")
    rows = []
    for dirpath, _, files in os.walk(root):
        if os.path.basename(dirpath) != "agents":
            continue
        for f in sorted(files):
            if not f.endswith(".md"):
                continue
            p = os.path.join(dirpath, f)
            fm = read_yaml_frontmatter(p)
            rows.append({
                "path": os.path.relpath(p, root),
                "name": fm.get("name") or f[:-3],
                "desc": fm.get("description", ""),
            })
    return rows


# ---------------------------------------------------------------- expert teams
def curated(app):
    p = os.path.join(un(app["path"]), "resources/builtin-expert-recommendations/curated-experts.json")
    d = json.load(open(p, encoding="utf-8"))
    return d["candidates"]


def installed_experts(app):
    """Expert/team packages actually downloaded into the user data dir."""
    base = os.path.join(app["home"], "plugins/marketplaces/experts/plugins")
    out = []
    for f in sorted(glob.glob(base + "/*/.codebuddy-plugin/plugin.json")):
        d = json.load(open(f, encoding="utf-8"))
        p = os.path.dirname(os.path.dirname(f))
        agents_dir = os.path.join(p, "agents")
        agents = sorted(x[:-3] for x in os.listdir(agents_dir)) if os.path.isdir(agents_dir) else []
        out.append({"name": d.get("name"), "agent": d.get("agentName", ""),
                    "agents": agents, "desc": d.get("description", "")})
    return out


# ---------------------------------------------------------------- marketplaces
def marketplace_plugins(app, market):
    base = os.path.join(app["home"], "plugins/marketplaces", market, "plugins")
    rows = []
    for p in sorted(glob.glob(base + "/*/")):
        n = os.path.basename(p.rstrip("/"))
        jf = os.path.join(p, ".codebuddy-plugin/plugin.json")
        desc = ""
        if os.path.isfile(jf):
            try:
                desc = json.load(open(jf, encoding="utf-8")).get("description", "")
            except Exception:
                pass
        ag = sorted(x[:-3] for x in os.listdir(p + "agents")) if os.path.isdir(p + "agents") else []
        sk = sorted(os.listdir(p + "skills")) if os.path.isdir(p + "skills") else []
        cm = sorted(x[:-3] for x in os.listdir(p + "commands")) if os.path.isdir(p + "commands") else []
        rows.append({"name": n, "desc": desc, "agents": ag, "skills": sk, "commands": cm})
    return rows


def main():
    out = []
    W = out.append
    W("# WorkBuddy / WorkBuddy AI 内置 Skill 与 Agent Team 清单\n")
    W("> 数据来源：两个 App 的 `app.asar.unpacked` 内置资源 + 各自数据目录（`~/.workbuddy`、`~/.workbuddy-ai`）。\n")
    W("> 提取方式：解析 `cli/product.json`、`builtin-expert-recommendations/curated-experts.json`、")
    W("> 各插件 `plugin.json` 与全部 `SKILL.md` / `agents/*.md` 的 YAML frontmatter。\n")

    # ---- 0. overview
    W("## 0. 总览\n")
    W("| 维度 | WorkBuddy | WorkBuddy AI |")
    W("|---|---|---|")
    meta = {}
    for label, app in APPS.items():
        pn, ver, runtime, sub, d = builtin_agents(app)
        meta[label] = dict(pn=pn, ver=ver, runtime=runtime, sub=sub, product=d)
    W("| 应用路径 | `/Applications/WorkBuddy.app` | `/Applications/WorkBuddy AI.app` |")
    W("| productName / 版本 | %s / %s | %s / %s |" % (
        meta["WorkBuddy"]["pn"], meta["WorkBuddy"]["ver"],
        meta["WorkBuddy AI"]["pn"], meta["WorkBuddy AI"]["ver"]))
    W("| 数据目录 | `~/.workbuddy` | `~/.workbuddy-ai` |")
    W("| 内置 Skill（SKILL.md 总数） | %d | %d |" % (
        len(builtin_skills(APPS["WorkBuddy"])), len(builtin_skills(APPS["WorkBuddy AI"]))))
    W("| 顶层内置 Skill 目录 | %d | %d |" % (
        len([r for r in builtin_skills(APPS["WorkBuddy"]) if r["group"] == "顶层内置 Skill"]),
        len([r for r in builtin_skills(APPS["WorkBuddy AI"]) if r["group"] == "顶层内置 Skill"])))
    W("| 运行时 Agent（product.json agents） | %d | %d |" % (
        len(meta["WorkBuddy"]["runtime"]), len(meta["WorkBuddy AI"]["runtime"])))
    W("| 内置 Subagent | %d | %d |" % (
        len(meta["WorkBuddy"]["sub"]), len(meta["WorkBuddy AI"]["sub"])))
    W("| 插件 Agent 定义（agents/*.md） | %d | %d |" % (
        len(plugin_agents(APPS["WorkBuddy"])), len(plugin_agents(APPS["WorkBuddy AI"]))))
    W("| 专家（curated expert） | %d | %d |" % (
        len([c for c in curated(APPS["WorkBuddy"]) if c["type"] == "expert"]),
        len([c for c in curated(APPS["WorkBuddy AI"]) if c["type"] == "expert"])))
    W("| 专家团（curated expert_team） | %d | %d |" % (
        len([c for c in curated(APPS["WorkBuddy"]) if c["type"] == "expert_team"]),
        len([c for c in curated(APPS["WorkBuddy AI"]) if c["type"] == "expert_team"])))
    W("| 已下载专家/专家团包 | %d | %d |" % (
        len(installed_experts(APPS["WorkBuddy"])), len(installed_experts(APPS["WorkBuddy AI"]))))
    W("| 交互模式（interactionmode） | 4（ask/craft/plan/expert） | 5（+quick） |")
    W("| 欢迎模式（welcomemode） | 3（code/work/design） | 3（code/work/design） |")
    W("| 被禁用的内置 Skill | — | %s |" % (
        ", ".join("`%s`" % s for s in (meta["WorkBuddy AI"]["product"].get("disabledBuiltinSkills") or [])) or "—"))
    W("")
    W("### 关键差异\n")
    def top_names(app):
        return {r["dir"].split("/")[1] if r["dir"].startswith("skills/") else r["dir"]
                for r in builtin_skills(app) if r["dir"].startswith("skills/")}
    def sub_names(app):
        return {"/".join(r["dir"].split("/")[1:]) for r in builtin_skills(app)
                if r["dir"].startswith("skills/") and r["dir"].count("/") > 1}
    wb_top, ai_top = top_names(APPS["WorkBuddy"]), top_names(APPS["WorkBuddy AI"])
    wb_sub, ai_sub = sub_names(APPS["WorkBuddy"]), sub_names(APPS["WorkBuddy AI"])
    W("- **顶层内置 Skill 仅 WorkBuddy 有**：%s" % (", ".join("`%s`" % s for s in sorted(wb_top - ai_top)) or "—"))
    W("- **顶层内置 Skill 仅 WorkBuddy AI 有**：%s" % (", ".join("`%s`" % s for s in sorted(ai_top - wb_top)) or "—"))
    W("- **子 Skill 仅 WorkBuddy 有**：%s" % (", ".join("`%s`" % s for s in sorted(wb_sub - ai_sub)) or "—"))
    W("- **子 Skill 仅 WorkBuddy AI 有**：%s" % (", ".join("`%s`" % s for s in sorted(ai_sub - wb_sub)) or "—"))
    def plug_skill_names(app):
        return {r["dir"] for r in builtin_skills(app) if r["dir"].startswith("builtin-plugins/")}
    wb_p, ai_p = plug_skill_names(APPS["WorkBuddy"]), plug_skill_names(APPS["WorkBuddy AI"])
    W("- **内置插件 Skill 仅 WorkBuddy 有**：%s" % (", ".join("`%s`" % s for s in sorted(wb_p - ai_p)) or "—"))
    W("- **内置插件 Skill 仅 WorkBuddy AI 有**：%s" % (", ".join("`%s`" % s for s in sorted(ai_p - wb_p)) or "—"))
    W("- **Agent Team 机制完全一致**：两版都暴露 `TeamCreate` / `TeamDelete` / `SendMessage`，")
    W("  并有 `team-lead-prompt`、`team-sys-prompt`、`system-reminder-delegate` 三套提示模板。")
    W("- **专家库一致**：两版 `curated-experts.json` 均为 50 专家 + 10 专家团。")
    W("- **本机已下载专家包不同**：WorkBuddy 8 个（含 trading-agent 13 人专家团、gpt-researcher-team 7 人专家团），")
    W("  WorkBuddy AI 3 个（含 stock-partner-team 7 人专家团）。")
    W("")

    for label, app in APPS.items():
        W("\n---\n")
        W("# %s\n" % label)

        # ---- 1. built-in skills
        W("## 1. 内置 Skill\n")
        skills = builtin_skills(app)
        groups = OrderedDict()
        for r in skills:
            groups.setdefault(r["group"], []).append(r)
        W("共 **%d** 个 `SKILL.md`。\n" % len(skills))
        for g, rows in groups.items():
            W("### %s（%d）\n" % (g, len(rows)))
            W("| Skill | 名称 | 说明 |")
            W("|---|---|---|")
            for r in rows:
                W("| `%s` | %s | %s |" % (r["dir"], r["name"], clean(r["desc"])))
            W("")

        # ---- 2. runtime agents
        W("## 2. 运行时 Agent（`cli/product.json` → `agents`）\n")
        pn, ver, runtime, sub, d = builtin_agents(app)
        W("| # | Agent | 说明 |")
        W("|---|---|---|")
        for i, a in enumerate(runtime, 1):
            W("| %d | `%s` | %s |" % (i, a["name"], clean(a["desc"], 110)))
        W("")

        # ---- 3. subagents
        W("## 3. 内置 Subagent（`builtInSubagents`）\n")
        for s in sub:
            W("- **`%s`** — %s" % (s["name"], clean(s["desc"], 200)))
        W("")
        W("`builtInAgentsName`：`%s`\n" % "`, `".join(d.get("builtInAgentsName") or []))

        # ---- 4. plugin agents
        W("## 4. 插件内 Agent 定义（`agents/*.md`）\n")
        pa = plugin_agents(app)
        W("| Agent | 定义文件 | 说明 |")
        W("|---|---|---|")
        for a in pa:
            W("| `%s` | `%s` | %s |" % (a["name"], a["path"], clean(a["desc"], 110)))
        W("")

        # ---- 5. interaction / welcome mode
        W("## 5. 模式型插件（Prompt 级 Agent）\n")
        root = os.path.join(un(app["path"]), "resources/plugins/workbuddy-builtin")
        for kind, pat in (("welcomemode", "welcomemode"), ("interactionmode", "interactionmode")):
            for p in sorted(glob.glob(os.path.join(root, pat, "*"))):
                if not os.path.isdir(p):
                    continue
                n = os.path.basename(p)
                files = []
                for dp, _, fs in os.walk(p):
                    files += [os.path.relpath(os.path.join(dp, f), p) for f in fs]
                W("- `%s/%s`：%s" % (kind, n, ", ".join(sorted(files)) or "—"))
        W("")

        # ---- 6. expert teams
        W("## 6. 专家团（Expert Team）\n")
        cands = curated(app)
        teams = [c for c in cands if c["type"] == "expert_team"]
        W("### 6.1 内置推荐专家团（`curated-experts.json`）—— %d 个\n" % len(teams))
        W("| 专家团 ID | 适用场景 | 说明 |")
        W("|---|---|---|")
        for t in teams:
            W("| `%s` | %s | %s |" % (t["id"], "、".join(t.get("scenarios") or []), clean(t["description"], 130)))
        W("")

        W("### 6.2 已下载到本机的专家 / 专家团包 —— %d 个\n" % len(installed_experts(app)))
        exps = installed_experts(app)
        if exps:
            W("| 包名 | 主理人 Agent | 成员（agents/） | 说明 |")
            W("|---|---|---|---|")
            for e in exps:
                kind = "专家团" if len(e["agents"]) > 1 else "专家"
                W("| `%s`（%s） | `%s` | %s | %s |" % (
                    e["name"], kind, e["agent"],
                    ", ".join("`%s`" % a for a in e["agents"]) or "—",
                    clean(e["desc"], 90)))
        else:
            W("_（本机未下载任何专家包）_")
        W("")

        # ---- 7. expert (single)
        W("### 6.3 内置推荐单专家（`expert` 类型）—— %d 个\n" % len([c for c in cands if c["type"] == "expert"]))
        W("| 专家 ID | 适用场景 | 说明 |")
        W("|---|---|---|")
        for c in cands:
            if c["type"] != "expert":
                continue
            W("| `%s` | %s | %s |" % (c["id"], "、".join(c.get("scenarios") or []), clean(c["description"], 110)))
        W("")

        # ---- 8. marketplaces
        W("## 7. 插件市场中的团队型插件\n")
        for mk in ("codebuddy-plugins-official", "cb_teams_marketplace"):
            rows = marketplace_plugins(app, mk)
            teamy = [r for r in rows if r["agents"]]
            W("### `%s` —— 共 %d 个插件，其中 %d 个带 Agent\n" % (mk, len(rows), len(teamy)))
            if teamy:
                W("| 插件 | Agent 数 | 成员 Agent | Skill | 命令 |")
                W("|---|---|---|---|---|")
                for r in teamy:
                    W("| `%s` | %d | %s | %d | %d |" % (
                        r["name"], len(r["agents"]),
                        ", ".join("`%s`" % a for a in r["agents"]), len(r["skills"]), len(r["commands"])))
            W("")
            other = [r for r in rows if not r["agents"] and (r["skills"] or r["commands"])]
            if other:
                W("<details><summary>无 Agent 但含 Skill/命令的插件（%d）</summary>\n" % len(other))
                W("| 插件 | Skill | 命令 | 说明 |")
                W("|---|---|---|---|")
                for r in other:
                    W("| `%s` | %d | %d | %s |" % (r["name"], len(r["skills"]), len(r["commands"]), clean(r["desc"], 70)))
                W("\n</details>\n")

        # ---- 9. user-level
        W("## 8. 用户级（数据目录）已安装 Skill / 插件\n")
        sk_dir = os.path.join(app["home"], "skills")
        if os.path.isdir(sk_dir):
            rows = []
            for p in sorted(glob.glob(sk_dir + "/*/")):
                f = os.path.join(p, "SKILL.md")
                if os.path.isfile(f):
                    fm = read_yaml_frontmatter(f)
                    rows.append((os.path.basename(p.rstrip("/")), fm.get("description", "")))
            W("用户 Skill 目录 `%s` —— %d 个：\n" % (sk_dir, len(rows)))
            W("| Skill | 说明 |")
            W("|---|---|")
            for n, de in rows:
                W("| `%s` | %s |" % (n, clean(de, 110)))
            W("")
        inst = os.path.join(app["home"], "plugins/installed_plugins.json")
        if os.path.isfile(inst):
            pl = json.load(open(inst, encoding="utf-8")).get("plugins", {})
            W("已安装插件（`installed_plugins.json`）—— %d 个：\n" % len(pl))
            W("| 插件 | 版本 |")
            W("|---|---|")
            for k in sorted(pl):
                v = pl[k][0].get("version", "") if isinstance(pl[k], list) and pl[k] else ""
                W("| `%s` | %s |" % (k, v))
            W("")

    # ---- shared team toolchain
    W("\n---\n")
    W("# 附：Agent Team 协作机制（两版共有）\n")
    W("| 能力 | 载体 | 说明 |")
    W("|---|---|---|")
    W("| `TeamCreate` | 工具 | 创建团队 + 同名任务列表 |")
    W("| `TeamDelete` | 工具 | 清理团队与任务目录 |")
    W("| `SendMessage` | 工具 | message / broadcast / shutdown_request |")
    W("| `team-lead-prompt` | Prompt 模板 | 主理人系统提示 |")
    W("| `team-sys-prompt` | Prompt 模板 | 团队成员系统提示 |")
    W("| `system-reminder-delegate` | Prompt 模板 | 委派模式协调者提示 |")
    W("| `deep-research.workflow.js` | 内置 Workflow | Scope→Search→Fetch→Verify→Synthesize |")
    W("| `expert-manager` Skill | Skill | 专家包全生命周期运营（含 team-spec 规范） |")
    W("")

    text = "\n".join(out) + "\n"
    dest = os.path.join(os.path.dirname(os.path.abspath(__file__)), "workbuddy-builtin-inventory.md")
    open(dest, "w", encoding="utf-8").write(text)
    print("written:", dest, len(text), "bytes")


if __name__ == "__main__":
    main()
