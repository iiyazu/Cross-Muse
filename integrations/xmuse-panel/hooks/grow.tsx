import type { ClientModule } from 'claude-code'

// Surface module (a Client region): text that grows step by step (the typing effect of a running member's draft, the
// reveal of a new message). Its own timer advances it, so the panel is not redrawn per step. When the last step is
// shown it posts { grown: id } (ui.message in register.tsx) and the panel swaps in its normal rendering.
// draftTail is a copy of ./logic.ts (a surface module has no documented import): keep it in step.

type GrowProps = {
  id: string // 't:<member>:<run>' or 'r:<message id>:<run>'; posted back when done
  text: string
  from: number // characters shown before the first step
  stepMs: number
  steps: number[] // cumulative shown lengths, the last one is text.length
  mode: string // 'draft' (dim tail in a bubble in the making) or 'md' (a message, Markdown)
}
type GrowState = { i: number }

function draftTail(text: string, max = 280): string {
  const t = String(text ?? '').trim()
  if (t.length <= max) return t
  let s = t.slice(-max)
  const nl = s.indexOf('\n')
  if (nl >= 0 && nl < 80) s = s.slice(nl + 1)
  return '…' + s
}

/** Text a surface can always take: no control characters but tab and newline, and no half of a surrogate pair at a cut. */
function clean(s: string): string {
  const t = s.replace(/\r\n?/g, '\n').replace(/[\u0000-\u0008\u000b-\u001f\u007f]/g, '')
  const last = t.charCodeAt(t.length - 1)
  return last >= 0xd800 && last <= 0xdbff ? t.slice(0, -1) : t
}

const Grow: ClientModule<GrowProps, GrowState> = (p, surface) => {
  const { Text } = surface.elements
  const st = surface.state
  if (!st) {
    surface.setState({ i: 0 })
    const stop = surface.every(p.stepMs, () => {
      const s = surface.state
      const i = (s ? s.i : 0) + 1
      surface.setState({ i })
      if (i >= p.steps.length) {
        stop()
        surface.post({ grown: p.id })
      }
    })
  }
  const i = st ? st.i : 0
  const done = i >= p.steps.length
  const shown = i <= 0 || !p.steps.length ? p.from : p.steps[Math.min(i, p.steps.length) - 1]!
  const prefix = clean(p.text.slice(0, shown))
  // Plain Text in both modes: a Markdown element as the root of a Client made the desktop refuse the tree ("returned a
  // tree the page cannot draw"); the panel draws the message as Markdown once this is done.
  if (p.mode === 'md') return <Text>{done ? clean(p.text) : `${prefix} ▍`}</Text>
  return <Text dimColor>{`${draftTail(prefix)} ▍`}</Text>
}

export default Grow
