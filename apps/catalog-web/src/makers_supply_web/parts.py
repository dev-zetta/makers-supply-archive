from __future__ import annotations

import csv
import io
import json
import sqlite3
from collections import defaultdict
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from makers_supply_web.builds import build_view
from makers_supply_web.catalog import connect_catalog
from makers_supply_web.state import connect

EXPECTED_CURRENCIES = {
    "us": "USD", "eu": "EUR", "uk": "GBP", "ca": "CAD",
    "au": "AUD", "jp": "JPY", "kr": "KRW", "asia": "USD",
}


def accessible_lists(
    state_db: Path, user_id: str, *, is_admin: bool = False
) -> list[dict[str, Any]]:
    with connect(state_db) as connection:
        if is_admin:
            rows = connection.execute(
                """SELECT l.*, CASE WHEN l.owner_id=? THEN 'owner' ELSE 'admin' END role,
                          COUNT(i.id) item_count FROM lists l
                   LEFT JOIN list_items i ON i.list_id=l.id GROUP BY l.id
                   ORDER BY l.updated_at DESC""",
                (user_id,),
            ).fetchall()
        else:
            rows = connection.execute(
            """SELECT l.*, CASE WHEN l.owner_id=? THEN 'owner' ELSE acl.role END role,
                      COUNT(i.id) item_count
               FROM lists l LEFT JOIN list_acl acl ON acl.list_id=l.id AND acl.user_id=?
               LEFT JOIN list_items i ON i.list_id=l.id
               WHERE l.owner_id=? OR acl.user_id=?
               GROUP BY l.id ORDER BY l.updated_at DESC""",
            (user_id, user_id, user_id, user_id),
        ).fetchall()
    return [dict(row) for row in rows]


def list_access(
    state_db: Path, list_id: str, user_id: str, *, is_admin: bool = False
) -> dict[str, Any] | None:
    with connect(state_db) as connection:
        if is_admin:
            row = connection.execute(
                """SELECT l.*, CASE WHEN l.owner_id=? THEN 'owner' ELSE 'admin' END role
                   FROM lists l WHERE l.id=?""",
                (user_id, list_id),
            ).fetchone()
        else:
            row = connection.execute(
            """SELECT l.*, CASE WHEN l.owner_id=? THEN 'owner' ELSE acl.role END role
               FROM lists l LEFT JOIN list_acl acl ON acl.list_id=l.id AND acl.user_id=?
               WHERE l.id=? AND (l.owner_id=? OR acl.user_id=?)""",
            (user_id, user_id, list_id, user_id, user_id),
        ).fetchone()
    return None if row is None else dict(row)


def current_price(
    catalog_db: Path, product_id: str, region: str, variant_id: str | None,
) -> tuple[str | None, str | None, bool | None]:
    with connect_catalog(catalog_db) as connection:
        offer = connection.execute(
            """SELECT price, currency, available, listed FROM offers
               WHERE product_id=? AND region=?""",
            (product_id, region),
        ).fetchone()
        if offer is None:
            return None, None, None
        if not offer["listed"]:
            return None, None, False
        if variant_id:
            variant = connection.execute(
                """SELECT price, currency, available FROM variants
                   WHERE product_id=? AND region=? AND variant_id=?""",
                (product_id, region, variant_id),
            ).fetchone()
            if variant and variant["price"]:
                return _trusted_price(variant, region)
    return _trusted_price(offer, region)


def _trusted_price(row: sqlite3.Row, region: str) -> tuple[str | None, str | None, bool | None]:
    currency = str(row["currency"]) if row["currency"] else None
    # Existing snapshots may predate per-region page isolation. Never total a price carrying
    # another storefront's currency; a fresh complete sync will make it available.
    if currency != EXPECTED_CURRENCIES[region]:
        return None, currency, None
    return (
        None if row["price"] is None else str(row["price"]),
        currency,
        None if row["available"] is None else bool(row["available"]),
    )


def list_view(
    state_db: Path, catalog_db: Path, list_id: str, user_id: str, *, is_admin: bool = False,
) -> dict[str, Any] | None:
    selected_list = list_access(state_db, list_id, user_id, is_admin=is_admin)
    if selected_list is None:
        return None
    with connect(state_db) as connection:
        state_items = connection.execute(
            """SELECT i.*, COALESCE(p.completed_quantity, 0) completed_quantity,
                      p.updated_at progress_updated_at
               FROM list_items i LEFT JOIN list_item_progress p ON p.item_id=i.id
               WHERE i.list_id=? ORDER BY i.created_at, i.id""", (list_id,)
        ).fetchall()
        selected_list["build"] = build_view(
            connection, list_id, [dict(item) for item in state_items]
        )
        shares = connection.execute(
            """SELECT u.username, acl.role, u.id user_id FROM list_acl acl
               JOIN users u ON u.id=acl.user_id WHERE acl.list_id=? ORDER BY u.username""",
            (list_id,),
        ).fetchall()
    current_totals: defaultdict[str, Decimal] = defaultdict(Decimal)
    captured_totals: defaultdict[str, Decimal] = defaultdict(Decimal)
    unknown_count = 0
    unavailable_count = 0
    items: list[dict[str, Any]] = []
    with connect_catalog(catalog_db) as connection:
        for state_item in state_items:
            product = connection.execute(
                """SELECT p.name,
                   (SELECT COALESCE(
                      (SELECT display.id FROM assets display
                       WHERE display.product_id=p.id AND display.parent_asset_id=source.id
                       AND display.image_processing_json IS NOT NULL
                       AND display.blob_path IS NOT NULL ORDER BY display.id LIMIT 1),
                      source.id)
                    FROM assets source WHERE source.product_id=p.id
                    AND source.kind='image' AND source.parent_asset_id IS NULL
                    AND source.blob_path IS NOT NULL ORDER BY source.id LIMIT 1) image_id
                   FROM products p WHERE p.id=?""",
                (state_item["product_id"],),
            ).fetchone()
            if product is None:
                name, image_id = f"Missing product: {state_item['product_id']}", None
            else:
                name, image_id = str(product["name"]), product["image_id"]
            price, currency, available = current_price(
                catalog_db, str(state_item["product_id"]), str(selected_list["region"]),
                state_item["variant_id"],
            )
            quantity = int(state_item["quantity"])
            current_line = None if available is False else _multiply(price, quantity)
            captured_line = _multiply(state_item["captured_price"], quantity)
            if current_line is not None and currency:
                current_totals[currency] += current_line
            elif available is not False:
                unknown_count += 1
            if available is False:
                unavailable_count += 1
            if captured_line is not None and state_item["captured_currency"]:
                captured_totals[str(state_item["captured_currency"])] += captured_line
            item = dict(state_item)
            item.update({
                "name": name, "image_id": image_id, "current_price": price,
                "current_currency": currency, "current_available": available,
                "current_line": _decimal_text(current_line),
                "captured_line": _decimal_text(captured_line),
                "price_changed": bool(
                    price and state_item["captured_price"] and
                    (price != state_item["captured_price"] or
                     currency != state_item["captured_currency"])
                ),
            })
            items.append(item)
    selected_list["items"] = items
    selected_list["shares"] = [dict(row) for row in shares]
    selected_list["current_totals"] = {
        key: _decimal_text(value) for key, value in current_totals.items()
    }
    selected_list["captured_totals"] = {
        key: _decimal_text(value) for key, value in captured_totals.items()
    }
    selected_list["unknown_count"] = unknown_count
    selected_list["unavailable_count"] = unavailable_count
    return selected_list


def _multiply(value: object, quantity: int) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value)) * quantity
    except InvalidOperation:
        return None


def _decimal_text(value: Decimal | None) -> str | None:
    if value is None:
        return None
    return format(value.quantize(Decimal("0.01")), "f")


def export_list(selected_list: dict[str, Any], output_format: str) -> tuple[str, str]:
    if output_format == "json":
        content = json.dumps(selected_list, ensure_ascii=False, indent=2, default=str)
        return content, "application/json"
    if output_format != "csv":
        raise ValueError("format must be csv or json")
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "product_id", "name", "variant_id", "quantity", "notes", "region",
        "captured_price", "captured_currency", "current_price", "current_currency",
    ])
    for item in selected_list["items"]:
        writer.writerow([
            item["product_id"], item["name"], item["variant_id"], item["quantity"],
            item["notes"], selected_list["region"], item["captured_price"],
            item["captured_currency"], item["current_price"], item["current_currency"],
        ])
    return output.getvalue(), "text/csv"
