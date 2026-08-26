# Maker’s Supply Archive

## Summary

Create `makers-supply-archive`, a Python 3.12 project containing:

- A versioned, multi-region database of every Bambu Lab Maker’s Supply product.
- Original gallery images, CAD/model archives, manuals, and other public downloads in Git LFS.
- Safely extracted STEP/STL/3MF/DXF files.
- A typed CLI for synchronization, validation, querying, and materializing product assets.
- Reviewable JSON as the source of truth and a generated SQLite database for releases.
- Weekly GitHub Actions updates through a reviewable pull request.

The archive covers Maker’s Supply products, kits, electronics, hardware, tools, and bundles. Linked community MakerWorld projects are recorded but their files are not mirrored.

## Data Model and Interfaces

- Store normalized records under `data/products/<stable-id>.json`.
- Assign each product a persistent internal ID. Reconcile regions using official part numbers/SKUs and explicit aliases; ambiguous matches remain separate and are reported for manual resolution.
- Record:
  - Product name, description, categories, specifications, box contents, part numbers, SKUs, variants, tags, and related MakerWorld links.
  - Regional offers for USA, EU, UK, Canada, Australia, Japan, Korea, and Asia: URL, currency, price, availability, Shopify identifiers, and retrieval time.
  - Assets with source URL, original filename, media type, SHA-256, size, retrieval time, license/rights status, parent archive, and extracted member path.
  - Lifecycle fields such as first/last seen, active status, and removal time.
- Deduplicate binaries in `data/blobs/sha256/<prefix>/<hash>.<ext>` and track that tree with Git LFS.
- Keep exact source packages and extracted supported files. Reject path traversal, symlinks, archive bombs, excessive expansion, and misleading file extensions.
- Generate a deterministic SQLite catalog from JSON for releases; JSON remains authoritative.

Expose these CLI commands:

- `makers-supply sync`: staged, resumable multi-region synchronization with region filters, metadata-only mode, dry-run, rate limits, and bounded retries.
- `makers-supply validate`: schema, references, hashes, extraction provenance, LFS coverage, and regional consistency checks.
- `makers-supply build-db`: generate SQLite from the committed JSON dataset.
- `makers-supply materialize <product-id>`: reconstruct a product’s assets using their original filenames and archive paths.
- `makers-supply diff`: summarize additions, changes, removals, regional offer changes, and asset replacements.

## Implementation

- Use `uv`, Typer, Pydantic, HTTPX, HTML parsing, Ruff, mypy, and pytest.
- Discover products from each official Maker’s Supply collection/API or sitemap, then parse product JSON and HTML documentation links. Use conditional requests, an identifiable user agent, conservative per-host throttling, exponential backoff, and `robots.txt` enforcement.
- Perform every sync in an ignored staging directory. Only replace the tracked snapshot after all requested regions and assets pass validation; failed runs leave the previous dataset untouched.
- Treat a product as removed only after it is absent from every successfully scanned region for two consecutive complete runs. Failed region scans never advance removal counters.
- Never silently delete history. Current records reference current assets, while replaced records and LFS objects remain recoverable through Git history.
- Produce a machine-readable run manifest and Markdown change report. A second sync against unchanged sources must create no tracked diff.
- Run weekly on Sunday through GitHub Actions. The workflow creates or updates an `automation/catalog-sync` pull request, includes the change report, and never auto-merges. On merge to `main`, publish the generated SQLite database and checksums as a dated GitHub release.
- Add LFS size preflight checks and clearly document GitHub LFS bandwidth/storage requirements.
- License original code under MIT. Explicitly exclude Bambu Lab names, images, CAD, documentation, and other mirrored third-party content from that license; include attribution, provenance, non-affiliation, and takedown documentation. Public downloads will be mirrored as requested, while `rights_status` remains `unknown` unless an explicit license is found.

## Test and Acceptance Plan

- Fixture tests for collection discovery, localized product pages, variants, specification tables, image selection, and documentation links.
- Reconciliation tests for shared SKUs, renamed handles, conflicting identities, and manual alias overrides.
- Download tests for retries, redirects, conditional requests, interrupted downloads, hashes, MIME detection, and deduplication.
- Archive-security tests for ZIP traversal, symlinks, nested archives, corrupt files, size limits, and duplicate members.
- Multi-run integration tests covering new products, changed metadata, regional price changes, replaced assets, transient region failures, and two-run tombstoning.
- JSON Schema/Pydantic validation and SQLite-versus-JSON parity tests.
- An opt-in live smoke test against one official product, isolated in a temporary directory.
- Initial population is accepted when all eight official storefronts complete, every referenced blob validates, `materialize` reconstructs representative products, SQLite matches JSON, and an immediate repeat sync is clean.

## Commit Sequence

1. `chore: scaffold makers supply archive`
2. `feat: define catalog schema and sqlite builder`
3. `feat: discover and parse regional supply catalogs`
4. `feat: archive and safely extract product assets`
5. `feat: add incremental sync reconciliation and reports`
6. `ci: validate and propose weekly catalog updates`
7. `docs: document usage provenance rights and takedowns`
8. `data: add initial makers supply metadata snapshot`
9. `data: add initial mirrored asset archive`

Each commit must be internally coherent and pass the applicable tests before proceeding. Credentials, temporary downloads, and incomplete staging data are never committed.

## Assumptions

- The project starts in the existing empty Git repository on `main`; it currently has no commits or remote.
- The initial official regional set is USA, EU, UK, CA, AU, JP, KR, and Asia, matching Bambu Lab’s current store selector and [shipping-region documentation](https://bambulab.com/en/support/buying-guide?id=1013579805858963456&page=1).
- Storefront product pages are the discovery and metadata source; public Bambu CDN links are the asset source. A representative page currently exposes a downloadable 3D-model ZIP and application instructions directly from its [Documentation section](https://us.store.bambulab.com/products/makers-s-supply-electronics-bundle?id=43010848948360).
- Mainland China is excluded from v1 because it uses a separate storefront/platform rather than the eight-store interface; it can be added later as a dedicated adapter.
- Public mirroring does not itself establish redistribution rights. The repository will accurately preserve rights status and support takedowns, but the owner should obtain legal review or Bambu authorization before broadly promoting the populated public mirror.
