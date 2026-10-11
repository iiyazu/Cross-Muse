#!/usr/bin/env python3
"""Which hidden tests does each rot legitimately break?  (README section 5, "completion")

The hidden tests encode the *original* conventions, so an agent that follows a rot decision breaks some of them by
design.  For every ``<seed>-rot<n>`` this script stages the rotated reference implementation
(``reference-rot/<seed>-rot<n>/`` laid over ``reference/<seed>/``), runs the hidden tests against it and writes the
failing test ids (``Class.method``, one per line, sorted) to ``rot-affects/<seed>-rot<n>.txt``.  metrics.py reads
those files: after a rot, a run is complete when every hidden test *not* listed passes and the post-rot tests pass.

usage: python3 rot_affects.py            # regenerate all lists
       python3 rot_affects.py --check    # exit 1 if a list differs from what the rotated reference produces
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SEEDS = ("ledger", "minisql", "pipeline")
ROTS = (1, 2)
_RESULT_RE = re.compile(r"^(\w+) \(([^)]*)\)(?:\n.*?)? \.\.\. (ok|FAIL|ERROR|skipped.*|expected failure|unexpected success)$",
                        re.M)


def parse_ids(text):
    """unittest -v output -> {"Class.method": "ok"|"fail"|"skip"} (the module part of the test id is dropped)."""
    out = {}
    for m in _RESULT_RE.finditer(text):
        ident = m[2].split(".", 1)[-1] if "." in m[2] else m[1]
        out[ident] = "ok" if m[3] in ("ok", "expected failure") else "skip" if m[3].startswith("skipped") else "fail"
    return out


def copy_tree(src, dst):
    shutil.copytree(src, dst, dirs_exist_ok=True, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))


def stage_rotated(seed, n, root):
    """reference/<seed>/<pkg> overlaid with reference-rot/<seed>-rot<n>/<pkg> (only the changed files live there)."""
    copy_tree(os.path.join(HERE, "reference", seed, seed), os.path.join(root, seed))
    copy_tree(os.path.join(HERE, "reference-rot", f"{seed}-rot{n}", seed), os.path.join(root, seed))


def run_ids(root, pattern, start=".", timeout=120):
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1", "PYTHONDONTWRITEBYTECODE": "1"}
    proc = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", start, "-p", pattern, "-v"], cwd=root,
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env, timeout=timeout)
    text = proc.stdout.decode("utf-8", "replace").replace("\r\n", "\n")
    return parse_ids(text), text


def hidden_on_rotated(seed, n):
    """Run the hidden tests on the rotated reference; return ({id: status}, raw output)."""
    with tempfile.TemporaryDirectory(prefix="rot-affects-") as root:
        stage_rotated(seed, n, root)
        shutil.copy2(os.path.join(HERE, "hidden", f"test_hidden_{seed}.py"), root)
        return run_ids(root, "test_hidden_*.py")


def post_rot_on_rotated(seed, n):
    """Run the post-rot tests on the rotated reference; return ({id: status}, raw output)."""
    with tempfile.TemporaryDirectory(prefix="rot-post-") as root:
        stage_rotated(seed, n, root)
        shutil.copy2(os.path.join(HERE, "rot", f"post_rot_test_{seed}.py"), root)
        return run_ids(root, "post_rot_test_*.py")


def affected(seed, n):
    ids, _ = hidden_on_rotated(seed, n)
    return sorted(k for k, v in ids.items() if v == "fail")


def list_path(seed, n):
    return os.path.join(HERE, "rot-affects", f"{seed}-rot{n}.txt")


def render(names):
    return "".join(name + "\n" for name in names)


def read_list(seed, n):
    with open(list_path(seed, n), encoding="utf-8") as handle:
        return [ln.strip() for ln in handle if ln.strip()]


def main(argv):
    check = "--check" in argv
    os.makedirs(os.path.join(HERE, "rot-affects"), exist_ok=True)
    bad = 0
    for seed in SEEDS:
        for n in ROTS:
            names = affected(seed, n)
            path = list_path(seed, n)
            if check:
                same = os.path.exists(path) and read_list(seed, n) == names
                bad += not same
                print("%s-rot%d: %d affected %s" % (seed, n, len(names), "(same)" if same else "(DIFFERS)"))
            else:
                with open(path, "w", encoding="utf-8", newline="\n") as handle:
                    handle.write(render(names))
                print("%s-rot%d: %d affected -> %s" % (seed, n, len(names), os.path.relpath(path, HERE)))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
