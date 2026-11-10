# Changelog

This project uses Semantic Versioning beginning with `v1.0.0`. Development before
the first versioned release is summarized below by day from the original commit
history; those commits were consolidated into the `v1.0.0` release commit.

## v1.1.0 - Unreleased

- Added the login-free Electron desktop catalog and named portable asset layout.
- Added shared offline ZIP data packs, size caps, SHA-256 manifests, and installation
  diagnostics, retaining the bundled build mode.
- Fixed scoped synchronization losing unscanned regions and canonical content;
  limited scans no longer advance removal counters.
- Scoped resume caches to matching interrupted runs while retaining pages for backfill.
- Fixed Unicode and quoted/control-character list names in CSV/JSON downloads.
- Stabilized tombstone counters and excluded unlisted or unavailable offers from current totals.
- Included web unit tests in CI and gated draft assembly on full validation, fresh
  snapshot acceptance, and packaged-app tests on four desktop targets.
- Updated Electron within the 44.x series to resolve known runtime security advisories.

## v1.0.0 - 2026-08-26

### 2026-08-23 — Archive foundation

- Scaffolded the Python project, canonical catalog schema, validation, and reproducible
  SQLite database builder.
- Added regional storefront discovery and parsing, stable product identities, locale
  handling, incremental reconciliation, resumable synchronization, and update reports.
- Implemented conservative request throttling, retry and robots handling, safe asset
  streaming, signature validation, rejection records, resumable downloads, and hardened
  archive extraction.
- Published the initial multi-region metadata and mirrored-asset snapshots with Git LFS,
  then normalized categories, dimensions, lifecycle data, and variant pricing.
- Added weekly synchronization, validation, release automation, provenance and rights
  documentation, installation guidance, and LFS budget checks.
- Built the authenticated visual catalog, searchable product and asset views, model
  previews, saved parts lists, sharing, regional cost totals, container deployment, and
  web CI.
- Refined metadata-only synchronization, container access to archived assets, Docker
  build context, and the responsive catalog browsing experience.

### 2026-08-24 — Catalog enrichment and workflow

- Added remembered login sessions and a one-command local catalog launcher with
  persistent accounts, lists, and session secrets.
- Added direct product selection for parts lists and normalized deterministic display
  images while preserving source images and primary ordering.
- Introduced kit classification, normalized package contents, and verified links between
  bundles and cataloged components.
- Recovered cached CAD files and documents, grouped downloads by variant, and unified
  commerce details with product galleries.
- Backfilled official descriptions, specification tables, reviewed categories,
  variant-specific contents, related-link names, and component matches.
- Improved external product links, commerce-link normalization, model shading, layout,
  infinite browsing, expandable product details, and variant identifiers.
- Added reviewed package-content overrides, standalone battery contents, and a global
  storefront region switch.

### 2026-08-26 — Portable 1.0 release

- Replaced distro-specific setup instructions with an idempotent bootstrap script for
  Ubuntu, Debian, Arch Linux, and Fedora, including optional Docker installation.
- Added explicit Semantic Versioning across the archive and web packages and established
  this changelog for future releases.
