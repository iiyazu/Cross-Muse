// 斜杠命令表：每个操作一个命令，都带 title/description，好在 / 菜单和命令面板里找到。
// tui.tsx 照这张表注册 keymap；测试断言标题和兼容入口。纯数据，无依赖。

export const COMMANDS = [
  { name: "xmuse-status", title: "xmuse：状态", description: "显示房间、成员、审批数" },
  { name: "xmuse-rooms", title: "xmuse：本机房间", description: "列出本机登记表里的房间" },
  { name: "xmuse-join", title: "xmuse：加入", description: "一键加入本机房间，或用邀请码加入" },
  { name: "xmuse-new-room", title: "xmuse：开房间", description: "在当前目录开一个新房间，自己当主控" },
  { name: "xmuse-add", title: "xmuse：添加成员", description: "登记一个新成员（厂商、角色、职责、名字）" },
  { name: "xmuse-host", title: "xmuse：设为主控", description: "把选中的成员设为主控" },
  { name: "xmuse-edit", title: "xmuse：改成员", description: "改成员的角色和职责描述" },
  { name: "xmuse-dm", title: "xmuse：私聊", description: "给选中的成员发私信" },
  { name: "xmuse-say", title: "xmuse：发言", description: "向成员、群或线程发消息" },
  { name: "xmuse-group", title: "xmuse：群管理", description: "新建私有群，把成员拉进群或移出群" },
  { name: "xmuse-approve", title: "xmuse：审批", description: "处理审批：批准一次、总是批准、拒绝" },
  { name: "xmuse-wake", title: "xmuse：叫醒主控", description: "放出压住的结果，立即唤醒主控" },
  { name: "xmuse-leave", title: "xmuse：离开", description: "离开房间，清掉本地令牌" },
  { name: "xmuse-more", title: "xmuse：更多", description: "邀请码邀请、暂停/恢复/移出、更早消息、确认已读" },
]

export const COMPAT_NAME = "xmuse"

// 旧的 /xmuse <子命令> 入口：子命令不认识时返回这段，不静默、不交给模型。
export function compatHelp() {
  return "可用命令：" + COMMANDS.map((c) => "/" + c.name).join("、");
}

// 旧子命令名（兼容入口接受的），供 tui 分发用
export const COMPAT_SUBS = [
  "status", "room", "invite", "join", "join-local", "joinlocal", "rooms", "leave", "say", "dm",
  "add", "edit", "host", "pause", "resume", "remove", "new-group", "group-new", "group-add", "group-rm",
  "approve", "more", "ack", "wake",
];
