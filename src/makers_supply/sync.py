from __future__ import annotations

import hashlib
import shutil
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from pydantic import HttpUrl

from makers_supply.assets import AssetStore, UnsafeAssetError, asset_from_parsed
from makers_supply.config import STORES
from makers_supply.diffing import CatalogDiff, diff_products
from makers_supply.discovery import ProductStub, discover_products, product_url
from makers_supply.enrichment import enrich_product, enrich_products
from makers_supply.http import ArchiveHttpClient
from makers_supply.images import ImageProcessor
from makers_supply.models import (
    Asset,
    Product,
    Region,
    RegionalOffer,
    RegionRun,
    RunManifest,
    SourceAlias,
    Variant,
    utc_now,
)
from makers_supply.parser import ParsedProduct, parse_product_page
from makers_supply.reconcile import REGION_ORDER, AliasRegistry, Observation, Reconciler
from makers_supply.storage import Catalog, atomic_write, canonical_json
from makers_supply.validation import validate_catalog


@dataclass(frozen=True)
class SyncOptions:
    regions: tuple[Region, ...] = tuple(STORES)
    metadata_only: bool = False
    dry_run: bool = False
    resume: bool = False
    max_products: int | None = None


@dataclass(frozen=True)
class SyncResult:
    manifest: RunManifest
    diff: CatalogDiff
    promoted: bool


def _offer(
    observation: Observation, now: datetime, previous: RegionalOffer | None
) -> RegionalOffer:
    first_variant = observation.parsed.variants[0] if observation.parsed.variants else None
    price = first_variant.price if first_variant and first_variant.price else observation.stub.price
    currency = (
        first_variant.currency
        if first_variant and first_variant.currency
        else observation.stub.currency
    )
    available = first_variant.available if first_variant else None
    url = product_url(STORES[observation.region], observation.stub.handle)
    candidate = RegionalOffer(
        region=observation.region,
        url=HttpUrl(url),
        currency=currency,
        price=price,
        compare_at_price=(first_variant.compare_at_price if first_variant else None),
        available=available,
        listed=True,
        missing_runs=0,
        retrieved_at=now,
    )
    if previous:
        old = previous.model_dump(exclude={"retrieved_at"})
        new = candidate.model_dump(exclude={"retrieved_at"})
        if old == new:
            return previous
    return candidate


def _variants(observations: list[Observation]) -> list[Variant]:
    variants: list[Variant] = []
    for observation in sorted(observations, key=lambda item: REGION_ORDER[item.region]):
        for item in observation.parsed.variants:
            variants.append(
                Variant(
                    region=observation.region,
                    variant_id=item.variant_id or f"unknown-{len(variants)}",
                    title=item.title,
                    sku=item.variant_id or None,
                    part_number=next(
                        (
                            part
                            for part in observation.parsed.part_numbers
                            if part in item.title
                        ),
                        None,
                    ),
                    available=item.available,
                    price=item.price,
                    compare_at_price=item.compare_at_price,
                    currency=item.currency,
                    url=HttpUrl(item.url) if item.url else None,
                    image_url=HttpUrl(item.image_url) if item.image_url else None,
                )
            )
    return variants


def _candidate_assets(
    canonical: Observation,
    previous: Product | None,
) -> list[Asset]:
    old_by_url = (
        {
            str(asset.source_url): asset
            for asset in previous.assets
            if asset.parent_asset_id is None
        }
        if previous
        else {}
    )
    assets = []
    for parsed in canonical.parsed.assets:
        assets.append(old_by_url.get(parsed.url, asset_from_parsed(parsed)))
    parent_ids = {asset.id for asset in assets}
    if previous:
        assets.extend(
            asset for asset in previous.assets if asset.parent_asset_id in parent_ids
        )
    return assets


def _signature(product: Product) -> dict[str, object]:
    payload = product.model_dump(mode="json", exclude={"first_seen", "last_seen", "removed_at"})
    for offer in payload.get("offers", []):
        offer.pop("retrieved_at", None)
    for asset in payload.get("assets", []):
        asset.pop("retrieved_at", None)
    return payload


class SyncEngine:
    def __init__(self, root: Path, client: ArchiveHttpClient) -> None:
        self.root = root
        self.client = client
        self.catalog = Catalog(root)
        self.staging = root / ".staging"

    def _prepare_staging(self, resume: bool) -> Catalog:
        snapshot = self.staging / "snapshot"
        downloads = self.staging / "downloads"
        pages = self.staging / "pages"
        if snapshot.exists():
            shutil.rmtree(snapshot)
        if not resume and downloads.exists():
            shutil.rmtree(downloads)
        if not resume and pages.exists():
            shutil.rmtree(pages)
        stage_catalog = Catalog(snapshot)
        stage_catalog.products_dir.mkdir(parents=True, exist_ok=True)
        if self.catalog.products_dir.exists():
            for source in self.catalog.products_dir.glob("*.json"):
                shutil.copy2(source, stage_catalog.products_dir / source.name)
        if self.catalog.blobs_dir.exists():
            shutil.copytree(
                self.catalog.blobs_dir,
                stage_catalog.blobs_dir,
                copy_function=lambda source, destination: Path(destination).hardlink_to(source),
                dirs_exist_ok=True,
            )
        return stage_catalog

    def _page(self, region: Region, handle: str, resume: bool) -> str:
        cache_key = hashlib.sha256(f"{region.value}:{handle}".encode()).hexdigest()
        cache_path = self.staging / "pages" / f"{cache_key}.html"
        if resume and cache_path.is_file():
            return cache_path.read_text("utf-8")
        page = self.client.get(product_url(STORES[region], handle)).text
        atomic_write(cache_path, page)
        return page

    def _build_product(
        self,
        product_id: str,
        observations: list[Observation],
        previous: Product | None,
        now: datetime,
        asset_store: AssetStore,
        metadata_only: bool,
        selected_regions: set[Region],
    ) -> tuple[Product, int, int, int]:
        canonical = min(observations, key=lambda item: REGION_ORDER[item.region])
        previous_offers = {offer.region: offer for offer in previous.offers} if previous else {}
        offers = [
            _offer(item, now, previous_offers.get(item.region))
            for item in sorted(observations, key=lambda item: REGION_ORDER[item.region])
        ]
        observed_regions = {item.region for item in observations}
        if previous:
            for old_offer in previous.offers:
                if old_offer.region in observed_regions or old_offer.region not in selected_regions:
                    continue
                missing_runs = old_offer.missing_runs + 1
                offers.append(
                    old_offer.model_copy(
                        update={"missing_runs": missing_runs, "listed": missing_runs < 2}
                    )
                )

        assets = (
            list(previous.assets)
            if metadata_only and previous is not None
            else _candidate_assets(canonical, previous)
        )
        downloaded = 0
        rejected = 0
        bytes_downloaded = 0
        if not metadata_only:
            complete_assets = []
            for asset in assets:
                if asset.image_processing is not None:
                    complete_assets.append(asset)
                    continue
                blob_exists = bool(
                    asset.blob_path
                    and (asset_store.catalog.root / asset.blob_path).is_file()
                )
                if asset.sha256 and blob_exists:
                    complete_assets.append(asset)
                    continue
                try:
                    stored, extracted = asset_store.ingest(asset, now)
                except UnsafeAssetError as error:
                    complete_assets.append(
                        asset.model_copy(
                            update={"rejection_reason": str(error), "retrieved_at": now}
                        )
                    )
                    rejected += 1
                    continue
                complete_assets.extend([stored, *extracted])
                downloaded += 1
                bytes_downloaded += stored.size or 0
            assets = ImageProcessor(
                asset_store.catalog, asset_store.staging_dir
            ).process(complete_assets).assets

        aliases = [
            SourceAlias(
                region=item.region,
                handle=item.stub.handle,
                product_id=item.parsed.source_id or item.stub.source_id,
            )
            for item in sorted(observations, key=lambda item: REGION_ORDER[item.region])
        ]
        part_numbers = sorted(
            {part for item in observations for part in item.parsed.part_numbers}
        )
        skus = sorted(
            {
                variant.variant_id
                for item in observations
                for variant in item.parsed.variants
                if variant.variant_id
            }
        )
        active = any(offer.listed for offer in offers)
        candidate = Product(
            id=product_id,
            name=canonical.parsed.name,
            description_html=canonical.parsed.description_html,
            description_text=canonical.parsed.description_text,
            description_blocks=list(canonical.parsed.description_blocks),
            categories=previous.categories if previous else [],
            tags=previous.tags if previous else [],
            specifications=canonical.parsed.specifications,
            source_tables=list(canonical.parsed.source_tables),
            box_contents=list(canonical.parsed.box_contents),
            part_numbers=part_numbers,
            skus=skus,
            aliases=aliases,
            variants=_variants(observations),
            offers=sorted(offers, key=lambda item: REGION_ORDER[item.region]),
            assets=assets,
            related_links=list(canonical.parsed.related_links),
            first_seen=previous.first_seen if previous else now,
            last_seen=now,
            active=active,
            removed_at=None if active else (previous.removed_at if previous else now),
        )
        candidate = enrich_product(candidate, self.root)
        if previous and _signature(previous) == _signature(candidate):
            return previous, downloaded, bytes_downloaded, rejected
        return candidate, downloaded, bytes_downloaded, rejected

    def _promote(self, staged: Catalog) -> None:
        products = staged.products()
        referenced_blobs = sorted(
            {
                asset.blob_path
                for product in products
                for asset in product.assets
                if asset.blob_path
            }
        )
        for relative in referenced_blobs:
            blob = staged.root / relative
            destination = self.catalog.root / relative
            if not destination.exists():
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(blob, destination)
        self.catalog.write_products(products)

    def run(self, options: SyncOptions) -> SyncResult:
        started_at = utc_now()
        existing = self.catalog.products()
        stage_catalog = self._prepare_staging(options.resume)
        aliases = AliasRegistry(self.root / "config" / "aliases.json")
        reconciler = Reconciler(existing, aliases)
        grouped: dict[str, list[Observation]] = defaultdict(list)
        region_runs = []
        regional_stubs: dict[Region, list[ProductStub]] = {}
        for region in options.regions:
            try:
                stubs = discover_products(self.client, STORES[region])
                if options.max_products is not None:
                    stubs = stubs[: options.max_products]
            except Exception as error:
                region_runs.append(
                    RegionRun(region=region, success=False, products_seen=0, error=str(error))
                )
                raise RuntimeError(f"sync failed for {region.value}: {error}") from error
            regional_stubs[region] = stubs
            region_runs.append(
                RegionRun(region=region, success=True, products_seen=len(stubs))
            )

        handle_regions: dict[str, list[Region]] = defaultdict(list)
        for region, stubs in regional_stubs.items():
            for stub in stubs:
                handle_regions[stub.handle].append(region)
        parsed_by_region_handle: dict[tuple[Region, str], ParsedProduct] = {}
        for handle, available_regions in sorted(handle_regions.items()):
            for region in sorted(available_regions, key=lambda item: REGION_ORDER[item]):
                try:
                    parsed_by_region_handle[(region, handle)] = parse_product_page(
                        self._page(region, handle, options.resume)
                    )
                except Exception as error:
                    raise RuntimeError(
                        f"sync failed for {region.value}/{handle}: {error}"
                    ) from error

        for region in options.regions:
            for stub in regional_stubs[region]:
                parsed = parsed_by_region_handle[(region, stub.handle)]
                observation = Observation(region, stub, parsed)
                grouped[reconciler.group_key(observation)].append(observation)

        asset_store = AssetStore(stage_catalog, self.client, self.staging)
        products_by_id = {product.id: product for product in existing}
        seen_ids: set[str] = set()
        assets_downloaded = 0
        assets_rejected = 0
        bytes_downloaded = 0
        selected_regions = set(options.regions)
        for key, observations in sorted(grouped.items()):
            product_id = (
                key.removeprefix("existing:")
                if key.startswith("existing:")
                else reconciler.new_id(observations)
            )
            previous = products_by_id.get(product_id)
            product, downloaded, byte_count, rejected = self._build_product(
                product_id,
                observations,
                previous,
                started_at,
                asset_store,
                options.metadata_only,
                selected_regions,
            )
            stage_catalog.write_product(product)
            seen_ids.add(product_id)
            assets_downloaded += downloaded
            assets_rejected += rejected
            bytes_downloaded += byte_count

        if options.max_products is None:
            for product in existing:
                if product.id in seen_ids:
                    continue
                offers = []
                for offer in product.offers:
                    if offer.region not in selected_regions:
                        offers.append(offer)
                        continue
                    missing_runs = offer.missing_runs + 1
                    offers.append(
                        offer.model_copy(
                            update={"missing_runs": missing_runs, "listed": missing_runs < 2}
                        )
                    )
                active = any(offer.listed for offer in offers)
                updated = product.model_copy(
                    update={
                        "offers": offers,
                        "active": active,
                        "removed_at": None if active else (product.removed_at or started_at),
                        "last_seen": started_at if active != product.active else product.last_seen,
                    }
                )
                stage_catalog.write_product(updated)

        stage_catalog.write_products(enrich_products(stage_catalog.products(), self.root))
        issues = validate_catalog(stage_catalog, check_blobs=not options.metadata_only)
        if issues:
            detail = "; ".join(f"{issue.product_id}: {issue.message}" for issue in issues[:10])
            raise RuntimeError(f"staged catalog failed validation: {detail}")
        after = stage_catalog.products()
        diff = diff_products(existing, after)
        manifest = RunManifest(
            started_at=started_at,
            completed_at=utc_now(),
            metadata_only=options.metadata_only,
            regions=region_runs,
            products_written=len(after),
            assets_downloaded=assets_downloaded,
            assets_rejected=assets_rejected,
            bytes_downloaded=bytes_downloaded,
        )
        promoted = diff.has_changes and not options.dry_run
        if promoted:
            self._promote(stage_catalog)
            atomic_write(self.root / "data" / "runs" / "latest.json", canonical_json(manifest))
            atomic_write(self.root / "reports" / "latest.md", diff.markdown())
        return SyncResult(manifest, diff, promoted)
