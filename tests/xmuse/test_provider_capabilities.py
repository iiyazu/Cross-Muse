from __future__ import annotations

import json
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
        "XMUSE_ANTIGRAVITY_AGENTAPI": "/missing/agentapi",
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
        discover_language_server=lambda _environ: (_ for _ in ()).throw(
            AssertionError("discovery must not run without an agentapi binary")
        ),
    )

    assert set(capabilities) == {"codex", "claude", "antigravity"}
    for record in capabilities.values():
        assert set(record) == SAFE_KEYS
        assert isinstance(record["available"], bool)
        assert isinstance(record["enabled"], bool)
    assert capabilities["claude"]["confinement"] == "client_permission_gated"
    assert capabilities["antigravity"]["confinement"] == "instructed_read_only"
    assert capabilities["codex"]["confinement"] == "read_only_sandbox"
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


def test_antigravity_requires_agentapi_binary_and_live_language_server(tmp_path: Path) -> None:
    environ = _base_environ(tmp_path, XMUSE_ANTIGRAVITY_AGENTAPI="/opt/agentapi")
    discoveries: list[dict[str, str]] = []

    def discovery(source):
        discoveries.append(dict(source))
        return {"ANTIGRAVITY_LS_ADDRESS": "127.0.0.1:65000", "ANTIGRAVITY_CSRF_TOKEN": "t"}

    without_binary = detect_provider_capabilities(
        environ=environ,
        which=_which({}),
        discover_language_server=discovery,
    )
    assert without_binary["antigravity"]["available"] is False
    assert discoveries == []

    with_binary = detect_provider_capabilities(
        environ=environ,
        which=_which({"/opt/agentapi": "/opt/agentapi"}),
        discover_language_server=discovery,
    )
    assert with_binary["antigravity"]["available"] is True
    assert with_binary["antigravity"]["enabled"] is True
    assert discoveries == [environ]

    def failing_discovery(_environ):
        raise RuntimeError("language server not reachable")

    assert (
        detect_provider_capabilities(
            environ=environ,
            which=_which({"/opt/agentapi": "/opt/agentapi"}),
            discover_language_server=failing_discovery,
        )["antigravity"]["available"]
        is False
    )


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
