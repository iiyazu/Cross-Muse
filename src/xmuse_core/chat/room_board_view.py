"""Host-owned per-owner board views mounted read-only into owner clones."""

from __future__ import annotations

import json
import logging
import os
import tempfile
from hashlib import sha256
from pathlib import Path
from typing import Any

from xmuse_core.chat.room_board import RoomBoardStore
from xmuse_core.chat.room_database import RoomDatabase
from xmuse_core.chat.room_owner_ids import owner_id_for_participant

logger = logging.getLogger(__name__)

BOARD_VIEW_SCHEMA_VERSION = "room_board_view/v1"


def _atomic_write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.tmp.")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            try:
                os.fsync(handle.fileno())
            except OSError:
                pass
        os.replace(tmp_name, path)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def _atomic_write_text(path: Path, text: str) -> None:
    _atomic_write_bytes(path, text.encode("utf-8"))


def _render_charter_md(
    *,
    participant_id: str,
    board_seq: int,
    my_modules: list[dict[str, Any]],
    other_modules: list[dict[str, Any]],
) -> str:
    lines: list[str] = [f"# Board view for {participant_id}", ""]
    if not my_modules:
        lines.append("This participant owns nothing.")
        lines.append("")
        return "\n".join(lines)
    lines.append(f"Board seq: {board_seq}")
    lines.append("")
    lines.append(f"## Owned modules ({len(my_modules)})")
    lines.append("")
    for entry in my_modules:
        charter = entry.get("charter", {})
        if not isinstance(charter, dict):
            charter = {}
        module_id = str(entry.get("module_id", ""))
        title = str(charter.get("title", ""))
        version = entry.get("version", "")
        paths = charter.get("paths", [])
        provides = charter.get("provides", [])
        depends = charter.get("depends", [])
        acceptance = charter.get("acceptance", [])
        report_to = charter.get("report_to")
        lines.append(f"### {module_id} — {title} (v{version})")
        lines.append("")
        lines.append(f"- Module: {module_id}")
        lines.append(f"- Title: {title}")
        lines.append(f"- Version: {version}")
        lines.append(
            "- Paths: " + (", ".join(str(p) for p in paths) if isinstance(paths, list) else "")
        )
        lines.append(
            "- Provides: "
            + (", ".join(str(p) for p in provides) if isinstance(provides, list) else "")
        )
        lines.append(
            "- Depends: "
            + (", ".join(str(p) for p in depends) if isinstance(depends, list) else "")
        )
        if isinstance(acceptance, list) and acceptance:
            lines.append("- Acceptance:")
            for item in acceptance:
                lines.append(f"  - {item}")
        else:
            lines.append("- Acceptance: none")
        lines.append(f"- Report to: {report_to if report_to else 'none'}")
        lines.append("")
    lines.append("## Other modules")
    lines.append("")
    if not other_modules:
        lines.append("No other active modules.")
        lines.append("")
    else:
        lines.append("| module | version | owner |")
        lines.append("| --- | --- | --- |")
        for other in other_modules:
            lines.append(
                f"| {other.get('module_id', '')} "
                f"| {other.get('version', '')} "
                f"| {other.get('owner_participant_id', '')} |"
            )
        lines.append("")
    return "\n".join(lines)


def materialize_owner_board_view(
    db_path: Path | str,
    conversation_id: str,
    participant_id: str,
    target_dir: Path | str,
) -> str:
    """Write one owner's board view into an existing directory, atomically."""

    target = Path(target_dir)
    store = RoomBoardStore(Path(db_path))
    view = store.owner_view(conversation_id=conversation_id, participant_id=participant_id)
    board_seq = int(view.get("board_seq", 0))
    my_modules = list(view.get("my_modules", []))
    other_modules = list(view.get("other_modules", []))
    contracts = list(view.get("contracts", []))

    index_contracts: list[dict[str, Any]] = []
    referenced: dict[str, dict[str, Any]] = {}
    for contract in sorted(contracts, key=lambda c: str(c.get("contract_id", ""))):
        contract_id = str(contract.get("contract_id", ""))
        version = int(contract.get("version", 0))
        filename = f"contracts/{contract_id}@v{version}.txt"
        index_contracts.append(
            {
                "contract_id": contract_id,
                "version": version,
                "digest": str(contract.get("digest", "")),
                "provider_module_id": str(contract.get("provider_module_id", "")),
                "kind": str(contract.get("kind", "")),
                "file": filename,
            }
        )
        referenced[filename] = contract

    index = {
        "schema_version": BOARD_VIEW_SCHEMA_VERSION,
        "conversation_id": conversation_id,
        "participant_id": participant_id,
        "board_seq": board_seq,
        "my_modules": sorted(my_modules, key=lambda m: str(m.get("module_id", ""))),
        "other_modules": sorted(other_modules, key=lambda m: str(m.get("module_id", ""))),
        "contracts": index_contracts,
    }
    index_bytes = (json.dumps(index, sort_keys=True, indent=2) + "\n").encode("utf-8")
    _atomic_write_bytes(target / "INDEX.json", index_bytes)

    charter_md = _render_charter_md(
        participant_id=participant_id,
        board_seq=board_seq,
        my_modules=sorted(my_modules, key=lambda m: str(m.get("module_id", ""))),
        other_modules=sorted(other_modules, key=lambda m: str(m.get("module_id", ""))),
    )
    _atomic_write_text(target / "charter.md", charter_md)

    contracts_dir = target / "contracts"
    if contracts_dir.is_symlink():
        try:
            contracts_dir.unlink()
        except OSError:
            pass
    if contracts_dir.is_file():
        try:
            contracts_dir.unlink()
        except OSError:
            pass
    contracts_dir.mkdir(parents=True, exist_ok=True)

    for filename, contract in referenced.items():
        dest = target / filename
        # Never write outside target_dir even for odd contract ids.
        try:
            dest.relative_to(target)
        except ValueError:
            continue
        content = contract.get("content", "")
        if not isinstance(content, str):
            content = str(content)
        _atomic_write_bytes(dest, content.encode("utf-8"))

    try:
        with os.scandir(contracts_dir) as entries:
            names = [entry.name for entry in entries]
    except FileNotFoundError:
        names = []
    referenced_names = {Path(name).name for name in (Path(f).name for f in referenced)}
    for name in names:
        if name in referenced_names or name.startswith("."):
            # Tmp files from concurrent writers start with "."; leave them.
            continue
        stale = contracts_dir / name
        try:
            if stale.is_symlink() or stale.is_file():
                stale.unlink()
            # Directories are left alone; only files are managed.
        except OSError:
            continue

    return "sha256:" + sha256(index_bytes).hexdigest()


def refresh_board_views(xmuse_root: Path | str, conversation_id: str) -> list[str]:
    """Refresh every existing per-owner board directory for one conversation."""

    root = Path(xmuse_root)
    db_path = root / "chat.db"
    try:
        with RoomDatabase(db_path).connect(readonly=True) as conn:
            rows = conn.execute(
                "select module_id, max(version) from room_board_charters "
                "where conversation_id = ? group by module_id",
                (conversation_id,),
            ).fetchall()
            owners: dict[str, str] = {}
            for row in rows:
                module_id = str(row[0])
                latest = conn.execute(
                    "select owner_participant_id, status from room_board_charters "
                    "where conversation_id = ? and module_id = ? "
                    "order by version desc limit 1",
                    (conversation_id, module_id),
                ).fetchone()
                if latest is None or str(latest["status"]) != "active":
                    continue
                owners[str(latest["owner_participant_id"])] = module_id
    except Exception as exc:
        logger.warning("room board refresh failed to list owners: %s", exc)
        return []
    refreshed: list[str] = []
    for participant_id in sorted(owners):
        owner_id = owner_id_for_participant(conversation_id, participant_id)
        board_dir = root / "runtime" / "board" / owner_id
        try:
            if board_dir.is_symlink():
                continue
            if not board_dir.is_dir():
                continue
            materialize_owner_board_view(db_path, conversation_id, participant_id, board_dir)
        except Exception as exc:
            logger.warning("room board refresh failed for %s: %s", owner_id, exc)
            continue
        refreshed.append(owner_id)
    return refreshed


__all__ = [
    "BOARD_VIEW_SCHEMA_VERSION",
    "materialize_owner_board_view",
    "refresh_board_views",
]
