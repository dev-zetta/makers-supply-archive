from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from makers_supply.models import Asset, AssetKind, Product, Region, RegionalOffer

NOW = datetime(2026, 1, 2, tzinfo=UTC)


def test_product_normalizes_unique_string_lists() -> None:
    product = Product(
        id="ia005-power-board",
        name="Power board",
        categories=[" Electronics ", "Electronics"],
        skus=["IA005", "IA005"],
        first_seen=NOW,
        last_seen=NOW,
    )
    assert product.categories == ["Electronics"]
    assert product.skus == ["IA005"]


def test_asset_rejects_path_as_filename() -> None:
    with pytest.raises(ValidationError):
        Asset(
            id="asset-one",
            kind=AssetKind.MODEL,
            source_url="https://example.com/file.step",
            original_filename="../file.step",
            media_type="model/step",
        )


def test_offer_normalizes_currency() -> None:
    offer = RegionalOffer(
        region=Region.US,
        url="https://example.com/product",
        currency="usd",
        retrieved_at=NOW,
    )
    assert offer.currency == "USD"
