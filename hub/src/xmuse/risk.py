"""Which shell commands still need the user in auto mode (the default approval policy, user 10-14).

Everything else an agent runs is approved without asking. A command line is parsed with tree-sitter-bash; it needs
the user when any simple command in it (in a list, pipeline, subshell, loop, function body, `sh -c` script...) is:
  - git push / merge / rebase / reset --hard / clean / branch -D / checkout -- / checkout -f / restore
  - rm -r or rm -f of anything but a relative path inside the workspace or a path under /tmp
  - sudo / su / doas
  - a package install: apt, apt-get, dnf, yum, pacman, brew, snap, pip install, uv pip install, uv tool install,
    cargo install, gem install, npm/pnpm/yarn with -g/--global (or yarn global)
  - curl / wget to anything but a loopback address, or with a proxy, config file or name override
  - another machine or a publication: ssh, scp, remote rsync, nc; gh merge/create/release/api...; npm/cargo publish
  - dd, mkfs*, chmod -R, chown -R, shutdown, reboot
  - a write outside the workspace and /tmp: a > >> &> >| <> redirection, tee, cp/mv/install/ln, -o/--output, sed -i
  - find -delete/-exec outside the workspace; xargs rm/mv/cp/sh (paths never seen); a shell reading its input
  - a credential or xmuse's own state: ~/.ssh, ~/.claude, ~/.aws, ~/.gnupg, .netrc, .git-credentials, id_rsa /
    id_ed25519, xmuse's state directory or sidebar.key; the admin `xmuse send` / `xmuse approve` / `xmuse config`
    (also with --ws, via python -m xmuse, or under uv run / uvx)
A command this module cannot read for sure is asked too: $( ), backticks, <( ), eval, source, a command name that is
an expansion, a PowerShell/cmd inner script, a line that does not parse (unbalanced quotes...). A bash `-c` script
with a literal body is parsed and checked like the outer line.

Runs in the hub only (POST /v1/risk): the agy and Claude member hooks ask the hub, so the parser is installed once.
"""
import os
import re

import tree_sitter_bash
from tree_sitter import Language, Node, Parser

_PARSER = Parser(Language(tree_sitter_bash.language()))
_DEPTH = 3  # sh -c 'sh -c "..."' nesting this check still reads

_LOOPBACK = re.compile(r"^(https?://)?(127\.\d+\.\d+\.\d+|localhost|\[::1\])(:\d+)?(/|$)", re.I)
_SECRET = re.compile(r"(^|[/\\~])\.(ssh|claude|aws|gnupg)([/\\]|$)|\.netrc|\.git-credentials|\bid_(rsa|ed25519|ecdsa)"
                     r"|\.local[/\\]state[/\\]xmuse|sidebar\.key", re.I)
_ASSIGN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
_SHELLS = {"sh", "bash", "zsh", "dash", "fish", "ksh", "pwsh", "powershell", "cmd", "cmd.exe"}
_POSIX_SHELLS = {"sh", "bash", "zsh", "dash", "ksh"}
_WRITE_OPS = {">", ">>", "&>", "&>>", ">|", "<>", ">&"}
_OPAQUE = {"command_substitution": "command substitution this check cannot read",
           "process_substitution": "process substitution this check cannot read"}

_OUT_FLAGS = {"-o", "--output", "-fprint", "-fprint0", "-fprintf", "-fls"}
_GH_WRITE = {"merge", "create", "close", "delete", "edit", "comment", "review", "release", "api", "push", "fork",
             "sync", "publish", "upload", "archive", "transfer", "rename", "lock", "ready", "reopen"}
_FETCH_ASK = {"-x", "--proxy", "--preproxy", "-K", "--config", "--resolve", "--connect-to", "--next", "-:",
              "-e", "--execute", "--unix-socket", "--abstract-unix-socket"}
_CURL_VALUE = {"-o", "--output", "-d", "--data", "--data-raw", "--data-binary", "--data-urlencode", "-H", "--header",
               "-u", "--user", "-w", "--write-out", "-X", "--request", "-A", "--user-agent", "-e", "--referer", "-b",
               "--cookie", "-c", "--cookie-jar", "-T", "--upload-file", "-F", "--form", "-m", "--max-time",
               "--connect-timeout", "-r", "--range", "--retry", "-Y", "-y", "-z", "--json", "-D", "--dump-header"}
_WGET_VALUE = {"-O", "--output-document", "-o", "--output-file", "-P", "--directory-prefix", "-T", "--timeout",
               "-t", "--tries", "--header", "-U", "--user-agent", "--post-data", "--method", "--body-data"}
GIT_ASK = {"push": "git push", "merge": "git merge", "rebase": "git rebase", "clean": "git clean",
           "restore": "git restore (discards changes)"}
INSTALLERS = {"apt", "apt-get", "aptitude", "dnf", "yum", "pacman", "brew", "snap", "zypper", "apk"}


def native(path: str) -> str:
    """A Windows path an agent on the Windows side reports (agy) -> the hub's own form: C:\\x -> /mnt/c/x,
    \\\\wsl.localhost\\<distro>\\home\\x (or \\\\wsl$) -> /home/x. Anything else is returned as it is."""
    if os.name == "nt" or not isinstance(path, str):
        return path
    m = re.match(r"^([A-Za-z]):[\\/]", path)
    if m:
        return f"/mnt/{m.group(1).lower()}/" + path[3:].replace("\\", "/")
    m = re.match(r"^[\\/]{2}wsl(?:\.localhost|\$)[\\/][^\\/]+(.*)$", path, re.I)
    if m:
        return m.group(1).replace("\\", "/") or "/"
    return path


class Where:
    """The workspace root a command may change, and the directory its relative paths start from. `cd` in the line
    moves `cwd` (None: a directory this check cannot know, so no relative path is inside)."""

    def __init__(self, root: str, cwd: str | None = None):
        self.root = native(root)
        self.cwd = native(cwd) if cwd else self.root

    def cd(self, args: list[str]) -> None:
        dest = next((native(a) for a in args if not a.startswith("-") or a == "-"), None)
        if dest is None or dest == "-" or dest.startswith(("~", "$")) or (self.cwd is None and not os.path.isabs(dest)):
            self.cwd = None  # home, the previous directory, an expansion: unknown
            return
        self.cwd = os.path.normpath(dest if os.path.isabs(dest) else os.path.join(self.cwd, dest))


def _inside(path: str, ws: "str | Where") -> bool:
    """A path an agent may change without asking: under /tmp, /dev/null, or inside the workspace."""
    w = ws if isinstance(ws, Where) else Where(ws)
    path, ws = native(path), w.root
    if not path or any(c in path for c in "*?["):
        return False
    if path.startswith("~") or path.startswith("$"):
        return False
    if not os.path.isabs(path) and w.cwd is None:
        return False
    full = os.path.normpath(path if os.path.isabs(path) else os.path.join(w.cwd, path))
    if full in ("/dev/null", "/dev/stdout", "/dev/stderr") or full.startswith("/tmp/") or full == "/tmp":
        return True
    root = os.path.normpath(ws)
    return full == root or full.startswith(root.rstrip("/\\") + os.sep) or full.startswith(root.rstrip("/\\") + "/")


# ---- from the syntax tree to argv ---------------------------------------------------------------------------

def _word(n: Node) -> str:
    """The value bash gives an argument node, as far as it is known without running anything. An expansion keeps
    its `$...` text: a path starting with one is never inside the workspace."""
    t = n.text.decode("utf-8", "replace")
    if n.type == "raw_string":
        return t[1:-1]
    if n.type == "ansi_c_string":
        return t[2:-1]
    if n.type == "string":
        return "".join(_word(c) for c in n.children if c.type != '"')
    if n.type == "string_content":
        return re.sub(r"\\([\\$`\"\n])", r"\1", t)
    if n.type == "concatenation":
        return "".join(_word(c) for c in n.children)
    if n.type == "word":
        return re.sub(r"\\(.)", r"\1", t, flags=re.S)
    return t  # number, simple_expansion, expansion, ...


def _dynamic(n: Node) -> bool:
    """The node's value depends on the environment ($X, ${X}, $(...))."""
    return n.type in ("simple_expansion", "expansion", "command_substitution", "arithmetic_expansion") or \
        any(_dynamic(c) for c in n.children)


def _argv(cmd: Node) -> tuple[list[str], bool]:
    """A `command` node -> (argv without its leading assignments, whether the command name is an expansion)."""
    name = cmd.child_by_field_name("name")
    if name is None:
        return [], False
    args = cmd.children_by_field_name("argument")
    return [_word(name.children[0] if name.children else name)] + [_word(a) for a in args], _dynamic(name)


def _flags(args: list[str]) -> set[str]:
    f = set()
    for a in args:
        if a.startswith("--"):
            f.add(a)
        elif a.startswith("-") and len(a) > 1:
            f.update("-" + c for c in a[1:])
    return f


# interpreter options that take a separate value (`python -X utf8 -m xmuse ...`)
_PY_VALUED = {"-X", "-W", "--check-hash-based-pycs"}


def _xmuse_sub(name: str, args: list[str]) -> str | None:
    """The xmuse subcommand, skipping wrapper noise: `python [-I] [-u]... -m xmuse` and the global options
    (`--ws <dir>` / `--ws=<dir>`, any other dash-flag). The first remaining positional is the subcommand."""
    rest = args
    if name.startswith("python"):
        mod: str | None = None
        i = 0
        while i < len(rest):
            a = rest[i]
            if a == "-m" and i + 1 < len(rest):
                mod, rest = rest[i + 1], rest[i + 2:]
                break
            if a.startswith("-m") and len(a) > 2:  # joined form: -mxmuse
                mod, rest = a[2:], rest[i + 1:]
                break
            if a in _PY_VALUED:  # -X utf8, -W ignore: the value is not a script
                i += 2
                continue
            if a.startswith("-"):
                i += 1
                continue
            return None  # a script path (or -c code): not a module run
        if mod != "xmuse":
            return None
    elif name != "xmuse":
        return None
    i = 0
    while i < len(rest):
        a = rest[i]
        if a == "--ws":
            i += 2
        elif a.startswith("-"):
            i += 1
        else:
            return a
    return None


# options of `uv run` / `uvx` that take a value (also as --opt=value)
_UV_VALUED = {"--project", "--with", "--python", "--directory", "--package", "--env-file", "--group", "--extra",
              "--with-requirements", "--from", "-p"}


def _strip_uv(argv: list[str]) -> list[str]:
    """Drop a `uv run [opts]` / `uvx [opts]` launcher: what remains is judged on its own (xmuse, python -m xmuse,
    or whatever the launcher would execute). Bare `uv ...` is left alone for the package-install rule."""
    if not argv:
        return argv
    if argv[0] == "uvx":
        rest = argv[1:]
    elif len(argv) > 1 and argv[0] == "uv" and argv[1] == "run":
        rest = argv[2:]
    elif len(argv) > 2 and argv[0] == "uv" and argv[1:3] == ["tool", "run"]:
        rest = argv[3:]  # the formal spelling of uvx
    else:
        return argv
    valued = _UV_VALUED
    i = 0
    while i < len(rest):
        a = rest[i]
        if a == "--":
            return rest[i + 1:]
        if a.startswith("--"):
            name, eq, _ = a.partition("=")
            i += 1 if eq or name not in valued or i + 1 >= len(rest) else 2
        elif len(a) > 1 and a.startswith("-"):
            i += 2 if a in valued and i + 1 < len(rest) else 1
        else:
            return rest[i:]
    return []


def _one(argv: list[str], ws: Where, depth: int) -> str | None:
    """One simple command (its redirections are file_redirect nodes, checked on their own)."""
    while argv and _ASSIGN.match(argv[0]):
        argv = argv[1:]
    while argv and argv[0] in ("env", "command", "nohup", "time", "exec", "nice", "timeout"):
        argv = argv[1:]
        while argv and (argv[0].startswith("-") or _ASSIGN.match(argv[0]) or re.fullmatch(r"\d+[smhd]?", argv[0])):
            argv = argv[1:]
    argv = _strip_uv(argv)
    if not argv:
        return None
    name = argv[0].replace("\\", "/").rsplit("/", 1)[-1].lower()
    args = argv[1:]
    fl = _flags(args)
    if name in ("sudo", "su", "doas"):
        return name
    if name in ("eval", "source", "."):
        return f"{name} runs code this check cannot read"
    if name in _SHELLS and ("-c" in fl or "-command" in {a.lower() for a in args} or "/c" in {a.lower() for a in args}):
        script = next((a for a in args if not a.startswith("-")), None)
        if name not in _POSIX_SHELLS or script is None or depth >= _DEPTH:
            return f"{name} -c runs a script this check cannot read"
        why = _check(script, ws, depth + 1)  # a literal script: the same check, one level down
        return f"{name} -c: {why}" if why else None
    if name in _SHELLS and not [a for a in args if not a.startswith("-")]:
        return f"{name} runs a script from its input"
    sub = _xmuse_sub(name, args)
    if sub in ("send", "approve", "config"):
        return f"xmuse {sub} (admin command)"
    for i, a in enumerate(args):  # -o FILE / --output=FILE / find -fprint FILE: a write, wherever the tool
        path = a.split("=", 1)[1] if a.startswith("--output=") else \
            args[i + 1] if a in _OUT_FLAGS and i + 1 < len(args) else None
        if path is not None and not _inside(path, ws):
            return f"writes outside the workspace ({path})"
    if name == "xargs":  # the command it runs gets arguments this check never sees
        inner = args
        while inner and inner[0].startswith("-"):
            inner = inner[2:] if inner[0] in ("-I", "-n", "-P", "-L", "-d", "-a", "-E", "-s") else inner[1:]
        iname = inner[0].replace("\\", "/").rsplit("/", 1)[-1] if inner else "echo"
        if iname in ("rm", "mv", "cp", "tee", "dd", "chmod", "chown", *_SHELLS):
            return f"xargs {iname} on paths this check never sees"
        return _one(inner, ws, depth)
    if name == "find":
        starts = [a for a in args if not a.startswith(("-", "(", ")", "!"))][:1] or ["."]
        acts = {"-delete", "-exec", "-execdir", "-ok", "-okdir"} & set(args)
        if acts and not all(_inside(s, ws) for s in starts):
            return f"find {' '.join(sorted(acts))} outside the workspace"
        for i, a in enumerate(args):
            if a in ("-exec", "-execdir", "-ok", "-okdir"):
                inner = []
                for t in args[i + 1:]:
                    if t in (";", "+"):
                        break
                    inner.append(t)
                why = _one(inner, ws, depth)
                if why:
                    return why
        return None
    if name in ("ssh", "scp", "sftp", "telnet", "nc", "ncat", "socat") or \
            (name == "rsync" and any(re.match(r"^[\w.@-]+:", a) for a in args)):
        return f"{name} reaches another machine"
    if name == "gh" and _GH_WRITE & set(args):
        return "gh " + " ".join(a for a in args if a in _GH_WRITE)
    if (name in ("npm", "pnpm", "yarn", "bun", "cargo", "poetry", "gem") and "publish" in args[:2]) or \
            (name == "twine" and "upload" in args):
        return f"{name} publish"
    if name == "sed" and ("-i" in fl or any(a.startswith("--in-place") for a in args)):
        bad = [a for a in args[1:] if a.startswith(("/", "~")) and not _inside(a, ws)]
        if bad:
            return f"writes outside the workspace ({' '.join(bad)})"
    if name == "git":
        rest = list(args)
        while rest and rest[0].startswith("-"):  # git -C dir / -c k=v
            rest = rest[2:] if rest[0] in ("-C", "-c", "--git-dir", "--work-tree") else rest[1:]
        sub, sargs = (rest[0], rest[1:]) if rest else ("", [])
        sf = _flags(sargs)
        if sub in GIT_ASK:
            return GIT_ASK[sub]
        if sub == "reset" and "--hard" in sf:
            return "git reset --hard"
        if sub == "branch" and ({"-D"} & sf or {"--delete", "--force"} <= sf or ("-d" in sf and "-f" in sf)):
            return "git branch -D"
        if sub in ("checkout", "switch") and ("--" in sargs or "-f" in sf or "--force" in sf or "--discard-changes" in sf):
            return f"git {sub} discarding changes"
        if sub == "stash" and sargs[:1] and sargs[0] in ("drop", "clear"):
            return "git stash " + sargs[0]
        return None
    if name == "rm":
        if fl & {"-r", "-R", "-f", "--recursive", "--force"}:
            # the parent must be inside too: rm -rf . (or the workspace by name) removes the workspace itself
            bad = [a for a in args if not a.startswith("-") and not _inside(os.path.join(a, ".."), ws)]
            if bad or not [a for a in args if not a.startswith("-")]:
                return f"rm {' '.join(sorted(fl))} outside the workspace ({' '.join(bad) or '?'})"
        return None
    if name in INSTALLERS:
        return f"{name} (package install)"
    if name in ("pip", "pip3") or (name.startswith("python") and args[:2] == ["-m", "pip"]):
        if "install" in args or "uninstall" in args:
            return "pip install"
    if name == "uv" and (args[:2] in (["pip", "install"], ["tool", "install"]) or args[:1] == ["self"]):
        return "uv " + " ".join(args[:2])
    if name in ("cargo", "gem", "go") and args[:1] == ["install"]:
        return f"{name} install"
    if name in ("npm", "pnpm", "yarn", "bun") and (fl & {"-g", "--global"} or args[:1] == ["global"]):
        return f"{name} global install"
    if name in ("curl", "wget"):
        return _fetch(name, args)
    if name == "dd" or name.startswith("mkfs") or name in ("shutdown", "reboot", "poweroff", "halt"):
        return name
    if name in ("chmod", "chown", "chgrp") and fl & {"-R", "--recursive"}:
        return f"{name} -R"
    if name == "tee":
        bad = [a for a in args if not a.startswith("-") and not _inside(a, ws)]
        if bad:
            return f"writes outside the workspace ({' '.join(bad)})"
    if name in ("cp", "mv", "install", "ln", "rsync"):
        files = [a for a in args if not a.startswith("-")]
        dest = next((args[i + 1] for i, a in enumerate(args) if a in ("-t", "--target-directory") and i + 1 < len(args)),
                    files[-1] if len(files) >= 2 else None)
        if dest is not None and not _inside(dest, ws):
            return f"writes outside the workspace ({dest})"
        if name == "mv" and any(not _inside(a, ws) for a in files[:-1]):
            return "moves files from outside the workspace"
    return None


def _fetch(name: str, args: list[str]) -> str | None:
    """curl / wget: only addresses on this machine, no proxy, config file or name override."""
    takes = _CURL_VALUE if name == "curl" else _WGET_VALUE
    i = 0
    while i < len(args):
        a = args[i]
        if a.startswith("--"):
            key = a.split("=", 1)[0]
            if key in _FETCH_ASK:
                return f"{name} {key}"
            if key in takes and "=" not in a:
                i += 1
        elif a.startswith("-") and len(a) > 1:
            for j, c in enumerate(a[1:]):
                if "-" + c in _FETCH_ASK:
                    return f"{name} -{c}"
                if "-" + c in takes:
                    if j == len(a) - 2:
                        i += 1  # the value is the next argument
                    break  # else the rest of this argument is the value
        elif not _LOOPBACK.match(a):
            return f"{name} to a non-local address ({a})"
        i += 1
    if not [a for a in args if _LOOPBACK.match(a)]:
        return f"{name} with no address on this machine"
    return None


def _redirect(n: Node, ws: Where) -> str | None:
    """A file_redirect node: a write outside the workspace (`>&2` duplicates a descriptor and writes nothing new)."""
    op = next((c.type for c in n.children if c.type in _WRITE_OPS), None)
    dest = n.child_by_field_name("destination")
    if op is None or dest is None or (op == ">&" and dest.type == "number") or _word(dest) == "-":
        return None
    target = _word(dest)
    return None if _inside(target, ws) else f"writes outside the workspace ({target})"


def _walk(n: Node, ws: Where, depth: int) -> str | None:
    """Every node of the tree: substitutions, redirections and simple commands wherever they are nested."""
    if n.type in _OPAQUE:
        return _OPAQUE[n.type]
    if n.type == "file_redirect":
        why = _redirect(n, ws)
        if why:
            return why
    if n.type == "command":
        argv, opaque = _argv(n)
        if opaque:
            return "a command name this check cannot read"
        if argv and argv[0] in ("cd", "pushd", "popd"):
            ws.cd(argv[1:] if argv[0] != "popd" else ["-"])
        why = argv and _one(argv, ws, depth)
        if why:
            return why
    for c in n.children:
        why = _walk(c, ws, depth)
        if why:
            return why
    return None


def _check(cmd: str, ws: Where, depth: int) -> str | None:
    if _SECRET.search(cmd):
        return "touches credentials or xmuse's own state"
    tree = _PARSER.parse(cmd.encode("utf-8"))
    if tree.root_node.has_error:
        return "unbalanced quotes or syntax this check cannot parse"
    return _walk(tree.root_node, ws, depth)


def risky(cmd: str, ws: str, cwd: str | None = None) -> str | None:
    """Why `cmd` (one shell command line for workspace `ws`, run in directory `cwd`, default the workspace) needs
    the user, or None. A `cwd` outside the workspace makes every relative path outside too."""
    if not isinstance(cmd, str) or not cmd.strip():
        return None
    return _check(cmd, Where(ws, cwd), 0)


def risky_paths(paths: list[str], ws: str) -> str | None:
    """A file tool writing `paths` (agy's write_to_file...): why that needs the user, or None."""
    bad = [p for p in paths if not _inside(p, ws) or _SECRET.search(p)]
    return f"writes outside the workspace ({', '.join(bad)})" if bad else None
