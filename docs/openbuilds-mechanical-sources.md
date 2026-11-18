# OpenBuilds mechanical references

Reviewed 2026-11-17. The eight entries are legacy OpenBuilds design references,
not current storefront offers: four V-Slot profiles, C-Beam, two Delrin/POM wheels
and a standard 6 mm eccentric spacer.

## Source and attribution

The original STEP Parts Library 1.5, published by Rob Stehlik in 2017, is identified
by [OpenBuilds' resource page](https://builds.openbuilds.com/projectresources/step-parts-library.162/).
The reviewed catalog files are downloaded from the community-hosted
[`mirage335/templates-lib-OpenBuilds_STEP` mirror](https://github.com/mirage335/templates-lib-OpenBuilds_STEP/tree/48a8a2bf44ef9818edc2f070c848417938816002/_ref/OpenBuilds_STEP/orig/STEP%20Parts%20Library%201.5),
pinned at `48a8a2bf44ef9818edc2f070c848417938816002`.

Its [original-source license notice](https://github.com/mirage335/templates-lib-OpenBuilds_STEP/blob/48a8a2bf44ef9818edc2f070c848417938816002/_ref/OpenBuilds_STEP/license.txt)
explicitly identifies OpenBuilds, LLC, STEP Parts Library 1.5 and CC-BY-SA-4.0.
The notice distinguishes original OpenBuilds files from the mirror author's GPL
fallback; the catalog uses files under `orig/`, not community modifications.
Every product retains that notice as a document, source repository, commit,
path, rights evidence and OpenBuilds attribution. Models are marked `licensed`;
share-alike conditions are retained. No manufacturer endorsement of the mirror
or current revision compatibility is claimed.

All eight URLs returned STEP content with an `ISO-10303-21;` header. The selected
model files total 2,157,297 bytes. Their individual hashes, sizes and source headers
are retained in `tests/fixtures/suppliers/openbuilds-mechanical-reviewed-sources.json`.

## Geometry and material boundaries

| Entry | Source geometry | Boundary |
| --- | --- | --- |
| V-Slot 20×20, 20×40, 20×60, 20×80 | One 500 mm rail per profile | Fixed geometry; no other length or finish SKU is mapped |
| C-Beam 40×80 | One 500 mm rail | Fixed geometry; no end tapping or cut tolerance is inferred |
| Solid V Wheel, Delrin | Bare wheel, 23.90 mm OD × 10.20 mm width | No bearings, fasteners or kit contents |
| Delrin Mini V Wheel | Bare wheel, 15.23 mm OD × 8.80 mm width | Separate from the polycarbonate Xtreme variant |
| Eccentric Spacer | Standard 6 mm spacer, 5 mm bore | Separate from 6.35 mm and Mini Eccentric variants |

The [official OpenBuilds V-Slot overview](https://support.openbuilds.com/support/solutions/articles/65000167811-what-is-v-slot-)
establishes 6063-T5 aluminium for its rail family. Wheel materials and nominal
dimensions, and the spacer material and height, were checked against original
OpenBuilds PDF drawings mirrored by Botland at revision
`ae050c376202ed475d0f9b7d16f980e93e6c61b4`. Their URLs and hashes are in the source
evidence fixture and their links remain in the products' documentation.

The wheel drawings distinguish Delrin from polycarbonate using separate material
rows. Delrin is the selected hardware material for these entries; a STEP shape
alone does not establish material. The files come from `2 - Wheels`, not the
library's assembly folder. Bearing-seat tolerances, wheel preload, slot radii, mating hardware and physical fit still need verification against the chosen part.
