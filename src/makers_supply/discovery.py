from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

from pydantic import TypeAdapter

from makers_supply.config import COLLECTION_PATH, SEARCH_PATH, StoreConfig
from makers_supply.http import ArchiveHttpClient

SERIES_ID_PATTERN = re.compile(r'(?:seriesId|pageProductSeriesId)\\?"\s*:\s*\\?"(\d+)')


@dataclass(frozen=True)
class ProductStub:
    source_id: str
    handle: str
    name: str
    currency: str
    price: str | None
    image_urls: tuple[str, ...]


def extract_series_id(html: str) -> str:
    match = SERIES_ID_PATTERN.search(html)
    if match is None:
        raise ValueError("Maker's Supply series ID was not found in the collection page")
    return match.group(1)


def _headers(store: StoreConfig) -> dict[str, str]:
    return {
        "Accept": "application/json, text/plain, */*",
        "Bbl-Locale": store.locale,
        "X-BBL-TIME-ZONE": store.timezone,
        "X-BBL-STORE-REGION": store.header_region,
    }


def _string_price(value: object) -> str | None:
    if value is None:
        return None
    return str(value)


def _parse_stub(record: dict[str, Any], store: StoreConfig) -> ProductStub:
    strings = TypeAdapter(list[str])
    return ProductStub(
        source_id=str(record["id"]),
        handle=str(record["seoCode"]),
        name=str(record["name"]),
        currency=str(record.get("currency") or store.default_currency),
        price=_string_price(record.get("lowerPrice") or record.get("price")),
        image_urls=tuple(strings.validate_python(record.get("mediaFiles") or [])),
    )


def discover_products(
    client: ArchiveHttpClient, store: StoreConfig, *, page_size: int = 100
) -> list[ProductStub]:
    collection_url = f"{store.store_url}{COLLECTION_PATH}"
    series_id = extract_series_id(client.get(collection_url).text)
    endpoint = f"{store.api_url}{SEARCH_PATH}"
    records: list[dict[str, Any]] = []
    current = 1
    total = 1
    while len(records) < total:
        response = client.request(
            "POST",
            endpoint,
            headers=_headers(store),
            json={"current": current, "size": page_size, "pageProductSeriesId": series_id},
        ).json()
        if not isinstance(response, dict) or not isinstance(response.get("data"), dict):
            raise ValueError(f"catalog API error: {response!r}")
        page = response["data"].get("productGlobalSearchVOIPage")
        if not isinstance(page, dict):
            raise ValueError(f"catalog API returned an invalid page: {page!r}")
        batch = page.get("records")
        if not isinstance(batch, list) or not all(isinstance(item, dict) for item in batch):
            raise ValueError("catalog API returned an invalid records list")
        total_value = page.get("total")
        if isinstance(total_value, bool) or not isinstance(total_value, (str, int)):
            raise ValueError("catalog API returned a missing or invalid total")
        if not re.fullmatch(r"\d+", str(total_value)):
            raise ValueError("catalog API returned an invalid total")
        total = int(total_value)
        records.extend(batch)
        if len(records) > total:
            raise ValueError("catalog API returned more records than its total")
        if not batch and len(records) < total:
            raise ValueError(f"catalog API ended after {len(records)} of {total} products")
        current += 1
    unique: dict[str, ProductStub] = {}
    for record in records:
        stub = _parse_stub(record, store)
        unique[stub.handle] = stub
    return [unique[key] for key in sorted(unique)]


def product_url(store: StoreConfig, handle: str) -> str:
    return f"{store.store_url}/en/products/{quote(handle, safe='%')}?skr=yes"
