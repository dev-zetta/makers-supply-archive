from __future__ import annotations

import json
import re
import unicodedata
from decimal import Decimal, InvalidOperation
from difflib import SequenceMatcher
from pathlib import Path
from urllib.parse import unquote, urlsplit

from makers_supply.models import (
    BoxItem,
    CategoryAssignment,
    Measurement,
    Product,
    Provenance,
    RelatedLink,
)
from makers_supply.parser import (
    GENERIC_MAKERWORLD_TITLES,
    PART_NUMBER_PATTERN,
    makerworld_title_from_url,
    parse_description,
    parse_related_links,
)

MEASUREMENT_KEY = re.compile(
    r"(?:dimension|diameter|length|width|height|thickness|size|radius|pitch|travel)", re.I
)
VALUE_WITH_UNIT = re.compile(
    r"^\s*(?P<value>\d+(?:[.,]\d+)?)\s*(?P<unit>mm|cm|m|in|inch|inches|°|deg)\s*$",
    re.I,
)
SKU_PATTERN = re.compile(r"(?<!\d)\d{8,20}(?!\d)")
FUZZY_MATCH_THRESHOLD = 0.88
FUZZY_MATCH_MARGIN = 0.07
TECHNICAL_TOKEN = re.compile(r"(?=.*\d)[a-z0-9]+(?:x[a-z0-9]+)*$")


def _config(path: Path) -> dict[str, object]:
    if not path.exists():
        return {}
    value = json.loads(path.read_text("utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def category_for(product: Product, root: Path) -> CategoryAssignment:
    taxonomy = _config(root / "config" / "categories.json")
    overrides = _config(root / "config" / "catalog_overrides.json")
    product_override = overrides.get(product.id)
    if isinstance(product_override, dict) and isinstance(product_override.get("category"), str):
        category_id = product_override["category"]
        kind = "manual_override"
        reference = f"config/catalog_overrides.json:{product.id}"
    else:
        category_id = "uncategorized"
        kind = "classification_rule"
        reference = "fallback"
        haystack = f"{product.id} {product.name}".casefold()
        rules = taxonomy.get("rules", [])
        if isinstance(rules, list):
            for index, rule in enumerate(rules):
                if not isinstance(rule, dict):
                    continue
                pattern, candidate = rule.get("pattern"), rule.get("category")
                if (
                    isinstance(pattern, str)
                    and isinstance(candidate, str)
                    and re.search(pattern, haystack, re.I)
                ):
                    category_id = candidate
                    reference = f"config/categories.json:rules[{index}]"
                    break
    categories = taxonomy.get("categories", {})
    definition = categories.get(category_id, {}) if isinstance(categories, dict) else {}
    label = str(definition.get("label", category_id.replace("-", " ").title()))
    path_value = definition.get("path", [label])
    path = [str(item) for item in path_value] if isinstance(path_value, list) else [label]
    return CategoryAssignment(
        id=category_id,
        label=label,
        path=path,
        provenance=Provenance(kind=kind, reference=reference),  # type: ignore[arg-type]
    )


def tags_for(product: Product, root: Path) -> list[str]:
    taxonomy = _config(root / "config" / "categories.json")
    overrides = _config(root / "config" / "catalog_overrides.json")
    rules = taxonomy.get("tag_rules", [])
    managed = (
        {
            str(rule["tag"])
            for rule in rules
            if isinstance(rule, dict) and isinstance(rule.get("tag"), str)
        }
        if isinstance(rules, list)
        else set()
    )
    configured_managed = taxonomy.get("managed_tags", [])
    if isinstance(configured_managed, list):
        managed.update(str(tag) for tag in configured_managed if isinstance(tag, str))
    tags = [tag for tag in product.tags if tag not in managed]
    haystack = f"{product.id} {product.name} {product.description_text}"
    if isinstance(rules, list):
        for rule in rules:
            if not isinstance(rule, dict):
                continue
            pattern, tag = rule.get("pattern"), rule.get("tag")
            if (
                isinstance(pattern, str)
                and isinstance(tag, str)
                and re.search(pattern, haystack, re.I)
            ):
                tags.append(tag)
    product_override = overrides.get(product.id)
    if isinstance(product_override, dict) and isinstance(product_override.get("tags"), list):
        tags.extend(str(tag) for tag in product_override["tags"] if isinstance(tag, str))
    return list(dict.fromkeys(tags))


def box_contents_for(product: Product, root: Path) -> list[BoxItem]:
    """Apply reviewed package-content overrides after source HTML parsing."""
    overrides = _config(root / "config" / "catalog_overrides.json")
    product_override = overrides.get(product.id)
    if not isinstance(product_override, dict) or "box_contents" not in product_override:
        return product.box_contents
    raw_items = product_override["box_contents"]
    if not isinstance(raw_items, list):
        raise ValueError(f"box_contents override for {product.id} must be a JSON array")
    return [BoxItem.model_validate(item) for item in raw_items]


def measurements_for(product: Product) -> list[Measurement]:
    measurements: list[Measurement] = []
    source_url = next(
        (
            table.provenance.source_url
            for table in product.source_tables
            if table.provenance.source_url is not None
        ),
        None,
    )
    for label, raw_value in sorted(product.specifications.items()):
        if not MEASUREMENT_KEY.search(label):
            continue
        match = VALUE_WITH_UNIT.fullmatch(raw_value)
        numeric = None
        unit = None
        if match:
            try:
                numeric = Decimal(match.group("value").replace(",", "."))
            except InvalidOperation:
                numeric = None
            unit = match.group("unit")
        measurements.append(
            Measurement(
                label=label,
                raw_value=raw_value,
                numeric_value=numeric,
                unit=unit,
                provenance=Provenance(
                    kind="page_table",
                    reference=f"specification:{label}",
                    source_url=source_url,
                ),
            )
        )
    return measurements


def _description_data(product: Product) -> dict[str, object]:
    if not product.description_html:
        return {}
    source_url = next(
        (
            table.provenance.source_url
            for table in product.source_tables
            if table.provenance.source_url is not None
        ),
        None,
    )
    base_url = (
        str(source_url)
        if source_url is not None
        else (str(product.offers[0].url) if product.offers else None)
    )
    description, blocks, specifications, box_contents, source_tables = parse_description(
        product.description_html, fallback=product.description_text, base_url=base_url
    )
    return {
        "description_text": description,
        "description_blocks": list(blocks),
        "specifications": specifications,
        "box_contents": list(box_contents),
        "source_tables": list(source_tables),
    }


def _ascii(value: str) -> str:
    return unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()


def _name_key(value: str) -> str:
    value = re.sub(r"^\s*\d+\s*[.)-]\s*", "", value)
    value = re.sub(r"\(\s*\d+\s*(?:pcs?|pieces?|sets?)\s*\)", " ", _ascii(value), flags=re.I)
    value = re.sub(r"(?<=\d)[.,](?=\d)", "p", value)
    value = re.sub(
        r"\s*-\s*(?:(?:B-)?[A-Z]{1,3}\d{3}|[A-Z]\d[A-Z0-9]{0,4})\s*$",
        " ",
        value,
        flags=re.I,
    )
    tokens = re.findall(r"[a-z0-9]+", value.casefold())
    return " ".join(
        token[:-1] if token.endswith("s") and len(token) > 3 else token for token in tokens
    )


def _family_name_key(value: str) -> str:
    key = _name_key(value)
    if " kit" in f" {key}":
        key = re.sub(r"\s+0?\d{1,2}$", "", key)
    return key


def _related_links_for(product: Product) -> list[RelatedLink]:
    html_titles = {
        str(link.url): link.title for link in parse_related_links(product.description_html)
    }
    normalized: list[RelatedLink] = []
    for link in product.related_links:
        if link.kind != "makerworld":
            normalized.append(link)
            continue
        title = link.title.strip()
        if title.casefold().rstrip(" .:↗") in GENERIC_MAKERWORLD_TITLES:
            title = html_titles.get(str(link.url), makerworld_title_from_url(str(link.url)))
        if title.startswith("MakerWorld model #"):
            title = f"{product.name} project"
        normalized.append(link.model_copy(update={"title": title}))
    return normalized


def _unique_index(pairs: list[tuple[str, str]]) -> dict[str, str]:
    grouped: dict[str, set[str]] = {}
    for key, product_id in pairs:
        if key:
            grouped.setdefault(key, set()).add(product_id)
    return {key: next(iter(values)) for key, values in grouped.items() if len(values) == 1}


def _fastener_signature(value: str) -> tuple[str, str] | None:
    normalized = _ascii(value).casefold().replace("*", "x").replace("×", "x")
    size = re.search(r"\bm\s*(\d+(?:\.\d+)?)", normalized)
    kind = re.search(r"\b(bhcs|shcs|fhcs|shss)\b", normalized)
    return (f"m{size.group(1)}", kind.group(1)) if size and kind else None


def _product_name_keys(product: Product) -> set[str]:
    keys = {_name_key(product.name)}
    keys.update(_name_key(alias.handle.replace("-", " ")) for alias in product.aliases)
    prefix = re.compile(rf"^\s*{re.escape(product.name)}\s+-\s+", re.I)
    for variant in product.variants:
        keys.add(_name_key(prefix.sub("", variant.title, count=1)))
    return {key for key in keys if key}


def _technical_tokens(value: str) -> set[str]:
    return {token for token in value.split() if TECHNICAL_TOKEN.fullmatch(token)}


def _compatible_technical_tokens(query: str, candidate: str) -> bool:
    query_tokens = _technical_tokens(query)
    candidate_tokens = _technical_tokens(candidate)
    if not query_tokens or not candidate_tokens:
        return True
    return any(
        left == right
        or left.startswith(f"{right}x")
        or right.startswith(f"{left}x")
        for left in query_tokens
        for right in candidate_tokens
    )


def _fuzzy_score(query: str, candidate: str) -> float:
    query_tokens = set(query.split())
    candidate_tokens = set(candidate.split())
    if (
        len(query_tokens) < 2
        or len(candidate_tokens) < 2
        or not _compatible_technical_tokens(query, candidate)
    ):
        return 0.0
    union = query_tokens | candidate_tokens
    token_score = len(query_tokens & candidate_tokens) / len(union)
    sequence_score = SequenceMatcher(None, query, candidate).ratio()
    return sequence_score * 0.88 + token_score * 0.12


def _fuzzy_product_id(
    item_name: str, product_names: list[tuple[str, str, frozenset[str]]]
) -> str | None:
    query = _name_key(item_name)
    if len(query) < 8:
        return None
    query_tokens = set(query.split())
    required_overlap = 1 if len(query_tokens) < 3 else 2
    scores_by_product: dict[str, float] = {}
    for product_id, key, key_tokens in product_names:
        if len(query_tokens & key_tokens) < required_overlap:
            continue
        if min(len(query), len(key)) / max(len(query), len(key)) < 0.7:
            continue
        score = _fuzzy_score(query, key)
        scores_by_product[product_id] = max(score, scores_by_product.get(product_id, 0))
    scores = sorted((score, product_id) for product_id, score in scores_by_product.items())
    if not scores:
        return None
    best_score, best_id = scores[-1]
    runner_up = scores[-2][0] if len(scores) > 1 else 0.0
    if (
        best_score < FUZZY_MATCH_THRESHOLD
        or best_score - runner_up < FUZZY_MATCH_MARGIN
    ):
        return None
    return best_id


def _linked_box_items(products: list[Product]) -> list[Product]:
    handles = _unique_index(
        [(alias.handle.casefold(), product.id) for product in products for alias in product.aliases]
    )
    parts = _unique_index(
        [(part.casefold(), product.id) for product in products for part in product.part_numbers]
    )
    variant_parts = _unique_index(
        [
            (variant.part_number.casefold(), product.id)
            for product in products
            for variant in product.variants
            if variant.part_number
        ]
    )
    skus = _unique_index(
        [
            (sku.casefold(), product.id)
            for product in products
            for sku in [
                *product.skus,
                *(variant.sku for variant in product.variants if variant.sku),
            ]
        ]
    )
    names = _unique_index([(_name_key(product.name), product.id) for product in products])
    families = _unique_index(
        [(_family_name_key(product.name), product.id) for product in products]
    )
    fasteners = _unique_index(
        [
            ("|".join(signature), product.id)
            for product in products
            if (signature := _fastener_signature(product.name))
        ]
    )
    fuzzy_names = [
        (product.id, key, frozenset(key.split()))
        for product in products
        for key in _product_name_keys(product)
    ]

    updated: list[Product] = []
    for product in products:
        items: list[BoxItem] = []
        for item in product.box_contents:
            linked_id = None
            if item.source_url:
                segments = [
                    unquote(segment) for segment in urlsplit(str(item.source_url)).path.split("/")
                ]
                if "products" in segments:
                    index = segments.index("products")
                    if index + 1 < len(segments):
                        linked_id = handles.get(segments[index + 1].casefold())
            if linked_id is None:
                matches = PART_NUMBER_PATTERN.findall(f"{item.item_number or ''} {item.name}")
                candidates = {
                    variant_parts[match.casefold()]
                    for match in matches
                    if match.casefold() in variant_parts
                }
                if len(candidates) == 1:
                    linked_id = next(iter(candidates))
            if linked_id is None:
                sku_matches = SKU_PATTERN.findall(f"{item.item_number or ''} {item.name}")
                candidates = {
                    skus[match.casefold()] for match in sku_matches if match.casefold() in skus
                }
                if len(candidates) == 1:
                    linked_id = next(iter(candidates))
            if linked_id is None:
                matches = PART_NUMBER_PATTERN.findall(f"{item.item_number or ''} {item.name}")
                candidates = {
                    parts[match.casefold()] for match in matches if match.casefold() in parts
                }
                if len(candidates) == 1:
                    linked_id = next(iter(candidates))
            # Page-wide part-number extraction can include a kit's component codes.
            # Do not let those codes incorrectly resolve a component to its parent kit.
            if linked_id == product.id:
                linked_id = None
            if linked_id is None:
                linked_id = names.get(_name_key(item.name))
            if linked_id is None:
                linked_id = families.get(_family_name_key(item.name))
            if linked_id is None and (signature := _fastener_signature(item.name)):
                linked_id = fasteners.get("|".join(signature))
            if linked_id is None:
                linked_id = _fuzzy_product_id(item.name, fuzzy_names)
            items.append(item.model_copy(update={"linked_product_id": linked_id}))
        updated.append(product.model_copy(update={"box_contents": items}))
    return updated


def enrich_product(product: Product, root: Path) -> Product:
    described = product.model_copy(update=_description_data(product))
    described = described.model_copy(update={"related_links": _related_links_for(described)})
    described = described.model_copy(update={"box_contents": box_contents_for(described, root)})
    assignment = category_for(described, root)
    described = described.model_copy(update={"tags": tags_for(described, root)})
    return described.model_copy(
        update={
            "schema_version": 4,
            "categories": [assignment.label],
            "category_assignments": [assignment],
            "measurements": measurements_for(described),
        }
    )


def enrich_products(products: list[Product], root: Path) -> list[Product]:
    """Apply per-record enrichment and cross-catalog component links."""
    linked = _linked_box_items([enrich_product(product, root) for product in products])
    # Explicit reviewed package rows and links are authoritative over inferred matches.
    return [
        product.model_copy(update={"box_contents": box_contents_for(product, root)})
        for product in linked
    ]
