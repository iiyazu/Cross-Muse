"""Safe-overlay Settings using pydantic-settings.

This is purely additive and optional — it does NOT replace any existing
``os.environ.get()`` calls anywhere in the codebase.
"""

from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration overlay backed by env vars and ``.env`` files.

    pydantic-settings v2 auto-maps ``snake_case`` field names to ``UPPER_CASE``
    environment variables and loads ``.env`` files automatically.
    """

    # Runtime
    xmuse_root: Path = Path("./xmuse")

    # Provider / Model
    codex_model: str = "gpt-5.4"
    deepseek_api_key: str = ""
    deepseek_model: str = "deepseek-v4-flash"
    deepseek_base_url: str | None = None

    # Runtime Backend / GOD
    runtime_backend: str = "ray"
    review_god_backend: str = "ray"
    execute_god_backend: str = "ray"
    peer_god_backend: str = "native"
    degraded_local_god_mode: bool = False
    ray_god_transport: str = "app-server"
    ray_god_effort: str = "low"
    ray_god_mcp: bool = False

    # Orchestrator
    reconcile_gate_review_concurrency: int | None = None
    recovery: str = ""

    # TUI / Dashboard
    chat_api_url: str = "http://127.0.0.1:8201"
    superpowers: bool = False

    # Legacy
    review_gate: bool = True
    review_codex_cmd: str = "codex"
    review_model: str = "gpt-5.5"
    review_timeout_s: int = 300
    loop_root: str | None = None
    report_only: bool = False
    max_hours: int = 10
    monitor_interval_seconds: int = 600
    monitor_log_file: str = "/tmp/xmuse_scheduler_monitor.log"
    monitor_pid_file: str = "/tmp/xmuse_scheduler_monitor.pid"
    monitor_lock_file: str = "/tmp/xmuse_scheduler_monitor.lock"

    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
        frozen=True,
    )


_settings: Settings | None = None


def get_settings() -> Settings:
    """Return a cached Settings singleton."""
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


def validate_runtime_config() -> list[str]:
    """Check required config. Returns list of warnings (empty = all good)."""
    warnings: list[str] = []
    settings = get_settings()
    if not settings.deepseek_api_key:
        warnings.append("DEEPSEEK_API_KEY is not set — OpenCode worker will be UNAVAILABLE")
    if not settings.deepseek_api_key and any(
        [
            settings.review_god_backend != "ray",
            settings.execute_god_backend != "ray",
        ]
    ):
        warnings.append("Non-Ray GOD backends may require additional configuration")
    return warnings


__all__ = [
    "Settings",
    "get_settings",
    "validate_runtime_config",
]
