# Noctua PC/NAS fan references

Reviewed 2026-11-17. These are manufacturer references for integrating purchased
fans into an enclosure, not generic fan models or printable replacement parts.

| Reference | Frame without pads | Envelope with pads | Mounting-hole pitch |
| --- | --- | --- | --- |
| [NF-A6x25 PWM](https://www.noctua.at/en/products/nf-a6x25-pwm/specifications) | 60 × 60 × 25 mm | 60 × 60 × 26 mm | 50 × 50 mm |
| [NF-A9 PWM](https://www.noctua.at/en/products/nf-a9-pwm/specifications) | 92 × 92 × 25 mm | 93 × 93 × 27 mm | 82.5 × 82.5 mm |
| [NF-A12x25 PWM](https://www.noctua.at/en/products/nf-a12x25-pwm/specifications) | 120 × 120 × 25 mm | 120 × 120 × 27 mm | 105 × 105 mm |
| [NF-A14x25 G2 PWM](https://www.noctua.at/en/products/nf-a14x25-g2-pwm/specifications) | 140 × 140 × 25 mm | 140 × 140 × 27 mm | 124.5 × 124.5 mm |

NF-A9 is the actual 92 mm product in the requested “90 mm class”; it must not
be represented as a 90 mm frame. All four selected products are the 12 V,
4-pin PWM versions. Model-family CAD filenames do not establish current
physical hardware revisions, variants, vendor stock or prices.

The STEP links were followed from each official product's Downloads tab. All
four ZIP downloads returned HTTP 200 using Maker's Fridge's normal archive HTTP
client. Each archive contains one `.stp` member with an `ISO-10303-21;` header
and the same original 1,950-byte `README.txt`. Source ZIP and member hashes,
filenames, sizes, specification URLs and download URLs are recorded in
`tests/fixtures/suppliers/noctua-reviewed-sources.json`. Keeping the ZIP and
extracting the README alongside the STEP retains the publisher's original
usage notice.

The [Noctua CAD policy](https://www.noctua.at/en/3d-cad-models) describes
external and mounting dimensions as representative, with modified impeller
and internal frame geometry. It permits reference, visualization and
integration uses, and excludes reproducing or commercializing the represented
fans or substantially similar products. It also excludes performance
simulation and 3D printing of these models. The original archive README omits
the website's explicit printing sentence, so both sources are linked and the
stricter published purpose is shown in the catalog.

The reviewed terms contain no express standalone redistribution prohibition,
but also provide no broad open-source or redistribution grant. Assets are
therefore marked `restricted` and link to the publisher's terms; they must
not be presented as permissively licensed or freely printable designs. An
enclosure designed around a purchased fan is an integration reference use.
Cable routing, connector clearance, fasteners, gaskets and the physical fan
still need to be checked for a particular build.
