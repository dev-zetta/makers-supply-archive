import io
import json
import sqlite3
import zipfile
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError
from test_reconcile_diff import observation

from makersfridge.backfill import CachedAssetBackfill
from makersfridge.database import build_database
from makersfridge.diffing import diff_products
from makersfridge.enrichment import enrich_products
from makersfridge.http import ArchiveHttpClient
from makersfridge.metadata_backfill import CachedMetadataBackfill
from makersfridge.models import (
    Asset,
    AssetKind,
    BoxItem,
    Product,
    Region,
    RegionalOffer,
    RunManifest,
    SourceAlias,
    Variant,
)
from makersfridge.reconcile import AliasRegistry, Reconciler
from makersfridge.storage import Catalog
from makersfridge.suppliers.catalog import PilotAsset
from makersfridge.suppliers.sync import SupplierSyncEngine, SupplierSyncOptions
from makersfridge.validation import validate_product

NOW = datetime(2026, 1, 2, tzinfo=UTC)


def test_legacy_record_defaults_to_bambu_without_changing_its_identity() -> None:
    product = Product.model_validate(
        {
            "id": "ia005-power-board",
            "name": "Power Board",
            "schema_version": 4,
            "first_seen": NOW,
            "last_seen": NOW,
            "aliases": [{"region": "us", "handle": "power-board", "product_id": "123"}],
        }
    )
    assert product.id == "ia005-power-board"
    assert product.schema_version == 4
    assert product.supplier_id == "bambu-lab"
    assert product.manufacturer == "Bambu Lab"
    assert product.aliases[0].supplier_id == "bambu-lab"
    assert product.aliases[0].store_id == ""


def test_old_run_manifest_loads_and_new_runs_record_supplier_scope() -> None:
    manifest = RunManifest(
        started_at=NOW,
        completed_at=NOW,
        metadata_only=True,
        regions=[],
        products_written=0,
        assets_downloaded=0,
        bytes_downloaded=0,
    )
    assert manifest.supplier_ids == []
    scoped = manifest.model_copy(update={"supplier_ids": ["bigtreetech", "biqu"]})
    assert RunManifest.model_validate_json(scoped.model_dump_json()).supplier_ids == [
        "bigtreetech",
        "biqu",
    ]


def test_bambu_reconciler_does_not_match_another_suppliers_part_or_handle(tmp_path: Path) -> None:
    other = Product(
        schema_version=5,
        id="btt-power-board",
        name="Power Board",
        supplier_id="bigtreetech",
        manufacturer="BIGTREETECH",
        part_numbers=["IA005"],
        aliases=[
            SourceAlias(
                supplier_id="bigtreetech", region=Region.US, handle="power-board", product_id="123"
            )
        ],
        first_seen=NOW,
        last_seen=NOW,
    )
    reconciler = Reconciler([other], AliasRegistry(tmp_path / "aliases.json"))
    assert reconciler.existing_id(observation()) is None
    assert reconciler.group_key(observation()) == "part:IA005"
    assert reconciler.existing[other.id] is other


def test_database_persists_supplier_asset_provenance_and_distinct_stores(tmp_path: Path) -> None:
    catalog = Catalog(tmp_path)
    catalog.write_product(
        Product(
            schema_version=5,
            id="btt-pilot",
            name="Pilot board",
            supplier_id="bigtreetech",
            manufacturer="BIGTREETECH",
            hardware_revision="V1.0",
            first_seen=NOW,
            last_seen=NOW,
            aliases=[
                SourceAlias(
                    supplier_id="bigtreetech",
                    store_id="biqu-global",
                    region=Region.GLOBAL,
                    handle="pilot",
                    product_id="123",
                )
            ],
            offers=[
                RegionalOffer(
                    region=Region.GLOBAL,
                    store_id=store,
                    url="https://example.com/pilot",
                    currency="USD",
                    price=price,
                    retrieved_at=NOW,
                )
                for store, price in [("biqu-global", "20"), ("other-store", "21")]
            ],
            variants=[
                Variant(
                    region=Region.GLOBAL,
                    store_id=store,
                    variant_id="123",
                    title="Board",
                    sku="ABC-123",
                )
                for store in ["biqu-global", "other-store"]
            ],
            assets=[
                Asset(
                    id="model-pilot",
                    kind=AssetKind.MODEL,
                    source_url="https://example.com/pilot.step",
                    original_filename="pilot.step",
                    media_type="model/step",
                    role="component",
                    applies_to_skus=["ABC-123"],
                    hardware_revision="V1.0",
                    source_repository="bigtreetech/pilot",
                    source_commit="a" * 40,
                    source_path="3D/pilot.step",
                    license_url="https://example.com/license",
                )
            ],
        )
    )
    output = tmp_path / "catalog.sqlite"
    build_database(catalog, output)
    with sqlite3.connect(output) as connection:
        assert connection.execute("PRAGMA user_version").fetchone() == (6,)
        assert connection.execute(
            "SELECT supplier_id, manufacturer, hardware_revision FROM products"
        ).fetchone() == ("bigtreetech", "BIGTREETECH", "V1.0")
        assert connection.execute(
            "SELECT store_id, price FROM offers ORDER BY store_id"
        ).fetchall() == [("biqu-global", "20"), ("other-store", "21")]
        assert connection.execute("SELECT COUNT(*) FROM variants").fetchone() == (2,)
        row = connection.execute(
            "SELECT role, applies_to_skus_json, source_repository, source_commit, source_path, "
            "license_url FROM assets"
        ).fetchone()
        assert row == (
            "component",
            json.dumps(["ABC-123"], separators=(",", ":")),
            "bigtreetech/pilot",
            "a" * 40,
            "3D/pilot.step",
            "https://example.com/license",
        )
        assert connection.execute("SELECT supplier_id, store_id FROM aliases").fetchone() == (
            "bigtreetech",
            "biqu-global",
        )
        assert connection.execute(
            "SELECT product_id FROM product_search WHERE product_search MATCH 'BIGTREETECH'"
        ).fetchall() == [("btt-pilot",)]


def test_offers_validate_and_diff_by_store_and_region(tmp_path: Path) -> None:
    offers = [
        RegionalOffer(
            region=Region.GLOBAL,
            store_id=store,
            url="https://example.com/pilot",
            currency="USD",
            price="20",
            retrieved_at=NOW,
        )
        for store in ["biqu-global", "another-store"]
    ]
    before = Product(
        id="btt-pilot",
        name="Pilot",
        supplier_id="bigtreetech",
        first_seen=NOW,
        last_seen=NOW,
        offers=offers,
    )
    assert not validate_product(before, Catalog(tmp_path))
    after = before.model_copy(
        update={"offers": [offers[0].model_copy(update={"price": "21"}), offers[1]]}
    )
    assert diff_products([before], [after]).offer_changes == [before.id]
    duplicate = before.model_copy(update={"offers": [offers[0], offers[0]]})
    assert "duplicate offer" in validate_product(duplicate, Catalog(tmp_path))[0].message


def test_variant_identity_validation_matches_the_database_key(tmp_path: Path) -> None:
    variant = Variant(region=Region.GLOBAL, store_id="biqu-global", variant_id="123", title="Board")
    product = Product(
        id="btt-pilot",
        name="Pilot",
        supplier_id="bigtreetech",
        first_seen=NOW,
        last_seen=NOW,
        variants=[variant, variant.model_copy(update={"store_id": "another-store"})],
    )
    assert not validate_product(product, Catalog(tmp_path))
    duplicate = product.model_copy(update={"variants": [variant, variant]})
    assert "duplicate variant" in validate_product(duplicate, Catalog(tmp_path))[0].message


def test_asset_mapping_corrections_are_reported_even_with_unchanged_cad_bytes() -> None:
    asset = Asset(
        id="model-pilot",
        kind=AssetKind.MODEL,
        source_url="https://example.com/pilot.step",
        original_filename="pilot.step",
        media_type="model/step",
        sha256="a" * 64,
        applies_to_skus=["OLD"],
        retrieved_at=NOW,
    )
    before = Product(
        id="btt-pilot",
        name="Pilot",
        supplier_id="bigtreetech",
        first_seen=NOW,
        last_seen=NOW,
        assets=[asset],
    )
    after = before.model_copy(
        update={"assets": [asset.model_copy(update={"applies_to_skus": ["CORRECT"]})]}
    )
    assert diff_products([before], [after]).asset_changes == [before.id]
    timestamp_only = before.model_copy(
        update={
            "assets": [asset.model_copy(update={"retrieved_at": datetime(2026, 2, 2, tzinfo=UTC)})]
        }
    )
    assert not diff_products([before], [timestamp_only]).has_changes


def test_enrichment_preserves_supplier_records_and_existing_component_links(tmp_path: Path) -> None:
    component = Product(
        id="bambu-part",
        name="A reviewed component",
        first_seen=NOW,
        last_seen=NOW,
    )
    kit = Product(
        id="bambu-kit",
        name="Bambu kit",
        first_seen=NOW,
        last_seen=NOW,
        box_contents=[
            BoxItem(name="A different description", linked_product_id=component.id),
            BoxItem(name="Other supplier component"),
        ],
    )
    other = Product(
        schema_version=5,
        id="waveshare-part",
        name="Other supplier component",
        supplier_id="waveshare",
        manufacturer="Waveshare",
        first_seen=NOW,
        last_seen=NOW,
        categories=["Displays"],
        tags=["reviewed"],
        box_contents=[BoxItem(name="A reviewed component", linked_product_id=component.id)],
    )
    enriched_component, enriched_kit, enriched_other = enrich_products(
        [component, kit, other], tmp_path
    )
    assert enriched_component.id == component.id
    assert enriched_kit.box_contents[0].linked_product_id == component.id
    assert enriched_kit.box_contents[1].linked_product_id is None
    assert enriched_other is other


def test_bambu_backfills_skip_supplier_records_and_global_aliases(tmp_path: Path) -> None:
    catalog = Catalog(tmp_path)
    supplier = Product(
        schema_version=5,
        id="waveshare-part",
        name="Supplier",
        supplier_id="waveshare",
        manufacturer="Waveshare",
        first_seen=NOW,
        last_seen=NOW,
        aliases=[SourceAlias(supplier_id="waveshare", region=Region.GLOBAL, handle="supplier")],
    )
    catalog.write_product(supplier)
    original = catalog.product_path(supplier.id).read_bytes()
    with ArchiveHttpClient() as client:
        assets = CachedAssetBackfill(tmp_path, client)
        assert assets._page(supplier) is None
        result = assets.run(download=True)
        assert result.products_scanned == 0
        assert not result.promoted
    metadata = CachedMetadataBackfill(tmp_path)
    assert metadata._canonical_page(supplier) == (None, 0)
    assert metadata.run().products_scanned == 0
    assert catalog.product_path(supplier.id).read_bytes() == original


@pytest.mark.parametrize("case", ["nonhex-commit", "different-url", "traversal-path"])
def test_git_asset_provenance_must_match_a_valid_pinned_url(case: str) -> None:
    commit = "a" * 40
    path = "3D/board.step"
    url = f"https://raw.githubusercontent.com/bigtreetech/pilot/{commit}/{path}"
    if case == "nonhex-commit":
        commit = "g" * 40
        url = f"https://raw.githubusercontent.com/bigtreetech/pilot/{commit}/{path}"
    elif case == "different-url":
        url = "https://example.com/unrelated.step"
    else:
        path = "../board.step"
    with pytest.raises(ValidationError):
        PilotAsset(
            url=url,
            filename="board.step",
            source_repository="https://github.com/bigtreetech/pilot",
            source_commit=commit,
            source_path=path,
        )


def test_supplier_refresh_and_mapping_updates_preserve_legacy_bytes(tmp_path: Path) -> None:
    catalog = Catalog(tmp_path)
    catalog.products_dir.mkdir(parents=True)
    legacy = {
        "schema_version": 1,
        "id": "bambu-existing",
        "name": "Original Bambu record",
        "first_seen": NOW.isoformat(),
        "last_seen": NOW.isoformat(),
    }
    original = (json.dumps(legacy, indent=3) + "\n").encode()
    legacy_path = catalog.product_path("bambu-existing")
    legacy_path.write_bytes(original)
    manifest = tmp_path / "config/supplier-pilots.json"
    manifest.parent.mkdir()
    spec = {
        "id": "btt-review",
        "supplier_id": "bigtreetech",
        "manufacturer": "BIGTREETECH",
        "name": "Reviewed board",
        "source_kind": "shopify",
        "store_id": "biqu-global",
        "product_url": "https://shop.example/pilot",
        "skus": ["BOARD", "CABLE"],
        "selected_skus": ["BOARD", "CABLE"],
        "assets": [
            {
                "url": "https://files.example/model.zip",
                "filename": "model.zip",
                "role": "component",
                "applies_to_skus": ["BOARD", "CABLE"],
                "hardware_revision": "V1",
            }
        ],
    }

    def write_manifest() -> None:
        manifest.write_text(json.dumps({"schema_version": 1, "products": [spec]}))

    def archive(version: str) -> bytes:
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w") as bundle:
            bundle.writestr("models/board.step", f"ISO-10303-21;\n{version}\nEND-ISO-10303-21;")
        return output.getvalue()

    skus = ["BOARD", "CABLE"]
    version = "old"

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nAllow: /")
        if request.url.path == "/model.zip":
            return httpx.Response(200, content=archive(version))
        variants = [
            {
                "@type": "Product",
                "sku": sku,
                "name": sku,
                "offers": {
                    "price": "20",
                    "priceCurrency": "USD",
                    "availability": "https://schema.org/InStock",
                    "url": f"https://shop.example/pilot?variant={sku}",
                },
            }
            for sku in skus
        ]
        return httpx.Response(
            200,
            text='<script type="application/ld+json">'
            + json.dumps(
                {"@type": "ProductGroup", "name": "Reviewed board", "hasVariant": variants}
            )
            + "</script>",
        )

    write_manifest()
    with ArchiveHttpClient(delay=0, retries=0, transport=httpx.MockTransport(handler)) as client:
        engine = SupplierSyncEngine(tmp_path, client)
        initial = engine.run_suppliers(SupplierSyncOptions(suppliers=("bigtreetech",)))
        assert initial.promoted
        before = catalog.load_product("btt-review")
        old_child = next(asset for asset in before.assets if asset.parent_asset_id)
        assert {variant.variant_id for variant in before.variants} == {"BOARD", "CABLE"}
        skus = ["CABLE"]
        version = "new"
        refreshed = engine.run_suppliers(
            SupplierSyncOptions(
                suppliers=("bigtreetech",),
                refresh_assets=True,
            )
        )
        assert refreshed.promoted
        after = catalog.load_product("btt-review")
        child = next(asset for asset in after.assets if asset.parent_asset_id)
        assert child.sha256 != old_child.sha256
        assert after.first_seen == before.first_seen
        assert {variant.variant_id for variant in after.variants} == {"CABLE"}
        assert child.blob_path is not None
        assert b"new" in (tmp_path / child.blob_path).read_bytes()
        spec["assets"][0]["hardware_revision"] = "V2"
        spec["assets"][0]["applies_to_skus"] = ["CABLE"]
        write_manifest()
        correction = engine.run_suppliers(
            SupplierSyncOptions(
                suppliers=("bigtreetech",),
                metadata_only=True,
            )
        )
        assert correction.promoted
        corrected = catalog.load_product("btt-review")
        corrected_child = next(asset for asset in corrected.assets if asset.parent_asset_id)
        assert corrected_child.sha256 == child.sha256
        assert corrected_child.hardware_revision == "V2"
        assert corrected_child.applies_to_skus == ["CABLE"]
        assert legacy_path.read_bytes() == original
