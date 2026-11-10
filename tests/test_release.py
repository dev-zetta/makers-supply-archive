import hashlib
import json
import zipfile
from pathlib import Path

import pytest
from test_storage_database import sample_product

from makers_supply.models import Asset, AssetKind
from makers_supply.release import PayloadFile, build_data_packs, verify_installed_catalog
from makers_supply.storage import Catalog


def release_catalog(root: Path) -> Catalog:
    catalog = Catalog(root)
    assets = []
    for number in range(3):
        content = bytes([number]) * 150_000
        digest = hashlib.sha256(content).hexdigest()
        blob = catalog.blob_path(digest, ".step")
        blob.parent.mkdir(parents=True, exist_ok=True)
        blob.write_bytes(content)
        assets.append(
            Asset(
                id=f"part-{number}",
                kind=AssetKind.MODEL,
                    media_type="model/step",
                source_url=f"https://example.com/{number}.step",
                original_filename=f"Příliš part {number}.step",
                sha256=digest,
                size=len(content),
                blob_path=blob.relative_to(root).as_posix(),
            )
        )
    catalog.write_product(sample_product().model_copy(update={"assets": assets}))
    return catalog


def unpack(output: Path, destination: Path, names: list[str]) -> None:
    for name in names:
        with zipfile.ZipFile(output / name) as archive:
            archive.extractall(destination)


def test_packs_are_deterministic_complete_and_bounded(tmp_path: Path) -> None:
    catalog = release_catalog(tmp_path / "source")
    first = build_data_packs(catalog, tmp_path / "one", revision="abc", max_pack_bytes=256_000)
    second = build_data_packs(catalog, tmp_path / "two", revision="abc", max_pack_bytes=256_000)
    assert first == second
    assert len(first.packs) > 1
    assert all(pack.size <= 256_000 for pack in first.packs)
    assert (tmp_path / "one/SHA256SUMS.txt").read_bytes() == (
        tmp_path / "two/SHA256SUMS.txt"
    ).read_bytes()
    installed = tmp_path / "Unicode Ž / catalog"
    unpack(tmp_path / "one", installed, [pack.name for pack in first.packs])
    manifest = verify_installed_catalog(installed, full_hash=True)
    assert len(manifest.files) == 4
    assert len(list((installed / "assets").rglob("*.step"))) == 3
    for item in manifest.files:
        assert hashlib.sha256((installed / item.path).read_bytes()).hexdigest() == item.sha256


def test_incomplete_corrupt_and_mismatched_packs_fail_clearly(tmp_path: Path) -> None:
    catalog = release_catalog(tmp_path / "source")
    result = build_data_packs(catalog, tmp_path / "packs", revision="abc", max_pack_bytes=256_000)
    installed = tmp_path / "installed"
    unpack(tmp_path / "packs", installed, [result.packs[0].name])
    with pytest.raises(ValueError, match="Missing or incomplete"):
        verify_installed_catalog(installed)
    unpack(tmp_path / "packs", installed, [p.name for p in result.packs[1:]])
    manifest = verify_installed_catalog(installed)
    target = installed / manifest.files[0].path
    content = target.read_bytes()
    target.write_bytes(b"X" + content[1:])
    with pytest.raises(ValueError, match="corrupt"):
        verify_installed_catalog(installed, full_hash=True)
    target.write_bytes(content)
    path = installed / "catalog-manifest.json"
    data = json.loads(path.read_text())
    data["app_version"] = "0.0.0"
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="app is"):
        verify_installed_catalog(installed)


def test_bad_source_hash_and_too_small_pack_limit_are_rejected(tmp_path: Path) -> None:
    catalog = release_catalog(tmp_path / "source")
    with pytest.raises(ValueError, match="exceeds pack limit|too small"):
        build_data_packs(catalog, tmp_path / "tiny", revision="abc", max_pack_bytes=10_000)
    product = catalog.products()[0]
    product.assets[0].sha256 = "f" * 64
    catalog.write_product(product)
    with pytest.raises(ValueError, match="hash/size mismatch"):
        build_data_packs(catalog, tmp_path / "bad", revision="abc")
    assert list((tmp_path / "bad").iterdir()) == []


@pytest.mark.parametrize("path", ["../escape", "/absolute", "C:/drive", "a\\b", "a/../b"])
def test_manifest_rejects_unsafe_paths(path: str) -> None:
    with pytest.raises(ValueError, match="unsafe payload path"):
        PayloadFile(path=path, size=1, sha256="a" * 64)
