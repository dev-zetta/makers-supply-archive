# Contributing

Run `./setup.sh` once to install Python 3.12, `uv`, Git LFS, and the development
dependencies. Then use:

```bash
uv sync --all-packages --extra dev
uv run pytest
uv run ruff check .
uv run mypy
uv run makers-supply validate
```

Keep source fixes, collector changes, and generated data in separate commits. Never
commit credentials, cookies, `.staging/`, partial downloads, or generated SQLite files.

## Identity overrides

`config/aliases.json` maps a regional source identity to a stable product ID:

```json
{
  "eu:localized-product-handle": "ia005-power-distribution-board"
}
```

Add an override only after verifying that both pages describe the same physical product.

## Taxonomy and web application

Category and tag rules belong in `config/categories.json`; exceptional product assignments
belong in `config/catalog_overrides.json`. Rules must be deterministic, reviewable,
and based on stable identifiers or official names. Run `uv run makers-supply
backfill-metadata --check`, then promote with `uv run makers-supply
backfill-metadata`, and review the resulting product JSON. Do not infer or fabricate measurements: only
unambiguous official structured fields may become normalized measurements.
Included-item links must come from official product links, unambiguous part numbers,
exact normalized names, or a unique reviewed component-family signature.

Display-image changes belong in the deterministic processor, not manual blob edits.
Run `uv run makers-supply process-images` twice and confirm the second run creates no
tracked diff. Downloaded originals must remain referenced and unmodified.

Web changes must keep the generated catalog read-only and user state separate. Run
the Python suite plus the frontend build/typecheck and Playwright tests documented in
`apps/catalog-web/README.md` before committing.

## Source etiquette

Do not bypass authentication, anti-bot controls, or `robots.txt`. Keep the default
two-to-three-second randomized per-host interval unless a slower rate is required.
All binary downloads must use `ArchiveHttpClient`; do not add a direct HTTP path that
bypasses its throttle and retry policy. Scraper fixtures should be reduced examples
rather than full copies of product pages.
