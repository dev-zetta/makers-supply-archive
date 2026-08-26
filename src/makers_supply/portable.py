from __future__ import annotations

import os
import shutil
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from makers_supply.assets import UnsafeAssetError, materialized_asset_path
from makers_supply.database import build_database
from makers_supply.storage import Catalog, atomic_write


@dataclass(frozen=True)
class PortableCatalog:
    database: Path
    assets: Path
    file_count: int


def build_portable_catalog(catalog: Catalog, output: Path) -> PortableCatalog:
    """Build a catalog whose database points at ordinary, named asset files."""
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    database = output / "catalog.sqlite"
    assets_root = output / "assets"
    build_database(catalog, database)

    updates: list[tuple[str, str, str]] = []
    file_count = 0
    for product in catalog.products():
        for asset in product.assets:
            if not asset.blob_path:
                continue
            source = (catalog.root / asset.blob_path).resolve()
            if not source.is_relative_to(catalog.root.resolve()) or not source.is_file():
                raise FileNotFoundError(f"asset source is unavailable: {asset.blob_path}")
            if asset.size is not None and source.stat().st_size != asset.size:
                raise ValueError(f"asset source has the wrong size: {asset.blob_path}")

            relative = Path("assets") / product.id / materialized_asset_path(asset)
            target = (output / relative).resolve()
            if not target.is_relative_to(output):
                raise UnsafeAssetError(f"portable asset path escapes output: {relative}")
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                raise FileExistsError(f"portable asset path collision: {relative}")
            shutil.copyfile(source, target)
            os.utime(target, (0, 0))
            file_count += 1
            updates.append((relative.as_posix(), product.id, asset.id))

    with sqlite3.connect(database) as connection, connection:
        connection.executemany(
            "UPDATE assets SET blob_path = ? WHERE product_id = ? AND id = ?", updates
        )

    atomic_write(
        assets_root / "README.txt",
        "Maker's Supply Catalog assets\n"
        "\n"
        "Files are grouped by catalog product ID. Source downloads retain their original "
        "filenames; extracted archive members retain their original archive paths.\n",
    )
    return PortableCatalog(database=database, assets=assets_root, file_count=file_count)
