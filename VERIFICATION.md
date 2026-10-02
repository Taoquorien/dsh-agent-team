# Verification record — Agent Team Definitions plugin

Date: 2026-09-30 · Profile: `desktop` · DSH `0.2.0-rc.2`

## Round 9 — extending the data layer to every finance surface

**Goal:** apply the same zero-config approach everywhere it belongs, and *analyse*
each team's real data need rather than blanket-applying it.

### What each team actually needs

Determined by reading the briefs' own vocabulary, not by assumption:

| Team | Nature | Verdict |
|---|---|---|
| `trading-team` | securities analysis | full command set |
| `stock-partner-team` | securities roundtable | full command set |
| `gpt-researcher-team` | general research | **subset, conditional** — the topic only sometimes involves a listed company |
| `product-strategy-team` | **product** team | **web research, not securities** |

The product team's members talk about 官网 / 产品文档 / 定价页 / 应用商店 / 竞品 /
埋点 — no securities vocabulary at all. The first pass had wrongly given it the full
A-share command set. Fixed by making `tools/wire_wbdata.py` team-aware, with an
explicit rule that an **unmapped team is left untouched** rather than guessed at.

Members that are pure *reasoners* keep no data section, and that is correct: 8 of 12
trading-team briefs (bull/bear, three risk analysts, both managers) and 5 of 6
research-team briefs (writers, reviewer, reviser, planner) consume peers' reports and
never fetch.

### Six new data dimensions

Chosen from the dimensions the briefs already referenced but `wbdata.py` did not
cover — 估值分位, 分红股息, 股东持仓, 涨停/竞价, 宏观:

| Command | Verified live |
|---|---|
| `valuation` | ✅ 250-day window, PE/PB/PS + `percentile_in_window` (PE at 20.4th pct) |
| `dividend` | ✅ payout history; trailing-4-payout yield 8.23% |
| `holders` | ✅ 茅台集团 54.5% of float, with QoQ change |
| `limitup` / `limitdown` | ✅ pool with consecutive-board counts, 52 names |
| `macro` | ✅ 6 series (gdp/cpi/ppi/pmi/money/retail) |
| `indices` | ✅ 8 headline indices |

**19/19 subcommands pass** (the 18 data commands plus `snapshot`), `snapshot --full`
returns all 10 sections, and the four team copies are byte-identical.

### Bugs found by testing

1. **Limit-up prices were 10× too high.** The pool's fixed point is 1000, not 100 —
   caught only by **cross-checking the pool against live quotes**: 紫竹高科 appeared
   as 202.0 while trading at 20.20. A silent 10× error in every price level.
2. **`indices` failed with `RemoteDisconnected`** — same unreliable Eastmoney
   `push2` host that forced `sector` off it. Moved to Tencent with Eastmoney as
   fallback.
3. **Four macro series returned 0 rows** because I had guessed report names. Three
   more guessed names (`gdpxq`/`czsr`/`gdzctz`) were also dead. Fixed by registering
   only names verified to return data, and by distinguishing "unavailable upstream"
   from "published nothing" — an empty list would have made the second claim.
4. **`dividend`'s `plan` field was mapped to a long free-text column** instead of the
   short `ASSIGN_PROGRESS`, and the newest row's null cash figure needed `progress`
   passed through so it reads as 预披露 rather than "no dividend".
5. **Two spellings of the data heading** existed (`## 数据获取` and the research
   team's `## 检索工具使用`); both are now matched so they cannot drift apart.

`tools/wire_wbdata.py` is idempotent — a rerun reports "0 updated".

### Not verified

- **Still no end-to-end team run.** Each command is verified against live upstreams;
  how a member composes them under its turn budget is not.
- Upstream APIs are undocumented and can change. Failures surface as an `error`
  field, which the briefs require members to report as 未获取到 rather than guess.

---

## Round 8 — zero-config market data (`scripts/wbdata.py`)

**Goal:** the finance teams needed real-time data **without configuring a search key
or any token**. `web_search` is unavailable on this deployment and `web_fetch`
scraping is lossy, so the data path was the weakest part of the teams.

### Approach

Rather than routing through WorkBuddy's authenticated backend (see Round 9 — it works
but needs a live app and a per-session credential), this uses **public, keyless quote
and filing APIs** that need no account at all.

### Every command exercised against live upstreams

| Command | Result |
|---|---|
| `quote 600519 00700 AAPL` | ✅ A/HK/US in one batched call |
| `kline 600519 --count 5` | ✅ 5 bars, forward-adjusted |
| `minute 600519` | ✅ 320 five-minute bars |
| `financials 600519` | ✅ 12 periods |
| `announcements 600519` | ✅ filings with links |
| `research 600519` | ✅ 47 hits, org + rating + forecast |
| `fundflow 600519` | ✅ 4 order-size buckets |
| `billboard` | ✅ 龙虎榜 rows |
| `margin 600519` | ✅ financing balance |
| `sector --count 5` | ✅ industry ranking + leaders |
| `northbound` | ✅ four Connect channels |
| `snapshot 600519` | ✅ all six sections, one call |

11/11 subcommands pass; the four team copies of the script each pass a live `quote`.

### Bugs found by testing, not by reading

Each of these was a real defect that the first implementation shipped:

1. **US tickers were lowercased.** `normalize("usAAPL")` returned `usaapl`, and the
   upstream answers `v_pv_none_match` — an **empty result rather than an error**, so
   a US analysis would have silently reported no data. Fixed by upper-casing only the
   US ticker body, and by surfacing unrecognised symbols in a `missing` list.
2. **PB was read from index 46 for every market.** That index is PB for A-shares but
   holds a name string for HK/US (`'TENCENT'`, `'Apple Inc.'`). Fixed with per-market
   tail tables.
3. **Quote time had three different spellings** across markets; only the A-share
   `YYYYMMDDHHMMSS` form was parsed.
4. **`sector` crashed** with `'list' object has no attribute 'values'` — Eastmoney's
   `data.diff` is a `list` on some responses and a `dict` on others.
5. **`northbound` always returned null** — the live field is `dayNetAmtIn`, not
   `netBuyAmt`.
6. **`sector`'s Tencent parameter was invalid** (`sort_type=zdf` → `参数错误`). The
   accepted name is `price`. Note this API returns **HTTP 200 with an error payload**,
   so a status-code check alone would have passed a broken call.
7. **Eastmoney `clist` is unusable as a routine call** — it starts answering
   `RemoteDisconnected` after a burst and stays down, while `kamt` on the same host
   keeps working. Sector ranking was moved to Tencent with Eastmoney as fallback.
8. **A transient `RemoteDisconnected` read as "no data"** — added bounded retry.

A `_num` helper was also accidentally deleted during an edit and restored; the missing
symbol would have raised `NameError` at the first quote call.

### Wiring

`tools/wire_wbdata.py` rewrote the data-acquisition guidance in **15 member briefs**
(the two distinct shapes that exist, since the teams were ported in two passes). The
script is idempotent — a second run reports "0 updated". The four `SKILL.md` files
were updated by hand to lead with `wbdata.py`.

**Not every brief needed it, and that is correct:** 8 of the 12 trading-team briefs
(bull/bear researchers, risk analysts, both managers) are *reasoners* that consume
peers' reports and never fetch data, so they have no data section by design. The four
that do fetch — market, fundamentals, news, sentiment — are wired, as is
`topic-researcher` in the research team.

All four `SKILL.md` bodies stay under the 8192 prune threshold (4498 / 5280 / 4159 /
3238).

### Not verified

- **No team has been run end-to-end with this layer.** The commands are verified
  individually against live upstreams; how a member composes them under its turn
  budget is not.
- Upstream APIs are undocumented and can change without notice. A failure surfaces as
  an `error` field, which the briefs require members to report as 未获取到 rather than
  guess around.

---

## Round 7 — the Teams tree did nothing in a new session

**Reported:** in a freshly created session, clicking a team did not put anything into
the composer.

### Root cause

The draft was written through a bridge component (`ComposerBridge`) mounted in the
session-scoped `conversation.composer.dock` slot, which captured the `inputActions`
prop and published it to the root-scoped tree. **That slot is variant-gated:**

```js
// dsh-client-ui-conversation, InputBar render
variant === "composer" && input !== void 0 && sessionId !== void 0
  ? renderSlot("conversation.composer.dock", {}) : null
```

and the variant is derived from whether the Session is still blank:

```js
const hero = sessionId === void 0 || shellPhase === "blank" && (openState === "open" || summaryBlank === true);
// …
renderSlot("conversation.composer.bar", { variant: hero ? "hero" : "composer", … })
```

A brand-new Session is blank, so it renders the **hero** composer — `variant: "hero"`.
The dock therefore never mounted, `inputActions` was never captured,
`composerActionsBySession` stayed empty, and `fillComposer` returned `false`. The tree
showed a "composer not ready" notice at most, and wrote nothing. The defect was
invisible in a session that already had a turn, which is why it survived the earlier
rounds: every prior check ran against a conversation in the active state.

### Fix

Replaced the bridge with the `conversation` service's service-face path, which has no
variant dependency:

```js
const actx = ctx.sessions.scope(sessionId)
actx.get('conversation').input.for(actx).setDraft(text)
```

Precedent verified in the shipped bundles rather than inferred:
`dsh-client-ui-commands` reaches the same shell with
`binding.ctx.get("conversation")?.input.for(binding.ctx).focus()`, and its `noticeFor`
does `actx.get("conversation"); conversation.input.for(actx).notify(level, text)`.

`SessionInputShell.setDraft(text)` is the public method (it delegates to
`DraftEditorRuntime.setDraft`), and the editor is created by Lexical's `createEditor()`
in the shell constructor — it does not require a DOM mount, so it is callable before the
composer is on screen. That is what makes this work for a blank Session.

`actx.get()` is the non-throwing accessor and needs no `inject` declaration, unlike
direct `ctx.conversation` property access, which throws
`cannot get property "conversation" without inject`. `input.for()` does throw when the
ctx is not a retained Session scope, so the call is wrapped and reports a notice rather
than breaking the sidebar entry.

The click handler now navigates **before** writing the draft, so the text lands in the
composer that is actually on screen.

### Checks

| # | Check | Method | Result |
|---|---|---|---|
| 25 | Bridge fully removed | `grep` for `ComposerBridge` / `composerActionsBySession` | 0 live references (2 remaining hits are explanatory comments) |
| 26 | One slot registered, not two | `grep -c 'ctx.slots.inject'` | 1 (`sidebar.footer.action`) |
| 27 | The slot that remains is not variant-gated | read `dsh-client-ui-sidebar` render | `renderSlot("sidebar.footer.action", { wide })`, unconditional |
| 28 | Service path matches a shipped precedent | read `dsh-client-ui-commands` | same `get("conversation")` → `input.for(actx)` → shell method shape |
| 29 | `setDraft` is public and DOM-independent | read `SessionInputShell` + `DraftEditorRuntime` | `setDraft` public; editor built by `createEditor()`, no mount needed |
| 30 | `sessions.scope(id)` is public | read `ui-input-trigger` / `ui-commands` usage | `sessions.scope(sessionId)` used by both |
| 31 | Services used are declared | cross-check `ctx.<svc>` against `inject` | `slots`, `locale`, `sessions`, `uiWorkspace`, `remote`, `remote.skills`; `conversation` reached via `actx.get()` so it needs no declaration |
| 32 | Syntax | `node --check client.js` | pass |

### Not verified

- **The fix has not been exercised in a browser.** The defect is a render-variant
  condition, so only a real new-session click proves it. The reasoning above is from
  the shipped bundle source, not from a run.
- A page refresh (or a `client-hmr` reload) is required to pick up the new `client.js`.

---

## Round 6 — three teams added, member cap raised

Added `gpt-researcher-team`, `stock-partner-team` and `product-strategy-team`, and
raised the Agent Teams roster cap from 8 to 64.

### Provenance check (source packages on disk)

| Team | Upstream package found? | Method | Consequence |
|---|---|---|---|
| `gpt-researcher-team` | yes — `~/.workbuddy/plugins/marketplaces/experts/plugins/gpt-researcher-team` (lead brief 23.8 KB) | `find` + `wc -c` | ported |
| `stock-partner-team` | yes — `~/.workbuddy-ai/plugins/marketplaces/experts/plugins/stock-partner-team` (6 briefs, 17-31 KB) | `find` + `wc -c` | ported |
| `product-strategy-team` | **no** — only a catalog entry; no `agents/` directory anywhere under either app or data dir | `find` over both apps + both data dirs, plus the 448-entry experts `manifest.json` | **authored** |

`product-strategy-team` is recorded as `source.kind: "authored"` in its `team.json`
rather than `ported`, because its briefs are new DSH text derived from the catalog
description, not upstream wording. Reporting it as ported would have overstated
fidelity.

### Rewrites applied on port

`stock-partner-team` referenced a connector DSH does not have in **40 places**:

| Token | Count in upstream briefs | Action |
|---|---|---|
| `westock-mcp` | 40 | replaced with `web_fetch` / `web_search` / `bash` guidance |
| `westock-tool` / `westock-data` | 16 | replaced |
| `skills/md-to-html` | in the lead SOP | replaced with a self-contained HTML written via `python3` |

A residual-token scan over every generated brief asserts no brief still names a
missing channel as a live instruction. Mentions inside an explicit negation
("this session has no `neodata-financial-search`") are correct and are not flagged;
the check inspects the preceding 160 characters so it does not fire on those.

Two porting bugs were found and fixed by that scan rather than by inspection:

1. **Replacement text was being rewritten.** Inline cleanup ran *after* section
   substitution, so the inserted phrase "no WorkBuddy connector" became the
   nonsense "no 公开数据源 (公开数据源)". Fixed by substituting placeholders first,
   cleaning what remains, then expanding the placeholders.
2. **A section silently failed to match.** Upstream heading
   `## 执行预算（铁律）— 防轮次耗尽` did not match the bare key `## 执行预算（铁律）`,
   so the WorkBuddy-only budget block survived. Fixed by matching the heading as a
   line prefix. The script now prints `!! section not found` instead of failing
   silently.

### Member cap

| Check | Method | Result |
|---|---|---|
| Cap is a profile override, not a hard cap | read the runtime schema and constructor | `maxMembers: z.number().step(1).min(1)` — no upper bound; `positiveLimit` only rejects non-positive / non-safe-integer |
| Patch semantics | read `applyEntryPatches` in `dsh-app-boot` | `target[key] = value` — a **shallow replace** of the whole `config` object |
| Consequence | — | the patch must restate all five limit keys, or the other four silently revert to runtime defaults (`maxTasks` 256, `maxPendingMessagesPerMember` 64, `maxMessageBytes` 65536, `disposalTimeoutMs` 5000) |
| Patch parses | `js-yaml` (the loader's own parser, extracted from the asar) | 6 entries, no syntax error |
| Patch applies | replayed `applyEntryPatches` over the bundle's row | effective config `maxMembers: 64` + all four siblings preserved |
| Runtime accepts it | `positiveLimit` semantics | all five are positive safe integers |

### Catalog checks (all four teams)

| # | Check | Method | Result |
|---|---|---|---|
| 18 | Frontmatter parses for every team | the plugin's own `splitFrontmatter` / `readScalar` | 4/4 OK |
| 19 | `name` in frontmatter == directory name | compared | 4/4 match |
| 20 | `team.json` member count == brief count | counted | 12/6/6/5 == 12/6/6/5 |
| 21 | Every `spawnName` has a brief | cross-checked | 4/4 no gaps |
| 22 | Skill body under the 8192 prune threshold | measured | 4187 / 3910 / 4912 / 3102 |
| 23 | Picker regex matches every team's path | regex vs synthetic paths | 4/4 match, non-team path correctly rejected |
| 24 | Teams reachable through the profile symlink | `ls` on `node_modules/@local/dsh-agent-team/teams/` | 4 directories present |

### Not verified

- **No team was run end-to-end.** All 8 roster slots of the live session were already
  consumed before this change, and the profile disables the direct `subagent` tools,
  so spawning was not possible. The ported briefs are therefore verified as *parseable
  and consistent*, not as *behaviourally correct at runtime*.
- **The raised cap is verified by replaying the patch logic offline**, not by booting
  the app: `desktop` is managed by the Electron app and `dsh --profile desktop
  --dump-config` refuses to run ("profile is managed exclusively by the Electron
  application"). A restart of the app is required for the new cap to take effect.

---

## Round 1-5 — original verification

Date: 2026-09-30 · Profile: `desktop` · DSH `0.2.0-rc.2`

## What was verified

| # | Check | Method | Result |
|---|---|---|---|
| 1 | `index.js` syntax | `node --check` | pass |
| 2 | All JSON manifests parse | `json.load` on 4 files | pass |
| 3 | `icon.svg` well-formed | `ElementTree.parse` | pass |
| 4 | Provider `list()` contract | driven with a fake `ctx.skills` | 1 team, correct `source`/`provider`/`rank`/`invocation`/`resourceBase` |
| 5 | Provider `get()` strips frontmatter | compared to raw file | body 3416 chars, frontmatter removed |
| 6 | Relative `teamsDir` rejected | unit test | throws with clear message |
| 7 | Missing `teamsDir` rejected | unit test | friendly error, not raw ENOENT |
| 8 | Malformed team skipped, others survive | temp dir with one bad + one good team | `good` listed, warning emitted for `bad` |
| 9 | Roster ↔ brief consistency | 12 members cross-checked | every `brief` exists, every `marker` present |
| 10 | `spawnName` grammar | regex vs `[a-z0-9]+(-[a-z0-9]+)*` | all 12 valid |
| 11 | Skill name == directory name | compared | `trading-team` == `trading-team` |
| 12 | Skill body under prune threshold | measured | 3416 < 8192 |
| 13 | Bundle installs into profile | `dsh plugin --profile desktop add` | dependency + bundle entry written |
| 14 | Skill reaches the live catalog | session catalog update | `trading-team` appeared without restart |
| 15 | Skill loads with resources | `skill` tool call | `resourceBase` = team dir, body correct |
| 16 | Resource paths resolve | `ls` + `json.load` via base dir | `members/` and `team.json` readable |
| 17 | Definition layer drives a real teammate | spawned `market-analyst` | see below |

## Smoke test (check 17)

Spawned one teammate using the ported brief, with a bounded 400-character scope.

Observed:

- The teammate **read the ported brief** at the path the SOP instructs and followed its
  role, output marker, and data discipline.
- It emitted the required marker `[市场技术分析报告]` on the final line.
- It delivered the full body to `lead` via `send_message`, as the brief requires.
- **No fabrication:** `web_search` failed (no search key), so it fell back to `web_fetch`
  against two independent quote sources, cross-checked 260 trading days row by row, and
  reported the pre-market gap ("2026-09-30 未开盘") instead of inventing a close.
- It attached a computation appendix (SMA/EMA/MACD/RSI/Bollinger/ATR/VWMA) for the Lead
  to check at compile time.

Roster after the run: `lead` (running) + `market-analyst` (inactive). No orphaned members.

## Known limitations

1. **`web_search` is unavailable in this deployment.** Verified directly: it errors with
   `DeepSeek search has no API key for "DEEPSEEK_API_KEY"`. The briefs now state the
   `web_fetch` fallback explicitly, but a research-heavy team is degraded until a search
   key is configured. This is an environment gap, not a plugin defect.
2. **`maxMembers` is cumulative, not concurrent.** See the section below — this was
   discovered the hard way during the first real run.
3. **No `Config` schema.** The plugin is deliberately dependency-free so installation
   never needs a registry round-trip. Consequence: `config` is read defensively and is not
   validated or shown in the settings UI. Only `teamsDir` (absolute path) is honoured.
4. **Upstream instructions are Chinese-only.** Faithful to the source; not translated.
5. **Not exercised:** the full 12-member workflow. Only one member was spawned, because a
   complete run costs 12 spawns and minutes of wall time. Phases 2–5 (debate ordering,
   handoff relay, adjudication) are specified in the SOP but unproven in this session.
6. **Agent Teams is experimental.** This plugin depends only on `ctx.skills.registerProvider`,
   a stable seam, and not on Team internals — so a Team API change should not break the
   definition layer, though it could break the SOP's tool names.

## Round 2 — findings from the first real run

The 600519 analysis (2026-09-30) ran Phase 1–3 with 8 members and exposed these gaps.

### The `maxMembers` error (corrected)

`maxMembers` is a **cumulative, immutable** cap, not a concurrency limit. The roster never
shrinks and names are never reused, so each spawn permanently consumes a slot for the
session. Verified in the runtime:

```js
if (state.members.length >= this.maxMembers) throw new TeamError(`Team member limit ${this.maxMembers} reached`, "TEAM_MEMBER_LIMIT");
```

The original `team.json` note claimed "Phase 1 needs 4 concurrent and Phase 4 needs 3, so
both fit" — wrong, and it made a 12-member roster look runnable. Corrected in `team.json`,
`SKILL.md`, and `README.md`, and now enforced three ways:

- `/team` prints the remaining budget and flags any team that will not fit.
- The plugin logs a warning at load when a roster exceeds the cap.
- The SOP requires counting slots first and names the degradation order.

### `/team` command (added)

`ctx.commands.register({ name: 'team', ... })` — a read-only catalog. It deliberately does
not spawn: a command runs outside the model turn, so creating teammates there would bypass
the Lead's planning and burn irreversible slots. Optional injection (`ctx.inject(['commands'])`),
so the plugin still loads without a command surface.

### `path` field (added)

`toSummary` preserves exactly `name`, `path`, `description`, `whenToUse`, `invocation`,
`source`, `provider`, `resourceBase`. Adding `path` lets the `/` menu open the playbook on
click. **A `metadata` field was tried and removed**: `toSummary` drops it, so it would have
been dead code reaching no consumer. Roster size is read from `team.json` on demand instead.

### No UI picker (investigated, rejected) — LATER CORRECTED

**This conclusion was wrong and has been reversed.** See "Round 3" below.

The original reasoning: the client exposes no composer or send API, so a panel could
render the catalog but not start the work. The error was concluding from the absence
of a `session.prompt` symbol in *client* bundles that no such capability existed,
without enumerating the remote namespace list.

### Verified live

- Skill catalog: `trading-team` present, loads with correct `resourceBase`.
- SOP update visible on reload (bodies are re-read per load; no reinstall needed).
- Provider contract, `path` propagation, command registration, load-time cap warning: unit-tested.
- **Not verified:** `/team` rendering in the browser. It requires a restart to load the new
  module generation (the bundle is a symlink, so `dsh plugin add` reports "already up to
  date"), and this session has no browser control. Registration is proven; on-screen
  rendering is not.

## Round 3 — the Teams panel

### The correction

`session/prompt` is a real remote method:

- id `@deepseek-ai/dsh-api-session-controller#session/prompt`
- namespace `session`, service `sessionController`
- request `{ requestId, sessionId, mode: 'queue'|'steer', content, clientTimeZone? }`
- result `{ accepted: true }`

The composer's own submit path calls it (`dsh-client-ui-conversation`), and client
plugins reach it as `ctx.remote.session`.

### How activation works without a bespoke API

The host already turns literal `/name` user text into a skill load.
`@deepseek-ai/dsh-tool-skill` registers an `agent/pre-step` listener that scans
direct user input for:

```js
SKILL_GESTURE = /(^|\s)\/([a-z0-9]+(?:-[a-z0-9]+)*)(?=\s|$)/g
```

and injects the matching skill's instructions as a user message. So submitting
`/trading-team <task>` through `session/prompt` loads the team SOP — the same path
the `/` menu uses. No new host capability was needed.

### What the panel registers

| Slot | Value | Purpose |
|---|---|---|
| `sidebar.panellist` | `id: 'agent-teams'`, `order: 1` | nav row directly under Plugins (order 0), before Schedules (order 10) |
| `main` | `key: 'agent-teams'` | the page that row opens |

Verified against the shipped consumers: `dsh-client-ui-sidebar` calls
`ctx.layout.selectPanel(id)` on row click, and `ui-layout`'s `selectPanel` throws
unless a `main` entry with that key is registered — so the id/key pairing is
required, not optional.

### Catalog source

`skills/list` filtered to skills whose `path` matches `teams/<name>/SKILL.md`. The
provider sets `path`, so it identifies this plugin's teams with no custom host route.
The filter regex was unit-tested against POSIX, Windows, nested, and non-team paths
(7 cases, all pass).

### Verified

- `index.js` and `client.js` syntax; all JSON manifests; icon.
- Client bundle id equals the package name (required by the module loader).
- Every API used is one confirmed present in the shipped bundles:
  `ctx.remote.skills.list` (`.ok` / `.value.skills`), `ctx.remote.session.prompt`,
  `ctx.sessions.list` (`getSnapshot`/`subscribe`), `ctx.slots.inject`,
  `ctx.uiWorkspace.openSession`, `ctx.locale.bind`.
- The team-filter regex.

### NOT verified

- **The panel rendering.** It requires a restart: the bundle is a symlink, so
  `dsh plugin add` reports "already up to date", and the Host loaded `index.js`
  before `client.js` existed. Per the plugin docs, replacing an installed package
  requires a restart to load a fresh JavaScript module generation.
- `ctx.sessions.list` shape was read from `dsh-client-ui-session`, not exercised at
  runtime; `retainedBy.mainView` is the same discriminator that bundle uses.
- Whether the `main` slot page receives the injected `operations` prop as assumed.

## Round 4 — the blank-panel bug

### Symptom

After a restart the **Teams** row appeared in the left panel, but clicking it showed
nothing. That combination is diagnostic: the row proved `apply()` had run and every
injected service resolved, so the failure was after `sidebar.panellist` registered.

### Root cause (my bug)

```js
inject: () => operations,          // returns the face itself
...
const { t, operations } = props;   // props.operations === undefined
```

The `inject` return value is **spread onto the component's props directly**
(`runInject` → `bindInjectSources` → spread). Returning `operations` bare hoisted
`listTeams`/`activate` to the top level, so `props.operations` was `undefined` and
the component threw on `operations.currentSessionList()`.

The throw was invisible because `SlotErrorBoundary` catches it and the entry
**abdicates** (`reportEntryError(..., { abdicate: spec.kind !== 'chain' })`), so the
page rendered as nothing at all rather than as an error.

Fixed by wrapping: `inject: () => ({ operations })`.

### Hardening

- Added `TeamsPage`, a hook-free wrapper that reports a missing inject face inside
  the panel instead of throwing. A throw abdicates the entry and shows a blank page;
  an in-panel message is diagnosable. The wrapper exists so the guard runs before any
  hook — an early return inside the stateful component would change hook order.
- Verified hook order: every `useState`/`useEffect`/`useCallback` in `TeamsPanel` is
  unconditional, and all guards sit after them.

### Verified

- The inject→props contract, reproduced directly: the fixed form yields
  `props.operations` present; the old form yields `undefined`.
- `client-hmr` polls every `pollIntervalMs` (500 ms) and calls
  `clientModules.rebuilt(id)` on change, so an edited `client.js` reloads in the open
  page **without a restart**. `rebuilt()` also fires when only mtime/ctime/size move.
- The symlink resolves to the edited file (`~/.dsh/.../client.js` contains the fix).

### Still not verified

- That the panel now renders. The mechanism is fixed and the reload path is
  confirmed, but this session has no browser control, so the on-screen result is
  unconfirmed.

## Round 5 — the missing remote namespace inject

### Symptom

The panel rendered (Round 4 fixed that), but loading the catalog failed with:

```
Load failed: cannot get property "remote.skills" without inject
```

This is a good error: the host refuses a namespace read that the plugin did not
declare, instead of returning `undefined`.

### Root cause (my bug)

The inject list declared `'remote'` but not the namespaces read through it. The
convention requires **both**: `remote` for the facade, and `remote.<namespace>` for
every namespace used. Confirmed across the shipped bundles:

| Bundle | Declares | Uses |
|---|---|---|
| `dsh-client-ui-skill` | `"remote"`, `"remote.skills"` | `ctx.remote.skills.list` |
| `dsh-client-ui-chat` | `"remote"`, `"remote.session"` | `ctx.remote.session.*` |
| `dsh-client-ui-workspace` | `"remote"`, `"remote.directoryPicker"` | `ctx.remote.directoryPicker.*` |

Fixed:

```js
const inject = [
  'slots', 'locale', 'sessions', 'uiWorkspace',
  'remote', 'remote.skills', 'remote.session',
];
```

### Cross-check

Every service the file touches is now declared:

- used: `ctx.effect` (a context method, not a service), `ctx.locale`,
  `ctx.remote`, `ctx.sessions`, `ctx.slots`, `ctx.uiWorkspace`
- declared: `locale`, `remote`, `remote.session`, `remote.skills`, `sessions`,
  `slots`, `uiWorkspace`
- namespaces actually read: `ctx.remote.session`, `ctx.remote.skills` — both declared.

### Verified

- `client.js` syntax.
- Inject list covers every `ctx.<service>` used and every `remote.<ns>` read.
- The symlink resolves to the edited file.

### Still not verified

- That the catalog now loads and a team activates. Reload path is confirmed
  (client-hmr, 500 ms poll) but there is no browser control here.




