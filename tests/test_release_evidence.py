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


def changed_receipt(root: Path) -> tuple[Path, Path, Path]:
    path = receipt(root)
    data = json.loads(path.read_text())
    data.update(has_changes=True, promoted=True)
    path.write_text(json.dumps(data))
    review = root / "reports/release-reviewed-changes.json"
    review.parent.mkdir()
    review.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "snapshot_id": snapshot_identity(root),
                "full_blob_validation": True,
                "database_reproducible": True,
                "asset_records_unchanged": True,
                "canonical_fields_changed": {"variants": 1},
                "reviewed_variant_changes": [
                    {
                        "product": "part",
                        "region": "eu",
                        "variant_id": "123",
                        "fields": {"available": {"before": True, "after": False}},
                    }
                ],
            }
        )
    )
    return path, review, root / "reports/release-validation.json"


def test_reviewed_live_changes_remain_explicit_and_bound_to_the_review(tmp_path: Path) -> None:
    _, review, output = changed_receipt(tmp_path)
    with pytest.raises(ValueError, match="unchanged"):
        record_acceptance(tmp_path, output)
    record_acceptance(tmp_path, output, reviewed_changes=review)
    data = json.loads(output.read_text())
    assert data["schema_version"] == 2
    assert data["acceptance_policy"] == "reviewed-live-changes"
    assert data["unchanged_repeat"] is False
    assert data["reviewed_changes_receipt"] == review.name
    verify_acceptance(tmp_path, output)
    review.write_text(review.read_text() + "\n")
    with pytest.raises(ValueError, match="checksum"):
        verify_acceptance(tmp_path, output)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("snapshot_id", "another-snapshot"),
        ("full_blob_validation", False),
        ("database_reproducible", False),
        ("asset_records_unchanged", False),
        ("canonical_fields_changed", {"assets": 1}),
        ("reviewed_variant_changes", []),
        ("reviewed_variant_changes", [{"fields": {"image_url": {}}}]),
    ],
)
def test_reviewed_policy_rejects_incomplete_or_structural_review(
    tmp_path: Path, field: str, value: object
) -> None:
    _, review, output = changed_receipt(tmp_path)
    data = json.loads(review.read_text())
    data[field] = value
    review.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="reviewed"):
        record_acceptance(tmp_path, output, reviewed_changes=review)


@pytest.mark.parametrize("failure", ["region", "metadata", "dry_run", "limited", "stale"])
def test_reviewed_policy_keeps_full_scan_requirements(tmp_path: Path, failure: str) -> None:
    source, review, output = changed_receipt(tmp_path)
    data = json.loads(source.read_text())
    if failure == "region":
        data["manifest"]["regions"][0]["success"] = False
    elif failure == "metadata":
        data["manifest"]["metadata_only"] = True
    elif failure == "dry_run":
        data["options"]["dry_run"] = True
    elif failure == "limited":
        data["options"]["max_products"] = 1
    else:
        data["manifest"]["completed_at"] = (datetime.now(UTC) - timedelta(days=8)).isoformat()
    source.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="complete eight-region"):
        record_acceptance(tmp_path, output, reviewed_changes=review)


def test_original_unchanged_receipts_still_verify(tmp_path: Path) -> None:
    receipt(tmp_path)
    output = tmp_path / "acceptance.json"
    record_acceptance(tmp_path, output)
    data = json.loads(output.read_text())
    data["schema_version"] = 1
    for field in ["scan_options", "acceptance_policy", "reviewed_changes_receipt",
                  "reviewed_changes_sha256"]:
        data.pop(field)
    output.write_text(json.dumps(data))
    verify_acceptance(tmp_path, output)


@pytest.mark.parametrize("tamper", ["limited", "policy", "missing_review"])
def test_reviewed_acceptance_is_rechecked_before_assembly(
    tmp_path: Path, tamper: str
) -> None:
    _, review, output = changed_receipt(tmp_path)
    record_acceptance(tmp_path, output, reviewed_changes=review)
    data = json.loads(output.read_text())
    if tamper == "limited":
        data["scan_options"]["max_products"] = 1
    elif tamper == "policy":
        data["acceptance_policy"] = "unchanged-repeat"
    else:
        review.unlink()
    output.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="stale|reviewed-change"):
        verify_acceptance(tmp_path, output)
