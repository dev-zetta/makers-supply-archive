from datetime import datetime
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from makers_supply_web.app import create_app
from makers_supply_web.config import Settings
from makers_supply_web.security import PASSWORDS, now, token, token_hash
from makers_supply_web.state import connect, migrate


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def settings(tmp_path: Path) -> Settings:
    return Settings(
        root=tmp_path,
        catalog_db=tmp_path / "catalog.sqlite",
        state_db=tmp_path / "state.sqlite",
        secret_key="test-secret",
        secure_cookies=False,
    )


def create_user(config: Settings, username: str = "admin", admin: bool = True) -> str:
    migrate(config.state_db)
    user_id = str(uuid4())
    with connect(config.state_db) as connection, connection:
        connection.execute(
            "INSERT INTO users VALUES (?, ?, ?, ?, 1, ?)",
            (
                user_id,
                username,
                PASSWORDS.hash("correct horse battery"),
                int(admin),
                now().isoformat(),
            ),
        )
    return user_id


@pytest.mark.anyio
async def test_login_uses_hashed_session_and_csrf(tmp_path: Path) -> None:
    config = settings(tmp_path)
    create_user(config)
    transport = httpx.ASGITransport(app=create_app(config))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/login",
            data={"username": "admin", "password": "correct horse battery"},
            follow_redirects=False,
        )
        assert response.status_code == 303
        assert response.headers["x-content-type-options"] == "nosniff"
        assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
        raw_cookie = response.cookies["makers_supply_session"]
        with connect(config.state_db) as connection:
            session = connection.execute("SELECT * FROM sessions").fetchone()
        assert session is not None
        assert session["token_hash"] != raw_cookie
        assert len(session["csrf_token"]) > 20
        assert "max-age" not in response.headers["set-cookie"].casefold()


@pytest.mark.anyio
async def test_remember_me_persists_session_for_thirty_days(tmp_path: Path) -> None:
    config = settings(tmp_path)
    create_user(config)
    before = now()
    transport = httpx.ASGITransport(app=create_app(config))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/login",
            data={
                "username": "admin",
                "password": "correct horse battery",
                "remember_me": "true",
            },
            follow_redirects=False,
        )

    assert response.status_code == 303
    assert "max-age=2592000" in response.headers["set-cookie"].casefold()
    with connect(config.state_db) as connection:
        expiry = str(connection.execute("SELECT expires_at FROM sessions").fetchone()[0])
    lifetime = datetime.fromisoformat(expiry) - before
    assert 29 <= lifetime.days <= 30


@pytest.mark.anyio
async def test_invitation_is_single_use(tmp_path: Path) -> None:
    config = settings(tmp_path)
    admin_id = create_user(config)
    raw = token()
    with connect(config.state_db) as connection, connection:
        connection.execute(
            "INSERT INTO invites VALUES (?, ?, ?, NULL, NULL)",
            (token_hash(raw, config.secret_key), admin_id, "2999-01-01T00:00:00+00:00"),
        )
    transport = httpx.ASGITransport(app=create_app(config))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        first = await client.post(
            f"/invite/{raw}",
            data={"username": "maker", "password": "a secure password"},
            follow_redirects=False,
        )
        second = await client.post(
            f"/invite/{raw}",
            data={"username": "maker2", "password": "another secure password"},
        )
    assert first.status_code == 303
    assert second.status_code == 404
