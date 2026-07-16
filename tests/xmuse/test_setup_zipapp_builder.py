from __future__ import annotations

import hashlib
import subprocess
import sys
from pathlib import Path

from scripts.build_setup_zipapp import build_setup_zipapp


def test_setup_zipapp_is_deterministic_and_executable(tmp_path: Path) -> None:
    repository = Path(__file__).parents[2]
    first = tmp_path / "first.pyz"
    second = tmp_path / "second.pyz"

    first_digest = build_setup_zipapp(output=first, repository=repository)
    second_digest = build_setup_zipapp(output=second, repository=repository)

    assert first_digest == second_digest
    assert hashlib.sha256(first.read_bytes()).hexdigest() == first_digest
    result = subprocess.run(
        [sys.executable, str(first), "--help"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "xmuse-setup" in result.stdout
