from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from makersfridge.models import Product
from makersfridge.storage import Catalog


@dataclass(frozen=True)
class ValidationIssue:
    product_id: str
    message: str


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_product(
    product: Product, catalog: Catalog, *, check_blobs: bool = True
) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    asset_ids: set[str] = set()
    offer_keys: set[tuple[str, str]] = set()
    variant_keys: set[tuple[str, str, str]] = set()

    for offer in product.offers:
        key = (offer.region.value, offer.store_id)
        if key in offer_keys:
            issues.append(
                ValidationIssue(
                    product.id,
                    f"duplicate offer for region {offer.region} and store {offer.store_id!r}",
                )
            )
        offer_keys.add(key)

    for variant in product.variants:
        variant_key = (variant.region.value, variant.store_id, variant.variant_id)
        if variant_key in variant_keys:
            issues.append(
                ValidationIssue(
                    product.id,
                    f"duplicate variant {variant.variant_id!r} for region {variant.region} "
                    f"and store {variant.store_id!r}",
                )
            )
        variant_keys.add(variant_key)

    for asset in product.assets:
        if asset.id in asset_ids:
            issues.append(ValidationIssue(product.id, f"duplicate asset id {asset.id}"))
        asset_ids.add(asset.id)
        if asset.parent_asset_id and product.asset(asset.parent_asset_id) is None:
            issues.append(
                ValidationIssue(
                    product.id, f"asset {asset.id} has missing parent {asset.parent_asset_id}"
                )
            )
        if asset.image_processing:
            parent = product.asset(asset.parent_asset_id) if asset.parent_asset_id else None
            if asset.kind.value != "image" or parent is None or parent.kind.value != "image":
                issues.append(
                    ValidationIssue(
                        product.id,
                        f"processed image {asset.id} must reference a source image",
                    )
                )
            elif asset.image_processing.source_sha256 != parent.sha256:
                issues.append(
                    ValidationIssue(
                        product.id,
                        f"processed image {asset.id} source hash does not match its parent",
                    )
                )
        if asset.rejection_reason:
            if any(value is not None for value in (asset.sha256, asset.size, asset.blob_path)):
                issues.append(
                    ValidationIssue(product.id, f"rejected asset {asset.id} has blob metadata")
                )
            continue
        populated = (asset.sha256, asset.size, asset.blob_path, asset.retrieved_at)
        if any(value is not None for value in populated) and not all(
            value is not None for value in populated
        ):
            issues.append(
                ValidationIssue(product.id, f"asset {asset.id} has incomplete blob metadata")
            )
        if check_blobs and asset.sha256 and asset.blob_path:
            path = catalog.root / asset.blob_path
            if not path.is_file():
                issues.append(ValidationIssue(product.id, f"missing blob {asset.blob_path}"))
            else:
                if path.stat().st_size != asset.size:
                    issues.append(ValidationIssue(product.id, f"size mismatch for {asset.id}"))
                if sha256_file(path) != asset.sha256:
                    issues.append(ValidationIssue(product.id, f"hash mismatch for {asset.id}"))
    return issues


def validate_catalog(catalog: Catalog, *, check_blobs: bool = True) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    products = catalog.products()
    product_ids = {product.id for product in products}
    for product in products:
        issues.extend(validate_product(product, catalog, check_blobs=check_blobs))
        for item in product.box_contents:
            if item.linked_product_id and item.linked_product_id not in product_ids:
                issues.append(
                    ValidationIssue(
                        product.id,
                        f"box item {item.name!r} links to missing product {item.linked_product_id}",
                    )
                )
    return issues
