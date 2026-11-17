"""Supplier browsing must preserve existing product and saved-list identities."""
import hashlib
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest
from bs4 import BeautifulSoup
from makersfridge_web.catalog import SearchFilters, product_detail, search_products, suppliers
from makersfridge_web.parts import current_price, list_view
from makersfridge_web.state import connect
from test_catalog import authenticated_client, make_settings
from test_lists import csrf

from makersfridge.database import build_database
from makersfridge.models import Asset, AssetKind, Product, Region, RegionalOffer, Variant
from makersfridge.storage import Catalog


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def add_supplier(root: Path, *, count: int = 1) -> None:
    timestamp = datetime(2026, 11, 17, tzinfo=UTC)
    catalog = Catalog(root)
    for number in range(count):
        catalog.write_product(Product(
            schema_version=5, id=f"bigtreetech-board-{number:02}", name=f"BTT board {number:02}",
            supplier_id="bigtreetech", manufacturer="BIGTREETECH", hardware_revision="V3.0",
            skus=[f"BTT-{number:02}"], first_seen=timestamp, last_seen=timestamp,
            offers=[RegionalOffer(
                region=Region.GLOBAL, store_id="biqu-global", currency="USD", price="19.50",
                available=True, url="https://biqu.equipment/products/test", retrieved_at=timestamp,
            )],
            variants=[Variant(
                region=Region.GLOBAL, store_id="biqu-global", variant_id=f"btt-{number:02}",
                title="Board only", sku=f"BTT-{number:02}", price="19.50", currency="USD",
                available=True,
            )],
            assets=[Asset(
                id="board-step", kind=AssetKind.MODEL, role="component",
                source_url="https://example.com/board.step", original_filename="board.step",
                media_type="application/step", applies_to_skus=[f"BTT-{number:02}"],
                hardware_revision="V3.0", source_repository="bigtreetech/test",
                source_commit="1" * 40, source_path="CAD/board.step",
            )],
        ))
    build_database(catalog, root / "catalog.sqlite")


def test_supplier_search_global_market_and_explicit_cad_mapping(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    add_supplier(tmp_path)
    rows, total = search_products(
        settings.catalog_db, SearchFilters(region="eu", supplier_id="bigtreetech")
    )
    assert total == 1
    assert rows[0]["id"] == "bigtreetech-board-00"
    assert rows[0]["currency"] == "USD"
    assert {item["id"] for item in suppliers(settings.catalog_db)} == {
        "bambu-lab", "bigtreetech"
    }
    assert search_products(
        settings.catalog_db, SearchFilters(supplier_id="bigtreetech' OR 1=1 --")
    )[1] == 0
    product = product_detail(settings.catalog_db, "bigtreetech-board-00", "eu")
    assert product is not None
    assert product["supplier_label"] == "BIGTREETECH"
    assert product["commerce_rows"][0]["store_id"] == "biqu-global"
    assert product["asset_groups"][0]["part_number"] == "BTT-00"
    assert product["shared_assets"] == []


def test_reference_only_hardware_is_visible_in_regional_catalog(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    catalog = Catalog(tmp_path)
    timestamp = datetime(2026, 11, 17, tzinfo=UTC)
    catalog.write_product(Product(
        schema_version=5, id="biqu-hermit-crab", name="Hermit Crab", supplier_id="biqu",
        manufacturer="BIQU", first_seen=timestamp, last_seen=timestamp,
    ))
    build_database(catalog, settings.catalog_db)
    rows, total = search_products(
        settings.catalog_db, SearchFilters(region="us", supplier_id="biqu")
    )
    assert total == 1 and rows[0]["id"] == "biqu-hermit-crab"
    assert rows[0]["price"] is None and rows[0]["available"] is None
    assert current_price(settings.catalog_db, "biqu-hermit-crab", "us", None) == (
        None, None, None
    )


@pytest.mark.anyio
async def test_supplier_filter_preserved_by_navigation(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    add_supplier(tmp_path, count=25)
    client = await authenticated_client(settings)
    try:
        response = await client.get("/?supplier_id=bigtreetech&region=eu&view=list&q=BTT")
        assert response.status_code == 200
        soup = BeautifulSoup(response.text, "html.parser")
        supplier_filter = soup.select_one('select[name="supplier_id"]')
        assert supplier_filter is not None and supplier_filter["aria-label"] == "Supplier"
        selected = soup.select_one('select[name="supplier_id"] option[selected]')
        assert selected is not None and selected["value"] == "bigtreetech"
        assert "Bambu Lab (1)" in response.text
        next_link = soup.select_one("[data-next-page]")
        assert next_link is not None
        query = parse_qs(urlsplit(str(next_link["href"])).query)
        assert query["supplier_id"] == ["bigtreetech"]
        assert query["region"] == ["eu"]
        assert query["q"] == ["BTT"]
        view_link = soup.select_one('.view-switcher a[title="Grid view"]')
        assert view_link is not None and "supplier_id=bigtreetech" in str(view_link["href"])
        region_return = soup.select_one('.global-region input[name="next"]')
        assert region_return is not None
        assert "supplier_id=bigtreetech" in str(region_return["value"])
        product_link = soup.select_one('.product-card a')
        assert product_link is not None
        detail = await client.get(str(product_link["href"]))
        assert "CAD revision: V3.0" in detail.text
        assert "Compatible SKUs: BTT-00" in detail.text
        assert "BIQU global store ↗" in detail.text
        back = BeautifulSoup(detail.text, "html.parser").select_one("a.brand")
        assert back is not None
        assert parse_qs(urlsplit(str(back["href"])).query)["supplier_id"] == ["bigtreetech"]
        api = await client.get("/api/products?supplier_id=bigtreetech&region=eu")
        assert api.json()["total"] == 25
        assert {item["supplier_id"] for item in api.json()["items"]} == {"bigtreetech"}
    finally:
        await client.aclose()


@pytest.mark.anyio
async def test_global_variant_and_bambu_saved_links_survive_together(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    client = await authenticated_client(settings)
    try:
        created = await client.post("/lists", data={
            "name": "Mixed suppliers", "region": "eu", "csrf": csrf(settings),
        }, follow_redirects=False)
        list_url = created.headers["location"]
        original = await client.post(list_url + "/items", data={
            "product_id": "ia005-power-board", "variant_id": "eu-standard",
            "quantity": "2", "notes": "Existing inventory link", "csrf": csrf(settings),
        }, follow_redirects=False)
        assert original.status_code == 303
        with connect(settings.state_db) as db:
            old_item = dict(db.execute("SELECT * FROM list_items").fetchone())
        add_supplier(tmp_path)
        added = await client.post(list_url + "/items", data={
            "product_id": "bigtreetech-board-00", "variant_id": "btt-00",
            "quantity": "3", "csrf": csrf(settings),
        }, follow_redirects=False)
        assert added.status_code == 303
        with connect(settings.state_db) as db:
            assert dict(db.execute(
                "SELECT * FROM list_items WHERE id=?", (old_item["id"],)
            ).fetchone()) == old_item
            owner = db.execute("SELECT owner_id FROM lists").fetchone()[0]
        view = list_view(settings.state_db, settings.catalog_db, list_url.rsplit("/", 1)[1], owner)
        assert view is not None
        assert view["current_totals"] == {"USD": "58.50"}
        # The existing EU variant is unavailable and remains excluded from current totals.
        assert view["unavailable_count"] == 1
        assert current_price(settings.catalog_db, "bigtreetech-board-00", "eu", "btt-00") == (
            "19.50", "USD", True
        )
        exported = await client.get(list_url + "/export?format=json")
        assert exported.status_code == 200
        assert "ia005-power-board" in exported.text and "bigtreetech-board-00" in exported.text
        assert "Existing inventory link" in exported.text
    finally:
        await client.aclose()


def test_multiple_stores_do_not_mix_variant_prices(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    add_supplier(tmp_path)
    with sqlite3.connect(settings.catalog_db) as db:
        db.execute("INSERT INTO offers SELECT product_id, region, url, currency, '2.00', "
                   "compare_at_price, available, listed, missing_runs, retrieved_at, 'other-store' "
                   "FROM offers WHERE product_id='bigtreetech-board-00'")
        db.execute("INSERT INTO variants SELECT product_id, region, 'other-variant', title, sku, "
                   "part_number, available, NULL, compare_at_price, currency, url, image_url, "
                   "'other-store' FROM variants WHERE product_id='bigtreetech-board-00'")
    product = product_detail(settings.catalog_db, "bigtreetech-board-00", "eu")
    assert product is not None
    assert {row["store_id"]: row["price"] for row in product["commerce_rows"]} == {
        "biqu-global": "19.50", "other-store": "2.00"
    }
    assert current_price(settings.catalog_db, "bigtreetech-board-00", "eu", "other-variant") == (
        "2.00", "USD", True
    )


def test_schema_five_catalog_remains_readable_without_mutation(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    with sqlite3.connect(settings.catalog_db) as db:
        db.execute("DROP INDEX products_supplier")
        for column in ("supplier_id", "manufacturer", "hardware_revision"):
            db.execute(f"ALTER TABLE products DROP COLUMN {column}")
        for table in ("offers", "variants"):
            columns = [row[1] for row in db.execute(f"PRAGMA table_info({table})")
                       if row[1] != "store_id"]
            db.execute(f"CREATE TABLE old_{table} AS SELECT {', '.join(columns)} FROM {table}")
            db.execute(f"DROP TABLE {table}")
            db.execute(f"ALTER TABLE old_{table} RENAME TO {table}")
        for column in ("role", "applies_to_skus_json", "hardware_revision", "source_repository",
                       "source_commit", "source_path", "license_url"):
            db.execute(f"ALTER TABLE assets DROP COLUMN {column}")
        db.execute("PRAGMA user_version=5")
    before = hashlib.sha256(settings.catalog_db.read_bytes()).hexdigest()
    products, total = search_products(settings.catalog_db, SearchFilters(supplier_id="bambu-lab"))
    assert total == 1 and products[0]["id"] == "ia005-power-board"
    product = product_detail(settings.catalog_db, "ia005-power-board", "us")
    assert product is not None and product["manufacturer"] == "Bambu Lab"
    assert current_price(settings.catalog_db, "ia005-power-board", "us", "us-standard") == (
        "6.29", "USD", True
    )
    assert hashlib.sha256(settings.catalog_db.read_bytes()).hexdigest() == before
