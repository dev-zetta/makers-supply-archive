from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from makers_supply.storage import atomic_write


class SyncCheckpoint(BaseModel):
    schema_version: Literal[1] = 1
    signature: str
    started_at: str
    status: Literal["running", "complete"] = "running"
    page_hashes: dict[str, str] = Field(default_factory=dict)

    def save(self, path: Path) -> None:
        atomic_write(path, self.model_dump_json(indent=2) + "\n")


def resume_signature(options: dict[str, object], snapshot: str) -> str:
    return hashlib.sha256(
        json.dumps({"options": options, "snapshot": snapshot}, sort_keys=True).encode()
    ).hexdigest()
