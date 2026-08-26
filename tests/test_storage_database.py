import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from makers_supply.database import build_database
from makers_supply.models import BoxItem, BoxItemQuantity, Product, Region, RegionalOffer
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
