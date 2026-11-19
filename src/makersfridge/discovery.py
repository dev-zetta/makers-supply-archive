from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

import httpx
from bs4 import BeautifulSoup
from pydantic import TypeAdapter

from makersfridge.config import COLLECTION_PATH, SEARCH_PATH, StoreConfig
from makersfridge.http import ArchiveHttpClient

SERIES_ID_PATTERN = re.compile(r'(?:seriesId|pageProductSeriesId)\\?"\s*:\s*\\?"(\d+)')
COLLECTION_CHUNK = re.compile(r"\s*self\.__next_f\.push\((.*)\)\s*;?\s*", re.S)
COLLECTION_PAGE = re.compile(r'\{"size":\d+,"initialPage":\d+,')


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
        raise ValueError("Maker's Fridge series ID was not found in the collection page")
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


def _collection_page(html: str, series_id: str, page: int) -> tuple[int, int, list[dict[str, Any]]]:
    # The storefront can split a single JSON record across multiple script elements.
    chunks = []
    for script in BeautifulSoup(html, "html.parser").find_all("script", string=True):
        match = COLLECTION_CHUNK.fullmatch(str(script.string))
        if match:
            chunk = json.loads(match[1])
            if (
                isinstance(chunk, list) and len(chunk) == 2 and chunk[0] == 1
                and isinstance(chunk[1], str)
            ):
                chunks.append(chunk[1])
    payload = "".join(chunks)
    decoder = json.JSONDecoder()
    candidates = []
    for match in COLLECTION_PAGE.finditer(payload):
        props, _ = decoder.raw_decode(payload, match.start())
        if props.get("seriesId") == series_id and "productList" in props:
            candidates.append(props)
    if len(candidates) != 1 or candidates[0]["initialPage"] != page:
        raise ValueError(f"storefront collection is missing the expected page {page}")
    props = candidates[0]
    total, size, records = props.get("total"), props["size"], props["productList"]
    if (
        type(total) is not int or total < 0 or size < 1
        or not isinstance(records, list) or not all(isinstance(record, dict) for record in records)
        or len(records) != min(size, max(0, total - (page - 1) * size))
    ):
        raise ValueError(f"storefront collection page {page} is incomplete or invalid")
    return total, size, records


def _discover_collection(
    client: ArchiveHttpClient, store: StoreConfig, url: str, html: str, series_id: str
) -> list[ProductStub]:
    total, size, records = _collection_page(html, series_id, 1)
    for page in range(2, (total + size - 1) // size + 1):
        page_html = client.get(f"{url}&page={page}").text
        page_total, page_size, batch = _collection_page(page_html, series_id, page)
        if (page_total, page_size) != (total, size):
            raise ValueError("storefront collection changed while paginating")
        records.extend(batch)
    products = [_parse_stub(record, store) for record in records]
    if len({product.handle for product in products}) != total:
        raise ValueError("storefront collection contains duplicate product handles")
    return sorted(products, key=lambda product: product.handle)


def discover_products(
    client: ArchiveHttpClient, store: StoreConfig, *, page_size: int = 100
) -> list[ProductStub]:
    collection_url = f"{store.store_url}{COLLECTION_PATH}"
    collection_html = client.get(collection_url).text
    series_id = extract_series_id(collection_html)
    endpoint = f"{store.api_url}{SEARCH_PATH}"
    records: list[dict[str, Any]] = []
    current = 1
    total = 1
    while len(records) < total:
        try:
            response = client.request(
                "POST",
                endpoint,
                headers=_headers(store),
                json={"current": current, "size": page_size, "pageProductSeriesId": series_id},
            ).json()
        except httpx.HTTPStatusError as error:
            if current != 1 or error.response.status_code != 404:
                raise
            return _discover_collection(client, store, collection_url, collection_html, series_id)
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
