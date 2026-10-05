// Server-owned gate driver for the `remix-monorepo/v1` execution profile.
//
// Shipped with xmuse and mounted read-only into the gate sandbox; it is never
// repository content.  The host passes the affected workspace packages (derived
// from the candidate's changed paths) in XMUSE_GATE_PACKAGES.  Each package runs
// in its own child process with the package directory as cwd:
//   typecheck: the installed TypeScript compiler, `tsc --noEmit`
//   test:      the frozen runner's public API, `runRemixTest({type: ["server"]})`
//              from packages/test (mounted read-only from the execution root);
//              the `remix` cli dispatcher is never loaded.
// A package's script text is never executed; its presence only states that the
// package expects the check.  An affected package without the matching script,
// or a run that gated no package at all, fails: nothing is passed unchecked.
import { spawnSync } from "node:child_process";
import { existsSync, readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

const workspace = process.env.XMUSE_GATE_WORKSPACE || "/workspace";
const mode = process.argv[2];
const NAME = /^[a-z0-9][a-z0-9._-]*$/;

if (mode === "test-one") {
  // Child of the test mode: cwd is one package directory.
  const runner = await import(`${workspace}/packages/test/src/cli.ts`);
  const code = await runner.runRemixTest({ cwd: process.cwd(), type: ["server"], concurrency: 2 });
  process.exit(typeof code === "number" ? code : 1);
}

if (mode !== "typecheck" && mode !== "test") {
  console.error(`remix gate: unknown mode ${mode}`);
  process.exit(2);
}
const packages = (process.env.XMUSE_GATE_PACKAGES || "").split(",").filter(Boolean);
const self = fileURLToPath(import.meta.url);
const entry =
  mode === "typecheck"
    ? [`${workspace}/node_modules/typescript/bin/tsc`, "--noEmit"]
    : [self, "test-one"];

let ran = 0;
let failed = 0;
for (const name of packages) {
  if (!NAME.test(name)) {
    console.error("remix gate: invalid package name");
    process.exit(2);
  }
  const dir = `${workspace}/packages/${name}`;
  const manifest = `${dir}/package.json`;
  let scripts = null;
  if (existsSync(manifest)) {
    try {
      scripts = JSON.parse(readFileSync(manifest, "utf8")).scripts || {};
    } catch {
      scripts = null;
    }
  }
  if (scripts === null) {
    console.log(`### ${mode} ${name}: FAILED (no readable package.json)`);
    failed += 1;
    continue;
  }
  if (typeof scripts[mode] !== "string") {
    console.log(`### ${mode} ${name}: FAILED (the package declares no ${mode} script)`);
    failed += 1;
    continue;
  }
  ran += 1;
  console.log(`### ${mode} ${name}`);
  const result = spawnSync(process.execPath, entry, { cwd: dir, stdio: "inherit", env: process.env });
  const code = result.status === null ? 1 : result.status;
  console.log(`### ${mode} ${name}: exit ${code}`);
  if (code !== 0) failed += 1;
}
if (packages.length === 0) {
  // The package gates are only selected for package sources: an empty list
  // means the host derived nothing to check, which must never read as a pass.
  console.log(`### ${mode}: FAILED (no affected package to gate)`);
  process.exit(1);
}
console.log(`### ${mode}: ${packages.length - failed}/${packages.length} affected packages passed`);
process.exit(failed === 0 ? 0 : 1);
