// xmuse mod state contract (XMUSE2-VIEW-API v0 shapes, the fields the sidebar uses).
// Secrets (member / operator tokens) are NOT in $.state: other plugins can read it.
// They live in $.store only.

export type XmuseMember = {
  id: string
  vendor: string
  model?: string
  role: string
  description: string
  status: string
  online: boolean
  paused: boolean
  unread: number
  tokens_hour?: number
  tokens_hour_cap?: number
}

export type XmuseThread = {
  id: string
  kind: string
  title: string
  members: string[]
  last_at: number
  unread: number
}

export type XmuseMessage = {
  id: number
  thread: string
  from: string
  via: string | null
  to: string[]
  mentions: string[]
  kind: string
  text: string
  at: number
  for_me: boolean
}

export type XmuseAlignEntry = {
  id: string
  kind: string
  scope: string
  author: string
  text: string
  supersedes: string | null
  status: string
  at: number
}

export type XmuseApproval = {
  id: string
  kind: string
  member: string
  summary: string
  detail: string
  risk: string
  at: number
}

export type XmuseView = {
  version: number
  room: { id: string; name: string; dir: string; host: string; info_layer: string; created_at: number }
  me: { kind: string; id: string }
  members: XmuseMember[]
  threads: XmuseThread[]
  timeline: XmuseMessage[]
  timeline_cursor: { oldest: number; has_more: boolean }
  alignment: XmuseAlignEntry[]
  approvals: XmuseApproval[]
  run: unknown
}

export type XmuseInvite = {
  code: string
  command: string
  expires_at: number
  vendor: string
  role: string
}

export type XmuseUi = {
  section: string
  thread: string
  to: string
  draft: string
  newRoom: string
  joinCode: string
  invVendor: string
  invRole: string
  invDesc: string
  target: string
  lastInvite: XmuseInvite | null
  notice: string
}

export type XmuseConn = {
  status: string
  error: string
  at: number
  memberId: string
  hub: string
  roomId: string
}

export type XmuseMore = {
  items: XmuseMessage[]
  hasMore: boolean
}

declare module 'claude-code' {
  interface PluginState {
    xmuse: {
      ui: XmuseUi
      view: XmuseView | null
      conn: XmuseConn
      more: XmuseMore
    }
  }
}
