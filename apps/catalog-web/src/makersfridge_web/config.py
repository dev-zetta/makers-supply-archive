from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def environment(name: str, default: str) -> str:
    """Prefer the new setting while accepting existing deployment configuration."""
    return os.environ.get(f"MAKERSFRIDGE_{name}", os.environ.get(f"MAKERS_SUPPLY_{name}", default))


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
        root = Path(environment("ROOT", ".")).resolve()
        catalog = root / "dist/makersfridge.sqlite"
        legacy_catalog = root / "dist/makers-supply.sqlite"
        if not catalog.exists() and legacy_catalog.is_file():
            catalog = legacy_catalog
        return cls(
            root=root,
            catalog_db=Path(
                environment("CATALOG_DB", str(catalog))
            ).resolve(),
            state_db=Path(
                environment("STATE_DB", str(root / ".state/catalog-web.sqlite"))
            ).resolve(),
            secret_key=environment("SECRET_KEY", "development-only"),
            secure_cookies=environment("SECURE_COOKIES", "1") != "0",
        )
