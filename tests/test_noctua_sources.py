import json
from pathlib import Path

import httpx
import pytest

from makersfridge.models import AssetKind, RightsStatus, utc_now
from makersfridge.suppliers.adapters import ADAPTERS
from makersfridge.suppliers.catalog import PilotCatalog

ROOT = Path(__file__).parents[1]
EVIDENCE = json.loads((ROOT / "tests/fixtures/suppliers/noctua-reviewed-sources.json").read_text())


@pytest.mark.parametrize("slug", list(EVIDENCE["products"]))
def test_noctua_reference_matches_reviewed_size_and_public_cad(slug: str) -> None:
    specs = PilotCatalog.model_validate_json(
        (ROOT / "config/supplier-sources/noctua.json").read_text()
    ).products
    spec = next(spec for spec in specs if spec.id == f"noctua-{slug}")
    reviewed = EVIDENCE["products"][slug]

    def no_network(request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"reference metadata unexpectedly fetched a shop: {request.url}")

    with httpx.Client(transport=httpx.MockTransport(no_network)) as client:
        product = ADAPTERS[spec.source_kind].fetch(spec, client, utc_now())

    assert product.supplier_id == "noctua" and product.manufacturer == "Noctua"
    assert reviewed["part_number"] in product.part_numbers
    assert product.skus == [] and product.variants == [] and product.offers == []
    assert product.hardware_revision is None
    assert product.specifications["Frame dimensions (without pads)"] == reviewed["frame"]
    assert product.specifications["Dimensions (with pads)"] == reviewed["padded"]
    assert product.specifications["Mounting hole spacing"] == reviewed["mounting_pitch"]
    assert product.specifications["Rated voltage"] == "12 V"
    assert "generic-reference" not in product.tags
    assert {"pc", "nas", "fan", "manufacturer-reference"}.issubset(product.tags)
    archive = next(asset for asset in product.assets if asset.kind == AssetKind.ARCHIVE)
    assert str(archive.source_url) == reviewed["download_url"]
    assert archive.original_filename == reviewed["archive_filename"]
    assert archive.rights_status == RightsStatus.RESTRICTED
    assert str(archive.license_url) == EVIDENCE["cad_policy_url"]
    assert "performance simulation" in product.description_text
    assert "3D printing" in product.description_text
    assert "reference" in product.description_text


def test_noctua_nine_centimetre_class_does_not_claim_a_90mm_frame() -> None:
    specs = PilotCatalog.model_validate_json(
        (ROOT / "config/supplier-sources/noctua.json").read_text()
    ).products
    spec = next(spec for spec in specs if spec.id == "noctua-nf-a9-pwm")
    assert "92 mm" in spec.name
    assert "90 mm class" in spec.compatibility_notes
    assert "not a 90 mm frame" in spec.compatibility_notes
    assert spec.specifications["Frame dimensions (without pads)"] == "92 x 92 x 25 mm"


def test_noctua_references_keep_download_and_policy_documentation_links() -> None:
    specs = PilotCatalog.model_validate_json(
        (ROOT / "config/supplier-sources/noctua.json").read_text()
    ).products
    for spec in specs:
        urls = {str(url) for url in spec.documentation_urls}
        assert f"{spec.product_url}/downloads" in urls
        assert f"{spec.product_url}/specifications" in urls
        assert EVIDENCE["cad_policy_url"] in urls
        assert spec.review_status == "reviewed-manufacturer-reference"
        assert spec.reviewed_at == EVIDENCE["reviewed_at"]
