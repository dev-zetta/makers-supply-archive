from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from makers_supply.models import Region, RunManifest
from makers_supply.storage import Catalog, atomic_write, canonical_json, snapshot_identity
from makers_supply.validation import validate_catalog


def record_acceptance(root: Path, output: Path) -> None:
    """Record a successful full, unchanged repeat scan and independent blob validation."""
    receipt = json.loads((root / ".staging/last-sync.json").read_text())
    manifest = RunManifest.model_validate(receipt["manifest"])
    regions = {item.region for item in manifest.regions if item.success}
    options = receipt["options"]
    identity = snapshot_identity(root)
    scan_age = datetime.now(UTC) - manifest.completed_at
    if (
        receipt["has_changes"]
        or receipt["promoted"]
        or receipt["snapshot_id"] != identity
        or regions != set(Region)
        or manifest.metadata_only
        or options["metadata_only"]
        or options["dry_run"]
        or options["max_products"] is not None
        or not timedelta(0) <= scan_age <= timedelta(days=7)
    ):
        raise ValueError(
            "acceptance requires a complete eight-region, binary, unchanged repeat sync"
        )
    issues = validate_catalog(Catalog(root))
    if issues:
        raise ValueError(f"archive validation failed: {issues[:5]}")
    atomic_write(
        output,
        canonical_json(
            {
                "schema_version": 1,
                "snapshot_id": identity,
                "verified_at": datetime.now(UTC).isoformat(),
                "full_blob_validation": True,
                "unchanged_repeat": True,
                "repeat_sync": manifest.model_dump(mode="json"),
            }
        ),
    )


def verify_acceptance(root: Path, path: Path) -> None:
    receipt = json.loads(path.read_text())
    manifest = RunManifest.model_validate(receipt["repeat_sync"])
    verified = datetime.fromisoformat(receipt["verified_at"])
    age = datetime.now(UTC) - verified
    scan_age = datetime.now(UTC) - manifest.completed_at
    if (
        receipt.get("schema_version") != 1
        or receipt.get("snapshot_id") != snapshot_identity(root)
        or receipt.get("full_blob_validation") is not True
        or receipt.get("unchanged_repeat") is not True
        or {item.region for item in manifest.regions if item.success} != set(Region)
        or manifest.metadata_only
        or not timedelta(0) <= age <= timedelta(days=7)
        or not timedelta(0) <= scan_age <= timedelta(days=7)
    ):
        raise ValueError("release acceptance is stale, incomplete, or for another snapshot")
