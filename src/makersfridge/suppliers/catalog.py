from __future__ import annotations

import hashlib
import re
from pathlib import Path, PurePosixPath
from typing import Literal
from urllib.parse import unquote, urlsplit

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator

from makersfridge.models import Asset, AssetKind, RightsStatus, StableId
from makersfridge.suppliers import SUPPLIERS


class PilotAsset(BaseModel):
    model_config = ConfigDict(extra="forbid")
    url: HttpUrl
    filename: str
    role: Literal["component", "accessory", "drawing", "document", "image", "other"] = "component"
    applies_to_skus: list[str] = Field(default_factory=list)
    hardware_revision: str | None = None
    source_repository: str | None = None
    source_commit: str | None = None
    source_path: str | None = None
    license_url: HttpUrl | None = None
    rights_status: RightsStatus = RightsStatus.UNKNOWN
    compatibility_notes: str = ""

    @model_validator(mode="after")
    def validate_filename(self) -> PilotAsset:
        # Use the same path and filename contract as archived assets.
        Asset(
            id="pilot-validation",
            kind=AssetKind.MODEL,
            source_url=self.url,
            original_filename=self.filename,
            media_type="application/octet-stream",
        )
        if (
            self.rights_status in {RightsStatus.PERMISSIVE, RightsStatus.LICENSED}
            and self.license_url is None
        ):
            raise ValueError("licensed assets require explicit license evidence")
        if any((self.source_repository, self.source_commit, self.source_path)):
            if not (self.source_repository and self.source_commit and self.source_path):
                raise ValueError("GitHub assets require a reviewed repository, commit and path")
            repo = urlsplit(self.source_repository)
            path = Path(self.source_path)
            raw = urlsplit(str(self.url))
            if (
                not re.fullmatch(r"[0-9a-f]{40}", self.source_commit)
                or path.is_absolute()
                or ".." in path.parts
                or repo.scheme != "https"
                or repo.netloc != "github.com"
                or len(repo.path.strip("/").split("/")) != 2
            ):
                raise ValueError("invalid pinned GitHub source identity")
            expected = f"{repo.path.rstrip('/')}/{self.source_commit}/{self.source_path}"
            if (
                raw.scheme != "https"
                or raw.netloc != "raw.githubusercontent.com"
                or unquote(raw.path) != expected
                or raw.query
                or raw.fragment
            ):
                raise ValueError("asset URL does not match the pinned GitHub source")
        return self


class PilotProduct(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: StableId
    supplier_id: StableId
    manufacturer: str
    name: str
    hardware_revision: str | None = None
    source_kind: Literal["shopify", "waveshare", "reference"] = "reference"
    store_id: str = ""
    product_url: HttpUrl
    documentation_urls: list[HttpUrl] = Field(default_factory=list)
    categories: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    specifications: dict[str, str] = Field(default_factory=dict)
    skus: list[str] = Field(default_factory=list)
    part_numbers: list[str] = Field(default_factory=list)
    selected_skus: list[str] = Field(default_factory=list)
    description: str = ""
    compatibility_notes: str = ""
    review_status: str = "reviewed"
    reviewed_at: str | None = None
    shopify_handle: str | None = None
    default_currency: str | None = None
    assets: list[PilotAsset] = Field(default_factory=list)

    @model_validator(mode="after")
    def known_supplier(self) -> PilotProduct:
        if self.supplier_id not in SUPPLIERS or self.supplier_id == "bambu-lab":
            raise ValueError(f"unsupported pilot supplier: {self.supplier_id}")
        for asset in self.assets:
            if set(asset.applies_to_skus) - set(self.skus):
                raise ValueError("asset applicability must use this product's reviewed SKUs")
        return self


class PilotCatalog(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal[1] = 1
    reviewed_at: str | None = None
    notes: str = ""
    includes: list[str] = Field(default_factory=list)
    products: list[PilotProduct]

    @model_validator(mode="after")
    def unique_ids(self) -> PilotCatalog:
        ids = [product.id for product in self.products]
        if len(ids) != len(set(ids)):
            raise ValueError("pilot product IDs must be unique")
        return self


def load_pilots(path: Path) -> list[PilotProduct]:
    return load_pilots_snapshot(path)[0]


def load_pilots_snapshot(path: Path) -> tuple[list[PilotProduct], str]:
    """Read reviewed sources and bind resume identity to every included file."""
    base = path.parent.resolve()
    visited: set[Path] = set()
    digest = hashlib.sha256()
    products: list[PilotProduct] = []

    def read(source: Path, depth: int = 0) -> None:
        resolved = source.resolve()
        if not resolved.is_relative_to(base):
            raise ValueError("source include escapes the configuration directory")
        if resolved in visited or depth > 8:
            raise ValueError("cyclic or repeated source include")
        visited.add(resolved)
        raw = resolved.read_bytes()
        digest.update(resolved.relative_to(base).as_posix().encode() + b"\0" + raw + b"\0")
        catalog = PilotCatalog.model_validate_json(raw)
        products.extend(catalog.products)
        for name in catalog.includes:
            relative = PurePosixPath(name)
            if (
                not name
                or "\\" in name
                or relative.is_absolute()
                or ".." in relative.parts
                or relative.suffix.lower() != ".json"
            ):
                raise ValueError(f"invalid source include: {name!r}")
            read(base / relative, depth + 1)

    read(path)
    # Validate product identities across the complete set of reviewed source files.
    PilotCatalog(products=products)
    return products, digest.hexdigest()
