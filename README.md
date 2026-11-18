# Maker's Fridge

Your ingredients for the next build: parts, CAD models, design files, regional
pricing, and project parts lists in one place. Maker's Fridge uses `makersfridge`
as its package, command, and repository name.

The versioned archive catalogs Bambu Lab Maker's Supply alongside reviewed
BIGTREETECH, BIQU, Waveshare, Raspberry Pi, Espressif, Noctua, and OpenBuilds references,
plus generic PC fit references from the FreeCAD Parts Library and Intel's PSU
design guide. Canonical, reviewable JSON records are paired with content-addressed
files and a generated SQLite catalog.

The archive covers the official USA, EU, UK, Canada, Australia, Japan, Korea, and
Asia storefronts. It records links to related MakerWorld projects but does not mirror
those community project files.

## Installation

### Upgrading from Maker's Supply Archive

The project is now **Maker's Fridge** (`makersfridge`). After updating a checkout,
run `uv sync --all-packages --extra dev` to install the renamed commands and Python
packages. The CAD skill is now `makersfridge-cad`; copy that folder again when using
an installed skill. Published releases through v1.3.0 retain their original asset
filenames; see [RELEASE.md](RELEASE.md).

Existing `MAKERS_SUPPLY_*` web settings and desktop path overrides remain accepted;
`MAKERSFRIDGE_*` settings take precedence. The app reuses an existing desktop profile
when no new profile exists, retaining lists, build progress, secrets, and browser
storage. Browser preferences and selections move to the new storage keys on first
use, and existing sessions and region cookies remain readable. The Docker launcher
also reuses an existing default state volume and container. Back up user state with
the app closed before upgrading, as for any release.

### Setup

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
uv run makersfridge sync --metadata-only --region us
uv run makersfridge backfill-metadata
uv run makersfridge backfill-assets
uv run makersfridge process-images
uv run makersfridge validate
uv run makersfridge build-db
uv run makersfridge materialize ia005-power-distribution-board --output ./export
```

Run `uv run makersfridge --help` for all options. Synchronization occurs in
`.staging/`; validated results are promoted after validation. `--resume` preserves partial
downloads and verified pages from a matching interrupted run; completed runs start
fresh scans. Cached pages remain available for backfill. `--dry-run` leaves tracked
data unchanged, and `--max-products` is useful
for live smoke tests.

### Supplier pilots

The default `sync` command retains its existing Bambu regional behavior. Import the
reviewed supplier pilots separately, then rebuild the read-only catalog database:

```bash
uv run makersfridge sync --supplier bigtreetech --supplier biqu --resume
uv run makersfridge sync --supplier waveshare --resume
uv run makersfridge sync --supplier raspberry-pi --supplier espressif --resume
uv run makersfridge sync --supplier noctua --supplier freecad-library --supplier generic-pc --resume
uv run makersfridge sync --supplier openbuilds --resume
uv run makersfridge build-db
```

Use `--metadata-only` to collect metadata and download links, `--dry-run` to review
changes, or `--product-id btt-skr-mini-e3-v3-0` with its supplier for a focused import.
`--supplier all` runs Bambu and the pilot suppliers. Pilot offers represent their
global storefront and retain the source currency; they do not imply local shipping,
taxes, or physical stock owned by the user. Omit `--region` for pilot-only imports.

The reviewed mappings in `config/supplier-pilots.json` cover SKR Mini E3 V3.0,
original EBB36 CAN V1.0, CB2, original Hermit Crab, Waveshare 27478 (3.4inch round
HDMI LCD), and Waveshare 29957 (AMOLED 1.8 with battery). Separate modules,
successor revisions, Pi2/Lite boards, and unrelated options are excluded. Original
EBB36/Hermit Crab models are reference-only entries with no current sales offer.
Unconfirmed hardware/model revision compatibility is labeled explicitly. The
configurable AMOLED page does not establish a per-SKU price, so that price remains
unknown. Supplier availability never changes saved list quantities or build progress.

Additional reviewed sources in `config/supplier-sources/` cover Raspberry Pi 5,
Pi 4 Model B, Pico, Pico W, Pico 2, and Pico 2 W; Espressif ESP32-WROOM-32E,
ESP32-S3-WROOM-1, ESP32-C3-MINI-1, ESP32-C6-WROOM-1, ESP32-DevKitC V4, and
ESP32-S3-DevKitC-1 v1.1; and Waveshare ESP32-S3-Zero, ESP32-S3-Touch-LCD-4.3,
RP2040-Zero, and RP2350-Zero. ESP32 is a device family: search finds both Espressif
modules and Waveshare boards while supplier filters retain each board's manufacturer.

Pi 5, Pico, Pico W, Pico 2, the four Espressif modules, and the four added Waveshare
boards have verified STEP models. Pi 4 and the two Espressif DevKit entries have
dimensional drawings; Pico 2 W has documentation only. A module model is never
substituted for its development board, and a non-wireless Pico model is never
assigned to Pico 2 W. These reference entries have no inferred reseller price,
stock status, or memory/header variant SKU.

The PC/NAS set adds official Noctua NF-A6x25 PWM (60 mm), NF-A9 PWM (92 mm,
the requested 90 mm class), NF-A12x25 PWM (120 mm), and NF-A14x25 G2 PWM
(140 mm) STEP references. Frame size, padded envelope, and mounting-hole pitch
are separate specifications. Noctua's CAD and original README usage terms are
retained as restricted manufacturer references for integrating purchased fans.
See [the fan source review](docs/noctua-source-review.md).

The FreeCAD Parts Library provides generic 2.5-inch SATA (7 mm) and 3.5-inch
SATA STEP models, pinned to a reviewed commit with CC-BY 3.0 license evidence
and author attribution. Generic ATX and SFX PSU entries link to Intel's mechanical
drawings and record body dimensions; they are documentation-only references,
with no downloadable PSU CAD. All four generic entries have a visible **Generic
reference** badge and names that retain that distinction in saved lists. Check
actual hardware and cable/connector clearances before a fit-critical design.

The OpenBuilds set adds four V-Slot extrusion profiles (20x20, 20x40, 20x60,
20x80) and C-Beam 40x80, each represented by a 500 mm STEP model; Solid V and
Mini V Delrin/POM wheels; a 6 mm eccentric spacer; and NEMA 17, NEMA 23 and
NEMA 23 High Torque stepper models. These are legacy CAD references from the
original STEP Parts Library 1.5, retrieved from a pinned community mirror with
the original attribution and CC-BY-SA 4.0 notice. They are labeled as legacy
references, with no inferred current storefront SKU, price or stock. Source
motor body lengths and shaft dimensions describe those particular models;
a NEMA frame designation does not establish another motor's body length,
electrical ratings, shaft, connector or cable clearances. Extrusion CAD length
does not imply compatibility with every current rail SKU. See the
[mechanical source review](docs/openbuilds-mechanical-sources.md) and
[motor source review](docs/openbuilds-motor-sources.md).

The maker starter sets cover Linear Motion & Transmission, Connectors & Panel
Controls, Power & Battery Hardware, Sensors & Breakout Boards, Enclosure &
Assembly Hardware, and Robotics & Small Actuators. Find them using the category
filter or search by manufacturer part number. Each reference links to its source
and lists the dimensions or variant details relevant to fit. Verified CAD files
and drawings appear in Downloads. When a manufacturer publishes a combined CAD
library, the reference links to that library and identifies the matching member
where the source establishes the mapping.

The source manifest's relative JSON includes keep reviewed manufacturer sets
separate. Included files are confined to the configuration directory; duplicate
IDs and cyclic includes fail validation. Resume fingerprints cover every included
file, and changes to reviewed source definitions during import prevent promotion.

Adapters normalize official structured storefront data and reviewed CAD links.
GitHub models are pinned to a repository commit and path. Assets carry SKU
applicability, revision, role, source, hash, and license evidence; a public download
does not establish redistribution permission. Unknown rights remain `unknown`.
Explicit MIT-style grants use `permissive`; condition-bearing grants use `licensed`
and retain their license source. Espressif KiCad library models retain their
CC-BY-SA 4.0 notice and KiCad exception. Included ZIP `LICENSE`, `COPYING`,
`NOTICE`, and `README` files are preserved as documents alongside extracted CAD; macOS
AppleDouble files are ignored after archive safety checks.
Supplier imports write only selected product records, preserving existing Bambu JSON,
product IDs, and saved references. An incomplete or failed import does not retire
products from any supplier. Bambu-specific reconciliation and backfills stay scoped
to Bambu records.

Interrupted pilot imports can resume verified cached pages and partial downloads;
completed runs fetch fresh product metadata. Existing CAD bytes are reused by
default. Use `--refresh-assets` with a pilot supplier to check mutable download URLs
again; this requires binary downloads and also replaces extracted members. Crawling
honors published delay/rate rules, including Waveshare's one request per minute.
ZIP extraction uses the existing size, traversal, symlink, and compression limits;
RAR/7z files are retained as archives without automatic extraction.

The catalog supplier filter works with search, categories, region, and view choices.
Global offers and reference-only parts remain visible from regional views. STEP/STP
originals can be downloaded, included in project exports, and used by CAD tools;
in-browser previews currently support STL and 3MF.

`backfill-assets` audits official pages retained in `.staging/pages` for CAD archives,
direct models, PDFs, and other downloadable files that an older parser missed. It is
discovery-only by default; review the count, then archive through the normal validated
pipeline with `uv run makersfridge backfill-assets --download --resume`. A product can
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
uv run makersfridge build-db
export MAKERSFRIDGE_ROOT="$PWD"
export MAKERSFRIDGE_CATALOG_DB="$PWD/dist/makersfridge.sqlite"
export MAKERSFRIDGE_STATE_DB="$PWD/.state/catalog-web.sqlite"
export MAKERSFRIDGE_SECRET_KEY="$(openssl rand -hex 32)"
export MAKERSFRIDGE_SECURE_COOKIES=0
uv run makersfridge-web create-admin admin
uv run makersfridge-web serve
```

The insecure-cookie setting is only for loopback HTTP.
Deployments must keep secure cookies enabled and terminate HTTPS in a reverse proxy.
Unchecked login uses a browser-session cookie; “Remember me” persists a hashed server
session and cookie for 30 days. Changing `MAKERSFRIDGE_SECRET_KEY` invalidates all
existing sessions.
Use `uv run makersfridge-web invite --admin admin --base-url https://catalog.example`
to create a single-use, 24-hour invitation URL. Open registration and email delivery
are intentionally absent.

### Standalone local app

A portable, login-free edition can be built for Windows, macOS, or Linux without
shipping Python, `uv`, Node.js, or Docker to the end user. Builds are native: run the
command on each target operating system and CPU architecture after pulling the Git LFS
objects:

```bash
npm --prefix apps/catalog-desktop ci
uv run --package makersfridge-web --extra standalone \
  python scripts/build-standalone.py
```

Official downloads contain one platform app plus shared ZIP data packs. Extract the
app and **every** data pack from the same release into one directory. Every pack is
at most 1,800,000,000 bytes. See [RELEASE.md](RELEASE.md) for checksums, platform support,
unsigned-build prompts, installation, upgrades, and release acceptance.

The default local build remains bundled. Use `--layout split` to build only the app,
and `uv run python scripts/build-data-packs.py --revision "$(git rev-parse HEAD)"`
to generate shared data. No Python or other development tools are needed by end users.

The result is written to `dist/standalone/makersfridge-<platform>-<arch>` and
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
uv run makersfridge sync --metadata-only --resume
uv run makersfridge validate --no-check-blobs
uv run makersfridge build-db
```

See [the web application guide](apps/catalog-web/README.md) for Docker deployment,
backups, administration, frontend development, and security details.

## AI agents and CAD

The portable [Maker's Fridge CAD skill](skills/README.md) lets Codex, Claude Code,
and other Agent Skills clients find hardware, inspect exact variants and source
dimensions, and export verified reference files with provenance for CAD projects.
It works offline with a checkout or an extracted portable catalog and includes
guidance for Chili3D, SolidCraft, Extrudo, build123d, CadQuery, FreeCAD, and OpenSCAD. See the
guide for installation, example prompts, and the dependency-free JSON command interface.

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
uv run makersfridge lfs-preflight
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
uv run makersfridge --help
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
