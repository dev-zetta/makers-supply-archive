import hashlib
import io
import stat
import zipfile
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from makers_supply.assets import AssetStore, DownloadLimits, UnsafeAssetError, materialize_product
from makers_supply.http import ArchiveHttpClient
from makers_supply.models import Asset, AssetKind, Product
from makers_supply.parser import ParsedAsset
from makers_supply.storage import Catalog
from makers_supply.validation import validate_product

NOW = datetime(2026, 1, 2, tzinfo=UTC)


def zip_bytes(files: dict[str, bytes]) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    return output.getvalue()


def make_store(tmp_path: Path, content: bytes) -> tuple[AssetStore, ArchiveHttpClient]:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        return httpx.Response(200, content=content, headers={"Content-Length": str(len(content))})

    client = ArchiveHttpClient(delay=0, transport=httpx.MockTransport(handler))
    store = AssetStore(Catalog(tmp_path), client, tmp_path / ".staging")
    return store, client


def archive_asset() -> Asset:
    parsed = ParsedAsset(
        "https://cdn.example.com/models.zip",
        "models.zip",
        "application/zip",
        AssetKind.ARCHIVE,
    )
    from makers_supply.assets import asset_from_parsed

    return asset_from_parsed(parsed)


def test_ingest_deduplicates_and_extracts_supported_models(tmp_path: Path) -> None:
    content = zip_bytes({"CAD/board.step": b"ISO-10303-21;\nENDSEC;", "readme.txt": b"help"})
    store, client = make_store(tmp_path, content)
    try:
        stored, extracted = store.ingest(archive_asset(), NOW)
    finally:
        client.close()
    assert stored.blob_path and (tmp_path / stored.blob_path).is_file()
    assert stat.S_IMODE((tmp_path / stored.blob_path).stat().st_mode) == 0o644
    assert len(extracted) == 1
    assert extracted[0].archive_member_path == "CAD/board.step"
    assert extracted[0].parent_asset_id == stored.id


def test_ingest_reuses_verified_completed_download(tmp_path: Path) -> None:
    calls = 0
    content = zip_bytes({"CAD/board.step": b"ISO-10303-21;\nENDSEC;"})

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        calls += 1
        return httpx.Response(200, content=content)

    client = ArchiveHttpClient(delay=0, transport=httpx.MockTransport(handler))
    store = AssetStore(Catalog(tmp_path), client, tmp_path / ".staging")
    try:
        store.ingest(archive_asset(), NOW)
        store.ingest(archive_asset(), NOW)
    finally:
        client.close()

    assert calls == 1


def test_ingest_recovers_complete_unmarked_partial(tmp_path: Path) -> None:
    content = zip_bytes({"CAD/board.step": b"ISO-10303-21;\nENDSEC;"})

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        assert request.headers["Range"] == f"bytes={len(content)}-"
        return httpx.Response(416, headers={"Content-Range": f"bytes */{len(content)}"})

    client = ArchiveHttpClient(delay=0, transport=httpx.MockTransport(handler))
    staging = tmp_path / ".staging"
    downloads = staging / "downloads"
    downloads.mkdir(parents=True)
    key = hashlib.sha256(str(archive_asset().source_url).encode()).hexdigest()
    (downloads / f"{key}.part").write_bytes(content)
    store = AssetStore(Catalog(tmp_path), client, staging)
    try:
        stored, extracted = store.ingest(archive_asset(), NOW)
    finally:
        client.close()

    assert stored.size == len(content)
    assert len(extracted) == 1
    assert (downloads / f"{key}.complete").is_file()


@pytest.mark.parametrize("member", ["../escape.step", "/absolute.step", "C:/drive.step"])
def test_archive_rejects_unsafe_paths(tmp_path: Path, member: str) -> None:
    store, client = make_store(tmp_path, zip_bytes({member: b"ISO-10303-21;"}))
    try:
        with pytest.raises(UnsafeAssetError):
            store.ingest(archive_asset(), NOW)
    finally:
        client.close()


def test_archive_rejects_duplicate_casefolded_members(tmp_path: Path) -> None:
    content = zip_bytes({"Part.step": b"ISO-10303-21;", "part.step": b"ISO-10303-21;"})
    store, client = make_store(tmp_path, content)
    try:
        with pytest.raises(UnsafeAssetError):
            store.ingest(archive_asset(), NOW)
    finally:
        client.close()


def test_download_rejects_html_disguised_as_model(tmp_path: Path) -> None:
    store, client = make_store(tmp_path, b"<!doctype html><title>Denied</title>")
    asset = Asset(
        id="model-example",
        kind=AssetKind.MODEL,
        source_url="https://cdn.example.com/model.step",
        original_filename="model.step",
        media_type="model/step",
    )
    try:
        with pytest.raises(UnsafeAssetError):
            store.ingest(asset, NOW)
    finally:
        client.close()


def test_download_rejects_oversize_from_headers_before_writing(tmp_path: Path) -> None:
    store, client = make_store(tmp_path, b"PK\x03\x04" + b"large archive")
    store.limits = DownloadLimits(max_download_size=4)
    try:
        with pytest.raises(UnsafeAssetError, match="exceeds download limit"):
            store.ingest(archive_asset(), NOW)
    finally:
        client.close()

    assert not list((tmp_path / ".staging/downloads").glob("*.part"))


def test_mislabeled_raster_uses_detected_blob_format(tmp_path: Path) -> None:
    store, client = make_store(tmp_path, b"\xff\xd8\xff" + b"jpeg data")
    asset = Asset(
        id="image-example",
        kind=AssetKind.IMAGE,
        source_url="https://cdn.example.com/image.webp",
        original_filename="image.webp",
        media_type="image/webp",
    )
    try:
        stored, _ = store.ingest(asset, NOW)
    finally:
        client.close()

    assert stored.original_filename == "image.webp"
    assert stored.media_type == "image/jpeg"
    assert stored.declared_media_type == "image/webp"
    assert stored.blob_path and stored.blob_path.endswith(".jpg")


def test_explicitly_rejected_asset_has_no_blob_requirement(tmp_path: Path) -> None:
    product = Product(
        id="sample-product",
        name="Sample",
        assets=[
            Asset(
                id="archive-rejected",
                kind=AssetKind.ARCHIVE,
                source_url="https://example.com/oversize.zip",
                original_filename="oversize.zip",
                media_type="application/zip",
                retrieved_at=NOW,
                rejection_reason="asset exceeds download limit",
            )
        ],
        first_seen=NOW,
        last_seen=NOW,
    )

    assert validate_product(product, Catalog(tmp_path)) == []


def test_archive_limits_compression_ratio(tmp_path: Path) -> None:
    content = io.BytesIO()
    with zipfile.ZipFile(content, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("large.stl", b"0" * 100_000)
    store, client = make_store(tmp_path, content.getvalue())
    store.limits = DownloadLimits(max_compression_ratio=2)
    try:
        with pytest.raises(UnsafeAssetError):
            store.ingest(archive_asset(), NOW)
    finally:
        client.close()


def test_materialize_reconstructs_member_path(tmp_path: Path) -> None:
    catalog = Catalog(tmp_path)
    blob = catalog.blob_path("a" * 64, ".step")
    blob.parent.mkdir(parents=True)
    blob.write_bytes(b"ISO-10303-21;")
    product = Product(
        id="sample-product",
        name="Sample",
        assets=[
            Asset(
                id="model-child",
                kind=AssetKind.MODEL,
                source_url="https://example.com/archive.zip",
                original_filename="part.step",
                media_type="model/step",
                sha256="a" * 64,
                size=14,
                blob_path=blob.relative_to(tmp_path).as_posix(),
                retrieved_at=NOW,
                parent_asset_id="archive-parent",
                archive_member_path="CAD/part.step",
            ),
            Asset(
                id="archive-parent",
                kind=AssetKind.ARCHIVE,
                source_url="https://example.com/archive.zip",
                original_filename="archive.zip",
                media_type="application/zip",
            ),
        ],
        first_seen=NOW,
        last_seen=NOW,
    )
    catalog.write_product(product)
    output = tmp_path / "out"
    assert materialize_product(catalog, product.id, output) == 1
    assert (output / "extracted/archive-parent/CAD/part.step").read_bytes() == b"ISO-10303-21;"
