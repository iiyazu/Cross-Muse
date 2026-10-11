export type XmuseProbeUi = {
  room: string
  joined: string
  draft: string
  provider: string
  presses: number
}

declare module 'claude-code' {
  interface PluginState {
    'xmuse-probe': { ui: XmuseProbeUi }
  }
}
