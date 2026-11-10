from __future__ import annotations

import argparse
import os
import secrets
import sys
from contextlib import suppress
from pathlib import Path

import uvicorn

from makers_supply.release import verify_installed_catalog
from makers_supply_web.app import create_app
from makers_supply_web.config import Settings


def application_directory() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path.cwd().resolve()


def state_directory() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state"))
    return base / "makers-supply-catalog"


def local_secret(directory: Path) -> str:
    path = directory / "secret"
    if path.is_file():
        return path.read_text("ascii").strip()
    directory.mkdir(parents=True, exist_ok=True)
    value = secrets.token_hex(32)
    path.write_text(value + "\n", encoding="ascii")
    with suppress(OSError):
        path.chmod(0o600)
    return value


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the desktop catalog service")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--data-dir", type=Path, default=application_directory())
    parser.add_argument("--state-dir", type=Path, default=state_directory())
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("--port must be between 1 and 65535")

    data_dir = args.data_dir.resolve()
    database = data_dir / "catalog.sqlite"
    assets = data_dir / "assets"
    if not database.is_file() or not assets.is_dir():
        parser.error(f"catalog.sqlite and assets/ were not found beside the app: {data_dir}")
    try:
        verify_installed_catalog(data_dir)
    except ValueError as error:
        parser.error(str(error))

    state = args.state_dir.resolve()
    settings = Settings(
        root=data_dir,
        catalog_db=database,
        state_db=state / "state.sqlite",
        secret_key=local_secret(state),
        secure_cookies=False,
        local_mode=True,
    )
    url = f"http://127.0.0.1:{args.port}"
    print(f"Maker's Supply Catalog is running at {url}")
    uvicorn.run(
        create_app(settings),
        host="127.0.0.1",
        port=args.port,
        loop="asyncio",
        http="h11",
        log_level="warning",
    )


if __name__ == "__main__":
    main()
