import { atom, read, update } from 'claude-code'
import type { Register } from 'claude-code'

// D0 probe: nothing here is product code. It records what the mod API can do.
// Config is read from ../../out/config.json (relative to the plugin root) so
// the same module can be driven from different runs without editing it:
//   { "urls": ["http://127.0.0.1:18080/ping"], "pushAfterMs": 1500,
//     "pushText": "...", "asUser": false, "openPane": true, "tickMs": 300 }

const PANE = 'xmuse-probe'
const state = atom({ plugin: 'xmuse-probe', key: 'ui' } as const, {
  room: 'none',
  joined: '',
  draft: '',
  provider: 'claude',
  presses: 0,
})

function outDir($: any) {
  return `${$.plugin.root}/../out`
}

let chain: Promise<void> = Promise.resolve()

function log($: any, obj: Record<string, unknown>) {
  chain = chain.then(() => logNow($, obj))
  return chain
}

async function logNow($: any, obj: Record<string, unknown>) {
  try {
    const path = `${outDir($)}/claude-probe.log`
    let prev = ''
    try {
      prev = (await $.fs.read(path)) as string
    } catch {
      prev = ''
    }
    const line = JSON.stringify({ t: await $.clock.now(), ...obj })
    await $.fs.write(path, prev + line + '\n')
  } catch (err) {
    $.ui.log(`probe log failed: ${String(err)}`, { to: 'debug' })
  }
}

function short(s: unknown) {
  return typeof s === 'string' ? s.slice(0, 600) : s
}

export const register: Register = on => {
  let ticks = 0

  on('classic.SessionStart', async ($, e, next) => {
    await log($, {
      ev: 'classic.SessionStart',
      session_id: (e as any).session_id,
      transcript_path: (e as any).transcript_path,
      cwd: (e as any).cwd,
      source: (e as any).source,
    })
    return next(e)
  })

  on('session.start', async ($, e, next) => {
    const id = await $.session.id()
    const cwd = await $.session.cwd()
    const ver = await $.session.version()
    const surfaces = await $.session.surfaces()
    await log($, { ev: 'session.start', input: e, sessionId: id, cwd, ver, surfaces })

    await $.command.register({
      name: 'xmuse',
      description: 'xmuse D0 probe: status | join <code> | push',
      argumentHint: 'status | join <code>',
    })

    let cfg: any = {}
    try {
      cfg = JSON.parse((await $.fs.read(`${outDir($)}/config.json`)) as string)
    } catch (err) {
      await log($, { ev: 'config.missing', err: String(err) })
    }

    // 1. $.http.fetch
    for (const url of cfg.urls ?? []) {
      try {
        const t0 = await $.clock.now()
        const r = await $.http.fetch(url, { headers: { 'x-xmuse-session': id } })
        await log($, {
          ev: 'http.fetch',
          url,
          status: r.status,
          ok: r.ok,
          text: short(r.text),
          ms: (await $.clock.now()) - t0,
        })
      } catch (err) {
        await log($, { ev: 'http.fetch.error', url, err: String(err) })
      }
    }
    // POST with header, to see the server echo
    if (cfg.postUrl) {
      try {
        const r = await $.http.fetch(cfg.postUrl, {
          method: 'POST',
          headers: { 'content-type': 'application/json', 'x-xmuse-session': id },
          body: JSON.stringify({ hello: 'from-mod', session: id }),
        })
        await log($, { ev: 'http.post', status: r.status, text: short(r.text) })
      } catch (err) {
        await log($, { ev: 'http.post.error', err: String(err) })
      }
    }

    // 2. $.clock.every
    $.clock.every(cfg.tickMs ?? 300, () => {
      ticks += 1
      if (ticks <= 8) void log($, { ev: 'clock.every.tick', n: ticks })
    })

    // 3. $.prompt.submit wake-up
    if (cfg.pushAfterMs) {
      $.clock.after(cfg.pushAfterMs, async () => {
        await log($, { ev: 'push.submit.begin', asUser: !!cfg.asUser })
        try {
          const r = cfg.asUser
            ? await $.prompt.submit({ text: cfg.pushText ?? 'ping', asUser: true })
            : await $.prompt.submit({ text: cfg.pushText ?? 'ping' })
          await log($, { ev: 'push.submit.done', r })
        } catch (err) {
          await log($, { ev: 'push.submit.error', err: String(err) })
        }
      })
    }

    // 6. pane
    if (cfg.openPane) {
      try {
        const opened = await $.ui.open({ id: PANE, title: 'xmuse probe' })
        await log($, { ev: 'ui.open', opened })
      } catch (err) {
        await log($, { ev: 'ui.open.error', err: String(err) })
      }
    }
    return next(e)
  })

  on('session.end', async ($, e, next) => {
    await log($, { ev: 'session.end', e, ticks })
    return next(e)
  })

  on('prompt.submit', async ($, e, next) => {
    await log($, { ev: 'prompt.submit', origin: e.origin, text: short(e.text), wait: e.wait })
    return next(e)
  })

  on('session.append', async ($, e, next) => {
    const m: any = e.message
    const text = Array.isArray(m.content)
      ? m.content.map((b: any) => (b.type === 'text' ? b.text : `[${b.type}]`)).join('|')
      : m.content
    if (m.role === 'user' || m.type === 'user') {
      await log($, { ev: 'session.append', door: (e as any).door, origin: (e as any).origin, isMeta: m.isMeta, text: short(text) })
    }
    return next(e)
  })

  on('turn.complete', async ($, e, next) => {
    await log($, { ev: 'turn.complete', text: short((e as any).text) })
    return next(e)
  })

  // 5. command.run
  on('command.run', { command: 'xmuse' }, async ($, e) => {
    const [sub, ...rest] = e.args.trim().split(/\s+/)
    const id = await $.session.id()
    await log($, { ev: 'command.run', args: e.args, origin: e.origin, presentation: e.presentation })
    if (sub === 'join') {
      await update($, state, s => ({ ...s, joined: rest[0] ?? '' }))
      return { text: `xmuse join code=${rest[0]} session=${id}`, exitCode: 0 }
    }
    if (sub === 'push') {
      void $.prompt.submit({ text: `XMUSE-PUSH from command ${rest.join(' ')}` })
      return { text: 'push queued' }
    }
    return { text: `xmuse status ok session=${id} args=${JSON.stringify(rest)}` }
  })

  // 6. UI: Pane + AbovePrompt using Input / Select / Button / Markdown
  on('ui.render', { component: 'Pane', requestId: PANE }, async ($, e) => {
    const { Box, Text, Button, Markdown, Input, Select } = $.ui.resolve(e) as any
    const s = (await read($, state)) as any
    return (
      <Box flexDirection="column" gap={1}>
        <Text bold>xmuse room: {s.room}</Text>
        <Text dimColor>surface={e.surface} placement={(e.props as any).placement} cols={(e.props as any).bodyColumns}</Text>
        <Select
          key="provider"
          label="provider"
          value={s.provider}
          options={[
            { value: 'claude', label: 'Claude' },
            { value: 'opencode', label: 'OpenCode' },
            { value: 'dsh', label: 'dsh' },
          ]}
          onSelect={(v: string) => update($, state, (x: any) => ({ ...x, provider: v }))}
        />
        <Input
          key="room-name"
          label="room"
          placeholder="room name"
          value={s.draft}
          submitLabel="create"
          onInput={(v: string) => update($, state, (x: any) => ({ ...x, draft: v }))}
          onSubmit={(v: string) => update($, state, (x: any) => ({ ...x, room: v }))}
        />
        <Box>
          <Button
            key="invite"
            label="Invite"
            variant="primary"
            onPress={() => update($, state, (x: any) => ({ ...x, presses: x.presses + 1 }))}
          />
          <Button key="approve" label="Approve" hotkey="a" onPress={() => update($, state, (x: any) => ({ ...x, presses: x.presses + 10 }))} />
        </Box>
        <Text>presses: {s.presses}</Text>
        <Markdown text={'**timeline**\n\n- @claude hello\n- @dsh ok'} />
      </Box>
    )
  })

  on('ui.render', { component: 'AbovePrompt' }, async ($, e, next) => {
    if ((e.props as any).hasSurvey) return next(e)
    const { Box, Text, Button } = $.ui.resolve(e) as any
    const s = (await read($, state)) as any
    return (
      <Box>
        <Text dimColor>xmuse: 2 unread @ · 1 approval </Text>
        <Button key="open" label="Open" onPress={() => $.ui.open({ id: PANE, title: 'xmuse probe' })} />
        <Text dimColor> presses={s.presses}</Text>
      </Box>
    )
  })
}
