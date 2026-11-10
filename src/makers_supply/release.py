"""Deterministic offline data packs and verification of their installed payload."""

from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
import zipfile
from pathlib import Path, PurePosixPath
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from makers_supply import __version__
from makers_supply.portable import build_portable_database, portable_files
from makers_supply.storage import Catalog, atomic_write, snapshot_identity
from makers_supply.validation import sha256_file

PACK_LIMIT = 1_800_000_000
INSTALLATION = """Maker's Supply Catalog — offline installation

Download the app archive for your operating system and ALL makers-supply-data-*.zip
packs from the same release. Verify downloads against SHA256SUMS.txt. Extract the app
and every data ZIP into ONE directory (on Windows prefer C:\\MakersSupply to avoid
legacy path-length limits). There is no numbered-file concatenation step.

That directory must contain the app, catalog.sqlite, catalog-manifest.json, and
assets/. On macOS keep the .app beside those data files. Start the app normally.
No Python, Node.js, Docker, account, or network connection is required.

These portable builds have no trusted publisher signature/notarization. Your OS may
show its normal unknown-publisher prompt. Only open downloads whose source and
checksums you trust; do not disable system security globally.

Keep user-state backups when upgrading. Extract a new release into a fresh directory,
never mix its app/data packs with another release. Lists remain in your OS user-state
directory. Source assets retain their original filenames and rights metadata remains
unknown unless an affirmative license is recorded. See NOTICE.md.
"""


def _relative(value: str) -> str:
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or ".." in path.parts
        or not path.parts
        or "\\" in value
        or ":" in value
        or value != path.as_posix()
    ):
        raise ValueError(f"unsafe payload path: {value}")
    return value


class PayloadFile(BaseModel):
    path: str
    size: int = Field(ge=0)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    pack: str = ""

    _path = field_validator("path")(_relative)


class DataManifest(BaseModel):
    schema_version: Literal[1] = 1
    app_version: str = __version__
    catalog_schema: Literal[5] = 5
    snapshot_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    revision: str
    files: list[PayloadFile]


class ArchiveFile(BaseModel):
    name: str
    size: int = Field(ge=0)
    sha256: str


class ReleaseManifest(BaseModel):
    schema_version: Literal[1] = 1
    app_version: str = __version__
    snapshot_id: str
    revision: str
    data_manifest_sha256: str
    packs: list[ArchiveFile]


def _json(model: BaseModel) -> bytes:
    return (
        json.dumps(model.model_dump(), sort_keys=True, ensure_ascii=False, indent=2) + "\n"
    ).encode()


def _zip_cost(name: str, size: int) -> int:
    # Stored entries: local header + central directory entry + names (no ZIP64).
    return 76 + 2 * len(name.encode("utf-8")) + size


def _groups(files: list[PayloadFile], limit: int, bootstrap_size: int) -> list[list[PayloadFile]]:
    size = 22 + _zip_cost("catalog-manifest.json", bootstrap_size)
    if size > limit:
        raise ValueError("pack limit is too small for catalog-manifest.json")
    groups: list[list[PayloadFile]] = [[]]
    for item in files:
        cost = _zip_cost(item.path, item.size)
        if cost + 22 > limit:
            raise ValueError(f"payload file exceeds pack limit: {item.path}")
        if size + cost > limit:
            groups.append([])
            size = 22
        groups[-1].append(item)
        size += cost
    return groups


def _zip_info(name: str, size: int) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
    info.create_system = 3
    info.external_attr = 0o100644 << 16
    info.compress_type = zipfile.ZIP_STORED
    info.file_size = size
    return info


def write_checksums(directory: Path) -> None:
    files = sorted(p for p in directory.iterdir() if p.is_file() and p.name != "SHA256SUMS.txt")
    atomic_write(
        directory / "SHA256SUMS.txt", "".join(f"{sha256_file(p)}  {p.name}\n" for p in files)
    )


def build_data_packs(
    catalog: Catalog, output: Path, *, revision: str, max_pack_bytes: int = PACK_LIMIT
) -> ReleaseManifest:
    if not 0 < max_pack_bytes <= PACK_LIMIT:
        raise ValueError(f"max_pack_bytes must be between 1 and {PACK_LIMIT}")
    output.mkdir(parents=True, exist_ok=True)
    if any(output.iterdir()):
        raise FileExistsError(f"data-pack output must be empty: {output}")
    with tempfile.TemporaryDirectory(prefix="data-pack-", dir=output) as temporary:
        work = Path(temporary)
        entries = portable_files(catalog)
        database = work / "catalog.sqlite"
        build_portable_database(catalog, database, entries)
        sources = {item.relative.as_posix(): item.source for item in entries}
        sources["catalog.sqlite"] = database
        files = [
            PayloadFile(
                path=item.relative.as_posix(),
                size=item.source.stat().st_size,
                sha256=item.asset.sha256 or sha256_file(item.source),
            )
            for item in entries
        ]
        files.append(
            PayloadFile(
                path="catalog.sqlite", size=database.stat().st_size, sha256=sha256_file(database)
            )
        )
        files.sort(key=lambda item: item.path)
        manifest = DataManifest(
            snapshot_id=snapshot_identity(catalog.root), revision=revision, files=files
        )
        reserve = len(_json(manifest))
        while True:
            groups = _groups(files, max_pack_bytes, reserve)
            for number, group in enumerate(groups, 1):
                for item in group:
                    item.pack = f"makers-supply-data-{__version__}-{number:03}.zip"
            bootstrap = _json(manifest)
            if len(bootstrap) <= reserve:
                break
            reserve = len(bootstrap)
        archives = []
        for number, group in enumerate(groups, 1):
            name = f"makers-supply-data-{__version__}-{number:03}.zip"
            destination = work / name
            with zipfile.ZipFile(destination, "w", allowZip64=False) as archive:
                if number == 1:
                    archive.writestr(_zip_info("catalog-manifest.json", len(bootstrap)), bootstrap)
                for item in group:
                    digest = hashlib.sha256()
                    size = 0
                    with (
                        sources[item.path].open("rb") as source,
                        archive.open(_zip_info(item.path, item.size), "w") as target,
                    ):
                        while chunk := source.read(1024 * 1024):
                            target.write(chunk)
                            digest.update(chunk)
                            size += len(chunk)
                    if size != item.size or digest.hexdigest() != item.sha256:
                        raise ValueError(f"payload hash/size mismatch: {item.path}")
            if destination.stat().st_size > max_pack_bytes:
                raise ValueError(f"archive exceeds pack limit: {name}")
            archives.append(
                ArchiveFile(
                    name=name, size=destination.stat().st_size, sha256=sha256_file(destination)
                )
            )
        release = ReleaseManifest(
            snapshot_id=manifest.snapshot_id,
            revision=revision,
            data_manifest_sha256=hashlib.sha256(bootstrap).hexdigest(),
            packs=archives,
        )
        atomic_write(work / "release-manifest.json", _json(release))
        atomic_write(work / "INSTALL.txt", INSTALLATION)
        for path in sorted(work.iterdir()):
            if path.name != "catalog.sqlite":
                shutil.move(path, output / path.name)
    write_checksums(output)
    return release


def verify_installed_catalog(root: Path, *, full_hash: bool = False) -> DataManifest:
    root = root.resolve()
    instructions = "Extract every data pack from the same release beside the app."
    path = root / "catalog-manifest.json"
    try:
        manifest = DataManifest.model_validate_json(path.read_bytes())
    except (OSError, ValueError) as error:
        raise ValueError(f"Catalog manifest is missing or invalid. {instructions}") from error
    if manifest.app_version != __version__:
        raise ValueError(
            f"Catalog data is for {manifest.app_version}; app is {__version__}. " + instructions
        )
    seen: set[str] = set()
    for item in manifest.files:
        if item.path in seen:
            raise ValueError(f"Duplicate catalog payload: {item.path}")
        seen.add(item.path)
        target = (root / item.path).resolve()
        if (
            not target.is_relative_to(root)
            or not target.is_file()
            or target.stat().st_size != item.size
        ):
            raise ValueError(
                f"Missing or incomplete {item.path} (pack {item.pack}). {instructions}"
            )
        if (full_hash or item.path == "catalog.sqlite") and sha256_file(target) != item.sha256:
            raise ValueError(f"Catalog payload is corrupt: {item.path}. {instructions}")
    if "catalog.sqlite" not in seen:
        raise ValueError(f"Catalog database is absent from the manifest. {instructions}")
    return manifest


def write_bundled_manifest(catalog: Catalog, output: Path, *, revision: str) -> None:
    files = []
    for entry in portable_files(catalog):
        files.append(
            PayloadFile(
                path=entry.relative.as_posix(),
                size=entry.source.stat().st_size,
                sha256=entry.asset.sha256 or sha256_file(entry.source),
                pack="bundled app archive",
            )
        )
    database = output / "catalog.sqlite"
    files.append(
        PayloadFile(
            path="catalog.sqlite",
            size=database.stat().st_size,
            sha256=sha256_file(database),
            pack="bundled app archive",
        )
    )
    manifest = DataManifest(
        snapshot_id=snapshot_identity(catalog.root), revision=revision, files=files
    )
    atomic_write(output / "catalog-manifest.json", _json(manifest))
