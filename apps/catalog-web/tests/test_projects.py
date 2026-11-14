import hashlib
import io
import json
import sqlite3
import zipfile
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import replace
from pathlib import Path, PurePosixPath
from uuid import uuid4

import httpx
import pytest
from makers_supply_web import state
from makers_supply_web.app import create_app
from makers_supply_web.config import Settings
from makers_supply_web.security import PASSWORDS, now, token_hash
from makers_supply_web.state import connect, migrate
from test_catalog import authenticated_client, make_settings


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def csrf(settings: Settings, username: str = "admin") -> str:
    with connect(settings.state_db) as connection:
        return str(
            connection.execute(
                """SELECT s.csrf_token FROM sessions s JOIN users u ON u.id=s.user_id
               WHERE u.username=? ORDER BY s.created_at DESC, s.rowid DESC LIMIT 1""",
                (username,),
            ).fetchone()[0]
        )


@asynccontextmanager
async def logged_in(settings: Settings) -> AsyncIterator[httpx.AsyncClient]:
    client = await authenticated_client(settings)
    try:
        yield client
    finally:
        await client.aclose()


async def new_list(client: httpx.AsyncClient, settings: Settings) -> tuple[str, str]:
    response = await client.post(
        "/lists",
        data={
            "name": "Clock build",
            "region": "us",
            "csrf": csrf(settings),
        },
    )
    list_id = response.headers["location"].rsplit("/", 1)[-1]
    response = await client.post(
        f"/lists/{list_id}/items",
        data={
            "product_id": "ia005-power-board",
            "variant_id": "us-standard",
            "quantity": "3",
            "notes": "Keep this line note",
            "csrf": csrf(settings),
        },
    )
    assert response.status_code == 303
    with connect(settings.state_db) as connection:
        item_id = str(
            connection.execute("SELECT id FROM list_items WHERE list_id=?", (list_id,)).fetchone()[
                0
            ]
        )
    return list_id, item_id


def add_asset(
    settings: Settings,
    asset_id: str,
    content: bytes,
    *,
    filename: str = "part.stl",
    blob_path: str | None = None,
) -> None:
    blob_path = blob_path or f"assets/models/{asset_id}.stl"
    path = settings.root / blob_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    with sqlite3.connect(settings.catalog_db) as connection:
        connection.execute(
            """INSERT INTO assets (product_id, id, kind, source_url, original_filename,
               media_type, sha256, size, blob_path, rights_status, retrieved_at)
               VALUES ('ia005-power-board', ?, 'model', 'https://example.com/part.stl', ?,
               'model/stl', ?, ?, ?, 'unknown', '2026-01-02T00:00:00Z')""",
            (asset_id, filename, hashlib.sha256(content).hexdigest(), len(content), blob_path),
        )


def test_additive_migration_preserves_legacy_list_data_and_is_atomic(tmp_path: Path) -> None:
    database = tmp_path / "legacy.sqlite"
    with sqlite3.connect(database) as connection:
        connection.executescript(state.MIGRATIONS[0])
        connection.execute("PRAGMA user_version=1")
        connection.execute("INSERT INTO users VALUES ('u', 'Owner', 'hash', 0, 1, 'time')")
        connection.execute("INSERT INTO lists VALUES ('l', 'u', 'Clock', 'eu', 't1', 't2')")
        connection.execute(
            """INSERT INTO list_items VALUES
               ('i', 'l', 'p', 'eu-variant', 3, 'original note', '1.25', 'EUR', 't0', 't1', 't2')"""
        )
        before = connection.execute("SELECT * FROM list_items").fetchall()
    assert migrate(database) == 2
    assert migrate(database) == 2
    with connect(database) as connection:
        assert [tuple(row) for row in connection.execute("SELECT * FROM list_items")] == before
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 2
        assert connection.execute("SELECT COUNT(*) FROM list_item_progress").fetchone()[0] == 0
        assert connection.execute("SELECT region FROM lists").fetchone()[0] == "eu"


def test_failed_migration_rolls_back_schema_and_version(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = tmp_path / "state.sqlite"
    migrate(database)
    monkeypatch.setattr(
        state,
        "MIGRATIONS",
        [
            *state.MIGRATIONS,
            "CREATE TABLE unfinished (id TEXT); INVALID SQL;",
        ],
    )
    with pytest.raises(sqlite3.OperationalError):
        migrate(database)
    with connect(database) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 2
        assert (
            connection.execute("SELECT name FROM sqlite_master WHERE name='unfinished'").fetchone()
            is None
        )


@pytest.mark.anyio
async def test_build_progress_survives_app_recreation_without_changing_prices(
    tmp_path: Path,
) -> None:
    settings = make_settings(tmp_path)
    catalog_hash = hashlib.sha256(settings.catalog_db.read_bytes()).hexdigest()
    async with logged_in(settings) as client:
        list_id, item_id = await new_list(client, settings)
        token = csrf(settings)
        with connect(settings.state_db) as connection:
            original_item = tuple(
                connection.execute("SELECT * FROM list_items WHERE id=?", (item_id,)).fetchone()
            )
        assert (
            await client.post(
                f"/lists/{list_id}/build",
                data={
                    "build_status": "in_progress",
                    "notes": "Print first\nThen assemble <script>",
                    "csrf": token,
                },
            )
        ).status_code == 303
        assert (
            await client.post(
                f"/lists/{list_id}/items/{item_id}/progress",
                data={
                    "completed_quantity": "2",
                    "csrf": token,
                },
            )
        ).status_code == 303
        assert (
            await client.post(
                f"/lists/{list_id}/steps",
                data={
                    "label": "Print enclosure <script>",
                    "csrf": token,
                },
            )
        ).status_code == 303
        with connect(settings.state_db) as connection:
            step_id = connection.execute("SELECT id FROM build_steps").fetchone()[0]
        assert (
            await client.post(
                f"/lists/{list_id}/steps/{step_id}",
                data={
                    "completed": "true",
                    "csrf": token,
                },
            )
        ).status_code == 303
    # A new application and new login load state from SQLite, not client memory.
    async with logged_in(settings) as restarted:
        page = await restarted.get(f"/lists/{list_id}")
        exported = (await restarted.get(f"/lists/{list_id}/export?format=json")).json()
        assert exported["build"]["status"] == "in_progress"
        assert exported["build"]["completed_steps"] == 1
        assert exported["build"]["steps"][0]["completed_at"] is not None
        assert exported["build"]["percent"] == 66
        assert exported["items"][0]["completed_quantity"] == 2
        assert exported["items"][0]["variant_id"] == "us-standard"
        assert exported["current_totals"] == exported["captured_totals"] == {"USD": "18.87"}
        assert "2 of 3 parts completed" in page.text
        assert "&lt;script&gt;" in page.text and "<script>" not in page.text
        assert (
            await restarted.post(
                f"/lists/{list_id}/steps/{step_id}",
                data={
                    "completed": "false",
                    "csrf": csrf(settings),
                },
            )
        ).status_code == 303
        reopened = (await restarted.get(f"/lists/{list_id}/export?format=json")).json()
        assert reopened["build"]["steps"][0]["completed_at"] is None
    with connect(settings.state_db) as connection:
        assert (
            tuple(connection.execute("SELECT * FROM list_items WHERE id=?", (item_id,)).fetchone())
            == original_item
        )
    assert hashlib.sha256(settings.catalog_db.read_bytes()).hexdigest() == catalog_hash


@pytest.mark.anyio
async def test_quantity_changes_clamp_progress_and_removal_cascades(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    async with logged_in(settings) as client:
        list_id, item_id = await new_list(client, settings)
        token = csrf(settings)
        await client.post(
            f"/lists/{list_id}/items/{item_id}/progress",
            data={
                "completed_quantity": "2",
                "csrf": token,
            },
        )
        await client.post(
            f"/lists/{list_id}/items/{item_id}",
            data={
                "quantity": "1",
                "notes": "quantity reduced",
                "csrf": token,
            },
        )
        view = (await client.get(f"/lists/{list_id}/export?format=json")).json()
        assert view["items"][0]["completed_quantity"] == 1
        assert view["build"]["percent"] == 100
        await client.post(
            f"/lists/{list_id}/items/{item_id}",
            data={
                "quantity": "3",
                "csrf": token,
            },
        )
        view = (await client.get(f"/lists/{list_id}/export?format=json")).json()
        assert view["items"][0]["completed_quantity"] == 1
        await client.post(
            f"/lists/{list_id}/items/{item_id}",
            data={
                "quantity": "3",
                "remove": "true",
                "csrf": token,
            },
        )
        with connect(settings.state_db) as connection:
            assert connection.execute("SELECT COUNT(*) FROM list_item_progress").fetchone()[0] == 0


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("endpoint", "data"),
    [
        ("build", {"build_status": "invalid"}),
        ("build", {"build_status": "planned", "notes": "x" * 10001}),
        ("steps", {"label": "  "}),
        ("steps", {"label": "x" * 241}),
        ("items/{item_id}/progress", {"completed_quantity": "-1"}),
        ("items/{item_id}/progress", {"completed_quantity": "4"}),
    ],
)
async def test_progress_validates_input(
    tmp_path: Path,
    endpoint: str,
    data: dict[str, str],
) -> None:
    settings = make_settings(tmp_path)
    async with logged_in(settings) as client:
        list_id, item_id = await new_list(client, settings)
        result = await client.post(
            f"/lists/{list_id}/" + endpoint.format(item_id=item_id),
            data={**data, "csrf": csrf(settings)},
        )
        assert result.status_code == 422


@pytest.mark.anyio
async def test_progress_csrf_and_cross_list_ids_are_rejected(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    async with logged_in(settings) as client:
        list_id, item_id = await new_list(client, settings)
        other_id, _ = await new_list(client, settings)
        await client.post(
            f"/lists/{list_id}/steps",
            data={
                "label": "Assemble",
                "csrf": csrf(settings),
            },
        )
        with connect(settings.state_db) as connection:
            step_id = connection.execute("SELECT id FROM build_steps").fetchone()[0]
        for endpoint, data in [
            ("build", {"build_status": "completed"}),
            ("steps", {"label": "Injected"}),
            (f"steps/{step_id}", {"completed": "true"}),
            (f"items/{item_id}/progress", {"completed_quantity": "1"}),
        ]:
            assert (
                await client.post(
                    f"/lists/{list_id}/{endpoint}",
                    data={
                        **data,
                        "csrf": "wrong",
                    },
                )
            ).status_code == 403
        for endpoint, data in [
            (f"steps/{step_id}", {"remove": "true"}),
            (f"items/{item_id}/progress", {"completed_quantity": "1"}),
        ]:
            assert (
                await client.post(
                    f"/lists/{other_id}/{endpoint}",
                    data={
                        **data,
                        "csrf": csrf(settings),
                    },
                )
            ).status_code == 404


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("role", "read_status", "write_status"),
    [
        ("viewer", 200, 403),
        ("editor", 200, 303),
        (None, 404, 404),
    ],
)
async def test_projects_follow_existing_sharing_permissions(
    tmp_path: Path,
    role: str | None,
    read_status: int,
    write_status: int,
) -> None:
    settings = make_settings(tmp_path)
    async with logged_in(settings) as owner:
        list_id, item_id = await new_list(owner, settings)
        await owner.post(
            f"/lists/{list_id}/steps",
            data={
                "label": "Print",
                "csrf": csrf(settings),
            },
        )
    with connect(settings.state_db) as connection, connection:
        connection.execute(
            "INSERT INTO users VALUES (?, 'member', ?, 0, 1, ?)",
            (
                "member",
                PASSWORDS.hash("member secure password"),
                now().isoformat(),
            ),
        )
        if role:
            connection.execute("INSERT INTO list_acl VALUES (?, 'member', ?)", (list_id, role))
        step_id = connection.execute("SELECT id FROM build_steps").fetchone()[0]
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(settings)), base_url="http://test"
    ) as member:
        await member.post(
            "/login", data={"username": "member", "password": "member secure password"}
        )
        token = csrf(settings, "member")
        page = await member.get(f"/lists/{list_id}")
        assert page.status_code == read_status
        assert (await member.get(f"/lists/{list_id}/export?format=zip")).status_code == read_status
        if role == "viewer":
            assert "Save build" not in page.text and "Save progress" not in page.text
        for endpoint, data in [
            ("build", {"build_status": "paused"}),
            ("steps", {"label": "Test print"}),
            (f"steps/{step_id}", {"completed": "true"}),
            (f"items/{item_id}/progress", {"completed_quantity": "1"}),
        ]:
            assert (
                await member.post(
                    f"/lists/{list_id}/{endpoint}",
                    data={
                        **data,
                        "csrf": token,
                    },
                )
            ).status_code == write_status


@pytest.mark.anyio
async def test_project_zip_preserves_data_hashes_rights_and_duplicate_filenames(
    tmp_path: Path,
) -> None:
    settings = make_settings(tmp_path)
    add_asset(settings, "first-model", b"first model")
    add_asset(settings, "second-model", b"second model")
    catalog_hash = hashlib.sha256(settings.catalog_db.read_bytes()).hexdigest()
    async with logged_in(settings) as client:
        list_id, item_id = await new_list(client, settings)
        await client.post(
            f"/lists/{list_id}/items",
            data={
                "product_id": "ia005-power-board",
                "quantity": "2",
                "csrf": csrf(settings),
            },
        )
        await client.post(
            f"/lists/{list_id}/items/{item_id}/progress",
            data={
                "completed_quantity": "1",
                "csrf": csrf(settings),
            },
        )
        regular_json = (await client.get(f"/lists/{list_id}/export?format=json")).json()
        regular_csv = (await client.get(f"/lists/{list_id}/export?format=csv")).text
        response = await client.get(f"/lists/{list_id}/export?format=zip")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    assert response.headers["cache-control"] == "private, no-store"
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        assert archive.testzip() is None
        assert json.loads(archive.read("parts-list.json")) == regular_json
        assert archive.read("parts-list.csv").decode() == regular_csv
        progress = json.loads(archive.read("build-progress.json"))
        assert (
            next(row for row in progress["items"] if row["id"] == item_id)["completed_quantity"]
            == 1
        )
        manifest = json.loads(archive.read("manifest.json"))
        assert manifest["region"] == "us" and manifest["catalog_schema"] == 5
        included = [row for row in manifest["assets"] if row["status"] == "included"]
        assert len(included) == 2
        assert len({row["package_path"].casefold() for row in included}) == 2
        for asset in included:
            content = archive.read(asset["package_path"])
            assert hashlib.sha256(content).hexdigest() == asset["sha256"]
            assert asset["rights_status"] == "unknown"
            assert asset["source_url"] == "https://example.com/part.stl"
            assert asset["original_filename"] == "part.stl"
        for metadata in manifest["metadata_files"]:
            assert hashlib.sha256(archive.read(metadata["path"])).hexdigest() == metadata["sha256"]
        assert any(row["status"] == "unavailable" for row in manifest["assets"])
        assert any(row["status"] == "excluded" for row in manifest["assets"])
        product = json.loads(archive.read(manifest["products"][0]["metadata_path"]))
        assert {offer["region"] for offer in product["offers"]} == {"us", "eu"}
        assert all("blob_path" not in row for row in product["assets"])
    assert hashlib.sha256(settings.catalog_db.read_bytes()).hexdigest() == catalog_hash


@pytest.mark.anyio
async def test_project_zip_includes_images_only_when_requested(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    with sqlite3.connect(settings.catalog_db) as connection:
        for asset_id, blob_path in connection.execute(
            "SELECT id, blob_path FROM assets WHERE kind='image'"
        ).fetchall():
            content = (settings.root / blob_path).read_bytes()
            connection.execute(
                "UPDATE assets SET sha256=?, size=? WHERE id=?",
                (
                    hashlib.sha256(content).hexdigest(),
                    len(content),
                    asset_id,
                ),
            )
    async with logged_in(settings) as client:
        list_id, _ = await new_list(client, settings)
        result = await client.get(f"/lists/{list_id}/export?format=zip&include_images=true")
    assert result.status_code == 200
    with zipfile.ZipFile(io.BytesIO(result.content)) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        assert sum(row["status"] == "included" for row in manifest["assets"]) == 4


@pytest.mark.anyio
async def test_project_zip_rejects_corruption_and_records_missing_or_escaping_files(
    tmp_path: Path,
) -> None:
    settings = make_settings(tmp_path)
    add_asset(settings, "model", b"original", filename="../../unsafe\\name.stl")
    async with logged_in(settings) as client:
        list_id, _ = await new_list(client, settings)
        path = settings.root / "assets/models/model.stl"
        path.write_bytes(b"tampered")
        assert (await client.get(f"/lists/{list_id}/export?format=zip")).status_code == 409
        path.write_bytes(b"original")
        good = await client.get(f"/lists/{list_id}/export?format=zip")
        with zipfile.ZipFile(io.BytesIO(good.content)) as archive:
            for name in archive.namelist():
                assert not PurePosixPath(name).is_absolute()
                assert ".." not in PurePosixPath(name).parts and "\\" not in name
        path.unlink()
        with zipfile.ZipFile(
            io.BytesIO((await client.get(f"/lists/{list_id}/export?format=zip")).content)
        ) as archive:
            manifest = json.loads(archive.read("manifest.json"))
            assert (
                next(row for row in manifest["assets"] if row["asset_id"] == "model")["status"]
                == "unavailable"
            )
        outside = tmp_path.parent / f"secret-{uuid4()}"
        outside.write_bytes(b"must never export")
        try:
            path.symlink_to(outside)
            response = await client.get(f"/lists/{list_id}/export?format=zip")
            with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
                assert all(b"must never export" not in archive.read(n) for n in archive.namelist())
        finally:
            outside.unlink()


@pytest.mark.anyio
async def test_empty_project_zip_and_authentication(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    async with logged_in(settings) as client:
        result = await client.post(
            "/lists",
            data={
                "name": "Empty project",
                "region": "eu",
                "csrf": csrf(settings),
            },
        )
        url = result.headers["location"] + "/export?format=zip"
        exported = await client.get(url)
    with zipfile.ZipFile(io.BytesIO(exported.content)) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        assert manifest["assets"] == [] and manifest["region"] == "eu"
        assert json.loads(archive.read("parts-list.json"))["items"] == []
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(settings)), base_url="http://test"
    ) as anonymous:
        assert (await anonymous.get(url)).status_code == 303


@pytest.mark.anyio
async def test_project_features_in_login_free_desktop_mode(tmp_path: Path) -> None:
    settings = replace(make_settings(tmp_path), local_mode=True)
    app = create_app(settings)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client,
    ):
        token = token_hash("local-csrf", settings.secret_key)
        result = await client.post(
            "/lists",
            data={
                "name": "Local project",
                "region": "eu",
                "csrf": token,
            },
        )
        url = result.headers["location"]
        assert (
            await client.post(
                url + "/build",
                data={
                    "build_status": "completed",
                    "notes": "Local build done",
                    "csrf": token,
                },
            )
        ).status_code == 303
        package = await client.get(url + "/export?format=zip")
        assert package.status_code == 200
        with zipfile.ZipFile(io.BytesIO(package.content)) as archive:
            assert json.loads(archive.read("parts-list.json"))["build"]["status"] == "completed"
    restarted = create_app(settings)
    async with (
        restarted.router.lifespan_context(restarted),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=restarted), base_url="http://test"
        ) as client,
    ):
        assert "Local build done" in (await client.get(url)).text
