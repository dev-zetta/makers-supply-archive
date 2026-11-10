#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

from makers_supply.release_evidence import record_acceptance, verify_acceptance


def main() -> None:
    parser = argparse.ArgumentParser(description="Record or verify fresh release acceptance")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--output", type=Path, default=Path("reports/release-validation.json"))
    parser.add_argument(
        "--reviewed-live-changes",
        type=Path,
        help="Explicitly accept documented live commerce changes using a sibling review receipt",
    )
    args = parser.parse_args()
    if args.check:
        if args.reviewed_live_changes is not None:
            parser.error("--check reads the acceptance policy from the recorded receipt")
        verify_acceptance(args.root.resolve(), args.output.resolve())
    else:
        record_acceptance(
            args.root.resolve(), args.output.resolve(), reviewed_changes=args.reviewed_live_changes
        )
    print("release acceptance verified" if args.check else "release acceptance recorded")


if __name__ == "__main__":
    main()
