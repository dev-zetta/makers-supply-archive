from pathlib import Path

import pytest
from bs4 import BeautifulSoup
from makersfridge_web.catalog import SearchFilters, product_detail, search_products, suppliers
from test_catalog import authenticated_client, make_settings

from makersfridge.database import build_database
from makersfridge.models import utc_now
from makersfridge.storage import Catalog
from makersfridge.suppliers.adapters import reference_product
from makersfridge.suppliers.catalog import load_pilots

ROOT = Path(__file__).parents[3]


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def test_manufacturer_filters_and_esp32_family_search_share_reviewed_sources(
    tmp_path: Path,
) -> None:
    catalog = Catalog(tmp_path)
    specs = load_pilots(ROOT / "config/supplier-pilots.json")
    for spec in specs:
        if spec.supplier_id in {"raspberry-pi", "espressif", "waveshare"}:
            catalog.write_product(reference_product(spec, utc_now()))
    database = tmp_path / "catalog.sqlite"
    build_database(catalog, database)
    labels = {item["id"]: item["label"] for item in suppliers(database)}
    assert labels["raspberry-pi"] == "Raspberry Pi"
    assert labels["espressif"] == "Espressif Systems"
    assert search_products(database, SearchFilters(supplier_id="raspberry-pi", region="eu"))[1] == 6
    assert search_products(database, SearchFilters(supplier_id="espressif", region="us"))[1] == 6
    found, count = search_products(database, SearchFilters(query="ESP32", region="eu"))
    assert count >= 8
    assert {item["supplier_id"] for item in found} == {"espressif", "waveshare"}
    module = product_detail(database, "espressif-esp32-s3-wroom-1", "us")
    assert module is not None
    assert module["supplier_label"] == "Espressif Systems"
    assert module["commerce_rows"] == []
    assert any(asset["rights_status"] == "licensed" for asset in module["assets"])
    no_cad = product_detail(database, "raspberry-pi-pico-2-w", "eu")
    assert no_cad is not None
    assert all(asset["kind"] != "model" for asset in no_cad["assets"])


@pytest.mark.anyio
async def test_drawing_only_boards_are_not_labeled_as_3d_models(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    catalog = Catalog(tmp_path)
    specs = load_pilots(ROOT / "config/supplier-pilots.json")
    spec = next(p for p in specs if p.id == "espressif-esp32-devkitc-v4")
    catalog.write_product(reference_product(spec, utc_now()))
    build_database(catalog, settings.catalog_db)
    client = await authenticated_client(settings)
    try:
        response = await client.get(f"/products/{spec.id}")
    finally:
        await client.aclose()
    assert response.status_code == 200
    cards = BeautifulSoup(response.text, "html.parser").select("article.asset-card")
    drawings = [card for card in cards if card.select_one("h3").get_text().endswith(".dxf")]
    assert drawings
    assert all(card.select_one(".asset-icon").get_text() == "2D" for card in drawings)
