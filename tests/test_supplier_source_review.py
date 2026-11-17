"""Independent checks for source-file boundaries, promotion, and license retention."""

import json
import zipfile
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from makersfridge.assets import AssetStore
from makersfridge.http import ArchiveHttpClient
from makersfridge.models import Asset, AssetKind, Product, RightsStatus, utc_now
from makersfridge.storage import Catalog
from makersfridge.suppliers.adapters import ADAPTERS, reference_product
from makersfridge.suppliers.catalog import PilotAsset, load_pilots_snapshot
from makersfridge.suppliers.sync import SupplierSyncEngine, SupplierSyncOptions


def product_spec(product_id: str) -> dict[str, object]:
    return {
        "id": product_id,
        "supplier_id": "raspberry-pi",
        "manufacturer": "Raspberry Pi",
        "name": product_id,
        "product_url": "https://vendor.test/products/" + product_id,
    }


def source_file(
    path: Path,
    *,
    includes: list[str] | None = None,
    products: list[dict[str, object]] | None = None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"schema_version": 1, "includes": includes or [], "products": products or []})
    )


def test_source_includes_are_root_relative_and_bound_to_content(tmp_path: Path) -> None:
    root = tmp_path / "sources.json"
    source_file(root, includes=["nested/board.json"])
    source_file(
        tmp_path / "nested/board.json",
        includes=["shared.json"],
        products=[product_spec("board-one")],
    )
    shared = tmp_path / "shared.json"
    source_file(shared, products=[product_spec("board-two")])
    products, before = load_pilots_snapshot(root)
    assert [p.id for p in products] == ["board-one", "board-two"]
    source_file(shared, products=[product_spec("board-three")])
    assert load_pilots_snapshot(root)[1] != before


@pytest.mark.parametrize(
    "include", ["../outside.json", "/outside.json", "\\outside.json", "nested/file.txt", ""]
)
def test_invalid_source_include_is_rejected(tmp_path: Path, include: str) -> None:
    root = tmp_path / "sources.json"
    source_file(root, includes=[include])
    with pytest.raises(ValueError, match="invalid source include"):
        load_pilots_snapshot(root)


def test_source_symlinks_cannot_escape_or_hide_repeated_files(tmp_path: Path) -> None:
    config = tmp_path / "config"
    root = config / "sources.json"
    outside = tmp_path / "outside.json"
    source_file(outside, products=[product_spec("outside-board")])
    source_file(root, includes=["linked.json"])
    (config / "linked.json").symlink_to(outside)
    with pytest.raises(ValueError, match="escapes"):
        load_pilots_snapshot(root)
    (config / "linked.json").unlink()
    source_file(config / "board.json", products=[product_spec("inside-board")])
    (config / "linked.json").symlink_to(config / "board.json")
    source_file(root, includes=["board.json", "linked.json"])
    with pytest.raises(ValueError, match="cyclic or repeated"):
        load_pilots_snapshot(root)


def test_included_source_cycle_is_rejected(tmp_path: Path) -> None:
    root = tmp_path / "sources.json"
    source_file(root, includes=["child.json"])
    source_file(tmp_path / "child.json", includes=["sources.json"])
    with pytest.raises(ValueError, match="cyclic or repeated"):
        load_pilots_snapshot(root)


def test_licensed_source_requires_license_evidence() -> None:
    base = {"url": "https://vendor.test/board.step", "filename": "board.step"}
    for status in [RightsStatus.LICENSED, RightsStatus.PERMISSIVE]:
        with pytest.raises(ValidationError, match="license evidence"):
            PilotAsset(**base, rights_status=status)
    assert PilotAsset(**base).rights_status is RightsStatus.UNKNOWN


def test_zip_retains_license_documents_and_skips_appledouble(tmp_path: Path) -> None:
    catalog = Catalog(tmp_path)
    archive_path = tmp_path / "input.zip"
    notice = b"Shared CAD license notice\n"
    with zipfile.ZipFile(archive_path, "w") as bundle:
        bundle.writestr("board.step", b"ISO-10303-21;\nEND-ISO-10303-21;")
        bundle.writestr("legal/LICENSE.md", notice)
        bundle.writestr("__MACOSX/._board.step", b"\x00\x05metadata")
        bundle.writestr("._extra.step", b"\x00\x05metadata")
    archive = Asset(
        id="review-archive",
        kind=AssetKind.ARCHIVE,
        source_url="https://vendor.test/board.zip",
        original_filename="board.zip",
        media_type="application/zip",
        blob_path="input.zip",
        role="component",
        rights_status=RightsStatus.LICENSED,
        license_url="https://vendor.test/license",
        applies_to_skus=["board-sku"],
        hardware_revision="R1",
        retrieved_at=utc_now(),
    )
    with ArchiveHttpClient(delay=0) as client:
        assets = AssetStore(catalog, client, tmp_path / "staging").extract(archive)
    assert {a.original_filename for a in assets} == {"board.step", "LICENSE.md"}
    document = next(a for a in assets if a.original_filename == "LICENSE.md")
    assert document.kind is AssetKind.DOCUMENT and document.role == "document"
    assert (tmp_path / (document.blob_path or "")).read_bytes() == notice
    assert all(a.rights_status is RightsStatus.LICENSED for a in assets)
    assert all(
        a.license_url == archive.license_url
        and a.hardware_revision == "R1"
        and a.applies_to_skus == ["board-sku"]
        for a in assets
    )


def test_included_source_change_invalidates_resume_without_rewriting_other_records(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "config/supplier-pilots.json"
    included = tmp_path / "config/supplier-sources/boards.json"
    source_file(root, includes=["supplier-sources/boards.json"])
    specs = [product_spec("board-one"), product_spec("board-two")]
    source_file(included, products=specs)
    catalog = Catalog(tmp_path)
    now = utc_now()
    catalog.write_product(
        Product(id="bambu-original", name="Original Bambu record", first_seen=now, last_seen=now)
    )
    original = catalog.product_path("bambu-original").read_bytes()
    fetched: list[str] = []
    interrupted = True

    class Adapter:
        def fetch(self, spec, client, observed):
            if spec.id == "board-two" and interrupted:
                raise RuntimeError("review interruption")
            client.get(str(spec.product_url))
            return reference_product(spec, observed)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nAllow: /")
        fetched.append(request.url.path)
        return httpx.Response(200, text="recorded public page")

    monkeypatch.setitem(ADAPTERS, "reference", Adapter())
    options = SupplierSyncOptions(suppliers=("raspberry-pi",), metadata_only=True, resume=True)
    with ArchiveHttpClient(delay=0, transport=httpx.MockTransport(handler)) as client:
        engine = SupplierSyncEngine(tmp_path, client)
        with pytest.raises(RuntimeError, match="review interruption"):
            engine.run_suppliers(options)
        assert len(catalog.products()) == 1
        specs[0]["description"] = "Reviewed source correction"
        source_file(included, products=specs)
        interrupted = False
        engine.run_suppliers(options)
    assert fetched.count("/products/board-one") == 2
    assert catalog.load_product("board-one").description_text == "Reviewed source correction"
    assert catalog.product_path("bambu-original").read_bytes() == original


def test_source_edit_during_import_prevents_promotion(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "config/supplier-pilots.json"
    included = tmp_path / "config/supplier-sources/boards.json"
    source_file(root, includes=["supplier-sources/boards.json"])
    source_file(included, products=[product_spec("board-one")])
    catalog = Catalog(tmp_path)
    now = utc_now()
    catalog.write_product(
        Product(id="bambu-original", name="Existing record", first_seen=now, last_seen=now)
    )
    original = catalog.product_path("bambu-original").read_bytes()

    class Adapter:
        def fetch(self, spec, client, observed):
            revised = product_spec("board-one")
            revised["description"] = "New source edit"
            source_file(included, products=[revised])
            return reference_product(spec, observed)

    monkeypatch.setitem(ADAPTERS, "reference", Adapter())
    with (
        ArchiveHttpClient(delay=0) as client,
        pytest.raises(RuntimeError, match="source manifests changed during import"),
    ):
        SupplierSyncEngine(tmp_path, client).run_suppliers(
            SupplierSyncOptions(suppliers=("raspberry-pi",), metadata_only=True)
        )
    assert not catalog.product_path("board-one").exists()
    assert catalog.product_path("bambu-original").read_bytes() == original
