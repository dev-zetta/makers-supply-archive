from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

import httpx

from makersfridge.assets import AssetStore, UnsafeAssetError
from makersfridge.diffing import diff_products
from makersfridge.http import ArchiveHttpClient
from makersfridge.images import ImageProcessor
from makersfridge.models import Asset, Region, RegionRun, RunManifest, utc_now
from makersfridge.storage import atomic_write, canonical_json, snapshot_identity
from makersfridge.suppliers import SUPPLIERS
from makersfridge.suppliers.adapters import ADAPTERS
from makersfridge.suppliers.catalog import load_pilots_snapshot
from makersfridge.sync import SyncEngine, SyncResult, _signature
from makersfridge.sync_state import SyncCheckpoint, resume_signature
from makersfridge.validation import validate_catalog


@dataclass(frozen=True)
class SupplierSyncOptions:
    suppliers: tuple[str, ...] = tuple(s for s in SUPPLIERS if s != "bambu-lab")
    product_ids: tuple[str, ...] = ()
    metadata_only: bool = False
    dry_run: bool = False
    resume: bool = False
    max_products: int | None = None
    refresh_assets: bool = False
    manifest: Path | None = None


class CachedPages:
    def __init__(self, engine: SupplierSyncEngine, continuing: bool) -> None:
        self.engine = engine
        self.continuing = continuing

    def get(self, url: str, *, check_robots: bool = True) -> httpx.Response:
        key = hashlib.sha256(url.encode()).hexdigest()
        engine = self.engine
        path = engine.staging / "pages" / f"{key}.html"
        assert engine.checkpoint is not None
        if self.continuing and path.is_file():
            raw = path.read_bytes()
            if hashlib.sha256(raw).hexdigest() == engine.checkpoint.page_hashes.get(key):
                return httpx.Response(200, content=raw, request=httpx.Request("GET", url))
        response = engine.client.get(url, check_robots=check_robots)
        # Store decoded text in a known encoding, including on non-UTF8 storefronts.
        raw = response.text.encode("utf-8")
        atomic_write(path, raw)
        engine.checkpoint.page_hashes[key] = hashlib.sha256(raw).hexdigest()
        engine.checkpoint.save(engine.checkpoint_path)
        return httpx.Response(200, content=raw, request=httpx.Request("GET", url))


class SupplierSyncEngine(SyncEngine):
    """Import reviewed supplier products without treating the pilot as a full catalog scan."""

    def __init__(self, root: Path, client: ArchiveHttpClient) -> None:
        super().__init__(root, client)
        self.staging = root / ".staging" / "suppliers"
        self.checkpoint_path = self.staging / "sync-state.json"

    def run_suppliers(self, options: SupplierSyncOptions) -> SyncResult:
        if options.metadata_only and options.refresh_assets:
            raise ValueError("asset refresh requires binary downloads")
        if options.max_products is not None and options.max_products < 1:
            raise ValueError("max_products must be positive")
        started = utc_now()
        manifest_path = options.manifest or self.root / "config" / "supplier-pilots.json"
        pilots, manifest_identity = load_pilots_snapshot(manifest_path)
        selected_suppliers = set(options.suppliers)
        known = {spec.supplier_id for spec in pilots}
        if not selected_suppliers or selected_suppliers - known:
            raise ValueError(f"unknown or empty pilot supplier selection: {options.suppliers}")
        selected_ids = set(options.product_ids)
        selected = [
            spec
            for spec in pilots
            if spec.supplier_id in selected_suppliers
            and (not selected_ids or spec.id in selected_ids)
        ]
        if selected_ids - {spec.id for spec in selected}:
            raise ValueError("selected product IDs do not belong to the selected suppliers")
        if options.max_products is not None:
            selected = selected[: options.max_products]
        existing = self.catalog.products()
        by_id = {p.id: p for p in existing}
        original_bytes = {
            spec.id: self.catalog.product_path(spec.id).read_bytes()
            if self.catalog.product_path(spec.id).is_file()
            else None
            for spec in selected
        }
        for spec in selected:
            old = by_id.get(spec.id)
            if old and old.supplier_id != spec.supplier_id:
                raise ValueError(f"product ID {spec.id} already belongs to {old.supplier_id}")
        signature = resume_signature(
            {
                "suppliers": sorted(selected_suppliers),
                "product_ids": sorted(selected_ids),
                "metadata_only": options.metadata_only,
                "dry_run": options.dry_run,
                "max_products": options.max_products,
                "refresh_assets": options.refresh_assets,
                "manifest_sha256": manifest_identity,
            },
            snapshot_identity(self.root),
        )
        continuing = False
        if options.resume and self.checkpoint_path.is_file():
            try:
                saved = SyncCheckpoint.model_validate_json(self.checkpoint_path.read_text())
                if saved.status == "running" and saved.signature == signature:
                    self.checkpoint = saved
                    continuing = True
            except (ValueError, OSError):
                pass
        if not continuing:
            self.checkpoint = SyncCheckpoint(signature=signature, started_at=started.isoformat())
            self.checkpoint.save(self.checkpoint_path)
        staged = self._prepare_staging(continuing)
        taxonomy_path = self.root / "config" / "categories.json"
        taxonomy = json.loads(taxonomy_path.read_text()) if taxonomy_path.is_file() else {}
        definitions = taxonomy.get("categories", {})
        pages = CachedPages(self, continuing)
        store = AssetStore(staged, self.client, self.staging)
        downloaded = rejected = byte_count = 0
        for spec in selected:
            candidate = ADAPTERS[spec.source_kind].fetch(spec, pages, started)
            for assignment in candidate.category_assignments:
                definition = definitions.get(assignment.id, {})
                assignment.label = str(definition.get("label", assignment.id.title()))
                assignment.path = [str(x) for x in definition.get("path", [assignment.label])]
            previous = by_id.get(candidate.id)
            if previous:
                candidate.first_seen = previous.first_seen
                old_assets = {asset.id: asset for asset in previous.assets}
                roots = []
                for asset in candidate.assets:
                    prior = old_assets.get(asset.id)
                    if prior and prior.sha256 and prior.blob_path and not options.refresh_assets:
                        asset = asset.model_copy(
                            update={
                                key: getattr(prior, key)
                                for key in (
                                    "sha256",
                                    "size",
                                    "blob_path",
                                    "retrieved_at",
                                    "media_type",
                                    "declared_media_type",
                                )
                            }
                        )
                    roots.append(asset)
                root_ids = {asset.id for asset in roots}
                parents = {asset.id: asset for asset in roots}
                children = [
                    asset.model_copy(
                        update={
                            field: getattr(parents[asset.parent_asset_id], field)
                            for field in (
                                "applies_to_skus",
                                "hardware_revision",
                                "source_repository",
                                "source_commit",
                                "source_path",
                                "license_url",
                                "rights_status",
                            )
                        }
                        | {
                            "role": "document"
                            if asset.kind.value == "document"
                            else parents[asset.parent_asset_id].role,
                        }
                    )
                    for asset in previous.assets
                    if asset.parent_asset_id in root_ids and not options.refresh_assets
                ]
                candidate.assets = [*roots, *children]
            if not options.metadata_only:
                assets: list[Asset] = []
                for asset in candidate.assets:
                    if (
                        asset.sha256
                        and asset.blob_path
                        and (staged.root / asset.blob_path).is_file()
                    ):
                        assets.append(asset)
                        continue
                    try:
                        stored, extracted = store.ingest(asset, started)
                    except UnsafeAssetError as error:
                        assets.append(
                            asset.model_copy(
                                update={"rejection_reason": str(error), "retrieved_at": started}
                            )
                        )
                        rejected += 1
                        continue
                    assets.extend([stored, *extracted])
                    downloaded += 1
                    byte_count += stored.size or 0
                candidate.assets = ImageProcessor(staged, self.staging).process(assets).assets
            if previous and _signature(previous) == _signature(candidate):
                candidate = previous
            staged.write_product(candidate)
        # A curated pilot is never evidence that any other product has disappeared.
        issues = validate_catalog(staged, check_blobs=not options.metadata_only)
        if issues:
            details = "; ".join(f"{i.product_id}: {i.message}" for i in issues[:10])
            raise RuntimeError(f"staged supplier catalog failed validation: {details}")
        after = staged.products()
        diff = diff_products(existing, after)
        receipt = RunManifest(
            started_at=started,
            completed_at=utc_now(),
            metadata_only=options.metadata_only,
            supplier_ids=sorted(selected_suppliers),
            regions=[RegionRun(region=Region.GLOBAL, success=True, products_seen=len(selected))],
            products_written=len(selected),
            assets_downloaded=downloaded,
            assets_rejected=rejected,
            bytes_downloaded=byte_count,
        )
        promoted = diff.has_changes and not options.dry_run
        if promoted:
            if load_pilots_snapshot(manifest_path)[1] != manifest_identity:
                raise RuntimeError("reviewed source manifests changed during import; retry sync")
            for product_id, original in original_bytes.items():
                path = self.catalog.product_path(product_id)
                current = path.read_bytes() if path.is_file() else None
                if current != original:
                    raise RuntimeError(f"product changed during import: {product_id}; retry sync")
            self._promote(staged, {spec.id for spec in selected})
            atomic_write(
                self.root / "data" / "runs" / "suppliers-latest.json", canonical_json(receipt)
            )
            atomic_write(self.root / "reports" / "suppliers-latest.md", diff.markdown())
        assert self.checkpoint is not None
        self.checkpoint.status = "complete"
        self.checkpoint.save(self.checkpoint_path)
        atomic_write(
            self.staging / "last-sync.json",
            canonical_json(
                {
                    "manifest": receipt.model_dump(mode="json"),
                    "promoted": promoted,
                    "snapshot_id": snapshot_identity(self.root),
                    "has_changes": diff.has_changes,
                }
            ),
        )
        return SyncResult(receipt, diff, promoted)
