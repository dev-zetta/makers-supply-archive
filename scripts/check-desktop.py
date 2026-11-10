#!/usr/bin/env python3
"""Extract the delivered app and data packs, then run its real Electron smoke test."""

from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.request
import zipfile
from pathlib import Path

from makers_supply.storage import atomic_write
from makers_supply.validation import sha256_file


def check_backend(installed: Path) -> None:
    if sys.platform == "darwin":
        backend = next(installed.glob("*.app/Contents/Resources/backend/makers-supply-backend"))
    else:
        backend = (
            installed
            / "resources/backend"
            / ("makers-supply-backend.exe" if sys.platform == "win32" else "makers-supply-backend")
        )
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    with (
        tempfile.TemporaryDirectory(prefix="backend-state-Ž-") as state,
        tempfile.TemporaryFile() as log,
    ):
        service = subprocess.Popen(
            [
                str(backend),
                "--port",
                str(port),
                "--data-dir",
                str(installed),
                "--state-dir",
                state,
            ],
            stdout=log,
            stderr=log,
        )
        try:
            for _ in range(1200):
                if service.poll() is not None:
                    break
                try:
                    with urllib.request.urlopen(f"http://127.0.0.1:{port}/healthz", timeout=1):
                        print("packaged sidecar preflight passed", flush=True)
                        return
                except OSError:
                    time.sleep(0.1)
            log.seek(0)
            detail = log.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"packaged sidecar did not start: {detail[-16000:]}")
        finally:
            if service.poll() is None:
                service.terminate()
            service.wait(timeout=15)


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
        check_backend(installed)
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
                    "graphics": "software-swangle"
                    if os.environ.get("E2E_DESKTOP_SOFTWARE_GPU") == "1"
                    else "default",
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
