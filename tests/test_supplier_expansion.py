import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from makersfridge.models import RightsStatus, utc_now
from makersfridge.storage import snapshot_identity
from makersfridge.suppliers import SUPPLIERS
from makersfridge.suppliers.adapters import reference_product
from makersfridge.suppliers.catalog import (
    PilotAsset,
    load_pilots,
    load_pilots_snapshot,
)


def write_manifest(path: Path, **values: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"schema_version": 1, "products": [], **values}))


def board(supplier: str = "raspberry-pi") -> dict[str, object]:
    return {
        "id": f"{supplier}-test-board",
        "supplier_id": supplier,
        "manufacturer": SUPPLIERS[supplier],
        "name": "Reference board",
        "product_url": "https://example.com/board",
        "source_kind": "reference",
        "tags": ["microcontroller", "esp32"],
        "specifications": {"Form factor": "Complete development board"},
    }


def test_official_manufacturers_and_reference_metadata_are_supported(tmp_path: Path) -> None:
    path = tmp_path / "supplier-pilots.json"
    write_manifest(path, includes=["sources/boards.json"])
    write_manifest(tmp_path / "sources/boards.json", products=[board(), board("espressif")])
    products = load_pilots(path)
    assert len(products) == 2
    product = reference_product(products[1], utc_now())
    assert product.manufacturer == "Espressif Systems"
    assert "esp32" in product.tags
    assert product.specifications["Form factor"] == "Complete development board"
    assert not product.offers


@pytest.mark.parametrize("include", ["../outside.json", "/tmp/outside.json", "..\\outside.json"])
def test_source_includes_cannot_escape_configuration(tmp_path: Path, include: str) -> None:
    path = tmp_path / "supplier-pilots.json"
    write_manifest(path, includes=[include])
    with pytest.raises(ValueError, match="include"):
        load_pilots(path)


def test_source_includes_reject_duplicates_cycles_and_symlink_escape(tmp_path: Path) -> None:
    path = tmp_path / "config/supplier-pilots.json"
    child = tmp_path / "config/sources/boards.json"
    write_manifest(path, products=[board()], includes=["sources/boards.json"])
    write_manifest(child, products=[board()])
    with pytest.raises(ValueError, match="unique"):
        load_pilots(path)
    write_manifest(child, includes=["supplier-pilots.json"])
    with pytest.raises(ValueError, match="include"):
        load_pilots(path)
    external = tmp_path / "outside.json"
    write_manifest(external, products=[board()])
    child.unlink()
    child.symlink_to(external)
    with pytest.raises(ValueError, match="include"):
        load_pilots(path)


def test_resume_identity_covers_nested_source_contents(tmp_path: Path) -> None:
    path = tmp_path / "supplier-pilots.json"
    child = tmp_path / "sources/boards.json"
    write_manifest(path, includes=["sources/boards.json"])
    write_manifest(child, products=[board()])
    first, fingerprint = load_pilots_snapshot(path)
    data = board()
    data["hardware_revision"] = "R2"
    write_manifest(child, products=[data])
    second, updated = load_pilots_snapshot(path)
    assert fingerprint != updated
    assert first[0].hardware_revision is None
    assert second[0].hardware_revision == "R2"


def test_catalog_snapshot_identity_includes_reviewed_source_fragments(tmp_path: Path) -> None:
    path = tmp_path / "config/supplier-pilots.json"
    child = tmp_path / "config/sources/boards.json"
    write_manifest(path, includes=["sources/boards.json"])
    write_manifest(child, products=[board()])
    before = snapshot_identity(tmp_path)
    data = board()
    data["hardware_revision"] = "R2"
    write_manifest(child, products=[data])
    assert snapshot_identity(tmp_path) != before


def test_permissive_design_assets_require_explicit_license_evidence() -> None:
    values = {
        "url": "https://example.com/board.step",
        "filename": "board.step",
        "rights_status": "permissive",
    }
    with pytest.raises(ValidationError, match="license"):
        PilotAsset.model_validate(values)
    asset = PilotAsset.model_validate({**values, "license_url": "https://example.com/license"})
    assert asset.rights_status == RightsStatus.PERMISSIVE
