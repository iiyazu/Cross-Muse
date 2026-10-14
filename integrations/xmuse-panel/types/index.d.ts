export type ConnInfo = { phase: 'idle' | 'connecting' | 'ok' | 'error' | 'noroom'; error: string }

declare module 'claude-code' {
  interface PluginState {
    xmuse: {
      conn: ConnInfo
      view: any
      tab: string
      rail: 'auto' | 'open' | 'closed'
      replyTo: number
      gen: number
      promoted: Record<string, string>
      lastRead: string
      light: boolean
      mention: string | null
      forced: string | null
      decision: { id: number; text: string; ok: boolean }
      avatarVer: number
      sendN: number
      sending: boolean
      addOpen: boolean
      expanded: string
      busy: Record<string, boolean>
      fold: Record<string, boolean>
      open: { busy: boolean; msg: string; error: string }
      typed: { id: string; full: string; from: number; steps: number[]; run: number }
      done: Record<string, { tools: number; startedMs: number; endedMs: number }>
      brief: boolean
      older: { items: any[]; hasMore: boolean; loading: boolean }
      selfCtx: number
      reveal: { id: number; steps: number[]; run: number }
      modelPick: {
        member: string; current: string; options: { value: string; label?: string }[]; format: string; note: string
        loading: boolean; error: string
      } | null
    }
  }
}
