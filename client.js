/**
 * Browser half of the Agent Team Definitions bundle.
 *
 * One contribution: `sidebar.footer.action` — an expandable **Teams** tree in the
 * left sidebar. Clicking a team fills the current composer with `/<team-name> ` and
 * switches to that conversation. It does **not** send: the user adds their own prompt
 * first, and nothing consumes roster slots until they do.
 *
 * How the draft is written: through the `conversation` service's service-face path,
 * `conversation.input.for(actx).setDraft(text)`. `dsh-client-ui-commands` reaches the
 * same shell as `binding.ctx.get("conversation")?.input.for(binding.ctx).focus()`.
 *
 * An earlier revision instead captured the session-scoped `inputActions` prop via a
 * bridge component mounted in `conversation.composer.dock`. That was wrong: the dock
 * only renders when `variant === "composer"`, and a brand-new Session renders the
 * **hero** composer (`variant: hero ? "hero" : "composer"`). So in exactly the case
 * that mattered most — a fresh Session — the bridge never mounted, the captured face
 * was never published, and clicking a team silently did nothing. The service path has
 * no such variant dependency, which is why it replaced the bridge.
 *
 * Why the tree is not in `sidebar.panellist`: that slot renders one flat nav row per
 * entry and hardcodes each row's click to `ctx.layout.selectPanel(id)`. It cannot
 * expand in place, so nesting a team list there is not expressible. `sidebar.panellist`
 * rows also render only a glyph, so a tree would not fit. `sidebar.footer.action` is
 * the one sidebar list slot whose rendering this plugin owns.
 *
 * The gesture itself is the host's: `invokedSkillNames()` in `@deepseek-ai/dsh-tool-skill`
 * scans direct user input for `/name`:
 *   SKILL_GESTURE = /(^|\s)\/([a-z0-9]+(?:-[a-z0-9]+)*)(?=\s|$)/g
 * and injects that skill's instructions, so sending `/<team>` loads the team SOP.
 */
window.__ModuleLoader__.load({
  id: '@local/dsh-agent-team',
  factory(require) {
    const React = require('react');
    const h = React.createElement;

    const NS = 'agent-team-picker';

    const zh = {
      panel: '团队',
      title: 'Agent Teams',
      loading: '正在读取团队…',
      empty: '没有团队定义',
      failed: '读取失败',
      retry: '重试',
      noSession: '没有可用会话',
      filled: '已填入输入框，补充你的问题后发送',
      noComposer: '输入框尚未就绪，请切到该会话后重试',
      budget: (used, cap) => `本会话已用 ${used}/${cap} 个名额（累计，不释放）`,
    };

    const en = {
      panel: 'Teams',
      title: 'Agent Teams',
      loading: 'Loading teams\u2026',
      empty: 'No team definitions',
      failed: 'Load failed',
      retry: 'Retry',
      noSession: 'No session available',
      filled: 'Inserted into the composer \u2014 add your question, then send',
      noComposer: 'Composer not ready yet; open that conversation and retry',
      budget: (used, cap) => `${used}/${cap} team slots used this session (cumulative)`,
    };

    /** Small roster glyph, drawn locally so no Harness Client package is imported. */
    function TeamsGlyph({ size }) {
      const s = size ?? 15;
      return h(
        'svg',
        {
          viewBox: '0 0 16 16', width: s, height: s, fill: 'none',
          stroke: 'currentColor', strokeWidth: 1.4,
          strokeLinecap: 'round', strokeLinejoin: 'round', 'aria-hidden': true,
        },
        h('circle', { cx: 8, cy: 3.6, r: 2 }),
        h('circle', { cx: 3.4, cy: 12.2, r: 1.8 }),
        h('circle', { cx: 12.6, cy: 12.2, r: 1.8 }),
        h('path', { d: 'M6.6 5.3 4.4 10.6M9.4 5.3l2.2 5.3M5.2 12.2h5.6' }),
      );
    }

    /** Chevron indicating expand/collapse; rotates via CSS transform. */
    function Chevron({ open }) {
      return h(
        'svg',
        {
          viewBox: '0 0 16 16', width: 12, height: 12, fill: 'none',
          stroke: 'currentColor', strokeWidth: 1.5,
          strokeLinecap: 'round', strokeLinejoin: 'round', 'aria-hidden': true,
          style: { transform: open ? 'rotate(90deg)' : 'none', transition: 'transform .12s' },
        },
        h('path', { d: 'M6 3.5 10.5 8 6 12.5' }),
      );
    }

    /**
     * The expandable Teams section in the sidebar foot.
     *
     * Collapsed it is one row; expanded it lists the team definitions beneath itself,
     * so picking a team never leaves the sidebar.
     */
    function TeamsTree(props) {
      const { t, wide, operations } = props;
      const [open, setOpen] = React.useState(false);
      const [teams, setTeams] = React.useState(null);
      const [error, setError] = React.useState(null);
      const [notice, setNotice] = React.useState(null);

      const [list, setList] = React.useState(() => operations.currentSessionList());
      const sessionId = operations.targetSessionId(list);

      React.useEffect(() => operations.subscribeSessionList(setList), [operations]);

      const load = React.useCallback(async () => {
        if (sessionId === undefined) return;
        setError(null);
        setTeams(null);
        try {
          setTeams(await operations.listTeams(sessionId));
        } catch (cause) {
          setError(String(cause?.message ?? cause));
        }
      }, [sessionId, operations]);

      React.useEffect(() => {
        if (open) load();
      }, [open, load]);

      const pick = (team) => {
        setNotice(null);
        if (sessionId === undefined) {
          setNotice(t('noSession'));
          return;
        }
        // Navigate first, then write the draft. `fillComposer` resolves the shell
        // through the service face, so this order guarantees the text lands in the
        // composer that is actually on screen. Never send: the user still has to
        // write their own question, and sending would burn roster slots.
        operations.openConversation(sessionId);
        const filled = operations.fillComposer(sessionId, `/${team.name} `);
        setNotice(filled ? t('filled') : t('noComposer'));
      };

      const rows = [];
      if (open) {
        if (error !== null) {
          rows.push(h('div', { key: 'err', style: S.errorRow },
            h('span', { style: S.errorText }, `${t('failed')}: ${error}`),
            h('button', { type: 'button', style: S.retry, onClick: load }, t('retry'))));
        } else if (teams === null) {
          rows.push(h('div', { key: 'loading', style: S.muted }, t('loading')));
        } else if (teams.length === 0) {
          rows.push(h('div', { key: 'empty', style: S.muted }, t('empty')));
        } else {
          for (const team of teams) {
            rows.push(h('button', {
              key: team.name,
              type: 'button',
              title: team.description ?? `/${team.name}`,
              style: S.teamRow,
              onClick: () => pick(team),
            },
              h('code', { style: S.teamName }, `/${team.name}`),
              team.description === undefined ? null : h('span', { style: S.teamDesc }, team.description)));
          }
        }
      }

      return h('div', { style: S.root },
        h('button', {
          type: 'button',
          style: S.header,
          'aria-expanded': open,
          onClick: () => setOpen((value) => !value),
        },
          h('span', { style: S.headerGlyph }, h(TeamsGlyph, { size: wide ? 15 : 18 })),
          wide ? h('span', { style: S.headerLabel }, t('panel')) : null,
          wide ? h('span', { style: S.headerChevron }, h(Chevron, { open })) : null),
        open && wide ? h('div', { style: S.body }, rows) : null,
        notice === null ? null : h('div', { style: S.notice }, notice));
    }

    const S = {
      // `sidebar.footer.action` renders inside a horizontal flex row, so the tree
      // claims the full width instead of sitting beside a sibling action.
      root: { display: 'flex', flexDirection: 'column', gap: 2, width: '100%', minWidth: 0 },
      header: {
        display: 'flex', alignItems: 'center', gap: 8, width: '100%',
        padding: '6px 6px', border: 0, borderRadius: 6, cursor: 'pointer',
        background: 'transparent', color: 'var(--dsw-alias-label-tertiary)',
        fontSize: 12, textAlign: 'left',
      },
      headerGlyph: { display: 'inline-flex', alignItems: 'center', flex: 'none' },
      headerLabel: { flex: '1 1 auto', minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' },
      headerChevron: { display: 'inline-flex', alignItems: 'center', flex: 'none', opacity: 0.8 },
      body: { display: 'flex', flexDirection: 'column', gap: 2, paddingLeft: 10, marginBottom: 2 },
      teamRow: {
        display: 'flex', flexDirection: 'column', alignItems: 'flex-start', gap: 2,
        width: '100%', padding: '5px 8px', border: 0, borderRadius: 6,
        background: 'transparent', color: 'var(--dsw-alias-label-secondary)',
        cursor: 'pointer', textAlign: 'left',
      },
      teamName: { fontSize: 11.5, fontWeight: 600, color: 'var(--dsw-alias-label-primary)' },
      teamDesc: {
        fontSize: 10.5, lineHeight: '14px', color: 'var(--dsw-alias-label-tertiary)',
        display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical', overflow: 'hidden',
      },
      muted: { padding: '4px 8px', fontSize: 11, color: 'var(--dsw-alias-label-tertiary)' },
      errorRow: { display: 'flex', alignItems: 'center', gap: 8, padding: '4px 8px' },
      errorText: { fontSize: 11, color: 'var(--dsw-alias-state-error-primary)', minWidth: 0, overflow: 'hidden' },
      retry: {
        flex: 'none', padding: '2px 8px', fontSize: 10.5, cursor: 'pointer',
        background: 'transparent', color: 'var(--dsw-alias-label-secondary)',
        border: '0.5px solid var(--dsw-alias-border-l2)', borderRadius: 5,
      },
      notice: { padding: '3px 8px 5px', fontSize: 10.5, lineHeight: '14px', color: 'var(--dsw-alias-label-tertiary)' },
    };

    // `remote` alone is not enough: each namespace used must also be declared, or
    // the property read throws "cannot get property "remote.<ns>" without inject".
    // Mirrors dsh-client-ui-skill (remote.skills).
    const inject = [
      'slots',
      'locale',
      'sessions',
      'uiWorkspace',
      'remote',
      'remote.skills',
    ];

    function apply(ctx) {
      const t = ctx.locale.bind(NS);
      ctx.effect(() => ctx.locale.register(NS, { zh, en }), 'agent-team-picker: dictionaries');

      /** Pick the Session a pick should target: the one in the main view, else the newest. */
      function targetSessionId(list) {
        const byId = list?.byId ?? {};
        const ids = Object.keys(byId);
        if (ids.length === 0) return undefined;
        return ids.find((id) => (byId[id]?.retainedBy?.mainView ?? 0) > 0) ?? ids[ids.length - 1];
      }

      const operations = {
        subscribeSessionList(listener) {
          listener(ctx.sessions.list.getSnapshot());
          return ctx.sessions.list.subscribe(() => listener(ctx.sessions.list.getSnapshot()));
        },
        currentSessionList() {
          return ctx.sessions.list.getSnapshot();
        },
        targetSessionId,
        /** User-invocable skills whose path sits under a team directory. */
        async listTeams(sessionId) {
          const result = await ctx.remote.skills.list({ sessionId });
          if (!result.ok) throw new Error(`${result.error.code}: ${result.error.message}`);
          return (result.value.skills ?? [])
            .filter((skill) => typeof skill.path === 'string' && /[\\/]teams[\\/][^\\/]+[\\/]SKILL\.md$/.test(skill.path))
            .map((skill) => ({
              name: skill.name,
              description: typeof skill.description === 'string' ? skill.description : undefined,
            }));
        },
        /**
         * Replace the Session's composer draft. Does not send.
         *
         * Goes through the `conversation` service's documented service-face path:
         * `conversation.input.for(actx).setDraft(text)`. This is the same accessor
         * `dsh-client-ui-commands` uses (`binding.ctx.get("conversation")?.input
         * .for(binding.ctx).focus()`), and it works regardless of which composer
         * variant is on screen.
         *
         * The earlier implementation captured `inputActions` from a bridge mounted in
         * the session-scoped `conversation.composer.dock` slot. That slot only renders
         * when `variant === "composer"`, and a brand-new session renders the **hero**
         * composer (`variant: hero ? "hero" : "composer"`), so the bridge never
         * mounted in a new session and clicking a team silently did nothing.
         *
         * @param sessionId - target Session.
         * @param text - full next draft text.
         * @returns whether the draft was written.
         */
        fillComposer(sessionId, text) {
          const actx = ctx.sessions.scope(sessionId);
          if (actx === undefined) return false;
          // `actx.get` is the non-throwing accessor (unlike direct `ctx.conversation`
          // property access, which requires the name in `inject`). `input.for()`
          // throws when the ctx is not a retained Session scope, so guard it: a
          // failure here must surface as a notice, not as a broken sidebar entry.
          const conversation = actx.get('conversation');
          if (conversation === undefined) return false;
          try {
            conversation.input.for(actx).setDraft(text);
            return true;
          } catch {
            return false;
          }
        },
        openConversation(sessionId) {
          ctx.uiWorkspace.openSession(sessionId);
        },
      };

      // The expandable Teams tree in the sidebar foot. The inject face is wrapped in
      // a named key: the renderer spreads it onto props, so returning `operations`
      // bare would leave `props.operations` undefined and crash the entry.
      ctx.slots.inject('sidebar.footer.action', () => ctx.slots.register({
        name: 'sidebar.footer.action',
        id: 'agent-teams',
        order: 50,
        locale: NS,
        inject: () => ({ operations }),
      }, TeamsTree));
    }

    return { inject, apply };
  },
});
