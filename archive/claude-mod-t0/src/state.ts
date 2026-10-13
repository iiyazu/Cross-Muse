import type { XmuseConn, XmuseUi } from '../types/index'

export const PANE = 'xmuse'

export const INITIAL_UI: XmuseUi = {
  section: 'timeline',
  thread: 'all',
  to: '',
  draft: '',
  newRoom: '',
  joinCode: '',
  invVendor: 'opencode',
  invRole: 'executor',
  invDesc: '',
  target: '',
  lastInvite: null,
  notice: '',
  addVendor: 'opencode',
  addModel: '',
  addRole: 'executor',
  addDesc: '',
  addName: '',
  editRole: '',
  editDesc: '',
  editModel: '',
  grpPick: '',
  grpId: '',
  grpTitle: '',
  grpMembers: '',
}

export const INITIAL_CONN: XmuseConn = {
  status: 'none',
  error: '',
  at: 0,
  memberId: '',
  hub: '',
  roomId: '',
}
