from __future__ import annotations

import hashlib
import shutil
from dataclasses import dataclass
from pathlib import Path

from makers_supply.assets import AssetStore, UnsafeAssetError, asset_from_parsed
from makers_supply.http import ArchiveHttpClient
from makers_supply.images import ImageProcessor
from makers_supply.models import AssetKind, Product, utc_now
from makers_supply.parser import ParsedProduct, parse_product_page
from makers_supply.reconcile import REGION_ORDER
from makers_supply.storage import Catalog
from makers_supply.validation import validate_catalog


@dataclass(frozen=True)
class AssetBackfillResult:
    products_scanned: int
    products_with_missing_assets: int
    cached_pages_missing: int
    assets_discovered: int
    assets_downloaded: int
    assets_extracted: int
    assets_rejected: int
    bytes_downloaded: int
    promoted: bool


class CachedAssetBackfill:
    """Recover assets from official product pages retained by a previous sync."""

    def __init__(self, root: Path, client: ArchiveHttpClient) -> None:
        self.root = root
        self.client = client
        self.catalog = Catalog(root)
        self.work_dir = root / ".staging" / "asset-backfill"
        self.pages_dir = root / ".staging" / "pages"

    def _page(self, product: Product) -> ParsedProduct | None:
        for alias in sorted(product.aliases, key=lambda item: REGION_ORDER[item.region]):
            key = hashlib.sha256(f"{alias.region.value}:{alias.handle}".encode()).hexdigest()
            path = self.pages_dir / f"{key}.html"
            if path.is_file():
                return parse_product_page(path.read_text("utf-8"))
        return None

    def _prepare_catalog(self, resume: bool) -> Catalog:
        snapshot = self.work_dir / "snapshot"
        if snapshot.exists():
            shutil.rmtree(snapshot)
        if not resume:
            downloads = self.work_dir / "downloads"
            if downloads.exists():
                shutil.rmtree(downloads)
        staged = Catalog(snapshot)
        staged.products_dir.mkdir(parents=True, exist_ok=True)
        for source in self.catalog.products_dir.glob("*.json"):
            shutil.copy2(source, staged.products_dir / source.name)
        if self.catalog.blobs_dir.exists():
            shutil.copytree(
                self.catalog.blobs_dir,
                staged.blobs_dir,
                copy_function=lambda source, destination: Path(destination).hardlink_to(source),
                dirs_exist_ok=True,
            )
        return staged

    def _promote(self, staged: Catalog) -> None:
        products = staged.products()
        referenced = {
            asset.blob_path
            for product in products
            for asset in product.assets
            if asset.blob_path
        }
        for relative in sorted(referenced):
            source = staged.root / relative
            destination = self.catalog.root / relative
            if not destination.exists():
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, destination)
        self.catalog.write_products(products)

    def run(
        self,
        product_ids: set[str] | None = None,
        *,
        download: bool = False,
        dry_run: bool = False,
        resume: bool = True,
    ) -> AssetBackfillResult:
        products = self.catalog.products()
        known_ids = {product.id for product in products}
        requested_ids = product_ids or known_ids
        unknown = sorted(requested_ids - known_ids)
        if unknown:
            raise ValueError(f"unknown product IDs: {', '.join(unknown)}")

        staged = self._prepare_catalog(resume) if download else None
        asset_store = AssetStore(staged, self.client, self.work_dir) if staged else None
        processor = ImageProcessor(staged, self.work_dir) if staged else None
        timestamp = utc_now()
        scanned = changed = missing_pages = discovered = downloaded = extracted = rejected = 0
        bytes_downloaded = 0
        for product in products:
            if product.id not in requested_ids:
                continue
            scanned += 1
            parsed = self._page(product)
            if parsed is None:
                missing_pages += 1
                continue
            existing_urls = {
                str(asset.source_url)
                for asset in product.assets
                if asset.parent_asset_id is None
            }
            missing = [
                asset
                for asset in parsed.assets
                if asset.kind is not AssetKind.IMAGE and asset.url not in existing_urls
            ]
            if not missing:
                continue
            changed += 1
            discovered += len(missing)
            if not download:
                continue
            assert staged is not None and asset_store is not None and processor is not None
            assets = list(product.assets)
            for parsed_asset in missing:
                candidate = asset_from_parsed(parsed_asset)
                try:
                    stored, members = asset_store.ingest(candidate, timestamp)
                except UnsafeAssetError as error:
                    assets.append(
                        candidate.model_copy(
                            update={"rejection_reason": str(error), "retrieved_at": timestamp}
                        )
                    )
                    rejected += 1
                    continue
                assets.extend([stored, *members])
                downloaded += 1
                extracted += len(members)
                bytes_downloaded += stored.size or 0
            staged.write_product(
                product.model_copy(update={"assets": processor.process(assets).assets})
            )

        promoted = False
        if staged is not None:
            issues = validate_catalog(staged)
            if issues:
                detail = "; ".join(
                    f"{issue.product_id}: {issue.message}" for issue in issues[:10]
                )
                raise RuntimeError(f"staged asset backfill failed validation: {detail}")
            promoted = changed > 0 and not dry_run
            if promoted:
                self._promote(staged)
        return AssetBackfillResult(
            products_scanned=scanned,
            products_with_missing_assets=changed,
            cached_pages_missing=missing_pages,
            assets_discovered=discovered,
            assets_downloaded=downloaded,
            assets_extracted=extracted,
            assets_rejected=rejected,
            bytes_downloaded=bytes_downloaded,
            promoted=promoted,
        )
