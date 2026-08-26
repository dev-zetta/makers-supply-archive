from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote

from makers_supply.config import STORES
from makers_supply.discovery import ProductStub
from makers_supply.models import Product, Region
from makers_supply.parser import PART_NUMBER_PATTERN, ParsedProduct

REGION_ORDER = {region: index for index, region in enumerate(STORES)}


def slugify(value: str) -> str:
    value = unquote(value)
    ascii_value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", ascii_value.lower()).strip("-")[:100] or "product"


def primary_part_number(parsed: ParsedProduct) -> str | None:
    for variant in parsed.variants:
        matches: list[str] = PART_NUMBER_PATTERN.findall(variant.title)
        if matches:
            return matches[-1]
    return parsed.part_numbers[0] if len(parsed.part_numbers) == 1 else None


@dataclass(frozen=True)
class Observation:
    region: Region
    stub: ProductStub
    parsed: ParsedProduct


class AliasRegistry:
    def __init__(self, path: Path) -> None:
        payload = json.loads(path.read_text("utf-8")) if path.exists() else {}
        if not isinstance(payload, dict) or not all(
            isinstance(key, str) and isinstance(value, str) for key, value in payload.items()
        ):
            raise ValueError("config/aliases.json must map region:handle strings to product IDs")
        self.aliases: dict[str, str] = payload

    def get(self, region: Region, handle: str) -> str | None:
        return self.aliases.get(f"{region.value}:{handle}")


class Reconciler:
    def __init__(self, existing: list[Product], aliases: AliasRegistry) -> None:
        self.existing = {product.id: product for product in existing}
        self.aliases = aliases
        self.by_source: dict[str, str] = {}
        self.by_part: dict[str, set[str]] = {}
        self.used_ids = set(self.existing)
        for product in existing:
            for alias in product.aliases:
                self.by_source[f"{alias.region.value}:{alias.handle}"] = product.id
            for part in product.part_numbers:
                self.by_part.setdefault(part, set()).add(product.id)

    def existing_id(self, observation: Observation) -> str | None:
        explicit = self.aliases.get(observation.region, observation.stub.handle)
        if explicit:
            return explicit
        source_key = f"{observation.region.value}:{observation.stub.handle}"
        if source_key in self.by_source:
            return self.by_source[source_key]
        part = primary_part_number(observation.parsed)
        matches = self.by_part.get(part or "", set())
        return next(iter(matches)) if len(matches) == 1 else None

    def group_key(self, observation: Observation) -> str:
        if existing_id := self.existing_id(observation):
            return f"existing:{existing_id}"
        if part := primary_part_number(observation.parsed):
            return f"part:{part}"
        return f"handle:{slugify(observation.stub.handle)}"

    def new_id(self, observations: list[Observation]) -> str:
        canonical = min(observations, key=lambda item: REGION_ORDER[item.region])
        part = primary_part_number(canonical.parsed)
        base = slugify(f"{part}-{canonical.stub.handle}" if part else canonical.stub.handle)
        candidate = base
        counter = 2
        while candidate in self.used_ids:
            candidate = f"{base}-{counter}"
            counter += 1
        self.used_ids.add(candidate)
        return candidate
