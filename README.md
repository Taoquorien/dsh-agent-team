# Agent Team Definitions

A declarative layer over DeepSeek Harness's experimental Agent Teams runtime.

The runtime gives a session a team *mechanism*: a roster, a durable mailbox, and a
shared task board. It has no notion of a *reusable team* — every team is improvised
at spawn time and leaves nothing behind. This bundle adds the missing declaration
layer: a team is a directory on disk that any session can load.

## Install

Requires DeepSeek Harness with the Agent Teams runtime enabled. Install the bundle
into a profile:

```bash
# from a local checkout
dsh plugin --profile <your-profile> add /path/to/agent-team

# straight from git
dsh plugin --profile <your-profile> add github:<owner>/<repo>
```

Then restart the app (or reload the window) so the host picks up the new bundle.

Verify it loaded by running the catalog command in a session:

```
/team
```

It lists every team definition plus the remaining team slots for the session.

### Enabling the Agent Teams runtime

The plugin registers *definitions* and a picker. Actually **running** a team needs
the experimental Agent Teams bundle, which is a separate row in your profile. On a
default profile it is not enabled, and the plugin still loads — it degrades rather
than failing: the catalog and the Teams tree work, but spawning teammates does not,
because there is no runtime to spawn into.

To enable it, add the profile layer and raise the member cap (see
[Member cap](#member-cap) — the shipped default of 8 cannot complete the 12-member
`trading-team`):

```yaml
# ~/.dsh/profiles/<your-profile>/cordis.patch.yml
- id: agent-team
  config:
    maxMembers: 64
    maxTasks: 256
    maxPendingMessagesPerMember: 64
    maxMessageBytes: 65536
    disposalTimeoutMs: 5000
```

### A note on names

The package is published as `@local/dsh-agent-team`. `@local` is a placeholder
scope, not a registry namespace — the plugin is installed by path or git URL, not
from npm. The `name` in `package.json`, the `id` in `client.js`, and the `name` in
`cordis.patch.yml` **must stay identical**; the client module loader resolves a
browser entry by matching its id against the package name.

## Layout

```
teams/<team-name>/
  SKILL.md        the Lead's SOP playbook, registered as a model-invocable skill
  team.json       machine-readable roster: lead, members, phases, workflows
  members/*.md    one brief per teammate, used as spawn_teammate's `prompt`
  scripts/        wbdata.py — zero-config market data (see below)
```

`SKILL.md` is registered through `ctx.skills.registerProvider()` — the same seam
`@deepseek-ai/dsh-skill-office` uses for its bundled Office skills. It therefore
shows up in the ordinary skill catalog and is loadable with the `skill` tool.

## Market data: `scripts/wbdata.py`

A zero-config data layer for the finance teams. **No API key, no token, no login.**

The briefs originally said "use `web_fetch` / `web_search`". That is a weak path on
this deployment: `web_search` has no search key and fails outright, and scraping
quote pages through `web_fetch` makes a model read HTML and guess at numbers. Every
upstream below is a public quote/filing API that returns JSON directly — the same
sources the major finance sites render from.

| Command | What it returns |
|---|---|
| `quote 600519 hk00700 usAAPL` | real-time snapshot, batched, A/HK/US in one call |
| `kline 600519 --period day --count 250` | OHLCV, forward-adjusted by default |
| `minute 600519` | intraday 5-minute bars |
| `indices` | headline index snapshot |
| `financials 600519` | multi-period main indicators (revenue/ROE/margins/debt) |
| `valuation 600519` | PE/PB/PS history **plus the percentile in window** |
| `dividend 600519` | payout history + trailing-4-payout cash yield |
| `holders 600519` | top free-float holders, with QoQ share change |
| `announcements 600519` | company filings, with links |
| `research 600519` | sell-side reports (org, rating, forecast EPS/PE) |
| `fundflow 600519` | super-large / large / medium / small order flow |
| `margin 600519` | margin-trading balance |
| `sector --count 10` | industry rotation ranking |
| `billboard` | daily 龙虎榜 |
| `northbound` | Stock-Connect net flow |
| `limitup` / `limitdown` | limit-up/down pools with consecutive-board counts |
| `macro [--kind gdp\|cpi\|ppi\|pmi\|money\|retail]` | macro series |
| `snapshot 600519 [--full]` | **all sections for one ticker in one call** |

### Which team gets which guidance

The four teams do not need the same data, so the wiring is team-aware
(`tools/wire_wbdata.py`). Handing A-share commands to a product team would be
wrong guidance, and an unmapped team is left untouched rather than guessed at:

| Team | Guidance |
|---|---|
| `trading-team` | full securities command set (4 fetching members) |
| `stock-partner-team` | full securities command set (all 6) |
| `gpt-researcher-team` | securities **subset**, conditional — the topic only sometimes involves a listed company (1 fetching member) |
| `product-strategy-team` | **web research** — competitor sites, docs, pricing pages, app stores; securities only as an optional size reference |

Members that are pure *reasoners* (bull/bear researchers, risk analysts, both
managers, and the research team's writers/reviewers) have no data section **by
design** — they consume peers' reports and never fetch.

Design rules that matter for correctness:

- **Standard library only** — a member may run where nothing is installed, so the
  script must never fail on an import.
- **JSON on stdout, diagnostics on stderr** — a redirect never corrupts the payload.
- **Timestamp everything** — each payload carries `fetched_at`, and the market's own
  `quote_time`. A price without a time is not usable for a trading decision.
- **Never invent a number.** A failed source becomes an `error` field; callers are
  told to write 未获取到 rather than guess.
- **Retry transient failures.** Eastmoney's `push2` endpoints drop connections under
  bursts; one flaky GET must not read as "this data does not exist".

Market quirks the script encodes, each verified against live responses rather than
assumed:

- Tencent's quote tail **differs per market**: A-shares carry PB at index 46, while
  HK/US put a name string there. Reading 46 as PB is only valid for A-shares.
- The quote-time spelling also differs (`20260930161458` / `2026/09/30 16:08:33` /
  `2026-09-30 16:00:01`).
- US symbols must keep their case (`usAAPL`); lowercasing makes the upstream answer
  `v_pv_none_match` — a **silent empty result**, the worst failure mode for a data
  layer. Such symbols are reported in a `missing` list instead.
- Sector ranking uses Tencent, not Eastmoney: Eastmoney's `clist` answers
  `RemoteDisconnected` after a burst and stays down (verified — `kamt` on the same
  host kept working), so it is unusable as a routine call. Eastmoney remains the
  fallback, and both `list` and `dict` shapes of `data.diff` are accepted.
- Tencent's sector API answers **HTTP 200 even for a parameter error**, so the
  payload's `code` is checked rather than the status code.
- **Limit-up pool prices are scaled by 1000, not 100.** Cross-checked against live
  quotes: 紫竹高科 is `p=20200` and trades at 20.20. Dividing by 100 gives 202.0 —
  a silent 10× error in every price level.
- Eastmoney's `push2` host also backs `indices`, which is why indices use Tencent
  first with Eastmoney as fallback.
- **Macro report names are not guessable.** Only names verified to return rows are
  registered; plausible-looking ones (`RPT_ECONOMY_LPR`, `RPT_ECONOMY_GDPSORT`)
  answer `报表配置不存在`, which would surface as a silent zero-row series reading
  like "nothing published this period". LPR / social financing / unemployment are
  absent upstream and are reported as `unavailable` with a pointer to where the
  number actually lives.
- A valuation percentile is computed because raw PE/PB is not decision-useful on
  its own; the newest dividend row is often a 预披露 pre-disclosure with a
  legitimately null cash figure, so `progress` is carried through.

The script is copied into each team's `scripts/` directory so a member can call it
by path without knowing about the others.

## Bundled teams

| Team | Members | Phases | Provenance |
|---|---|---|---|
| `trading-team` | 12 | 5 | ported from WorkBuddy `trading-agent` |
| `stock-partner-team` | 6 | 2 | ported from WorkBuddy `stock-partner-team` |
| `gpt-researcher-team` | 6 | 5 | ported from WorkBuddy `gpt-researcher-team` |
| `product-strategy-team` | 5 | 4 | **authored** — see below |

`team.json` records the provenance in `source.kind`:

- **`ported`** — the member briefs are the upstream text, with only the
  WorkBuddy-only data channels rewritten for DSH. The roster, phases and
  specialist instructions survive verbatim.
- **`authored`** — written for DSH from a catalog entry alone.
  `product-strategy-team` is authored: its WorkBuddy expert package was never
  downloaded to this machine, so only the catalog metadata existed (roster,
  display names, professions, one-line scope per role). To replace the briefs
  with upstream wording, download `product-strategy-team` from the WorkBuddy
  Expert Marketplace and re-run a porting pass.

### WorkBuddy-only channels rewritten on port

Two upstream data channels do not exist in DSH, and a brief that still named them
would send a teammate hunting for a missing tool:

| Upstream | Rewritten to |
|---|---|
| `neodata-financial-search` skill (`trading-agent`) | `web_fetch` / `web_search` / `bash` |
| `westock-mcp` connector (`stock-partner-team`) | `web_fetch` / `web_search` / `bash` |
| `skills/md-to-html` (`stock-partner-team`) | a self-contained HTML file written with `python3` |

The porting scripts are `tools/port_team.py` (trading-team),
`tools/port_teams.py` (the other two ported teams) and
`tools/author_product_team.py` (the authored team).

## `tools/`

Repo-maintenance scripts. They are **not** part of the installed plugin — the
`files` list in `package.json` excludes them, so an install never ships them.

| Script | Purpose |
|---|---|
| `port_team.py` | ports WorkBuddy `trading-agent` into `teams/trading-team/` |
| `port_teams.py` | ports `gpt-researcher-team` and `stock-partner-team`, and asserts no brief still names a missing data channel |
| `author_product_team.py` | regenerates the **authored** `product-strategy-team` briefs |
| `wire_wbdata.py` | rewrites the data-acquisition section in every brief, team-aware |
| `build_inventory.py` | builds the WorkBuddy built-in skill/team inventory |

Reading the ported teams back requires the upstream WorkBuddy expert packages on
disk (`~/.workbuddy/...`); `author_product_team.py` and `wire_wbdata.py` need no
upstream data and are safe to run anywhere. `wire_wbdata.py` is idempotent — a
rerun reports `0 briefs updated`.

## Member cap

The runtime caps a Team at `maxMembers` **cumulatively**, not concurrently: the
roster is immutable, names are never reused, and a spawn never frees a slot. The
shipped default is 8, which cannot complete the 12-member `trading-team`.

This profile raises the cap to **64** on the `agent-team` row of
`~/.dsh/profiles/desktop/cordis.patch.yml`, so every bundled team runs in full.
Patch application replaces the whole `config` object, so that row restates all
five limit keys — listing only `maxMembers` would silently reset the other four
to the runtime defaults.

## Discovering and invoking a team

| Surface | How | What it gives |
|---|---|---|
| **Teams tree** | expand **Teams** in the sidebar foot | the team list; clicking one fills the composer with `/<team> ` and reveals that conversation |
| `/` menu | type `/` and pick `trading-team` | every team, because each is a skill with `userInvocable: true` |
| `/trading-team` | type it literally | loads the playbook; clicking the reference opens `SKILL.md` in the right pane |
| `/team` | the plugin's own command | catalog plus **remaining slot budget** for the session |

### The Teams tree

`client.js` registers one slot:

- `sidebar.footer.action` — a collapsible **Teams** section. Collapsed it is one row;
  expanded it lists the team definitions beneath itself, so picking never leaves the sidebar.

Clicking a team does **not** start work. It fills the current composer with
`/<team-name> ` and switches to that conversation, leaving the user to add their own
question before sending. This is deliberate: sending immediately would consume the
runtime's cumulative, irreversible roster slots before the user has said what they
want. The gesture is the host's own — `invokedSkillNames()` in
`@deepseek-ai/dsh-tool-skill` turns literal `/name` user text into a skill load:

```js
SKILL_GESTURE = /(^|\s)\/([a-z0-9]+(?:-[a-z0-9]+)*)(?=\s|$)/g
```

so the user's eventual send loads the team SOP through the same path the `/` menu uses.

### How the draft is written

Through the `conversation` service's service-face path:

```js
const actx = ctx.sessions.scope(sessionId)
actx.get('conversation').input.for(actx).setDraft(text)
```

`dsh-client-ui-commands` reaches the same shell the same way
(`binding.ctx.get("conversation")?.input.for(binding.ctx).focus()`). `actx.get()` is the
non-throwing accessor and needs no `inject` declaration, unlike direct
`ctx.conversation` property access.

An earlier revision instead captured the session-scoped `inputActions` prop through a
bridge mounted in `conversation.composer.dock`. **That was broken for new sessions** and
is worth recording, because the failure was silent. The dock renders only when
`variant === "composer"`, and a brand-new Session renders the **hero** composer:

```js
variant === "composer" && input !== void 0 && sessionId !== void 0
  ? renderSlot("conversation.composer.dock", {}) : null
// …
renderSlot("conversation.composer.bar", { variant: hero ? "hero" : "composer", … })
```

So in exactly the case that mattered most the bridge never mounted, `inputActions` was
never captured, and clicking a team did nothing with no error. The service path has no
variant dependency.

### Why the tree is not in `sidebar.panellist`

`sidebar.panellist` renders **one flat nav row per entry** and hardcodes each row's
click to `ctx.layout.selectPanel(id)`, which swaps the centre panel. It cannot expand
in place, and its rows render only a glyph — a nested team list is not expressible
there. `sidebar.footer.action` is the one sidebar list slot whose rendering this
plugin owns.

The catalog is read from `skills/list`, filtered to entries whose `path` ends in
`teams/<name>/SKILL.md`. The provider sets that path, so it identifies this
plugin's teams without a custom host route.

The tree targets the Session in the main view (`retainedBy.mainView > 0`), else the
newest one. It never spawns teammates, so it cannot burn roster slots by accident.

`/team` remains the only surface that reports the **slot budget**: it is read-only
and deliberately spawns nothing, because a command runs outside the model turn, and
creating teammates there would bypass the Lead's planning and consume irreversible
roster slots. The plugin also warns at load time when a roster cannot fit the cap.


### Correction: an earlier "no picker is possible" claim was wrong

An earlier revision of this file argued that a launching picker was not
implementable, on the grounds that the client exposes no send API. **That was
wrong.** The mistake was searching the client bundles for a `session.prompt`
symbol and concluding from its absence in *client* code that no such capability
existed, without checking the remote namespace list.

`session/prompt` is a real remote method (namespace `session`, service
`sessionController`), and the composer's own submit path calls it as
`session.prompt(content, mode, signal)`. Client plugins reach it through
`ctx.remote.session`. The panel now uses exactly that call.

The lesson worth keeping: absence of a symbol in one layer is not absence of the
capability. Enumerate the API surface (`ctx.remote`, `ctx.slots.entriesOfSlot`)
before declaring something impossible.


## Why the SOP stays small

Skill bodies are pruned above 8192 characters. Rather than inline twelve member
briefs, `SKILL.md` carries the roster and the phase plan, and the Lead reads
`members/<name>.md` only when it is about to spawn that teammate. The skill's
`resourceBase` is the team directory, so `members/...` resolves relatively and no
absolute path is baked into the playbook.

## Adding a team

1. `mkdir teams/<kebab-case-name>`
2. Write `SKILL.md` with `name` and `description` frontmatter. The skill name must
   equal the directory name and be kebab-case.
3. Add `team.json` and `members/*.md`.

The provider re-scans on every catalog read, so a new team appears without
reinstalling the bundle.

## Included teams

| Team | Skill | Members |
|---|---|---|
| Trading Analysis Team | `trading-team` | 12 |

### Trading Analysis Team

Ported from the WorkBuddy expert package `trading-agent`. Five phases:
parallel data collection (technical / fundamental / news / sentiment) → bull-bear
debate with an adjudicator → trader decision → three-way risk debate with a risk
adjudicator → Lead compiles.

**Adaptation.** Upstream mandates the WorkBuddy-only `neodata-financial-search`
skill for market data. Harness has no such skill, so every data-acquisition
section was rewritten to use `web_search` / `web_fetch` with an explicit
provenance rule: every figure must be traceable, and missing data must be
reported as missing rather than fabricated. The specialist instructions
themselves are unchanged.

## Limits

- **`maxMembers` is cumulative, not concurrent.** The roster is immutable — names are never
  reused and members are never removed, so each spawn permanently consumes a slot for the
  session. The shipped default is 8; this profile raises it to 64 (see *Member cap* above),
  so all four bundled teams run in full. Verified against the runtime:
  `if (state.members.length >= this.maxMembers) throw new TeamError(..., "TEAM_MEMBER_LIMIT")`.
  Each SOP still tells the Lead to count remaining slots first — a session that already ran
  one team may be short — and to degrade to Phase 1–3 when necessary, declaring the omission.
- The runtime is experimental and promises no stability. This bundle only reads the skill
  registry, which is a stable seam; it does not depend on Team internals.
- Write-scope overlap between teammates is advisory, never a lock.
- This bundle declares no `Config` schema (see `index.js`), so the row's `config` is read
  defensively. `teamsDir` is honoured when set to an absolute path.
- `web_search` may be unavailable depending on deployment; the member briefs state the
  `web_fetch` fallback.
