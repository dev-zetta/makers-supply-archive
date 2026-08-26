from __future__ import annotations

import hashlib
import shutil
from dataclasses import dataclass
from pathlib import Path

from makers_supply.enrichment import enrich_products
from makers_supply.models import Product
from makers_supply.parser import ParsedProduct, parse_product_page
from makers_supply.reconcile import REGION_ORDER
from makers_supply.storage import Catalog
from makers_supply.validation import validate_catalog


@dataclass(frozen=True)
class MetadataBackfillResult:
    products_scanned: int
    cached_pages_missing: int
    cached_pages_failed: int
    products_updated: int
    descriptions_recovered: int
    specifications_recovered: int


class CachedMetadataBackfill:
    """Recover richer normalized metadata from official pages retained by sync."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.catalog = Catalog(root)
        self.pages_dir = root / ".staging" / "pages"
        self.work_dir = root / ".staging" / "metadata-backfill"

    def _canonical_page(self, product: Product) -> tuple[ParsedProduct | None, int]:
        failures = 0
        for alias in sorted(product.aliases, key=lambda item: REGION_ORDER[item.region]):
            key = hashlib.sha256(f"{alias.region.value}:{alias.handle}".encode()).hexdigest()
            path = self.pages_dir / f"{key}.html"
            if not path.is_file():
                continue
            try:
                return parse_product_page(path.read_text("utf-8")), failures
            except (OSError, UnicodeError, ValueError):
                failures += 1
                continue
        return None, failures

    @staticmethod
    def _updated_product(product: Product, parsed: ParsedProduct) -> Product:
        updates: dict[str, object] = {}
        has_structured_content = bool(
            parsed.description_text
            or parsed.specifications
            or parsed.source_tables
            or parsed.box_contents
        )
        if parsed.description_html and has_structured_content:
            updates["description_html"] = parsed.description_html
        if parsed.description_text:
            updates["description_text"] = parsed.description_text
            updates["description_blocks"] = list(parsed.description_blocks)
        if parsed.specifications:
            updates["specifications"] = parsed.specifications
        if parsed.source_tables:
            updates["source_tables"] = list(parsed.source_tables)
        if parsed.box_contents:
            updates["box_contents"] = list(parsed.box_contents)
        if parsed.related_links:
            updates["related_links"] = list(parsed.related_links)
        return product.model_copy(update=updates)

    def run(
        self, product_ids: set[str] | None = None, *, promote: bool = True
    ) -> MetadataBackfillResult:
        products = self.catalog.products()
        known_ids = {product.id for product in products}
        requested_ids = product_ids or known_ids
        unknown = sorted(requested_ids - known_ids)
        if unknown:
            raise ValueError(f"unknown product IDs: {', '.join(unknown)}")

        scanned = missing = failed = descriptions = specifications = 0
        candidates: list[Product] = []
        for product in products:
            if product.id not in requested_ids:
                candidates.append(product)
                continue
            scanned += 1
            parsed, page_failures = self._canonical_page(product)
            failed += page_failures
            if parsed is None:
                missing += 1
                candidates.append(product)
                continue
            updated = self._updated_product(product, parsed)
            descriptions += int(not product.description_text and bool(updated.description_text))
            specifications += int(not product.specifications and bool(updated.specifications))
            candidates.append(updated)

        fully_enriched = enrich_products(candidates, self.root)
        enriched = [
            updated if previous.id in requested_ids else previous
            for previous, updated in zip(products, fully_enriched, strict=True)
        ]
        changed = [
            updated
            for previous, updated in zip(products, enriched, strict=True)
            if previous != updated
        ]
        if changed:
            if self.work_dir.exists():
                shutil.rmtree(self.work_dir)
            staged = Catalog(self.work_dir)
            staged.write_products(enriched)
            issues = validate_catalog(staged, check_blobs=False)
            if issues:
                detail = "; ".join(
                    f"{issue.product_id}: {issue.message}" for issue in issues[:10]
                )
                raise RuntimeError(f"staged metadata backfill failed validation: {detail}")
            if promote:
                self.catalog.write_products(changed)

        return MetadataBackfillResult(
            products_scanned=scanned,
            cached_pages_missing=missing,
            cached_pages_failed=failed,
            products_updated=len(changed),
            descriptions_recovered=descriptions,
            specifications_recovered=specifications,
        )
