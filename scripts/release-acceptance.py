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
    args = parser.parse_args()
    operation = verify_acceptance if args.check else record_acceptance
    operation(args.root.resolve(), args.output.resolve())
    print("release acceptance verified" if args.check else "release acceptance recorded")


if __name__ == "__main__":
    main()
