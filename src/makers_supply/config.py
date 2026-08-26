from __future__ import annotations

from dataclasses import dataclass

from makers_supply.models import Region


@dataclass(frozen=True)
class StoreConfig:
    region: Region
    store_url: str
    api_url: str
    locale: str
    timezone: str
    header_region: str
    default_currency: str


STORES: dict[Region, StoreConfig] = {
    Region.US: StoreConfig(
        Region.US,
        "https://us.store.bambulab.com",
        "https://na-store-api.bambulab.com",
        "en-US",
        "America/New_York",
        "US",
        "USD",
    ),
    Region.CA: StoreConfig(
        Region.CA,
        "https://ca.store.bambulab.com",
        "https://na-store-api.bambulab.com",
        "en-US",
        "America/Toronto",
        "CA",
        "CAD",
    ),
    Region.EU: StoreConfig(
        Region.EU,
        "https://eu.store.bambulab.com",
        "https://eu-store-api.bambulab.com",
        "en-US",
        "Europe/Berlin",
        "EU",
        "EUR",
    ),
    Region.UK: StoreConfig(
        Region.UK,
        "https://uk.store.bambulab.com",
        "https://eu-store-api.bambulab.com",
        "en-US",
        "Europe/London",
        "UK",
        "GBP",
    ),
    Region.AU: StoreConfig(
        Region.AU,
        "https://au.store.bambulab.com",
        "https://ap-store-api.bambulab.com",
        "en-US",
        "Australia/Sydney",
        "AU",
        "AUD",
    ),
    Region.JP: StoreConfig(
        Region.JP,
        "https://jp.store.bambulab.com",
        "https://ap-store-api.bambulab.com",
        "en-US",
        "Asia/Tokyo",
        "JP",
        "JPY",
    ),
    Region.KR: StoreConfig(
        Region.KR,
        "https://kr.store.bambulab.com",
        "https://ap-store-api.bambulab.com",
        "en-US",
        "Asia/Seoul",
        "KR",
        "KRW",
    ),
    Region.ASIA: StoreConfig(
        Region.ASIA,
        "https://asia.store.bambulab.com",
        "https://ap-store-api.bambulab.com",
        "en-US",
        "Asia/Singapore",
        "GLOBAL",
        "USD",
    ),
}

COLLECTION_PATH = "/collections/makers-supply?skr=yes"
SEARCH_PATH = "/mall-goods/product/aggregateGlobalSearchV2"
