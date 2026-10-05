// Server-owned gate driver for the `remix-monorepo/v1` execution profile.
//
// Shipped with xmuse and mounted read-only into the gate sandbox; it is never
// repository content.  The host passes the affected workspace packages (derived
// from the candidate's changed paths) in XMUSE_GATE_PACKAGES.  For each package
// that declares the matching script it runs a fixed entrypoint with the package
// directory as cwd:
//   typecheck: the installed TypeScript compiler, `tsc --noEmit`
//   test:      the repository's frozen runner, `remix test --type server`
// A package's script text is never executed; only its presence is read.
import { spawnSync } from "node:child_process";
import { existsSync, readFileSync } from "node:fs";

const workspace = process.env.XMUSE_GATE_WORKSPACE || "/workspace";
const mode = process.argv[2];
const NAME = /^[a-z0-9][a-z0-9._-]*$/;
const packages = (process.env.XMUSE_GATE_PACKAGES || "").split(",").filter(Boolean);

if (mode !== "typecheck" && mode !== "test") {
  console.error(`remix gate: unknown mode ${mode}`);
  process.exit(2);
}
const entry =
  mode === "typecheck"
    ? [`${workspace}/node_modules/typescript/bin/tsc`, "--noEmit"]
    : [`${workspace}/packages/remix/src/cli-entry.ts`, "test", "--type", "server", "--concurrency", "2"];

let ran = 0;
let failed = 0;
for (const name of packages) {
  if (!NAME.test(name)) {
    console.error(`remix gate: invalid package name`);
    process.exit(2);
  }
  const dir = `${workspace}/packages/${name}`;
  const manifest = `${dir}/package.json`;
  if (!existsSync(manifest)) {
    console.log(`### ${mode} ${name}: skipped (no package.json)`);
    continue;
  }
  let scripts = {};
  try {
    scripts = JSON.parse(readFileSync(manifest, "utf8")).scripts || {};
  } catch {
    console.log(`### ${mode} ${name}: unreadable package.json`);
    ran += 1;
    failed += 1;
    continue;
  }
  if (typeof scripts[mode] !== "string") {
    console.log(`### ${mode} ${name}: skipped (no ${mode} script)`);
    continue;
  }
  ran += 1;
  console.log(`### ${mode} ${name}`);
  const result = spawnSync(process.execPath, entry, { cwd: dir, stdio: "inherit", env: process.env });
  const code = result.status === null ? 1 : result.status;
  console.log(`### ${mode} ${name}: exit ${code}`);
  if (code !== 0) failed += 1;
}
console.log(`### ${mode}: ${ran - failed}/${ran} packages passed (${packages.length} affected)`);
process.exit(failed === 0 ? 0 : 1);
