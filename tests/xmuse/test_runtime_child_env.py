from __future__ import annotations

from xmuse_core.runtime.child_env import normalize_child_temp_env


def test_normalize_child_temp_env_rewrites_windows_mount_temp() -> None:
    env = {
        "TMPDIR": "/mnt/c/Users/iiyatu/AppData/Local/Temp",
        "TMP": "/mnt/c/Users/iiyatu/AppData/Local/Temp",
        "TEMP": "/mnt/c/Users/iiyatu/AppData/Local/Temp",
        "KEEP": "value",
    }

    normalized = normalize_child_temp_env(env)

    assert normalized["TMPDIR"] == "/tmp"
    assert normalized["TMP"] == "/tmp"
    assert normalized["TEMP"] == "/tmp"
    assert normalized["KEEP"] == "value"
    assert env["TMPDIR"] == "/mnt/c/Users/iiyatu/AppData/Local/Temp"


def test_normalize_child_temp_env_preserves_linux_temp_when_no_override() -> None:
    env = {"TMPDIR": "/var/tmp", "TMP": "/tmp", "TEMP": "/tmp"}

    assert normalize_child_temp_env(env) == env


def test_normalize_child_temp_env_honors_explicit_override(tmp_path) -> None:
    child_tmp = tmp_path / "child-tmp"
    env = {"XMUSE_CHILD_TMPDIR": str(child_tmp), "TMPDIR": "/var/tmp"}

    normalized = normalize_child_temp_env(env)

    assert normalized["TMPDIR"] == str(child_tmp)
    assert normalized["TMP"] == str(child_tmp)
    assert normalized["TEMP"] == str(child_tmp)
    assert child_tmp.is_dir()
