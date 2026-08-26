from datetime import UTC, datetime
from pathlib import Path

from makers_supply.enrichment import enrich_product, enrich_products
from makers_supply.models import (
    BoxItem,
    Product,
    Region,
    RegionalOffer,
    RelatedLink,
    SourceAlias,
    Variant,
)


def test_enrichment_assigns_category_and_provenanced_measurements(tmp_path: Path) -> None:
    config = tmp_path / "config"
    config.mkdir()
    (config / "categories.json").write_text(
        '{"categories":{"electronics":{"label":"Electronics","path":["Electronics"]},'
        '"uncategorized":{"label":"Uncategorized"}},'
        '"rules":[{"pattern":"board","category":"electronics"}]}',
        encoding="utf-8",
    )
    (config / "catalog_overrides.json").write_text("{}", encoding="utf-8")
    now = datetime(2026, 1, 2, tzinfo=UTC)
    product = Product(
        id="ia005-power-board",
        name="Power board",
        specifications={"Width": "25 mm", "Voltage": "5 V"},
        first_seen=now,
        last_seen=now,
    )
    enriched = enrich_product(product, tmp_path)
    assert enriched.schema_version == 4
    assert enriched.categories == ["Electronics"]
    assert enriched.category_assignments[0].provenance.kind == "classification_rule"
    assert enriched.measurements[0].numeric_value == 25
    assert enriched.measurements[0].unit == "mm"


def test_enrichment_tags_kits_and_links_box_items(tmp_path: Path) -> None:
    config = tmp_path / "config"
    config.mkdir()
    (config / "categories.json").write_text(
        '{"categories":{"uncategorized":{"label":"Uncategorized"}},"rules":[],'
        '"tag_rules":[{"pattern":"non-3D printed parts for assembling","tag":"kit"}]}',
        encoding="utf-8",
    )
    (config / "catalog_overrides.json").write_text("{}", encoding="utf-8")
    timestamp = datetime(2026, 1, 2, tzinfo=UTC)
    component = Product(
        id="ia005-power-board",
        name="Power board",
        aliases=[SourceAlias(region=Region.US, handle="power-board")],
        first_seen=timestamp,
        last_seen=timestamp,
    )
    kit = Product(
        id="project-kit",
        name="Project parts",
        description_text="All non-3D printed parts for assembling the project",
        box_contents=[
            BoxItem(
                name="Power board",
                quantity="1 pc",
                source_url="https://us.store.bambulab.com/products/power-board",
            )
        ],
        first_seen=timestamp,
        last_seen=timestamp,
    )

    enriched = enrich_products([component, kit], tmp_path)
    enriched_kit = next(product for product in enriched if product.id == "project-kit")
    assert enriched_kit.tags == ["kit"]
    assert enriched_kit.box_contents[0].linked_product_id == "ia005-power-board"


def test_enrichment_applies_reviewed_box_contents_override(tmp_path: Path) -> None:
    config = tmp_path / "config"
    config.mkdir()
    (config / "categories.json").write_text(
        '{"categories":{"uncategorized":{"label":"Uncategorized"}},"rules":[]}',
        encoding="utf-8",
    )
    (config / "catalog_overrides.json").write_text(
        """{
          "pc003-battery": {
            "box_contents": [{
              "name": "14500 battery",
              "quantity": "1 pc",
              "item_number": "PC003",
              "source_url": "https://example.com/products/14500-battery",
              "linked_product_id": "pc003-battery"
            }]
          }
        }""",
        encoding="utf-8",
    )
    timestamp = datetime(2026, 1, 2, tzinfo=UTC)
    product = Product(
        id="pc003-battery",
        name="14500 battery (1PCS)",
        first_seen=timestamp,
        last_seen=timestamp,
    )

    enriched = enrich_products([product], tmp_path)[0]

    assert enriched.box_contents[0].quantity == "1 pc"
    assert enriched.box_contents[0].item_number == "PC003"
    assert enriched.box_contents[0].linked_product_id == product.id
    assert str(enriched.box_contents[0].source_url) == (
        "https://example.com/products/14500-battery"
    )


def test_enrichment_links_a_named_kit_module_to_its_catalog_product(
    tmp_path: Path,
) -> None:
    config = tmp_path / "config"
    config.mkdir()
    (config / "categories.json").write_text(
        '{"categories":{"uncategorized":{"label":"Uncategorized"}},"rules":[]}',
        encoding="utf-8",
    )
    (config / "catalog_overrides.json").write_text("{}", encoding="utf-8")
    timestamp = datetime(2026, 1, 2, tzinfo=UTC)
    kit = Product(
        id="zc006-electric-bubble-maker-kit-01",
        name="Electric Bubble Maker Kit 01",
        box_contents=[BoxItem(name="Electric Bubble Maker Kit-P6M", quantity="1")],
        first_seen=timestamp,
        last_seen=timestamp,
    )

    enriched = enrich_products([kit], tmp_path)[0]

    assert enriched.box_contents[0].linked_product_id == kit.id


def test_enrichment_prefers_variant_part_number_over_parent_kit_metadata(
    tmp_path: Path,
) -> None:
    config = tmp_path / "config"
    config.mkdir()
    (config / "categories.json").write_text(
        '{"categories":{"uncategorized":{"label":"Uncategorized"}},"rules":[]}',
        encoding="utf-8",
    )
    (config / "catalog_overrides.json").write_text("{}", encoding="utf-8")
    timestamp = datetime(2026, 1, 2, tzinfo=UTC)
    component = Product(
        id="aa221-bt3-self-tapping-screw",
        name="BT3 Button Head Cap Self Tapping Screw",
        variants=[
            Variant(
                region=Region.US,
                variant_id="variant-aa222",
                title="BT3x10 BHCS Self Tapping Screw (20PCS) - AA222",
                sku="42382284947592",
                part_number="AA222",
            )
        ],
        first_seen=timestamp,
        last_seen=timestamp,
    )
    kit = Product(
        id="zh018-project-kit",
        name="Project Kit",
        part_numbers=["AA222", "ZH018"],
        variants=[
            Variant(
                region=Region.US,
                variant_id="variant-zh018",
                title="Project Kit - ZH018",
                part_number="ZH018",
            )
        ],
        box_contents=[
            BoxItem(name="BT3x10 BHCS Self Tapping Screw (20PCS) - AA222")
        ],
        first_seen=timestamp,
        last_seen=timestamp,
    )

    enriched = enrich_products([component, kit], tmp_path)
    enriched_kit = next(product for product in enriched if product.id == kit.id)

    assert enriched_kit.box_contents[0].linked_product_id == component.id


def test_enrichment_matches_exact_sku_before_fuzzy_name(tmp_path: Path) -> None:
    config = tmp_path / "config"
    config.mkdir()
    (config / "categories.json").write_text(
        '{"categories":{"uncategorized":{"label":"Uncategorized"}},"rules":[]}',
        encoding="utf-8",
    )
    (config / "catalog_overrides.json").write_text("{}", encoding="utf-8")
    timestamp = datetime(2026, 1, 2, tzinfo=UTC)
    component = Product(
        id="controller-board",
        name="Controller Board",
        skus=["42382284947592"],
        first_seen=timestamp,
        last_seen=timestamp,
    )
    kit = Product(
        id="robot-kit",
        name="Robot Kit",
        box_contents=[BoxItem(name="Main electronics", item_number="42382284947592")],
        first_seen=timestamp,
        last_seen=timestamp,
    )

    enriched = enrich_products([component, kit], tmp_path)
    enriched_kit = next(product for product in enriched if product.id == kit.id)

    assert enriched_kit.box_contents[0].linked_product_id == component.id


def test_enrichment_uses_only_unambiguous_high_confidence_fuzzy_match(
    tmp_path: Path,
) -> None:
    config = tmp_path / "config"
    config.mkdir()
    (config / "categories.json").write_text(
        '{"categories":{"uncategorized":{"label":"Uncategorized"}},"rules":[]}',
        encoding="utf-8",
    )
    (config / "catalog_overrides.json").write_text("{}", encoding="utf-8")
    timestamp = datetime(2026, 1, 2, tzinfo=UTC)
    board = Product(
        id="power-distribution-board",
        name="Power Distribution Board",
        first_seen=timestamp,
        last_seen=timestamp,
    )
    control_board = Product(
        id="power-control-board",
        name="Power Control Board",
        first_seen=timestamp,
        last_seen=timestamp,
    )
    controller_board = Product(
        id="power-controller-board",
        name="Power Controller Board",
        first_seen=timestamp,
        last_seen=timestamp,
    )
    kit = Product(
        id="robot-kit",
        name="Robot Kit",
        box_contents=[
            BoxItem(name="Power Distribtion Board"),
            BoxItem(name="Power Controler Board"),
        ],
        first_seen=timestamp,
        last_seen=timestamp,
    )

    enriched = enrich_products([board, control_board, controller_board, kit], tmp_path)
    enriched_kit = next(product for product in enriched if product.id == kit.id)

    assert enriched_kit.box_contents[0].linked_product_id == board.id
    assert enriched_kit.box_contents[1].linked_product_id is None


def test_enrichment_fuzzy_match_rejects_conflicting_technical_sizes(
    tmp_path: Path,
) -> None:
    config = tmp_path / "config"
    config.mkdir()
    (config / "categories.json").write_text(
        '{"categories":{"uncategorized":{"label":"Uncategorized"}},"rules":[]}',
        encoding="utf-8",
    )
    (config / "catalog_overrides.json").write_text("{}", encoding="utf-8")
    timestamp = datetime(2026, 1, 2, tzinfo=UTC)
    component = Product(
        id="m2-m3-flat-washer",
        name="M2 M3 Carbon Steel Flat Washer",
        first_seen=timestamp,
        last_seen=timestamp,
    )
    kit = Product(
        id="machine-kit",
        name="Machine Kit",
        box_contents=[BoxItem(name="M6x12x1.6 Carbon Steel Flat Washer")],
        first_seen=timestamp,
        last_seen=timestamp,
    )

    enriched = enrich_products([component, kit], tmp_path)
    enriched_kit = next(product for product in enriched if product.id == kit.id)

    assert enriched_kit.box_contents[0].linked_product_id is None


def test_enrichment_fuzzy_match_preserves_decimal_dimensions(tmp_path: Path) -> None:
    config = tmp_path / "config"
    config.mkdir()
    (config / "categories.json").write_text(
        '{"categories":{"uncategorized":{"label":"Uncategorized"}},"rules":[]}',
        encoding="utf-8",
    )
    (config / "catalog_overrides.json").write_text("{}", encoding="utf-8")
    timestamp = datetime(2026, 1, 2, tzinfo=UTC)
    component = Product(
        id="d5-dowel-pin",
        name="D5 Stainless Steel Dowel Pins",
        variants=[
            Variant(
                region=Region.US,
                variant_id="d5x30",
                title="D5 Stainless Steel Dowel Pin - 5x30 mm (5PCS) - DA033",
                part_number="DA033",
            )
        ],
        first_seen=timestamp,
        last_seen=timestamp,
    )
    kit = Product(
        id="clock-kit",
        name="Clock Kit",
        box_contents=[BoxItem(name="M1.5x30 Stainless Steel Dowel Pin")],
        first_seen=timestamp,
        last_seen=timestamp,
    )

    enriched = enrich_products([component, kit], tmp_path)
    enriched_kit = next(product for product in enriched if product.id == kit.id)

    assert enriched_kit.box_contents[0].linked_product_id is None


def test_enrichment_replaces_generic_makerworld_titles(tmp_path: Path) -> None:
    config = tmp_path / "config"
    config.mkdir()
    (config / "categories.json").write_text(
        '{"categories":{"uncategorized":{"label":"Uncategorized"}},"rules":[]}',
        encoding="utf-8",
    )
    (config / "catalog_overrides.json").write_text("{}", encoding="utf-8")
    timestamp = datetime(2026, 1, 2, tzinfo=UTC)
    product = Product(
        id="zk003-cyberbrick-hardware-kit",
        name="CyberBrick Hardware Kit",
        related_links=[
            RelatedLink(
                title="MakerWorld model",
                url=(
                    "https://makerworld.com/en/models/"
                    "1395994-cyberbrick-official-forklift"
                ),
                kind="makerworld",
            )
        ],
        first_seen=timestamp,
        last_seen=timestamp,
    )

    enriched = enrich_product(product, tmp_path)

    assert enriched.related_links[0].title == "CyberBrick Official Forklift"


def test_enrichment_falls_back_to_product_name_for_numeric_makerworld_url(
    tmp_path: Path,
) -> None:
    config = tmp_path / "config"
    config.mkdir()
    (config / "categories.json").write_text(
        '{"categories":{"uncategorized":{"label":"Uncategorized"}},"rules":[]}',
        encoding="utf-8",
    )
    (config / "catalog_overrides.json").write_text("{}", encoding="utf-8")
    timestamp = datetime(2026, 1, 2, tzinfo=UTC)
    product = Product(
        id="kc009-lithophane-led-backlight-board-kit",
        name="Lithophane LED Backlight Board Kit",
        related_links=[
            RelatedLink(
                title="click here.",
                url="https://makerworld.com/en/models/1096380",
                kind="makerworld",
            )
        ],
        first_seen=timestamp,
        last_seen=timestamp,
    )

    enriched = enrich_product(product, tmp_path)

    assert enriched.related_links[0].title == (
        "Lithophane LED Backlight Board Kit project"
    )


def test_enrichment_preserves_schema_description_when_page_has_only_tables(
    tmp_path: Path,
) -> None:
    config = tmp_path / "config"
    config.mkdir()
    (config / "categories.json").write_text(
        '{"categories":{"uncategorized":{"label":"Uncategorized"}},"rules":[]}',
        encoding="utf-8",
    )
    (config / "catalog_overrides.json").write_text("{}", encoding="utf-8")
    timestamp = datetime(2026, 1, 2, tzinfo=UTC)
    product = Product(
        id="ia005-power-board",
        name="Power board",
        description_html="""
        <div class="pct"><h2>Product Specifications</h2>
        <table><tr><th>Width</th></tr><tr><td>25 mm</td></tr></table></div>
        """,
        description_text="A compact board with four outputs.",
        offers=[
            RegionalOffer(
                region=Region.EU,
                url="https://eu.store.bambulab.com/products/power-board",
                currency="EUR",
                retrieved_at=timestamp,
            )
        ],
        first_seen=timestamp,
        last_seen=timestamp,
    )

    enriched = enrich_product(product, tmp_path)

    assert enriched.description_text == "A compact board with four outputs."
    assert enriched.specifications == {"Width": "25 mm"}
    assert str(enriched.source_tables[0].provenance.source_url) == (
        "https://eu.store.bambulab.com/products/power-board"
    )
    assert enriched.measurements[0].provenance.source_url == (
        enriched.source_tables[0].provenance.source_url
    )
