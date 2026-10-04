from __future__ import annotations

import json
import sys
from pathlib import Path

from xmuse.provider_capabilities import (
    ANTIGRAVITY_FLAG_ENV,
    CLAUDE_FLAG_ENV,
    detect_provider_capabilities,
)

SAFE_KEYS = {"available", "enabled", "confinement"}


def _which(paths: dict[str, str]):
    return lambda name: paths.get(name)


def _base_environ(tmp_path: Path, **overrides: str) -> dict[str, str]:
    return {
        "CODEX_HOME": str(tmp_path / "codex-home"),
        "XMUSE_AGY_COMMAND": "/missing/agy",
        **overrides,
    }


def test_projection_records_only_safe_fields_per_provider(tmp_path: Path) -> None:
    capabilities = detect_provider_capabilities(
        environ=_base_environ(tmp_path, XMUSE_CLAUDE_ACP_COMMAND="/secret/npx command"),
        which=_which(
            {
                "codex": "/secret/bin/codex",
                "claude": "/secret/bin/claude",
                "npx": "/secret/bin/npx",
            }
        ),
    )

    assert set(capabilities) == {"codex", "claude", "antigravity", "opencode"}
    for record in capabilities.values():
        assert set(record) == SAFE_KEYS
        assert isinstance(record["available"], bool)
        assert isinstance(record["enabled"], bool)
    assert capabilities["claude"]["confinement"] == "client_permission_gated"
    assert capabilities["antigravity"]["confinement"] == "os_read_only_sandbox"
    assert capabilities["codex"]["confinement"] == "read_only_sandbox"
    assert capabilities["opencode"]["confinement"] == "os_read_only_sandbox"
    serialized = json.dumps(capabilities)
    assert "/secret" not in serialized


def test_claude_availability_requires_cli_and_npx(tmp_path: Path) -> None:
    environ = _base_environ(tmp_path)

    only_cli = detect_provider_capabilities(
        environ=environ,
        which=_which({"claude": "/usr/bin/claude"}),
    )
    assert only_cli["claude"]["available"] is False
    assert only_cli["claude"]["enabled"] is False

    both = detect_provider_capabilities(
        environ=environ,
        which=_which({"claude": "/usr/bin/claude", "npx": "/usr/bin/npx"}),
    )
    assert both["claude"]["available"] is True
    assert both["claude"]["enabled"] is True


def test_opencode_availability_requires_cli_and_bubblewrap(tmp_path: Path) -> None:
    environ = _base_environ(tmp_path, HOME=str(tmp_path / "home"))

    only_cli = detect_provider_capabilities(
        environ=environ,
        which=_which({"opencode": "/usr/bin/opencode"}),
    )
    assert only_cli["opencode"]["available"] is False
    assert only_cli["opencode"]["enabled"] is False

    sandboxed = detect_provider_capabilities(
        environ=environ,
        which=_which({"opencode": "/usr/bin/opencode", "bwrap": "/usr/bin/bwrap"}),
    )
    assert sandboxed["opencode"]["available"] is True
    assert sandboxed["opencode"]["enabled"] is True


def test_codex_availability_requires_an_authentication_carrier(tmp_path: Path) -> None:
    codex_home = tmp_path / "codex-home"
    environ = _base_environ(tmp_path)
    which = _which({"codex": "/usr/bin/codex"})

    assert detect_provider_capabilities(environ=environ, which=which)["codex"]["available"] is False

    codex_home.mkdir()
    (codex_home / "auth.json").write_text("{}\n", encoding="utf-8")
    assert detect_provider_capabilities(environ=environ, which=which)["codex"]["available"] is True

    assert (
        detect_provider_capabilities(
            environ={**environ, "OPENAI_API_KEY": "sk-test"},
            which=which,
        )["codex"]["available"]
        is True
    )


def test_antigravity_requires_agy_bwrap_and_python3(tmp_path: Path) -> None:
    agy = tmp_path / "agy"
    agy.write_text("#!/bin/sh\n", encoding="utf-8")
    bwrap = tmp_path / "bwrap"
    bwrap.write_text("#!/bin/sh\n", encoding="utf-8")
    home = tmp_path / "home"
    home.mkdir()
    environ = {
        "CODEX_HOME": str(tmp_path / "codex-home"),
        "HOME": str(home),
        "XMUSE_AGY_COMMAND": str(agy),
    }
    full_which = _which(
        {"bwrap": str(bwrap), "python3": sys.executable},
    )

    assert (
        detect_provider_capabilities(environ=environ, which=_which({}))["antigravity"]["available"]
        is False
    )

    without_bwrap = detect_provider_capabilities(
        environ=environ,
        which=_which({"python3": sys.executable}),
    )
    assert without_bwrap["antigravity"]["available"] is False

    without_python = detect_provider_capabilities(
        environ=environ,
        which=_which({"bwrap": str(bwrap)}),
    )
    assert without_python["antigravity"]["available"] is False

    sandboxed = detect_provider_capabilities(environ=environ, which=full_which)
    assert sandboxed["antigravity"]["available"] is True
    assert sandboxed["antigravity"]["enabled"] is True

    refused = detect_provider_capabilities(
        environ={**environ, ANTIGRAVITY_FLAG_ENV: "0"},
        which=full_which,
    )
    assert refused["antigravity"]["available"] is True
    assert refused["antigravity"]["enabled"] is False


def test_explicit_flags_override_auto_enablement(tmp_path: Path) -> None:
    refused = detect_provider_capabilities(
        environ=_base_environ(tmp_path, **{CLAUDE_FLAG_ENV: "0"}),
        which=_which({"claude": "/usr/bin/claude", "npx": "/usr/bin/npx"}),
    )
    assert refused["claude"] == {
        "available": True,
        "enabled": False,
        "confinement": "client_permission_gated",
    }

    requested = detect_provider_capabilities(
        environ=_base_environ(tmp_path, **{ANTIGRAVITY_FLAG_ENV: "1"}),
        which=_which({}),
    )
    assert requested["antigravity"]["available"] is False
    assert requested["antigravity"]["enabled"] is True
