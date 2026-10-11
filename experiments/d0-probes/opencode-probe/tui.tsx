/** @jsxImportSource @opentui/solid */
// D0 probe for the OpenCode 2.x TUI plugin API: sidebar slot, slash command with args, toast, timers, HTTP.
import { Plugin } from "@opencode/plugin/tui"

export default Plugin.define({
  id: "xmuse-probe",
  setup(ctx) {
    const log = (o: Record<string, unknown>) =>
      fetch("http://127.0.0.1:18081/oc-tui", { method: "POST", body: JSON.stringify(o) }).catch(() => {})
    log({ ev: "setup", app: ctx.app, ctxKeys: Object.keys(ctx), uiKeys: Object.keys(ctx.ui) })

    const off = ctx.ui.slot({
      append: "sidebar.content",
      render: (input: { sessionID: string }) => (
        <box flexDirection="column">
          <text>xmuse room: demo</text>
          <text>members: claude dsh opencode</text>
          <text>session: {input.sessionID.slice(0, 12)}</text>
        </box>
      ),
    })

    ctx.keymap.layer(() => ({
      commands: [
        {
          id: "xmuse.cmd",
          title: "xmuse",
          description: "xmuse probe command",
          slash: { name: "xmuse", arguments: true },
          run: (input?: string) => {
            ctx.ui.toast.show({ title: "xmuse", message: "slash got: " + String(input), variant: "info" })
            log({ ev: "slash", input })
          },
        },
      ],
    }))

    const t = setInterval(() => log({ ev: "tick" }), 2000)
    setTimeout(() => ctx.ui.toast.show({ title: "xmuse", message: "hello toast from plugin", variant: "success", duration: 8000 }), 5000)
    return () => {
      clearInterval(t)
      off()
    }
  },
})
