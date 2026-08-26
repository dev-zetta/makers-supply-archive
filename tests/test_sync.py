import io
from pathlib import Path

import httpx
from PIL import Image, ImageDraw

from makers_supply.http import ArchiveHttpClient
from makers_supply.models import Asset, AssetKind, Product, Region, SourceAlias, utc_now
from makers_supply.storage import Catalog
from makers_supply.sync import SyncEngine, SyncOptions

FIXTURES = Path(__file__).parent / "fixtures"


def handler(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/robots.txt":
        return httpx.Response(200, text="User-agent: *\nAllow: /")
    if request.url.path == "/collections/makers-supply":
        return httpx.Response(200, text=(FIXTURES / "collection.html").read_text())
    if request.url.path.endswith("/products/power-board"):
        return httpx.Response(200, text=(FIXTURES / "product.html").read_text())
    if request.url.path.endswith("aggregateGlobalSearchV2"):
        return httpx.Response(
            200,
            json={
                "data": {
                    "productGlobalSearchVOIPage": {
                        "records": [
                            {
                                "id": "123",
                                "seoCode": "power-board",
                                "name": "Power Board",
                                "currency": "USD",
                                "lowerPrice": 5.29,
                                "mediaFiles": [],
                            }
                        ],
                        "total": "1",
                    }
                }
            },
        )
    raise AssertionError(str(request.url))


def test_metadata_sync_is_atomic_and_idempotent(tmp_path: Path) -> None:
    (tmp_path / "config").mkdir()
    (tmp_path / "config/aliases.json").write_text("{}")
    transport = httpx.MockTransport(handler)
    with ArchiveHttpClient(delay=0, transport=transport) as client:
        engine = SyncEngine(tmp_path, client)
        first = engine.run(SyncOptions(regions=(Region.US,), metadata_only=True))
        second = engine.run(SyncOptions(regions=(Region.US,), metadata_only=True))
    assert first.promoted is True
    assert second.promoted is False
    products = Catalog(tmp_path).products()
    assert len(products) == 1
    assert products[0].offers[0].region == Region.US


def test_two_successful_misses_tombstone_product(tmp_path: Path) -> None:
    (tmp_path / "config").mkdir()
    (tmp_path / "config/aliases.json").write_text("{}")
    empty_calls = 0

    def changing_handler(request: httpx.Request) -> httpx.Response:
        nonlocal empty_calls
        if request.url.path.endswith("aggregateGlobalSearchV2"):
            empty_calls += 1
            records = [] if empty_calls > 1 else [{
                "id": "123", "seoCode": "power-board", "name": "Power Board",
                "currency": "USD", "lowerPrice": 5.29, "mediaFiles": []
            }]
            return httpx.Response(200, json={"data": {"productGlobalSearchVOIPage": {
                "records": records, "total": str(len(records))}}})
        return handler(request)

    with ArchiveHttpClient(delay=0, transport=httpx.MockTransport(changing_handler)) as client:
        engine = SyncEngine(tmp_path, client)
        options = SyncOptions(regions=(Region.US,), metadata_only=True)
        engine.run(options)
        engine.run(options)
        engine.run(options)
    assert Catalog(tmp_path).products()[0].active is False


def test_regional_pages_are_isolated(tmp_path: Path) -> None:
    (tmp_path / "config").mkdir()
    (tmp_path / "config/aliases.json").write_text("{}")
    template = (FIXTURES / "product.html").read_text()

    def regional_handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/products/power-board"):
            currency = "EUR" if request.url.host.startswith("eu.") else "USD"
            price = "4.99" if currency == "EUR" else "5.29"
            return httpx.Response(
                200,
                text=template.replace('"price": 5.29', f'"price": {price}').replace(
                    '"priceCurrency": "USD"', f'"priceCurrency": "{currency}"'
                ),
            )
        if request.url.path.endswith("aggregateGlobalSearchV2"):
            currency = "EUR" if request.url.host.startswith("eu-") else "USD"
            return httpx.Response(200, json={"data": {"productGlobalSearchVOIPage": {
                "records": [{"id": "123", "seoCode": "power-board", "name": "Power Board",
                             "currency": currency,
                             "lowerPrice": 4.99 if currency == "EUR" else 5.29,
                             "mediaFiles": []}], "total": "1"}}})
        return handler(request)

    with ArchiveHttpClient(delay=0, transport=httpx.MockTransport(regional_handler)) as client:
        SyncEngine(tmp_path, client).run(
            SyncOptions(regions=(Region.US, Region.EU), metadata_only=True)
        )
    product = Catalog(tmp_path).products()[0]
    assert {(offer.region.value, offer.currency, offer.price) for offer in product.offers} == {
        ("us", "USD", "5.29"), ("eu", "EUR", "4.99")
    }


def test_metadata_sync_preserves_mirrored_assets(tmp_path: Path) -> None:
    (tmp_path / "config").mkdir()
    (tmp_path / "config/aliases.json").write_text("{}")
    timestamp = utc_now()
    existing = Product(
        id="power-board",
        name="Power Board",
        aliases=[SourceAlias(region=Region.US, handle="power-board", product_id="123")],
        assets=[Asset(
            id="mirrored-image", kind=AssetKind.IMAGE,
            source_url="https://example.com/old.png", original_filename="old.png",
            media_type="image/png", sha256="a" * 64, size=3,
            blob_path=f"data/blobs/sha256/aa/{'a' * 64}.png", retrieved_at=timestamp,
        )],
        first_seen=timestamp, last_seen=timestamp,
    )
    catalog = Catalog(tmp_path)
    catalog.write_product(existing)
    blob = tmp_path / str(existing.assets[0].blob_path)
    blob.parent.mkdir(parents=True)
    blob.write_bytes(b"old")
    with ArchiveHttpClient(delay=0, transport=httpx.MockTransport(handler)) as client:
        SyncEngine(tmp_path, client).run(
            SyncOptions(regions=(Region.US,), metadata_only=True)
        )
    assert Catalog(tmp_path).load_product("power-board").assets == existing.assets


def test_binary_sync_generates_and_reuses_normalized_display_images(tmp_path: Path) -> None:
    (tmp_path / "config").mkdir()
    (tmp_path / "config/aliases.json").write_text("{}")
    image = Image.new("RGB", (800, 800), (247, 247, 247))
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, 799, 199), fill=(90, 90, 90))
    encoded = io.BytesIO()
    image.save(encoded, format="PNG")

    def binary_handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith(("board.png", "board-2.png")):
            return httpx.Response(200, content=encoded.getvalue())
        if request.url.path.endswith("board.step"):
            return httpx.Response(200, content=b"ISO-10303-21;\nENDSEC;")
        return handler(request)

    with ArchiveHttpClient(
        delay=0, transport=httpx.MockTransport(binary_handler)
    ) as client:
        engine = SyncEngine(tmp_path, client)
        first = engine.run(SyncOptions(regions=(Region.US,)))
        second = engine.run(SyncOptions(regions=(Region.US,)))

    product = Catalog(tmp_path).products()[0]
    display_images = [asset for asset in product.assets if asset.image_processing]
    assert first.promoted is True
    assert second.promoted is False
    assert len(display_images) == 2
    assert all(asset.image_processing.crop_top == 200 for asset in display_images)
    assert all(asset.parent_asset_id for asset in display_images)
