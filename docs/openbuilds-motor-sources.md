# OpenBuilds stepper motor references

Reviewed 2026-11-17. These three STEP models come from **STEP Parts Library
1.5**, preserved unchanged in a community mirror at commit
`48a8a2bf44ef9818edc2f070c848417938816002` of
[`mirage335/templates-lib-OpenBuilds_STEP`](https://github.com/mirage335/templates-lib-OpenBuilds_STEP).
The original library attribution identifies OpenBuilds, LLC and CC BY-SA 4.0.
The catalog identifies the mirror and legacy library explicitly; it does not
present these as newly downloaded current storefront models.

| Legacy model | Body length | Shaft diameter | Shaft projection from mounting face | Mounting-hole pitch |
| --- | --- | --- | --- | --- |
| NEMA 17 | 48 mm | 5 mm | 24 mm | 31 × 31 mm |
| NEMA 23 | 56 mm | 6.35 mm | 20.6 mm | 47.14 × 47.14 mm |
| NEMA 23 High Torque | 86 mm | 6.35 mm | 20.6 mm | 47.14 × 47.14 mm |

Dimensions above describe the selected source models, not all motors in a NEMA
frame family. The NEMA 17 body face is approximately 42.42 × 42.42 mm; the two
NEMA 23 models have approximately 56.4 × 56.4 mm body faces. Shaft projection
is measured from the front mounting plane, including the boss, rather than
from the end of the boss.

All three files have genuine STEP AP203 headers with millimetre length units.
Source exports are dated 2015-07-29 for NEMA 17 and NEMA 23, and 2016-09-02
for NEMA 23 High Torque. These dates do not establish physical hardware
revisions. Body and shaft lengths were checked from referenced STEP vertex
coordinates; shaft diameters from circle radii; mounting pitch from the front
hole circle centres. This is bounded source-geometry evidence, not a physical
fit test or a full CAD-kernel validation.

Source paths are under
`_ref/OpenBuilds_STEP/orig/STEP Parts Library 1.5/6 - Electronics/`.
Original byte sizes are 136,992, 243,354 and 243,405 respectively. Reviewed
hashes, export timestamps, dimensions and immutable paths are recorded in
`tests/fixtures/suppliers/openbuilds-motors-reviewed-sources.json`.

The [original-library license notice](https://github.com/mirage335/templates-lib-OpenBuilds_STEP/blob/48a8a2bf44ef9818edc2f070c848417938816002/_ref/OpenBuilds_STEP/license.txt)
accompanies each model as a document. Its explicit OpenBuilds CC BY-SA 4.0
attribution governs these original library files; the mirror's GPL fallback
does not replace that notice. No geometry was modified. Attribution and
share-alike conditions remain recorded as `licensed` rights.

The current OpenBuilds storefront was unavailable during review. No current
SKU, purchasable variant, stock, price, torque, current or electrical rating
is inferred from an old model name. Check the chosen motor's datasheet,
mounting points, shaft flat and cable/connector clearances when designing
a printed mount.
