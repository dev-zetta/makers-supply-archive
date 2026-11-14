from __future__ import annotations

import sqlite3
from typing import Any

BUILD_STATUSES = {
    "planned": "Planned",
    "in_progress": "In progress",
    "paused": "Paused",
    "completed": "Completed",
}


def build_view(
    connection: sqlite3.Connection,
    list_id: str,
    items: list[dict[str, Any]],
) -> dict[str, Any]:
    row = connection.execute(
        "SELECT status, notes, updated_at FROM list_builds WHERE list_id=?", (list_id,)
    ).fetchone()
    build: dict[str, Any] = (
        dict(row) if row else {"status": "planned", "notes": "", "updated_at": None}
    )
    steps = connection.execute(
        """SELECT id, label, completed, completed_at, created_at, updated_at
           FROM build_steps WHERE list_id=? ORDER BY created_at, rowid""",
        (list_id,),
    ).fetchall()
    build["steps"] = [{**dict(step), "completed": bool(step["completed"])} for step in steps]
    build["completed_steps"] = sum(bool(step["completed"]) for step in steps)
    build["total_steps"] = len(steps)
    build["required_quantity"] = sum(int(item["quantity"]) for item in items)
    build["completed_quantity"] = sum(int(item["completed_quantity"]) for item in items)
    build["percent"] = (
        100 * build["completed_quantity"] // build["required_quantity"]
        if build["required_quantity"]
        else 0
    )
    return build
