from pathlib import Path
from uuid import uuid4

import pytest
from makers_supply_web.cli import app
from makers_supply_web.security import PASSWORDS, now
from makers_supply_web.state import connect, migrate
from typer.testing import CliRunner


def test_create_admin_if_missing_is_non_interactive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state_db = tmp_path / "state.sqlite"
    migrate(state_db)
    with connect(state_db) as connection, connection:
        connection.execute(
            "INSERT INTO users VALUES (?, 'admin', ?, 1, 1, ?)",
            (str(uuid4()), PASSWORDS.hash("correct horse battery"), now().isoformat()),
        )
    monkeypatch.setenv("MAKERS_SUPPLY_ROOT", str(tmp_path))
    monkeypatch.setenv("MAKERS_SUPPLY_CATALOG_DB", str(tmp_path / "catalog.sqlite"))
    monkeypatch.setenv("MAKERS_SUPPLY_STATE_DB", str(state_db))
    monkeypatch.setenv("MAKERS_SUPPLY_SECRET_KEY", "test-secret")

    result = CliRunner().invoke(app, ["create-admin", "admin", "--if-missing"])

    assert result.exit_code == 0
    assert "already exists" in result.stdout
