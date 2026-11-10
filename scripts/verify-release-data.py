#!/usr/bin/env python3
"""Verify and extract the shared packs in CI before testing a packaged application."""

from __future__ import annotations

import argparse
import hashlib
import shutil
import zipfile
from pathlib import Path

from makers_supply.release import ReleaseManifest, verify_installed_catalog
from makers_supply.validation import sha256_file


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--packs", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    args = parser.parse_args()
    release = ReleaseManifest.model_validate_json(
        (args.packs / "release-manifest.json").read_bytes()
    )
    root = args.destination.resolve()
    root.mkdir(parents=True, exist_ok=True)
    seen: set[str] = set()
    for pack in release.packs:
        path = (args.packs / pack.name).resolve()
        if not path.is_relative_to(args.packs.resolve()) or not path.is_file():
            raise ValueError(f"missing data pack: {pack.name}")
        if path.stat().st_size != pack.size or sha256_file(path) != pack.sha256:
            raise ValueError(f"data pack checksum mismatch: {pack.name}")
        with zipfile.ZipFile(path) as archive:
            for info in archive.infolist():
                target = (root / info.filename).resolve()
                if (
                    not target.is_relative_to(root)
                    or info.filename in seen
                    or info.is_dir()
                    or (info.external_attr >> 16) & 0o170000 == 0o120000
                ):
                    raise ValueError(f"unsafe or duplicate pack entry: {info.filename}")
                seen.add(info.filename)
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(info) as source, target.open("wb") as output:
                    shutil.copyfileobj(source, output)
    bootstrap = (root / "catalog-manifest.json").read_bytes()
    if hashlib.sha256(bootstrap).hexdigest() != release.data_manifest_sha256:
        raise ValueError("catalog manifest checksum mismatch")
    manifest = verify_installed_catalog(root, full_hash=True)
    if manifest.snapshot_id != release.snapshot_id or manifest.revision != release.revision:
        raise ValueError("data packs do not match release identity")
    print(f"verified {len(manifest.files)} payload files for {manifest.snapshot_id}")


if __name__ == "__main__":
    main()
