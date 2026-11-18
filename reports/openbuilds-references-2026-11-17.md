# OpenBuilds motion reference verification

Verified 2026-11-17 against the local working tree based on `f58a41b`.
The preceding PC reference commit `f58a41bbdbf0a654f3a0f65e713ad438022e1d6a`
was pushed to GitHub main and its
[Test workflow passed](https://github.com/dev-zetta/makersfridge/actions/runs/44021651278).

## Added references

- V-Slot 20x20, 20x40, 20x60 and 20x80; C-Beam 40x80: five 500 mm STEP references.
- Solid V and Mini V Delrin/POM bare wheels, with bearings and kits distinguished.
- Standard 6 mm eccentric spacer.
- NEMA 17, NEMA 23 and NEMA 23 High Torque stepper models, with respective
  model body lengths of 48, 56 and 86 mm. Frame size does not establish another
  motor's body length, shaft, mounting details or electrical characteristics.

All eleven are explicitly named legacy CAD references from STEP Parts Library
1.5. Original files are pinned to community mirror
`mirage335/templates-lib-OpenBuilds_STEP` at
`48a8a2bf44ef9818edc2f070c848417938816002`. The original OpenBuilds attribution
and CC-BY-SA 4.0 notice accompany each STEP. No current storefront SKU, price,
stock, physical revision or electrical rating is inferred from a legacy model.

## Preservation and verification

- Catalog total: 418 products. All 407 pre-existing product JSON files matched
  the pre-import SHA-256 baseline byte-for-byte.
- The new saved-list regression retained the full existing Bambu item row,
  variant ID, quantity and notes through import/database rebuild, then saved
  an extrusion beside it and exported both references.
- Isolated full repeat import: zero network requests, no promotion, all 418
  product files unchanged. Two generated SQLite catalogs were byte-identical.
- All 22 new product asset links are hydrated without rejection: eleven STEP
  files plus the shared license notice, stored as twelve unique new blobs.
- Full blob validation passed. LFS preflight: 5,697 blobs, 5,246,459,689 bytes,
  below the existing 5 GiB limit; largest blob remains 77,627,469 bytes.
- Archive tests: 286 passed, one optional released-CLI CAD integration skipped.
  Web tests: 67 passed. Browser workflows: 22 passed. Packaged desktop: 1 passed,
  including previews, project export, restart persistence and sidecar shutdown.
- Ruff, strict mypy, TypeScript and frontend build passed. Independent code and
  security review found no blocking issues; minor documentation/tag cleanup and
  source-entity geometry regression evidence were completed.

The final local desktop executable is
`dist/standalone/makersfridge-openbuilds-20261117/makersfridge-linux-x86_64/makersfridge`,
labelled `working-tree-openbuilds-20261117`, containing 418 products and 6,020
named asset files. Its catalog snapshot matches the source working tree:
`2d2d4148902d5143dd89141f20e44bb1dd8676625f099d0c5104185aa7e37520`.
The new OpenBuilds changes are local and uncommitted; this is not a published release.
