from __future__ import annotations

import os
from pathlib import Path

import pytest
from makersfridge_web import standalone
from makersfridge_web.app import selected_region
from makersfridge_web.config import Settings
from starlette.requests import Request


@pytest.fixture(autouse=True)
def clear_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in os.environ:
        if name.startswith(("MAKERSFRIDGE_", "MAKERS_SUPPLY_")):
            monkeypatch.delenv(name)


def test_existing_web_configuration_and_catalog_remain_usable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "dist").mkdir()
    legacy = tmp_path / "dist/makers-supply.sqlite"
    legacy.touch()
    monkeypatch.setenv("MAKERS_SUPPLY_ROOT", str(tmp_path))
    monkeypatch.setenv("MAKERS_SUPPLY_STATE_DB", str(tmp_path / "saved.sqlite"))
    monkeypatch.setenv("MAKERS_SUPPLY_SECRET_KEY", "existing-secret")
    monkeypatch.setenv("MAKERS_SUPPLY_SECURE_COOKIES", "0")
    settings = Settings.from_environment()
    assert settings.catalog_db == legacy
    assert settings.state_db == tmp_path / "saved.sqlite"
    assert settings.secret_key == "existing-secret"
    assert not settings.secure_cookies

    current = tmp_path / "dist/makersfridge.sqlite"
    current.touch()
    monkeypatch.setenv("MAKERSFRIDGE_ROOT", str(tmp_path))
    monkeypatch.setenv("MAKERSFRIDGE_STATE_DB", str(tmp_path / "current.sqlite"))
    monkeypatch.setenv("MAKERSFRIDGE_SECRET_KEY", "current-secret")
    monkeypatch.setenv("MAKERSFRIDGE_SECURE_COOKIES", "1")
    settings = Settings.from_environment()
    assert settings.catalog_db == current
    assert settings.state_db == tmp_path / "current.sqlite"
    assert settings.secret_key == "current-secret"
    assert settings.secure_cookies


@pytest.mark.parametrize("platform", ["linux", "darwin", "win32"])
def test_desktop_state_survives_rename_on_each_platform(
    platform: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(standalone.sys, "platform", platform)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "windows"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "linux"))
    base = {
        "linux": tmp_path / "linux",
        "darwin": tmp_path / "Library/Application Support",
        "win32": tmp_path / "windows",
    }[platform]
    assert standalone.state_directory() == base / "makersfridge"
    legacy = base / "makers-supply-catalog"
    legacy.mkdir(parents=True)
    (legacy / "secret").write_text("preserved-secret\n")
    (legacy / "state.sqlite").write_bytes(b"saved lists and build progress")
    assert standalone.state_directory() == legacy
    assert standalone.local_secret(standalone.state_directory()) == "preserved-secret"
    (base / "makersfridge").mkdir()
    assert standalone.state_directory() == base / "makersfridge"
    assert (legacy / "state.sqlite").read_bytes() == b"saved lists and build progress"


@pytest.mark.parametrize(
    ("cookies", "expected"),
    [
        ("makers_supply_region=eu", "eu"),
        ("makers_supply_region=eu; makersfridge_region=kr", "kr"),
        ("makers_supply_region=invalid", "us"),
    ],
)
def test_existing_region_preference(cookies: str, expected: str) -> None:
    request = Request({"type": "http", "headers": [(b"cookie", cookies.encode())]})
    assert selected_region(request) == expected
