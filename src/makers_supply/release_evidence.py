from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from makers_supply.models import Region, RunManifest
from makers_supply.storage import Catalog, atomic_write, canonical_json, snapshot_identity
from makers_supply.validation import validate_catalog


def _full_regions(manifest: RunManifest) -> bool:
    return (
        len(manifest.regions) == len(Region)
        and all(item.success for item in manifest.regions)
        and {item.region for item in manifest.regions} == set(Region)
    )


def _full_options(options: object) -> bool:
    return (
        isinstance(options, dict)
        and options.get("metadata_only") is False
        and options.get("dry_run") is False
        and options.get("max_products", "missing") is None
    )


def _review_checksum(path: Path, identity: str) -> str:
    try:
        content = path.read_bytes()
        review = json.loads(content)
    except (OSError, ValueError) as error:
        raise ValueError("reviewed-change evidence is missing or invalid") from error
    if not isinstance(review, dict):
        raise ValueError("reviewed-change evidence must be an object")
    fields = review.get("canonical_fields_changed")
    changes = review.get("reviewed_variant_changes")
    if (
        review.get("schema_version") != 1
        or review.get("snapshot_id") != identity
        or review.get("full_blob_validation") is not True
        or review.get("database_reproducible") is not True
        or review.get("asset_records_unchanged") is not True
        or not isinstance(fields, dict)
        or not fields
        or not set(fields) <= {"last_seen", "offers", "variants"}
        or not isinstance(changes, list)
        or not changes
    ):
        raise ValueError("reviewed-change evidence is incomplete or for another snapshot")
    for change in changes:
        if (
            not isinstance(change, dict)
            or not isinstance(change.get("fields"), dict)
            or not change["fields"]
            or not set(change["fields"]) <= {"available", "price", "compare_at_price", "title"}
        ):
            raise ValueError("reviewed changes must describe live inventory, prices, or titles")
    return hashlib.sha256(content).hexdigest()


def record_acceptance(root: Path, output: Path, *, reviewed_changes: Path | None = None) -> None:
    """Record full scan/blob validation with an explicit, auditable acceptance policy."""
    receipt = json.loads((root / ".staging/last-sync.json").read_text())
    manifest = RunManifest.model_validate(receipt["manifest"])
    identity = snapshot_identity(root)
    scan_age = datetime.now(UTC) - manifest.completed_at
    if (
        type(receipt.get("has_changes")) is not bool
        or type(receipt.get("promoted")) is not bool
        or receipt["has_changes"] != receipt["promoted"]
        or (reviewed_changes is None and receipt["has_changes"])
        or receipt["snapshot_id"] != identity
        or not _full_regions(manifest)
        or manifest.metadata_only
        or not _full_options(receipt["options"])
        or not timedelta(0) <= scan_age <= timedelta(days=7)
    ):
        raise ValueError(
            "acceptance requires a complete eight-region binary scan and an unchanged "
            "repeat or explicit reviewed-change evidence"
        )
    review_name = None
    review_hash = None
    if reviewed_changes is not None:
        reviewed_changes = reviewed_changes.resolve()
        if (
            reviewed_changes.parent != output.resolve().parent
            or not reviewed_changes.name.startswith("release-")
            or reviewed_changes.suffix != ".json"
        ):
            raise ValueError("reviewed-change receipt must be a release JSON beside acceptance")
        review_name = reviewed_changes.name
        review_hash = _review_checksum(reviewed_changes, identity)
    issues = validate_catalog(Catalog(root))
    if issues:
        raise ValueError(f"archive validation failed: {issues[:5]}")
    atomic_write(
        output,
        canonical_json(
            {
                "schema_version": 2,
                "snapshot_id": identity,
                "verified_at": datetime.now(UTC).isoformat(),
                "full_blob_validation": True,
                "unchanged_repeat": not receipt["has_changes"],
                "acceptance_policy": "reviewed-live-changes"
                if reviewed_changes is not None
                else "unchanged-repeat",
                "reviewed_changes_receipt": review_name,
                "reviewed_changes_sha256": review_hash,
                "scan_options": receipt["options"],
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
    schema = receipt.get("schema_version")
    policy = receipt.get("acceptance_policy", "unchanged-repeat")
    policy_valid = (
        schema in {1, 2}
        and policy == "unchanged-repeat"
        and receipt.get("unchanged_repeat") is True
    ) or (
        schema == 2
        and policy == "reviewed-live-changes"
        and type(receipt.get("unchanged_repeat")) is bool
    )
    if (
        not policy_valid
        or receipt.get("snapshot_id") != snapshot_identity(root)
        or receipt.get("full_blob_validation") is not True
        or not _full_regions(manifest)
        or manifest.metadata_only
        or (schema == 2 and not _full_options(receipt.get("scan_options")))
        or not timedelta(0) <= age <= timedelta(days=7)
        or not timedelta(0) <= scan_age <= timedelta(days=7)
    ):
        raise ValueError("release acceptance is stale, incomplete, or for another snapshot")
    if policy == "reviewed-live-changes":
        name = receipt.get("reviewed_changes_receipt")
        if (
            not isinstance(name, str)
            or Path(name).name != name
            or "\\" in name
            or ":" in name
            or not name.startswith("release-")
            or not name.endswith(".json")
        ):
            raise ValueError("reviewed-change receipt filename is invalid")
        review = path.parent / name
        if review.resolve().parent != path.parent.resolve():
            raise ValueError("reviewed-change receipt must be beside acceptance")
        if _review_checksum(review, receipt["snapshot_id"]) != receipt.get(
            "reviewed_changes_sha256"
        ):
            raise ValueError("reviewed-change evidence checksum mismatch")
