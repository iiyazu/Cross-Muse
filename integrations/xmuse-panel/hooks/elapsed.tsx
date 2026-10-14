import type { ClientModule } from 'claude-code'

// Surface module (a Client region): the once-a-second elapsed time of a running member. It counts on its own timer, so the
// panel is not redrawn every second. Props are plain data; baseMs is the host clock ($.clock.now()) when the panel drew.
// The sandbox Date.now is not the host clock, so the time shown is baseMs plus the ticks counted here.
// fmtElapsed, elapsedLevel and the two colours are copies of ./logic.ts (a surface module has no documented import): keep them in step.

type ElProps = { startedAt: number; baseMs: number; kind: string } // kind: 'dots' (dots and time), 'plain', 'level' (coloured by age)
type ElState = { base: number; ticks: number }

const C_AMBER = 'warning'
const C_RED = 'error'

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

const Elapsed: ClientModule<ElProps, ElState> = (p, surface) => {
  const { Text } = surface.elements
  const st = surface.state
  if (!st) {
    // start the one timer; the callback reads the live state, so it follows the props of later draws
    surface.setState({ base: p.baseMs, ticks: 0 })
    surface.every(1000, () => {
      const s = surface.state
      if (s) surface.setState({ base: s.base, ticks: s.ticks + 1 })
    })
  } else if (st.base !== p.baseMs) {
    surface.setState({ base: p.baseMs, ticks: 0 }) // the panel redrew with a fresh clock reading: count from it
  }
  const ticks = st && st.base === p.baseMs ? st.ticks : 0
  const now = p.baseMs + ticks * 1000
  const t = fmtElapsed(p.startedAt, now)
  if (p.kind === 'dots') {
    const dots = ['·  ', '·· ', '···'][Math.floor(now / 1000) % 3]!
    return <Text dimColor>{`${dots} ${t}`}</Text>
  }
  if (p.kind === 'level') {
    const lvl = elapsedLevel(p.startedAt, now)
    return <Text color={lvl === 2 ? C_RED : lvl === 1 ? C_AMBER : undefined} dimColor={lvl === 0}>{` ${t}`}</Text>
  }
  return <Text dimColor>{` ${t}`}</Text>
}

export default Elapsed
