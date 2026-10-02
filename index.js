/**
 * Agent Team Definitions — a declarative layer over the experimental Agent Teams runtime.
 *
 * Each directory under `teams/` is one reusable team definition:
 *
 *   teams/<team-name>/
 *     SKILL.md        the Lead's SOP playbook (registered as a model-invocable skill)
 *     team.json       machine-readable roster: lead, members, phases, workflows
 *     members/*.md    one brief per teammate, passed as the `prompt` of spawn_teammate
 *
 * The plugin registers one skill per team through `ctx.skills.registerProvider()`,
 * the same seam `@deepseek-ai/dsh-skill-office` uses for its bundled Office skills.
 * Skill bodies stay small on purpose: the SOP points at `members/*.md`, and the
 * Lead reads a member brief only when it is about to spawn that teammate.
 *
 * Deliberately dependency-free. A Host-only bundle needs no dependencies, and
 * importing `@deepseek-ai/schemastery` or `@deepseek-ai/dsh-skill` would force a
 * registry round-trip at install time. The cost is that this plugin declares no
 * `Config` schema, so the row's config is read defensively instead of validated.
 */

import { readFileSync, readdirSync, statSync } from 'node:fs';
import { readFile } from 'node:fs/promises';
import { join, isAbsolute, basename } from 'node:path';
import { fileURLToPath } from 'node:url';

/** Cordis plugin name. */
export const name = 'agent-team-definitions';

/** The skill registry is the only service this plugin needs. */
export const inject = ['skills'];

/** Provider name shown to the skill registry. */
const PROVIDER = 'dsh-agent-team';

/** `BUNDLED_SKILL_RANK` from `@deepseek-ai/dsh-skill`; hardcoded to stay dependency-free. */
const BUNDLED_SKILL_RANK = 600;

/** Only kebab-case names satisfy the registry's skill-name grammar. */
const SKILL_NAME = /^[a-z0-9]+(?:-[a-z0-9]+)*$/;

/**
 * Read one scalar or folded/literal block scalar from a YAML frontmatter block.
 * This is a deliberately small subset: enough for `name`, `description`, and
 * `whenToUse`, which is all a skill summary needs.
 *
 * @param {string} block - the text between the leading and trailing `---`.
 * @param {string} key - the top-level key to read.
 * @returns {string | undefined} the resolved value.
 */
function readScalar(block, key) {
  const match = new RegExp(`^${key}:[ \\t]*(.*)$`, 'm').exec(block);
  if (match === null) return undefined;
  const inline = match[1].trim();
  if (!/^[>|][+-]?$/.test(inline)) return inline.replace(/^["']|["']$/g, '').trim() || undefined;
  // Folded (`>`) or literal (`|`) block: consume the more-indented following lines.
  const lines = [];
  for (const line of block.slice(match.index + match[0].length).split('\n')) {
    if (line.trim() === '') continue;
    if (!/^\s/.test(line)) break;
    lines.push(line.trim());
  }
  return lines.join(' ').trim() || undefined;
}

/**
 * Split a `SKILL.md` into its frontmatter and body.
 *
 * @param {string} raw - the file contents.
 * @param {string} path - the file path, for error messages.
 * @returns {{ block: string, body: string }} the frontmatter block and trimmed body.
 */
function splitFrontmatter(raw, path) {
  const match = /^---\r?\n([\s\S]*?)\r?\n---(?:\r?\n|$)/u.exec(raw);
  if (match === null) throw new Error(`${PROVIDER}: ${path} has no YAML frontmatter`);
  return { block: match[1], body: raw.slice(match[0].length).trim() };
}

/**
 * Resolve the directory holding team definitions.
 *
 * @param {object} config - the loader row's config.
 * @returns {string} an absolute directory path.
 */
function resolveTeamsDir(config) {
  const configured = config?.teamsDir;
  if (typeof configured === 'string' && configured.length > 0) {
    if (!isAbsolute(configured)) throw new Error(`${PROVIDER}: teamsDir must be an absolute path`);
    return configured;
  }
  return fileURLToPath(new URL('./teams/', import.meta.url));
}

/**
 * Enumerate the team definitions on disk. Re-read on every call so a newly added
 * team directory reaches the next skill catalog without reinstalling the plugin.
 *
 * A malformed team is skipped with a warning rather than failing the whole
 * provider: one bad directory must not hide every other team from the catalog.
 *
 * @param {string} teamsDir - the directory holding one subdirectory per team.
 * @param {(message: string) => void} warn - sink for skipped-definition diagnostics.
 * @returns {Array<{ name: string, description: string, whenToUse?: string, dir: string, locator: string }>}
 */
function scanTeams(teamsDir, warn) {
  let entries;
  try {
    entries = readdirSync(teamsDir, { withFileTypes: true });
  } catch (error) {
    if (error?.code === 'ENOENT') return [];
    throw error;
  }
  const teams = [];
  for (const entry of entries) {
    if (!entry.isDirectory()) continue;
    const teamName = entry.name;
    if (!SKILL_NAME.test(teamName)) continue;
    const dir = join(teamsDir, teamName);
    const locator = join(dir, 'SKILL.md');
    let raw;
    try {
      raw = readFileSync(locator, 'utf8');
    } catch {
      continue; // A directory without SKILL.md is not a team definition.
    }
    let block;
    let description;
    try {
      ({ block } = splitFrontmatter(raw, locator));
      description = readScalar(block, 'description');
      if (description === undefined) throw new Error('frontmatter has no description');
    } catch (error) {
      warn(`skipping team "${teamName}": ${error.message}`);
      continue;
    }
    teams.push({
      name: teamName,
      description,
      whenToUse: readScalar(block, 'whenToUse'),
      dir,
      locator,
    });
  }
  return teams.sort((a, b) => a.name.localeCompare(b.name));
}

/**
 * Read the roster and phase plan out of a team's `team.json`.
 *
 * The skill body stays small by pointing at this file instead of inlining twelve
 * briefs, so the loader surfaces the facts a Lead needs to plan a run: how many
 * members the roster wants, and which phases exist. A missing or malformed
 * `team.json` degrades to "unknown size" rather than failing the catalog.
 *
 * @param {string} dir - the team directory.
 * @param {(message: string) => void} warn - diagnostic sink.
 * @returns {{ memberCount: number | null, phaseCount: number | null, lead: string | null, error?: string }}
 */
function readRoster(dir, warn) {
  try {
    const raw = readFileSync(join(dir, 'team.json'), 'utf8');
    const parsed = JSON.parse(raw);
    const members = Array.isArray(parsed?.members) ? parsed.members.length : null;
    const phases = Array.isArray(parsed?.phases) ? parsed.phases.length : null;
    const lead = typeof parsed?.lead?.displayName?.zh === 'string'
      ? parsed.lead.displayName.zh
      : (typeof parsed?.lead?.name === 'string' ? parsed.lead.name : null);
    return { memberCount: members, phaseCount: phases, lead };
  } catch (error) {
    if (error?.code !== 'ENOENT') warn(`team "${basename(dir)}" has an unreadable team.json: ${error.message}`);
    return { memberCount: null, phaseCount: null, lead: null, error: error?.code === 'ENOENT' ? 'missing' : 'invalid' };
  }
}

/**
 * Register one skill per team definition.
 *
 * @param {import('@deepseek-ai/cordis').Context} ctx - the plugin context.
 * @param {{ teamsDir?: string }} [config] - optional loader row config.
 */
export function apply(ctx, config = {}) {
  const teamsDir = resolveTeamsDir(config);
  let isDirectory = false;
  try {
    isDirectory = statSync(teamsDir).isDirectory();
  } catch (error) {
    if (error?.code !== 'ENOENT') throw error;
  }
  if (!isDirectory) {
    throw new Error(`${PROVIDER}: teamsDir does not exist or is not a directory: ${teamsDir}`);
  }

  const warn = (message) => {
    if (typeof ctx?.logger?.warn === 'function') ctx.logger.warn(`${PROVIDER}: ${message}`);
  };

  const provider = {
    name: PROVIDER,
    list: () => Promise.resolve(
      scanTeams(teamsDir, warn).map((team) => ({
        name: team.name,
        description: team.description,
        ...(team.whenToUse !== undefined ? { whenToUse: team.whenToUse } : {}),
        invocation: { modelInvocable: true, userInvocable: true },
        provider: PROVIDER,
        source: 'bundled',
        rank: BUNDLED_SKILL_RANK,
        // Resolving relative paths against this directory is how the Lead reaches
        // `members/*.md` and `team.json` without any path baked into the SOP.
        resourceBase: { kind: 'directory', path: team.dir },
        locator: team.locator,
        // `path` is the one extra field `toSummary` preserves, and the `/` menu uses
        // it to open the playbook on click. Roster size is NOT carried here:
        // `toSummary` drops `metadata`, so it would never reach a consumer.
        path: team.locator,
      })),
    ),
    async get(candidate, options) {
      const { rank: _rank, locator, ...summary } = candidate;
      const raw = await readFile(locator, { encoding: 'utf8', signal: options?.signal });
      return { ...summary, content: splitFrontmatter(raw, locator).body };
    },
  };

  ctx.skills.registerProvider(() => provider);

  registerTeamCommand(ctx, teamsDir, warn);

  // Warn at load when a roster cannot fit the runtime's member cap. The cap is
  // cumulative for the session, so a team larger than it can never run in full —
  // better to say so here than to fail partway through a multi-phase run.
  if (typeof ctx.inject === 'function') {
    ctx.inject(['agentTeams'], (teamCtx) => {
      const cap = teamCtx.agentTeams?.config?.maxMembers;
      if (typeof cap !== 'number') return;
      for (const team of scanTeams(teamsDir, warn)) {
        const roster = readRoster(team.dir, warn);
        if (roster.memberCount !== null && roster.memberCount > cap) {
          warn(
            `team "${team.name}" declares ${roster.memberCount} members but the Agent Teams cap is ${cap} `
            + `(cumulative per session, never freed). It can only run a degraded prefix; raise maxMembers on the `
            + 'agent-team row or start a fresh session to run it in full.',
          );
        }
      }
    });
  }
}

/**
 * Render the team catalog for the `/team` command.
 *
 * @param {Array<{ name: string, description: string, dir: string, memberCount: number|null, phaseCount: number|null, lead: string|null }>} teams
 * @param {{ running: number, cap: number|null, names: string[] }} roster - live Team state.
 * @returns {string} plain-text output for the command surface.
 */
function renderCatalog(teams, roster) {
  if (teams.length === 0) {
    return 'No team definitions found. Add a directory under teams/ with a SKILL.md to define one.';
  }
  const lines = ['Available Agent Teams', ''];
  for (const team of teams) {
    const size = team.memberCount === null ? '? members' : `${team.memberCount} members`;
    const phases = team.phaseCount === null ? '' : `, ${team.phaseCount} phases`;
    lines.push(`  ${team.name} — ${size}${phases}`);
    if (team.lead !== null) lines.push(`    Lead: ${team.lead}`);
    lines.push(`    ${team.description.split('\n')[0].slice(0, 160)}`);
    lines.push('');
  }
  // Surface the slot budget up front: the runtime's member cap is cumulative for
  // the session, so a Lead that does not count first will hit TEAM_MEMBER_LIMIT
  // partway through a multi-phase run.
  lines.push('Team slots');
  if (roster.cap === null) {
    lines.push('  live roster unavailable; assume the cap applies for the whole session.');
  } else {
    const used = roster.running;
    lines.push(`  ${used} of ${roster.cap} used this session (cumulative — spawning never frees a slot).`);
    if (roster.names.length > 0) lines.push(`  Already spawned: ${roster.names.join(', ')}`);
    const remaining = Math.max(0, roster.cap - used);
    lines.push(`  Remaining: ${remaining}`);
    for (const team of teams) {
      if (team.memberCount !== null && team.memberCount > remaining) {
        lines.push(`  ! ${team.name} wants ${team.memberCount} members but only ${remaining} remain — it will degrade.`);
      }
    }
  }
  lines.push('');
  lines.push('Invoke one by loading its skill (e.g. `/trading-team` or the skill tool), then follow its SOP.');
  return lines.join('\n');
}

/**
 * Register the `/team` discovery command.
 *
 * The command is a read-only catalog. It deliberately does not spawn anything:
 * a command runs outside the model turn, so silently creating teammates there
 * would bypass the Lead's planning and burn irreversible roster slots.
 *
 * `commands` is injected optionally — the plugin still loads in compositions that
 * have no command surface.
 *
 * @param {import('@deepseek-ai/cordis').Context} ctx - the plugin context.
 * @param {string} teamsDir - the team definitions directory.
 * @param {(message: string) => void} warn - diagnostic sink.
 */
function registerTeamCommand(ctx, teamsDir, warn) {
  if (typeof ctx.inject !== 'function') return;
  ctx.inject(['commands'], (commandCtx) => {
    commandCtx.commands.register({
      name: 'team',
      description: 'List available Agent Teams and the remaining team slots for this session',
      input: { hint: '[<team-name>]' },
      handler: async (invocation) => {
        const teams = scanTeams(teamsDir, warn).map((team) => {
          const roster = readRoster(team.dir, warn);
          return { ...team, ...roster };
        });
        const requested = invocation.rawInput.trim();
        if (requested.length > 0) {
          const match = teams.find((team) => team.name === requested);
          if (match === undefined) {
            return { kind: 'error', text: `Unknown team "${requested}". Run /team to list the definitions.` };
          }
          const size = match.memberCount === null ? 'unknown size' : `${match.memberCount} members`;
          const phases = match.phaseCount === null ? '' : ` across ${match.phaseCount} phases`;
          return {
            kind: 'success',
            text: [
              `${match.name} — ${size}${phases}`,
              match.lead === null ? '' : `Lead: ${match.lead}`,
              '',
              match.description,
              '',
              `Playbook: ${join(match.dir, 'SKILL.md')}`,
              `Roster:   ${join(match.dir, 'team.json')}`,
              `Members:  ${join(match.dir, 'members')}/`,
            ].filter((line) => line !== '').join('\n'),
          };
        }
        return { kind: 'success', text: renderCatalog(teams, liveRoster(ctx, invocation)) };
      },
    });
  });
}

/**
 * Read the live Team roster, when the Agent Teams service is mounted.
 *
 * @param {import('@deepseek-ai/cordis').Context} ctx - the plugin context.
 * @param {{ agent: unknown }} invocation - the command invocation carrying the receiving agent.
 * @returns {{ running: number, cap: number|null, names: string[] }} roster facts.
 */
function liveRoster(ctx, invocation) {
  const teams = ctx.get?.('agentTeams');
  if (teams === undefined || teams === null) return { running: 0, cap: null, names: [] };
  try {
    const members = teams.listMembers(invocation.agent) ?? [];
    const names = members.filter((member) => member.role !== 'lead').map((member) => member.target ?? member.name);
    const cap = teams.config?.maxMembers ?? null;
    return { running: names.length, cap, names };
  } catch {
    // Outside a Team member context, or before the Team is active.
    return { running: 0, cap: teams.config?.maxMembers ?? null, names: [] };
  }
}
