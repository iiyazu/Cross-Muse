/** @jsxImportSource @opentui/solid */
import { Plugin } from "@opencode/plugin/tui";
import { createSignal } from "solid-js";
import { createBoardHost, POLL_MS, type TuiContext } from "./host";

declare const process: { env?: Record<string, string | undefined> } | undefined;

export default Plugin.define({
  id: "xmuse",
  setup(context) {
    const [line, setLine] = createSignal("xmuse …");
    const host = createBoardHost(context as unknown as TuiContext, {
      env: process?.env ?? {},
      onStatus: (text) => setLine(text),
    });
    setLine(host.initialStatus);

    // The keymap layer must be created from inside a component (the host
    // throws when it is created in setup). Register once, guarded by flag.
    let commandsRegistered = false;
    function Footer() {
      if (!commandsRegistered) {
        commandsRegistered = true;
        context.keymap.layer(() => ({
          mode: "global",
          commands: [
            {
              id: "xmuse.board",
              title: "xmuse board status",
              slash: { name: "xmuse", arguments: true },
              palette: true,
              run: async (input) => {
                const text = await host.command(input);
                context.ui.toast.show({ message: text });
              },
            },
          ],
        }));
      }
      return <text>{line()}</text>;
    }

    const disposeSlot = context.ui.slot({
      append: "home.footer.status",
      render: () => <Footer />,
    });

    let inFlight = false;
    const timer = setInterval(() => {
      if (inFlight) return;
      inFlight = true;
      void (async () => {
        try {
          await host.tick(Date.now());
        } catch {
          // degraded: never throw out of the poll loop
        } finally {
          inFlight = false;
        }
      })();
    }, POLL_MS);

    return () => {
      clearInterval(timer);
      disposeSlot();
    };
  },
});
