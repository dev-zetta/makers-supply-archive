from __future__ import annotations

import json
import mimetypes
import re
from dataclasses import dataclass
from pathlib import PurePosixPath
from urllib.parse import parse_qs, unquote, urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup, Tag
from pydantic import HttpUrl

from makers_supply.models import (
    AssetKind,
    BoxItem,
    BoxItemQuantity,
    DescriptionBlock,
    Provenance,
    RelatedLink,
    SourceTable,
)

PART_NUMBER_PATTERN = re.compile(r"(?<![A-Z0-9])(?:B-)?[A-Z]{1,3}\d{3}(?![A-Z0-9])")
DOWNLOAD_SUFFIXES = {
    ".3mf",
    ".7z",
    ".dxf",
    ".dwg",
    ".iges",
    ".igs",
    ".pdf",
    ".rar",
    ".step",
    ".stl",
    ".stp",
    ".zip",
}
ARCHIVE_SUFFIXES = {".7z", ".rar", ".zip"}
IMAGE_SUFFIXES = {".avif", ".gif", ".jpeg", ".jpg", ".png", ".webp"}
DESCRIPTION_END_HEADING = re.compile(
    r"^(?:in the box|what(?:'s| is) in the box|box contents?|package contents?|"
    r"(?:product )?specifications?|technical (?:data|specifications?)|parameters?|documentation|"
    r"downloads?|dimensions?|3d models?|application instructions?|assembly instructions?|"
    r"models? list)$",
    re.I,
)
ITEM_HEADERS = {"item", "item name", "name", "product", "component"}
ITEM_NUMBER_HEADERS = {"item number", "part number", "sku", "model", "model number"}
QUANTITY_HEADERS = {"qty", "quantity", "q ty", "count"}
POSITION_HEADERS = {"#", "no", "number", "position"}
QUANTITY_VALUE = re.compile(
    r"^(?:[-—–]|n/?a|(?:✅|❌)?\s*\d+(?:[.,]\d+)?(?:\s*(?:pcs?|pieces?|sets?|"
    r"packs?|pairs?|units?|m|cm|mm))?)$",
    re.I,
)
GENERIC_MAKERWORLD_TITLES = {
    "click here",
    "here",
    "makerworld",
    "makerworld model",
    "model",
    "note",
    "no",
    "yes",
}
MAKERWORLD_TITLE_WORDS = {
    "3d": "3D",
    "cyberbrick": "CyberBrick",
    "diy": "DIY",
    "rc": "RC",
    "v8": "V8",
}


@dataclass(frozen=True)
class ParsedVariant:
    variant_id: str
    title: str
    price: str | None
    currency: str | None
    available: bool | None
    url: str | None
    image_url: str | None
    compare_at_price: str | None = None


@dataclass(frozen=True)
class ParsedAsset:
    url: str
    filename: str
    media_type: str
    kind: AssetKind


@dataclass(frozen=True)
class ParsedProduct:
    source_id: str | None
    name: str
    description_html: str
    description_text: str
    part_numbers: tuple[str, ...]
    variants: tuple[ParsedVariant, ...]
    assets: tuple[ParsedAsset, ...]
    specifications: dict[str, str]
    box_contents: tuple[BoxItem, ...]
    related_links: tuple[RelatedLink, ...]
    source_tables: tuple[SourceTable, ...] = ()
    description_blocks: tuple[DescriptionBlock, ...] = ()


def _schema_product(soup: BeautifulSoup) -> dict[str, object]:
    for script in soup.select('script[type="application/ld+json"]'):
        try:
            value = json.loads(script.get_text())
        except (TypeError, json.JSONDecodeError):
            continue
        if isinstance(value, dict) and value.get("@type") in {"Product", "ProductGroup"}:
            return value
    raise ValueError("product JSON-LD was not found")


def _canonical_asset_url(url: str) -> str:
    parts = urlsplit(url)
    path = parts.path.split("__op__", 1)[0]
    return urlunsplit((parts.scheme, parts.netloc, path, "", ""))


def _filename(url: str, fallback: str) -> str:
    name = PurePosixPath(unquote(urlsplit(url).path)).name
    return name if name not in {"", ".", ".."} else fallback


def _asset_kind(suffix: str) -> AssetKind:
    if suffix in IMAGE_SUFFIXES:
        return AssetKind.IMAGE
    if suffix in ARCHIVE_SUFFIXES:
        return AssetKind.ARCHIVE
    if suffix == ".pdf":
        return AssetKind.DOCUMENT
    if suffix in DOWNLOAD_SUFFIXES:
        return AssetKind.MODEL
    return AssetKind.OTHER


def _parsed_asset(url: str, fallback: str) -> ParsedAsset:
    url = _canonical_asset_url(url)
    filename = _filename(url, fallback)
    suffix = PurePosixPath(filename).suffix.lower()
    media_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    return ParsedAsset(url, filename, media_type, _asset_kind(suffix))


def _variant(value: object) -> ParsedVariant | None:
    if not isinstance(value, dict):
        return None
    offer = value.get("offers")
    offer = offer if isinstance(offer, dict) else {}
    availability = str(offer.get("availability", ""))
    available = None
    if availability:
        available = availability.endswith("/InStock")
    return ParsedVariant(
        variant_id=str(value.get("sku") or ""),
        title=str(value.get("name") or ""),
        price=None if offer.get("price") is None else str(offer["price"]),
        currency=None if offer.get("priceCurrency") is None else str(offer["priceCurrency"]),
        available=available,
        url=None if offer.get("url") is None else str(offer["url"]),
        image_url=None if value.get("image") is None else str(value["image"]),
        compare_at_price=(None if offer.get("highPrice") is None else str(offer["highPrice"])),
    )


def _description_containers(soup: BeautifulSoup) -> list[Tag]:
    """Return official content sections once, preserving their document order."""
    return [
        tag
        for tag in soup.select("div.pct")
        if tag.find_parent("div", class_="pct") is None
        and tag.find(["h1", "h2", "h3", "h4", "h5", "h6", "p", "li", "table"])
        is not None
    ]


def _normalized_header(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()


def _clean_text(value: str) -> str:
    value = re.sub(r"\s+", " ", value.replace("\xa0", " ")).strip()
    return re.sub(r"\s+([,.:;!?])", r"\1", value)


def _is_generic_makerworld_title(value: str) -> bool:
    return _clean_text(value).casefold().rstrip(" .:↗") in GENERIC_MAKERWORLD_TITLES


def _humanize_makerworld_slug(value: str) -> str:
    words = re.split(r"[-_]+", unquote(value).strip("-_/"))
    return " ".join(
        MAKERWORLD_TITLE_WORDS.get(word.casefold(), word.capitalize())
        for word in words
        if word
    )


def makerworld_title_from_url(url: str) -> str:
    """Return a stable descriptive title when a MakerWorld link has generic text."""
    parts = urlsplit(url)
    query_name = parse_qs(parts.query).get("name", [])
    if query_name and query_name[0].strip():
        return _clean_text(query_name[0])
    leaf = PurePosixPath(parts.path).name
    match = re.fullmatch(r"(?P<id>\d+)(?:-(?P<slug>.+))?", leaf)
    if match and match.group("slug"):
        return _humanize_makerworld_slug(match.group("slug"))
    if match:
        return f"MakerWorld model #{match.group('id')}"
    title = _humanize_makerworld_slug(leaf)
    return title or "MakerWorld model"


def _makerworld_context_title(anchor: Tag) -> str | None:
    cell = anchor.find_parent(["td", "th"])
    if isinstance(cell, Tag):
        cell_text = _clean_text(cell.get_text(" ", strip=True))
        if cell_text and not _is_generic_makerworld_title(cell_text):
            return cell_text
        row = cell.find_parent("tr")
        if isinstance(row, Tag):
            for sibling in row.find_all(["td", "th"], recursive=False):
                candidate = _clean_text(sibling.get_text(" ", strip=True))
                if (
                    candidate
                    and not candidate.isdigit()
                    and not _is_generic_makerworld_title(candidate)
                ):
                    return candidate
    container = anchor.find_parent(["p", "div"])
    if isinstance(container, Tag):
        candidates = [
            _clean_text(tag.get_text(" ", strip=True))
            for tag in container.find_all(["strong", "b"])
        ]
        candidates = [
            candidate
            for candidate in candidates
            if candidate and not _is_generic_makerworld_title(candidate)
        ]
        if candidates:
            return max(candidates, key=len)
    return None


def _makerworld_links(soup: BeautifulSoup | Tag) -> tuple[RelatedLink, ...]:
    related: dict[str, RelatedLink] = {}
    for anchor in soup.find_all("a", href=True):
        href = anchor.get("href")
        if not isinstance(href, str) or not href.startswith(("http://", "https://")):
            continue
        hostname = (urlsplit(href).hostname or "").lower()
        if hostname != "makerworld.com" and not hostname.endswith(".makerworld.com"):
            continue
        anchor_title = _clean_text(anchor.get_text(" ", strip=True))
        if not anchor_title:
            image = anchor.find("img", alt=True)
            if isinstance(image, Tag) and isinstance(image.get("alt"), str):
                anchor_title = _clean_text(str(image["alt"]))
        if anchor_title and not _is_generic_makerworld_title(anchor_title):
            title = anchor_title
        else:
            url_title = makerworld_title_from_url(href)
            title = (
                _makerworld_context_title(anchor)
                if url_title.startswith("MakerWorld model #")
                else url_title
            ) or url_title
        candidate = RelatedLink(title=title, url=HttpUrl(href), kind="makerworld")
        previous = related.get(href)
        previous_is_placeholder = previous is not None and (
            _is_generic_makerworld_title(previous.title)
            or previous.title.startswith("MakerWorld model #")
        )
        candidate_is_placeholder = _is_generic_makerworld_title(
            candidate.title
        ) or candidate.title.startswith("MakerWorld model #")
        if previous is None or (previous_is_placeholder and not candidate_is_placeholder):
            related[href] = candidate
    return tuple(related.values())


def parse_related_links(html: str) -> tuple[RelatedLink, ...]:
    """Extract named MakerWorld links from an HTML fragment."""
    return _makerworld_links(BeautifulSoup(html, "html.parser"))


def _variant_quantity_columns(headers: list[str], rows: list[list[str]]) -> list[int]:
    """Find variant quantity columns without treating arbitrary wide tables as packages."""
    normalized = [_normalized_header(header) for header in headers]
    excluded = ITEM_HEADERS | ITEM_NUMBER_HEADERS | POSITION_HEADERS
    candidates = [index for index, header in enumerate(normalized) if header not in excluded]
    values = [
        row[index].strip()
        for row in rows
        for index in candidates
        if index < len(row) and row[index].strip()
    ]
    if not candidates or not values:
        return []
    matching = sum(bool(QUANTITY_VALUE.fullmatch(value)) for value in values)
    return candidates if matching / len(values) >= 0.8 else []


def _description_blocks(container: Tag | None) -> list[DescriptionBlock]:
    if container is None:
        return []
    blocks: list[DescriptionBlock] = []
    include = True
    block_tags = ["h1", "h2", "h3", "h4", "h5", "h6", "p", "li"]
    for element in container.find_all([*block_tags, "div"]):
        if element.find_parent(["table", "style", "script"]):
            continue
        name = element.name.casefold()
        if name == "div" and element.find(block_tags + ["table"]):
            continue
        text = _clean_text(element.get_text(" ", strip=True))
        if not text:
            continue
        if name.startswith("h") and len(name) == 2 and name[1].isdigit():
            if DESCRIPTION_END_HEADING.fullmatch(text):
                include = False
                continue
            include = True
            kind = "heading"
        elif name == "li":
            kind = "bullet"
        else:
            kind = "paragraph"
        if not include:
            continue
        if not blocks or blocks[-1].text != text:
            blocks.append(DescriptionBlock(kind=kind, text=text))  # type: ignore[arg-type]

    # Image-only marketing headings are not useful without their source layout.
    useful: list[DescriptionBlock] = []
    for index, block in enumerate(blocks):
        if block.kind != "heading" or any(
            candidate.kind != "heading" for candidate in blocks[index + 1 : index + 2]
        ):
            useful.append(block)
    while useful and useful[-1].kind == "heading":
        useful.pop()
    return useful


def _clean_fallback_description(value: str) -> str:
    return _clean_text(BeautifulSoup(value, "html.parser").get_text(" ", strip=True))


def _tables(
    container: Tag | None,
    base_url: str | None = None,
) -> tuple[dict[str, str], list[BoxItem], list[SourceTable]]:
    specifications: dict[str, str] = {}
    box_contents: list[BoxItem] = []
    source_tables: list[SourceTable] = []
    if container is None:
        return specifications, box_contents, source_tables
    for position, table in enumerate(container.find_all("table")):
        rows: list[list[str]] = []
        row_tags: list[list[Tag]] = []
        for row in table.find_all("tr"):
            tags = list(row.find_all(["th", "td"]))
            cells = [cell.get_text(" ", strip=True) for cell in tags]
            if cells:
                rows.append(cells)
                row_tags.append(tags)
        if not rows:
            continue
        caption_tag = table.find("caption")
        first_row = table.find("tr")
        normalized_first_row = [_normalized_header(cell) for cell in rows[0]]
        known_headers = ITEM_HEADERS | ITEM_NUMBER_HEADERS | QUANTITY_HEADERS
        inferred_headers = sum(cell in known_headers for cell in normalized_first_row) >= 2
        first_row_has_headers = bool(
            first_row is not None
            and (
                first_row.find("th")
                or first_row.find_parent("thead") is not None
                or inferred_headers
            )
        )
        headers = rows[0] if first_row_has_headers else []
        data_rows = rows[1:] if first_row_has_headers else rows
        previous_heading = table.find_previous(["h1", "h2", "h3", "h4", "h5", "h6"])
        caption = (
            caption_tag.get_text(" ", strip=True)
            if caption_tag is not None
            else (
                previous_heading.get_text(" ", strip=True)
                if previous_heading is not None
                else None
            )
        )
        source_tables.append(
            SourceTable(
                caption=caption,
                headers=headers,
                rows=data_rows,
                provenance=Provenance(
                    kind="page_table",
                    reference=f"table:{position}",
                    source_url=HttpUrl(base_url) if base_url else None,
                ),
            )
        )
        header = normalized_first_row if first_row_has_headers else []
        item_index = next(
            (index for index, cell in enumerate(header) if cell in ITEM_HEADERS), None
        )
        quantity_index = next(
            (index for index, cell in enumerate(header) if cell in QUANTITY_HEADERS), None
        )
        item_number_index = next(
            (index for index, cell in enumerate(header) if cell in ITEM_NUMBER_HEADERS), None
        )
        variant_quantity_columns = (
            _variant_quantity_columns(headers, data_rows)
            if item_index is not None and quantity_index is None
            else []
        )
        if item_index is not None and (quantity_index is not None or variant_quantity_columns):
            for cells, tags in zip(rows[1:], row_tags[1:], strict=True):
                required_indexes = [item_index]
                if quantity_index is not None:
                    required_indexes.append(quantity_index)
                if max(required_indexes) >= len(cells) or not cells[item_index]:
                    continue
                anchor = tags[item_index].find("a", href=True)
                href = anchor.get("href") if anchor is not None else None
                source_url = urljoin(base_url, href) if base_url and isinstance(href, str) else href
                if not isinstance(source_url, str) or not source_url.startswith(
                    ("http://", "https://")
                ):
                    source_url = None
                box_contents.append(
                    BoxItem(
                        item_number=(
                            cells[item_number_index]
                            if item_number_index is not None
                            and item_number_index < len(cells)
                            and cells[item_number_index]
                            else None
                        ),
                        name=cells[item_index],
                        quantity=(
                            cells[quantity_index] or None if quantity_index is not None else None
                        ),
                        variant_quantities=[
                            BoxItemQuantity(variant=headers[index], quantity=cells[index])
                            for index in variant_quantity_columns
                            if index < len(cells) and cells[index]
                        ],
                        source_url=HttpUrl(source_url) if source_url else None,
                    )
                )
        elif headers and len(data_rows) == 1 and len(headers) == len(data_rows[0]):
            for name, value in zip(headers, data_rows[0], strict=True):
                if name and value:
                    specifications.setdefault(name, value)
        else:
            for cells in data_rows:
                if len(cells) == 2 and cells[0] and cells[1]:
                    specifications.setdefault(cells[0], cells[1])
    return specifications, box_contents, source_tables


def parse_description(
    html: str, fallback: str = "", base_url: str | None = None
) -> tuple[
    str,
    tuple[DescriptionBlock, ...],
    dict[str, str],
    tuple[BoxItem, ...],
    tuple[SourceTable, ...],
]:
    """Normalize the narrative and structured tables from a stored description fragment."""
    fragment = BeautifulSoup(f"<div class='pct'>{html}</div>", "html.parser")
    container = fragment.select_one("div.pct")
    blocks = _description_blocks(container)
    narrative = "\n\n".join(block.text for block in blocks if block.kind != "heading")
    description_text = narrative or _clean_fallback_description(fallback)
    specifications, box_contents, source_tables = _tables(container, base_url)
    return (
        description_text,
        tuple(blocks),
        specifications,
        tuple(box_contents),
        tuple(source_tables),
    )


def parse_product_page(html: str) -> ParsedProduct:
    soup = BeautifulSoup(html, "html.parser")
    schema = _schema_product(soup)
    name = str(schema.get("name") or "").strip()
    if not name:
        raise ValueError("product name is empty")
    raw_variants = schema.get("hasVariant")
    if not isinstance(raw_variants, list):
        raw_variants = [schema]
    variants = tuple(item for value in raw_variants if (item := _variant(value)) is not None)
    base_url = next((variant.url for variant in variants if variant.url), None)
    containers = _description_containers(soup)
    description_html = "\n".join(str(container) for container in containers).strip()
    fallback_description = str(schema.get("description") or "").strip()

    assets_by_url: dict[str, ParsedAsset] = {}
    for variant in variants:
        if variant.image_url:
            asset = _parsed_asset(variant.image_url, "product-image")
            assets_by_url[asset.url] = asset
    for image in soup.find_all("img", alt=name):
        source = image.get("data-src") or image.get("src")
        if isinstance(source, str) and source.startswith("http"):
            asset = _parsed_asset(source, "product-image")
            assets_by_url[asset.url] = asset
    for anchor in soup.find_all("a", href=True):
        href = anchor.get("href")
        if not isinstance(href, str):
            continue
        absolute_href = urljoin(base_url, href) if base_url else href
        if not absolute_href.startswith(("http://", "https://")):
            continue
        suffix = PurePosixPath(urlsplit(absolute_href).path).suffix.lower()
        if suffix in DOWNLOAD_SUFFIXES:
            asset = _parsed_asset(absolute_href, "download")
            assets_by_url[asset.url] = asset

    (
        description_text,
        description_blocks,
        specifications,
        box_contents,
        source_tables,
    ) = parse_description(description_html, fallback_description, base_url)
    part_source = f"{soup.get_text(' ', strip=True)} {json.dumps(schema, ensure_ascii=False)}"
    part_numbers = sorted(set(PART_NUMBER_PATTERN.findall(part_source)))
    return ParsedProduct(
        source_id=None if schema.get("productGroupID") is None else str(schema["productGroupID"]),
        name=name,
        description_html=description_html,
        description_text=description_text,
        description_blocks=description_blocks,
        part_numbers=tuple(part_numbers),
        variants=variants,
        assets=tuple(assets_by_url.values()),
        specifications=specifications,
        box_contents=tuple(box_contents),
        related_links=_makerworld_links(soup),
        source_tables=tuple(source_tables),
    )
