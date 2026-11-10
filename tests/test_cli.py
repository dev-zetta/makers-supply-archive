import json
import tomllib
from pathlib import Path

from makers_supply import __version__


def test_version() -> None:
    assert __version__ == "1.1.0"


def test_package_and_lock_versions_are_consistent() -> None:
    root = Path(__file__).parents[1]
    for relative in ("pyproject.toml", "apps/catalog-web/pyproject.toml"):
        metadata = tomllib.loads((root / relative).read_text("utf-8"))
        assert metadata["project"]["version"] == __version__
    package = json.loads((root / "apps/catalog-desktop/package.json").read_text("utf-8"))
    lock = json.loads((root / "apps/catalog-desktop/package-lock.json").read_text("utf-8"))
    assert package["version"] == lock["version"] == lock["packages"][""]["version"] == __version__
    python_lock = tomllib.loads((root / "uv.lock").read_text("utf-8"))
    for package in python_lock["package"]:
        if package["name"] in {"makers-supply-archive", "makers-supply-web"}:
            assert package["version"] == __version__
