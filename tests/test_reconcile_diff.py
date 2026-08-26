from datetime import UTC, datetime
from pathlib import Path

from makers_supply.diffing import diff_products
from makers_supply.discovery import ProductStub
from makers_supply.models import Product, Region, SourceAlias
from makers_supply.parser import ParsedProduct, ParsedVariant
from makers_supply.reconcile import (
    AliasRegistry,
    Observation,
    Reconciler,
    primary_part_number,
    slugify,
)

NOW = datetime(2026, 1, 2, tzinfo=UTC)


def observation(region: Region = Region.US, handle: str = "power-board") -> Observation:
    return Observation(
        region,
        ProductStub("123", handle, "Power Board", "USD", "5.29", ()),
        ParsedProduct(
            source_id="123",
            name="Power Board",
            description_html="",
            description_text="",
            part_numbers=("IA005", "ZH038"),
            variants=(ParsedVariant("99", "Power Board - IA005", "5.29", "USD", True, None, None),),
            assets=(),
            specifications={},
            box_contents=(),
            related_links=(),
        ),
    )


def product(active: bool = True) -> Product:
    return Product(
        id="ia005-power-board",
        name="Power Board",
        aliases=[SourceAlias(region=Region.US, handle="power-board", product_id="123")],
        first_seen=NOW,
        last_seen=NOW,
        active=active,
        removed_at=None if active else NOW,
    )


def test_primary_part_prefers_variant_title() -> None:
    assert primary_part_number(observation().parsed) == "IA005"


def test_reconciler_uses_existing_source_alias(tmp_path: Path) -> None:
    registry = AliasRegistry(tmp_path / "missing.json")
    reconciler = Reconciler([product()], registry)
    assert reconciler.group_key(observation()) == "existing:ia005-power-board"


def test_explicit_alias_overrides_identity(tmp_path: Path) -> None:
    path = tmp_path / "aliases.json"
    path.write_text('{"eu:netzteil": "power-supply"}')
    reconciler = Reconciler([], AliasRegistry(path))
    assert reconciler.group_key(observation(Region.EU, "netzteil")) == "existing:power-supply"


def test_diff_reports_lifecycle_change() -> None:
    result = diff_products([product()], [product(active=False)])
    assert result.removed == ["ia005-power-board"]
    assert result.changed == ["ia005-power-board"]


def test_slugify_decodes_percent_encoded_handles() -> None:
    assert slugify("waffentr%C3%A4ger") == "waffentrager"
