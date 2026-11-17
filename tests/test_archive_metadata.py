"""Pico-style ZIP metadata must not become CAD or hide unsafe members."""

import io
import stat
import zipfile
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from makersfridge.assets import AssetStore, DownloadLimits, UnsafeAssetError, materialize_product
from makersfridge.http import ArchiveHttpClient
from makersfridge.models import Asset, AssetKind, Product, RightsStatus
from makersfridge.storage import Catalog

NOW = datetime(2026, 11, 17, tzinfo=UTC)
STEP = b"ISO-10303-21;\nHEADER;\nENDSEC;\nEND-ISO-10303-21;"


def bundle_bytes(files: dict[str, bytes], *, compressed: bool = False) -> bytes:
    output = io.BytesIO()
    method = zipfile.ZIP_DEFLATED if compressed else zipfile.ZIP_STORED
    with zipfile.ZipFile(output, "w", compression=method) as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    return output.getvalue()


def archive() -> Asset:
    return Asset(
        id="archive-pico-metadata",
        kind=AssetKind.ARCHIVE,
        source_url="https://example.com/Pico-R3.zip",
        original_filename="Pico-R3.zip",
        media_type="application/zip",
        role="component",
        applies_to_skus=["SC0915"],
        hardware_revision="R3",
        rights_status=RightsStatus.LICENSED,
        license_url="https://example.com/licenses/pico-model.txt",
    )


def client_for(content: bytes) -> ArchiveHttpClient:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        return httpx.Response(200, content=content)

    return ArchiveHttpClient(delay=0, transport=httpx.MockTransport(handler))


def test_pico_zip_skips_appledouble_and_keeps_model_and_license(tmp_path: Path) -> None:
    license_text = b"Copyright model author. Licensed under the linked model license."
    content = bundle_bytes(
        {
            "Pico-R3.step": STEP,
            "__MACOSX/._Pico-R3.step": b"\x00\x05\x16\x07AppleDouble resource fork",
            "._Pico-R3.step": b"\x00\x05\x16\x07AppleDouble resource fork",
            "LICENSE.txt": license_text,
        }
    )
    catalog = Catalog(tmp_path)
    with client_for(content) as client:
        stored, children = AssetStore(catalog, client, tmp_path / ".staging").ingest(archive(), NOW)
    assert {asset.archive_member_path for asset in children} == {"Pico-R3.step", "LICENSE.txt"}
    model = next(asset for asset in children if asset.kind == AssetKind.MODEL)
    notice = next(asset for asset in children if asset.kind == AssetKind.DOCUMENT)
    assert model.original_filename == "Pico-R3.step" and model.role == "component"
    assert notice.original_filename == "LICENSE.txt" and notice.role == "document"
    assert notice.media_type == "text/plain"
    for asset in children:
        assert asset.parent_asset_id == stored.id
        assert asset.rights_status == RightsStatus.LICENSED
        assert asset.license_url == stored.license_url
        assert asset.applies_to_skus == ["SC0915"]
        assert asset.hardware_revision == "R3"
    assert model.blob_path and (tmp_path / model.blob_path).read_bytes() == STEP
    assert notice.blob_path and (tmp_path / notice.blob_path).read_bytes() == license_text
    catalog.write_product(
        Product(
            id="raspberry-pi-pico-reference",
            name="Pico reference",
            first_seen=NOW,
            last_seen=NOW,
            assets=[stored, *children],
        )
    )
    exported = tmp_path / "export"
    assert materialize_product(catalog, "raspberry-pi-pico-reference", exported) == 3
    assert {path.name for path in exported.rglob("*") if path.is_file()} == {
        "Pico-R3.zip",
        "Pico-R3.step",
        "LICENSE.txt",
    }


def test_metadata_folder_cannot_hide_traversal(tmp_path: Path) -> None:
    content = bundle_bytes({"__MACOSX/../../escape.step": STEP})
    with client_for(content) as client, pytest.raises(UnsafeAssetError, match="unsafe"):
        AssetStore(Catalog(tmp_path), client, tmp_path / ".staging").ingest(archive(), NOW)
    assert not (tmp_path.parent / "escape.step").exists()


def test_metadata_folder_cannot_hide_symlinks(tmp_path: Path) -> None:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive_zip:
        member = zipfile.ZipInfo("__MACOSX/._Pico-R3.step")
        member.create_system = 3
        member.external_attr = (stat.S_IFLNK | 0o777) << 16
        archive_zip.writestr(member, "../../escape.step")
    with client_for(output.getvalue()) as client, pytest.raises(UnsafeAssetError, match="symlink"):
        AssetStore(Catalog(tmp_path), client, tmp_path / ".staging").ingest(archive(), NOW)


def test_metadata_folder_counts_toward_expansion_limit(tmp_path: Path) -> None:
    content = bundle_bytes({"__MACOSX/._Pico-R3.step": bytes(range(100))})
    with client_for(content) as client, pytest.raises(UnsafeAssetError, match="expanded size"):
        store = AssetStore(
            Catalog(tmp_path),
            client,
            tmp_path / ".staging",
            limits=DownloadLimits(max_archive_expanded_size=64),
        )
        store.ingest(archive(), NOW)


def test_metadata_folder_cannot_hide_suspicious_compression(tmp_path: Path) -> None:
    content = bundle_bytes({"__MACOSX/._Pico-R3.step": b"x" * 100_000}, compressed=True)
    with client_for(content) as client, pytest.raises(UnsafeAssetError, match="compression ratio"):
        AssetStore(Catalog(tmp_path), client, tmp_path / ".staging").ingest(archive(), NOW)
