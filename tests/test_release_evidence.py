import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from makers_supply.models import Region, RegionRun, RunManifest
from makers_supply.release_evidence import record_acceptance, verify_acceptance
from makers_supply.storage import snapshot_identity


def receipt(root: Path) -> Path:
    now = datetime.now(UTC)
    manifest = RunManifest(
        started_at=now,
        completed_at=now,
        metadata_only=False,
        regions=[RegionRun(region=r, success=True, products_seen=1) for r in Region],
        products_written=0,
        assets_downloaded=0,
        bytes_downloaded=0,
    )
    path = root / ".staging/last-sync.json"
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(
            {
                "manifest": manifest.model_dump(mode="json"),
                "snapshot_id": snapshot_identity(root),
                "has_changes": False,
                "promoted": False,
                "options": {"metadata_only": False, "dry_run": False, "max_products": None},
            }
        )
    )
    return path


def test_acceptance_requires_full_unchanged_scan_for_current_snapshot(tmp_path: Path) -> None:
    path = receipt(tmp_path)
    output = tmp_path / "reports/acceptance.json"
    record_acceptance(tmp_path, output)
    verify_acceptance(tmp_path, output)
    data = json.loads(path.read_text())
    for field, value in [("has_changes", True), ("promoted", True), ("snapshot_id", "bad")]:
        bad = {**data, field: value}
        path.write_text(json.dumps(bad))
        with pytest.raises(ValueError, match="complete eight-region"):
            record_acceptance(tmp_path, output)
    path.write_text(json.dumps(data))
    data["options"]["max_products"] = 1
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="complete eight-region"):
        record_acceptance(tmp_path, output)
    path.unlink()
    data = json.loads(output.read_text())
    data["verified_at"] = (datetime.now(UTC) - timedelta(days=8)).isoformat()
    output.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="stale"):
        verify_acceptance(tmp_path, output)


def test_failed_region_cannot_be_accepted(tmp_path: Path) -> None:
    path = receipt(tmp_path)
    data = json.loads(path.read_text())
    data["manifest"]["regions"][0]["success"] = False
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="eight-region"):
        record_acceptance(tmp_path, tmp_path / "acceptance.json")


def test_old_scan_cannot_be_recertified_as_fresh(tmp_path: Path) -> None:
    path = receipt(tmp_path)
    data = json.loads(path.read_text())
    data["manifest"]["completed_at"] = (datetime.now(UTC) - timedelta(days=8)).isoformat()
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="complete eight-region"):
        record_acceptance(tmp_path, tmp_path / "acceptance.json")
