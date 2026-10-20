import type { ClientModule } from 'claude-code'

// Surface module (a Client region): the live parts of a working member, drawn without redrawing the panel.
//   part 'act'   : "正在：<tool or last line> · m:ss" (the working strip)
//   part 'draft' : the member's latest partial output, typed in a few steps (the draft bubble body)
// One timer per instance (every 250 ms): every 4th tick it posts { live: part, id } and the ui.message hook in
// register.tsx answers with fresh props (liveProps), so the panel itself is not redrawn. The draft's typing runs on the
// same timer. The elapsed time is computed from the latest props (nowMs is the host clock when the hook answered).
// startMsOf, fmtElapsed, elapsedLevel, draftTail and softBreak are copies of ./logic.ts / ./elapsed.tsx (a surface module
// has no documented import): keep them in step.

type LiveProps = { part: string; id: string; tool: string; text: string; startedAt: number; nowMs: number }
type LiveState = { shown: number; text: string }

const C_AMBER = 'warning'
const C_RED = 'error'
const TICK_MS = 250
const POST_EVERY = 4 // ticks between two posts: once a second

// the newest props of each instance, for its timer (the timer was made by the first render, whose `p` is stale by then)
const latest = new Map<string, LiveProps>()

function startMsOf(startedAt: number | undefined): number {
  if (typeof startedAt !== 'number' || !isFinite(startedAt) || startedAt <= 0) return 0
  return startedAt > 1e11 ? startedAt : startedAt * 1000
}

function fmtElapsed(startedAt: number | undefined, nowMs: number): string {
  const s = startMsOf(startedAt)
  if (!s || !nowMs) return '0:00'
  const sec = Math.max(0, Math.floor((nowMs - s) / 1000))
  const p = (n: number) => String(n).padStart(2, '0')
  const h = Math.floor(sec / 3600)
  const m = Math.floor((sec % 3600) / 60)
  return h > 0 ? `${h}:${p(m)}:${p(sec % 60)}` : `${m}:${p(sec % 60)}`
}

function elapsedLevel(startedAt: number | undefined, nowMs: number): number {
  const s = startMsOf(startedAt)
  if (!s || !nowMs) return 0
  const sec = (nowMs - s) / 1000
  return sec > 900 ? 2 : sec > 300 ? 1 : 0
}

function draftTail(text: string, max = 280): string {
  const t = String(text ?? '').trim()
  if (t.length <= max) return t
  let s = t.slice(-max)
  const nl = s.indexOf('\n')
  if (nl >= 0 && nl < 80) s = s.slice(nl + 1)
  return '…' + s
}

/** Zero-width breaks every 16 characters in runs of 28+ characters that are not space or CJK (a path, a hash). */
function softBreak(text: string): string {
  return String(text ?? '').split('\n').map(line => {
    if (!/\S{28,}/.test(line)) return line
    return line.split(/(\s+)/).map(tok => {
      if (tok.length < 28 || /\s/.test(tok)) return tok
      return tok.replace(/[^\s　-鿿＀-￯]{16}(?=[^\s　-鿿＀-￯])/g, s => s + '​')
    }).join('')
  }).join('\n')
}

/** Text a surface can always take: no control characters but tab and newline, and no half of a surrogate pair at a cut. */
function clean(s: string): string {
  const t = s.replace(/\r\n?/g, '\n').replace(/[\u0000-\u0008\u000b-\u001f\u007f]/g, '')
  const last = t.charCodeAt(t.length - 1)
  return last >= 0xd800 && last <= 0xdbff ? t.slice(0, -1) : t
}

function lastLine(text: string): string {
  const ls = String(text ?? '').split('\n').map(x => x.trimEnd()).filter(x => x.trim())
  const l = ls[ls.length - 1] ?? ''
  return l.length > 160 ? l.slice(0, 160) + '…' : l
}

/** How much of `text` to show, given the state: an extension of what was seen keeps its shown length, anything else shows at once. */
function shownOf(st: LiveState | undefined, text: string): number {
  if (!st) return text.length
  if (st.text === text) return Math.min(st.shown, text.length)
  return text.startsWith(st.text) ? Math.min(st.shown, text.length) : text.length
}

const Live: ClientModule<LiveProps, LiveState> = (p, surface) => {
  const { Box, Text } = surface.elements
  const key = `${p.part}:${p.id}`
  latest.set(key, p)
  const st = surface.state
  if (!st) {
    // the one timer; it reads the newest props and the live state each tick
    surface.setState({ shown: p.text.length, text: p.text })
    let n = 0
    surface.every(TICK_MS, () => {
      n++
      const cur = latest.get(key)
      if (!cur) return
      if (cur.part === 'draft') {
        const s = surface.state
        const sh = shownOf(s, cur.text)
        const len = cur.text.length
        const next = sh >= len ? len : Math.min(len, sh + Math.max(1, Math.ceil((len - sh) / 2)))
        if (!s || s.text !== cur.text || s.shown !== next) surface.setState({ shown: next, text: cur.text })
      }
      if (n % POST_EVERY === 0) surface.post({ live: cur.part, id: cur.id })
    })
  }

  const t = fmtElapsed(p.startedAt, p.nowMs)
  if (p.part === 'draft') {
    const prefix = clean(p.text.slice(0, shownOf(st, p.text)))
    return <Text dimColor>{`${softBreak(draftTail(prefix))} ▍`}</Text>
  }
  const lvl = elapsedLevel(p.startedAt, p.nowMs)
  return (
    <Box flexDirection="row" minWidth={0}>
      <Box flexShrink={1} minWidth={0} overflow="hidden">
        <Text dimColor wrap="truncate-end">{`正在：${p.tool || lastLine(p.text) || '思考中'}`}</Text>
      </Box>
      <Box flexShrink={0}>
        <Text color={lvl === 2 ? C_RED : lvl === 1 ? C_AMBER : undefined} dimColor={lvl === 0}>{` ${t}`}</Text>
      </Box>
    </Box>
  )
}

export default Live
