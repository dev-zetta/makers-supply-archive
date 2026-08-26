import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from makers_supply.database import build_database
from makers_supply.models import (
    Asset,
    AssetKind,
    BoxItem,
    BoxItemQuantity,
    Product,
    Region,
    RegionalOffer,
)
from makers_supply.portable import build_portable_catalog
from makers_supply.storage import Catalog


def sample_product() -> Product:
    now = datetime(2026, 1, 2, tzinfo=UTC)
    return Product(
        id="ia005-power-board",
        name="Power board",
        categories=["Electronics"],
        specifications={"Voltage": "5 V"},
        box_contents=[
            BoxItem(
                name="Power lead",
                variant_quantities=[BoxItemQuantity(variant="Full Kit", quantity="2 pcs")],
            )
        ],
        offers=[
            RegionalOffer(
                region=Region.US,
                url="https://example.com/products/power-board",
                currency="USD",
                price="5.29",
                retrieved_at=now,
            )
        ],
        first_seen=now,
        last_seen=now,
    )


def test_catalog_writes_canonical_json(tmp_path: Path) -> None:
    catalog = Catalog(tmp_path)
    catalog.write_product(sample_product())
    content = catalog.product_path("ia005-power-board").read_text("utf-8")
    assert content.endswith("\n")
    assert json.loads(content)["name"] == "Power board"
    assert catalog.load_product("ia005-power-board") == sample_product()


def test_database_matches_json(tmp_path: Path) -> None:
    catalog = Catalog(tmp_path)
    catalog.write_product(sample_product())
    output = tmp_path / "catalog.sqlite"
    build_database(catalog, output)
    with sqlite3.connect(output) as connection:
        assert connection.execute("SELECT id, name FROM products").fetchall() == [
            ("ia005-power-board", "Power board")
        ]
        assert connection.execute("SELECT region, price FROM offers").fetchall() == [("us", "5.29")]
        assert connection.execute("PRAGMA user_version").fetchone() == (5,)
        assert connection.execute(
            "SELECT variant_quantities_json FROM box_contents"
        ).fetchone() == ('[{"quantity":"2 pcs","variant":"Full Kit"}]',)
        assert connection.execute(
            "SELECT product_id FROM product_search WHERE product_search MATCH 'Power'"
        ).fetchall() == [("ia005-power-board",)]


def test_portable_catalog_uses_named_asset_files(tmp_path: Path) -> None:
    catalog = Catalog(tmp_path / "source")
    blob = catalog.blob_path("a" * 64, ".step")
    blob.parent.mkdir(parents=True)
    blob.write_bytes(b"ISO-10303-21;")
    product = sample_product().model_copy(
        update={
            "assets": [
                Asset(
                    id="model-file",
                    kind=AssetKind.MODEL,
                    source_url="https://example.com/board.step",
                    original_filename="Power board.step",
                    media_type="model/step",
                    sha256="a" * 64,
                    size=13,
                    blob_path=blob.relative_to(catalog.root).as_posix(),
                )
            ]
        }
    )
    catalog.write_product(product)

    portable = build_portable_catalog(catalog, tmp_path / "portable")

    named_asset = portable.assets / "ia005-power-board/Models/Power board.step"
    assert portable.file_count == 1
    assert named_asset.read_bytes() == b"ISO-10303-21;"
    with sqlite3.connect(portable.database) as connection:
        assert connection.execute("SELECT blob_path FROM assets").fetchone() == (
            "assets/ia005-power-board/Models/Power board.step",
        )


def test_portable_catalog_uses_readable_folders_for_filename_collisions(tmp_path: Path) -> None:
    catalog = Catalog(tmp_path / "source")
    primary_blob = catalog.blob_path("b" * 64, ".step")
    alternate_blob = catalog.blob_path("c" * 64, ".step")
    primary_blob.parent.mkdir(parents=True)
    alternate_blob.parent.mkdir(parents=True)
    primary_blob.write_bytes(b"primary")
    alternate_blob.write_bytes(b"alternate")
    product = sample_product().model_copy(
        update={
            "assets": [
                Asset(
                    id="primary-archive",
                    kind=AssetKind.ARCHIVE,
                    source_url="https://example.com/primary.zip",
                    original_filename="Primary models.zip",
                    media_type="application/zip",
                ),
                Asset(
                    id="alternate-archive",
                    kind=AssetKind.ARCHIVE,
                    source_url="https://example.com/alternate.zip",
                    original_filename="Alternate models.zip",
                    media_type="application/zip",
                ),
                Asset(
                    id="primary-model",
                    kind=AssetKind.MODEL,
                    source_url="https://example.com/primary.zip",
                    original_filename="part.step",
                    media_type="model/step",
                    sha256="b" * 64,
                    size=7,
                    blob_path=primary_blob.relative_to(catalog.root).as_posix(),
                    parent_asset_id="primary-archive",
                    archive_member_path="models/part.step",
                ),
                Asset(
                    id="alternate-model",
                    kind=AssetKind.MODEL,
                    source_url="https://example.com/alternate.zip",
                    original_filename="part.step",
                    media_type="model/step",
                    sha256="c" * 64,
                    size=9,
                    blob_path=alternate_blob.relative_to(catalog.root).as_posix(),
                    parent_asset_id="alternate-archive",
                    archive_member_path="other/deep/path/part.step",
                ),
            ]
        }
    )
    catalog.write_product(product)

    portable = build_portable_catalog(catalog, tmp_path / "portable")

    assert (
        portable.assets / "ia005-power-board/Models/Primary models/part.step"
    ).read_bytes() == b"primary"
    assert (
        portable.assets / "ia005-power-board/Models/Alternate models/part.step"
    ).read_bytes() == b"alternate"
    with sqlite3.connect(portable.database) as connection:
        assert connection.execute(
            "SELECT id, blob_path FROM assets WHERE blob_path IS NOT NULL ORDER BY id"
        ).fetchall() == [
            (
                "alternate-model",
                "assets/ia005-power-board/Models/Alternate models/part.step",
            ),
            ("primary-model", "assets/ia005-power-board/Models/Primary models/part.step"),
        ]
