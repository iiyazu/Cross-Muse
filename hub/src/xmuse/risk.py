"""Which shell commands still need the user in auto mode (the default approval policy, user 10-14).

Everything else an agent runs is approved without asking. A command needs the user when any of its pieces
(split at ; && || | & and newlines) is one of:
  - git push / merge / rebase / reset --hard / clean / branch -D / checkout -- / checkout -f / restore
  - rm -r or rm -f of anything but a relative path inside the workspace or a path under /tmp
  - sudo / su / doas
  - a package install: apt, apt-get, dnf, yum, pacman, brew, snap, pip install, uv pip install, uv tool install,
    cargo install, gem install, npm/pnpm/yarn with -g/--global (or yarn global)
  - curl / wget to anything but a loopback address, or with a proxy, config file or name override
  - another machine or a publication: ssh, scp, remote rsync, nc; gh merge/create/release/api...; npm/cargo publish
  - dd, mkfs*, chmod -R, chown -R, shutdown, reboot
  - a write outside the workspace and /tmp: a > or >> redirection, tee, cp/mv/install/ln, -o/--output, sed -i
  - find -delete/-exec outside the workspace; xargs rm/mv/cp/sh (paths never seen); a shell reading its input
  - a credential or xmuse's own state: ~/.ssh, ~/.claude, ~/.aws, ~/.gnupg, .netrc, .git-credentials, id_rsa /
    id_ed25519, xmuse's state directory or sidebar.key; the admin `xmuse send` / `xmuse approve`
A command this module cannot read for sure is asked too: $( ), backticks, <( ), eval, source, `sh -c`-style
inner scripts, unbalanced quotes.

Standalone on purpose (stdlib only, no package import): the agy and Claude member hooks embed this file's source.
"""
import os
import re
import shlex

_SUBST = re.compile(r"\$\(|`|<\(|>\(")
_LOOPBACK = re.compile(r"^(https?://)?(127\.\d+\.\d+\.\d+|localhost|\[::1\])(:\d+)?(/|$)", re.I)
_ENV = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
_SECRET = re.compile(r"(^|[/\\~])\.(ssh|claude|aws|gnupg)([/\\]|$)|\.netrc|\.git-credentials|\bid_(rsa|ed25519|ecdsa)"
                     r"|\.local[/\\]state[/\\]xmuse|sidebar\.key", re.I)
_SHELLS = {"sh", "bash", "zsh", "dash", "fish", "ksh", "pwsh", "powershell", "cmd", "cmd.exe"}
_OPS = {";", "&&", "||", "|", "&", "\n", "|&", ";;"}
_REDIRECT = re.compile(r"^\d*>>?$|^&>>?$")

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


def _inside(path: str, ws: str) -> bool:
    """A path an agent may change without asking: under /tmp, /dev/null, or inside the workspace."""
    if not path or any(c in path for c in "*?["):
        return False
    if path.startswith("~") or path.startswith("$"):
        return False
    full = os.path.normpath(path if os.path.isabs(path) else os.path.join(ws, path))
    if full in ("/dev/null", "/dev/stdout", "/dev/stderr") or full.startswith("/tmp/") or full == "/tmp":
        return True
    root = os.path.normpath(ws)
    return full == root or full.startswith(root.rstrip("/\\") + os.sep) or full.startswith(root.rstrip("/\\") + "/")


def _pieces(cmd: str) -> list[list[str]] | None:
    lex = shlex.shlex(cmd.replace("\n", " ; "), posix=True, punctuation_chars=";&|<>")  # a line is a command
    lex.whitespace_split = True
    lex.commenters = ""
    try:
        toks = list(lex)
    except ValueError:
        return None
    out, cur = [], []
    for t in toks:
        if t in _OPS or set(t) <= set(";&|"):
            if cur:
                out.append(cur)
            cur = []
        else:
            cur.append(t)
    if cur:
        out.append(cur)
    return out


def _flags(args: list[str]) -> set[str]:
    f = set()
    for a in args:
        if a.startswith("--"):
            f.add(a)
        elif a.startswith("-") and len(a) > 1:
            f.update("-" + c for c in a[1:])
    return f


def _one(argv: list[str], ws: str) -> str | None:
    while argv and _ENV.match(argv[0]):
        argv = argv[1:]
    while argv and argv[0] in ("env", "command", "nohup", "time", "exec", "nice", "timeout"):
        argv = argv[1:]
        while argv and (argv[0].startswith("-") or _ENV.match(argv[0]) or re.fullmatch(r"\d+[smhd]?", argv[0])):
            argv = argv[1:]
    if not argv:
        return None
    name = argv[0].replace("\\", "/").rsplit("/", 1)[-1].lower()
    args = argv[1:]
    # redirections first: a write outside the workspace, whatever the command
    for i, a in enumerate(args):
        if _REDIRECT.match(a) and i + 1 < len(args) and not _inside(args[i + 1], ws):
            return f"writes outside the workspace ({args[i + 1]})"
        m = re.match(r"^\d*>>?(.+)$", a)
        if m and not m.group(1).startswith("&") and not _inside(m.group(1), ws):
            return f"writes outside the workspace ({m.group(1)})"
    plain = []  # the arguments without redirections (2>&1, > file, < file)
    for i, a in enumerate(args):
        if re.fullmatch(r"[<>&]+\d*", a) or (i and re.fullmatch(r"[<>&]+", args[i - 1])) or \
                (a.isdigit() and i + 1 < len(args) and re.fullmatch(r"[<>&]+", args[i + 1])):
            continue
        plain.append(a)
    args = plain
    fl = _flags(args)
    if name in ("sudo", "su", "doas"):
        return name
    if name in ("eval", "source", "."):
        return f"{name} runs code this check cannot read"
    if name in _SHELLS and ("-c" in fl or "-command" in {a.lower() for a in args} or "/c" in {a.lower() for a in args}):
        return f"{name} -c runs a script this check cannot read"
    if name in _SHELLS and not [a for a in args if not a.startswith("-")]:
        return f"{name} runs a script from its input"
    if name == "xmuse" and args[:1] and args[0] in ("send", "approve"):
        return f"xmuse {args[0]} (admin command)"
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
        return _one(inner, ws)
    if name == "find":
        starts = [a for a in args if not a.startswith(("-", "(", ")", "!"))][:1] or ["."]
        acts = {"-delete", "-exec", "-execdir", "-ok", "-okdir"} & set(args)
        if acts and not all(_inside(s, ws) for s in starts):
            return f"find {' '.join(sorted(acts))} outside the workspace"
        for i, a in enumerate(args):
            if a in ("-exec", "-execdir", "-ok", "-okdir"):
                inner = []
                for t in args[i + 1:]:
                    if t in (";", "\\;", "+"):
                        break
                    inner.append(t)
                why = _one(inner, ws)
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
            bad = [a for a in args if not a.startswith("-") and not _inside(a, ws)]
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
        return _fetch(name, args, ws)
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


def _fetch(name: str, args: list[str], ws: str) -> str | None:
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


def risky(cmd: str, ws: str) -> str | None:
    """Why `cmd` (one shell command line, run in workspace `ws`) needs the user, or None."""
    if not isinstance(cmd, str) or not cmd.strip():
        return None
    if _SUBST.search(cmd):
        return "command substitution this check cannot read"
    if _SECRET.search(cmd):
        return "touches credentials or xmuse's own state"
    pieces = _pieces(cmd)
    if pieces is None:
        return "unbalanced quotes"
    for argv in pieces:
        why = _one(argv, ws)
        if why:
            return why
    return None
