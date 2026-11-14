from __future__ import annotations

import hashlib
import importlib.util
import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

from makers_supply.database import build_database
from makers_supply.models import Product
from makers_supply.storage import Catalog, canonical_json

SCRIPT = Path(__file__).resolve().parents[1] / "skills/makers-supply-cad/scripts/catalog.py"
SPEC = importlib.util.spec_from_file_location("agent_catalog", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
agent_catalog = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(agent_catalog)


@pytest.fixture
def archive(tmp_path: Path) -> tuple[Path, dict[str, Any]]:
    root = tmp_path / "catalog"
    products = root / "data/products"
    products.mkdir(parents=True)
    content = b"ISO-10303-21;\nENDSEC;\n"
    blob = root / "data/blobs/bearing.stp"
    blob.parent.mkdir(parents=True)
    blob.write_bytes(content)
    timestamp = "2026-11-14T00:00:00Z"
    product = Product.model_validate(
        {
            "id": "bearing-608",
            "name": "608 Bearing",
            "part_numbers": ["EA028"],
            "specifications": {"Outside diameter": "22 mm"},
            "first_seen": timestamp,
            "last_seen": timestamp,
            "measurements": [
                {
                    "label": "Bore",
                    "raw_value": "8 mm",
                    "numeric_value": "8",
                    "unit": "mm",
                    "provenance": {"kind": "page_table", "reference": "Dimensions"},
                }
            ],
            "offers": [
                {
                    "region": "eu",
                    "url": "https://example.com/bearing",
                    "currency": "EUR",
                    "price": "4.50",
                    "retrieved_at": timestamp,
                }
            ],
            "variants": [
                {
                    "region": "eu",
                    "variant_id": "variant-ea028",
                    "title": "608ZZ P5",
                    "part_number": "EA028",
                    "sku": "SKU-608",
                    "price": "4.50",
                    "currency": "EUR",
                }
            ],
            "assets": [
                {
                    "id": "model-bearing",
                    "kind": "model",
                    "original_filename": "Bearing EA028.stp",
                    "media_type": "application/step",
                    "source_url": "https://example.com/bearing.stp",
                    "blob_path": "data/blobs/bearing.stp",
                    "sha256": hashlib.sha256(content).hexdigest(),
                    "size": len(content),
                    "retrieved_at": timestamp,
                    "rights_status": "unknown",
                }
            ],
        }
    )
    record = json.loads(product.model_dump_json())
    (products / "bearing-608.json").write_text(canonical_json(record))
    inactive = {**record, "id": "bearing-inactive", "active": False}
    (products / "bearing-inactive.json").write_text(canonical_json(inactive))
    return root, record


def invoke(capsys: pytest.CaptureFixture[str], *args: str) -> tuple[int, Any, str]:
    code = agent_catalog.main(list(args))
    captured = capsys.readouterr()
    return code, json.loads(captured.out) if captured.out else None, captured.err


def test_search_json_and_sqlite_preserve_metadata(
    archive: tuple[Path, dict[str, Any]],
    capsys: pytest.CaptureFixture[str],
) -> None:
    root, _ = archive
    database = root / "catalog.sqlite"
    build_database(Catalog(root), database)
    results = []
    for path in (root, database):
        code, result, error = invoke(
            capsys,
            "--catalog",
            str(path),
            "search",
            "BEARING ea028 22",
            "--region",
            "eu",
            "--limit",
            "1",
        )
        assert code == 0, error
        assert result["total"] == 1
        assert result["items"][0]["offers"][0]["price"] == "4.50"
        assert result["items"][0]["offers"][0]["retrieved_at"].startswith("2026-11-14")
        assert result["items"][0]["variants"][0]["variant_id"] == "variant-ea028"
        offer = result["items"][0]["offers"][0]
        offer["retrieved_at"] = datetime.fromisoformat(offer["retrieved_at"]).isoformat()
        results.append(result)
    assert results[0] == results[1]
    code, result, _ = invoke(capsys, "--catalog", str(root), "search", "bearing", "--region", "us")
    assert code == 0 and result["total"] == 0
    code, result, _ = invoke(capsys, "--catalog", str(root), "search", "bearing * ea028")
    assert code == 0 and result["total"] == 0


def test_show_json_and_sqlite_keep_provenance(
    archive: tuple[Path, dict[str, Any]],
    capsys: pytest.CaptureFixture[str],
) -> None:
    root, _ = archive
    database = root / "catalog.sqlite"
    build_database(Catalog(root), database)
    before_hash = hashlib.sha256(database.read_bytes()).hexdigest()
    before_mtime = database.stat().st_mtime_ns
    before_entries = set(root.iterdir())
    for path in (root, database):
        code, product, error = invoke(capsys, "--catalog", str(path), "show", "bearing-608")
        assert code == 0, error
        assert product["measurements"][0]["provenance"]["reference"] == "Dimensions"
        assert product["measurements"][0]["raw_value"] == "8 mm"
        assert product["assets"][0]["availability"] == "available"
        assert Path(product["assets"][0]["local_path"]).read_bytes().startswith(b"ISO-")
    assert hashlib.sha256(database.read_bytes()).hexdigest() == before_hash
    assert database.stat().st_mtime_ns == before_mtime
    assert set(root.iterdir()) == before_entries


def test_portable_directory_search_show_and_export(
    archive: tuple[Path, dict[str, Any]],
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    root, product = archive
    portable = tmp_path / "portable"
    portable.mkdir()
    database = portable / "catalog.sqlite"
    build_database(Catalog(root), database)
    named_path = "assets/bearing-608/Models/Bearing EA028.stp"
    model = portable / named_path
    model.parent.mkdir(parents=True)
    model.write_bytes((root / product["assets"][0]["blob_path"]).read_bytes())
    with sqlite3.connect(database) as connection:
        connection.execute("UPDATE assets SET blob_path=?", (named_path,))
    code, found, error = invoke(
        capsys,
        "--catalog",
        str(portable),
        "search",
        "ea028",
        "--region",
        "eu",
    )
    assert code == 0, error
    assert found["items"][0]["id"] == "bearing-608"
    code, detailed, error = invoke(
        capsys,
        "--catalog",
        str(portable),
        "show",
        "bearing-608",
    )
    assert code == 0, error
    assert detailed["assets"][0]["local_path"] == str(model)
    assert detailed["assets"][0]["availability"] == "available"
    output = tmp_path / "portable-handoff"
    code, _, error = invoke(
        capsys,
        "--catalog",
        str(portable),
        "export",
        "bearing-608",
        "--asset-id",
        "model-bearing",
        "--output",
        str(output),
    )
    assert code == 0, error
    manifest = json.loads((output / "manifest.json").read_text())
    entry = manifest["assets"][0]
    assert (output / entry["package_path"]).read_bytes() == model.read_bytes()
    assert entry["rights_status"] == "unknown"


@pytest.mark.parametrize("failure", ["json_syntax", "json_shape", "unsupported_db"])
def test_invalid_catalog_reports_concise_error(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    failure: str,
) -> None:
    if failure == "unsupported_db":
        catalog = tmp_path / "unsupported.sqlite"
        sqlite3.connect(catalog).close()
    else:
        catalog = tmp_path / "catalog"
        products = catalog / "data/products"
        products.mkdir(parents=True)
        (products / "broken.json").write_text("{" if failure == "json_syntax" else "[]")
    code, result, error = invoke(capsys, "--catalog", str(catalog), "search", "bearing")
    assert code == 1 and result is None
    assert error.startswith("catalog: ") and "Traceback" not in error


def test_export_verified_files_and_provenance(
    archive: tuple[Path, dict[str, Any]],
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    root, product = archive
    output = tmp_path / "handoff"
    code, result, error = invoke(
        capsys,
        "--catalog",
        str(root),
        "export",
        "bearing-608",
        "--asset-id",
        "model-bearing",
        "--output",
        str(output),
    )
    assert code == 0, error
    assert result["files"] == 1
    manifest = json.loads((output / "manifest.json").read_text())
    entry = manifest["assets"][0]
    copied = output / entry["package_path"]
    assert copied.name == "Bearing EA028.stp"
    assert hashlib.sha256(copied.read_bytes()).hexdigest() == entry["sha256"]
    assert entry["source_url"] == product["assets"][0]["source_url"]
    assert entry["rights_status"] == "unknown"
    assert (
        json.loads((output / "product.json").read_text())["variants"][0]["part_number"] == "EA028"
    )
    assert (root / "data/blobs/bearing.stp").read_bytes() == copied.read_bytes()


@pytest.mark.parametrize(
    "failure", ["hash", "size", "pointer", "traversal", "symlink", "missing", "rejected"]
)
def test_export_fails_without_partial_output(
    archive: tuple[Path, dict[str, Any]],
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    failure: str,
) -> None:
    root, product = archive
    asset = product["assets"][0]
    blob = root / asset["blob_path"]
    if failure == "hash":
        blob.write_bytes(b"wrong bytes")
    elif failure == "size":
        asset["size"] += 1
    elif failure == "pointer":
        blob.write_bytes(agent_catalog.LFS_HEADER + b"\noid sha256:123\nsize 456\n")
        # A pointer remains unusable even if its own bytes match the recorded hash.
        asset.update(sha256=hashlib.sha256(blob.read_bytes()).hexdigest(), size=blob.stat().st_size)
    elif failure == "traversal":
        asset["blob_path"] = "../outside.stp"
    elif failure == "symlink":
        outside = tmp_path / "outside.stp"
        outside.write_bytes(blob.read_bytes())
        blob.unlink()
        blob.symlink_to(outside)
    elif failure == "missing":
        blob.unlink()
    elif failure == "rejected":
        asset["rejection_reason"] = "Rejected by archive policy"
    (root / "data/products/bearing-608.json").write_text(canonical_json(product))
    output = tmp_path / "handoff"
    code, result, error = invoke(
        capsys,
        "--catalog",
        str(root),
        "export",
        "bearing-608",
        "--asset-id",
        "model-bearing",
        "--output",
        str(output),
    )
    assert code == 1 and result is None and error.startswith("catalog: ")
    assert not output.exists()
    assert not list(tmp_path.glob(".handoff-*"))


def test_existing_output_is_never_overwritten(
    archive: tuple[Path, dict[str, Any]],
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    root, _ = archive
    output = tmp_path / "handoff"
    output.mkdir()
    sentinel = output / "keep.txt"
    sentinel.write_text("keep")
    code, _, error = invoke(
        capsys,
        "--catalog",
        str(root),
        "export",
        "bearing-608",
        "--asset-id",
        "model-bearing",
        "--output",
        str(output),
    )
    assert code == 1 and "already exists" in error
    assert sentinel.read_text() == "keep"
    assert list(output.iterdir()) == [sentinel]
