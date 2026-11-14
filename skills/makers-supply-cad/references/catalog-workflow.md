# Catalog commands and CAD handoff

Run `scripts/catalog.py --help` relative to the installed skill directory. The helper
requires Python 3.10+ and has no third-party dependencies. Commands return JSON on
stdout; operational failures return a nonzero status with a message on stderr.
It reads catalog data and creates only explicitly requested export directories.

## Catalog layouts

| Input to `--catalog` | Metadata source | Asset base |
| --- | --- | --- |
| Archive checkout | `data/products/*.json` (preferred over a generated DB) | Checkout root |
| Portable data directory | `catalog.sqlite` | Directory containing the database |
| SQLite file | The named database, opened read-only | Directory containing the database |

Use a portable database with the assets from the same release. A repository-generated
`dist/makers-supply.sqlite` has paths relative to the checkout, so use the checkout's
JSON instead. The writable parts-list/state SQLite database has a different purpose
and is not supported. No account, password, web session, or MCP server is needed.

## Search and inspect

```bash
python "$SKILL_DIR/scripts/catalog.py" --catalog "$CATALOG" search "bearing" --limit 5
python "$SKILL_DIR/scripts/catalog.py" --catalog "$CATALOG" search "EA028" --region eu
python "$SKILL_DIR/scripts/catalog.py" --catalog "$CATALOG" show ea028-high-performance-bearings
```

`search` returns `items`, `total`, and `limit`. All query terms must match searchable
metadata; this is literal matching rather than SQLite query syntax or semantic search.
`--region` narrows results and their offer/variant summaries to `us`, `eu`, `uk`, `ca`,
`au`, `jp`, `kr`, or `asia`. It does not refresh prices or guarantee stock.
`show` returns full product metadata, including inactive products when addressed by ID.
Product IDs are stable family identifiers; variant IDs are region-specific strings.

Assets include `availability` and, when safe and local, `local_path`. An available file
has not yet been fully hash-verified; export performs that check. Missing, rejected,
unsafe, or Git LFS pointer files cannot be exported. `rejection_reason` explains known
archive restrictions; a `source_url` alone does not mean a download was archived.

Measurements retain their label, `raw_value`, optional decimal `numeric_value`, `unit`,
`applies_to`, and provenance. Some products have useful dimensions only in specifications
or source tables. Neither product photographs nor a size-like filename establishes a
manufacturing dimension. Preserve the original precision and state any conversion.

## Verified export

```bash
mkdir -p ./references
python "$SKILL_DIR/scripts/catalog.py" --catalog "$CATALOG" \
  export PRODUCT_ID --asset-id MODEL_ASSET_ID --asset-id DRAWING_ASSET_ID \
  --output ./references/selected-hardware
```

Choose IDs from `show`; export does not choose a variant on the agent's behalf.
Repeated `--asset-id` selects multiple files. Each exported file retains its original
metadata and has a `package_path` in `manifest.json`. Hash and size verification
must succeed before the new output directory is published. A failed export removes
its temporary directory; it never replaces an existing destination. Files remain
ordinary files: archive members already extracted by the archive can be selected,
but selecting an archive exports the archive itself.
The parent of `--output` must exist; create the project's `references` directory
first (with `mkdir -p` on Linux/macOS or an equivalent Windows command).

Retain `product.json` and `manifest.json` beside the CAD project. Record the chosen
variant separately because files may apply to a whole product family. Avoid inferring
variant applicability solely from the presence of one model on a product page.

## Local hardware BOM

For a CAD project without an existing catalog parts list, save a project-local JSON
BOM alongside editable CAD source. These are suggested handoff fields, not a catalog
API or an import format:

```json
{
  "items": [
    {
      "product_id": "ea028-high-performance-bearings",
      "region": "eu",
      "variant_id": "COPY_EXACT_ID_FROM_SHOW",
      "part_number": "EA028",
      "quantity": 1,
      "quantity_unit": "pack",
      "physical_part_quantity": 2,
      "reference_manifest": "references/ea028/manifest.json",
      "design_parameters": {
        "radial_clearance_mm": 0.2
      },
      "assumptions": ["Clearance is a design choice pending a fit test"]
    }
  ]
}
```

Copy actual IDs into the BOM; do not leave the example placeholder. The clearance is
illustrative, not a recommended tolerance for every material or manufacturing process.
Verify pack contents for the chosen variant: the example means one pack containing
two bearings. Price purchasable packs and keep the physical count explicit.
When recording a price, retain currency, amount as a decimal string, and the offer's
`retrieved_at`; leave unavailable prices null. Sum only matching region/currency data.

## Existing catalog projects

The catalog UI can export a parts-list project ZIP containing `parts-list.json`,
`build-progress.json`, `products/*.json`, available design files, and `manifest.json`.
Use that export when the user already maintains a parts list. Its manifest uses
`status` (`included`, `excluded`, or `unavailable`) and `package_path`; inspect those
and verify hashes before CAD use. These ZIPs are distinct from this helper's
single-product export and are not accepted as `--catalog` inputs.

Keep the user's build status and completed quantities with the project. Use the
application's normal authenticated UI for requested list edits; the helper does not
write to user-state SQLite or bypass CSRF. `GET /api/products` is the web search
endpoint; there is no JSON product-detail endpoint or general JSON list-mutation API
in this implementation. Prefer the offline helper for agent reads.
