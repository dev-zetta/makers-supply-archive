"""Generic fit references must be identifiable before choosing or saving a part."""

from pathlib import Path

import httpx
import pytest
from bs4 import BeautifulSoup
from makersfridge_web.state import connect
from test_catalog import authenticated_client, make_settings
from test_lists import csrf

from makersfridge.database import build_database
from makersfridge.http import ArchiveHttpClient
from makersfridge.models import Product, utc_now
from makersfridge.storage import Catalog
from makersfridge.suppliers.sync import SupplierSyncEngine, SupplierSyncOptions

ROOT = Path(__file__).parents[3]


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.anyio
@pytest.mark.parametrize("view", ["grid", "list", "compact"])
async def test_generic_reference_badge_is_visible_in_catalog_and_detail(
    tmp_path: Path, view: str
) -> None:
    settings = make_settings(tmp_path)
    now = utc_now()
    Catalog(tmp_path).write_product(
        Product(
            schema_version=5, id="generic-fit-reference", name="Generic drive reference",
            supplier_id="freecad-library", manufacturer="Generic reference",
            tags=["generic-reference"], first_seen=now, last_seen=now,
        )
    )
    build_database(Catalog(tmp_path), settings.catalog_db)
    client = await authenticated_client(settings)
    try:
        response = await client.get(f"/?supplier_id=freecad-library&region=eu&view={view}")
        soup = BeautifulSoup(response.text, "html.parser")
        cards = soup.select(".product-card")
        assert len(cards) == 1
        assert cards[0].select_one(".reference-badge").get_text() == "Generic reference"
        assert "FreeCAD Parts Library" in cards[0].get_text()
        detail = await client.get("/products/generic-fit-reference?region=eu")
        detail_soup = BeautifulSoup(detail.text, "html.parser")
        assert detail_soup.select_one(".reference-badge").get_text() == "Generic reference"
        assert "Verify the actual part" in detail_soup.select_one(".reference-note").get_text()
        # Existing manufacturer products retain their own classification and facts.
        original = await client.get("/products/ia005-power-board")
        assert not BeautifulSoup(original.text, "html.parser").select(".reference-badge")
        assert "Kit / project bundle" in original.text
    finally:
        await client.aclose()


@pytest.mark.anyio
async def test_pc_import_and_database_rebuild_preserve_existing_inventory_links(
    tmp_path: Path,
) -> None:
    settings = make_settings(tmp_path)
    catalog = Catalog(tmp_path)
    now = utc_now()
    catalog.write_product(Product(
        id="ia006-control-board", name="Linked control board", first_seen=now, last_seen=now,
    ))
    original_json = catalog.product_path("ia005-power-board").read_bytes()
    client = await authenticated_client(settings)
    try:
        created = await client.post("/lists", data={
            "name": "DIY NAS", "region": "eu", "csrf": csrf(settings),
        }, follow_redirects=False)
        list_url = created.headers["location"]
        response = await client.post(list_url + "/items", data={
            "product_id": "ia005-power-board", "variant_id": "eu-standard",
            "quantity": "2", "notes": "Existing inventory link", "csrf": csrf(settings),
        }, follow_redirects=False)
        assert response.status_code == 303
        with connect(settings.state_db) as db:
            original_item = dict(db.execute("SELECT * FROM list_items").fetchone())

        def unexpected_request(request: httpx.Request) -> httpx.Response:
            raise AssertionError(f"Metadata-only references should not fetch assets: {request.url}")

        with ArchiveHttpClient(delay=0, transport=httpx.MockTransport(unexpected_request)) as http:
            result = SupplierSyncEngine(tmp_path, http).run_suppliers(SupplierSyncOptions(
                suppliers=("noctua", "freecad-library", "generic-pc"), metadata_only=True,
                manifest=ROOT / "config/supplier-pilots.json",
            ))
        assert len(result.diff.added) == 8
        assert catalog.product_path("ia005-power-board").read_bytes() == original_json
        build_database(catalog, settings.catalog_db)
        with connect(settings.state_db) as db:
            assert dict(db.execute("SELECT * FROM list_items").fetchone()) == original_item

        for product_id in ["freecad-generic-drive-2-5-inch-7mm", "noctua-nf-a9-pwm"]:
            added = await client.post(list_url + "/items", data={
                "product_id": product_id, "quantity": "1", "csrf": csrf(settings),
            }, follow_redirects=False)
            assert added.status_code == 303
        exported = await client.get(list_url + "/export?format=json")
        assert exported.status_code == 200
        assert "Existing inventory link" in exported.text
        assert "ia005-power-board" in exported.text
        assert "eu-standard" in exported.text
        assert "freecad-generic-drive-2-5-inch-7mm" in exported.text
        assert "noctua-nf-a9-pwm" in exported.text
        with connect(settings.state_db) as db:
            assert dict(db.execute("SELECT * FROM list_items WHERE id=?",
                                   (original_item["id"],)).fetchone()) == original_item
    finally:
        await client.aclose()
