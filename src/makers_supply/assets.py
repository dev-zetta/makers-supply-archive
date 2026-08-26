from __future__ import annotations

import hashlib
import mimetypes
import os
import re
import shutil
import stat
import zipfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path, PurePosixPath

import httpx
from pydantic import HttpUrl

from makers_supply.http import ArchiveHttpClient
from makers_supply.models import Asset, AssetKind, RightsStatus
from makers_supply.parser import ParsedAsset
from makers_supply.storage import Catalog, atomic_write
from makers_supply.validation import sha256_file

EXTRACTABLE_SUFFIXES = {".3mf", ".dxf", ".dwg", ".iges", ".igs", ".step", ".stl", ".stp"}
MAX_DOWNLOAD_SIZE = 512 * 1024 * 1024
MAX_ARCHIVE_FILES = 10_000
MAX_ARCHIVE_EXPANDED_SIZE = 2 * 1024 * 1024 * 1024
MAX_COMPRESSION_RATIO = 200
CHUNK_SIZE = 1024 * 1024
IMAGE_SUFFIXES = {".avif", ".gif", ".jpeg", ".jpg", ".png", ".webp"}


class UnsafeAssetError(ValueError):
    pass


@dataclass(frozen=True)
class DownloadLimits:
    max_download_size: int = MAX_DOWNLOAD_SIZE
    max_archive_files: int = MAX_ARCHIVE_FILES
    max_archive_expanded_size: int = MAX_ARCHIVE_EXPANDED_SIZE
    max_compression_ratio: int = MAX_COMPRESSION_RATIO


DEFAULT_LIMITS = DownloadLimits()


def make_asset_id(kind: AssetKind, identity: str) -> str:
    digest = hashlib.sha256(identity.encode()).hexdigest()[:20]
    return f"{kind.value}-{digest}"


def asset_from_parsed(parsed: ParsedAsset) -> Asset:
    return Asset(
        id=make_asset_id(parsed.kind, parsed.url),
        kind=parsed.kind,
        source_url=HttpUrl(parsed.url),
        original_filename=parsed.filename,
        media_type=parsed.media_type,
        rights_status=RightsStatus.UNKNOWN,
    )


def _suffix(filename: str) -> str:
    return PurePosixPath(filename).suffix.lower() or ".bin"


def _detected_image(path: Path) -> tuple[str, str] | None:
    with path.open("rb") as stream:
        head = stream.read(512)
    if head.startswith((b"GIF87a", b"GIF89a")):
        return ".gif", "image/gif"
    if head.startswith(b"\xff\xd8\xff"):
        return ".jpg", "image/jpeg"
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png", "image/png"
    if head.startswith(b"RIFF") and head[8:12] == b"WEBP":
        return ".webp", "image/webp"
    if head[4:8] == b"ftyp" and head[8:12] in {b"avif", b"avis"}:
        return ".avif", "image/avif"
    return None


def _check_signature(path: Path, filename: str) -> None:
    suffix = _suffix(filename)
    with path.open("rb") as stream:
        head = stream.read(512)
    stripped = head.lstrip().lower()
    if stripped.startswith((b"<!doctype html", b"<html", b"<?xml")) and suffix not in {
        ".svg",
        ".xml",
    }:
        raise UnsafeAssetError(f"{filename} contains HTML/XML instead of the expected asset")
    if stripped.startswith((b"{", b"[")) and suffix not in {".json"}:
        raise UnsafeAssetError(f"{filename} contains JSON instead of the expected asset")
    signatures: dict[str, tuple[bytes, ...]] = {
        ".gif": (b"GIF87a", b"GIF89a"),
        ".jpg": (b"\xff\xd8\xff",),
        ".jpeg": (b"\xff\xd8\xff",),
        ".pdf": (b"%PDF-",),
        ".png": (b"\x89PNG\r\n\x1a\n",),
        ".zip": (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08"),
    }
    detected_image = _detected_image(path)
    if suffix in IMAGE_SUFFIXES and detected_image:
        valid = True
    elif suffix == ".webp":
        valid = head.startswith(b"RIFF") and head[8:12] == b"WEBP"
    elif suffix == ".3mf":
        valid = head.startswith((b"PK\x03\x04", b"PK\x05\x06"))
    elif suffix in signatures:
        valid = head.startswith(signatures[suffix])
    else:
        valid = True
    if not valid:
        raise UnsafeAssetError(f"{filename} does not match its file extension")


def _safe_member_path(name: str) -> PurePosixPath:
    normalized = PurePosixPath(name.replace("\\", "/"))
    if normalized.is_absolute() or not normalized.parts or ".." in normalized.parts:
        raise UnsafeAssetError(f"unsafe archive member path: {name}")
    if re.match(r"^[A-Za-z]:", normalized.parts[0]):
        raise UnsafeAssetError(f"unsafe archive member drive path: {name}")
    return normalized


class AssetStore:
    def __init__(
        self,
        catalog: Catalog,
        client: ArchiveHttpClient,
        staging_dir: Path,
        limits: DownloadLimits = DEFAULT_LIMITS,
    ) -> None:
        self.catalog = catalog
        self.client = client
        self.staging_dir = staging_dir
        self.limits = limits
        self.downloads_dir = staging_dir / "downloads"

    def _download(self, asset: Asset) -> Path:
        self.downloads_dir.mkdir(parents=True, exist_ok=True)
        key = hashlib.sha256(str(asset.source_url).encode()).hexdigest()
        partial = self.downloads_dir / f"{key}.part"
        complete = self.downloads_dir / f"{key}.complete"
        if partial.is_file() and complete.is_file():
            expected_hash = complete.read_text("ascii").strip()
            if expected_hash and sha256_file(partial) == expected_hash:
                _check_signature(partial, asset.original_filename)
                return partial
            complete.unlink(missing_ok=True)
        existing = partial.stat().st_size if partial.exists() else 0
        headers = {"Range": f"bytes={existing}-"} if existing else None
        try:
            response = self.client.request(
                "GET", str(asset.source_url), headers=headers, stream=True
            )
        except httpx.HTTPStatusError as error:
            content_range = error.response.headers.get("Content-Range", "")
            match = re.fullmatch(r"bytes \*/(\d+)", content_range)
            if error.response.status_code == 416 and match and int(match.group(1)) == existing:
                _check_signature(partial, asset.original_filename)
                atomic_write(complete, sha256_file(partial) + "\n")
                return partial
            raise
        try:
            append = existing > 0 and response.status_code == 206
            starting_size = existing if append else 0
            content_length = response.headers.get("Content-Length")
            if (
                content_length
                and starting_size + int(content_length) > self.limits.max_download_size
            ):
                raise UnsafeAssetError(f"asset exceeds download limit: {asset.source_url}")
            mode = "ab" if append else "wb"
            with partial.open(mode) as stream:
                for chunk in response.iter_bytes(CHUNK_SIZE):
                    stream.write(chunk)
                    if stream.tell() > self.limits.max_download_size:
                        raise UnsafeAssetError(
                            f"asset exceeds download limit: {asset.source_url}"
                        )
        finally:
            response.close()
        if partial.stat().st_size == 0:
            raise UnsafeAssetError(f"empty asset: {asset.source_url}")
        _check_signature(partial, asset.original_filename)
        atomic_write(complete, sha256_file(partial) + "\n")
        return partial

    def _store_file(self, source: Path, filename: str) -> tuple[str, int, str]:
        digest = sha256_file(source)
        destination = self.catalog.blob_path(digest, _suffix(filename))
        relative = destination.relative_to(self.catalog.root).as_posix()
        if destination.exists():
            if destination.stat().st_size != source.stat().st_size:
                raise UnsafeAssetError(f"hash collision at {relative}")
        else:
            atomic_write(destination, source.read_bytes())
        # Blobs are mounted into the web container read-only and served by its
        # unprivileged user. Temporary downloads intentionally start private,
        # but committed archive content must be readable independently of the
        # account that performed the synchronization.
        destination.chmod(0o644)
        return digest, source.stat().st_size, relative

    def ingest(self, asset: Asset, retrieved_at: datetime) -> tuple[Asset, list[Asset]]:
        partial = self._download(asset)
        detected_image = _detected_image(partial)
        storage_filename = asset.original_filename
        media_type = asset.media_type
        declared_media_type = asset.declared_media_type
        if detected_image:
            detected_suffix, detected_media_type = detected_image
            expected_suffix = _suffix(asset.original_filename)
            equivalent_suffixes = {expected_suffix, detected_suffix} <= {".jpeg", ".jpg"}
            if expected_suffix != detected_suffix and not equivalent_suffixes:
                declared_media_type = asset.media_type
                media_type = detected_media_type
                storage_filename = f"{Path(asset.original_filename).stem}{detected_suffix}"
        digest, size, blob_path = self._store_file(partial, storage_filename)
        stored = asset.model_copy(
            update={
                "media_type": media_type,
                "declared_media_type": declared_media_type,
                "sha256": digest,
                "size": size,
                "blob_path": blob_path,
                "retrieved_at": retrieved_at,
            }
        )
        extracted = self.extract(stored) if _suffix(stored.original_filename) == ".zip" else []
        return stored, extracted

    def extract(self, archive: Asset) -> list[Asset]:
        if archive.blob_path is None:
            raise ValueError("archive must be stored before extraction")
        archive_path = self.catalog.root / archive.blob_path
        extracted: list[Asset] = []
        seen_paths: set[str] = set()
        total_size = 0
        try:
            bundle = zipfile.ZipFile(archive_path)
        except zipfile.BadZipFile as error:
            raise UnsafeAssetError(f"invalid ZIP archive {archive.original_filename}") from error
        with bundle:
            members = bundle.infolist()
            if len(members) > self.limits.max_archive_files:
                raise UnsafeAssetError("archive has too many members")
            for member in members:
                member_path = _safe_member_path(member.filename)
                normalized = member_path.as_posix().casefold()
                if normalized in seen_paths:
                    raise UnsafeAssetError(f"duplicate archive member: {member.filename}")
                seen_paths.add(normalized)
                mode = member.external_attr >> 16
                if stat.S_ISLNK(mode):
                    raise UnsafeAssetError(f"archive contains symlink: {member.filename}")
                if member.flag_bits & 0x1:
                    raise UnsafeAssetError(f"archive contains encrypted member: {member.filename}")
                total_size += member.file_size
                if total_size > self.limits.max_archive_expanded_size:
                    raise UnsafeAssetError("archive expanded size exceeds limit")
                compressed = max(member.compress_size, 1)
                if member.file_size / compressed > self.limits.max_compression_ratio:
                    raise UnsafeAssetError(f"suspicious compression ratio: {member.filename}")
                if member.is_dir() or member_path.suffix.lower() not in EXTRACTABLE_SUFFIXES:
                    continue
                temporary = self.staging_dir / "extract" / archive.id / member_path
                temporary.parent.mkdir(parents=True, exist_ok=True)
                with bundle.open(member) as source, temporary.open("wb") as target:
                    shutil.copyfileobj(source, target, CHUNK_SIZE)
                _check_signature(temporary, member_path.name)
                digest, size, blob_path = self._store_file(temporary, member_path.name)
                extracted.append(
                    Asset(
                        id=make_asset_id(AssetKind.MODEL, f"{archive.id}:{member_path.as_posix()}"),
                        kind=AssetKind.MODEL,
                        source_url=archive.source_url,
                        original_filename=member_path.name,
                        media_type=mimetypes.guess_type(member_path.name)[0]
                        or "application/octet-stream",
                        sha256=digest,
                        size=size,
                        blob_path=blob_path,
                        rights_status=archive.rights_status,
                        retrieved_at=archive.retrieved_at,
                        parent_asset_id=archive.id,
                        archive_member_path=member_path.as_posix(),
                    )
                )
        return extracted


def materialized_asset_path(asset: Asset) -> Path:
    """Return an accessible, collision-resistant path ending in the original filename."""
    if asset.image_processing and asset.parent_asset_id:
        return Path("display") / asset.parent_asset_id / asset.original_filename
    if asset.parent_asset_id and asset.archive_member_path:
        return Path("extracted") / asset.parent_asset_id / Path(asset.archive_member_path)
    return Path("source") / asset.id / asset.original_filename


def materialize_product(catalog: Catalog, product_id: str, output: Path) -> int:
    product = catalog.load_product(product_id)
    written = 0
    for asset in product.assets:
        if not asset.blob_path:
            continue
        source = catalog.root / asset.blob_path
        relative = materialized_asset_path(asset)
        target = output / relative
        resolved_output = output.resolve()
        resolved_target = target.resolve()
        if resolved_output not in resolved_target.parents:
            raise UnsafeAssetError(f"materialized path escapes output: {relative}")
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        os.utime(target, (0, 0))
        written += 1
    return written
