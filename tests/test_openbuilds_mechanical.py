"""Legacy OpenBuilds mechanical CAD retains concrete sizes and source attribution."""

import json
from pathlib import Path

import pytest

from makersfridge.models import AssetKind, RightsStatus, utc_now
from makersfridge.suppliers.adapters import reference_product
from makersfridge.suppliers.catalog import PilotCatalog

ROOT = Path(__file__).parents[1]
PIN = "48a8a2bf44ef9818edc2f070c848417938816002"
REPO = "https://github.com/mirage335/templates-lib-OpenBuilds_STEP"


def mechanical_sources() -> PilotCatalog:
    return PilotCatalog.model_validate_json(
        (ROOT / "config/supplier-sources/openbuilds-mechanical.json").read_bytes()
    )


@pytest.mark.parametrize("profile", ["20x20", "20x40", "20x60", "20x80", "40x80"])
def test_extrusions_are_exact_500mm_reference_models(profile: str) -> None:
    kind = "c-beam" if profile == "40x80" else "v-slot"
    spec = next(
        p for p in mechanical_sources().products if p.id == f"openbuilds-{kind}-{profile}-500mm"
    )
    product = reference_product(spec, utc_now())
    assert profile in product.name and "500 mm" in product.name
    assert product.specifications["CAD length"] == "500 mm"
    assert product.specifications["Profile cross-section"] == profile.replace("x", " x ") + " mm"
    assert "aluminium-extrusion" in product.tags
    assert "other lengths" in product.description_text
    assert "current" in product.description_text
    assert product.offers == [] and product.variants == [] and product.skus == []


@pytest.mark.parametrize(
    "product_id",
    [
        "openbuilds-solid-v-wheel-delrin",
        "openbuilds-delrin-mini-v-wheel",
    ],
)
def test_pom_wheels_are_bare_delrin_components_not_xtreme_kits(product_id: str) -> None:
    spec = next(p for p in mechanical_sources().products if p.id == product_id)
    product = reference_product(spec, utc_now())
    assert product.specifications["Wheel material"] == "Delrin / POM (acetal)"
    assert {"pom", "wheel", "v-slot"}.issubset(product.tags)
    assert "bare wheel" in product.description_text
    assert "polycarbonate" in product.description_text
    assert "bearings" in product.description_text.lower()
    model = next(a for a in product.assets if a.kind == AssetKind.MODEL)
    assert "/2%20-%20Wheels/" in str(model.source_url)
    assert "/Assemblies/" not in str(model.source_url)


def test_all_mechanical_models_are_pinned_licensed_legacy_references() -> None:
    evidence = json.loads(
        (ROOT / "tests/fixtures/suppliers/openbuilds-mechanical-reviewed-sources.json").read_text()
    )
    specs = mechanical_sources().products
    assert len(specs) == 8
    for spec in specs:
        product = reference_product(spec, utc_now())
        assert product.supplier_id == "openbuilds" and product.manufacturer == "OpenBuilds"
        assert product.hardware_revision is None
        assert product.offers == [] and product.variants == [] and product.skus == []
        assert "community-hosted" in product.description_text
        assert "OpenBuilds, LLC" in product.specifications["Attribution"]
        assert "CC-BY-SA-4.0" in product.specifications["CAD license"]
        assert "generic-reference" not in product.tags
        model, license_asset = product.assets
        assert model.kind == AssetKind.MODEL and model.role == "component"
        assert license_asset.kind == AssetKind.DOCUMENT and license_asset.role == "document"
        assert license_asset.original_filename == "OpenBuilds-STEP-Library-LICENSE.txt"
        reviewed = evidence["models"][product.id]
        assert model.source_path == reviewed["source_path"]
        assert reviewed["size"] > 30_000
        assert len(reviewed["sha256"]) == 64
        assert reviewed["step_header"].startswith("ISO-10303-21;")
        for asset in product.assets:
            assert asset.source_repository == REPO and asset.source_commit == PIN
            assert asset.rights_status == RightsStatus.LICENSED
            assert str(asset.license_url) == f"{REPO}/blob/{PIN}/_ref/OpenBuilds_STEP/license.txt"
            assert asset.applies_to_skus == []


def test_eccentric_reference_does_not_merge_six_mm_with_quarter_inch() -> None:
    spec = next(
        p for p in mechanical_sources().products if p.id == "openbuilds-eccentric-spacer-6mm"
    )
    assert spec.specifications["Spacer height"] == "6 mm"
    assert "6.35 mm" in spec.compatibility_notes
    assert "Mini Eccentric" in spec.compatibility_notes
    assert spec.assets[0].filename == "Eccentric Spacer 6mm.step"
