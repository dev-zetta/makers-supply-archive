from pathlib import Path

import httpx
import pytest

from makersfridge.models import AssetKind, utc_now
from makersfridge.suppliers.adapters import ADAPTERS
from makersfridge.suppliers.catalog import PilotCatalog

ROOT = Path(__file__).parents[1]


@pytest.mark.parametrize("sku,flash", [("25081", "4 MB"), ("25948", "16 MB")])
def test_waveshare_selects_reviewed_hardware_and_main_image(sku: str, flash: str) -> None:
    specs = PilotCatalog.model_validate_json(
        (ROOT / "config/supplier-sources/waveshare.json").read_text()
    ).products
    spec = next(spec for spec in specs if spec.id == f"waveshare-{sku}")
    fixture = (ROOT / f"tests/fixtures/suppliers/waveshare-expansion-{sku}.html").read_text()

    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == str(spec.product_url)
        return httpx.Response(200, text=fixture)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        product = ADAPTERS[spec.source_kind].fetch(spec, client, utc_now())
    assert product.supplier_id == "waveshare" and product.manufacturer == "Waveshare"
    assert {variant.sku for variant in product.variants} == {sku}
    assert product.offers[0].price is None and product.offers[0].available is None
    assert product.hardware_revision is None
    models = [asset for asset in product.assets if asset.kind != AssetKind.IMAGE]
    assert len(models) == 1 and models[0].hardware_revision is None
    assert models[0].applies_to_skus == [sku]
    images = [asset for asset in product.assets if asset.kind == AssetKind.IMAGE]
    assert len(images) == 1
    assert "/image/560x560/" in str(images[0].source_url)
    assert "/thumbnail/" not in str(images[0].source_url)
    assert product.specifications["Flash"] == flash
    assert {"esp32", "esp32-s3", "development-board"}.issubset(product.tags)


@pytest.mark.parametrize("family", ["rp2040", "rp2350"])
def test_waveshare_raspberry_pi_mcu_boards_stay_waveshare_references(family: str) -> None:
    specs = PilotCatalog.model_validate_json(
        (ROOT / "config/supplier-sources/waveshare.json").read_text()
    ).products
    spec = next(spec for spec in specs if spec.id == f"waveshare-{family}-zero")

    # A source_kind=reference record must not invent a shop offer or fetch one.
    class NoNetwork:
        def get(self, url: str, *, check_robots: bool = True) -> httpx.Response:
            raise AssertionError(f"unexpected network access: {url}")

    product = ADAPTERS[spec.source_kind].fetch(spec, NoNetwork(), utc_now())
    assert product.supplier_id == "waveshare" and product.manufacturer == "Waveshare"
    assert product.offers == [] and product.variants == [] and product.skus == []
    assert product.hardware_revision is None
    assert {"raspberry-pi", family}.issubset(product.tags)
    assert len(product.assets) == 1 and product.assets[0].hardware_revision is None
