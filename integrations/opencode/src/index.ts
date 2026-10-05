// Server entry for the xmuse plugin package. Loaded by the OpenCode host
// outside the TUI; it must stay dependency-free (zero dependencies) so
// loading the package never pulls UI code into the server process.
const plugin = {
  id: "xmuse.server",
  setup() {},
};

export default plugin;
