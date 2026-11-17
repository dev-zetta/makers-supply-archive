from __future__ import annotations

import json
import mimetypes
import re
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import PurePosixPath
from typing import Any, Protocol
from urllib.parse import parse_qs, unquote, urljoin, urlsplit

from bs4 import BeautifulSoup
from pydantic import HttpUrl

from makersfridge.assets import make_asset_id
from makersfridge.models import (
    Asset,
    AssetKind,
    CategoryAssignment,
    DescriptionBlock,
    Product,
    Provenance,
    Region,
    RegionalOffer,
    RelatedLink,
    SourceAlias,
    SourceTable,
    Variant,
)
from makersfridge.reconcile import slugify
from makersfridge.suppliers.catalog import PilotProduct


class PageClient(Protocol):
    def get(self, url: str, *, check_robots: bool = True) -> Any: ...


class SupplierAdapter(Protocol):
    def fetch(self, spec: PilotProduct, client: PageClient, now: datetime) -> Product: ...


def _records(value: object) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [record for item in value for record in _records(item)]
    if not isinstance(value, dict):
        return []
    records = [value]
    if "@graph" in value:
        records.extend(_records(value["@graph"]))
    return records


def structured_products(soup: BeautifulSoup) -> list[dict[str, Any]]:
    records = []
    for script in soup.select('script[type="application/ld+json"]'):
        try:
            records.extend(_records(json.loads(script.get_text())))
        except (ValueError, TypeError):
            continue
    return [r for r in records if r.get("@type") in ("Product", "ProductGroup")]


def _price(value: object) -> str | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        amount = Decimal(str(value))
    except InvalidOperation:
        return None
    return format(amount, "f") if amount.is_finite() and amount >= 0 else None


def _availability(value: object) -> bool | None:
    status = str(value).rstrip("/").rsplit("/", 1)[-1]
    if status in {"InStock", "LimitedAvailability", "OnlineOnly"}:
        return True
    if status in {"OutOfStock", "SoldOut", "Discontinued"}:
        return False
    return None


def _assets(spec: PilotProduct) -> list[Asset]:
    result = []
    for source in spec.assets:
        suffix = PurePosixPath(source.filename).suffix.lower()
        kind = (
            AssetKind.ARCHIVE
            if suffix in {".zip", ".7z", ".rar"}
            else AssetKind.IMAGE
            if source.role == "image"
            else AssetKind.DOCUMENT
            if suffix == ".pdf"
            else AssetKind.MODEL
        )
        result.append(
            Asset(
                id=make_asset_id(kind, str(source.url)),
                kind=kind,
                source_url=source.url,
                original_filename=source.filename,
                media_type=mimetypes.guess_type(source.filename)[0] or "application/octet-stream",
                **source.model_dump(exclude={"url", "filename", "compatibility_notes"}),
            )
        )
    return result


def reference_product(spec: PilotProduct, now: datetime) -> Product:
    notes = "\n\n".join(x for x in [spec.description, spec.compatibility_notes] if x)
    provenance = Provenance(
        kind="manual_override",
        reference="reviewed supplier pilot manifest",
        source_url=spec.product_url,
    )
    return Product(
        schema_version=5,
        id=spec.id,
        supplier_id=spec.supplier_id,
        manufacturer=spec.manufacturer,
        name=spec.name,
        hardware_revision=spec.hardware_revision,
        description_text=notes,
        description_blocks=[DescriptionBlock(kind="paragraph", text=notes)] if notes else [],
        categories=spec.categories,
        category_assignments=[
            CategoryAssignment(id=slugify(label), label=label, path=[label], provenance=provenance)
            for label in spec.categories
        ],
        skus=spec.skus,
        part_numbers=spec.part_numbers,
        assets=_assets(spec),
        tags=[spec.supplier_id],
        specifications={"Source review": spec.review_status},
        aliases=[
            SourceAlias(
                supplier_id=spec.supplier_id,
                store_id=spec.store_id,
                region=Region.GLOBAL,
                handle=str(spec.product_url),
            )
        ],
        related_links=[
            RelatedLink(title="Official product / source", url=spec.product_url),
            *[
                RelatedLink(title="Official documentation", url=url, kind="documentation")
                for url in spec.documentation_urls
            ],
        ],
        first_seen=now,
        last_seen=now,
    )


class ReferenceAdapter:
    def fetch(self, spec: PilotProduct, client: PageClient, now: datetime) -> Product:
        # A historical mechanical reference must not inherit a successor's shop offer.
        return reference_product(spec, now)


class StorefrontAdapter:
    def fetch(self, spec: PilotProduct, client: PageClient, now: datetime) -> Product:
        html = client.get(str(spec.product_url)).text
        soup = BeautifulSoup(html, "html.parser")
        records = structured_products(soup)
        if not records:
            if spec.source_kind == "waveshare":
                return _waveshare_options(spec, soup, now)
            raise ValueError(f"no structured product data at {spec.product_url}")
        product = reference_product(spec, now)
        parent = records[0]
        candidates = [record for r in records for record in _records(r.get("hasVariant", []))]
        if not candidates:
            candidates = records
        selected = set(spec.selected_skus or spec.skus)
        if selected:
            candidates = [r for r in candidates if str(r.get("sku", "")) in selected]
        if not candidates:
            raise ValueError(f"reviewed SKUs not found at {spec.product_url}; mapping needs review")
        store = spec.store_id or spec.supplier_id
        variants = []
        image_urls: list[str] = []
        for index, record in enumerate(candidates):
            raw_offers = record.get("offers")
            offers = _records(raw_offers)
            offer = offers[0] if offers else {}
            currency = str(offer.get("priceCurrency") or spec.default_currency or "")
            if not currency:
                raise ValueError("offer currency missing; refusing to infer currency from price")
            if len(currency) != 3 or not currency.isalpha():
                raise ValueError(f"invalid offer currency: {currency!r}")
            sku = str(record.get("sku") or "") or None
            url = urljoin(
                str(spec.product_url),
                str(offer.get("url") or record.get("url") or record.get("@id") or spec.product_url),
            )
            variant_id = parse_qs(urlsplit(url).query).get("variant", [""])[0]
            variant_id = variant_id or sku or f"option-{index}"
            images = record.get("image") or parent.get("image") or []
            if isinstance(images, (str, dict)):
                images = [images]
            for item in images:
                image = item.get("url", "") if isinstance(item, dict) else str(item)
                if image:
                    image_urls.append(urljoin(str(spec.product_url), image))
            variants.append(
                Variant(
                    region=Region.GLOBAL,
                    store_id=store,
                    variant_id=variant_id,
                    title=str(record.get("name") or spec.name),
                    sku=sku,
                    part_number=spec.part_numbers[0] if len(spec.part_numbers) == 1 else None,
                    price=_price(offer.get("price")),
                    currency=currency,
                    available=_availability(offer.get("availability")),
                    url=HttpUrl(url),
                    image_url=HttpUrl(image_urls[-1]) if image_urls else None,
                )
            )
        product.variants = variants
        if len({v.currency for v in variants}) != 1:
            raise ValueError("mixed currencies within one storefront offer")
        product.skus = list(dict.fromkeys([*spec.skus, *(v.sku for v in variants if v.sku)]))
        priced = [v for v in variants if v.price is not None]
        preferred = min(priced, key=lambda v: Decimal(v.price or "0")) if priced else variants[0]
        statuses = [v.available for v in variants]
        available = (
            True if True in statuses else False if all(x is False for x in statuses) else None
        )
        product.offers = [
            RegionalOffer(
                region=Region.GLOBAL,
                store_id=store,
                url=spec.product_url,
                currency=preferred.currency or "",
                price=preferred.price,
                available=available,
                retrieved_at=now,
            )
        ]
        product.aliases = [
            SourceAlias(
                supplier_id=spec.supplier_id,
                store_id=store,
                region=Region.GLOBAL,
                handle=urlsplit(str(spec.product_url)).path,
                product_id=str(parent.get("productGroupID") or parent.get("id") or "") or None,
            )
        ]
        raw_description = str(parent.get("description") or "")
        description = BeautifulSoup(raw_description, "html.parser").get_text(" ", strip=True)
        if description:
            text = "\n\n".join(x for x in [description, spec.compatibility_notes] if x)
            product.description_text = text
            product.description_blocks = [DescriptionBlock(kind="paragraph", text=text)]
        content = soup.select_one(".product-view, article, main") or soup
        for table in content.select("table")[:40]:
            rows = [
                [c.get_text(" ", strip=True) for c in row.select("th, td")]
                for row in table.select("tr")
            ]
            rows = [row for row in rows if row and any(row)]
            if not rows:
                continue
            product.source_tables.append(
                SourceTable(
                    rows=rows,
                    provenance=Provenance(
                        kind="page_table",
                        reference="official product table",
                        source_url=spec.product_url,
                    ),
                )
            )
            for row in rows:
                if len(row) == 2 and row[0] and len(row[0]) < 100:
                    product.specifications.setdefault(row[0], row[1])
        for url in dict.fromkeys(image_urls):
            filename = PurePosixPath(unquote(urlsplit(url).path)).name
            if filename:
                product.assets.append(
                    Asset(
                        id=make_asset_id(AssetKind.IMAGE, url),
                        kind=AssetKind.IMAGE,
                        source_url=HttpUrl(url),
                        original_filename=filename,
                        media_type=mimetypes.guess_type(filename)[0] or "application/octet-stream",
                        role="image",
                        applies_to_skus=product.skus,
                    )
                )
        return product


def _waveshare_options(spec: PilotProduct, soup: BeautifulSoup, now: datetime) -> Product:
    """Read Magento's explicit SKU map without evaluating storefront JavaScript.

    Family price ranges do not establish a selected SKU's price or inventory.
    """
    mappings: list[dict[str, Any]] = []
    for script in soup.select("script"):
        text = script.get_text()
        match = re.search(r"\b(?:var\s+)?waveshare_sku_attributes\s*=\s*", text)
        if match:
            value, _ = json.JSONDecoder().raw_decode(text[match.end() :].lstrip())
            mappings.extend(_records(value))
    wanted = set(spec.selected_skus or spec.skus)
    options = [r for r in mappings if str(r.get("sku ", r.get("sku", ""))) in wanted]
    if not options:
        raise ValueError(f"reviewed Waveshare SKUs not found at {spec.product_url}")
    currency = spec.default_currency
    if not currency:
        raise ValueError("configurable product needs a reviewed market currency")
    product = reference_product(spec, now)
    product.variants = [
        Variant(
            region=Region.GLOBAL,
            store_id=spec.store_id or "waveshare-global",
            variant_id=str(r.get("sku ", r.get("sku", ""))),
            sku=str(r.get("sku ", r.get("sku", ""))),
            title=" · ".join([spec.name, *(str(x) for x in r.get("attributes", []))]),
            currency=currency,
            url=spec.product_url,
        )
        for r in options
    ]
    product.offers = [
        RegionalOffer(
            region=Region.GLOBAL,
            store_id=spec.store_id or "waveshare-global",
            url=spec.product_url,
            currency=currency,
            retrieved_at=now,
        )
    ]
    image = soup.select_one('meta[property="og:image"]')
    source = str(image.get("content") or "") if image else ""
    if not source:
        image = soup.select_one('img[src*="media/catalog/product/"]')
        source = str(image.get("src") or "") if image else ""
    if source:
        url = urljoin(str(spec.product_url), source)
        filename = PurePosixPath(unquote(urlsplit(url).path)).name
        product.assets.append(
            Asset(
                id=make_asset_id(AssetKind.IMAGE, url),
                kind=AssetKind.IMAGE,
                source_url=HttpUrl(url),
                original_filename=filename,
                media_type=mimetypes.guess_type(filename)[0] or "application/octet-stream",
                role="image",
                applies_to_skus=list(wanted),
            )
        )
    return product


ADAPTERS: dict[str, SupplierAdapter] = {
    "reference": ReferenceAdapter(),
    "shopify": StorefrontAdapter(),
    "waveshare": StorefrontAdapter(),
}
