from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from makers_supply.models import Product
from makers_supply.storage import Catalog

SCHEMA = """
PRAGMA foreign_keys = ON;
CREATE TABLE products (
  id TEXT PRIMARY KEY, schema_version INTEGER NOT NULL, name TEXT NOT NULL,
  description_html TEXT NOT NULL, description_text TEXT NOT NULL,
  description_blocks_json TEXT NOT NULL,
  categories_json TEXT NOT NULL, tags_json TEXT NOT NULL,
  part_numbers_json TEXT NOT NULL, skus_json TEXT NOT NULL,
  first_seen TEXT NOT NULL, last_seen TEXT NOT NULL, active INTEGER NOT NULL, removed_at TEXT
);
CREATE TABLE category_assignments (
  product_id TEXT NOT NULL REFERENCES products(id), position INTEGER NOT NULL,
  category_id TEXT NOT NULL, label TEXT NOT NULL, path_json TEXT NOT NULL,
  provenance_kind TEXT NOT NULL, provenance_reference TEXT NOT NULL, source_url TEXT,
  PRIMARY KEY (product_id, position)
);
CREATE TABLE offers (
  product_id TEXT NOT NULL REFERENCES products(id), region TEXT NOT NULL, url TEXT NOT NULL,
  currency TEXT NOT NULL, price TEXT, compare_at_price TEXT, available INTEGER,
  listed INTEGER NOT NULL, missing_runs INTEGER NOT NULL, retrieved_at TEXT NOT NULL,
  PRIMARY KEY (product_id, region)
);
CREATE TABLE variants (
  product_id TEXT NOT NULL REFERENCES products(id), region TEXT NOT NULL,
  variant_id TEXT NOT NULL, title TEXT NOT NULL, sku TEXT, part_number TEXT,
  available INTEGER, price TEXT, compare_at_price TEXT, currency TEXT, url TEXT, image_url TEXT,
  PRIMARY KEY (product_id, region, variant_id)
);
CREATE TABLE assets (
  product_id TEXT NOT NULL REFERENCES products(id), id TEXT NOT NULL, kind TEXT NOT NULL,
  source_url TEXT NOT NULL, original_filename TEXT NOT NULL, media_type TEXT NOT NULL,
  declared_media_type TEXT, sha256 TEXT, size INTEGER, blob_path TEXT,
  rights_status TEXT NOT NULL, retrieved_at TEXT, rejection_reason TEXT,
  parent_asset_id TEXT, archive_member_path TEXT,
  image_processing_json TEXT,
  PRIMARY KEY (product_id, id)
);
CREATE TABLE specifications (
  product_id TEXT NOT NULL REFERENCES products(id), name TEXT NOT NULL, value TEXT NOT NULL,
  PRIMARY KEY (product_id, name)
);
CREATE TABLE measurements (
  product_id TEXT NOT NULL REFERENCES products(id), position INTEGER NOT NULL,
  label TEXT NOT NULL, raw_value TEXT NOT NULL, numeric_value TEXT, unit TEXT, applies_to TEXT,
  provenance_kind TEXT NOT NULL, provenance_reference TEXT NOT NULL, source_url TEXT,
  PRIMARY KEY (product_id, position)
);
CREATE TABLE source_tables (
  product_id TEXT NOT NULL REFERENCES products(id), position INTEGER NOT NULL,
  caption TEXT, headers_json TEXT NOT NULL, rows_json TEXT NOT NULL,
  provenance_kind TEXT NOT NULL, provenance_reference TEXT NOT NULL, source_url TEXT,
  PRIMARY KEY (product_id, position)
);
CREATE TABLE box_contents (
  product_id TEXT NOT NULL REFERENCES products(id), position INTEGER NOT NULL,
  item_number TEXT, name TEXT NOT NULL, quantity TEXT, variant_quantities_json TEXT NOT NULL,
  source_url TEXT,
  linked_product_id TEXT, PRIMARY KEY (product_id, position)
);
CREATE TABLE related_links (
  product_id TEXT NOT NULL REFERENCES products(id), position INTEGER NOT NULL,
  title TEXT NOT NULL, url TEXT NOT NULL, kind TEXT NOT NULL, PRIMARY KEY (product_id, position)
);
CREATE TABLE aliases (
  product_id TEXT NOT NULL REFERENCES products(id), position INTEGER NOT NULL,
  region TEXT NOT NULL, handle TEXT NOT NULL, source_product_id TEXT,
  PRIMARY KEY (product_id, position)
);
CREATE VIRTUAL TABLE product_search USING fts5(
  product_id UNINDEXED, search_text, tokenize='unicode61'
);
CREATE INDEX offers_region_available ON offers(region, available, listed);
CREATE INDEX assets_product_kind ON assets(product_id, kind);
CREATE INDEX categories_id ON category_assignments(category_id, product_id);
"""


def _json(items: object) -> str:
    return json.dumps(items, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _text(value: object) -> str | None:
    return None if value is None else str(value)


def _bool(value: bool | None) -> int | None:
    return None if value is None else int(value)


def _search_text(product: Product) -> str:
    chunks: list[str] = [
        product.id,
        product.name,
        product.description_text,
        *product.categories,
        *product.tags,
        *product.part_numbers,
        *product.skus,
        *(f"{key} {value}" for key, value in product.specifications.items()),
        *(f"{item.label} {item.raw_value}" for item in product.measurements),
        *(
            f"{item.name} {item.quantity or ''} {item.item_number or ''} "
            + " ".join(
                f"{quantity.variant} {quantity.quantity}" for quantity in item.variant_quantities
            )
            for item in product.box_contents
        ),
    ]
    return "\n".join(chunks)


def insert_product(connection: sqlite3.Connection, product: Product) -> None:
    connection.execute(
        "INSERT INTO products VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            product.id,
            product.schema_version,
            product.name,
            product.description_html,
            product.description_text,
            _json([block.model_dump(mode="json") for block in product.description_blocks]),
            _json(product.categories),
            _json(product.tags),
            _json(product.part_numbers),
            _json(product.skus),
            product.first_seen.isoformat(),
            product.last_seen.isoformat(),
            int(product.active),
            _text(product.removed_at),
        ),
    )
    for position, assignment in enumerate(product.category_assignments):
        connection.execute(
            "INSERT INTO category_assignments VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                product.id,
                position,
                assignment.id,
                assignment.label,
                _json(assignment.path),
                assignment.provenance.kind,
                assignment.provenance.reference,
                _text(assignment.provenance.source_url),
            ),
        )
    for offer in sorted(product.offers, key=lambda item: item.region.value):
        connection.execute(
            "INSERT INTO offers VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                product.id,
                offer.region.value,
                str(offer.url),
                offer.currency,
                offer.price,
                offer.compare_at_price,
                _bool(offer.available),
                int(offer.listed),
                offer.missing_runs,
                offer.retrieved_at.isoformat(),
            ),
        )
    for variant in sorted(product.variants, key=lambda item: (item.region.value, item.variant_id)):
        connection.execute(
            "INSERT INTO variants VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                product.id,
                variant.region.value,
                variant.variant_id,
                variant.title,
                variant.sku,
                variant.part_number,
                _bool(variant.available),
                variant.price,
                variant.compare_at_price,
                variant.currency,
                _text(variant.url),
                _text(variant.image_url),
            ),
        )
    for asset in sorted(product.assets, key=lambda item: item.id):
        connection.execute(
            "INSERT INTO assets VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                product.id,
                asset.id,
                asset.kind.value,
                str(asset.source_url),
                asset.original_filename,
                asset.media_type,
                asset.declared_media_type,
                asset.sha256,
                asset.size,
                asset.blob_path,
                asset.rights_status.value,
                _text(asset.retrieved_at),
                asset.rejection_reason,
                asset.parent_asset_id,
                asset.archive_member_path,
                _json(asset.image_processing.model_dump(mode="json"))
                if asset.image_processing
                else None,
            ),
        )
    for name, value in sorted(product.specifications.items()):
        connection.execute("INSERT INTO specifications VALUES (?, ?, ?)", (product.id, name, value))
    for position, measurement in enumerate(product.measurements):
        connection.execute(
            "INSERT INTO measurements VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                product.id,
                position,
                measurement.label,
                measurement.raw_value,
                _text(measurement.numeric_value),
                measurement.unit,
                measurement.applies_to,
                measurement.provenance.kind,
                measurement.provenance.reference,
                _text(measurement.provenance.source_url),
            ),
        )
    for position, table in enumerate(product.source_tables):
        connection.execute(
            "INSERT INTO source_tables VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                product.id,
                position,
                table.caption,
                _json(table.headers),
                _json(table.rows),
                table.provenance.kind,
                table.provenance.reference,
                _text(table.provenance.source_url),
            ),
        )
    for position, box_item in enumerate(product.box_contents):
        connection.execute(
            "INSERT INTO box_contents VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                product.id,
                position,
                box_item.item_number,
                box_item.name,
                box_item.quantity,
                _json([item.model_dump(mode="json") for item in box_item.variant_quantities]),
                _text(box_item.source_url),
                box_item.linked_product_id,
            ),
        )
    for position, link in enumerate(product.related_links):
        connection.execute(
            "INSERT INTO related_links VALUES (?, ?, ?, ?, ?)",
            (product.id, position, link.title, str(link.url), link.kind),
        )
    for position, alias in enumerate(product.aliases):
        connection.execute(
            "INSERT INTO aliases VALUES (?, ?, ?, ?, ?)",
            (product.id, position, alias.region.value, alias.handle, alias.product_id),
        )
    connection.execute(
        "INSERT INTO product_search VALUES (?, ?)", (product.id, _search_text(product))
    )


def build_database(catalog: Catalog, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(f"{output.suffix}.tmp")
    temporary.unlink(missing_ok=True)
    connection = sqlite3.connect(temporary)
    try:
        connection.executescript(SCHEMA)
        with connection:
            for product in sorted(catalog.products(), key=lambda item: item.id):
                insert_product(connection, product)
        connection.execute("PRAGMA user_version = 5")
        connection.execute("VACUUM")
    finally:
        connection.close()
    temporary.replace(output)
