import io
import json
import zipfile
from pathlib import Path

import httpx
import pytest
from typer.testing import CliRunner

from makersfridge.cli import app
from makersfridge.http import ArchiveHttpClient
from makersfridge.models import Product, Region, utc_now
from makersfridge.storage import Catalog
from makersfridge.suppliers.adapters import ADAPTERS
from makersfridge.suppliers.catalog import load_pilots
from makersfridge.suppliers.sync import SupplierSyncEngine, SupplierSyncOptions
from makersfridge.sync import SyncEngine, SyncOptions

ROOT = Path(__file__).parents[1]
FIXTURES = ROOT / "tests/fixtures/suppliers"
MANIFEST = ROOT / "config/supplier-pilots.json"


def fixture_handler(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/robots.txt":
        return httpx.Response(200, text="User-agent: *\nAllow: /")
    fixture = {
        "/products/btt-skr-mini-e3-v2-control-board": "biqu-skr-mini-e3.html",
        "/products/bigtreetech-pi-2-cb2": "biqu-cb2.html",
        "/3.4inch-800x800-lcd.htm": "waveshare-27478.html",
        "/ESP32-S3-Touch-AMOLED-1.8.htm": "waveshare-29957.html",
    }.get(request.url.path)
    assert fixture, str(request.url)
    return httpx.Response(200, text=(FIXTURES / fixture).read_text())


def options(*suppliers: str, **kwargs: object) -> SupplierSyncOptions:
    return SupplierSyncOptions(suppliers=suppliers, manifest=MANIFEST, **kwargs)


def test_pilot_import_preserves_bambu_bytes_ids_and_other_suppliers(tmp_path: Path) -> None:
    now = utc_now()
    catalog = Catalog(tmp_path)
    legacy = Product(id="original-bambu-id", name="Original part", first_seen=now, last_seen=now)
    catalog.products_dir.mkdir(parents=True)
    original = json.dumps(
        legacy.model_dump(
            mode="json",
            exclude={
                "supplier_id",
                "manufacturer",
                "hardware_revision",
            },
        ),
        indent=1,
    ).encode()
    catalog.product_path(legacy.id).write_bytes(original)
    with ArchiveHttpClient(delay=0, transport=httpx.MockTransport(fixture_handler)) as client:
        engine = SupplierSyncEngine(tmp_path, client)
        btt = engine.run_suppliers(options("bigtreetech", "biqu", metadata_only=True))
        assert len(btt.diff.added) == 4
        before_btt = catalog.product_path("btt-skr-mini-e3-v3-0").read_bytes()
        waveshare = engine.run_suppliers(options("waveshare", metadata_only=True))
        assert len(waveshare.diff.added) == 2
    assert catalog.product_path(legacy.id).read_bytes() == original
    assert catalog.product_path("btt-skr-mini-e3-v3-0").read_bytes() == before_btt
    assert len(catalog.products()) == 7
    board = catalog.load_product("btt-skr-mini-e3-v3-0")
    assert {v.sku for v in board.variants} == {"1060000511", "1060000511*1+3040020432*1"}
    assert all(v.sku != "2020000064" for v in board.variants)
    assert board.hardware_revision == "V3.0"
    assert catalog.load_product("biqu-hermit-crab").offers == []
    assert catalog.load_product("btt-ebb36-can-v1-0").offers == []
    configurable = catalog.load_product("waveshare-29957")
    assert configurable.offers[0].price is None
    assert configurable.offers[0].available is None
    assert configurable.variants[0].sku == "29957"
    assert configurable.assets[0].hardware_revision is None


def test_bambu_scan_does_not_retire_or_rewrite_supplier_products(tmp_path: Path) -> None:
    with ArchiveHttpClient(delay=0, transport=httpx.MockTransport(fixture_handler)) as client:
        SupplierSyncEngine(tmp_path, client).run_suppliers(options("biqu", metadata_only=True))
    path = Catalog(tmp_path).product_path("biqu-hermit-crab")
    before = path.read_bytes()

    def empty(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nAllow: /")
        if request.url.path.endswith("aggregateGlobalSearchV2"):
            return httpx.Response(
                200, json={"data": {"productGlobalSearchVOIPage": {"records": [], "total": 0}}}
            )
        return httpx.Response(200, text=(ROOT / "tests/fixtures/collection.html").read_text())

    with ArchiveHttpClient(delay=0, transport=httpx.MockTransport(empty)) as client:
        for _ in range(2):
            SyncEngine(tmp_path, client).run(SyncOptions(regions=(Region.US,), metadata_only=True))
    assert path.read_bytes() == before
    assert Catalog(tmp_path).load_product("biqu-hermit-crab").active


def test_failed_supplier_import_and_dry_run_do_not_promote(tmp_path: Path) -> None:
    with ArchiveHttpClient(delay=0, transport=httpx.MockTransport(fixture_handler)) as client:
        engine = SupplierSyncEngine(tmp_path, client)
        result = engine.run_suppliers(options("bigtreetech", dry_run=True, metadata_only=True))
        assert not result.promoted
        assert Catalog(tmp_path).products() == []

    def failing(request: httpx.Request) -> httpx.Response:
        if "cb2" in request.url.path:
            return httpx.Response(200, text="<html>source changed</html>")
        return fixture_handler(request)

    with (
        ArchiveHttpClient(delay=0, transport=httpx.MockTransport(failing)) as client,
        pytest.raises(ValueError, match="structured product"),
    ):
        SupplierSyncEngine(tmp_path, client).run_suppliers(
            options("bigtreetech", metadata_only=True)
        )
    assert Catalog(tmp_path).products() == []


def test_completed_resume_refreshes_pages_and_changed_mapping_fails_closed(tmp_path: Path) -> None:
    fetched = 0
    changed = False

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal fetched
        if "/products/" in request.url.path:
            fetched += 1
            if changed:
                text = (FIXTURES / "biqu-skr-mini-e3.html").read_text().replace("1060000511", "999")
                return httpx.Response(200, text=text)
        return fixture_handler(request)

    with ArchiveHttpClient(delay=0, transport=httpx.MockTransport(handler)) as client:
        engine = SupplierSyncEngine(tmp_path, client)
        opt = options(
            "bigtreetech", product_ids=("btt-skr-mini-e3-v3-0",), metadata_only=True, resume=True
        )
        engine.run_suppliers(opt)
        before = Catalog(tmp_path).product_path("btt-skr-mini-e3-v3-0").read_bytes()
        changed = True
        with pytest.raises(ValueError, match="reviewed SKUs"):
            engine.run_suppliers(opt)
    assert fetched == 2
    assert Catalog(tmp_path).product_path("btt-skr-mini-e3-v3-0").read_bytes() == before


def test_zip_models_keep_sku_revision_and_rights_and_can_refresh(tmp_path: Path) -> None:
    model = b"ISO-10303-21;\nHEADER;\nENDSEC;\nEND-ISO-10303-21;"
    fetched = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal fetched
        if request.url.host == "files.waveshare.com":
            if request.url.path == "/robots.txt":
                return httpx.Response(404)
            fetched += 1
            buffer = io.BytesIO()
            with zipfile.ZipFile(buffer, "w") as archive:
                archive.writestr("model.stp", model)
            return httpx.Response(200, content=buffer.getvalue())
        response = fixture_handler(request)
        # This test focuses on the mechanical archive rather than catalog images.
        if request.url.path.endswith(".htm"):
            soup = response.text
            data = json.loads(soup.split('type="application/ld+json">')[1].split("</script>")[0])
            data.pop("image", None)
            return httpx.Response(
                200, text='<script type="application/ld+json">' + json.dumps(data) + "</script>"
            )
        return response

    with ArchiveHttpClient(delay=0, transport=httpx.MockTransport(handler)) as client:
        engine = SupplierSyncEngine(tmp_path, client)
        opt = options("waveshare", product_ids=("waveshare-27478",))
        engine.run_suppliers(opt)
        product = Catalog(tmp_path).load_product("waveshare-27478")
        child = next(a for a in product.assets if a.parent_asset_id)
        assert child.applies_to_skus == ["27478"]
        assert child.role == "component" and child.rights_status.value == "unknown"
        assert child.hardware_revision is None
        assert (tmp_path / (child.blob_path or "")).read_bytes() == model
        engine.run_suppliers(opt)
        assert fetched == 1
        model += b"\n/* updated */"
        engine.run_suppliers(
            options("waveshare", product_ids=("waveshare-27478",), refresh_assets=True)
        )
    updated = Catalog(tmp_path).load_product("waveshare-27478")
    assert fetched == 2
    assert next(a for a in updated.assets if a.parent_asset_id).sha256 != child.sha256


def test_supplier_manifest_and_cli_reject_unsafe_scope(tmp_path: Path) -> None:
    pilots = load_pilots(MANIFEST)
    assert len(pilots) == 6
    assert {p.supplier_id for p in pilots} == {"bigtreetech", "biqu", "waveshare"}
    runner = CliRunner()
    for args in [
        ["--supplier", "unknown"],
        ["--supplier", "waveshare", "--region", "us"],
        ["--region", "global"],
        ["--refresh-assets", "--supplier", "all"],
    ]:
        assert runner.invoke(app, ["sync", *args, "--root", str(tmp_path)]).exit_code == 2


def test_mixed_currency_and_changed_sku_are_not_merged() -> None:
    spec = load_pilots(MANIFEST)[0]
    raw = (FIXTURES / "biqu-skr-mini-e3.html").read_text()
    data = json.loads(raw.split('type="application/ld+json">')[1].split("</script>")[0])
    data["hasVariant"][1]["offers"]["priceCurrency"] = "EUR"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, text='<script type="application/ld+json">' + json.dumps(data) + "</script>"
        )

    with (
        httpx.Client(transport=httpx.MockTransport(handler)) as client,
        pytest.raises(ValueError, match="mixed currencies"),
    ):
        ADAPTERS[spec.source_kind].fetch(spec, client, utc_now())


def test_metadata_refresh_rejected_before_catalog_changes(tmp_path: Path) -> None:
    with (
        ArchiveHttpClient(delay=0, transport=httpx.MockTransport(fixture_handler)) as client,
        pytest.raises(ValueError, match="binary downloads"),
    ):
        SupplierSyncEngine(tmp_path, client).run_suppliers(
            options("waveshare", metadata_only=True, refresh_assets=True)
        )
    assert not (tmp_path / ".staging").exists()


def test_interrupted_supplier_import_resumes_only_verified_pages(tmp_path: Path) -> None:
    interrupted = True
    fetched: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if "/products/" in request.url.path:
            if "cb2" in request.url.path and interrupted:
                raise ValueError("supplier interrupted")
            fetched.append(request.url.path)
        return fixture_handler(request)

    with ArchiveHttpClient(delay=0, transport=httpx.MockTransport(handler)) as client:
        engine = SupplierSyncEngine(tmp_path, client)
        opt = options("bigtreetech", metadata_only=True, resume=True)
        with pytest.raises(ValueError, match="supplier interrupted"):
            engine.run_suppliers(opt)
        assert Catalog(tmp_path).products() == []
        interrupted = False
        engine.run_suppliers(opt)
    assert fetched.count("/products/btt-skr-mini-e3-v2-control-board") == 1
    assert len(Catalog(tmp_path).products()) == 3


@pytest.mark.parametrize("edit_selected", [False, True])
def test_supplier_promotion_preserves_concurrent_edits(
    tmp_path: Path,
    edit_selected: bool,
) -> None:
    catalog = Catalog(tmp_path)
    now = utc_now()
    catalog.write_product(
        Product(id="bambu-original", name="Bambu original", first_seen=now, last_seen=now)
    )
    opt = options("bigtreetech", product_ids=("btt-skr-mini-e3-v3-0",), metadata_only=True)
    if edit_selected:
        with ArchiveHttpClient(delay=0, transport=httpx.MockTransport(fixture_handler)) as client:
            SupplierSyncEngine(tmp_path, client).run_suppliers(opt)
    target = "btt-skr-mini-e3-v3-0" if edit_selected else "bambu-original"

    def editing(request: httpx.Request) -> httpx.Response:
        response = fixture_handler(request)
        if "/products/" in request.url.path:
            product = catalog.load_product(target)
            catalog.write_product(product.model_copy(update={"name": "Concurrent user edit"}))
            data = json.loads(
                response.text.split('type="application/ld+json">')[1].split("</script>")[0]
            )
            data["hasVariant"][0]["offers"]["price"] = "999.99"
            return httpx.Response(
                200, text='<script type="application/ld+json">' + json.dumps(data) + "</script>"
            )
        return response

    with ArchiveHttpClient(delay=0, transport=httpx.MockTransport(editing)) as client:
        engine = SupplierSyncEngine(tmp_path, client)
        if edit_selected:
            with pytest.raises(RuntimeError, match="changed during import"):
                engine.run_suppliers(opt)
        else:
            engine.run_suppliers(opt)
    assert catalog.load_product(target).name == "Concurrent user edit"
