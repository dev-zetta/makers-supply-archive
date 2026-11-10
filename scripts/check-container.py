#!/usr/bin/env python3
"""Build the deployment image and verify login, lists, and an online backup/restore."""

from __future__ import annotations

import os
import re
import subprocess
import tempfile
import time
from contextlib import closing
from pathlib import Path
from uuid import uuid4

import httpx


def docker(*args: str, **kwargs: object) -> str:
    result = subprocess.run(
        ["docker", *args], check=True, text=True, stdout=subprocess.PIPE, **kwargs
    )
    return result.stdout.strip()


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    suffix = uuid4().hex[:12]
    image, volume, container = (f"makers-supply-check-{suffix}" for _ in range(3))
    image += ":local"
    environment = [
        "-e",
        "MAKERS_SUPPLY_ROOT=/archive",
        "-e",
        "MAKERS_SUPPLY_CATALOG_DB=/archive/dist/makers-supply.sqlite",
        "-e",
        "MAKERS_SUPPLY_STATE_DB=/state/catalog-web.sqlite",
        "-e",
        "MAKERS_SUPPLY_SECRET_KEY=isolated-container-check-secret",
        "-e",
        "MAKERS_SUPPLY_SECURE_COOKIES=0",
    ]
    mounts = ["-v", f"{root}:/archive:ro", "-v", f"{volume}:/state"]
    docker("build", "-t", image, "-f", "apps/catalog-web/Dockerfile", str(root))
    docker("volume", "create", volume)
    try:
        docker(
            "run",
            "--rm",
            "-i",
            *environment,
            *mounts,
            image,
            "makers-supply-web",
            "create-admin",
            "check-admin",
            "--password-stdin",
            input="isolated test password\n",
        )

        def start() -> str:
            docker(
                "run",
                "-d",
                "--name",
                container,
                "--read-only",
                "--tmpfs",
                "/tmp",
                "-p",
                "127.0.0.1::8000",
                *environment,
                *mounts,
                image,
            )
            address = docker("port", container, "8000/tcp").splitlines()[0]
            url = "http://" + address
            for _ in range(100):
                try:
                    if httpx.get(url + "/healthz", timeout=1).status_code == 200:
                        return url
                except httpx.HTTPError:
                    pass
                time.sleep(0.2)
            raise RuntimeError("container did not become healthy")

        def login(url: str) -> httpx.Client:
            client = httpx.Client(base_url=url, follow_redirects=True, timeout=15)
            response = client.post(
                "/login", data={"username": "check-admin", "password": "isolated test password"}
            )
            if response.status_code != 200 or "Hardware catalog" not in response.text:
                raise RuntimeError("container login failed")
            return client

        url = start()
        with closing(login(url)) as client:
            page = client.get("/lists")
            match = re.search(r'name="csrf" value="([^"]+)"', page.text)
            if match is None:
                raise RuntimeError("missing CSRF token")
            result = client.post(
                "/lists", data={"csrf": match.group(1), "name": "Backup Ž 🔩", "region": "eu"}
            )
            result.raise_for_status()
            if "Backup Ž 🔩" not in result.text:
                raise RuntimeError("container list creation failed")
        docker(
            "exec",
            container,
            "python",
            "-c",
            "import sqlite3; s=sqlite3.connect('/state/catalog-web.sqlite'); "
            "d=sqlite3.connect('/state/backup.sqlite'); s.backup(d); d.close(); s.close()",
        )
        with tempfile.TemporaryDirectory(prefix="catalog-backup-") as temporary:
            docker("cp", f"{container}:/state/backup.sqlite", temporary + "/backup.sqlite")
            if not (Path(temporary) / "backup.sqlite").is_file():
                raise RuntimeError("online backup was not created")
        docker("rm", "-f", container)
        docker(
            "run",
            "--rm",
            *mounts,
            image,
            "python",
            "-c",
            "import os,shutil; os.replace('/state/catalog-web.sqlite', '/state/previous.sqlite'); "
            "[os.unlink('/state/catalog-web.sqlite'+s) for s in ('-wal','-shm') "
            "if os.path.exists('/state/catalog-web.sqlite'+s)]; "
            "shutil.copyfile('/state/backup.sqlite', '/state/catalog-web.sqlite')",
        )
        with closing(login(start())) as client:
            if "Backup Ž 🔩" not in client.get("/lists").text:
                raise RuntimeError("restored list is missing")
        print("container startup, login, list creation, online backup and restore passed")
    finally:
        subprocess.run(
            ["docker", "rm", "-f", container], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        subprocess.run(["docker", "volume", "rm", volume], stdout=subprocess.DEVNULL)
        if not os.environ.get("MAKERS_SUPPLY_KEEP_TEST_IMAGE"):
            subprocess.run(["docker", "image", "rm", image], stdout=subprocess.DEVNULL)


if __name__ == "__main__":
    main()
