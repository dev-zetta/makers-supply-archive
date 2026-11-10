#!/usr/bin/env python3
"""Extract the delivered app and data packs, then run its real Electron smoke test."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tarfile
import tempfile
import zipfile
from pathlib import Path

from makers_supply.storage import atomic_write
from makers_supply.validation import sha256_file


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app-archive", type=Path, required=True)
    parser.add_argument("--packs", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(prefix="catalog-installed-") as temporary:
        installed = Path(temporary)
        if args.app_archive.suffix == ".zip":
            with zipfile.ZipFile(args.app_archive) as archive:
                archive.extractall(installed)
        else:
            with tarfile.open(args.app_archive) as archive:
                archive.extractall(installed, filter="data")
        subprocess.run(
            [
                sys.executable,
                str(root / "scripts/verify-release-data.py"),
                "--packs",
                str(args.packs.resolve()),
                "--destination",
                str(installed),
            ],
            check=True,
        )
        build = json.loads((installed / "app-build.json").read_text("utf-8"))
        data = json.loads((installed / "catalog-manifest.json").read_text("utf-8"))
        if build["revision"] != data["revision"] or build["version"] != data["app_version"]:
            raise ValueError("app and catalog were built from different revisions")
        if sys.platform == "darwin":
            executable = next(installed.glob("*.app/Contents/MacOS/*"))
        else:
            executable = installed / (
                "makers-supply-catalog.exe" if sys.platform == "win32" else "makers-supply-catalog"
            )
        subprocess.run(
            [
                "node",
                "node_modules/@playwright/test/cli.js",
                "test",
                "--config",
                "desktop.playwright.config.ts",
            ],
            cwd=root / "apps/catalog-web/frontend",
            env={**os.environ, "E2E_DESKTOP_EXECUTABLE": str(executable)},
            check=True,
        )

        atomic_write(
            root / "apps/catalog-web/frontend/test-results/desktop/validation.json",
            json.dumps(
                {
                    "schema_version": 1,
                    "passed": True,
                    "version": build["version"],
                    "revision": build["revision"],
                    "platform": build["platform"],
                    "snapshot_id": data["snapshot_id"],
                    "app_archive": args.app_archive.name,
                    "app_sha256": sha256_file(args.app_archive),
                    "checks": [
                        "offline launch",
                        "search",
                        "STL",
                        "3MF",
                        "Unicode exports",
                        "list persistence",
                        "sidecar shutdown",
                    ],
                },
                indent=2,
            )
            + "\n",
        )


if __name__ == "__main__":
    main()
