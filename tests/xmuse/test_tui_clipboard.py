from __future__ import annotations

import subprocess
from pathlib import Path

import xmuse.tui.clipboard as clipboard_module
from xmuse.tui.clipboard import copy_to_system_clipboard


def test_copy_to_system_clipboard_prefers_windows_utf8_bridge(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_which(name: str) -> str | None:
        return {
            "powershell.exe": "/usr/bin/powershell.exe",
            "wslpath": "/usr/bin/wslpath",
        }.get(name)

    def fake_check_output(command, **kwargs):
        captured["wslpath_command"] = command
        captured["tmp_path"] = command[-1]
        return r"\\wsl.localhost\Ubuntu-24.04\tmp\xmuse-clipboard.txt" + "\n"

    def fake_run(command, **kwargs):
        captured["powershell_command"] = command
        tmp_path = Path(str(captured["tmp_path"]))
        captured["tmp_text"] = tmp_path.read_text(encoding="utf-8")
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(clipboard_module.shutil, "which", fake_which)
    monkeypatch.setattr(clipboard_module.subprocess, "check_output", fake_check_output)
    monkeypatch.setattr(clipboard_module.subprocess, "run", fake_run)

    copied = copy_to_system_clipboard("我已收到。当前 CLI GOD 响应超时。")

    assert copied is True
    assert captured["tmp_text"] == "我已收到。当前 CLI GOD 响应超时。"
    assert captured["wslpath_command"][:2] == ["/usr/bin/wslpath", "-w"]
    assert captured["powershell_command"][:3] == [
        "/usr/bin/powershell.exe",
        "-NoProfile",
        "-Command",
    ]
    assert "Encoding UTF8" in str(captured["powershell_command"][3])
    assert r"'\\wsl.localhost\Ubuntu-24.04\tmp\xmuse-clipboard.txt'" in str(
        captured["powershell_command"][3]
    )


def test_copy_to_system_clipboard_uses_available_command(tmp_path: Path) -> None:
    out = tmp_path / "clipboard.txt"
    script = tmp_path / "fake_clip.sh"
    script.write_text(f"#!/bin/sh\ncat > {out}\n", encoding="utf-8")
    script.chmod(script.stat().st_mode | 0o111)

    copied = copy_to_system_clipboard(
        "hello from xmuse",
        candidates=((str(script),),),
    )

    assert copied is True
    assert out.read_text(encoding="utf-8") == "hello from xmuse"


def test_copy_to_system_clipboard_returns_false_when_no_command(tmp_path: Path) -> None:
    missing = tmp_path / "missing-clip"

    copied = copy_to_system_clipboard(
        "hello",
        candidates=((str(missing),),),
    )

    assert copied is False
