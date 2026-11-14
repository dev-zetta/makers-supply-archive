# Executed Extrudo example: EA028 bearing housing

This optional example runs the complete catalog-to-CAD workflow, using an existing
Extrudo source checkout. It was executed on 2026-11-14 with **Extrudo 0.10.0**, source
revision `9631a7071b17014af4bb366fc521d4c74a93aa86`, Node 24.14.1 and Extrudo's
downloaded matching OCCT/sketch WASM engines. Its native design also opened and
recomputed successfully in the Extrudo web app. Desktop MCP was not exercised.

The example is specifically for the catalog's EA028 608ZZ bearing and EU two-piece
pack. It checks the local source table, variant and exported file before modeling;
adapt it explicitly for a different product rather than substituting an asset ID.
The catalog helper remains Python-only; Node/Extrudo are optional dependencies
for this example.

## Runtime

Use an existing Extrudo checkout, or obtain the upstream source separately. Do not
assume that `@extrudo/api` or a global `extrudo` executable is published. In that
checkout, prepare the source runtime as its [CLI guide](https://github.com/zoltanf/extrudo/blob/main/docs/cli.md)
describes:

```bash
pnpm install --frozen-lockfile --ignore-scripts
pnpm wasm
```

The install and WASM preparation require network access. Running the example after
preparation is offline and does not require Docker, a browser or an MCP server.
Use Node 24+ and the package manager supported by that checkout. The test used pnpm
11.25.0; the checkout's `packageManager` declares pnpm 12.6.0. Record the revision
actually used, because these are source entrypoints rather than a stable npm API.

## Run from any CAD project

Set `SKILL_DIR`, `CATALOG` and `EXTRUDO_SOURCE` to absolute local paths. Select and
inspect the hardware before exporting the example's known STEP asset:

```bash
python "$SKILL_DIR/scripts/catalog.py" --catalog "$CATALOG" search EA028 --region eu
python "$SKILL_DIR/scripts/catalog.py" --catalog "$CATALOG" show ea028-high-performance-bearings
mkdir -p ./references ./cad
python "$SKILL_DIR/scripts/catalog.py" --catalog "$CATALOG" \
  export ea028-high-performance-bearings \
  --asset-id model-3f4ff15eee8cf265bc90 --output ./references/ea028
node "$SKILL_DIR/scripts/extrudo_bearing_housing.mjs" \
  --extrudo "$EXTRUDO_SOURCE" --reference ./references/ea028 --output ./cad/ea028-housing
```

Both output directories must be new and their parents must exist. An existing
destination is not overwritten. The script resolves the actual STEP path from
`manifest.json`, checks containment, size and SHA-256 again, and keeps source URLs,
rights and archive ancestry in the BOM. It does not install or modify Extrudo.

## Result

| File | Purpose |
| --- | --- |
| `bearing-housing.extrudo` | Editable parameters and timeline, with both purchased-bearing solids embedded and placed |
| `housing.step`, `housing.stl`, `housing.3mf` | Housing only, excluding reference hardware |
| `clearance-0.4.extrudo` | Recomputed, saved parameter variant with 0.4 mm diametral clearance |
| `hardware-bom.json` | Exact regional variant, purchase/physical/spare counts and source information |
| `validation.json` | Geometry, export/reimport, parameter-change and interference evidence |
| `preview-meshes.json` | Actual recomputed meshes, available for visualization |

Open `bearing-housing.extrudo` through Extrudo's Import control. Wait for three
bodies and ten features to finish computing, then use Fit to frame the assembly.
The native file carries its STEP attachment, so the app does not need a path back
to the catalog. Parameter edits in the app retain the normal editable timeline.

## Dimensions and validation

The vendor EA028 source-table row specifies **8 mm bore, 22 mm OD, 7 mm width**.
Normalized `measurements` can be empty; the script retains the source table's
provenance. The selected EU variant is a two-bearing pack: this housing uses one
bearing, purchases one pack and leaves one spare.

Prototype design choices:

| Feature | Dimension |
| --- | --- |
| Mounting plate | 44 × 32 × 4 mm |
| Boss above plate | Ø30 × 8 mm |
| Bearing seat | Ø22.2 × 7.2 mm deep |
| Shaft/inner-race relief | Ø18 mm through |
| Mounting holes | Four Ø3.4 mm, centered at `(±17, ±10)` mm |

The clearance parameter is **diametral**: 0.2 mm gives 0.1 mm radial allowance.
The shoulder is at z=4.8 mm; the bearing reaches z=11.8 mm, leaving 0.2 mm top recess.
These allowances are example design choices, not vendor tolerances or a universal
printing recommendation. This open-top prototype has no axial retainer; physical
fit, retention, material and loading must be evaluated for a practical design.

The executable checks zero feature errors/warnings, one housing solid, expected
44 × 32 × 12 mm bounds and analytic volume **7133.203766332575 mm³**, plus zero
assembly interference. It exports closed meshes, reimports STEP and checks body
count/volume/bounds, and changes a parameter to prove recomputation. A negative
control with -0.2 mm diametral clearance must detect bearing/housing overlap;
it is tested in memory and is not emitted as a manufacturing file.

The actual source STEP is X-axis oriented and imports as two solids. The example
first measures all imported bodies, then rotates them -90° about Y and translates
them onto the shoulder. Centering alone is insufficient. The original source bytes
remain unchanged. See the [tool handoff notes](cad-tools.md#extrudo) for attachment,
MIME and export-selection integration details.

The script writes export hashes for identity, not as a promise of deterministic
STEP bytes: STEP header timestamps can change between otherwise equivalent runs.
Inspect geometry and mesh closure in addition to file hashes.
