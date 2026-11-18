"""Legacy motion references remain searchable without reassigning saved inventory."""

from pathlib import Path

import httpx
import pytest
from makersfridge_web.catalog import SearchFilters, search_products, suppliers
from makersfridge_web.state import connect
from test_catalog import authenticated_client, make_settings
from test_lists import csrf

from makersfridge.database import build_database
from makersfridge.http import ArchiveHttpClient
from makersfridge.models import Product, utc_now
from makersfridge.storage import Catalog
from makersfridge.suppliers.adapters import reference_product
from makersfridge.suppliers.catalog import load_pilots
from makersfridge.suppliers.sync import SupplierSyncEngine, SupplierSyncOptions

ROOT = Path(__file__).parents[3]
LEGACY_SOURCES = (
    ROOT / "config/supplier-sources/openbuilds-mechanical.json",
    ROOT / "config/supplier-sources/openbuilds-motors.json",
)


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def test_openbuilds_profiles_wheels_and_motors_are_searchable_in_regional_views(
    tmp_path: Path,
) -> None:
    catalog = Catalog(tmp_path)
    specs = [spec for path in LEGACY_SOURCES for spec in load_pilots(path)]
    assert len(specs) == 11
    for spec in specs:
        catalog.write_product(reference_product(spec, utc_now()))
    database = tmp_path / "catalog.sqlite"
    build_database(catalog, database)
    assert {s["id"]: s["label"] for s in suppliers(database)} == {"openbuilds": "OpenBuilds"}
    _, count = search_products(database, SearchFilters(supplier_id="openbuilds", region="eu"))
    assert count == 11
    motors, motor_count = search_products(database, SearchFilters(query="NEMA", region="us"))
    assert motor_count == 3
    assert all("legacy" in motor["name"].lower() for motor in motors)
    wheels, wheel_count = search_products(database, SearchFilters(query="Delrin", region="eu"))
    assert wheel_count == 2
    assert all(wheel["supplier_id"] == "openbuilds" for wheel in wheels)


@pytest.mark.anyio
async def test_motion_import_preserves_bambu_inventory_and_saves_new_reference(
    tmp_path: Path,
) -> None:
    settings = make_settings(tmp_path)
    catalog = Catalog(tmp_path)
    now = utc_now()
    catalog.write_product(Product(
        id="ia006-control-board", name="Linked control board", first_seen=now, last_seen=now,
    ))
    original = catalog.product_path("ia005-power-board").read_bytes()
    client = await authenticated_client(settings)
    try:
        created = await client.post("/lists", data={
            "name": "CNC frame", "region": "eu", "csrf": csrf(settings),
        }, follow_redirects=False)
        list_url = created.headers["location"]
        added = await client.post(list_url + "/items", data={
            "product_id": "ia005-power-board", "variant_id": "eu-standard",
            "quantity": "3", "notes": "Existing stock link", "csrf": csrf(settings),
        }, follow_redirects=False)
        assert added.status_code == 303
        with connect(settings.state_db) as db:
            original_item = dict(db.execute("SELECT * FROM list_items").fetchone())

        def offline(request: httpx.Request) -> httpx.Response:
            raise AssertionError(f"Reference metadata unexpectedly fetched {request.url}")

        with ArchiveHttpClient(delay=0, transport=httpx.MockTransport(offline)) as http:
            result = SupplierSyncEngine(tmp_path, http).run_suppliers(SupplierSyncOptions(
                suppliers=("openbuilds",), metadata_only=True,
                product_ids=("openbuilds-v-slot-20x20-500mm",),
                manifest=ROOT / "config/supplier-pilots.json",
            ))
        assert len(result.diff.added) == 1
        assert catalog.product_path("ia005-power-board").read_bytes() == original
        build_database(catalog, settings.catalog_db)
        new = await client.post(list_url + "/items", data={
            "product_id": "openbuilds-v-slot-20x20-500mm", "quantity": "4",
            "csrf": csrf(settings),
        }, follow_redirects=False)
        assert new.status_code == 303
        with connect(settings.state_db) as db:
            assert dict(db.execute("SELECT * FROM list_items WHERE id=?",
                                   (original_item["id"],)).fetchone()) == original_item
        exported = await client.get(list_url + "/export?format=json")
        assert exported.status_code == 200
        assert "Existing stock link" in exported.text
        assert "eu-standard" in exported.text
        assert "openbuilds-v-slot-20x20-500mm" in exported.text
    finally:
        await client.aclose()
