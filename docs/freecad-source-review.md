# FreeCAD drive reference review

Reviewed 2026-11-17 at FreeCAD/FreeCAD-library revision
`f5ca01cdcaa2f69b9295a6382719c2d90628780c`. These are community reference models,
not manufacturer products. Both exported STEP files are retained unchanged.

| Reference | Native document main sketch and pad | Attribution |
| --- | --- | --- |
| 2.5-inch SATA, 7 mm | 100.45 × 69.85 × 7 mm | MrFreez |
| 3.5-inch SATA | 147 × 102 × 26.1 mm | Артём |

Dimensions describe these particular models. They do not establish normative
form-factor limits, manufacturer tolerances, universal mounting compatibility,
or connector and cable clearances. In particular, the 3.5-inch model's 102 mm
width must be checked against the chosen drive's manufacturer drawing, and the
7 mm model must not stand in for taller 2.5-inch drives.

The 2.5-inch files were originally added by MrFreez in
[2a889007](https://github.com/FreeCAD/FreeCAD-library/commit/2a889007f65471fdfe57d405c0b4ee2dafe5fd4c),
then moved from `Electrical Parts/electronic-components/HDD` to
`Computing/Storage/HDD` in
[48e6d979](https://github.com/FreeCAD/FreeCAD-library/commit/48e6d979811068f9c1efcef80e3dc763bf2dc899).
The 3.5-inch files were added by Артём in
[d60afebc](https://github.com/FreeCAD/FreeCAD-library/commit/d60afebc96d60e7dbf5a5b5bcbe09ca4410bbf9e).
These authors are credited in each product's description and specifications.

The reviewed repository's
[LICENSE-Assets](https://github.com/FreeCAD/FreeCAD-library/blob/f5ca01cdcaa2f69b9295a6382719c2d90628780c/LICENSE-Assets)
explicitly covers every part and exported STEP under CC-BY-3.0. The 2.5-inch
native document also names CC-BY 3.0. The 3.5-inch native document instead has
an `All rights reserved` metadata value. That discrepancy is retained in the
product compatibility notes and source fixtures; the explicit repository asset
license is the recorded grant. These assets use `licensed`, retaining the
attribution requirement, and the original full license is attached as a document.

`tests/fixtures/suppliers/freecad-drive-source-review.json` records source file
hashes and author commit evidence. The native document excerpts retain the
license properties, base sketch coordinates, and pad height used to review
the dimensions. Tests check those excerpts and ensure reference products have
no invented manufacturer revision, model number, offer, SKU, or capacity.
