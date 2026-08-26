from __future__ import annotations

from dataclasses import dataclass, field

from makers_supply.models import Product


def _offers(product: Product) -> dict[str, tuple[object, ...]]:
    return {
        offer.region.value: (
            offer.price,
            offer.currency,
            offer.available,
            offer.listed,
            offer.missing_runs,
            str(offer.url),
        )
        for offer in product.offers
    }


def _assets(product: Product) -> dict[str, str | None]:
    return {asset.id: asset.sha256 for asset in product.assets}


@dataclass
class CatalogDiff:
    added: list[str] = field(default_factory=list)
    changed: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    offer_changes: list[str] = field(default_factory=list)
    asset_changes: list[str] = field(default_factory=list)

    @property
    def has_changes(self) -> bool:
        return any((self.added, self.changed, self.removed, self.offer_changes, self.asset_changes))

    def markdown(self) -> str:
        sections = ["# Maker's Supply sync report", ""]
        for title, values in (
            ("Added products", self.added),
            ("Changed products", self.changed),
            ("Removed products", self.removed),
            ("Regional offer changes", self.offer_changes),
            ("Asset changes", self.asset_changes),
        ):
            sections.extend([f"## {title}", ""])
            sections.extend((f"- {value}" for value in values) if values else ["None."])
            sections.append("")
        return "\n".join(sections)


def diff_products(before: list[Product], after: list[Product]) -> CatalogDiff:
    old = {product.id: product for product in before}
    new = {product.id: product for product in after}
    result = CatalogDiff(
        added=sorted(new.keys() - old.keys()),
        removed=sorted(
            product_id
            for product_id in old.keys() & new.keys()
            if old[product_id].active and not new[product_id].active
        ),
    )
    for product_id in sorted(old.keys() & new.keys()):
        previous = old[product_id]
        current = new[product_id]
        previous_core = previous.model_dump(
            exclude={"offers", "assets", "first_seen", "last_seen", "removed_at"}
        )
        current_core = current.model_dump(
            exclude={"offers", "assets", "first_seen", "last_seen", "removed_at"}
        )
        if previous_core != current_core:
            result.changed.append(product_id)
        if _offers(previous) != _offers(current):
            result.offer_changes.append(product_id)
        if _assets(previous) != _assets(current):
            result.asset_changes.append(product_id)
    return result
