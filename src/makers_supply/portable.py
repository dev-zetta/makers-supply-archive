from __future__ import annotations

import os
import re
import shutil
import sqlite3
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from makers_supply.assets import UnsafeAssetError
from makers_supply.database import build_database
from makers_supply.models import Asset, AssetKind
from makers_supply.storage import Catalog, atomic_write

_ASSET_FOLDERS = {
    AssetKind.IMAGE: "Images",
    AssetKind.MODEL: "Models",
    AssetKind.ARCHIVE: "Archives",
    AssetKind.DOCUMENT: "Documents",
    AssetKind.OTHER: "Other",
}
_WINDOWS_RESERVED_NAMES = {
    "AUX",
    "CON",
    "NUL",
    "PRN",
    *(f"COM{number}" for number in range(1, 10)),
    *(f"LPT{number}" for number in range(1, 10)),
}


@dataclass(frozen=True)
class PortableCatalog:
    database: Path
    assets: Path
    file_count: int


@dataclass(frozen=True)
class PortableFile:
    source: Path
    relative: Path
    product_id: str
    asset: Asset


def portable_files(catalog: Catalog) -> list[PortableFile]:
    files = []
    for product in catalog.products():
        paths = _portable_asset_paths(product.assets)
        for asset in product.assets:
            if not asset.blob_path:
                continue
            source = (catalog.root / asset.blob_path).resolve()
            if not source.is_relative_to(catalog.root.resolve()) or not source.is_file():
                raise FileNotFoundError(f"asset source is unavailable: {asset.blob_path}")
            if asset.size is not None and source.stat().st_size != asset.size:
                raise ValueError(f"asset source has the wrong size: {asset.blob_path}")
            relative = Path("assets") / product.id / paths[asset.id]
            if relative.is_absolute() or ".." in relative.parts:
                raise UnsafeAssetError(f"portable asset path escapes output: {relative}")
            files.append(PortableFile(source, relative, product.id, asset))
    return sorted(files, key=lambda item: item.relative.as_posix())


def build_portable_database(catalog: Catalog, database: Path, files: list[PortableFile]) -> None:
    build_database(catalog, database)
    with sqlite3.connect(database) as connection, connection:
        connection.executemany(
            "UPDATE assets SET blob_path = ? WHERE product_id = ? AND id = ?",
            [(item.relative.as_posix(), item.product_id, item.asset.id) for item in files],
        )


def _safe_folder_name(value: str) -> str:
    value = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", value).strip(" .")
    value = value[:80].rstrip(" .") or "Related file"
    if value.upper() in _WINDOWS_RESERVED_NAMES:
        value = f"{value}_"
    return value


def _collision_context(asset: Asset, assets_by_id: dict[str, Asset]) -> str:
    if asset.parent_asset_id:
        parent = assets_by_id.get(asset.parent_asset_id)
        if parent:
            return _safe_folder_name(Path(parent.original_filename).stem)
    if asset.image_processing:
        return "Processed image"
    return "Source file"


def _portable_asset_paths(assets: list[Asset]) -> dict[str, Path]:
    """Return shallow, human-readable paths for assets that have local files."""
    assets_by_id = {asset.id: asset for asset in assets}
    groups: dict[str, list[Asset]] = defaultdict(list)
    base_paths: dict[str, Path] = {}
    for asset in assets:
        if not asset.blob_path:
            continue
        base = Path(_ASSET_FOLDERS[asset.kind]) / asset.original_filename
        base_paths[asset.id] = base
        groups[base.as_posix().casefold()].append(asset)

    paths: dict[str, Path] = {}
    used: set[str] = set()
    for group in groups.values():
        if len(group) == 1:
            asset = group[0]
            relative = base_paths[asset.id]
            paths[asset.id] = relative
            used.add(relative.as_posix().casefold())
            continue

        for asset in sorted(group, key=lambda item: item.id):
            category = _ASSET_FOLDERS[asset.kind]
            context = _collision_context(asset, assets_by_id)
            suffix = 1
            while True:
                folder = context if suffix == 1 else f"{context} ({suffix})"
                relative = Path(category) / folder / asset.original_filename
                normalized = relative.as_posix().casefold()
                if normalized not in used:
                    break
                suffix += 1
            paths[asset.id] = relative
            used.add(normalized)
    return paths


def build_portable_catalog(catalog: Catalog, output: Path) -> PortableCatalog:
    """Build a catalog whose database points at ordinary, named asset files."""
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    database = output / "catalog.sqlite"
    assets_root = output / "assets"
    files = portable_files(catalog)
    build_portable_database(catalog, database, files)

    file_count = 0
    for item in files:
        target = (output / item.relative).resolve()
        if not target.is_relative_to(output):
            raise UnsafeAssetError(f"portable asset path escapes output: {item.relative}")
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            raise FileExistsError(f"portable asset path collision: {item.relative}")
        shutil.copyfile(item.source, target)
        os.utime(target, (0, 0))
        file_count += 1

    atomic_write(
        assets_root / "README.txt",
        "Maker's Supply Catalog assets\n"
        "\n"
        "Files are grouped by catalog product ID, then by Images, Models, Archives, "
        "Documents, or Other. Every file retains its original filename. When original "
        "filenames collide, a short folder named after the related source file keeps them "
        "distinct.\n",
    )
    return PortableCatalog(database=database, assets=assets_root, file_count=file_count)
