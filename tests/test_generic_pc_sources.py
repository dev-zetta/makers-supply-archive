from pathlib import Path

from makersfridge.models import utc_now
from makersfridge.suppliers.adapters import reference_product
from makersfridge.suppliers.catalog import PilotCatalog

SOURCE = Path(__file__).resolve().parents[1] / "config/supplier-sources/generic-pc.json"
GUIDE = (
    "https://edc.intel.com/content/www/us/en/design/ipla/software-development-platforms/"
    "client/platforms/alder-lake-desktop/"
    "atx-version-3-0-multi-rail-desktop-platform-power-supply-design-guide/2.1a/"
)


def test_generic_psu_references_are_not_manufacturer_products_or_cad_models() -> None:
    catalog = PilotCatalog.model_validate_json(SOURCE.read_bytes())
    assert {spec.id for spec in catalog.products} == {"generic-atx-psu", "generic-sfx-psu"}
    for spec in catalog.products:
        assert spec.supplier_id == "generic-pc"
        assert spec.manufacturer == "Generic reference"
        assert spec.name.startswith("Generic ")
        assert "generic-reference" in spec.tags
        assert spec.review_status == "documentation-only"
        assert not spec.assets
        assert not spec.skus
        assert not spec.part_numbers
        assert not spec.selected_skus
        assert spec.specifications["CAD coverage"] == "Documentation only; no CAD model attached"
        product = reference_product(spec, utc_now())
        assert not product.assets
        assert not product.variants
        assert not product.offers
        assert "cable" in spec.compatibility_notes.lower()
        assert "connector" in spec.compatibility_notes.lower()


def test_psu_reference_dimensions_keep_axes_and_profile_limits_explicit() -> None:
    products = {
        spec.id: spec for spec in PilotCatalog.model_validate_json(SOURCE.read_bytes()).products
    }
    atx = products["generic-atx-psu"]
    assert atx.specifications["Rear face (width x height)"] == "150 x 86 mm (reference dimensions)"
    assert atx.specifications["Reference body depth"] == "140 mm; actual product depths vary"
    assert str(atx.product_url) == GUIDE + "atx12v-specific-guidelines-3-1/"
    sfx = products["generic-sfx-psu"]
    assert sfx.specifications["Reference body (width x depth x height)"] == "125 x 100 x 63.5 mm"
    assert str(sfx.product_url) == GUIDE + "reduced-depth-top-mount-fan-physical/"
    assert GUIDE + "fan-requirements-required_2/" in map(str, sfx.documentation_urls)
    assert "17 mm" in sfx.specifications["Guide profile limitation"]
    assert "SFX-L" in sfx.compatibility_notes
    assert "standard-sfx-profile-package" not in str(sfx.product_url)
