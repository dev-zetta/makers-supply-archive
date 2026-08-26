import sqlite3
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from makers_supply_web.app import create_app, human_datetime
from makers_supply_web.catalog import SearchFilters, search_products
from makers_supply_web.config import Settings
from makers_supply_web.security import PASSWORDS, now
from makers_supply_web.state import connect, migrate

from makers_supply.database import build_database
from makers_supply.models import (
    Asset,
    AssetKind,
    BoxItem,
    BoxItemQuantity,
    CategoryAssignment,
    DescriptionBlock,
    ImageProcessing,
    Measurement,
    Product,
    Provenance,
    Region,
    RegionalOffer,
    RelatedLink,
    Variant,
)
from makers_supply.storage import Catalog


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def make_catalog(root: Path) -> Path:
    timestamp = datetime(2026, 1, 2, tzinfo=UTC)
    blob = root / "data/blobs/sha256/aa/asset.png"
    blob.parent.mkdir(parents=True)
    blob.write_bytes(b"safe image")
    normalized_blob = root / "data/blobs/sha256/bb/normalized.png"
    normalized_blob.parent.mkdir(parents=True)
    normalized_blob.write_bytes(b"normalized image")
    secondary_blob = root / "data/blobs/sha256/cc/secondary.png"
    secondary_blob.parent.mkdir(parents=True)
    secondary_blob.write_bytes(b"secondary image")
    secondary_display_blob = root / "data/blobs/sha256/dd/secondary-display.png"
    secondary_display_blob.parent.mkdir(parents=True)
    secondary_display_blob.write_bytes(b"secondary display")
    product = Product(
        id="ia005-power-board",
        name="Power Distribution Board",
        description_text="Four channel electronics board",
        description_blocks=[
            DescriptionBlock(kind="heading", text="Overview"),
            DescriptionBlock(kind="paragraph", text="Four channel electronics board"),
        ],
        categories=["Electronics"],
        tags=["kit"],
        category_assignments=[
            CategoryAssignment(
                id="electronics",
                label="Electronics",
                path=["Electronics"],
                provenance=Provenance(kind="classification_rule", reference="test"),
            )
        ],
        measurements=[
            Measurement(
                label="Width (mm)",
                raw_value="25",
                provenance=Provenance(
                    kind="page_table",
                    reference="specification:Width (mm)",
                    source_url="https://us.store.bambulab.com/products/power-board",
                ),
            )
        ],
        skus=["IA005"],
        box_contents=[
            BoxItem(
                name="Control board",
                variant_quantities=[
                    BoxItemQuantity(variant="Standard Kit", quantity="2 pcs"),
                    BoxItemQuantity(variant="Starter Kit", quantity="1 pc"),
                ],
                item_number="IA006",
                source_url="https://example.com/control-board",
                linked_product_id="ia006-control-board",
            )
        ],
        offers=[
            RegionalOffer(
                region=Region.US,
                url="https://example.com/power",
                currency="USD",
                price="5.29",
                available=True,
                retrieved_at=timestamp,
            ),
            RegionalOffer(
                region=Region.EU,
                url="https://eu.example.com/power",
                currency="EUR",
                price="4.99",
                available=True,
                retrieved_at=timestamp,
            ),
        ],
        variants=[
            Variant(
                region=Region.US,
                variant_id="us-standard",
                title="Power Distribution Board - Standard Kit",
                sku="US-IA005",
                part_number="IA005",
                available=True,
                price="6.29",
                compare_at_price="7.29",
                currency="USD",
                url="https://example.com/power?id=us-standard",
                image_url="https://example.com/image.png",
            ),
            Variant(
                region=Region.EU,
                variant_id="eu-standard",
                title="Power Distribution Board - European Kit",
                sku="EU-IA005",
                part_number="IA005",
                available=False,
                price="5.99",
                currency="EUR",
                url="https://eu.example.com/power?id=eu-standard",
                image_url="https://example.com/image.png",
            ),
        ],
        related_links=[
            RelatedLink(
                title="Official instructions",
                url="https://makerworld.com/en/models/123",
                kind="makerworld",
            )
        ],
        assets=[
            Asset(
                id="primary-image",
                kind=AssetKind.IMAGE,
                source_url="https://example.com/image.png",
                original_filename="image.png",
                media_type="image/png",
                sha256="a" * 64,
                size=10,
                blob_path="data/blobs/sha256/aa/asset.png",
                retrieved_at=timestamp,
            ),
            Asset(
                id="normalized-image",
                kind=AssetKind.IMAGE,
                source_url="https://example.com/image.png",
                original_filename="image.catalog.png",
                media_type="image/png",
                sha256="b" * 64,
                size=16,
                blob_path="data/blobs/sha256/bb/normalized.png",
                retrieved_at=timestamp,
                parent_asset_id="primary-image",
                image_processing=ImageProcessing(
                    source_sha256="a" * 64,
                    source_width=640,
                    source_height=480,
                    output_width=800,
                    output_height=800,
                ),
            ),
            Asset(
                id="secondary-image",
                kind=AssetKind.IMAGE,
                source_url="https://example.com/secondary.png",
                original_filename="secondary.png",
                media_type="image/png",
                sha256="c" * 64,
                size=15,
                blob_path="data/blobs/sha256/cc/secondary.png",
                retrieved_at=timestamp,
            ),
            Asset(
                id="aaa-secondary-display",
                kind=AssetKind.IMAGE,
                source_url="https://example.com/secondary.png",
                original_filename="secondary.catalog.png",
                media_type="image/png",
                sha256="d" * 64,
                size=17,
                blob_path="data/blobs/sha256/dd/secondary-display.png",
                retrieved_at=timestamp,
                parent_asset_id="secondary-image",
                image_processing=ImageProcessing(
                    source_sha256="c" * 64,
                    source_width=800,
                    source_height=800,
                    output_width=800,
                    output_height=800,
                ),
            ),
            Asset(
                id="unsafe-model",
                kind=AssetKind.MODEL,
                source_url="https://example.com/Power-IA005.stl",
                original_filename="Power-IA005.stl",
                media_type="model/stl",
                rejection_reason="invalid model signature",
            ),
        ],
        first_seen=timestamp,
        last_seen=timestamp,
    )
    Catalog(root).write_product(product)
    output = root / "catalog.sqlite"
    build_database(Catalog(root), output)
    return output


def make_settings(tmp_path: Path) -> Settings:
    catalog = make_catalog(tmp_path)
    settings = Settings(tmp_path, catalog, tmp_path / "state.sqlite", "test-secret", False)
    migrate(settings.state_db)
    with connect(settings.state_db) as connection, connection:
        connection.execute(
            "INSERT INTO users VALUES (?, 'admin', ?, 1, 1, ?)",
            (str(uuid4()), PASSWORDS.hash("correct horse battery"), now().isoformat()),
        )
    return settings


async def authenticated_client(settings: Settings) -> httpx.AsyncClient:
    client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(settings)), base_url="http://test"
    )
    response = await client.post(
        "/login",
        data={"username": "admin", "password": "correct horse battery"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    return client


def test_fts_search_and_filters(tmp_path: Path) -> None:
    catalog = make_catalog(tmp_path)
    products, total = search_products(
        catalog, SearchFilters(query="IA005 board", category="electronics", region="us")
    )
    assert total == 1
    assert products[0]["name"] == "Power Distribution Board"

    global_products, global_total = search_products(
        catalog, SearchFilters(query="IA005 board", region="global")
    )
    assert global_total == 1
    assert global_products[0]["currency"] == "USD"


def test_lifecycle_filter_can_include_removed_products(tmp_path: Path) -> None:
    catalog = make_catalog(tmp_path)
    with sqlite3.connect(catalog) as connection:
        connection.execute("UPDATE products SET active=0")
    _, active_total = search_products(catalog, SearchFilters())
    _, removed_total = search_products(catalog, SearchFilters(lifecycle="inactive"))
    _, all_total = search_products(catalog, SearchFilters(lifecycle="all"))
    assert (active_total, removed_total, all_total) == (0, 1, 1)


def test_human_datetime_formats_iso_values() -> None:
    assert human_datetime("2026-08-23T16:35:17+00:00") == ("Aug 23, 2026 at 4:35 PM UTC")
    assert human_datetime(None) == "Not published"
    assert human_datetime("source value") == "source value"


@pytest.mark.anyio
async def test_catalog_pages_and_assets_require_login(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    anonymous = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(settings)), base_url="http://test"
    )
    response = await anonymous.get("/", follow_redirects=False)
    await anonymous.aclose()
    assert response.status_code == 303
    client = await authenticated_client(settings)
    try:
        catalog = await client.get("/")
        detail = await client.get("/products/ia005-power-board")
        image = await client.get("/assets/ia005-power-board/primary-image")
        partial = await client.get(
            "/assets/ia005-power-board/primary-image", headers={"Range": "bytes=0-3"}
        )
        rejected = await client.get("/assets/ia005-power-board/unsafe-model")
    finally:
        await client.aclose()
    assert catalog.status_code == 200
    assert "Power Distribution Board" in catalog.text
    assert "/assets/ia005-power-board/normalized-image" in catalog.text
    assert detail.status_code == 200
    assert "USA variants and pricing" in detail.text
    assert "Regional offers" not in detail.text
    assert "Power Distribution Board - Standard Kit" not in detail.text
    assert ">Standard Kit<" in detail.text
    assert "6.29 USD" in detail.text
    assert "7.29 USD" in detail.text
    assert "Kit / project bundle" in detail.text
    assert "Included items" in detail.text
    assert "Standard Kit" in detail.text
    assert "Starter Kit" in detail.text
    assert 'href="/products/ia006-control-board?region=us"' in detail.text
    assert "Official store ↗" in detail.text
    assert detail.text.count(
        'target="_blank" rel="external noopener noreferrer"'
    ) == 4
    assert '<span class="status available">Available</span>' in detail.text
    assert ">Unknown<" not in detail.text
    assert "25" in detail.text
    assert "Official specification ↗" in detail.text
    assert "specification:Width (mm)" not in detail.text
    assert ">MakerWorld</span>" in detail.text
    assert "<h2>Overview</h2>" in detail.text
    assert 'id="gallery-main-image"' in detail.text
    assert "data-gallery-thumbnail" in detail.text
    assert 'id="image-dialog"' in detail.text
    assert '<span class="variant-code">IA005</span>' in detail.text
    assert "Power-IA005.stl" in detail.text
    assert "<dt>Part numbers</dt>" not in detail.text
    assert "<dt>SKUs</dt>" not in detail.text
    assert 'data-gallery-part-number="IA005"' in detail.text
    assert 'data-gallery-skus="US · US-IA005"' in detail.text
    assert "data-gallery-part-number-output" in detail.text
    assert 'data-product-description' in detail.text
    assert 'data-description-toggle' in detail.text
    assert detail.text.index("<dt>Product ID</dt>") < detail.text.index(
        'data-product-description'
    )
    assert image.content == b"safe image"
    assert partial.status_code == 206
    assert partial.content == b"safe"
    assert partial.headers["content-range"] == "bytes 0-3/10"
    assert rejected.status_code == 404


@pytest.mark.anyio
async def test_local_mode_needs_no_login_information(tmp_path: Path) -> None:
    settings = replace(make_settings(tmp_path), local_mode=True)
    client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(settings)), base_url="http://test"
    )
    try:
        catalog = await client.get("/")
        login = await client.get("/login", follow_redirects=False)
    finally:
        await client.aclose()

    assert catalog.status_code == 200
    assert "Power Distribution Board" in catalog.text
    assert "Local app" in catalog.text
    assert "Sign out" not in catalog.text
    assert login.status_code == 303
    assert login.headers["location"] == "/"


@pytest.mark.anyio
async def test_catalog_view_controls_and_query_filters(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    client = await authenticated_client(settings)
    try:
        response = await client.get(
            "/?category=electronics&region=us&availability=available&view=list"
        )
        invalid_view = await client.get("/?view=unexpected")
        detail = await client.get("/products/ia005-power-board")
    finally:
        await client.aclose()

    assert response.status_code == 200
    assert 'class="product-grid view-list"' in response.text
    assert 'name="category" data-auto-submit' in response.text
    assert 'name="region" data-auto-submit' not in response.text
    assert 'data-global-region-switch' in response.text
    assert 'aria-label="Product display"' in response.text
    assert 'data-pagination' in response.text
    assert "Jan 2, 2026 at 12:00 AM UTC" in detail.text
    assert "view=compact" in response.text
    assert 'class="product-grid view-grid"' in invalid_view.text


@pytest.mark.anyio
async def test_global_region_switch_filters_catalog_and_product_commerce(
    tmp_path: Path,
) -> None:
    settings = make_settings(tmp_path)
    client = await authenticated_client(settings)
    try:
        switched = await client.get(
            "/region?region=eu&next=/products/ia005-power-board",
            follow_redirects=False,
        )
        european_detail = await client.get("/products/ia005-power-board")
        european_catalog = await client.get("/")
        await client.get("/region?region=global&next=/", follow_redirects=False)
        global_detail = await client.get("/products/ia005-power-board")
        invalid = await client.get(
            "/region?region=invalid&next=/", follow_redirects=False
        )
    finally:
        await client.aclose()

    assert switched.status_code == 303
    assert "makers_supply_region=eu" in switched.headers["set-cookie"]
    assert "EU variants and pricing" in european_detail.text
    assert "European Kit" in european_detail.text
    assert "5.99 EUR" in european_detail.text
    assert "6.29 USD" not in european_detail.text
    assert "US-IA005" not in european_detail.text
    assert '<option value="eu" selected>' in european_catalog.text
    assert "Regional variants and pricing" in global_detail.text
    assert "European Kit" in global_detail.text
    assert "Standard Kit" in global_detail.text
    assert '<th scope="col">Region</th>' in global_detail.text
    assert invalid.status_code == 422
