"""Freeze public interfaces before promoting the remaining six domains.

Internal implementation symbols are deliberately excluded. Responses under
rejections and mutations are frozen by domain-specific behavioral tests.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from scripts.refactor.snapshot import _dump, build_snapshot

ROOT = Path(__file__).resolve().parents[2]
BASELINE_COMMIT = "761b0a5"
DOMAINS = (
    "donation",
    "crypto_donation",
    "vaultwarden",
    "rankings",
    "reports",
    "profile",
)


def build_remaining_snapshot() -> dict:
    snapshot = build_snapshot()
    return {
        "schema": 1,
        "openapi": snapshot["openapi"],
        "bot": snapshot["bot"],
        "scheduler": snapshot["scheduler"],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.write_text(_dump(build_remaining_snapshot()), encoding="utf-8")


if __name__ == "__main__":
    main()
