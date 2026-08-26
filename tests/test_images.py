from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path

from PIL import Image, ImageDraw

from makers_supply.images import ImageProcessor, detect_title_bar
from makers_supply.models import Asset, AssetKind
from makers_supply.storage import Catalog

NOW = datetime(2026, 1, 2, tzinfo=UTC)


def title_bar_image() -> Image.Image:
    image = Image.new("RGB", (800, 800), (247, 247, 247))
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, 799, 199), fill=(90, 90, 90))
    draw.rectangle((180, 75, 620, 125), fill=(255, 255, 255))
    draw.rectangle((385, 300, 415, 680), fill=(20, 20, 20))
    return image


def stored_source(tmp_path: Path, image: Image.Image) -> tuple[Catalog, Asset]:
    catalog = Catalog(tmp_path)
    temporary = tmp_path / "source.png"
    image.save(temporary, format="PNG")
    content = temporary.read_bytes()
    digest = hashlib.sha256(content).hexdigest()
    blob = catalog.blob_path(digest, ".png")
    blob.parent.mkdir(parents=True)
    blob.write_bytes(content)
    return catalog, Asset(
        id="image-source",
        kind=AssetKind.IMAGE,
        source_url="https://example.com/source.png",
        original_filename="source.png",
        media_type="image/png",
        sha256=digest,
        size=len(content),
        blob_path=blob.relative_to(tmp_path).as_posix(),
        retrieved_at=NOW,
    )


def test_title_bar_detector_requires_safe_dark_border_transition() -> None:
    assert detect_title_bar(title_bar_image()) == 200
    assert detect_title_bar(Image.new("RGB", (800, 800), (247, 247, 247))) == 0
    assert detect_title_bar(Image.new("RGB", (800, 800), (90, 90, 90))) == 0


def test_processor_crops_normalizes_and_reuses_display_image(tmp_path: Path) -> None:
    catalog, source = stored_source(tmp_path, title_bar_image())
    processor = ImageProcessor(catalog, tmp_path / ".staging")

    first = processor.process([source])
    derived = first.assets[-1]
    second = processor.process(first.assets)

    assert (first.generated, first.cropped, first.skipped) == (1, 1, 0)
    assert derived.parent_asset_id == source.id
    assert derived.image_processing is not None
    assert derived.image_processing.crop_top == 200
    assert derived.image_processing.source_sha256 == source.sha256
    assert derived.blob_path is not None
    with Image.open(tmp_path / derived.blob_path) as display:
        assert display.size == (800, 800)
        assert display.getpixel((0, 0)) == (247, 247, 247)
    assert second.assets == first.assets
    assert (second.generated, second.reused) == (0, 1)


def test_processor_letterboxes_without_stretching(tmp_path: Path) -> None:
    source_image = Image.new("RGB", (400, 200), (10, 120, 220))
    catalog, source = stored_source(tmp_path, source_image)
    result = ImageProcessor(catalog, tmp_path / ".staging").process([source])
    derived = result.assets[-1]

    assert derived.image_processing is not None
    assert derived.image_processing.crop_top == 0
    with Image.open(tmp_path / str(derived.blob_path)) as display:
        assert display.size == (800, 800)
        assert display.getpixel((400, 100)) == (247, 247, 247)
        assert display.getpixel((400, 400)) == (10, 120, 220)


def test_processor_skips_invalid_raster_without_losing_original(tmp_path: Path) -> None:
    catalog = Catalog(tmp_path)
    blob = catalog.blob_path("a" * 64, ".png")
    blob.parent.mkdir(parents=True)
    blob.write_bytes(b"not an image")
    source = Asset(
        id="image-invalid",
        kind=AssetKind.IMAGE,
        source_url="https://example.com/invalid.png",
        original_filename="invalid.png",
        media_type="image/png",
        sha256="a" * 64,
        size=12,
        blob_path=blob.relative_to(tmp_path).as_posix(),
        retrieved_at=NOW,
    )

    result = ImageProcessor(catalog, tmp_path / ".staging").process([source])

    assert result.assets == [source]
    assert result.skipped == 1
