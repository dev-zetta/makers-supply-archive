from __future__ import annotations

import getpass
import sys
from typing import Annotated
from uuid import uuid4

import typer

from makers_supply_web.config import Settings
from makers_supply_web.security import INVITE_LIFETIME, PASSWORDS, now, token, token_hash
from makers_supply_web.state import connect, migrate

app = typer.Typer(name="makers-supply-web", no_args_is_help=True)


@app.command("migrate")
def migrate_command() -> None:
    """Apply forward-only application-state migrations."""
    settings = Settings.from_environment()
    typer.echo(f"state schema version {migrate(settings.state_db)}")


@app.command("create-admin")
def create_admin(
    username: str,
    password_stdin: Annotated[
        bool, typer.Option("--password-stdin", help="Read one password line from stdin")
    ] = False,
    if_missing: Annotated[
        bool,
        typer.Option("--if-missing", help="Exit successfully when an administrator exists"),
    ] = False,
) -> None:
    """Create the initial administrator using an interactive password prompt."""
    settings = Settings.from_environment()
    migrate(settings.state_db)
    if if_missing:
        with connect(settings.state_db) as connection:
            existing = connection.execute(
                "SELECT 1 FROM users WHERE is_admin = 1 AND active = 1 LIMIT 1"
            ).fetchone()
        if existing is not None:
            typer.echo("an active administrator already exists")
            return
    password = sys.stdin.readline().rstrip("\n") if password_stdin else getpass.getpass(
        "Password (12+ characters): "
    )
    confirmation = password if password_stdin else getpass.getpass("Confirm password: ")
    if password != confirmation or len(password) < 12:
        raise typer.BadParameter("passwords must match and contain at least 12 characters")
    with connect(settings.state_db) as connection, connection:
        connection.execute(
            "INSERT INTO users VALUES (?, ?, ?, 1, 1, ?)",
            (str(uuid4()), username.strip(), PASSWORDS.hash(password), now().isoformat()),
        )
    typer.echo(f"created administrator {username}")


@app.command()
def invite(
    base_url: Annotated[str, typer.Option()] = "https://catalog.example.com",
    admin: Annotated[str, typer.Option(help="Username of the inviting administrator")] = "admin",
) -> None:
    """Create a single-use invitation URL; no email is sent."""
    settings = Settings.from_environment()
    migrate(settings.state_db)
    raw = token()
    with connect(settings.state_db) as connection, connection:
        user = connection.execute(
            "SELECT id FROM users WHERE username = ? COLLATE NOCASE AND is_admin = 1", (admin,)
        ).fetchone()
        if user is None:
            raise typer.BadParameter("administrator was not found")
        connection.execute(
            "INSERT INTO invites VALUES (?, ?, ?, NULL, NULL)",
            (
                token_hash(raw, settings.secret_key),
                user["id"],
                (now() + INVITE_LIFETIME).isoformat(),
            ),
        )
    typer.echo(f"{base_url.rstrip('/')}/invite/{raw}")


@app.command()
def serve(
    host: str = "127.0.0.1",
    port: int = 8000,
    reload: Annotated[bool, typer.Option("--reload")] = False,
) -> None:
    """Run the catalog web service."""
    import uvicorn

    uvicorn.run("makers_supply_web.app:app", host=host, port=port, reload=reload)
