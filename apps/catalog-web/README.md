# Maker's Supply visual catalog

This application is a server-rendered FastAPI browser for the archive. It keeps the
generated catalog SQLite database read-only and stores accounts, sessions, sharing,
parts lists, and captured prices in a separate writable SQLite database.

## Features and cost semantics

- Search names, IDs, SKUs, part numbers, descriptions, categories, specifications,
  dimensions, tags, and box contents, with category, region, availability, price,
  lifecycle, and asset filters.
- Browse a thumbnail gallery with keyboard navigation, a zoomable lightbox, and
  complete product provenance. Preview validated STL and 3MF files with a shaded,
  reflective Three.js viewer that preserves embedded STL/3MF colors, materials, and
  textures when present; STEP/STP and other files remain downloadable.
- Use normalized 800×800 display images in cards, galleries, and lists. The archive
  retains each exact source image and records the derived image's crop/resize
  provenance; title bars are removed only after a conservative border-color match.
- Compare regional variant prices, availability, identifiers, and official links in
  one table with concise display names. Identify project kits at a glance, read
  structured narrative descriptions, and browse included-item tables—including
  variant-specific kit quantities—with local catalog and official storefront links.
  Official storefront and related external links open in a separate browser tab.
- Browse models and documents grouped by an exact official variant part-number match;
  product-wide packages and files without an unambiguous match stay visibly shared.
- Select products directly from the searchable catalog with checkboxes, keep the
  selection across filters and pages, and add it to a populated list picker or create
  a new list from the selection drawer.
- Manage region-specific parts lists with variants, quantities, notes, price snapshots,
  CSV/JSON exports, and named-user viewer/editor sharing.
- Use a browser-session login by default or explicitly remember a trusted device for
  30 days. Session tokens are random and only their keyed hashes are stored.
- Display current and captured subtotals separately per currency. There is no FX
  conversion. Taxes, duties, discounts, and shipping are excluded. Unknown,
  unavailable, or region/currency-inconsistent lines are counted and excluded rather
  than treated as zero.

The app never edits authoritative product JSON or taxonomy configuration.

## Local operation

For the shortest Docker-based path from the repository root:

```bash
./scripts/run-catalog-web.sh
```

The launcher rebuilds the generated catalog, creates the first administrator only when
needed, and binds to <http://127.0.0.1:8000>. Accounts and lists remain in the
`makers-supply-catalog-state` Docker volume. The local session secret is created once
at `.state/catalog-web.secret`; preserving it is required for remembered logins to
survive restarts. Use `--detach`, `--port PORT`, or `--no-build`; see `--help` for
environment overrides and all options.

For native development, run `./setup.sh` from the repository root, then:

```bash
uv run makers-supply build-db
export MAKERS_SUPPLY_ROOT="$PWD"
export MAKERS_SUPPLY_CATALOG_DB="$PWD/dist/makers-supply.sqlite"
export MAKERS_SUPPLY_STATE_DB="$PWD/.state/catalog-web.sqlite"
export MAKERS_SUPPLY_SECRET_KEY="$(openssl rand -hex 32)"
export MAKERS_SUPPLY_SECURE_COOKIES=0
uv run makers-supply-web create-admin admin
uv run makers-supply-web serve --host 127.0.0.1 --port 8000
```

`MAKERS_SUPPLY_SECURE_COOKIES=0` is only appropriate for loopback HTTP. The default is
secure cookies. State migrations are forward-only and run automatically at startup;
`uv run makers-supply-web migrate` can apply them explicitly.

Unchecked login creates a browser-session cookie with a 14-day server-side ceiling.
Selecting **Remember me** creates a persistent cookie and matching server-side session
that expire after 30 days. Logging out revokes either kind immediately. Do not use the
remembered-login option on a shared device.

Administrators provision accounts without enabling public registration:

```bash
uv run makers-supply-web invite \
  --admin admin --base-url https://catalog.example.com
```

The command prints a one-use URL that expires in 24 hours; it sends no email.

## Docker deployment

First generate `dist/makers-supply.sqlite` on the host and ensure LFS objects are
present. The Compose configuration mounts the entire archive read-only so image and
model blob paths remain resolvable, while `catalog-state` is writable and persistent.

```bash
uv run makers-supply build-db
export MAKERS_SUPPLY_SECRET_KEY="$(openssl rand -hex 32)"
docker compose -f apps/catalog-web/compose.yml build
docker compose -f apps/catalog-web/compose.yml run --rm catalog-web \
  makers-supply-web create-admin admin
docker compose -f apps/catalog-web/compose.yml up -d
```

The container runs as UID 10001 with a read-only root filesystem and binds to host
loopback port 8000. Put an HTTPS reverse proxy in front of it and preserve
`X-Forwarded-Proto`. Do not expose plain HTTP, weaken the security headers, mount the
archive writable, or run multiple replicas against the same state database.

The health endpoint is `/healthz`; it returns success only when SQLite schema v5 is
readable. After catalog JSON changes, atomically regenerate the host database and
restart the service:

```bash
uv run makers-supply build-db --output dist/makers-supply.sqlite
docker compose -f apps/catalog-web/compose.yml restart catalog-web
```

## Backup, restore, and upgrades

Back up state with SQLite's online backup API from the running container volume:

```bash
docker compose -f apps/catalog-web/compose.yml exec catalog-web \
  python -c "import sqlite3; s=sqlite3.connect('/state/catalog-web.sqlite'); d=sqlite3.connect('/state/catalog-web.backup.sqlite'); s.backup(d); d.close(); s.close()"
```

Copy `/state/catalog-web.backup.sqlite` out of the volume and store it securely; it
contains account and private-list data. Test restores periodically. To restore, stop
the service, preserve the current database, copy the selected backup to
`/state/catalog-web.sqlite`, then start the service and verify `/healthz` plus a login.
Never restore while the application is running.

Before upgrades, back up state, fetch LFS objects, rebuild the catalog database, build
the new image, and start one instance. Forward migrations run during startup. Roll back
the image only together with the pre-upgrade state backup if a migration is involved.

## Frontend development and tests

Node.js 22 is only required to rebuild the committed browser bundle:

```bash
cd apps/catalog-web/frontend
npm ci
npm audit --audit-level=high
npm run build
npm run typecheck
npx playwright install chromium
npm run test:e2e
```

Playwright expects the app at `http://127.0.0.1:8000`, an `e2e-admin` account, and its
password in `E2E_PASSWORD`. GitHub Actions creates an isolated catalog/state pair and
runs the full login, search, detail, and list-creation flows automatically.

The generated `static/viewer.js` must be committed with its TypeScript source so the
application image never depends on a third-party CDN at runtime.

## Data and rights

Images and models remain content-addressed under `data/blobs/sha256/`; the web service
only exposes assets referenced by `(product_id, asset_id)` in the generated database.
Public mirroring does not establish redistribution rights. Rights, provenance,
non-affiliation, and takedown terms in the repository `NOTICE.md` apply equally to the
web interface.
