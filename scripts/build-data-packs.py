#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

from makers_supply.release import PACK_LIMIT, build_data_packs
from makers_supply.storage import Catalog


def main() -> None:
    parser = argparse.ArgumentParser(description="Build shared offline catalog ZIP packs")
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--output", type=Path, default=Path("dist/data-packs"))
    parser.add_argument("--revision", required=True)
    parser.add_argument("--max-pack-bytes", type=int, default=PACK_LIMIT)
    args = parser.parse_args()
    manifest = build_data_packs(
        Catalog(args.root.resolve()),
        args.output.resolve(),
        revision=args.revision,
        max_pack_bytes=args.max_pack_bytes,
    )
    print(f"built {len(manifest.packs)} shared data packs for {manifest.snapshot_id}")


if __name__ == "__main__":
    main()
