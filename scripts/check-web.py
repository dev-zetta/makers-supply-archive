#!/usr/bin/env python3
"""Run browser tests against temporary state, never a developer's real accounts."""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

from makers_supply_web.security import PASSWORDS, now
from makers_supply_web.state import connect, migrate

from makers_supply.database import build_database
from makers_supply.storage import Catalog


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(prefix="catalog-web-test-") as temporary:
        work = Path(temporary)
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        build_database(Catalog(root), work / "catalog.sqlite")
        migrate(work / "state.sqlite")
        with connect(work / "state.sqlite") as connection, connection:
            connection.execute(
                "INSERT INTO users VALUES ('e2e', 'e2e-admin', ?, 1, 1, ?)",
                (PASSWORDS.hash("e2e secure password"), now().isoformat()),
            )
        environment = {
            **os.environ,
            "MAKERS_SUPPLY_ROOT": str(root),
            "MAKERS_SUPPLY_CATALOG_DB": str(work / "catalog.sqlite"),
            "MAKERS_SUPPLY_STATE_DB": str(work / "state.sqlite"),
            "MAKERS_SUPPLY_SECRET_KEY": "temporary-e2e-secret-only",
            "MAKERS_SUPPLY_SECURE_COOKIES": "0",
            "E2E_BASE_URL": f"http://127.0.0.1:{port}",
            "E2E_PASSWORD": "e2e secure password",
        }
        with (work / "server.log").open("w+") as log:
            server = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "uvicorn",
                    "makers_supply_web.app:app",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(port),
                ],
                env=environment,
                stdout=log,
                stderr=log,
            )
            try:
                for _ in range(100):
                    if server.poll() is not None:
                        raise RuntimeError("test server stopped before becoming ready")
                    try:
                        with urllib.request.urlopen(
                            environment["E2E_BASE_URL"] + "/healthz", timeout=1
                        ):
                            break
                    except OSError:
                        time.sleep(0.1)
                else:
                    raise RuntimeError("test server did not become ready")
                subprocess.run(
                    ["node", "node_modules/@playwright/test/cli.js", "test"],
                    cwd=root / "apps/catalog-web/frontend",
                    env=environment,
                    check=True,
                )
            finally:
                server.terminate()
                server.wait(timeout=15)
                if server.returncode not in {0, -15}:
                    log.seek(0)
                    print(log.read()[-16000:])


if __name__ == "__main__":
    main()
