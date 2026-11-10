import sqlite3
from pathlib import Path
from urllib.parse import unquote
from uuid import uuid4

import httpx
import pytest
from makers_supply_web.app import create_app
from makers_supply_web.config import Settings
from makers_supply_web.parts import current_price, list_view
from makers_supply_web.security import PASSWORDS, now
from makers_supply_web.state import connect
from test_catalog import authenticated_client, make_settings


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def csrf(settings: Settings) -> str:
    with connect(settings.state_db) as connection:
        return str(connection.execute("SELECT csrf_token FROM sessions").fetchone()[0])


@pytest.mark.anyio
async def test_unlisted_variants_and_unavailable_lines_are_not_totaled(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    client = await authenticated_client(settings)
    try:
        result = await client.post(
            "/lists",
            data={"name": "Unavailable", "region": "us", "csrf": csrf(settings)},
            follow_redirects=False,
        )
        list_id = result.headers["location"].split("/")[-1]
        await client.post(
            f"/lists/{list_id}/items",
            data={"product_id": "ia005-power-board", "quantity": "2", "csrf": csrf(settings)},
        )
        with sqlite3.connect(settings.catalog_db) as connection:
            connection.execute("UPDATE offers SET available=0")
        with connect(settings.state_db) as connection:
            owner = connection.execute(
                "SELECT owner_id FROM lists WHERE id=?", (list_id,)
            ).fetchone()[0]
        view = list_view(settings.state_db, settings.catalog_db, list_id, owner)
        assert view is not None
        assert view["current_totals"] == {}
        assert view["unavailable_count"] == 1
        assert view["unknown_count"] == 0
        with sqlite3.connect(settings.catalog_db) as connection:
            connection.execute("UPDATE offers SET listed=0")
            connection.execute("UPDATE variants SET available=1, price='100.00', currency='USD'")
            variant = connection.execute("SELECT variant_id FROM variants LIMIT 1").fetchone()
        assert current_price(
            settings.catalog_db, "ia005-power-board", "us", None if variant is None else variant[0]
        ) == (None, None, False)
    finally:
        await client.aclose()


@pytest.mark.anyio
@pytest.mark.parametrize("name", ["Parts", "Žluťoučký 🔩", 'A "quoted" list', "A\r\nInjected: yes"])
@pytest.mark.parametrize("format", ["csv", "json"])
async def test_export_download_filenames(tmp_path: Path, name: str, format: str) -> None:
    settings = make_settings(tmp_path)
    client = await authenticated_client(settings)
    try:
        response = await client.post(
            "/lists",
            data={"name": name, "region": "us", "csrf": csrf(settings)},
            follow_redirects=False,
        )
        exported = await client.get(response.headers["location"] + f"/export?format={format}")
    finally:
        await client.aclose()
    assert exported.status_code == 200
    disposition = exported.headers["content-disposition"]
    assert disposition.isascii()
    assert "\r" not in disposition and "\n" not in disposition
    assert "filename*=UTF-8''" in disposition
    decoded = unquote(disposition.split("filename*=UTF-8''")[1])
    assert "\r" not in decoded and "\n" not in decoded
    assert decoded.endswith(f".{format}")
    if "\r" not in name:
        assert decoded == f"{name}.{format}"


@pytest.mark.anyio
async def test_list_totals_snapshot_changes_exports_and_csrf(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    client = await authenticated_client(settings)
    try:
        create = await client.post(
            "/lists",
            data={"name": "Robot BOM", "region": "us", "csrf": csrf(settings)},
            follow_redirects=False,
        )
        list_id = create.headers["location"].rsplit("/", 1)[-1]
        invalid = await client.post(
            f"/lists/{list_id}/items",
            data={"product_id": "ia005-power-board", "quantity": "1", "csrf": "wrong"},
        )
        add = await client.post(
            f"/lists/{list_id}/items",
            data={"product_id": "ia005-power-board", "quantity": "2", "csrf": csrf(settings)},
            follow_redirects=False,
        )
        first = await client.get(f"/lists/{list_id}")
        with sqlite3.connect(settings.catalog_db) as catalog:
            catalog.execute(
                """UPDATE offers SET price='6.29'
                   WHERE product_id='ia005-power-board' AND region='us'"""
            )
        changed = await client.get(f"/lists/{list_id}")
        exported = await client.get(f"/lists/{list_id}/export?format=csv")
    finally:
        await client.aclose()
    assert create.status_code == 303
    assert invalid.status_code == 403
    assert add.status_code == 303
    assert "10.58 USD" in first.text
    assert "12.58 USD" in changed.text
    assert "Price changed from 5.29 USD" in changed.text
    assert "product_id,name,variant_id,quantity" in exported.text


@pytest.mark.anyio
async def test_catalog_picker_populates_lists_and_bulk_adds_selection(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    client = await authenticated_client(settings)
    try:
        create = await client.post(
            "/lists",
            data={"name": "Robot BOM", "region": "us", "csrf": csrf(settings)},
            follow_redirects=False,
        )
        list_id = create.headers["location"].rsplit("/", 1)[-1]
        catalog = await client.get(f"/?region=us&list_id={list_id}")
        added = await client.post(
            "/selection/add",
            data={
                "product_ids": ["ia005-power-board", "ia005-power-board"],
                "list_id": list_id,
                "quantity": "2",
                "csrf": csrf(settings),
            },
            follow_redirects=False,
        )
        detail = await client.get(f"/lists/{list_id}")
    finally:
        await client.aclose()

    assert catalog.status_code == 200
    assert 'data-product-select data-product-name="Power Distribution Board"' in catalog.text
    assert f'<option value="{list_id}" data-region="us" selected>' in catalog.text
    assert f'name="list_id" value="{list_id}"' in catalog.text
    assert added.status_code == 303
    assert added.headers["location"] == f"/lists/{list_id}?selection_added=1"
    assert 'name="quantity" min="1" max="100000" value="2"' in detail.text
    assert "/assets/ia005-power-board/normalized-image" in detail.text
    assert "Add by product ID" not in detail.text
    assert f'href="/region?region=us&amp;next=/?list_id={list_id}"' in detail.text


@pytest.mark.anyio
async def test_catalog_picker_can_create_a_list_with_selected_products(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    client = await authenticated_client(settings)
    try:
        response = await client.post(
            "/selection/add",
            data={
                "product_ids": "ia005-power-board",
                "list_id": "__new__",
                "list_name": "Quick picker list",
                "region": "us",
                "quantity": "3",
                "csrf": csrf(settings),
            },
            follow_redirects=False,
        )
        list_id = response.headers["location"].split("?", 1)[0].rsplit("/", 1)[-1]
        with connect(settings.state_db) as connection:
            selected_list = connection.execute(
                "SELECT name, region FROM lists WHERE id=?", (list_id,)
            ).fetchone()
            item = connection.execute(
                "SELECT product_id, quantity, captured_price FROM list_items WHERE list_id=?",
                (list_id,),
            ).fetchone()
    finally:
        await client.aclose()

    assert response.status_code == 303
    assert dict(selected_list) == {"name": "Quick picker list", "region": "us"}
    assert dict(item) == {
        "product_id": "ia005-power-board",
        "quantity": 3,
        "captured_price": "5.29",
    }


@pytest.mark.anyio
async def test_viewer_can_read_but_not_edit_shared_list(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    with connect(settings.state_db) as connection, connection:
        connection.execute(
            "INSERT INTO users VALUES (?, 'viewer', ?, 0, 1, ?)",
            (str(uuid4()), PASSWORDS.hash("viewer secure password"), now().isoformat()),
        )
    admin = await authenticated_client(settings)
    create = await admin.post(
        "/lists",
        data={"name": "Shared", "region": "us", "csrf": csrf(settings)},
        follow_redirects=False,
    )
    list_id = create.headers["location"].rsplit("/", 1)[-1]
    shared = await admin.post(
        f"/lists/{list_id}/share",
        data={"username": "viewer", "role": "viewer", "csrf": csrf(settings)},
        follow_redirects=False,
    )
    await admin.aclose()
    viewer = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(settings)), base_url="http://test"
    )
    await viewer.post(
        "/login",
        data={"username": "viewer", "password": "viewer secure password"},
        follow_redirects=False,
    )
    with connect(settings.state_db) as connection:
        viewer_csrf = str(
            connection.execute(
                """SELECT s.csrf_token FROM sessions s JOIN users u ON u.id=s.user_id
               WHERE u.username='viewer'"""
            ).fetchone()[0]
        )
    readable = await viewer.get(f"/lists/{list_id}")
    forbidden = await viewer.post(
        f"/lists/{list_id}/items",
        data={"product_id": "ia005-power-board", "quantity": "1", "csrf": viewer_csrf},
    )
    forbidden_bulk = await viewer.post(
        "/selection/add",
        data={
            "product_ids": "ia005-power-board",
            "list_id": list_id,
            "quantity": "1",
            "csrf": viewer_csrf,
        },
    )
    await viewer.aclose()
    assert shared.status_code == 303
    assert readable.status_code == 200
    assert forbidden.status_code == 403
    assert forbidden_bulk.status_code == 403


def test_mismatched_regional_currency_is_not_totaled(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    with sqlite3.connect(settings.catalog_db) as catalog:
        catalog.execute(
            "UPDATE offers SET currency='EUR' WHERE product_id='ia005-power-board' AND region='us'"
        )
    price, currency, available = current_price(settings.catalog_db, "ia005-power-board", "us", None)
    assert price is None
    assert currency == "EUR"
    assert available is None
