"""Legacy OpenBuilds motor CAD must not become universal NEMA or current SKU data."""

import json
import re
from pathlib import Path

import pytest

from makersfridge.models import AssetKind, RightsStatus, utc_now
from makersfridge.suppliers.adapters import reference_product
from makersfridge.suppliers.catalog import PilotCatalog

ROOT = Path(__file__).parents[1]
PIN = "48a8a2bf44ef9818edc2f070c848417938816002"
REPOSITORY = "https://github.com/mirage335/templates-lib-OpenBuilds_STEP"
SOURCE = ROOT / "config/supplier-sources/openbuilds-motors.json"
EVIDENCE = ROOT / "tests/fixtures/suppliers/openbuilds-motors-reviewed-sources.json"
EXCERPTS = ROOT / "tests/fixtures/suppliers/openbuilds-motors-step-excerpts.json"


@pytest.mark.parametrize(
    "product_id, frame, body_length, shaft_diameter, shaft_projection, mount_pitch",
    [
        ("openbuilds-nema17-legacy", "NEMA 17", "48 mm", "5 mm", "24 mm", "31 x 31 mm"),
        ("openbuilds-nema23-legacy", "NEMA 23", "56 mm", "6.35 mm", "20.6 mm", "47.14 x 47.14 mm"),
        (
            "openbuilds-nema23-high-torque-legacy",
            "NEMA 23",
            "86 mm",
            "6.35 mm",
            "20.6 mm",
            "47.14 x 47.14 mm",
        ),
    ],
)
def test_legacy_stepper_models_retain_specific_geometry_and_source_terms(
    product_id: str,
    frame: str,
    body_length: str,
    shaft_diameter: str,
    shaft_projection: str,
    mount_pitch: str,
) -> None:
    specs = PilotCatalog.model_validate_json(SOURCE.read_bytes()).products
    spec = next(item for item in specs if item.id == product_id)
    product = reference_product(spec, utc_now())
    assert product.supplier_id == "openbuilds"
    assert product.manufacturer == "OpenBuilds"
    assert "legacy CAD reference" in product.name
    assert {"stepper-motor", "legacy-reference", "community-mirror"}.issubset(product.tags)
    assert not product.skus and not product.part_numbers and not product.variants
    assert not product.offers and product.hardware_revision is None
    assert product.specifications["Motor frame family"] == frame
    assert product.specifications["Model body length"] == body_length
    assert product.specifications["Model shaft diameter"] == shaft_diameter
    assert product.specifications["Model shaft projection from mounting face"] == shaft_projection
    assert product.specifications["Model mounting-hole pitch"] == mount_pitch
    assert "NEMA" in product.description_text
    assert "not" in product.description_text
    assert "current" in product.description_text
    assert "CC BY-SA 4.0" in product.description_text
    assert len(product.assets) == 2
    model, notice = product.assets
    assert model.kind == AssetKind.MODEL and model.role == "component"
    assert notice.kind == AssetKind.DOCUMENT and notice.role == "document"
    assert model.source_path.startswith("_ref/OpenBuilds_STEP/orig/STEP Parts Library 1.5/")
    for asset in product.assets:
        assert asset.source_repository == REPOSITORY
        assert asset.source_commit == PIN
        assert asset.rights_status == RightsStatus.LICENSED
        assert asset.license_url is not None
        assert asset.applies_to_skus == []


def test_motor_evidence_records_original_exports_and_source_coordinate_measurements() -> None:
    evidence = json.loads(EVIDENCE.read_text())
    assert evidence["source_commit"] == PIN
    assert len(evidence["models"]) == 3
    for model in evidence["models"]:
        assert model["size"] < 250_000
        assert len(model["sha256"]) == 64
        assert model["step_exported_at"].startswith(("2015-", "2016-"))
    assert "OpenBuilds, LLC" in evidence["attribution"]


@pytest.mark.parametrize(
    "product_id",
    [
        "openbuilds-nema17-legacy",
        "openbuilds-nema23-legacy",
        "openbuilds-nema23-high-torque-legacy",
    ],
)
def test_motor_dimensions_derive_from_exact_source_step_entities(product_id: str) -> None:
    evidence = next(
        m for m in json.loads(EVIDENCE.read_text())["models"] if m["product_id"] == product_id
    )
    excerpts = json.loads(EXCERPTS.read_text())
    assert excerpts["source_commit"] == PIN
    model = next(m for m in excerpts["models"] if m["product_id"] == product_id)
    assert model["source_sha256"] == evidence["sha256"]
    assert model["source_path"] == evidence["source_path"]
    entities = {
        int(n): value
        for n, value in re.findall(r"#(\d+)\s*=\s*(.*?);", model["step_entity_excerpt"], re.S)
    }
    roles = model["roles"]
    assert re.search(
        r"SI_UNIT\s*\(\s*\.MILLI\.\s*,\s*\.METRE\.\s*\)", entities[roles["millimetre_unit"]]
    )

    def refs(entity: str) -> list[int]:
        return [int(n) for n in re.findall(r"#(\d+)", entity)]

    def point(number: int) -> list[float]:
        entity = entities[number]
        assert entity.startswith("CARTESIAN_POINT")
        return [float(value) for value in re.search(r",\s*\(([^)]+)\)", entity).group(1).split(",")]

    def vertex(role: str) -> list[float]:
        entity = entities[roles[role]]
        assert entity.startswith("VERTEX_POINT")
        return point(refs(entity)[0])

    def circle(role: str) -> tuple[list[float], float]:
        entity = entities[roles[role]]
        assert entity.startswith("CIRCLE")
        axis = entities[refs(entity)[0]]
        assert axis.startswith("AXIS2_PLACEMENT_3D")
        center = point(refs(axis)[0])
        radius = float(re.search(r",\s*([-\d.E+]+)\s*\)\s*$", entity).group(1))
        return center, radius

    positive, _ = circle("front_hole_positive")
    negative, _ = circle("front_hole_negative")
    shaft_center, radius = circle("shaft_tip_circle")
    assert positive[2] == pytest.approx(negative[2])
    face_z = positive[2]
    assert face_z - vertex("body_rear_vertex")[2] == pytest.approx(evidence["body_length_mm"])
    assert vertex("shaft_tip_vertex")[2] - face_z == pytest.approx(evidence["shaft_tip_z_mm"])
    assert shaft_center[2] == pytest.approx(vertex("shaft_tip_vertex")[2])
    assert 2 * radius == pytest.approx(evidence["shaft_diameter_mm"])
    assert [positive[i] - negative[i] for i in (0, 1)] == pytest.approx(
        [evidence["mount_pitch_mm"], evidence["mount_pitch_mm"]]
    )
