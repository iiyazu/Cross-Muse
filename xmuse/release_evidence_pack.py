"""CLI for writing an xmuse release evidence pack."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from xmuse_core.platform.release_evidence_pack import capture_release_evidence_pack
from xmuse_core.runtime.paths import default_xmuse_root

DEFAULT_XMUSE_ROOT = default_xmuse_root(Path(__file__).resolve().parent)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--artifacts-dir",
        type=Path,
        default=DEFAULT_XMUSE_ROOT / "work" / "release_readiness" / "artifacts",
        help="Directory containing release gate JSON artifacts.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_XMUSE_ROOT
        / "work"
        / "release_readiness"
        / "evidence-pack.json",
        help="Path for the release evidence pack JSON report.",
    )
    parser.add_argument(
        "--readiness-output",
        type=Path,
        default=None,
        help="Optional path for the nested release-readiness report.",
    )
    parser.add_argument(
        "--audit-output",
        type=Path,
        default=None,
        help="Optional path for the nested proof-contamination audit report.",
    )
    parser.add_argument(
        "--replay-output",
        type=Path,
        default=None,
        help="Optional path for the nested overnight replay bundle report.",
    )
    parser.add_argument(
        "--run-id",
        default="release-evidence-pack",
        help="Stable overnight run id to place in the nested replay bundle.",
    )
    parser.add_argument(
        "--section-artifact",
        action="append",
        default=[],
        metavar="SECTION=PATH",
        help=(
            "Attach an xmuse.production_evidence.v1 artifact for a required "
            "overnight replay section. May be repeated."
        ),
    )
    parser.add_argument(
        "--tombstoned-source-ref",
        action="append",
        default=[],
        help="Source ref that must be excluded from active replay refs.",
    )
    args = parser.parse_args(argv)
    pack = capture_release_evidence_pack(
        artifacts_dir=args.artifacts_dir,
        output_path=args.output,
        run_id=args.run_id,
        readiness_output=args.readiness_output,
        audit_output=args.audit_output,
        replay_output=args.replay_output,
        section_artifacts=_section_artifacts(args.section_artifact),
        tombstoned_source_refs=tuple(args.tombstoned_source_ref),
    )
    print(json.dumps({"decision": pack["decision"], "output": str(args.output)}, sort_keys=True))
    return 2 if pack["decision"] == "contaminated" else 0


def _section_artifacts(values: list[str]) -> dict[str, Path]:
    artifacts: dict[str, Path] = {}
    for value in values:
        if "=" not in value:
            raise SystemExit(
                "--section-artifact must use SECTION=PATH, for example "
                "supervisor=/tmp/supervisor.json"
            )
        section_id, path = value.split("=", 1)
        section_id = section_id.strip()
        path = path.strip()
        if not section_id or not path:
            raise SystemExit("--section-artifact requires non-empty SECTION and PATH")
        artifacts[section_id] = Path(path)
    return artifacts


if __name__ == "__main__":
    raise SystemExit(main())
