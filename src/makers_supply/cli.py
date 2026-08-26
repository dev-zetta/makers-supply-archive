from pathlib import Path
from typing import Annotated

import typer

from makers_supply.assets import materialize_product
from makers_supply.backfill import CachedAssetBackfill
from makers_supply.database import build_database
from makers_supply.diffing import diff_products
from makers_supply.enrichment import enrich_products
from makers_supply.http import ArchiveHttpClient
from makers_supply.images import ImageProcessor
from makers_supply.lfs import lfs_preflight
from makers_supply.metadata_backfill import CachedMetadataBackfill
from makers_supply.models import Region
from makers_supply.storage import Catalog
from makers_supply.sync import SyncEngine, SyncOptions
from makers_supply.validation import validate_catalog

app = typer.Typer(
    name="makers-supply",
    help="Build and inspect the Maker's Supply archive.",
    no_args_is_help=True,
)


@app.command()
def version() -> None:
    """Print the installed package version."""
    from makers_supply import __version__

    typer.echo(__version__)


@app.command("validate")
def validate_command(
    root: Annotated[Path, typer.Option(exists=True, file_okay=False)] = Path("."),
    check_blobs: Annotated[bool, typer.Option("--check-blobs/--no-check-blobs")] = True,
) -> None:
    """Validate product records and their referenced blobs."""
    issues = validate_catalog(Catalog(root.resolve()), check_blobs=check_blobs)
    for issue in issues:
        typer.echo(f"{issue.product_id}: {issue.message}", err=True)
    if issues:
        raise typer.Exit(1)
    typer.echo("catalog is valid")


@app.command("build-db")
def build_db_command(
    output: Annotated[Path, typer.Option(dir_okay=False)] = Path("dist/makers-supply.sqlite"),
    root: Annotated[Path, typer.Option(exists=True, file_okay=False)] = Path("."),
) -> None:
    """Build a queryable SQLite catalog from canonical JSON records."""
    build_database(Catalog(root.resolve()), output)
    typer.echo(str(output))


@app.command("enrich")
def enrich_command(
    root: Annotated[Path, typer.Option(exists=True, file_okay=False)] = Path("."),
    check: Annotated[bool, typer.Option("--check")] = False,
) -> None:
    """Apply reviewed category and measurement rules to canonical records."""
    catalog = Catalog(root.resolve())
    products = catalog.products()
    changed = []
    for product, enriched in zip(
        products, enrich_products(products, catalog.root), strict=True
    ):
        if enriched != product:
            changed.append(enriched)
    if check and changed:
        typer.echo(f"{len(changed)} product records need enrichment", err=True)
        raise typer.Exit(1)
    if not check:
        catalog.write_products(changed)
    typer.echo(f"{len(changed)} product records {'need' if check else 'received'} enrichment")


@app.command("materialize")
def materialize_command(
    product_id: str,
    output: Annotated[Path, typer.Option(file_okay=False)],
    root: Annotated[Path, typer.Option(exists=True, file_okay=False)] = Path("."),
) -> None:
    """Reconstruct one product's source and extracted files."""
    count = materialize_product(Catalog(root.resolve()), product_id, output.resolve())
    typer.echo(f"materialized {count} files into {output}")


@app.command("sync")
def sync_command(
    regions: Annotated[list[Region] | None, typer.Option("--region")] = None,
    metadata_only: Annotated[bool, typer.Option("--metadata-only")] = False,
    dry_run: Annotated[bool, typer.Option("--dry-run")] = False,
    resume: Annotated[bool, typer.Option("--resume")] = False,
    max_products: Annotated[int | None, typer.Option(min=1)] = None,
    delay: Annotated[float, typer.Option(min=2.0)] = 2.0,
    jitter: Annotated[float, typer.Option(min=0.0)] = 1.0,
    root: Annotated[Path, typer.Option(exists=True, file_okay=False)] = Path("."),
) -> None:
    """Synchronize products and assets from official regional storefronts."""
    selected = tuple(regions) if regions else tuple(Region)
    with ArchiveHttpClient(delay=delay, jitter=jitter) as client:
        result = SyncEngine(root.resolve(), client).run(
            SyncOptions(
                regions=selected,
                metadata_only=metadata_only,
                dry_run=dry_run,
                resume=resume,
                max_products=max_products,
            )
        )
    typer.echo(result.diff.markdown())
    typer.echo("promoted" if result.promoted else "no tracked changes")


@app.command("backfill-assets")
def backfill_assets_command(
    product_ids: Annotated[list[str] | None, typer.Option("--product-id")] = None,
    download: Annotated[
        bool, typer.Option("--download/--discover-only")
    ] = False,
    dry_run: Annotated[bool, typer.Option("--dry-run")] = False,
    resume: Annotated[bool, typer.Option("--resume/--no-resume")] = True,
    delay: Annotated[float, typer.Option(min=2.0)] = 2.0,
    jitter: Annotated[float, typer.Option(min=0.0)] = 1.0,
    root: Annotated[Path, typer.Option(exists=True, file_okay=False)] = Path("."),
) -> None:
    """Recover public assets from official product pages cached by synchronization."""
    with ArchiveHttpClient(delay=delay, jitter=jitter) as client:
        result = CachedAssetBackfill(root.resolve(), client).run(
            set(product_ids) if product_ids else None,
            download=download,
            dry_run=dry_run,
            resume=resume,
        )
    typer.echo(
        f"scanned {result.products_scanned} products; "
        f"{result.products_with_missing_assets} have missing assets; "
        f"discovered {result.assets_discovered}, downloaded {result.assets_downloaded}, "
        f"extracted {result.assets_extracted}, rejected {result.assets_rejected}; "
        f"{result.bytes_downloaded} bytes downloaded; "
        f"{result.cached_pages_missing} cached pages missing"
    )
    if download:
        typer.echo("promoted" if result.promoted else "no tracked changes")
    elif result.assets_discovered:
        typer.echo("discovery only; rerun with --download to archive these assets")


@app.command("backfill-metadata")
def backfill_metadata_command(
    product_ids: Annotated[list[str] | None, typer.Option("--product-id")] = None,
    check: Annotated[bool, typer.Option("--check")] = False,
    root: Annotated[Path, typer.Option(exists=True, file_okay=False)] = Path("."),
) -> None:
    """Recover descriptions and tables from official pages cached by synchronization."""
    result = CachedMetadataBackfill(root.resolve()).run(
        set(product_ids) if product_ids else None,
        promote=not check,
    )
    typer.echo(
        f"scanned {result.products_scanned} products; "
        f"{result.products_updated} records "
        f"{'need' if check else 'received'} metadata enrichment; "
        f"recovered {result.descriptions_recovered} descriptions and "
        f"{result.specifications_recovered} specification tables; "
        f"{result.cached_pages_missing} cached pages missing, "
        f"{result.cached_pages_failed} cached pages failed to parse"
    )
    if check and result.products_updated:
        raise typer.Exit(1)


@app.command("diff")
def diff_command(
    against: Annotated[Path, typer.Option(exists=True, file_okay=False)],
    root: Annotated[Path, typer.Option(exists=True, file_okay=False)] = Path("."),
) -> None:
    """Compare this catalog with another checkout or snapshot."""
    result = diff_products(
        Catalog(against.resolve()).products(), Catalog(root.resolve()).products()
    )
    typer.echo(result.markdown())


@app.command("lfs-preflight")
def lfs_preflight_command(
    max_total_bytes: Annotated[int, typer.Option(min=1)] = 5 * 1024 * 1024 * 1024,
    max_file_bytes: Annotated[int, typer.Option(min=1)] = 500 * 1024 * 1024,
    root: Annotated[Path, typer.Option(exists=True, file_okay=False)] = Path("."),
) -> None:
    """Check Git LFS availability and configured blob size budgets."""
    report = lfs_preflight(
        root.resolve(), max_total_bytes=max_total_bytes, max_file_bytes=max_file_bytes
    )
    typer.echo(
        f"{report.files} blobs, {report.bytes} bytes total, "
        f"{report.largest_file} bytes largest"
    )
    for error in report.errors:
        typer.echo(error, err=True)
    if report.errors:
        raise typer.Exit(1)


@app.command("process-images")
def process_images_command(
    root: Annotated[Path, typer.Option(exists=True, file_okay=False)] = Path("."),
) -> None:
    """Create normalized display images while preserving downloaded originals."""
    catalog = Catalog(root.resolve())
    processor = ImageProcessor(catalog, catalog.root / ".staging" / "image-processing")
    changed = generated = reused = cropped = skipped = 0
    for product in catalog.products():
        result = processor.process(product.assets)
        generated += result.generated
        reused += result.reused
        cropped += result.cropped
        skipped += result.skipped
        if result.assets != product.assets:
            catalog.write_product(product.model_copy(update={"assets": result.assets}))
            changed += 1
    typer.echo(
        f"updated {changed} products; generated {generated}, reused {reused}, "
        f"cropped {cropped}, skipped {skipped} display images"
    )
