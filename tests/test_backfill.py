import hashlib
import io
import zipfile
from datetime import UTC, datetime
from pathlib import Path

import httpx

from makers_supply.backfill import CachedAssetBackfill
from makers_supply.http import ArchiveHttpClient
from makers_supply.models import AssetKind, Product, Region, SourceAlias
from makers_supply.storage import Catalog


def _model_zip() -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("CAD/motor.step", "ISO-10303-21;\nEND-ISO-10303-21;")
    return output.getvalue()


def test_cached_asset_backfill_downloads_and_extracts_missing_files(tmp_path: Path) -> None:
    catalog = Catalog(tmp_path)
    timestamp = datetime(2026, 1, 2, tzinfo=UTC)
    product = Product(
        id="la024-micro-motor",
        name="Micro Motor",
        aliases=[SourceAlias(region=Region.US, handle="micro-motor")],
        first_seen=timestamp,
        last_seen=timestamp,
    )
    catalog.write_product(product)
    page = """
    <script type="application/ld+json">
    {"@type":"Product","name":"Micro Motor","sku":"LA024",
     "offers":{"url":"https://us.example.com/products/micro-motor",
     "priceCurrency":"USD","price":"4.39"}}
    </script>
    <p class="pct_downloadContent">
      <a href="https://cdn.example.com/motor.pdf">Specification</a>
      <a href="https://cdn.example.com/motor.zip">3D Model</a>
    </p><div class="pct"><p>Compact motor.</p></div>
    """
    page_key = hashlib.sha256(b"us:micro-motor").hexdigest()
    page_path = tmp_path / ".staging/pages" / f"{page_key}.html"
    page_path.parent.mkdir(parents=True)
    page_path.write_text(page, encoding="utf-8")
    archive_bytes = _model_zip()

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nAllow: /")
        if request.url.path == "/motor.pdf":
            return httpx.Response(200, content=b"%PDF-1.4\nfixture")
        if request.url.path == "/motor.zip":
            return httpx.Response(200, content=archive_bytes)
        raise AssertionError(request.url)

    with ArchiveHttpClient(
        delay=0, transport=httpx.MockTransport(handler)
    ) as client:
        result = CachedAssetBackfill(tmp_path, client).run(
            {product.id}, download=True
        )
        repeat = CachedAssetBackfill(tmp_path, client).run({product.id})

    stored = catalog.load_product(product.id)
    assert result.assets_discovered == 2
    assert result.assets_downloaded == 2
    assert result.assets_extracted == 1
    assert result.promoted is True
    assert repeat.assets_discovered == 0
    assert {asset.kind for asset in stored.assets} == {
        AssetKind.ARCHIVE,
        AssetKind.DOCUMENT,
        AssetKind.MODEL,
    }
    assert all(asset.blob_path for asset in stored.assets)
