from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError

from makers_supply.models import Asset, AssetKind, ImageProcessing
from makers_supply.storage import Catalog, atomic_write
from makers_supply.validation import sha256_file

PROCESSING_ALGORITHM = "catalog-display-v1"
DISPLAY_WIDTH = 800
DISPLAY_HEIGHT = 800
DISPLAY_BACKGROUND = (247, 247, 247, 255)
MAX_IMAGE_PIXELS = 50_000_000
HEADER_COLOR_TOLERANCE = 8
HEADER_MIN_FRACTION = 0.08
HEADER_MAX_FRACTION = 0.40


@dataclass(frozen=True)
class ImageProcessingResult:
    assets: list[Asset]
    generated: int
    reused: int
    cropped: int
    skipped: int


def _pixel(image: Image.Image, x: int, y: int) -> tuple[int, int, int]:
    value = image.getpixel((x, y))
    if not isinstance(value, tuple) or len(value) < 3:
        raise ValueError("expected an RGB image")
    return int(value[0]), int(value[1]), int(value[2])


def _near_color(
    left: tuple[int, int, int], right: tuple[int, int, int], tolerance: int
) -> bool:
    return all(abs(left[index] - right[index]) <= tolerance for index in range(3))


def detect_title_bar(image: Image.Image) -> int:
    """Find a conservative solid, dark-neutral title bar attached to the top edge."""
    rgb = image.convert("RGB")
    width, height = rgb.size
    if width < 32 or height < 32:
        return 0
    corner = _pixel(rgb, 0, 0)
    if max(corner) - min(corner) > 8 or not 45 <= sum(corner) / 3 <= 140:
        return 0

    sample_x = sorted({round((width - 1) * index / 16) for index in range(17)})
    if sum(
        _near_color(_pixel(rgb, x, 0), corner, HEADER_COLOR_TOLERANCE)
        for x in sample_x
    ) < len(sample_x) - 1:
        return 0

    minimum = max(2, round(height * HEADER_MIN_FRACTION))
    maximum = min(height - 2, round(height * HEADER_MAX_FRACTION))
    transition = 0
    for y in range(1, maximum + 1):
        left_matches = _near_color(
            _pixel(rgb, 0, y), corner, HEADER_COLOR_TOLERANCE
        )
        right_matches = _near_color(
            _pixel(rgb, width - 1, y), corner, HEADER_COLOR_TOLERANCE
        )
        if left_matches and right_matches:
            continue
        if y >= minimum:
            transition = y
        break
    if not transition:
        return 0

    # Ignore a one-pixel border or compression artifact: the new body color must persist.
    body_rows = range(transition, min(transition + 3, height))
    if any(
        _near_color(_pixel(rgb, 0, y), corner, 20)
        or _near_color(_pixel(rgb, width - 1, y), corner, 20)
        for y in body_rows
    ):
        return 0

    # The last header row may cross antialiased title text, but most sampled pixels
    # must still carry the same solid title-bar color.
    header_matches = sum(
        _near_color(
            _pixel(rgb, x, transition - 1), corner, HEADER_COLOR_TOLERANCE
        )
        for x in sample_x
    )
    if header_matches < round(len(sample_x) * 0.70):
        return 0
    return transition


def _display_image(source: Path) -> tuple[Image.Image, ImageProcessing]:
    Image.MAX_IMAGE_PIXELS = MAX_IMAGE_PIXELS
    with Image.open(source) as opened:
        opened.seek(0)
        oriented = ImageOps.exif_transpose(opened)
        source_width, source_height = oriented.size
        rgba = oriented.convert("RGBA")
    crop_top = detect_title_bar(rgba)
    if crop_top:
        rgba = rgba.crop((0, crop_top, rgba.width, rgba.height))

    scale = min(DISPLAY_WIDTH / rgba.width, DISPLAY_HEIGHT / rgba.height)
    resized_width = max(1, round(rgba.width * scale))
    resized_height = max(1, round(rgba.height * scale))
    resized = rgba.resize((resized_width, resized_height), Image.Resampling.LANCZOS)
    canvas = Image.new("RGBA", (DISPLAY_WIDTH, DISPLAY_HEIGHT), DISPLAY_BACKGROUND)
    position = (
        (DISPLAY_WIDTH - resized_width) // 2,
        (DISPLAY_HEIGHT - resized_height) // 2,
    )
    canvas.alpha_composite(resized, position)
    processing = ImageProcessing(
        source_sha256=sha256_file(source),
        source_width=source_width,
        source_height=source_height,
        crop_top=crop_top,
        output_width=DISPLAY_WIDTH,
        output_height=DISPLAY_HEIGHT,
    )
    return canvas.convert("RGB"), processing


def _derived_id(source: Asset) -> str:
    identity = f"{PROCESSING_ALGORITHM}:{source.id}:{source.sha256}"
    return f"image-display-{hashlib.sha256(identity.encode()).hexdigest()[:20]}"


def _derived_filename(source: Asset) -> str:
    return f"{Path(source.original_filename).stem}.catalog.png"


class ImageProcessor:
    def __init__(self, catalog: Catalog, staging_dir: Path) -> None:
        self.catalog = catalog
        self.staging_dir = staging_dir

    def _store(self, image: Image.Image, source: Asset) -> tuple[str, int, str]:
        temporary = self.staging_dir / "processed-images" / f"{source.sha256}.png"
        temporary.parent.mkdir(parents=True, exist_ok=True)
        image.save(temporary, format="PNG", optimize=False, compress_level=9)
        digest = sha256_file(temporary)
        destination = self.catalog.blob_path(digest, ".png")
        relative = destination.relative_to(self.catalog.root).as_posix()
        if destination.exists():
            if destination.stat().st_size != temporary.stat().st_size:
                raise ValueError(f"hash collision at {relative}")
        else:
            atomic_write(destination, temporary.read_bytes())
        destination.chmod(0o644)
        return digest, temporary.stat().st_size, relative

    def process(self, assets: list[Asset]) -> ImageProcessingResult:
        originals = [
            asset
            for asset in assets
            if asset.kind == AssetKind.IMAGE
            and asset.parent_asset_id is None
            and asset.sha256
            and asset.blob_path
            and not asset.rejection_reason
        ]
        retained = [asset for asset in assets if asset.image_processing is None]
        existing = {
            asset.parent_asset_id: asset
            for asset in assets
            if asset.image_processing is not None and asset.parent_asset_id
        }
        derived: list[Asset] = []
        generated = reused = cropped = skipped = 0
        for source in originals:
            if source.blob_path is None:
                skipped += 1
                continue
            previous = existing.get(source.id)
            if (
                previous
                and previous.image_processing
                and previous.image_processing.algorithm == PROCESSING_ALGORITHM
                and previous.image_processing.source_sha256 == source.sha256
                and previous.image_processing.output_width == DISPLAY_WIDTH
                and previous.image_processing.output_height == DISPLAY_HEIGHT
                and previous.blob_path
                and (self.catalog.root / previous.blob_path).is_file()
            ):
                derived.append(previous)
                reused += 1
                cropped += int(previous.image_processing.crop_top > 0)
                continue
            try:
                display, processing = _display_image(self.catalog.root / source.blob_path)
            except (Image.DecompressionBombError, UnidentifiedImageError, OSError, ValueError):
                skipped += 1
                continue
            digest, size, blob_path = self._store(display, source)
            derived.append(
                Asset(
                    id=_derived_id(source),
                    kind=AssetKind.IMAGE,
                    source_url=source.source_url,
                    original_filename=_derived_filename(source),
                    media_type="image/png",
                    sha256=digest,
                    size=size,
                    blob_path=blob_path,
                    rights_status=source.rights_status,
                    retrieved_at=source.retrieved_at,
                    parent_asset_id=source.id,
                    image_processing=processing,
                )
            )
            generated += 1
            cropped += int(processing.crop_top > 0)
        return ImageProcessingResult(
            assets=[*retained, *derived],
            generated=generated,
            reused=reused,
            cropped=cropped,
            skipped=skipped,
        )
