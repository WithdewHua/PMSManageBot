"""Freeze runtime behavior and source provenance as separate artifacts."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from scripts.refactor.snapshot import build_snapshot

RUNTIME_KEYS = ("schema", "openapi", "metadata", "scheduler", "bot", "facade")


def build_core_utility_snapshots() -> tuple[dict, dict]:
    snapshot = build_snapshot()
    runtime = {key: snapshot[key] for key in RUNTIME_KEYS}
    provenance = {"schema": snapshot["schema"], "references": snapshot["references"]}
    return runtime, provenance


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime-output", type=Path, required=True)
    parser.add_argument("--provenance-output", type=Path, required=True)
    args = parser.parse_args()
    runtime, provenance = build_core_utility_snapshots()
    for path, value in (
        (args.runtime_output, runtime),
        (args.provenance_output, provenance),
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )


if __name__ == "__main__":
    main()
