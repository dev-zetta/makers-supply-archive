# PC reference sources

Reviewed on 2026-11-17. The generic PSU records are documentation references
for case planning. They have no attached CAD, purchasable variants, offers, or
invented manufacturer part numbers.

| Record | Reviewed source | Body dimensions |
| --- | --- | --- |
| Generic ATX PSU reference | [Intel ATX12V 3.1, Figure 13-1](https://edc.intel.com/content/www/us/en/design/ipla/software-development-platforms/client/platforms/alder-lake-desktop/atx-version-3-0-multi-rail-desktop-platform-power-supply-design-guide/2.1a/atx12v-specific-guidelines-3-1/) | 150 mm rear-face width, 86 mm height, 140 mm reference depth. Product depths vary. |
| Generic SFX PSU reference | [Intel SFX12V 4.1 reduced-depth profile](https://edc.intel.com/content/www/us/en/design/ipla/software-development-platforms/client/platforms/alder-lake-desktop/atx-version-3-0-multi-rail-desktop-platform-power-supply-design-guide/2.1a/reduced-depth-top-mount-fan-physical/) and [Figure 14-6](https://edc.intel.com/content/www/us/en/design/ipla/software-development-platforms/client/platforms/alder-lake-desktop/atx-version-3-0-multi-rail-desktop-platform-power-supply-design-guide/2.1a/fan-requirements-required_2/) | 125 mm rear-face width, 100 mm depth, 63.5 mm body height. The illustrated fan adds a 17 mm projection. |

Both drawings belong to Intel's guide 2.1a, document 336521, dated 2023-11-01.
The SFX entry deliberately uses the reduced-depth profile: the guide's separate
“Standard SFX Profile” section depicts a different 100 mm wide, 125 mm deep
package. The source drawings remain linked rather than copied into the archive.

Body dimensions do not include every fan, grille, connector, cable bend or
airflow allowance. Select the physical PSU before fixing mounting holes and
clearances. The SFX reference does not represent SFX-L. Neither generic record
establishes electrical compliance or a vendor product's fit.

The catalog names, manufacturer field, `generic-reference` tag and reference-type
specification all identify these as generic entries. Stable IDs are
`generic-atx-psu` and `generic-sfx-psu`; imports add them without reassigning
existing manufacturer products or saved inventory links.
