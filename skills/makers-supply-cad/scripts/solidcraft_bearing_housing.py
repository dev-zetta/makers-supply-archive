#!/usr/bin/env python3
"""Build and check an EA028 bearing housing with an installed SolidCraft CLI."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

PRODUCT_ID = "ea028-high-performance-bearings"
ASSET_ID = "model-3f4ff15eee8cf265bc90"


class IntegrationError(ValueError):
    """The reference or CAD result cannot support this example."""


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            value.update(chunk)
    return value.hexdigest()


def load_reference(reference: Path) -> tuple[dict[str, Any], dict[str, Any], Path]:
    reference = reference.resolve(strict=True)
    product = read_json(reference / "product.json")
    manifest = read_json(reference / "manifest.json")
    if product["id"] != PRODUCT_ID or manifest.get("product_id") != PRODUCT_ID:
        raise IntegrationError("This example requires the EA028 bearing product")
    if manifest.get("format") != "makers-supply-cad":
        raise IntegrationError("Use a verified catalog.py export as --reference")
    variant = next(
        (v for v in product["variants"] if v["region"] == "eu" and v.get("part_number") == "EA028"),
        None,
    )
    if variant is None or "2PCS" not in variant["title"].upper():
        raise IntegrationError("Expected the EU EA028 two-bearing pack")
    table = next(
        (t for t in product["source_tables"] if any(row[0] == "EA028" for row in t["rows"])), None
    )
    if table is None:
        raise IntegrationError("EA028 source dimensions are required")
    row = next(row for row in table["rows"] if row[0] == "EA028")
    if (
        [float(v) for v in row[2:5]] != [8, 22, 7]
        or "Inside Diameter" not in table["headers"][2]
        or "Outer Diameter" not in table["headers"][3]
        or "Width" not in table["headers"][4]
    ):
        raise IntegrationError("This example expects the sourced 8 × 22 × 7 mm EA028")
    asset = next((a for a in manifest["assets"] if a["id"] == ASSET_ID), None)
    if asset is None or not asset.get("verified"):
        raise IntegrationError("The verified EA028 STEP asset is required")
    relative = Path(asset["package_path"])
    source = (reference / relative).resolve(strict=True)
    if relative.is_absolute() or ".." in relative.parts or not source.is_relative_to(reference):
        raise IntegrationError("Reference asset escapes the exported directory")
    if (
        source.stat().st_size != asset["size"]
        or digest(source) != asset["sha256"]
        or source.read_bytes().startswith(b"version https://git-lfs.github.com/spec/v1")
    ):
        raise IntegrationError("EA028 reference failed size/SHA-256 verification")
    return product, asset, source


def command(identifier: str, **params: Any) -> dict[str, Any]:
    return {"command": identifier, "params": params}


def expected_volume(clearance: float = 0.2) -> float:
    return (
        44 * 32 * 4
        + math.pi * 15**2 * 8
        - math.pi * 9**2 * 4.8
        - math.pi * ((22 + clearance) / 2) ** 2 * 7.2
        - 4 * math.pi * 1.7**2 * 4
    )


def build_commands(reference_bodies: list[str]) -> list[dict[str, Any]]:
    parameters = {
        "bearing_bore": "8 mm",
        "bearing_od": "22 mm",
        "bearing_width": "7 mm",
        "diametral_clearance": "0.2 mm",
        "axial_recess": "0.2 mm",
        "plate_length": "44 mm",
        "plate_width": "32 mm",
        "plate_thickness": "4 mm",
        "boss_diameter": "30 mm",
        "boss_height": "8 mm",
        "shaft_relief": "18 mm",
        "mount_diameter": "3.4 mm",
        "mount_x": "17 mm",
        "mount_y": "10 mm",
        "seat_diameter": "bearing_od + diametral_clearance",
        "seat_depth": "bearing_width + axial_recess",
        "seat_floor": "plate_thickness + boss_height - seat_depth",
    }
    steps = [command("parameters.add", name=k, expression=v) for k, v in parameters.items()]
    steps += [
        command(
            "solid.box",
            length="plate_length",
            width="plate_width",
            height="plate_thickness",
            corner=["-plate_length/2", "-plate_width/2", 0],
            body_name="Housing",
            name="Flange",
        ),
        command(
            "solid.cylinder",
            diameter="boss_diameter",
            height="boss_height",
            base=[0, 0, "plate_thickness"],
            operation="join",
            targets=["Housing"],
            name="Boss",
        ),
        command(
            "solid.cylinder",
            diameter="seat_diameter",
            height="seat_depth",
            base=[0, 0, "seat_floor"],
            operation="cut",
            targets=["Housing"],
            name="Seat",
        ),
        command(
            "solid.cylinder",
            diameter="shaft_relief",
            height="plate_thickness + boss_height + 2 mm",
            base=[0, 0, -1],
            operation="cut",
            targets=["Housing"],
            name="Shaft relief",
        ),
    ]
    for sx in [-1, 1]:
        for sy in [-1, 1]:
            steps.append(
                command(
                    "solid.cylinder",
                    diameter="mount_diameter",
                    height="plate_thickness + 2 mm",
                    base=[f"{sx} * mount_x", f"{sy} * mount_y", -1],
                    operation="cut",
                    targets=["Housing"],
                    name=f"Mount {sx},{sy}",
                )
            )
    steps += [
        command("file.insert_step", path="reference/ea028.stp", name="Catalog EA028"),
        command(
            "solid.move",
            bodies=reference_bodies,
            origin=[0, 0, 0],
            axis=[0, 1, 0],
            angle="-90 deg",
            translate=[0, 0, "seat_floor + bearing_width/2"],
            name="Seat both reference solids",
        ),
        command("document.inspect", measure=False),
        command("inspect.measure"),
        command("inspect.interference"),
    ]
    steps += [
        command("file.export", path=f"housing.{extension}", bodies=["Housing"], quality="fine")
        for extension in ["step", "stl", "3mf"]
    ]
    return steps


def validate_health(results: list[dict[str, Any]]) -> None:
    for result in results:
        if result.get("warning") or result.get("warnings"):
            raise IntegrationError(f"SolidCraft warning: {result}")
        for feature in result.get("timeline", []):
            if feature.get("error") or feature.get("warning"):
                raise IntegrationError(f"Unhealthy timeline feature: {feature}")


def validate_measure(
    measure: dict[str, Any], clearance: float = 0.2, references: bool = True
) -> None:
    bodies = measure["bodies"]
    expected_count = 3 if references else 1
    if measure["body_count"] != expected_count or len(bodies) != expected_count:
        raise IntegrationError(f"Expected {expected_count} complete solid bodies")
    housing = next(
        (b for b in bodies if b["name"] == "Housing"), bodies[0] if not references else None
    )
    if housing is None or not all(b.get("closed") is True for b in bodies):
        raise IntegrationError("Housing or bearing has an open/incomplete body")
    if not math.isclose(housing["volume_mm3"], expected_volume(clearance), rel_tol=0.0001):
        raise IntegrationError("Housing volume does not match the independent analytic solid")
    for side, expected in [("min", [-22, -16, 0]), ("max", [22, 16, 12])]:
        if any(abs(a - b) > 0.005 for a, b in zip(housing["bbox"][side], expected, strict=True)):
            raise IntegrationError("Housing world bounds do not match 44 × 32 × 12 mm")
    if references:
        for body in bodies:
            if body is housing:
                continue
            box = body["bbox"]
            if abs(box["min"][2] - 4.8) > 0.005 or abs(box["max"][2] - 11.8) > 0.005:
                raise IntegrationError("Bearing world placement is not on the shoulder")
            if any(abs(box["min"][i] + box["max"][i]) > 0.005 for i in [0, 1]):
                raise IntegrationError("Bearing world axis is not centered on the housing")
        reference_bodies = [b for b in bodies if b is not housing]
        for side, reference_expected in [("min", [-11, -11, 4.8]), ("max", [11, 11, 11.8])]:
            aggregate = [
                (min if side == "min" else max)(b["bbox"][side][i] for b in reference_bodies)
                for i in range(3)
            ]
            if any(abs(a - b) > 0.005 for a, b in zip(aggregate, reference_expected, strict=True)):
                raise IntegrationError(
                    "Bearing world envelope does not match the sourced dimensions"
                )


def validate_interference(result: dict[str, Any], negative: bool = False) -> None:
    if (
        result.get("unchecked")
        or result.get("pairs_not_checked")
        or result.get("truncated")
        or result.get("budget_exceeded")
        or result.get("checked") != 3
    ):
        raise IntegrationError("SolidCraft did not complete all three assembly interference pairs")
    overlaps = result["interferences"]
    housing_overlap = any(p.get("a") == "Housing" or p.get("b") == "Housing" for p in overlaps)
    if negative and not housing_overlap:
        raise IntegrationError(
            "Undersized-seat negative control did not detect housing interference"
        )
    if not negative and (result.get("count") != 0 or overlaps):
        raise IntegrationError("Bearing intersects the nominal housing")


def run_cli(cli: str, work: Path, *arguments: str) -> str:
    process = subprocess.run(
        [cli, *arguments], cwd=work, capture_output=True, text=True, timeout=120
    )
    if process.returncode:
        raise IntegrationError(f"SolidCraft failed: {process.stderr.strip()[:2000]}")
    return process.stdout.strip()


def run_script(
    cli: str,
    work: Path,
    name: str,
    steps: list[dict[str, Any]],
    source: str | None = None,
    save: str | None = None,
) -> list[dict[str, Any]]:
    write_json(work / f"{name}.json", {"commands": steps})
    arguments = [
        "run",
        f"{name}.json",
        "--param-check",
        "strict",
        "--results",
        "--json-out",
        f"{name}-results.json",
    ]
    if source:
        arguments += ["--in", source]
    if save:
        arguments += ["--save", save]
    run_cli(cli, work, *arguments)
    results: list[dict[str, Any]] = read_json(work / f"{name}-results.json")
    validate_health(results)
    return results


def build(cli: str, reference: Path, output: Path) -> dict[str, Any]:
    output = output.absolute()
    if output.exists() or output.is_symlink():
        raise IntegrationError("Output must be a new directory")
    if not output.parent.is_dir():
        raise IntegrationError("Output parent must already exist")
    product, asset, source = load_reference(reference)
    executable = shutil.which(cli)
    if executable is None:
        raise IntegrationError(
            "SolidCraft CLI was not found; install it separately or pass its path"
        )
    executable = str(Path(executable).resolve())
    temporary = Path(tempfile.mkdtemp(prefix=".solidcraft-housing-", dir=output.parent))
    try:
        version = run_cli(executable, temporary, "--version")
        (temporary / "reference").mkdir()
        shutil.copyfile(source, temporary / "reference/ea028.stp")
        write_json(temporary / "reference/source-asset.json", asset)
        probe = run_script(
            executable,
            temporary,
            "import-probe",
            [
                command("file.insert_step", path="reference/ea028.stp", name="Catalog EA028"),
                command("inspect.measure"),
            ],
        )
        names = probe[0]["created_bodies"]
        if len(names) != 2 or not all(b["closed"] for b in probe[1]["bodies"]):
            raise IntegrationError("The catalog STEP must import as two closed reference solids")
        source_bodies = probe[1]["bodies"]
        source_sizes = [
            max(b["bbox"]["max"][i] for b in source_bodies)
            - min(b["bbox"]["min"][i] for b in source_bodies)
            for i in range(3)
        ]
        if any(abs(a - b) > 0.005 for a, b in zip(source_sizes, [7, 22, 22], strict=True)):
            raise IntegrationError(
                "EA028 STEP source axis/dimensions differ from the tested example"
            )
        results = run_script(
            executable, temporary, "build", build_commands(names), save="bearing-housing.sc"
        )
        measure = next(r for r in results if "total" in r and "body_count" in r)
        interference = next(r for r in results if "pairs_not_checked" in r)
        validate_measure(measure)
        validate_interference(interference)
        run_cli(executable, temporary, "eval", "housing.step", "--json-out", "step-reimport.json")
        back = read_json(temporary / "step-reimport.json")
        validate_health([back])
        validate_measure(back, references=False)
        variant = run_script(
            executable,
            temporary,
            "clearance-0.4",
            [
                command("parameters.change", name="diametral_clearance", expression="0.4 mm"),
                command("document.inspect", measure=False),
                command("inspect.measure"),
            ],
            source="bearing-housing.sc",
            save="clearance-0.4.sc",
        )
        validate_measure(next(r for r in variant if "body_count" in r), clearance=0.4)
        negative = run_script(
            executable,
            temporary,
            "negative-control",
            [
                command("parameters.change", name="diametral_clearance", expression="-0.2 mm"),
                command("inspect.interference"),
            ],
            source="bearing-housing.sc",
        )
        validate_interference(negative[-1], negative=True)
        variant_record = next(
            v
            for v in product["variants"]
            if v["region"] == "eu" and v.get("part_number") == "EA028"
        )
        write_json(
            temporary / "hardware-bom.json",
            {
                "items": [
                    {
                        "product_id": PRODUCT_ID,
                        "region": "eu",
                        "variant_id": variant_record["variant_id"],
                        "part_number": "EA028",
                        "quantity": 1,
                        "quantity_unit": "pack",
                        "pack_size": 2,
                        "physical_part_quantity": 1,
                        "spare_part_quantity": 1,
                        "source_asset": asset,
                        "dimension_source": next(
                            t
                            for t in product["source_tables"]
                            if any(row[0] == "EA028" for row in t["rows"])
                        ),
                    }
                ]
            },
        )
        evidence = {
            "passed": True,
            "solidcraft_version": version,
            "mode": "released headless CLI, no desktop bridge",
            "reference_sha256": asset["sha256"],
            "measure": measure,
            "interference": interference,
            "step_reimport": back,
            "parameter_variant": variant,
            "negative_control": negative[-1],
            "exports": [
                {
                    "name": f"housing.{ext}",
                    "sha256": digest(temporary / f"housing.{ext}"),
                    "bytes": (temporary / f"housing.{ext}").stat().st_size,
                }
                for ext in ["step", "stl", "3mf"]
            ],
            "limitations": [
                "Prototype clearances; physical fit has not been tested.",
                "The open-top housing has no axial retainer.",
            ],
        }
        write_json(temporary / "validation.json", evidence)
        if output.exists() or output.is_symlink():
            raise IntegrationError("Output appeared during execution")
        temporary.rename(output)
        housing = next(b for b in measure["bodies"] if b["name"] == "Housing")
        return {
            "output": str(output),
            "passed": True,
            "housing_volume_mm3": housing["volume_mm3"],
            "bodies": measure["body_count"],
        }
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--solidcraft-cli", default="solidcraft-cli")
    parser.add_argument("--reference", required=True, type=Path, help="Verified catalog.py export")
    parser.add_argument(
        "--output", required=True, type=Path, help="New directory; parent must exist"
    )
    args = parser.parse_args(argv)
    try:
        print(json.dumps(build(args.solidcraft_cli, args.reference, args.output), indent=2))
        return 0
    except (
        IntegrationError,
        OSError,
        ValueError,
        KeyError,
        TypeError,
        subprocess.TimeoutExpired,
    ) as error:
        print(f"solidcraft housing: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
