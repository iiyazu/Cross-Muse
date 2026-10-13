export type ConnInfo = { phase: 'idle' | 'connecting' | 'ok' | 'error' | 'noroom'; error: string }

declare module 'claude-code' {
  interface PluginState {
    xmuse: {
      conn: ConnInfo
      view: any
      tab: string
      replyTo: number
      gen: number
      promoted: Record<string, string>
      lastRead: string
      now: number
      ticking: number
      light: boolean
      mention: string | null
      forced: string | null
      decision: { id: number; text: string; ok: boolean }
      avatarVer: number
      sendN: number
      sending: boolean
      addOpen: boolean
      busy: Record<string, boolean>
      fold: Record<string, boolean>
      open: { busy: boolean; msg: string; error: string }
      typed: { id: string; full: string; shown: number }
      done: Record<string, { tools: number; startedMs: number; endedMs: number }>
      brief: boolean
      older: { items: any[]; hasMore: boolean; loading: boolean }
      selfCtx: number
      reveal: { id: number; shown: number }
      modelPick: {
        member: string; current: string; options: { value: string; label?: string }[]; format: string; note: string
        loading: boolean; error: string
      } | null
    }
  }
}
