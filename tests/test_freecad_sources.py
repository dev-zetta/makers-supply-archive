import json
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from makersfridge.models import AssetKind, RightsStatus, utc_now
from makersfridge.suppliers.adapters import reference_product
from makersfridge.suppliers.catalog import PilotCatalog

ROOT = Path(__file__).parents[1]
PIN = "f5ca01cdcaa2f69b9295a6382719c2d90628780c"
REPOSITORY = "https://github.com/FreeCAD/FreeCAD-library"


@pytest.mark.parametrize(
    "product_id, filename, author, dimensions",
    [
        (
            "freecad-generic-drive-2-5-inch-7mm",
            "2-5inch-Disk-Drive-7mm-SATA.step",
            "MrFreez",
            "100.45 x 69.85 x 7 mm",
        ),
        (
            "freecad-generic-drive-3-5-inch",
            "3-5inch-Disk-Drive-SATA.step",
            "Артём",
            "147 x 102 x 26.1 mm",
        ),
    ],
)
def test_generic_drives_preserve_model_identity_and_attribution(
    product_id: str, filename: str, author: str, dimensions: str
) -> None:
    catalog = PilotCatalog.model_validate_json(
        (ROOT / "config/supplier-sources/freecad-library.json").read_bytes()
    )
    spec = next(item for item in catalog.products if item.id == product_id)
    product = reference_product(spec, utc_now())
    assert product.supplier_id == "freecad-library"
    assert product.manufacturer == "Generic reference"
    assert product.name.startswith("Generic ")
    assert {"generic-reference", "pc", "nas", "sata", "storage"}.issubset(product.tags)
    assert product.offers == [] and product.variants == [] and product.skus == []
    assert product.part_numbers == [] and product.hardware_revision is None
    assert product.specifications["Model author"] == author
    assert product.specifications["Model body dimensions (L x W x H)"] == dimensions
    assert "not a manufacturer" in product.description_text
    assert "CC-BY-3.0" in product.description_text
    assert author in product.description_text
    assert "verify" in product.description_text.lower()
    assert len(product.assets) == 2
    model, license_asset = product.assets
    assert model.kind == AssetKind.MODEL and model.role == "component"
    assert model.original_filename == filename
    assert model.source_repository == REPOSITORY
    assert model.source_commit == PIN
    assert model.source_path == f"Computing/Storage/HDD/{filename}"
    assert str(model.source_url) == (
        f"https://raw.githubusercontent.com/FreeCAD/FreeCAD-library/{PIN}/"
        f"Computing/Storage/HDD/{filename}"
    )
    for asset in product.assets:
        assert asset.rights_status == RightsStatus.LICENSED
        assert str(asset.license_url) == f"{REPOSITORY}/blob/{PIN}/LICENSE-Assets"
        assert asset.applies_to_skus == []
    assert license_asset.kind == AssetKind.DOCUMENT and license_asset.role == "document"
    assert license_asset.source_path == "LICENSE-Assets"


def test_drive_model_dimensions_and_license_discrepancy_are_source_evidence() -> None:
    evidence = json.loads(
        (ROOT / "tests/fixtures/suppliers/freecad-drive-source-review.json").read_text()
    )
    assert evidence["reviewed_commit"] == PIN
    assert evidence["models"]["2.5-inch"]["author"] == "MrFreez"
    assert evidence["models"]["2.5-inch"]["fcstd_license"] == "CC-BY 3.0"
    assert evidence["models"]["3.5-inch"]["author"] == "Артём"
    assert evidence["models"]["3.5-inch"]["fcstd_license"] == "All rights reserved"
    assert evidence["models"]["3.5-inch"]["main_sketch_width_mm"] == 102
    license_text = (ROOT / "tests/fixtures/suppliers/freecad-LICENSE-Assets.txt").read_text()
    assert "every part and every" in license_text
    assert "CC-BY-3.0" in license_text
    specs = PilotCatalog.model_validate_json(
        (ROOT / "config/supplier-sources/freecad-library.json").read_bytes()
    ).products
    three_five = next(spec for spec in specs if spec.id == "freecad-generic-drive-3-5-inch")
    assert "All rights reserved" in three_five.compatibility_notes
    assert "102 mm" in three_five.compatibility_notes
    assert "manufacturer drawing" in three_five.compatibility_notes


@pytest.mark.parametrize("size", ["2.5-inch", "3.5-inch"])
def test_drive_size_metadata_matches_native_document_excerpt(size: str) -> None:
    evidence = json.loads(
        (ROOT / "tests/fixtures/suppliers/freecad-drive-source-review.json").read_text()
    )["models"][size]
    document = ET.fromstring(
        (ROOT / "tests/fixtures/suppliers" / evidence["source_properties_fixture"]).read_bytes()
    )
    license_property = document.find('./Properties/Property[@name="License"]/String')
    assert license_property is not None
    assert license_property.attrib["value"] == evidence["fcstd_license"]
    height_property = document.find(
        './Object[@name="Pad"]/Properties/Property[@name="Length"]/Float'
    )
    assert height_property is not None
    assert float(height_property.attrib["value"]) == pytest.approx(evidence["main_pad_height_mm"])
    edges = document.findall(
        './Object[@name="Sketch"]/Properties/Property[@name="Geometry"]/'
        "GeometryList/Geometry/LineSegment"
    )
    x_values = [float(edge.attrib[key]) for edge in edges for key in ("StartX", "EndX")]
    y_values = [float(edge.attrib[key]) for edge in edges for key in ("StartY", "EndY")]
    x_size, y_size = max(x_values) - min(x_values), max(y_values) - min(y_values)
    assert sorted([x_size, y_size]) == pytest.approx(
        sorted([evidence["main_sketch_length_mm"], evidence["main_sketch_width_mm"]])
    )
