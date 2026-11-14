#!/usr/bin/env python3
"""Query local Maker's Supply data and export verified CAD reference files."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path
from typing import Any

LFS_HEADER = b"version https://git-lfs.github.com/spec/v1"
REGIONS = ("us", "eu", "uk", "ca", "au", "jp", "kr", "asia")


class CatalogError(ValueError):
    """A local catalog operation could not be completed."""


def _provenance(row: dict[str, Any]) -> dict[str, Any]:
    row["provenance"] = {
        "kind": row.pop("provenance_kind"),
        "reference": row.pop("provenance_reference"),
        "source_url": row.pop("source_url"),
    }
    return row


def _sqlite_products(path: Path) -> list[dict[str, Any]]:
    connection = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA query_only=ON")
        products = []
        for raw in connection.execute("SELECT * FROM products ORDER BY id"):
            product = dict(raw)
            for key in list(product):
                if key.endswith("_json"):
                    product[key[:-5]] = json.loads(product.pop(key))
            product["active"] = bool(product["active"])
            for table in (
                "assets",
                "offers",
                "variants",
                "measurements",
                "source_tables",
                "box_contents",
                "related_links",
                "category_assignments",
                "aliases",
                "specifications",
            ):
                rows = []
                for result in connection.execute(
                    f"SELECT * FROM {table} WHERE product_id=? ORDER BY rowid",  # noqa: S608
                    (product["id"],),
                ):
                    row = dict(result)
                    row.pop("product_id")
                    row.pop("position", None)
                    for key in list(row):
                        if key.endswith("_json"):
                            value = row.pop(key)
                            row[key[:-5]] = json.loads(value) if value else None
                    if "provenance_kind" in row:
                        _provenance(row)
                    for key in ("available", "listed"):
                        if row.get(key) is not None:
                            row[key] = bool(row[key])
                    if table == "category_assignments":
                        row["id"] = row.pop("category_id")
                    elif table == "aliases":
                        row["product_id"] = row.pop("source_product_id")
                    rows.append(row)
                product[table] = rows
            product["specifications"] = {
                row["name"]: row["value"] for row in product["specifications"]
            }
            products.append(product)
        return products
    finally:
        connection.close()


def load_catalog(path: Path) -> tuple[Path, list[dict[str, Any]]]:
    """Return the asset root and products without modifying any catalog files."""
    path = path.expanduser().resolve()
    if path.is_dir():
        if (path / "data" / "products").is_dir():
            root, products_dir = path, path / "data" / "products"
        elif path.name == "products" and path.parent.name == "data":
            root, products_dir = path.parent.parent, path
        elif (path / "catalog.sqlite").is_file():
            database = path / "catalog.sqlite"
            return path, _sqlite_products(database)
        else:
            raise CatalogError(
                "Expected a checkout with data/products/ or a portable catalog.sqlite"
            )
        products = [
            json.loads(file.read_text("utf-8")) for file in sorted(products_dir.glob("*.json"))
        ]
        if any(
            not isinstance(product, dict)
            or not isinstance(product.get("id"), str)
            or not isinstance(product.get("name"), str)
            for product in products
        ):
            raise CatalogError("Product JSON must contain an object with string id and name fields")
        return root, products
    if path.is_file():
        return path.parent, _sqlite_products(path)
    raise CatalogError(f"Catalog was not found: {path}")


def _asset_path(root: Path, asset: dict[str, Any]) -> Path | None:
    raw = asset.get("blob_path")
    if not raw:
        return None
    # Both POSIX traversal and Windows path spellings are rejected on every host.
    if not isinstance(raw, str) or "\\" in raw or re.match(r"^[A-Za-z]:", raw):
        raise CatalogError("Unsafe asset path")
    relative = Path(raw)
    path = (root / relative).resolve()
    if relative.is_absolute() or ".." in relative.parts or not path.is_relative_to(root):
        raise CatalogError("Unsafe asset path")
    return path


def inspect_asset(root: Path, asset: dict[str, Any]) -> dict[str, Any]:
    result = dict(asset)
    result.update(availability="missing", local_path=None)
    if asset.get("rejection_reason"):
        result["availability"] = "rejected"
        return result
    try:
        path = _asset_path(root, asset)
    except CatalogError:
        result["availability"] = "unsafe_path"
        return result
    if path is not None and path.is_file():
        with path.open("rb") as stream:
            pointer = stream.read(len(LFS_HEADER)).startswith(LFS_HEADER)
        result.update(availability="lfs_pointer" if pointer else "available", local_path=str(path))
    return result


def _search_text(product: dict[str, Any]) -> str:
    fields = (
        "id",
        "name",
        "description_text",
        "part_numbers",
        "skus",
        "categories",
        "tags",
        "specifications",
        "measurements",
        "variants",
        "box_contents",
    )
    return " ".join(
        json.dumps(product.get(key, ""), ensure_ascii=False) for key in fields
    ).casefold()


def search(
    products: list[dict[str, Any]], query: str, limit: int, region: str | None
) -> dict[str, Any]:
    terms = query.casefold().split()
    matches = []
    for product in products:
        if not product.get("active", True):
            continue
        offers = product.get("offers", [])
        variants = product.get("variants", [])
        if region:
            offers = [offer for offer in offers if offer["region"] == region]
            variants = [variant for variant in variants if variant["region"] == region]
            if not offers and not variants:
                continue
        text = _search_text(product)
        if all(term in text for term in terms):
            matches.append(
                {
                    "id": product["id"],
                    "name": product["name"],
                    "part_numbers": product.get("part_numbers", []),
                    "skus": product.get("skus", []),
                    "offers": offers,
                    "variants": variants,
                }
            )
    matches.sort(key=lambda item: (item["name"].casefold(), item["id"]))
    return {"items": matches[:limit], "total": len(matches), "limit": limit}


def show(root: Path, product: dict[str, Any]) -> dict[str, Any]:
    return {
        **product,
        "assets": [inspect_asset(root, asset) for asset in product.get("assets", [])],
    }


def _safe_segment(value: str) -> str:
    value = re.sub(r'[<>:"/\\|?*\x00-\x1f\x7f]', "_", value).strip(" .")
    value = value.encode("utf-8")[:180].decode("utf-8", errors="ignore").rstrip(" .") or "file"
    if value.split(".")[0].upper() in {
        "CON",
        "PRN",
        "AUX",
        "NUL",
        *(f"COM{i}" for i in range(1, 10)),
        *(f"LPT{i}" for i in range(1, 10)),
    }:
        value = "_" + value
    return value


def _write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def export_assets(
    root: Path,
    product: dict[str, Any],
    asset_ids: list[str],
    output: Path,
) -> dict[str, Any]:
    output = output.expanduser().absolute()
    if output.exists() or output.is_symlink():
        raise CatalogError(f"Output already exists: {output}")
    if not output.parent.is_dir():
        raise CatalogError(f"Output parent directory does not exist: {output.parent}")
    assets = {asset["id"]: asset for asset in product.get("assets", [])}
    selected = []
    for asset_id in dict.fromkeys(asset_ids):
        if asset_id not in assets:
            raise CatalogError(f"Unknown asset: {asset_id}")
        asset = assets[asset_id]
        status = inspect_asset(root, asset)
        if status["availability"] != "available":
            raise CatalogError(f"Asset {asset_id} is {status['availability']}")
        if not re.fullmatch(r"[0-9a-f]{64}", str(asset.get("sha256", ""))):
            raise CatalogError(f"Asset {asset_id} has no valid SHA-256 to verify")
        if not isinstance(asset.get("size"), int) or asset["size"] < 0:
            raise CatalogError(f"Asset {asset_id} has no valid size to verify")
        selected.append(asset)
    temporary = Path(tempfile.mkdtemp(prefix=f".{output.name}-", dir=output.parent))
    try:
        entries = []
        for index, asset in enumerate(selected, 1):
            relative = (
                Path("assets")
                / f"{index:03d}-{_safe_segment(asset['id'])}"
                / _safe_segment(asset["original_filename"])
            )
            destination = temporary / relative
            destination.parent.mkdir(parents=True)
            source = _asset_path(root, asset)
            if source is None:
                raise CatalogError(f"Asset {asset['id']} is missing")
            digest = hashlib.sha256()
            size = 0
            with source.open("rb") as incoming, destination.open("wb") as outgoing:
                if incoming.read(len(LFS_HEADER)).startswith(LFS_HEADER):
                    raise CatalogError(f"Asset {asset['id']} is lfs_pointer")
                incoming.seek(0)
                while chunk := incoming.read(1024 * 1024):
                    digest.update(chunk)
                    size += len(chunk)
                    outgoing.write(chunk)
            if digest.hexdigest() != asset["sha256"] or size != asset["size"]:
                raise CatalogError(f"Asset {asset['id']} failed SHA-256 or size verification")
            entries.append({**asset, "package_path": relative.as_posix(), "verified": True})
        manifest = {
            "format": "makers-supply-cad",
            "schema_version": 1,
            "product_id": product["id"],
            "assets": entries,
        }
        _write_json(temporary / "product.json", product)
        _write_json(temporary / "manifest.json", manifest)
        # Recheck immediately before promotion, including dangling symlinks.
        if output.exists() or output.is_symlink():
            raise CatalogError(f"Output already exists: {output}")
        temporary.rename(output)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)
    return {
        "output": str(output),
        "product_id": product["id"],
        "files": len(entries),
        "manifest": str(output / "manifest.json"),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--catalog", required=True, type=Path, help="Checkout or portable data path"
    )
    commands = parser.add_subparsers(dest="command", required=True)
    search_parser = commands.add_parser(
        "search", help="Search active products with literal AND terms"
    )
    search_parser.add_argument("query")
    search_parser.add_argument("--limit", type=int, default=10)
    search_parser.add_argument("--region", choices=REGIONS)
    show_parser = commands.add_parser("show", help="Show metadata and local file availability")
    show_parser.add_argument("product_id")
    export_parser = commands.add_parser(
        "export", help="Copy selected verified files to a new directory"
    )
    export_parser.add_argument("product_id")
    export_parser.add_argument("--asset-id", action="append", required=True)
    export_parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        root, products = load_catalog(args.catalog)
        if args.command == "search":
            if args.limit < 1:
                raise CatalogError("Limit must be at least 1")
            result = search(products, args.query, args.limit, args.region)
        else:
            product = next((item for item in products if item["id"] == args.product_id), None)
            if product is None:
                raise CatalogError(f"Product was not found: {args.product_id}")
            result = (
                show(root, product)
                if args.command == "show"
                else export_assets(
                    root,
                    product,
                    args.asset_id,
                    args.output,
                )
            )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (
        CatalogError,
        OSError,
        sqlite3.Error,
        json.JSONDecodeError,
        KeyError,
        TypeError,
    ) as error:
        print(f"catalog: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
