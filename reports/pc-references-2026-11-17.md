# PC/NAS reference expansion verification

Verified 2026-11-17 against the local working tree based on `31266a8`.

## Imported references

- Noctua NF-A6x25 PWM, NF-A9 PWM, NF-A12x25 PWM and NF-A14x25 G2 PWM:
  official STEP archives and original README usage terms. The requested 90 mm
  class is the actual 92 mm NF-A9. Nominal frames and padded envelopes are separate.
- FreeCAD Parts Library generic 2.5-inch SATA (7 mm) and 3.5-inch SATA models:
  unchanged STEP files pinned to `f5ca01cdcaa2f69b9295a6382719c2d90628780c`,
  author credits and original CC-BY-3.0 asset license. The 3.5-inch source model's
  102 mm width is disclosed as model geometry requiring physical fit verification.
- Generic ATX and SFX PSU documentation references linked to Intel's mechanical
  drawings. No PSU CAD, vendor SKUs, prices or stock are inferred.

All four generic references retain that distinction in their names, manufacturer,
tags, specifications and visible catalog/detail badges. Fit guidance appears in
its own panel so it does not crowd the description and saved-list controls.

## Preservation and repeatability

- 407 products after adding eight; all 399 existing product JSON files matched
  their pre-import SHA-256 hashes byte-for-byte. No existing variant IDs changed.
- The mixed-list regression retained an existing Bambu variant ID, quantity and
  notes after the supplier import and database rebuild, then saved Noctua and
  generic drive entries alongside it and exported the list.
- An isolated, full repeat PC import made zero network requests, promoted no
  changes, and preserved all 407 product files byte-for-byte.
- Full blob validation passed; two generated SQLite catalogs were byte-identical.
- LFS preflight: 5,685 blobs, 5,243,676,084 bytes, below the existing 5 GiB limit.
  Twelve new blobs include six STEP models, four ZIPs and two source documents.

## Checks

| Check | Result |
| --- | --- |
| Archive Python suite | 269 passed, one optional released-CLI CAD integration skipped |
| Web Python suite | 65 passed |
| Browser workflows | 21 passed, including generic labels and description-control separation |
| Packaged desktop workflow | 1 passed: isolated state, model previews, project ZIP export, restart persistence and sidecar shutdown |
| Ruff, strict mypy, TypeScript, frontend build | Passed |
| Independent code and security review | No actionable findings |

The final launchable Linux desktop build is
`dist/standalone/makersfridge-pc-references-20261117-final/makersfridge-linux-x86_64/makersfridge`,
labelled `working-tree-pc-references-20261117`, with 407 products and 5,998 named
asset files. This is a local working-tree build, not a published release.
