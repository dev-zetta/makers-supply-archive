from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "skills/makers-supply-cad/scripts"
sys.path.insert(0, str(SCRIPTS))
SPEC = importlib.util.spec_from_file_location(
    "chili3d_adapter", SCRIPTS / "chili3d_bearing_housing.py"
)
assert SPEC and SPEC.loader
adapter = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(adapter)


def measurement() -> dict[str, Any]:
    return {
        "results": {
            "housing_valid": True,
            "housing_solids": {"count": 1},
            "housing_volume": 7133.203766332575,
            "housing_bounds": {
                "min": dict(zip("xyz", [-22, -16, 0], strict=True)),
                "max": dict(zip("xyz", [22, 16, 12], strict=True)),
            },
        }
    }


@pytest.mark.parametrize("failure", ["volume", "invalid", "compound", "bounds"])
def test_wrong_geometry_is_rejected(failure: str) -> None:
    result = measurement()
    if failure == "volume":
        result["results"]["housing_volume"] += 10
    elif failure == "invalid":
        result["results"]["housing_valid"] = False
    elif failure == "compound":
        result["results"]["housing_solids"]["count"] = 2
    else:
        result["results"]["housing_bounds"]["min"]["z"] = -0.2
    with pytest.raises(adapter.IntegrationError):
        adapter.check_measurement(result)


def test_clearance_constraint_drives_a_real_feature_tree() -> None:
    ops = adapter.program()["ops"]
    seat = next(op for op in ops if op["id"] == "seat_profile")
    assert seat["constraints"][1]["datum"] == "seat_radius"
    assert next(op for op in ops if op["id"] == "seat")["depth"] == "seat_depth"
    assert sum(op["op"] == "extrude" for op in ops) == 8
    assert all(op.get("method") not in {"booleanCut", "booleanFuse"} for op in ops)
    assert len(next(op for op in ops if op["id"] == "flange_profile")["entities"]) == 4


def test_successful_bridge_envelope_can_still_contain_tool_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Reply:
        returncode = 0
        stdout = json.dumps({"error": "No active document"})
        stderr = ""

    monkeypatch.setattr(adapter.subprocess, "run", lambda *args, **kwargs: Reply())
    with pytest.raises(adapter.IntegrationError, match="No active document"):
        adapter.call("unused", "run_program", {})


def test_existing_cad_work_is_rejected_before_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = []

    def call(cli: str, tool: str, args: Any) -> dict[str, Any]:
        calls.append(tool)
        return {
            "hasActiveDocument": True,
            "nodes": [{"id": "user-work", "type": "ParametricBodyNode", "shapeKind": "solid"}],
        }

    monkeypatch.setattr(adapter, "call", call)
    with pytest.raises(adapter.IntegrationError, match="isolated document"):
        adapter.build("unused", tmp_path, ["a", "b"])
    assert calls == ["get_document_state"]


def test_failed_verification_restores_baseline_clearance(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "session.json").write_text(
        json.dumps({"body_id": "body", "bearing_node_ids": ["a", "b"]})
    )
    writes = []

    def call(cli: str, tool: str, args: Any) -> dict[str, Any]:
        if tool == "get_document_state":
            return {
                "nodes": [{"id": "body", "type": "ParametricBodyNode"}, {"id": "a"}, {"id": "b"}]
            }
        if tool == "document_variables":
            writes.append(args["variables"][0]["expression"])
            return {}
        raise adapter.IntegrationError("lost connection")

    monkeypatch.setattr(adapter, "call", call)
    with pytest.raises(adapter.IntegrationError, match="lost connection"):
        adapter.verify("unused", tmp_path)
    assert writes == ["0.2", "0.2"]


def test_stale_verification_session_does_not_change_another_document(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "session.json").write_text(
        json.dumps({"body_id": "old-body", "bearing_node_ids": ["a", "b"]})
    )
    calls = []

    def call(cli: str, tool: str, args: Any) -> dict[str, Any]:
        calls.append(tool)
        return {"nodes": [{"id": "unrelated-body", "type": "ParametricBodyNode"}]}

    monkeypatch.setattr(adapter, "call", call)
    with pytest.raises(adapter.IntegrationError, match="no variables changed"):
        adapter.verify("unused", tmp_path)
    assert calls == ["get_document_state"]


def test_missing_export_bytes_are_not_a_saved_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "session.json").write_text(json.dumps({"body_id": "body"}))
    monkeypatch.setattr(adapter, "call", lambda *args: {"ok": True, "bytes": 99})
    with pytest.raises(adapter.IntegrationError, match="browser download"):
        adapter.export_artifacts("unused", tmp_path)
    assert not list(tmp_path.glob("*.step"))


def test_export_verifies_binary_size_and_preserves_existing_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import base64

    (tmp_path / "session.json").write_text(json.dumps({"body_id": "body"}))
    calls = []

    def call(cli: str, tool: str, args: Any) -> dict[str, Any]:
        calls.append(args)
        data = b"ISO-10303-21;\nENDSEC;\n" if args["format"] == ".step" else bytes(84)
        return {"bytes": len(data), "dataBase64": base64.b64encode(data).decode()}

    monkeypatch.setattr(adapter, "call", call)
    receipt = adapter.export_artifacts("unused", tmp_path)
    assert receipt["ea028-housing.stl"]["bytes"] == 84
    assert all(c["returnData"] and c["ids"] == ["body"] for c in calls)
    with pytest.raises(adapter.IntegrationError, match="already exist"):
        adapter.export_artifacts("unused", tmp_path)
    assert len(calls) == 2
