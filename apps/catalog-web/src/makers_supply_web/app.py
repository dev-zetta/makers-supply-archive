from __future__ import annotations

import secrets
import sqlite3
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Annotated, Any, cast
from urllib.parse import quote, urlencode
from uuid import uuid4

from fastapi import Depends, FastAPI, Form, HTTPException, Query, Request, status
from fastapi.responses import (
    HTMLResponse,
    JSONResponse,
    RedirectResponse,
    Response,
    StreamingResponse,
)
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from makers_supply_web.catalog import (
    SearchFilters,
    asset_record,
    catalog_version,
    categories,
    decimal_filter,
    existing_product_ids,
    product_detail,
    search_products,
)
from makers_supply_web.config import Settings
from makers_supply_web.parts import (
    accessible_lists,
    current_price,
    export_list,
    list_access,
    list_view,
)
from makers_supply_web.security import (
    PASSWORDS,
    REMEMBERED_SESSION_LIFETIME,
    SESSION_COOKIE,
    SESSION_LIFETIME,
    now,
    token,
    token_hash,
    verify_password,
)
from makers_supply_web.state import connect, migrate

PACKAGE = Path(__file__).parent
REGION_COOKIE = "makers_supply_region"
REGION_OPTIONS = (
    ("global", "All / Global"),
    ("us", "USA"),
    ("eu", "EU"),
    ("uk", "UK"),
    ("ca", "Canada"),
    ("au", "Australia"),
    ("jp", "Japan"),
    ("kr", "Korea"),
    ("asia", "Asia"),
)
REGION_LABELS = dict(REGION_OPTIONS)
LOCAL_USER_ID = "local-user"


def selected_region(request: Request, explicit: str | None = None) -> str:
    candidate = explicit or request.cookies.get(REGION_COOKIE, "us")
    return candidate if candidate in REGION_LABELS else "us"


def region_template_context(request: Request) -> dict[str, object]:
    region = selected_region(request, request.query_params.get("region"))
    return_query = [
        (key, value)
        for key, value in request.query_params.multi_items()
        if key not in {"region", "page"}
    ]
    return_url = request.url.path
    if return_query:
        return_url = f"{return_url}?{urlencode(return_query)}"
    return {
        "global_region": region,
        "global_region_label": REGION_LABELS[region],
        "global_region_options": REGION_OPTIONS,
        "global_region_return_url": return_url,
    }


templates = Jinja2Templates(
    directory=PACKAGE / "templates", context_processors=[region_template_context]
)


def human_datetime(value: object) -> str:
    """Return an ISO timestamp as a readable UTC fallback for server-rendered pages."""
    if value in (None, ""):
        return "Not published"
    raw = str(value)
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return raw
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    parsed = parsed.astimezone(UTC)
    clock = parsed.strftime("%I:%M %p").lstrip("0")
    return f"{parsed.strftime('%b')} {parsed.day}, {parsed.year} at {clock} UTC"


templates.env.filters["human_datetime"] = human_datetime


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_environment()

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        migrate(settings.state_db)
        if settings.local_mode:
            with connect(settings.state_db) as connection, connection:
                connection.execute(
                    """INSERT OR IGNORE INTO users
                       VALUES (?, 'Local user', 'login-disabled', 1, 1, ?)""",
                    (LOCAL_USER_ID, now().isoformat()),
                )
        yield

    app = FastAPI(title="Maker's Supply Catalog", lifespan=lifespan)
    app.state.settings = settings
    app.mount("/static", StaticFiles(directory=PACKAGE / "static"), name="static")

    @app.middleware("http")
    async def security_headers(request: Request, call_next: Any) -> Any:
        response = await call_next(request)
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; img-src 'self' data:; style-src 'self'; "
            "script-src 'self'; connect-src 'self'; object-src 'none'; "
            "base-uri 'self'; frame-ancestors 'none'"
        )
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        if settings.secure_cookies:
            response.headers["Strict-Transport-Security"] = "max-age=31536000"
        return response

    async def current_user(request: Request) -> sqlite3.Row | dict[str, object] | None:
        if settings.local_mode:
            return {
                "id": LOCAL_USER_ID,
                "username": "Local user",
                "is_admin": 1,
                "active": 1,
                "csrf_token": token_hash("local-csrf", settings.secret_key),
            }
        raw = request.cookies.get(SESSION_COOKIE)
        if not raw:
            return None
        with connect(settings.state_db) as connection:
            return cast(
                sqlite3.Row | None,
                connection.execute(
                    """SELECT users.*, sessions.csrf_token
                   FROM sessions JOIN users ON users.id = sessions.user_id
                   WHERE sessions.token_hash = ? AND sessions.expires_at > ?
                   AND users.active = 1""",
                    (token_hash(raw, settings.secret_key), now().isoformat()),
                ).fetchone(),
            )

    async def require_user(request: Request) -> sqlite3.Row | dict[str, object]:
        user = await current_user(request)
        if user is None:
            raise HTTPException(status.HTTP_303_SEE_OTHER, headers={"Location": "/login"})
        return user

    def check_csrf(
        request: Request, supplied: str, user: sqlite3.Row | dict[str, object]
    ) -> None:
        if not secrets.compare_digest(str(user["csrf_token"]), supplied):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Invalid CSRF token")

    @app.get("/healthz")
    async def health() -> dict[str, str]:
        try:
            version = catalog_version(settings.catalog_db)
        except (FileNotFoundError, sqlite3.Error):
            raise HTTPException(503, "Catalog database is unavailable") from None
        return {"status": "ok", "catalog_schema": str(version)}

    @app.get("/region")
    async def set_region(
        region: str,
        return_to: Annotated[str, Query(alias="next")] = "/",
        user: sqlite3.Row = Depends(require_user),  # noqa: B008
    ) -> RedirectResponse:
        del user
        if region not in REGION_LABELS:
            raise HTTPException(422, "Invalid region")
        if not return_to.startswith("/") or return_to.startswith("//"):
            return_to = "/"
        response = RedirectResponse(return_to, status_code=303)
        response.set_cookie(
            REGION_COOKIE,
            region,
            httponly=True,
            secure=settings.secure_cookies,
            samesite="lax",
            max_age=365 * 24 * 60 * 60,
        )
        return response

    def browse_context(
        query: str,
        category: str,
        region: str,
        availability: str,
        asset_kind: str,
        lifecycle: str,
        minimum_price: str,
        maximum_price: str,
        view: str,
        page: int,
    ) -> tuple[list[dict[str, Any]], int, SearchFilters]:
        filters = SearchFilters(
            query=query,
            category=category,
            region=region,
            availability=availability,
            asset_kind=asset_kind,
            lifecycle=lifecycle,
            minimum_price=decimal_filter(minimum_price),
            maximum_price=decimal_filter(maximum_price),
            view=view if view in {"grid", "list", "compact"} else "grid",
            page=max(page, 1),
        )
        products, total = search_products(settings.catalog_db, filters)
        return products, total, filters

    @app.get("/", response_class=HTMLResponse)
    async def browse(
        request: Request,
        user: sqlite3.Row = Depends(require_user),  # noqa: B008
        q: str = "",
        category: str = "",
        region: str | None = None,
        availability: str = "",
        asset_kind: str = "",
        lifecycle: str = "active",
        min_price: str = "",
        max_price: str = "",
        view: str = "grid",
        page: int = 1,
        list_id: str = "",
    ) -> Any:
        region = selected_region(request, region)
        try:
            products, total, filters = browse_context(
                q, category, region, availability, asset_kind, lifecycle,
                min_price, max_price, view, page
            )
            category_items = categories(settings.catalog_db, region)
        except (FileNotFoundError, sqlite3.Error) as error:
            raise HTTPException(503, str(error)) from error
        editable_lists = [
            item
            for item in accessible_lists(
                settings.state_db, str(user["id"]), is_admin=bool(user["is_admin"])
            )
            if item["role"] != "viewer"
        ]
        target_list_id = list_id if any(
            item["id"] == list_id for item in editable_lists
        ) else ""
        query_values = {
            "q": filters.query,
            "category": filters.category,
            "region": filters.region,
            "availability": filters.availability,
            "asset_kind": filters.asset_kind,
            "lifecycle": filters.lifecycle,
            "min_price": str(filters.minimum_price or ""),
            "max_price": str(filters.maximum_price or ""),
            "view": filters.view,
            "list_id": target_list_id,
        }

        def page_url(target: int) -> str:
            return f"?{urlencode({**query_values, 'page': target})}"

        return templates.TemplateResponse(
            request,
            "catalog.html",
            {
                "user": user,
                "products": products,
                "total": total,
                "filters": filters,
                "categories": category_items,
                "editable_lists": editable_lists,
                "local_mode": settings.local_mode,
                "target_list_id": target_list_id,
                "previous_url": page_url(filters.page - 1) if filters.page > 1 else None,
                "next_url": (
                    page_url(filters.page + 1)
                    if filters.page * filters.page_size < total
                    else None
                ),
                "view_urls": {
                    mode: f"?{urlencode({**query_values, 'view': mode, 'page': 1})}"
                    for mode in ("grid", "list", "compact")
                },
            },
        )

    @app.get("/api/products")
    async def products_api(
        request: Request,
        user: sqlite3.Row = Depends(require_user),  # noqa: B008
        q: str = "",
        category: str = "",
        region: str | None = None,
        availability: str = "",
        asset_kind: str = "",
        lifecycle: str = "active",
        min_price: str = "",
        max_price: str = "",
        view: str = "grid",
        page: int = 1,
    ) -> JSONResponse:
        del user
        region = selected_region(request, region)
        products, total, filters = browse_context(
            q, category, region, availability, asset_kind, lifecycle,
            min_price, max_price, view, page
        )
        return JSONResponse({"items": products, "total": total, "page": filters.page})

    @app.get("/products/{product_id}", response_class=HTMLResponse)
    async def product_page(
        request: Request,
        product_id: str,
        region: str | None = None,
        user: sqlite3.Row = Depends(require_user),  # noqa: B008
    ) -> Any:
        region = selected_region(request, region)
        product = product_detail(settings.catalog_db, product_id, region)
        if product is None:
            raise HTTPException(404, "Product not found")
        editable_lists = [
            item for item in accessible_lists(
                settings.state_db, str(user["id"]), is_admin=bool(user["is_admin"])
            ) if item["role"] != "viewer"
        ]
        return templates.TemplateResponse(
            request, "product.html",
            {
                "user": user,
                "product": product,
                "editable_lists": editable_lists,
                "local_mode": settings.local_mode,
            },
        )

    @app.get("/assets/{product_id}/{asset_id}")
    async def asset_file(
        request: Request,
        product_id: str,
        asset_id: str,
        user: sqlite3.Row = Depends(require_user),  # noqa: B008
        download: Annotated[bool, Query()] = False,
    ) -> StreamingResponse:
        del user
        asset = asset_record(settings.catalog_db, product_id, asset_id)
        if asset is None or not asset["blob_path"] or asset["rejection_reason"]:
            raise HTTPException(404, "Asset is unavailable")
        root = settings.root.resolve()
        path = (root / str(asset["blob_path"])).resolve()
        if not path.is_relative_to(root) or not path.is_file():
            raise HTTPException(404, "Asset blob is unavailable")
        inline = asset["kind"] == "image" or (
            asset["kind"] == "model" and path.suffix.casefold() in {".stl", ".3mf"}
        )
        size = path.stat().st_size
        start, end, status_code = 0, max(size - 1, 0), 200
        requested_range = request.headers.get("range", "")
        if requested_range.startswith("bytes=") and "," not in requested_range:
            first, _, last = requested_range.removeprefix("bytes=").partition("-")
            try:
                if first:
                    start = int(first)
                    end = min(int(last), size - 1) if last else size - 1
                elif last:
                    start = max(size - int(last), 0)
                if start < 0 or start > end or start >= size:
                    raise ValueError
                status_code = 206
            except ValueError as error:
                raise HTTPException(416, "Requested range is not satisfiable") from error

        async def content() -> AsyncIterator[bytes]:
            remaining = end - start + 1
            with path.open("rb") as stream:
                stream.seek(start)
                while remaining:
                    chunk = stream.read(min(64 * 1024, remaining))
                    if not chunk:
                        break
                    remaining -= len(chunk)
                    yield chunk

        disposition = "inline" if inline and not download else "attachment"
        headers = {
            "Accept-Ranges": "bytes",
            "Content-Length": str(end - start + 1),
            "Content-Disposition": (
                disposition
                if disposition == "inline"
                else f"attachment; filename*=UTF-8''{quote(str(asset['original_filename']))}"
            ),
        }
        if status_code == 206:
            headers["Content-Range"] = f"bytes {start}-{end}/{size}"
        return StreamingResponse(
            content(),
            status_code=status_code,
            media_type=str(asset["media_type"]),
            headers=headers,
        )

    def permission(list_id: str, user: sqlite3.Row, *, owner: bool = False) -> dict[str, Any]:
        selected = list_access(
            settings.state_db, list_id, str(user["id"]), is_admin=bool(user["is_admin"])
        )
        if selected is None:
            raise HTTPException(404, "Parts list not found")
        allowed = {"owner", "admin"} if owner else {"owner", "admin", "editor"}
        if selected["role"] not in allowed:
            raise HTTPException(403, "This list is read-only")
        return selected

    @app.get("/lists", response_class=HTMLResponse)
    async def lists_page(
        request: Request, user: sqlite3.Row = Depends(require_user),  # noqa: B008
    ) -> Any:
        items = accessible_lists(
            settings.state_db, str(user["id"]), is_admin=bool(user["is_admin"])
        )
        return templates.TemplateResponse(
            request,
            "lists.html",
            {"user": user, "lists": items, "local_mode": settings.local_mode},
        )

    @app.post("/lists")
    async def create_list(
        request: Request, name: Annotated[str, Form()], region: Annotated[str, Form()],
        csrf: Annotated[str, Form()], user: sqlite3.Row = Depends(require_user),  # noqa: B008
    ) -> RedirectResponse:
        check_csrf(request, csrf, user)
        if region not in {"us", "eu", "uk", "ca", "au", "jp", "kr", "asia"}:
            raise HTTPException(422, "Invalid region")
        if not name.strip() or len(name.strip()) > 120:
            raise HTTPException(422, "List name must contain 1–120 characters")
        list_id, timestamp = str(uuid4()), now().isoformat()
        with connect(settings.state_db) as connection, connection:
            connection.execute(
                "INSERT INTO lists VALUES (?, ?, ?, ?, ?, ?)",
                (list_id, user["id"], name.strip(), region, timestamp, timestamp),
            )
        return RedirectResponse(f"/lists/{list_id}", status_code=303)

    @app.get("/lists/{list_id}", response_class=HTMLResponse)
    async def list_page(
        request: Request, list_id: str,
        user: sqlite3.Row = Depends(require_user),  # noqa: B008
    ) -> Any:
        selected = list_view(
            settings.state_db, settings.catalog_db, list_id, str(user["id"]),
            is_admin=bool(user["is_admin"]),
        )
        if selected is None:
            raise HTTPException(404, "Parts list not found")
        return templates.TemplateResponse(
            request,
            "list.html",
            {
                "user": user,
                "list": selected,
                "local_mode": settings.local_mode,
                "selection_added": request.query_params.get("selection_added") == "1",
            },
        )

    @app.post("/selection/add")
    async def add_selection(
        request: Request,
        product_ids: Annotated[list[str], Form()],
        csrf: Annotated[str, Form()],
        quantity: Annotated[int, Form()] = 1,
        list_id: Annotated[str, Form()] = "",
        list_name: Annotated[str, Form()] = "",
        region: Annotated[str, Form()] = "us",
        user: sqlite3.Row = Depends(require_user),  # noqa: B008
    ) -> RedirectResponse:
        """Add catalog selections to an editable list, creating it when requested."""
        check_csrf(request, csrf, user)
        if quantity < 1 or quantity > 100000:
            raise HTTPException(422, "Quantity must be between 1 and 100000")
        normalized_ids = list(
            dict.fromkeys(
                product_id.strip() for product_id in product_ids if product_id.strip()
            )
        )
        if not normalized_ids:
            raise HTTPException(422, "Select at least one product")
        if len(normalized_ids) > 250:
            raise HTTPException(422, "Select no more than 250 products at once")
        known_ids = existing_product_ids(settings.catalog_db, normalized_ids)
        missing = [product_id for product_id in normalized_ids if product_id not in known_ids]
        if missing:
            raise HTTPException(404, f"Product not found: {missing[0]}")

        create_new = not list_id or list_id == "__new__"
        if create_new:
            if region not in {"us", "eu", "uk", "ca", "au", "jp", "kr", "asia"}:
                raise HTTPException(422, "Invalid region")
            normalized_name = list_name.strip()
            if not normalized_name or len(normalized_name) > 120:
                raise HTTPException(422, "List name must contain 1–120 characters")
            destination_id = str(uuid4())
            destination_region = region
        else:
            selected = permission(list_id, user)
            destination_id = list_id
            destination_region = str(selected["region"])

        prices = {
            product_id: current_price(
                settings.catalog_db, product_id, destination_region, None
            )[:2]
            for product_id in normalized_ids
        }
        timestamp = now().isoformat()
        with connect(settings.state_db) as connection, connection:
            if create_new:
                connection.execute(
                    "INSERT INTO lists VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        destination_id,
                        user["id"],
                        normalized_name,
                        destination_region,
                        timestamp,
                        timestamp,
                    ),
                )
            for product_id in normalized_ids:
                price, currency = prices[product_id]
                existing = connection.execute(
                    """SELECT id, quantity FROM list_items WHERE list_id=? AND product_id=?
                       AND variant_id IS NULL""",
                    (destination_id, product_id),
                ).fetchone()
                if existing:
                    connection.execute(
                        """UPDATE list_items SET quantity=?, captured_price=?,
                           captured_currency=?, captured_at=?, updated_at=? WHERE id=?""",
                        (
                            int(existing["quantity"]) + quantity,
                            price,
                            currency,
                            timestamp if price else None,
                            timestamp,
                            existing["id"],
                        ),
                    )
                else:
                    connection.execute(
                        "INSERT INTO list_items VALUES (?, ?, ?, NULL, ?, '', ?, ?, ?, ?, ?)",
                        (
                            str(uuid4()),
                            destination_id,
                            product_id,
                            quantity,
                            price,
                            currency,
                            timestamp if price else None,
                            timestamp,
                            timestamp,
                        ),
                    )
            connection.execute(
                "UPDATE lists SET updated_at=? WHERE id=?", (timestamp, destination_id)
            )
        return RedirectResponse(
            f"/lists/{destination_id}?selection_added=1", status_code=303
        )

    @app.post("/lists/{list_id}/items")
    async def add_list_item(
        request: Request, list_id: str, product_id: Annotated[str, Form()],
        csrf: Annotated[str, Form()], quantity: Annotated[int, Form()] = 1,
        variant_id: Annotated[str, Form()] = "", notes: Annotated[str, Form()] = "",
        user: sqlite3.Row = Depends(require_user),  # noqa: B008
    ) -> RedirectResponse:
        check_csrf(request, csrf, user)
        selected = permission(list_id, user)
        if quantity < 1 or quantity > 100000:
            raise HTTPException(422, "Quantity must be between 1 and 100000")
        product = product_detail(settings.catalog_db, product_id, str(selected["region"]))
        if product is None:
            raise HTTPException(404, "Product not found")
        normalized_variant = variant_id or None
        if normalized_variant and not any(
            item["variant_id"] == normalized_variant and item["region"] == selected["region"]
            for item in product["variants"]
        ):
            raise HTTPException(422, "Variant is not available in the list region")
        price, currency, _ = current_price(
            settings.catalog_db, product_id, str(selected["region"]), normalized_variant
        )
        timestamp = now().isoformat()
        with connect(settings.state_db) as connection, connection:
            existing = connection.execute(
                """SELECT id, quantity FROM list_items WHERE list_id=? AND product_id=?
                   AND variant_id IS ?""",
                (list_id, product_id, normalized_variant),
            ).fetchone()
            if existing:
                connection.execute(
                    """UPDATE list_items SET quantity=?, notes=?, captured_price=?,
                       captured_currency=?, captured_at=?, updated_at=? WHERE id=?""",
                    (int(existing["quantity"]) + quantity, notes, price, currency,
                     timestamp if price else None, timestamp, existing["id"]),
                )
            else:
                connection.execute(
                    "INSERT INTO list_items VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (str(uuid4()), list_id, product_id, normalized_variant, quantity, notes,
                     price, currency, timestamp if price else None, timestamp, timestamp),
                )
            connection.execute(
                "UPDATE lists SET updated_at=? WHERE id=?", (timestamp, list_id)
            )
        return RedirectResponse(f"/lists/{list_id}", status_code=303)

    @app.post("/lists/{list_id}/items/{item_id}")
    async def update_list_item(
        request: Request, list_id: str, item_id: str, csrf: Annotated[str, Form()],
        quantity: Annotated[int, Form()], notes: Annotated[str, Form()] = "",
        remove: Annotated[bool, Form()] = False,
        user: sqlite3.Row = Depends(require_user),  # noqa: B008
    ) -> RedirectResponse:
        check_csrf(request, csrf, user)
        permission(list_id, user)
        if not remove and (quantity < 1 or quantity > 100000):
            raise HTTPException(422, "Quantity must be between 1 and 100000")
        with connect(settings.state_db) as connection, connection:
            if remove:
                cursor = connection.execute(
                    "DELETE FROM list_items WHERE id=? AND list_id=?", (item_id, list_id)
                )
            else:
                cursor = connection.execute(
                    """UPDATE list_items SET quantity=?, notes=?, updated_at=?
                       WHERE id=? AND list_id=?""",
                    (quantity, notes, now().isoformat(), item_id, list_id),
                )
            if cursor.rowcount != 1:
                raise HTTPException(404, "List item not found")
            connection.execute(
                "UPDATE lists SET updated_at=? WHERE id=?", (now().isoformat(), list_id)
            )
        return RedirectResponse(f"/lists/{list_id}", status_code=303)

    @app.post("/lists/{list_id}/refresh-prices")
    async def refresh_prices(
        request: Request, list_id: str, csrf: Annotated[str, Form()],
        user: sqlite3.Row = Depends(require_user),  # noqa: B008
    ) -> RedirectResponse:
        check_csrf(request, csrf, user)
        selected = permission(list_id, user)
        with connect(settings.state_db) as connection:
            items = connection.execute(
                "SELECT * FROM list_items WHERE list_id=?", (list_id,)
            ).fetchall()
            with connection:
                for item in items:
                    price, currency, _ = current_price(
                        settings.catalog_db, item["product_id"], selected["region"],
                        item["variant_id"],
                    )
                    connection.execute(
                        """UPDATE list_items SET captured_price=?, captured_currency=?,
                           captured_at=?, updated_at=? WHERE id=?""",
                        (price, currency, now().isoformat() if price else None,
                         now().isoformat(), item["id"]),
                    )
        return RedirectResponse(f"/lists/{list_id}", status_code=303)

    @app.post("/lists/{list_id}/share")
    async def share_list(
        request: Request, list_id: str, username: Annotated[str, Form()],
        role: Annotated[str, Form()], csrf: Annotated[str, Form()],
        user: sqlite3.Row = Depends(require_user),  # noqa: B008
    ) -> RedirectResponse:
        check_csrf(request, csrf, user)
        permission(list_id, user, owner=True)
        if role not in {"viewer", "editor", "remove"}:
            raise HTTPException(422, "Invalid sharing role")
        with connect(settings.state_db) as connection, connection:
            target = connection.execute(
                "SELECT id FROM users WHERE username=? COLLATE NOCASE AND active=1", (username,)
            ).fetchone()
            if target is None:
                raise HTTPException(404, "User not found")
            if role == "remove":
                connection.execute(
                    "DELETE FROM list_acl WHERE list_id=? AND user_id=?", (list_id, target["id"])
                )
            else:
                connection.execute(
                    """INSERT INTO list_acl VALUES (?, ?, ?)
                       ON CONFLICT(list_id,user_id) DO UPDATE SET role=excluded.role""",
                    (list_id, target["id"], role),
                )
        return RedirectResponse(f"/lists/{list_id}", status_code=303)

    @app.get("/lists/{list_id}/export")
    async def export_parts_list(
        list_id: str, format: str = "csv",  # noqa: A002
        user: sqlite3.Row = Depends(require_user),  # noqa: B008
    ) -> Response:
        selected = list_view(
            settings.state_db, settings.catalog_db, list_id, str(user["id"]),
            is_admin=bool(user["is_admin"]),
        )
        if selected is None:
            raise HTTPException(404, "Parts list not found")
        try:
            content, media_type = export_list(selected, format)
        except ValueError as error:
            raise HTTPException(422, str(error)) from error
        filename = f"{selected['name']}.{format}".replace('"', "")
        return Response(
            content, media_type=media_type,
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    @app.get("/login", response_class=HTMLResponse)
    async def login_page(request: Request) -> Any:
        if settings.local_mode:
            return RedirectResponse("/", status_code=303)
        return templates.TemplateResponse(request, "login.html", {"error": None})

    @app.post("/login")
    async def login(
        request: Request,
        username: Annotated[str, Form()],
        password: Annotated[str, Form()],
        remember_me: Annotated[bool, Form()] = False,
    ) -> Any:
        if settings.local_mode:
            raise HTTPException(404, "Login is disabled in the local app")
        identity = f"{request.client.host if request.client else 'unknown'}:{username.casefold()}"
        with connect(settings.state_db) as connection:
            attempt = connection.execute(
                "SELECT * FROM login_attempts WHERE identity = ?", (identity,)
            ).fetchone()
            is_blocked = (
                attempt
                and attempt["blocked_until"]
                and attempt["blocked_until"] > now().isoformat()
            )
            if is_blocked:
                return templates.TemplateResponse(
                    request,
                    "login.html",
                    {"error": "Too many attempts; try again later."},
                    status_code=429,
                )
            user = connection.execute(
                "SELECT * FROM users WHERE username = ? COLLATE NOCASE AND active = 1", (username,)
            ).fetchone()
            if user is None or not verify_password(str(user["password_hash"]), password):
                failures = int(attempt["failures"]) + 1 if attempt else 1
                blocked = (now() + timedelta(minutes=15)).isoformat() if failures >= 5 else None
                with connection:
                    connection.execute(
                        """INSERT INTO login_attempts VALUES (?, ?, ?, ?)
                           ON CONFLICT(identity) DO UPDATE SET failures=excluded.failures,
                           blocked_until=excluded.blocked_until""",
                        (identity, failures, now().isoformat(), blocked),
                    )
                return templates.TemplateResponse(
                    request,
                    "login.html",
                    {"error": "Invalid username or password."},
                    status_code=401,
                )
            raw, csrf = token(), token()
            session_lifetime = (
                REMEMBERED_SESSION_LIFETIME if remember_me else SESSION_LIFETIME
            )
            with connection:
                connection.execute("DELETE FROM login_attempts WHERE identity = ?", (identity,))
                connection.execute(
                    "INSERT INTO sessions VALUES (?, ?, ?, ?, ?)",
                    (
                        token_hash(raw, settings.secret_key),
                        user["id"],
                        csrf,
                        (now() + session_lifetime).isoformat(),
                        now().isoformat(),
                    ),
                )
        response = RedirectResponse("/", status_code=303)
        response.set_cookie(
            SESSION_COOKIE,
            raw,
            httponly=True,
            secure=settings.secure_cookies,
            samesite="lax",
            max_age=(int(session_lifetime.total_seconds()) if remember_me else None),
        )
        return response

    @app.post("/logout")
    async def logout(
        request: Request,
        csrf: Annotated[str, Form()],
        user: sqlite3.Row = Depends(require_user),  # noqa: B008
    ) -> Any:
        if settings.local_mode:
            return RedirectResponse("/", status_code=303)
        check_csrf(request, csrf, user)
        raw = request.cookies.get(SESSION_COOKIE, "")
        with connect(settings.state_db) as connection, connection:
            connection.execute(
                "DELETE FROM sessions WHERE token_hash = ?", (token_hash(raw, settings.secret_key),)
            )
        response = RedirectResponse("/login", status_code=303)
        response.delete_cookie(SESSION_COOKIE)
        return response

    @app.get("/invite/{raw_token}", response_class=HTMLResponse)
    async def invite_page(request: Request, raw_token: str) -> Any:
        if settings.local_mode:
            raise HTTPException(404, "Invitations are disabled in the local app")
        with connect(settings.state_db) as connection:
            invite = connection.execute(
                "SELECT * FROM invites WHERE token_hash = ? AND used_at IS NULL AND expires_at > ?",
                (token_hash(raw_token, settings.secret_key), now().isoformat()),
            ).fetchone()
        if invite is None:
            raise HTTPException(404, "Invitation is invalid or expired")
        return templates.TemplateResponse(
            request, "invite.html", {"token": raw_token, "error": None}
        )

    @app.post("/invite/{raw_token}")
    async def accept_invite(
        request: Request,
        raw_token: str,
        username: Annotated[str, Form()],
        password: Annotated[str, Form()],
    ) -> Any:
        if settings.local_mode:
            raise HTTPException(404, "Invitations are disabled in the local app")
        if len(username.strip()) < 3 or len(password) < 12:
            return templates.TemplateResponse(
                request,
                "invite.html",
                {
                    "token": raw_token,
                    "error": "Use a 3+ character name and 12+ character password.",
                },
                status_code=422,
            )
        hashed = token_hash(raw_token, settings.secret_key)
        with connect(settings.state_db) as connection, connection:
            invite = connection.execute(
                "SELECT * FROM invites WHERE token_hash = ? AND used_at IS NULL AND expires_at > ?",
                (hashed, now().isoformat()),
            ).fetchone()
            if invite is None:
                raise HTTPException(404, "Invitation is invalid or expired")
            user_id = str(uuid4())
            try:
                connection.execute(
                    "INSERT INTO users VALUES (?, ?, ?, 0, 1, ?)",
                    (user_id, username.strip(), PASSWORDS.hash(password), now().isoformat()),
                )
            except sqlite3.IntegrityError as error:
                raise HTTPException(409, "Username is already in use") from error
            connection.execute(
                "UPDATE invites SET used_at = ?, used_by = ? WHERE token_hash = ?",
                (now().isoformat(), user_id, hashed),
            )
        return RedirectResponse("/login", status_code=303)

    app.state.current_user = current_user
    app.state.require_user = require_user
    app.state.check_csrf = check_csrf
    return app


app = create_app()
