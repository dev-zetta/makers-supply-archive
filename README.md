# Maker's Supply Archive

A versioned, multi-region catalog of Bambu Lab Maker's Supply products and their
publicly downloadable design assets. Canonical, reviewable JSON records are paired
with content-addressed files and a generated SQLite catalog.

The archive covers the official USA, EU, UK, Canada, Australia, Japan, Korea, and
Asia storefronts. It records links to related MakerWorld projects but does not mirror
those community project files.

## Installation

On Ubuntu, Debian, Arch Linux, or Fedora, run:

```bash
./setup.sh
```

The idempotent setup script detects the distribution, installs Git LFS and other system
prerequisites, installs `uv` and Python 3.12, creates the project environment, downloads
the approximately 4.1 GiB LFS snapshot, and validates it. Use `--skip-lfs-pull` for a
metadata-only checkout, `--runtime-only` to omit development tools, or `--with-docker`
to also install and start Docker for the visual catalog. See `./setup.sh --help`.

## Quick start

```bash
uv run makers-supply sync --metadata-only --region us
uv run makers-supply backfill-metadata
uv run makers-supply backfill-assets
uv run makers-supply process-images
uv run makers-supply validate
uv run makers-supply build-db
uv run makers-supply materialize ia005-power-distribution-board --output ./export
```

Run `uv run makers-supply --help` for all options. Synchronization occurs in
`.staging/`; validated results are promoted after validation. `--resume` preserves partial
downloads and verified pages from a matching interrupted run; completed runs start
fresh scans. Cached pages remain available for backfill. `--dry-run` leaves tracked
data unchanged, and `--max-products` is useful
for live smoke tests.

`backfill-assets` audits official pages retained in `.staging/pages` for CAD archives,
direct models, PDFs, and other downloadable files that an older parser missed. It is
discovery-only by default; review the count, then archive through the normal validated
pipeline with `uv run makers-supply backfill-assets --download --resume`. A product can
be repaired alone with `--product-id <stable-id>`. This command never fetches a cached
storefront page again and does not bypass a current `robots.txt` restriction.

`backfill-metadata` idempotently reparses the canonical cached storefront page for
each product. It recovers Overview narratives, horizontal and vertical specification
tables, package contents, and reviewed deterministic categories without making new
network requests. Use `--check` in CI or before promotion, and `--product-id
<stable-id>` for a focused repair.

Full binary synchronization automatically produces derived 800×800 display images.
`process-images` idempotently backfills an existing snapshot. It preserves every
downloaded original, conservatively removes the known solid dark title bar when its
border-color transition is detected, and otherwise uses aspect-preserving resize plus
centered padding—never stretching or inventing image content. Processing dimensions,
crop height, algorithm version, parent asset, and source hash are recorded in JSON.

## Visual catalog

The responsive web application in `apps/catalog-web` visually browses the complete
archive. It provides a zoomable thumbnail gallery, categories, published dimensions,
specifications, per-variant regional pricing, full-text search, STL/3MF previews,
secure asset downloads, and shareable parts lists with current and saved cost totals.
Parts lists also track build status, notes, checklist steps and completed hardware
quantities in durable user storage. Export a project ZIP with the list, its progress,
available design files and a manifest of file hashes, provenance and rights; images
are optional. Catalog records and regional price snapshots remain separate from build
progress.
The model viewer uses studio lighting, smoothed crease-aware normals, glossy PBR
materials, and embedded STL/3MF colors or textures when they are available.
Project bundles are deterministically tagged as kits. Product pages keep narrative
descriptions separate from source tables and show normalized included-item rows with
variant-specific quantities plus links to matching local catalog records and official
Bambu Lab listings when available.
Repeated product prefixes are removed from variant display labels while the exact
official title remains in authoritative data. Download cards are grouped by variant
when an official part number occurs unambiguously in the filename or archive path;
family-wide and ambiguous files remain in a separate shared group.
Products can be selected with checkboxes while using the normal search and filters;
the selection drawer adds them to an existing list or creates a new one without
requiring product IDs to be typed manually.

The generated catalog database is read-only to the application; user accounts and
parts lists use a separate writable SQLite database. With Docker installed, one command
builds the image and catalog, creates the first administrator, and starts the UI:

```bash
./scripts/run-catalog-web.sh
```

Open <http://127.0.0.1:8000>. The first run asks for the administrator password;
later runs reuse the account, private lists, remembered sessions, and a persistent
local session secret. Use `--detach`, `--port PORT`, or `--no-build` as needed. Run
`./scripts/run-catalog-web.sh --help` for all launcher options.

For native Python development after running `./setup.sh`:

```bash
uv run makers-supply build-db
export MAKERS_SUPPLY_ROOT="$PWD"
export MAKERS_SUPPLY_CATALOG_DB="$PWD/dist/makers-supply.sqlite"
export MAKERS_SUPPLY_STATE_DB="$PWD/.state/catalog-web.sqlite"
export MAKERS_SUPPLY_SECRET_KEY="$(openssl rand -hex 32)"
export MAKERS_SUPPLY_SECURE_COOKIES=0
uv run makers-supply-web create-admin admin
uv run makers-supply-web serve
```

The insecure-cookie setting is only for loopback HTTP.
Deployments must keep secure cookies enabled and terminate HTTPS in a reverse proxy.
Unchecked login uses a browser-session cookie; “Remember me” persists a hashed server
session and cookie for 30 days. Changing `MAKERS_SUPPLY_SECRET_KEY` invalidates all
existing sessions.
Use `uv run makers-supply-web invite --admin admin --base-url https://catalog.example`
to create a single-use, 24-hour invitation URL. Open registration and email delivery
are intentionally absent.

### Standalone local app

A portable, login-free edition can be built for Windows, macOS, or Linux without
shipping Python, `uv`, Node.js, or Docker to the end user. Builds are native: run the
command on each target operating system and CPU architecture after pulling the Git LFS
objects:

```bash
npm --prefix apps/catalog-desktop ci
uv run --package makers-supply-web --extra standalone \
  python scripts/build-standalone.py
```

Official downloads contain one platform app plus shared ZIP data packs. Extract the
app and **every** data pack from the same release into one directory. Every pack is
at most 1,800,000,000 bytes. See [RELEASE.md](RELEASE.md) for checksums, platform support,
unsigned-build prompts, installation, upgrades, and release acceptance.

The default local build remains bundled. Use `--layout split` to build only the app,
and `uv run python scripts/build-data-packs.py --revision "$(git rev-parse HEAD)"`
to generate shared data. No Python or other development tools are needed by end users.

The result is written to `dist/standalone/makers-supply-catalog-<platform>-<arch>` and
also packaged as `.zip` on Windows or `.tar.gz` on macOS/Linux. The Electron shell
opens the catalog in its own application window and manages its loopback-only Python
sidecar. It uses an automatic local user, so there is no account setup, password, or
sign-in screen; private parts lists stay in the current OS user's application-state
directory.

The bundle's `assets/` directory contains ordinary files grouped by product ID, then
into shallow `Images`, `Models`, `Archives`, `Documents`, and `Other` folders. Every
file keeps its original filename. If names collide, a short folder named after the
related source file separates them. The bundled SQLite database points to these named
files rather than to the archive's content-addressed blob tree. Keep `catalog.sqlite`
and `assets/` in the generated application directory. Use `--no-archive` to leave only
the unpacked app.

Prices are grouped by their storefront currency; the application performs no foreign
exchange conversion and excludes taxes and shipping. It also refuses to total legacy
prices whose currency does not match their region. Run a complete eight-region refresh
before treating regional totals as current:

```bash
uv run makers-supply sync --metadata-only --resume
uv run makers-supply validate --no-check-blobs
uv run makers-supply build-db
```

See [the web application guide](apps/catalog-web/README.md) for Docker deployment,
backups, administration, frontend development, and security details.

## Repository layout

- `data/products/*.json`: authoritative product records.
- `data/blobs/sha256/`: deduplicated source and extracted files, tracked by Git LFS.
- `data/runs/latest.json`: manifest from the most recent material update.
- `reports/latest.md`: human-readable update report.
- `config/aliases.json`: reviewed cross-region identity overrides.
- `config/categories.json`: reviewed deterministic catalog taxonomy and tag rules.
- `config/catalog_overrides.json`: explicit per-product classification overrides.
- `apps/catalog-web/`: deployable visual catalog and private parts-list service.

The SQLite file is reproducibly generated from JSON and attached to dated GitHub
releases; it is not committed on every update.

## Asset storage and limits

Git LFS must be installed and initialized as described above before running a binary
sync. The default preflight budget is 5 GiB total and 500 MiB per file:

```bash
git lfs install
uv run makers-supply lfs-preflight
```

GitHub LFS storage and bandwidth are quota-limited. Review `reports/latest.md`, the
preflight result, and your account quota before merging automated update pull requests.

Every storefront, image, CAD, archive, and document request uses the same conservative
per-host throttle. Request starts are separated by a two-second minimum plus up to one
second of random jitter by default; retries add exponential backoff and honor
`Retry-After`. Requests also enforce `robots.txt`, SHA-256 verification, MIME/signature
checks, and hardened ZIP extraction. A product is
tombstoned only after it is missing from every successfully checked region twice.

Sources that exceed the safety or LFS budgets remain in product metadata with an
explicit `rejection_reason` and no blob. Raster files whose CDN filename or declared
media type disagrees with their signature retain the official `original_filename`,
record the incorrect `declared_media_type`, and use the detected type and extension
for content-addressed storage. Archive, model, and document type mismatches are
rejected rather than reinterpreted.

## Automation

The reusable test workflow runs both Python suites, browser tests, linting, type checks,
full catalog validation, LFS preflight, and container startup/backup/restore checks.
The candidate workflow builds and tests four app targets against one shared snapshot
and creates an unpublished draft with checksums and evidence only after all checks pass.
It never publishes automatically. Every Sunday at 04:17 UTC, the sync workflow proposes
changes on `automation/catalog-sync`; it never auto-merges.

The archive retains third-party rights notices; the public mirror distribution policy
is recorded in [RELEASE.md](RELEASE.md).

See [CHANGELOG.md](CHANGELOG.md) for release history, [NOTICE.md](NOTICE.md) for
attribution, third-party rights, and takedown handling, and
[CONTRIBUTING.md](CONTRIBUTING.md) for development and identity-override guidance.

## Development

```bash
uv sync --all-packages --extra dev
uv run makers-supply --help
uv run pytest tests
uv run pytest apps/catalog-web/tests
uv run ruff check .
uv run mypy
```

Node.js 22 is needed only when changing the Three.js frontend or running browser
tests. It is not required to run the committed frontend bundle:

```bash
cd apps/catalog-web/frontend
npm ci
npm run build
npm run typecheck
npx playwright install chromium
npm run test:e2e
```

This project is independent and is not affiliated with or endorsed by Bambu Lab.
