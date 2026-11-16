from __future__ import annotations

import json
import re
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, cast


@dataclass(frozen=True)
class SearchFilters:
    query: str = ""
    category: str = ""
    region: str = "us"
    availability: str = ""
    asset_kind: str = ""
    minimum_price: Decimal | None = None
    maximum_price: Decimal | None = None
    lifecycle: str = "active"
    view: str = "grid"
    page: int = 1
    page_size: int = 24


@contextmanager
def connect_catalog(path: Path) -> Iterator[sqlite3.Connection]:
    if not path.is_file():
        raise FileNotFoundError(f"catalog database not found: {path}")
    connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        yield connection
    finally:
        connection.close()


def _fts_query(value: str) -> str:
    tokens = [token.replace('"', '""') for token in value.split() if token]
    return " AND ".join(f'"{token}"*' for token in tokens)


def search_products(path: Path, filters: SearchFilters) -> tuple[list[dict[str, Any]], int]:
    if filters.region == "global":
        offer_join = """LEFT JOIN offers o ON o.rowid = (
            SELECT candidate.rowid FROM offers candidate
            WHERE candidate.product_id = p.id
            ORDER BY candidate.listed DESC, (candidate.region='us') DESC,
                     candidate.rowid LIMIT 1
        )"""
        parameters: list[object] = []
        where: list[str] = []
    else:
        offer_join = "LEFT JOIN offers o ON o.product_id = p.id AND o.region = ?"
        parameters = [filters.region]
        where = ["o.product_id IS NOT NULL"]
    joins = [offer_join, "LEFT JOIN category_assignments c ON c.product_id = p.id"]
    if filters.query.strip():
        joins.append("JOIN product_search f ON f.product_id = p.id")
        where.append("f.product_search MATCH ?")
        parameters.append(_fts_query(filters.query))
    if filters.category:
        where.append("c.category_id = ?")
        parameters.append(filters.category)
    if filters.availability == "available":
        where.append("o.available = 1 AND o.listed = 1")
    elif filters.availability == "unavailable":
        where.append("(o.available = 0 OR o.listed = 0)")
    if filters.asset_kind:
        where.append("EXISTS (SELECT 1 FROM assets ak WHERE ak.product_id=p.id AND ak.kind=?)")
        parameters.append(filters.asset_kind)
    if filters.minimum_price is not None:
        where.append("CAST(o.price AS REAL) >= ?")
        parameters.append(str(filters.minimum_price))
    if filters.maximum_price is not None:
        where.append("CAST(o.price AS REAL) <= ?")
        parameters.append(str(filters.maximum_price))
    if filters.lifecycle == "active":
        where.append("p.active = 1")
    elif filters.lifecycle == "inactive":
        where.append("p.active = 0")
    predicate = f"WHERE {' AND '.join(where)}" if where else ""
    from_clause = f"FROM products p {' '.join(joins)} {predicate}"
    with connect_catalog(path) as connection:
        total = int(
            connection.execute(
                f"SELECT COUNT(DISTINCT p.id) {from_clause}",  # noqa: S608
                parameters,
            ).fetchone()[0]
        )
        rows = connection.execute(
            f"""SELECT DISTINCT p.id, p.name, p.description_text, p.categories_json, p.tags_json,
                       p.active, o.price, o.currency, o.available,
                       (SELECT COALESCE(
                          (SELECT display.id FROM assets display
                           WHERE display.product_id=p.id AND display.parent_asset_id=source.id
                           AND display.image_processing_json IS NOT NULL
                           AND display.blob_path IS NOT NULL ORDER BY display.id LIMIT 1),
                          source.id)
                        FROM assets source WHERE source.product_id=p.id
                        AND source.kind='image' AND source.parent_asset_id IS NULL
                        AND source.blob_path IS NOT NULL ORDER BY source.id LIMIT 1) image_id
                {from_clause} ORDER BY p.name COLLATE NOCASE LIMIT ? OFFSET ?""",  # noqa: S608
            [*parameters, filters.page_size, (filters.page - 1) * filters.page_size],
        ).fetchall()
    products = [dict(row) for row in rows]
    for product in products:
        product["categories"] = json.loads(product["categories_json"])
        product["tags"] = json.loads(product["tags_json"])
    return products, total


def categories(path: Path, region: str = "global") -> list[dict[str, Any]]:
    with connect_catalog(path) as connection:
        if region == "global":
            rows = connection.execute(
                """SELECT category_id id, label, COUNT(DISTINCT product_id) count
                   FROM category_assignments GROUP BY category_id, label ORDER BY label"""
            ).fetchall()
        else:
            rows = connection.execute(
                """SELECT category.category_id id, category.label,
                          COUNT(DISTINCT category.product_id) count
                   FROM category_assignments category
                   JOIN offers offer ON offer.product_id=category.product_id
                   AND offer.region=?
                   GROUP BY category.category_id, category.label ORDER BY category.label""",
                (region,),
            ).fetchall()
    return [dict(row) for row in rows]


def existing_product_ids(path: Path, product_ids: list[str]) -> set[str]:
    """Return catalog IDs from a bounded, caller-validated selection."""
    if not product_ids:
        return set()
    placeholders = ",".join("?" for _ in product_ids)
    with connect_catalog(path) as connection:
        rows = connection.execute(
            f"SELECT id FROM products WHERE id IN ({placeholders})",  # noqa: S608
            product_ids,
        ).fetchall()
    return {str(row["id"]) for row in rows}


def _variant_display_title(product_name: str, title: str) -> str:
    prefix = re.compile(rf"^\s*{re.escape(product_name)}\s+-\s+", re.I)
    shortened = prefix.sub("", title, count=1).strip()
    return shortened or title


def _commerce_rows(product: dict[str, Any]) -> list[dict[str, Any]]:
    offers = {str(offer["region"]): offer for offer in product["offers"]}
    variants_by_region: dict[str, list[dict[str, Any]]] = {}
    for variant in product["variants"]:
        variants_by_region.setdefault(str(variant["region"]), []).append(variant)

    rows: list[dict[str, Any]] = []
    regions = list(offers)
    regions.extend(region for region in variants_by_region if region not in offers)
    for region in regions:
        offer = offers.get(region)
        variants = variants_by_region.get(region, [])
        if not variants:
            rows.append(
                {
                    "region": region,
                    "title": "Default offer",
                    "display_title": "Default offer",
                    "variant_id": None,
                    "sku": None,
                    "part_number": None,
                    "price": offer["price"] if offer else None,
                    "compare_at_price": offer["compare_at_price"] if offer else None,
                    "currency": offer["currency"] if offer else None,
                    "available": offer["available"] if offer else None,
                    "retrieved_at": offer["retrieved_at"] if offer else None,
                    "url": offer["url"] if offer else None,
                }
            )
            continue
        for variant in variants:
            rows.append(
                {
                    **variant,
                    "display_title": variant["display_title"],
                    "price": variant["price"] or (offer["price"] if offer else None),
                    "compare_at_price": variant["compare_at_price"]
                    or (offer["compare_at_price"] if offer else None),
                    "currency": variant["currency"] or (offer["currency"] if offer else None),
                    "available": (
                        variant["available"]
                        if variant["available"] is not None
                        else (offer["available"] if offer else None)
                    ),
                    "retrieved_at": offer["retrieved_at"] if offer else None,
                    "url": variant["url"] or (offer["url"] if offer else None),
                }
            )
    return rows


def _asset_groups(product: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    variants: dict[str, dict[str, Any]] = {}
    for variant in product["variants"]:
        part_number = variant["part_number"]
        if part_number and part_number not in variants:
            variants[part_number] = {
                "part_number": part_number,
                "title": variant["display_title"],
                "assets": [],
            }

    shared: list[dict[str, Any]] = []
    for asset in product["assets"]:
        if asset["kind"] == "image":
            continue
        evidence = " ".join(
            filter(
                None,
                [asset["original_filename"], asset["archive_member_path"]],
            )
        )
        matches = [
            part_number
            for part_number in variants
            if re.search(
                rf"(?<![A-Z0-9]){re.escape(part_number)}(?![A-Z0-9])",
                evidence,
                re.I,
            )
        ]
        if len(matches) == 1:
            variants[matches[0]]["assets"].append(asset)
        else:
            shared.append(asset)
    return [group for group in variants.values() if group["assets"]], shared


def _attach_image_variant_info(
    images: list[dict[str, Any]],
    variants: list[dict[str, Any]],
    source_variants: list[dict[str, Any]],
) -> None:
    variants_by_image: dict[str, list[dict[str, Any]]] = {}
    for variant in variants:
        image_url = variant.get("image_url")
        if image_url:
            variants_by_image.setdefault(str(image_url), []).append(variant)

    for image in images:
        matches = variants_by_image.get(str(image["source_url"]), [])
        if not matches:
            # Regional CDN URLs can differ for the same official part. The canonical
            # image's exact source URL establishes its part before selecting local SKUs.
            source_parts = {
                variant["part_number"]
                for variant in source_variants
                if variant.get("image_url") == image["source_url"]
                and variant.get("part_number")
            }
            matches = [v for v in variants if v.get("part_number") in source_parts]
        titles = list(dict.fromkeys(str(item["display_title"]) for item in matches))
        part_numbers = list(
            dict.fromkeys(
                str(item["part_number"]) for item in matches if item["part_number"]
            )
        )
        skus = list(
            dict.fromkeys(
                f"{str(item['region']).upper()} · {item['sku']}"
                for item in matches
                if item["sku"]
            )
        )
        image["variant_title"] = (
            titles[0]
            if len(titles) == 1
            else f"Shared by {len(titles)} variants"
            if titles
            else "Product overview image"
        )
        image["variant_part_number"] = ", ".join(part_numbers) or "Not variant-specific"
        image["variant_skus"] = " · ".join(skus) or "Not variant-specific"


def product_detail(
    path: Path, product_id: str, region: str = "global"
) -> dict[str, Any] | None:
    with connect_catalog(path) as connection:
        row = connection.execute("SELECT * FROM products WHERE id = ?", (product_id,)).fetchone()
        if row is None:
            return None
        product = dict(row)
        product["description_blocks"] = json.loads(product.pop("description_blocks_json"))
        product["categories"] = json.loads(product.pop("categories_json"))
        product["tags"] = json.loads(product.pop("tags_json"))
        product["part_numbers"] = json.loads(product.pop("part_numbers_json"))
        product["skus"] = json.loads(product.pop("skus_json"))
        for table in (
            "offers",
            "variants",
            "assets",
            "specifications",
            "measurements",
            "related_links",
            "source_tables",
        ):
            rows = connection.execute(
                f"SELECT * FROM {table} WHERE product_id = ? ORDER BY rowid",  # noqa: S608
                (product_id,),
            ).fetchall()
            product[table] = [dict(item) for item in rows]
        for commerce_item in [*product["offers"], *product["variants"]]:
            if commerce_item["available"] is not None:
                commerce_item["available"] = bool(commerce_item["available"])
        for variant in product["variants"]:
            variant["display_title"] = _variant_display_title(
                str(product["name"]), str(variant["title"])
            )
        source_variants = product["variants"]
        if region != "global":
            product["offers"] = [
                offer for offer in product["offers"] if offer["region"] == region
            ]
            product["variants"] = [
                variant for variant in product["variants"] if variant["region"] == region
            ]
        product["selected_region"] = region
        box_rows = connection.execute(
            """SELECT box.*, linked.name linked_product_name,
                      COALESCE(
                        box.source_url,
                        (SELECT offer.url FROM offers offer
                         WHERE offer.product_id=box.linked_product_id AND offer.listed=1
                         ORDER BY (offer.region='us') DESC, offer.rowid LIMIT 1)
                      ) external_url
               FROM box_contents box
               LEFT JOIN products linked ON linked.id=box.linked_product_id
               WHERE box.product_id=? ORDER BY box.position""",
            (product_id,),
        ).fetchall()
        product["box_contents"] = [dict(item) for item in box_rows]
        product["box_quantity_labels"] = []
        for item in product["box_contents"]:
            quantities = json.loads(item.pop("variant_quantities_json"))
            item["variant_quantities"] = quantities
            item["quantity_by_variant"] = {
                quantity["variant"]: quantity["quantity"] for quantity in quantities
            }
            for quantity in quantities:
                if quantity["variant"] not in product["box_quantity_labels"]:
                    product["box_quantity_labels"].append(quantity["variant"])
        product["commerce_rows"] = _commerce_rows(product)
        for asset in product["assets"]:
            processing = asset.pop("image_processing_json", None)
            asset["image_processing"] = json.loads(processing) if processing else None
        product["asset_groups"], product["shared_assets"] = _asset_groups(product)
        source_images = [
            asset
            for asset in product["assets"]
            if asset["kind"] == "image"
            and asset["parent_asset_id"] is None
            and asset["blob_path"] is not None
        ]
        display_by_parent = {
            asset["parent_asset_id"]: asset
            for asset in product["assets"]
            if asset["kind"] == "image"
            and asset["image_processing"] is not None
            and asset["blob_path"] is not None
        }
        product["images"] = [
            display_by_parent.get(source["id"], source) for source in source_images
        ]
        _attach_image_variant_info(product["images"], product["variants"], source_variants)
        for source_table in product["source_tables"]:
            source_table["headers"] = json.loads(source_table.pop("headers_json"))
            source_table["rows"] = json.loads(source_table.pop("rows_json"))
    return product


def asset_record(path: Path, product_id: str, asset_id: str) -> dict[str, Any] | None:
    with connect_catalog(path) as connection:
        row = connection.execute(
            "SELECT * FROM assets WHERE product_id = ? AND id = ?",
            (product_id, asset_id),
        ).fetchone()
    return None if row is None else dict(row)


def decimal_filter(value: str) -> Decimal | None:
    if not value:
        return None
    try:
        return Decimal(value)
    except InvalidOperation:
        return None


def catalog_version(path: Path) -> int:
    with connect_catalog(path) as connection:
        return cast(int, connection.execute("PRAGMA user_version").fetchone()[0])
