from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, StringConstraints, field_validator

StableId = Annotated[str, StringConstraints(pattern=r"^[a-z0-9][a-z0-9-]{2,127}$")]
Sha256 = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]


def utc_now() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)


class ArchiveModel(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class Region(StrEnum):
    US = "us"
    EU = "eu"
    UK = "uk"
    CA = "ca"
    AU = "au"
    JP = "jp"
    KR = "kr"
    ASIA = "asia"


class RightsStatus(StrEnum):
    UNKNOWN = "unknown"
    PERMISSIVE = "permissive"
    RESTRICTED = "restricted"


class AssetKind(StrEnum):
    IMAGE = "image"
    MODEL = "model"
    ARCHIVE = "archive"
    DOCUMENT = "document"
    OTHER = "other"


class ImageProcessing(ArchiveModel):
    algorithm: Literal["catalog-display-v1"] = "catalog-display-v1"
    source_sha256: Sha256
    source_width: int = Field(gt=0)
    source_height: int = Field(gt=0)
    crop_top: int = Field(default=0, ge=0)
    output_width: int = Field(gt=0)
    output_height: int = Field(gt=0)


class SourceAlias(ArchiveModel):
    region: Region
    handle: str
    product_id: str | None = None


class Provenance(ArchiveModel):
    kind: Literal["page_table", "description", "classification_rule", "manual_override"]
    reference: str
    source_url: HttpUrl | None = None


class CategoryAssignment(ArchiveModel):
    id: StableId
    label: str
    path: list[str] = Field(default_factory=list)
    provenance: Provenance


class Measurement(ArchiveModel):
    label: str
    raw_value: str
    numeric_value: Decimal | None = None
    unit: str | None = None
    applies_to: str | None = None
    provenance: Provenance


class SourceTable(ArchiveModel):
    caption: str | None = None
    headers: list[str] = Field(default_factory=list)
    rows: list[list[str]] = Field(default_factory=list)
    provenance: Provenance


class DescriptionBlock(ArchiveModel):
    kind: Literal["heading", "paragraph", "bullet"]
    text: str = Field(min_length=1)


class Variant(ArchiveModel):
    region: Region
    variant_id: str
    title: str
    sku: str | None = None
    part_number: str | None = None
    available: bool | None = None
    price: str | None = None
    compare_at_price: str | None = None
    currency: str | None = None
    url: HttpUrl | None = None
    image_url: HttpUrl | None = None

    @field_validator("currency")
    @classmethod
    def uppercase_optional_currency(cls, value: str | None) -> str | None:
        return None if value is None else value.upper()


class RegionalOffer(ArchiveModel):
    region: Region
    url: HttpUrl
    currency: str = Field(min_length=3, max_length=3)
    price: str | None = None
    compare_at_price: str | None = None
    available: bool | None = None
    listed: bool = True
    missing_runs: int = Field(default=0, ge=0)
    retrieved_at: datetime

    @field_validator("currency")
    @classmethod
    def uppercase_currency(cls, value: str) -> str:
        return value.upper()


class Asset(ArchiveModel):
    id: StableId
    kind: AssetKind
    source_url: HttpUrl
    original_filename: str
    media_type: str
    declared_media_type: str | None = None
    sha256: Sha256 | None = None
    size: int | None = Field(default=None, ge=0)
    blob_path: str | None = None
    rights_status: RightsStatus = RightsStatus.UNKNOWN
    retrieved_at: datetime | None = None
    rejection_reason: str | None = None
    parent_asset_id: StableId | None = None
    archive_member_path: str | None = None
    image_processing: ImageProcessing | None = None

    @field_validator("original_filename")
    @classmethod
    def filename_only(cls, value: str) -> str:
        if not value or value in {".", ".."} or "/" in value or "\\" in value:
            raise ValueError("original_filename must be a plain filename")
        return value


class BoxItemQuantity(ArchiveModel):
    variant: str = Field(min_length=1)
    quantity: str = Field(min_length=1)


class BoxItem(ArchiveModel):
    name: str
    quantity: str | None = None
    variant_quantities: list[BoxItemQuantity] = Field(default_factory=list)
    item_number: str | None = None
    source_url: HttpUrl | None = None
    linked_product_id: StableId | None = None


class RelatedLink(ArchiveModel):
    title: str
    url: HttpUrl
    kind: Literal["makerworld", "documentation", "other"] = "other"


class Product(ArchiveModel):
    schema_version: Literal[1, 2, 3, 4] = 4
    id: StableId
    name: str
    description_html: str = ""
    description_text: str = ""
    description_blocks: list[DescriptionBlock] = Field(default_factory=list)
    categories: list[str] = Field(default_factory=list)
    category_assignments: list[CategoryAssignment] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    specifications: dict[str, str] = Field(default_factory=dict)
    measurements: list[Measurement] = Field(default_factory=list)
    source_tables: list[SourceTable] = Field(default_factory=list)
    box_contents: list[BoxItem] = Field(default_factory=list)
    part_numbers: list[str] = Field(default_factory=list)
    skus: list[str] = Field(default_factory=list)
    aliases: list[SourceAlias] = Field(default_factory=list)
    variants: list[Variant] = Field(default_factory=list)
    offers: list[RegionalOffer] = Field(default_factory=list)
    assets: list[Asset] = Field(default_factory=list)
    related_links: list[RelatedLink] = Field(default_factory=list)
    first_seen: datetime
    last_seen: datetime
    active: bool = True
    removed_at: datetime | None = None

    @field_validator("categories", "tags", "part_numbers", "skus")
    @classmethod
    def unique_strings(cls, values: list[str]) -> list[str]:
        return list(dict.fromkeys(item.strip() for item in values if item.strip()))

    @field_validator("last_seen")
    @classmethod
    def last_seen_has_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("timestamps must include a timezone")
        return value

    def asset(self, asset_id: str) -> Asset | None:
        return next((asset for asset in self.assets if asset.id == asset_id), None)


class RegionRun(ArchiveModel):
    region: Region
    success: bool
    products_seen: int = Field(ge=0)
    error: str | None = None


class RunManifest(ArchiveModel):
    schema_version: Literal[1] = 1
    started_at: datetime
    completed_at: datetime
    metadata_only: bool
    regions: list[RegionRun]
    products_written: int = Field(ge=0)
    assets_downloaded: int = Field(ge=0)
    assets_rejected: int = Field(default=0, ge=0)
    bytes_downloaded: int = Field(ge=0)
