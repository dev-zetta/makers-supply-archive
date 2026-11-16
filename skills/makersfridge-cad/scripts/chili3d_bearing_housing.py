#!/usr/bin/env python3
"""Prepare/build the catalog EA028 housing through the official Chili3D bridge CLI.

The browser owns imports, native saves and downloads. This helper never replaces an
open document, deletes nodes, or feeds a parametric body to a consuming direct op.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import math
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

from solidcraft_bearing_housing import IntegrationError, expected_volume, load_reference, write_json


def variables() -> dict[str, Any]:
    values = {
        "bearing_od": "22",
        "bearing_width": "7",
        "diametral_clearance": "0.2",
        "axial_recess": "0.2",
        "plate_thickness": "4",
        "boss_height": "8",
        "seat_radius": "(bearing_od + diametral_clearance) / 2",
        "seat_depth": "bearing_width + axial_recess",
        "seat_floor": "plate_thickness + boss_height - seat_depth",
    }
    return {
        "action": "set",
        "variables": [
            {"name": name, "type": "length", "expression": value} for name, value in values.items()
        ],
    }


def circle_sketch(
    identifier: str, x: float, y: float, radius: float, expression: str | None = None
) -> dict[str, Any]:
    constraints: list[dict[str, Any]] = [
        {"kind": "Fix", "refs": [{"entity": 1, "point": 0}], "datums": [x, y]},
        {
            "kind": "Radius",
            "refs": [{"entity": 1, "point": 0}],
            "datum": expression if expression is not None else radius,
        },
    ]
    return {
        "op": "sketch",
        "id": identifier,
        "name": identifier,
        "plane": "XY",
        "entities": [{"type": "circle", "params": [x, y, radius]}],
        "constraints": constraints,
    }


def program() -> dict[str, Any]:
    corners = [(-22, -16), (22, -16), (22, 16), (-22, 16), (-22, -16)]
    ops: list[dict[str, Any]] = [
        {
            "op": "sketch",
            "id": "flange_profile",
            "name": "44 x 32 flange",
            "plane": "XY",
            "entities": [
                {"type": "line", "params": [*a, *b]}
                for a, b in zip(corners, corners[1:], strict=False)
            ],
        },
        {
            "op": "extrude",
            "id": "housing",
            "name": "EA028 Housing",
            "sketch": "flange_profile",
            "depth": "plate_thickness",
        },
        circle_sketch("boss_profile", 0, 0, 15),
        {
            "op": "extrude",
            "id": "boss",
            "name": "Boss",
            "body": "housing",
            "sketch": "boss_profile",
            "depth": "boss_height",
            "startOffset": "plate_thickness",
            "operation": "fuse",
        },
        circle_sketch("seat_profile", 0, 0, 11.1, "seat_radius"),
        {
            "op": "extrude",
            "id": "seat",
            "name": "Bearing seat",
            "body": "housing",
            "sketch": "seat_profile",
            "depth": "seat_depth",
            "startOffset": "seat_floor",
            "operation": "cut",
        },
        circle_sketch("shaft_profile", 0, 0, 9),
        {
            "op": "extrude",
            "id": "shaft",
            "name": "Shaft relief",
            "body": "housing",
            "sketch": "shaft_profile",
            "depth": 14,
            "startOffset": -1,
            "operation": "cut",
        },
    ]
    for i, (x, y) in enumerate([(-17, -10), (-17, 10), (17, -10), (17, 10)]):
        key = f"mount_{i + 1}"
        ops.extend(
            [
                circle_sketch(f"{key}_profile", x, y, 1.7),
                {
                    "op": "extrude",
                    "id": key,
                    "name": f"Mount {i + 1}",
                    "body": "housing",
                    "sketch": f"{key}_profile",
                    "depth": 6,
                    "startOffset": -1,
                    "operation": "cut",
                },
            ]
        )
    return {"ops": ops}


def queries(target: str, prefix: str = "housing") -> dict[str, Any]:
    return {
        "ops": [
            {
                "method": f"shape.{method}",
                "id": f"{prefix}_{key}",
                "target": target,
                **({"args": {"subshapeType": "solid"}} if method == "findSubShapes" else {}),
            }
            for method, key in [
                ("volume", "volume"),
                ("boundingBox", "bounds"),
                ("checkShape", "valid"),
                ("findSubShapes", "solids"),
            ]
        ]
    }


def check_measurement(result: dict[str, Any], clearance: float = 0.2) -> None:
    r = result["results"]
    if r["housing_valid"] is not True or r["housing_solids"]["count"] != 1:
        raise IntegrationError("Housing must be one valid solid")
    if not math.isclose(r["housing_volume"], expected_volume(clearance), abs_tol=0.002):
        raise IntegrationError("Housing volume differs from the analytic design")
    bounds = r["housing_bounds"]
    for key, expected in [("min", [-22, -16, 0]), ("max", [22, 16, 12])]:
        actual = bounds[key]
        if not all(
            math.isclose(actual[c], v, abs_tol=0.002) for c, v in zip("xyz", expected, strict=True)
        ):
            raise IntegrationError("Housing bounds differ from the design")


def check_bearing(results: list[dict[str, Any]], placed: bool = False) -> None:
    volumes = sorted(r["results"]["bearing_volume"] for r in results)
    if any(
        not math.isclose(a, b, abs_tol=0.002)
        for a, b in zip(volumes, [461.6404491319798, 938.0812230494548], strict=True)
    ) or any(r["results"]["bearing_valid"] is not True for r in results):
        raise IntegrationError("Imported solids do not match the verified EA028 STEP")
    boxes = [r["results"]["bearing_bounds"] for r in results]
    low = [min(b["min"][c] for b in boxes) for c in "xyz"]
    high = [max(b["max"][c] for b in boxes) for c in "xyz"]
    expected = [-11, -11, 4.8, 11, 11, 11.8] if placed else [-3.5, -11, -11, 3.5, 11, 11]
    if any(
        not math.isclose(a, b, abs_tol=0.002) for a, b in zip(low + high, expected, strict=True)
    ):
        raise IntegrationError("Bearing units/orientation/placement differs from the verified STEP")


def call(cli: str, tool: str, args: dict[str, Any]) -> dict[str, Any]:
    result = subprocess.run(
        [cli, "call", tool, "--json", "-", "--timeout", "120000"],
        input=json.dumps(args),
        text=True,
        capture_output=True,
        timeout=130,
    )
    if result.returncode:
        raise IntegrationError(result.stderr.strip() or result.stdout.strip())
    reply: Any = json.loads(result.stdout)
    # The upstream bridge can return ok=true while a tool's content contains an error.
    if not isinstance(reply, dict) or reply.get("error"):
        raise IntegrationError(f"{tool}: {reply}")
    return reply


def prepare(reference: Path, output: Path) -> dict[str, Any]:
    product, asset, step = load_reference(reference)
    if output.exists() or output.is_symlink():
        raise IntegrationError("Choose a new output directory")
    output.mkdir(parents=True)
    shutil.copy2(step, output / "ea028-reference.stp")
    write_json(output / "variables.json", variables())
    write_json(output / "housing-program.json", program())
    receipt = {
        "product_id": product["id"],
        "variant_id": "48795653767516",
        "region": "eu",
        "part_number": "EA028",
        "parts_used": 1,
        "purchase_packs": 1,
        "parts_per_pack": 2,
        "spare_parts": 1,
        "source_asset": asset,
        "dimensions_mm": [8, 22, 7],
        "dimension_provenance": "source_tables:0 / EA028 row",
        "expected_volume_mm3": expected_volume(),
        "assumptions": {
            "diametral_clearance_mm": 0.2,
            "radial_clearance_mm": 0.1,
            "axial_recess_mm": 0.2,
            "axial_retainer": False,
            "physical_fit_tested": False,
        },
        "source_step_axis": "X; rotate Y -90 degrees then translate Z 8.3 mm",
    }
    write_json(output / "bom.json", receipt)
    return receipt


def build(cli: str, output: Path, reference_ids: list[str]) -> dict[str, Any]:
    if (output / "build-result.json").exists() or (output / "session.json").exists():
        raise IntegrationError("This output already contains a CAD run; choose a new example")
    state = call(cli, "get_document_state", {})
    if not state.get("hasActiveDocument"):
        raise IntegrationError("Create a fresh document and import ea028-reference.stp first")
    # Only the two explicitly selected catalog solids and their import groups may exist.
    shapes = [n for n in state["nodes"] if n.get("shapeKind")]
    if (
        len(reference_ids) != 2
        or len(set(reference_ids)) != 2
        or {n["id"] for n in shapes} != set(reference_ids)
        or any(n["type"] != "GroupNode" for n in state["nodes"] if n not in shapes)
    ):
        raise IntegrationError(
            "Use an isolated document containing only the two imported bearing solids"
        )
    existing_variables = call(cli, "document_variables", {"action": "list"})
    if existing_variables.get("variables"):
        raise IntegrationError("Use a fresh document without existing variables")
    for name in ["parametric-modeling", "shape-query", "modeling-api"]:
        # load_skill returns a string, unlike the regular structured tools.
        loaded = subprocess.run(
            [cli, "call", "load_skill", "--json", "-"],
            input=json.dumps({"name": name}),
            text=True,
            capture_output=True,
            timeout=30,
        )
        if loaded.returncode:
            raise IntegrationError(loaded.stderr)
        (output / f"live-{name}.txt").write_text(loaded.stdout)
    bearing = [call(cli, "run_program", queries(n, "bearing")) for n in reference_ids]
    check_bearing(bearing)
    write_json(output / "bearing-before.json", bearing)
    call(cli, "document_variables", variables())
    result = call(cli, "run_parametric", program())
    write_json(output / "build-result.json", result)
    bodies = result.get("bodies", [])
    if len(bodies) != 1:
        raise IntegrationError(f"Expected one parametric body, got {bodies}")
    body_id = bodies[0]["nodeId"]
    measured = call(cli, "run_program", queries(body_id))
    write_json(output / "measurements.json", measured)
    check_measurement(measured)
    # shape.* queries read node-local geometry in 0.8.0. Bake reference copies
    # with transformedMul; a display-only transform_node would give false checks.
    placed = call(
        cli,
        "run_program",
        {
            "ops": [
                {
                    "method": "transformedMul",
                    "id": f"bearing_placed_{i}",
                    "name": f"Catalog EA028 reference {i + 1}",
                    "args": {
                        "shape": node,
                        "rotate": {"axis": {"x": 0, "y": 1, "z": 0}, "angle": -90},
                        "translate": {"x": 0, "y": 0, "z": 8.3},
                    },
                }
                for i, node in enumerate(reference_ids)
            ]
        },
    )
    placed_ids = [n["nodeId"] for n in placed["created"]]
    for node in reference_ids:
        call(cli, "set_node_visible", {"id": node, "visible": False})
    bearing = [call(cli, "run_program", queries(n, "bearing")) for n in placed_ids]
    check_bearing(bearing, placed=True)
    write_json(output / "bearing-placed.json", bearing)
    write_json(
        output / "session.json",
        {"body_id": body_id, "bearing_node_ids": placed_ids, "original_node_ids": reference_ids},
    )
    return {"body_id": body_id, "volume_mm3": measured["results"]["housing_volume"]}


def verify(cli: str, output: Path) -> dict[str, Any]:
    """Edit the example's clearance, check cloned geometry, then restore the baseline."""
    session = json.loads((output / "session.json").read_text())
    body = session["body_id"]
    nodes = session["bearing_node_ids"]
    state = call(cli, "get_document_state", {})
    current = {node["id"]: node for node in state.get("nodes", [])}
    if (
        current.get(body, {}).get("type") != "ParametricBodyNode"
        or len(nodes) != 2
        or any(node not in current for node in nodes)
    ):
        raise IntegrationError("The active document is not this example; no variables changed")
    reports = {}
    try:
        for value, label in [(0.2, "baseline"), (0.4, "clearance-0.4"), (-0.2, "negative-control")]:
            call(
                cli,
                "document_variables",
                {
                    "action": "set",
                    "variables": [
                        {"name": "diametral_clearance", "type": "length", "expression": str(value)}
                    ],
                },
            )
            measured = call(cli, "run_program", queries(body))
            check_measurement(measured, value)
            overlaps = []
            for node in nodes:
                # Edit-style run_program ops consume inputs. Use explicit geometry COPIES,
                # never the original parametric body or the purchased reference nodes.
                check = call(
                    cli,
                    "run_program",
                    {
                        "ops": [
                            {
                                "method": "transformedMul",
                                "id": "housing_check",
                                "args": {"shape": body, "translate": {"x": 0, "y": 0, "z": 0}},
                            },
                            {
                                "method": "transformedMul",
                                "id": "bearing_check",
                                "args": {"shape": node, "translate": {"x": 0, "y": 0, "z": 0}},
                            },
                            {
                                "method": "booleanCommon",
                                "id": "overlap",
                                "args": {"shape1": ["housing_check"], "shape2": ["bearing_check"]},
                            },
                            {"method": "shape.volume", "id": "overlap_volume", "target": "overlap"},
                        ]
                    },
                )
                overlaps.append(check["results"]["overlap_volume"])
                scratch = next(n["nodeId"] for n in check["created"] if n.get("id") == "overlap")
                call(cli, "delete_node", {"id": scratch})
            expected = 46.1618344883488 if value < 0 else 0
            if not math.isclose(sum(overlaps), expected, abs_tol=0.002):
                raise IntegrationError(f"{label}: unexpected interference {overlaps}")
            reports[label] = {"measurements": measured, "overlap_mm3": sum(overlaps)}
    finally:
        call(
            cli,
            "document_variables",
            {
                "action": "set",
                "variables": [
                    {"name": "diametral_clearance", "type": "length", "expression": "0.2"}
                ],
            },
        )
    check_measurement(call(cli, "run_program", queries(body)))
    features = call(cli, "run_parametric", {"ops": [{"op": "features", "body": body}]})
    chain = features.get("results", {}).get("features", [])
    if len(chain) != 8 or any(
        feature.get("error") or feature.get("suppressed") for feature in chain
    ):
        raise IntegrationError("The eight working housing features did not survive verification")
    write_json(output / "final-features.json", features)
    write_json(output / "verification.json", reports)
    call(cli, "select_nodes", {"nodeIds": [body, *nodes]})
    call(cli, "fit_content", {})
    call(cli, "select_nodes", {"nodeIds": []})
    return reports


def export_artifacts(cli: str, output: Path) -> dict[str, Any]:
    """Read real exporter bytes through the optional local file-transfer patch."""
    session = json.loads((output / "session.json").read_text())
    receipt = {}
    targets = [
        (".step", output / "ea028-housing.step"),
        (".stl binary", output / "ea028-housing.stl"),
    ]
    if any(path.exists() or path.is_symlink() for _, path in targets):
        raise IntegrationError("Export files already exist; preserve them or choose a fresh run")
    for format_name, path in targets:
        result = call(
            cli,
            "export_nodes",
            {
                "ids": [session["body_id"]],
                "format": format_name,
                "filename": path.name,
                "returnData": True,
            },
        )
        if "dataBase64" not in result:
            raise IntegrationError(
                "Export only requested a browser download; install the local export-data patch "
                "or collect and verify the browser download"
            )
        data = base64.b64decode(result["dataBase64"], validate=True)
        if len(data) != result["bytes"] or not data:
            raise IntegrationError("Export byte count differs from the file-transfer receipt")
        if format_name == ".step" and not data.startswith(b"ISO-10303-21;"):
            raise IntegrationError("Exporter did not return a STEP file")
        if format_name == ".stl binary" and (
            len(data) < 84 or len(data) != 84 + 50 * int.from_bytes(data[80:84], "little")
        ):
            raise IntegrationError("Exporter did not return a complete binary STL")
        with path.open("xb") as stream:
            stream.write(data)
        receipt[path.name] = {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
    write_json(output / "exports.json", receipt)
    return receipt


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--mcp-cli", help="Installed official chili3d-mcp executable; requires imported reference"
    )
    parser.add_argument("--bearing-node-id", action="append", default=[])
    parser.add_argument(
        "--export",
        action="store_true",
        dest="export_files",
        help="Save housing-only STEP/STL using the local file-transfer patch",
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help="Check an already built example and restore 0.2 mm clearance",
    )
    args = parser.parse_args()
    try:
        if args.reference:
            prepare(args.reference, args.output)
        elif not args.mcp_cli:
            parser.error("--reference is required when preparing an example")
        if (args.verify or args.export_files) and not args.mcp_cli:
            parser.error("--verify/--export requires --mcp-cli")
        if args.verify:
            print(json.dumps(verify(os.path.abspath(args.mcp_cli), args.output)))
        elif args.export_files:
            print(json.dumps(export_artifacts(os.path.abspath(args.mcp_cli), args.output)))
        elif args.mcp_cli:
            print(
                json.dumps(build(os.path.abspath(args.mcp_cli), args.output, args.bearing_node_id))
            )
        else:
            print(json.dumps({"output": str(args.output.resolve()), "prepared": True}))
    except (IntegrationError, OSError, ValueError, subprocess.TimeoutExpired) as exc:
        parser.exit(1, f"chili3d: {exc}\n")


if __name__ == "__main__":
    main()
