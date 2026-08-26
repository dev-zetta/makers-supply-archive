from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    root: Path
    catalog_db: Path
    state_db: Path
    secret_key: str
    secure_cookies: bool = True
    local_mode: bool = False

    @classmethod
    def from_environment(cls) -> Settings:
        root = Path(os.environ.get("MAKERS_SUPPLY_ROOT", ".")).resolve()
        return cls(
            root=root,
            catalog_db=Path(
                os.environ.get("MAKERS_SUPPLY_CATALOG_DB", root / "dist/makers-supply.sqlite")
            ).resolve(),
            state_db=Path(
                os.environ.get("MAKERS_SUPPLY_STATE_DB", root / ".state/catalog-web.sqlite")
            ).resolve(),
            secret_key=os.environ.get("MAKERS_SUPPLY_SECRET_KEY", "development-only"),
            secure_cookies=os.environ.get("MAKERS_SUPPLY_SECURE_COOKIES", "1") != "0",
        )
