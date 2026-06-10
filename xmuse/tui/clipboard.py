from __future__ import annotations

import shutil
import subprocess
import tempfile
from collections.abc import Iterable, Sequence
from pathlib import Path

ClipboardCommand = Sequence[str]


def copy_to_system_clipboard(
    text: str,
    *,
    candidates: Iterable[ClipboardCommand] | None = None,
    timeout_s: float = 2.0,
) -> bool:
    if not text:
        return False
    if candidates is None and _copy_to_windows_clipboard(text, timeout_s=timeout_s):
        return True
    for command in candidates or _default_clipboard_commands():
        resolved = _resolve_command(command)
        if resolved is None:
            continue
        try:
            subprocess.run(
                resolved,
                input=text,
                text=True,
                encoding="utf-8",
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=timeout_s,
                check=True,
            )
        except (OSError, subprocess.SubprocessError, UnicodeError):
            continue
        return True
    return False


def _default_clipboard_commands() -> tuple[ClipboardCommand, ...]:
    return (
        ("wl-copy",),
        ("xclip", "-selection", "clipboard"),
        ("xsel", "--clipboard", "--input"),
        ("clip.exe",),
        ("/mnt/c/WINDOWS/system32/clip.exe",),
    )


def _copy_to_windows_clipboard(text: str, *, timeout_s: float) -> bool:
    powershell = shutil.which("powershell.exe") or _existing_path(
        "/mnt/c/WINDOWS/System32/WindowsPowerShell/v1.0/powershell.exe"
    )
    wslpath = shutil.which("wslpath")
    if not powershell or not wslpath:
        return False

    tmp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            delete=False,
            prefix="xmuse-clipboard-",
            suffix=".txt",
        ) as tmp:
            tmp.write(text)
            tmp_path = Path(tmp.name)
        windows_path = subprocess.check_output(
            [wslpath, "-w", str(tmp_path)],
            text=True,
            encoding="utf-8",
            stderr=subprocess.DEVNULL,
            timeout=timeout_s,
        ).strip()
        if not windows_path:
            return False
        script = (
            "$p = "
            + _powershell_single_quoted(windows_path)
            + "; Set-Clipboard -Value (Get-Content -LiteralPath $p -Raw -Encoding UTF8)"
        )
        subprocess.run(
            [powershell, "-NoProfile", "-Command", script],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=timeout_s,
            check=True,
        )
        return True
    except (OSError, subprocess.SubprocessError, UnicodeError):
        return False
    finally:
        if tmp_path is not None:
            try:
                tmp_path.unlink()
            except OSError:
                pass


def _existing_path(path: str) -> str | None:
    return path if Path(path).exists() else None


def _powershell_single_quoted(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _resolve_command(command: ClipboardCommand) -> list[str] | None:
    if not command:
        return None
    executable = command[0]
    if "/" in executable:
        if not Path(executable).exists():
            return None
        return list(command)
    resolved = shutil.which(executable)
    if not resolved:
        return None
    return [resolved, *command[1:]]
