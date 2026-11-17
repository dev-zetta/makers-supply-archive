"""PC references retain their source identity and source-supplied usage notices."""

from pathlib import Path

from test_archive_metadata import NOW, STEP, archive, bundle_bytes, client_for

from makersfridge.assets import AssetStore, materialize_product
from makersfridge.models import AssetKind, Product, RightsStatus
from makersfridge.storage import Catalog
from makersfridge.suppliers import SUPPLIERS


def test_pc_reference_sources_are_distinct_from_hardware_manufacturers() -> None:
    assert SUPPLIERS["noctua"] == "Noctua"
    assert SUPPLIERS["freecad-library"] == "FreeCAD Parts Library"
    assert SUPPLIERS["generic-pc"] == "Generic PC references"


def test_manufacturer_cad_readme_is_exported_with_restricted_model(tmp_path: Path) -> None:
    terms = b"Manufacturer CAD reference. Read the original usage conditions before use."
    content = bundle_bytes({"fan.stp": STEP, "README.txt": terms})
    source = archive().model_copy(
        update={"rights_status": RightsStatus.RESTRICTED, "hardware_revision": None}
    )
    catalog = Catalog(tmp_path)
    with client_for(content) as client:
        stored, children = AssetStore(catalog, client, tmp_path / ".staging").ingest(source, NOW)
    notice = next(asset for asset in children if asset.original_filename == "README.txt")
    assert notice.kind == AssetKind.DOCUMENT
    assert notice.role == "document"
    assert notice.rights_status == RightsStatus.RESTRICTED
    assert notice.license_url == source.license_url
    assert notice.blob_path and (tmp_path / notice.blob_path).read_bytes() == terms
    catalog.write_product(
        Product(id="fan-reference", name="Fan reference", first_seen=NOW, last_seen=NOW,
                assets=[stored, *children])
    )
    export = tmp_path / "export"
    assert materialize_product(catalog, "fan-reference", export) == 3
    assert next(export.rglob("README.txt")).read_bytes() == terms
