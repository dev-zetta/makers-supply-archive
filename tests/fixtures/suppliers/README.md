# Supplier parser fixtures

Reviewed 2026-11-17 from public manufacturer/store sources. These are reduced
responses: navigation, tracking and unrelated scripts are removed; response data
needed for parser and variant-exclusion tests is retained. Prices and availability
are snapshots for offline tests, never a fallback for a failed live refresh.

- `biqu-skr-mini-e3.json` and `.html`: https://biqu.equipment/products/btt-skr-mini-e3-v2-control-board (public `.js` response and ProductGroup JSON-LD). The separate DCDC5V module is intentionally retained to test exclusion.
- `biqu-cb2.json` and `.html`: https://biqu.equipment/products/bigtreetech-pi-2-cb2 (public `.js` and ProductGroup JSON-LD). Pi2, Lite, heatsink and microSD variants are intentionally retained to test exclusion.
- `waveshare-27478.html`: https://www.waveshare.com/3.4inch-800x800-lcd.htm (Product JSON-LD).
- `waveshare-29957.html`: https://www.waveshare.com/ESP32-S3-Touch-AMOLED-1.8.htm (configurable-product options and inline SKU data; this response contains no Product JSON-LD and no exact per-SKU price).

CAD source paths and commit revisions are in `config/supplier-pilots.json`. The
3.4-inch wiki returned 502 during this review. Its download URL was recovered from
a printed copy of the publisher wiki at
https://m.media-amazon.com/images/I/91yxIAkGHWL.pdf, then verified directly on
`files.waveshare.com`: the ZIP contains `3_4inch-800x800-lcd.stp`.

Original content remains the property of its rights holders. A public download
does not establish a CAD redistribution license; rights remain unknown unless
separate license evidence is recorded.
