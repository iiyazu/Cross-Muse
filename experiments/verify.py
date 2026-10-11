#!/usr/bin/env python3
"""Verifier for the xmuse 2 / M2 experiment seeds.

For every task it checks:

  1. the reference implementation passes the public tests;
  2. the reference implementation passes the hidden tests;
  3. the skeleton in ``seeds/<task>`` fails the public tests;
  4. the skeleton also fails the hidden tests (nothing is accidentally pre-solved);
  5. every planted bug variant fails at least one hidden test;
  6. the post-rot test in ``rot/`` does NOT pass on the reference implementation
     (it encodes the *rotated* convention, so it can only pass after an agent has
     followed the mid-task convention change);
  7. for each rot, the rotated reference (``reference-rot/<task>-rot<n>``) passes the post-rot cases, the hidden
     cases it legitimately breaks are exactly the ones in ``rot-affects/<task>-rot<n>.txt``, and every other hidden
     case still passes on it (``rot_affects.py`` regenerates the lists).

A task whose ``seeds/<name>`` repository has not been written yet (``pipeline``
while it is still being designed) is skipped with a notice instead of aborting
the whole run.

Everything runs through ``sys.executable -m unittest`` inside a throwaway copy, so
no ``__pycache__`` or stray file ever lands in the seed repositories.

Usage:
    python verify.py              # all tasks
    python verify.py -t ledger    # one task, repeatable
    python verify.py -v           # dump the child output of failing checks

Exit code 0 means every check passed.
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile

import rot_affects

HERE = os.path.dirname(os.path.abspath(__file__))

TASKS = [
    {
        "name": "ledger",
        "package": "ledger",
        "hidden": "test_hidden_ledger.py",
        "bugs": ["bug-1", "bug-2"],
        "rot_test": "post_rot_test_ledger.py",
    },
    {
        "name": "minisql",
        "package": "minisql",
        "hidden": "test_hidden_minisql.py",
        "bugs": ["bug-1", "bug-2"],
        "rot_test": "post_rot_test_minisql.py",
    },
    {
        "name": "pipeline",
        "package": "pipeline",
        "hidden": "test_hidden_pipeline.py",
        "bugs": ["bug-1", "bug-2"],
        "rot_test": "post_rot_test_pipeline.py",
    },
]

_RAN_RE = re.compile(r"^Ran (\d+) tests? in", re.MULTILINE)
_FAIL_RE = re.compile(r"^FAILED \((.*)\)$", re.MULTILINE)


class Check:
    def __init__(self, label):
        self.label = label
        self.ok = False
        self.detail = ""

    def __str__(self):
        return "[%s] %s%s" % ("PASS" if self.ok else "FAIL", self.label, self.detail)


def _child_env():
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


def run_unittest(root, start=".", pattern="test_*.py", timeout=120):
    """Run unittest discovery in ``root`` and return a result dict.

    ``python -m unittest`` puts the current directory on ``sys.path``, so the
    package under test is importable without installing anything.
    """
    argv = [
        sys.executable,
        "-m",
        "unittest",
        "discover",
        "-s",
        start,
        "-p",
        pattern,
        "-v",
    ]
    try:
        proc = subprocess.run(
            argv,
            cwd=root,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            env=_child_env(),
            timeout=timeout,
        )
        output = proc.stdout.decode("utf-8", "replace").replace("\r\n", "\n").replace("\r", "\n")
        rc = proc.returncode
    except subprocess.TimeoutExpired as exc:
        output = (
            (exc.output or b"").decode("utf-8", "replace").replace("\r\n", "\n") + "\n<TIMEOUT>"
        )
        rc = 124
    ran = _RAN_RE.search(output)
    failed = _FAIL_RE.search(output)
    return {
        "rc": rc,
        "output": output,
        "ran": int(ran.group(1)) if ran else 0,
        "failed": failed.group(1) if failed else "",
        "passed": rc == 0 and bool(ran),
    }


def copy_tree(src, dst):
    shutil.copytree(
        src, dst, dirs_exist_ok=True, ignore=shutil.ignore_patterns("__pycache__", "*.pyc")
    )


def stage_reference(task, root):
    """Copy ``reference/<task>/<package>`` into the staging root."""
    src = os.path.join(HERE, "reference", task["name"], task["package"])
    copy_tree(src, os.path.join(root, task["package"]))


def stage_seed(task, root):
    """Copy the whole seed repository (package + tests + .gitignore) into root."""
    copy_tree(os.path.join(HERE, "seeds", task["name"]), root)


def stage_hidden(task, root):
    shutil.copy2(
        os.path.join(HERE, "hidden", task["hidden"]), os.path.join(root, task["hidden"])
    )


def stage_bug(task, bug, root):
    copy_tree(os.path.join(HERE, "planted", task["name"], bug), root)


def stage_rot(task, root):
    shutil.copy2(
        os.path.join(HERE, "rot", task["rot_test"]), os.path.join(root, task["rot_test"])
    )


def tail(text, n=25):
    lines = [line for line in text.splitlines() if line.strip()]
    return "\n".join("      | " + line for line in lines[-n:])


def task_present(task):
    """Return True once the task's seed repository has been written.

    ``TASKS`` is the full experiment slate; a task that is still being designed
    (currently ``pipeline``) has no ``seeds/<name>`` directory yet, so verifying
    it would only crash on a missing file.  Skipping it keeps one unstaged task
    from masking the results of the finished ones.
    """
    return os.path.isdir(os.path.join(HERE, "seeds", task["name"]))


def build_cases(task):
    """Return the list of (label, prepare, run_kwargs, expect) for one task."""
    name = task["name"]
    seed_tests = os.path.join(HERE, "seeds", name, "tests")

    def reference_public(root):
        stage_reference(task, root)
        copy_tree(seed_tests, os.path.join(root, "tests"))

    def reference_hidden(root):
        stage_reference(task, root)
        stage_hidden(task, root)

    def seed_public(root):
        stage_seed(task, root)

    def seed_hidden(root):
        stage_seed(task, root)
        stage_hidden(task, root)

    def bug_case(bug):
        def prepare(root, bug=bug):
            stage_reference(task, root)
            stage_bug(task, bug, root)
            stage_hidden(task, root)

        return prepare

    def rot_case(root):
        stage_reference(task, root)
        stage_rot(task, root)

    cases = [
        (
            "%s: reference passes public tests" % name,
            reference_public,
            {"start": "tests", "pattern": "test_public.py"},
            "pass",
        ),
        (
            "%s: reference passes hidden tests" % name,
            reference_hidden,
            {"start": ".", "pattern": "test_hidden_*.py"},
            "pass",
        ),
        (
            "%s: skeleton fails public tests" % name,
            seed_public,
            {"start": "tests", "pattern": "test_public.py"},
            "fail",
        ),
        (
            "%s: skeleton fails hidden tests" % name,
            seed_hidden,
            {"start": ".", "pattern": "test_hidden_*.py"},
            "fail",
        ),
    ]
    for bug in task["bugs"]:
        cases.append(
            (
                "%s/%s: hidden tests catch the planted bug" % (name, bug),
                bug_case(bug),
                {"start": ".", "pattern": "test_hidden_*.py"},
                "fail",
            )
        )
    cases.append(
        (
            "%s: post-rot test rejects the original convention" % name,
            rot_case,
            {"start": ".", "pattern": "post_rot_test_*.py"},
            "fail",
        )
    )
    return cases


def rotated_checks(task):
    """Checks on reference-rot/<task>-rot<n>/ (the reference rewritten to the new convention), for n = 1, 2:

    * the post-rot cases of that rot all pass on it (the detector is satisfiable);
    * rot-affects/<task>-rot<n>.txt equals what the hidden tests actually fail on it (regenerating changes nothing);
    * with the listed cases removed, the hidden tests pass on it (the list is complete).
    """
    name, out = task["name"], []
    for n in rot_affects.ROTS:
        label = "%s-rot%d" % (name, n)
        post, text = rot_affects.post_rot_on_rotated(name, n)
        mine = {k: v for k, v in post.items() if ".test_rot%d_" % n in "." + k}
        check = Check("%s: rotated reference passes its post-rot cases" % label)
        check.ok = bool(mine) and all(v == "ok" for v in mine.values())
        check.detail = " (%d/%d)" % (sum(v == "ok" for v in mine.values()), len(mine))
        if not check.ok:
            check.detail += "\n" + tail(text)
        out.append(check)

        hidden, text = rot_affects.hidden_on_rotated(name, n)
        failing = sorted(k for k, v in hidden.items() if v == "fail")
        path = rot_affects.list_path(name, n)
        listed = rot_affects.read_list(name, n) if os.path.exists(path) else None
        check = Check("%s: affected-hidden list matches the rotated reference" % label)
        check.ok = listed == failing
        check.detail = " (%d listed)" % (len(listed) if listed is not None else -1)
        if not check.ok:
            check.detail += "\n      | missing from list: %s\n      | stale in list: %s" % (
                sorted(set(failing) - set(listed or [])), sorted(set(listed or []) - set(failing)))
        out.append(check)

        rest = {k: v for k, v in hidden.items() if k not in (listed or [])}
        check = Check("%s: hidden tests minus the affected ones all pass on it" % label)
        check.ok = bool(rest) and all(v != "fail" for v in rest.values())
        check.detail = " (%d of %d)" % (len(rest), len(hidden))
        if not check.ok:
            check.detail += "\n" + tail(text)
        out.append(check)
    return out


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("-v", "--verbose", action="store_true", help="show child output")
    parser.add_argument(
        "-t",
        "--task",
        action="append",
        choices=[task["name"] for task in TASKS],
        help="only verify this task (repeatable); the default is all of them",
    )
    args = parser.parse_args()

    requested = [task for task in TASKS if not args.task or task["name"] in args.task]
    selected = []
    for task in requested:
        if task_present(task):
            selected.append(task)
        else:
            print(
                "[SKIP] %s: not staged yet (no seeds/%s)" % (task["name"], task["name"]),
                flush=True,
            )

    # Staging happens in a throwaway tree.  ``M2X_VERIFY_TMP`` lets a confined
    # sandbox point that tree at a location it is allowed to write to.
    override = os.environ.get("M2X_VERIFY_TMP")
    if override:
        base = os.path.abspath(override)
        os.makedirs(base, exist_ok=True)
        probe = os.path.join(base, "write-probe.txt")
        with open(probe, "w") as handle:
            handle.write("ok")
        os.remove(probe)
        tmpdir = tempfile.mkdtemp(prefix="m2x-verify-", dir=base)
    else:
        tmpdir = tempfile.mkdtemp(prefix="m2x-verify-")
    checks = []
    try:
        for task in selected:
            for label, prepare, run_kwargs, expect in build_cases(task):
                root = tempfile.mkdtemp(prefix="case-", dir=tmpdir)
                check = Check(label)
                prepare(root)
                result = run_unittest(root, **run_kwargs)
                ran = result["ran"]
                if expect == "pass":
                    check.ok = ran > 0 and result["passed"]
                else:
                    check.ok = ran > 0 and not result["passed"]
                check.detail = " (ran %d, %s)" % (ran, result["failed"] or "OK")
                if not check.ok:
                    check.detail += "\n" + tail(result["output"])
                checks.append(check)
                print(check, flush=True)
                if args.verbose and not check.ok:
                    print(result["output"], flush=True)
            for check in rotated_checks(task):
                checks.append(check)
                print(check, flush=True)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

    failed = [check for check in checks if not check.ok]
    print("")
    print("=" * 72)
    if not checks:
        print("no checks ran: every selected task is not staged yet")
        return 1
    print(
        "checks: %d, passed: %d, failed: %d"
        % (len(checks), len(checks) - len(failed), len(failed))
    )
    if failed:
        print("FAILED CHECKS:")
        for check in failed:
            print("  - %s" % check.label)
        return 1
    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
