from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import os
import sys
from pathlib import Path
from typing import Any

import pytest

SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "skills/makers-supply-cad/scripts/solidcraft_bearing_housing.py"
)
SPEC = importlib.util.spec_from_file_location("solidcraft_adapter", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
adapter = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(adapter)


@pytest.fixture
def reference(tmp_path: Path) -> Path:
    root = tmp_path / "reference"
    root.mkdir()
    data = b"ISO-10303-21;\nENDSEC;\n"
    (root / "bearing.stp").write_bytes(data)
    product = {
        "id": adapter.PRODUCT_ID,
        "variants": [
            {
                "region": "eu",
                "part_number": "EA028",
                "title": "608ZZ (2PCS)",
                "variant_id": "eu-variant",
            }
        ],
        "source_tables": [
            {
                "headers": ["ID", "Type", "Inside Diameter", "Outer Diameter", "Width"],
                "rows": [["EA028", "608ZZ", "8", "22", "7"]],
            }
        ],
    }
    asset = {
        "id": adapter.ASSET_ID,
        "verified": True,
        "package_path": "bearing.stp",
        "sha256": hashlib.sha256(data).hexdigest(),
        "size": len(data),
        "rights_status": "unknown",
    }
    (root / "product.json").write_text(json.dumps(product))
    (root / "manifest.json").write_text(
        json.dumps(
            {
                "format": "makers-supply-cad",
                "product_id": adapter.PRODUCT_ID,
                "assets": [asset],
            }
        )
    )
    return root


def test_verified_reference_keeps_rights_and_dimensions(reference: Path) -> None:
    product, asset, path = adapter.load_reference(reference)
    assert asset["rights_status"] == "unknown"
    assert product["source_tables"][0]["rows"][0][2:5] == ["8", "22", "7"]
    assert path.read_bytes().startswith(b"ISO-")


@pytest.mark.parametrize("failure", ["hash", "escape", "dimensions", "pack"])
def test_bad_reference_rejected_before_cad_execution(reference: Path, failure: str) -> None:
    if failure == "hash":
        (reference / "bearing.stp").write_bytes(b"changed")
    elif failure == "escape":
        outside = reference.parent / "outside.stp"
        outside.write_bytes((reference / "bearing.stp").read_bytes())
        (reference / "bearing.stp").unlink()
        (reference / "bearing.stp").symlink_to(outside)
    else:
        product = adapter.read_json(reference / "product.json")
        if failure == "dimensions":
            product["source_tables"][0]["rows"][0][3] = "12.7"
        else:
            product["variants"][0]["title"] = "Different pack"
        adapter.write_json(reference / "product.json", product)
    with pytest.raises(adapter.IntegrationError):
        adapter.load_reference(reference)


def test_existing_and_dangling_outputs_are_not_overwritten(reference: Path, tmp_path: Path) -> None:
    for dangling in [False, True]:
        output = tmp_path / f"output-{dangling}"
        if dangling:
            output.symlink_to(tmp_path / "absent")
        else:
            output.mkdir()
            (output / "keep.txt").write_text("keep")
        with pytest.raises(adapter.IntegrationError, match="new directory"):
            adapter.build("missing-cli", reference, output)
        assert output.is_symlink() if dangling else (output / "keep.txt").read_text() == "keep"


def test_failed_runtime_cleans_temporary_output(
    reference: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(*args: Any) -> str:
        raise adapter.IntegrationError("Runtime failed")

    monkeypatch.setattr(adapter, "run_cli", fail)
    with pytest.raises(adapter.IntegrationError, match="Runtime failed"):
        adapter.build(sys.executable, reference, tmp_path / "output")
    assert not (tmp_path / "output").exists()
    assert not list(tmp_path.glob(".solidcraft-housing-*"))


@pytest.fixture
def measurement() -> dict[str, Any]:
    return {
        "body_count": 3,
        "bodies": [
            {
                "name": "Housing",
                "closed": True,
                "volume_mm3": 7133.203766332575,
                "bbox": {"min": [-22, -16, 0], "max": [22, 16, 12]},
            },
            {
                "name": "Reference 1",
                "closed": True,
                "bbox": {"min": [-11, -11, 4.8], "max": [11, 11, 11.8]},
            },
            {
                "name": "Reference 2",
                "closed": True,
                "bbox": {"min": [-6.333, -6.333, 4.8], "max": [6.333, 6.333, 11.8]},
            },
        ],
    }


@pytest.mark.parametrize("failure", ["open", "volume", "local_coordinates", "translated_xy"])
def test_wrong_geometry_does_not_pass_measurement(
    measurement: dict[str, Any],
    failure: str,
) -> None:
    adapter.validate_measure(measurement)
    bad = copy.deepcopy(measurement)
    if failure == "open":
        bad["bodies"][1]["closed"] = False
    elif failure == "volume":
        bad["bodies"][0]["volume_mm3"] = 8000
    elif failure == "local_coordinates":
        bad["bodies"][1]["bbox"] = {"min": [-3.5, -11, -11], "max": [3.5, 11, 11]}
    else:
        for side in ["min", "max"]:
            bad["bodies"][1]["bbox"][side][0] += 50
    with pytest.raises(adapter.IntegrationError):
        adapter.validate_measure(bad)


@pytest.mark.parametrize(
    "field,value",
    [
        ("unchecked", ["pair"]),
        ("pairs_not_checked", 1),
        ("truncated", True),
        ("budget_exceeded", True),
        ("checked", 2),
    ],
)
def test_incomplete_interference_is_not_a_clean_fit(field: str, value: Any) -> None:
    result = {"checked": 3, "count": 0, "interferences": [], field: value}
    with pytest.raises(adapter.IntegrationError, match="complete"):
        adapter.validate_interference(result)


def test_negative_control_must_find_housing_overlap() -> None:
    result = {"checked": 3, "count": 0, "interferences": []}
    adapter.validate_interference(result)
    with pytest.raises(adapter.IntegrationError, match="negative control"):
        adapter.validate_interference(result, negative=True)
    result.update(count=1, interferences=[{"a": "Housing", "b": "Reference 1", "volume": 46.16}])
    adapter.validate_interference(result, negative=True)


@pytest.mark.parametrize(
    "result",
    [
        {"warnings": ["Incomplete STEP"]},
        {"timeline": [{"error": "Failed feature"}]},
        {"timeline": [{"warning": "Boolean retry"}]},
    ],
)
def test_import_or_feature_warnings_fail_validation(result: dict[str, Any]) -> None:
    with pytest.raises(adapter.IntegrationError):
        adapter.validate_health([result])


@pytest.mark.skipif(
    not (os.environ.get("SOLIDCRAFT_CLI") and os.environ.get("SOLIDCRAFT_REFERENCE")),
    reason="Optional integration requires released CLI and hydrated EA028 export",
)
def test_real_solidcraft_end_to_end(tmp_path: Path) -> None:
    result = adapter.build(
        os.environ["SOLIDCRAFT_CLI"], Path(os.environ["SOLIDCRAFT_REFERENCE"]), tmp_path / "housing"
    )
    assert result["passed"] is True
    evidence = adapter.read_json(tmp_path / "housing/validation.json")
    assert evidence["solidcraft_version"].startswith("solidcraft-cli ")
    assert evidence["interference"]["checked"] == 3
    assert evidence["step_reimport"]["body_count"] == 1
    assert all(
        (tmp_path / "housing" / entry["name"]).stat().st_size > 0 for entry in evidence["exports"]
    )
