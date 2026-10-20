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
      light: boolean
      mention: string | null
      forced: string | null
      decision: { id: number; text: string; ok: boolean }
      avatarVer: number
      sendN: number
      inputGen: number
      sending: boolean
      addOpen: boolean
      expanded: string
      busy: Record<string, boolean>
      fold: Record<string, boolean>
      open: { busy: boolean; msg: string; error: string }
      done: Record<string, { tools: number; startedMs: number; endedMs: number }>
      brief: boolean
      older: { items: any[]; hasMore: boolean; loading: boolean }
      shown: Record<string, number>
      selfCtx: number
      probe: boolean
      layout: 'chat' | 'flow'
      railFold: boolean
      scrollProbe: { n: number; by: number; offset: number; bodyRows: number; contentRows: number; origin: string }
      reveal: { id: number; steps: number[]; run: number }
      modelPick: {
        member: string; current: string; options: { value: string; label?: string }[]; format: string; note: string
        loading: boolean; error: string
      } | null
    }
  }
}
