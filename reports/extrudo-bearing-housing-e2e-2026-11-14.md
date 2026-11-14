# Extrudo bearing-housing end-to-end test — 2026-11-14

The skill ZIP was subsequently rebuilt with SolidCraft support. Its current
identity is recorded in `reports/solidcraft-desktop-mcp-e2e-2026-11-14.md`; the
evidence and package identity below describe this earlier Extrudo-specific run.

**Passed:** the skill selected and verified a real EA028 catalog bearing, modeled
a parameterized housing with Extrudo's actual geometry kernel, exported usable
files, and opened the native assembly in Extrudo's web app. Integration findings
are fixed in the skill's executable example and instructions.

## Runtime and reproducibility

- Official source: <https://github.com/zoltanf/extrudo>.
- Extrudo 0.10.0, revision `9631a7071b17014af4bb366fc521d4c74a93aa86`.
- Node 24.14.1, pnpm 11.25.0, frozen dependency lockfile and matching upstream
  OCCT/sketch/OpenSCAD WASM downloads in an isolated `/tmp` source checkout.
- Actual modeling used Extrudo's source API, storage and headless CLI library;
  geometry recomputed in OCCT, rather than stopping at document construction.
- Native-file UI verification used the same revision's local web app. The app
  computed all **10 features and 3 bodies**, displayed the seated bearing and
  saved the imported design. The temporary web server was stopped afterward.
- No desktop MCP session was connected; that particular transport remains untested.

The reusable runner is
`skills/makers-supply-cad/scripts/extrudo_bearing_housing.mjs`; complete commands
are in `skills/makers-supply-cad/references/extrudo-e2e.md`. It has no dependency
on this machine's paths and takes explicit source-runtime, reference and output
directories. CAD execution requires the external Extrudo source runtime.

## Catalog input

| Field | Verified value |
| --- | --- |
| Product | `ea028-high-performance-bearings` |
| Regional variant | EU `48795653767516`, EA028 608ZZ P5 Steel (2PCS) |
| Source dimensions | 8 mm bore × 22 mm OD × 7 mm width |
| Provenance | `source_tables[0]`, `table:0`, retained US official product-page URL |
| Asset | `model-3f4ff15eee8cf265bc90`, `608ZZ P5 - EA028.stp` |
| Source bytes | 116,193 |
| Source SHA-256 | `aeabc6c29cf32455b634f805e92e9f9ffb41d143d911a635c68d0034b7d288cf` |
| Rights | `unknown`, retained in the hardware BOM |

The catalog helper exported this exact selected asset. The CAD runner verified its
size and SHA-256 again before importing it. Normalized measurements are empty;
dimensions came from the exact EA028 source-table row, not a generic 608 assumption.
Independent OCCT inspection confirmed cylindrical radii of 11 mm and 4 mm and
the 7 mm width. The source STEP declares millimetres, but its bearing axis is X.

## Housing and geometry evidence

The modeled prototype has a 44 × 32 × 4 mm mounting flange, Ø30 × 8 mm boss,
Ø22.2 × 7.2 mm bearing seat, Ø18 mm through relief, and four Ø3.4 mm mounting
holes at `(±17, ±10)` mm. Housing dimensions and fit allowances are explicitly
design choices, separate from vendor dimensions.

| Check | Result |
| --- | --- |
| Native feature/document checks | Zero errors, zero warnings, no attachment notices |
| Housing topology | One connected solid |
| Exact bounds | `[-22,-16,0]` to `[22,16,12]` mm |
| Exact housing volume | 7133.203766332574 mm³ |
| Independent analytic volume | 7133.203766332575 mm³ |
| Reference import | Two valid solids, volumes 938.0812230494548 and 461.6404491319798 mm³ |
| Bearing placement | Both reference solids span z=4.8..11.8 mm |
| Default interference | None |
| Manufacturing exports | Housing only, excluding both reference solids |
| STEP round trip | One solid, matching volume and bounds, zero errors/warnings |
| Parameter edit | 0.4 mm diametral clearance recomputed to its changed analytic volume; saved native variant reopened successfully through CLI |
| Negative control | -0.2 mm diametral clearance detected 46.16183449768778 mm³ overlap |
| STL | 4,200 triangles; every one of 6,300 welded edges shared by exactly two triangles |
| Independent STL mesh volume | 7133.220186558981 mm³; positive and within 0.01642 mm³ of exact solid volume |
| Web app | Native assembly imported, recomputed, and rendered; screenshot retained |

The default 0.2 mm diametral allowance is 0.1 mm radially. The bearing touches
its supporting shoulder, so nearest-body distance can be zero without overlap.
The negative control demonstrates that the overlap test detects an incorrect fit.
It is evaluated in memory and is not exported as a manufacturing model.

An independent agent reran the entire integration in a separate `/tmp` output
directory and independently parsed the STL. STL and 3MF bytes matched across runs;
STEP header timestamps changed, so equivalent STEP geometry is checked rather
than requiring identical file hashes.

## Integration fixes

1. Register STEP as a design attachment and import by its ID; a filesystem path
   is not the import feature's input.
2. Map catalog `application/p21` to Extrudo attachment `model/step`, retaining
   the original catalog metadata in the provenance handoff.
3. Serialize attachment bytes with `writeArchive`; `Design.toFile()` alone does
   not carry them. Reopening the native file verifies it is self-contained.
4. Import/recompute before enumerating bodies, then rotate and place **both**
   solids. Centering alone leaves this model on the wrong mounting axis.
5. Resolve source-workspace modules by absolute file URLs and register Extrudo's
   TypeScript resolver, allowing the installed skill to run outside its pnpm tree.
6. Select `Housing` explicitly for STEP/STL/3MF export.
7. Check body overlap independently of shoulder-contact distance and test a
   deliberately undersized seat.
8. Resolve reference-file realpaths before containment checks and refuse existing
   output, including dangling symlinks. Both failure cases were exercised before
   runtime initialization. Avoid a subprocess dependency on Git for CAD execution.

## Artifacts and checks

Local project: `dist/agent-cad/ea028-extrudo-e2e/`.

- `model/bearing-housing.extrudo`: editable assembly with embedded bearing STEP.
- `model/housing.step`, `.stl`, `.3mf`: manufacturing/reference housing exports.
- `model/clearance-0.4.extrudo`: editable recomputed clearance variant.
- `model/hardware-bom.json`: one purchased two-bearing pack, one installed bearing,
  one spare, plus exact variant, source-table provenance and asset rights.
- `model/validation.json`: computed measures, export hashes, round-trip and control.
- `references/ea028/`: original verified asset, product metadata and manifest.
- `bearing-import-probe.json`: independent original STEP body/face measurements.
- `cli-check.json`, `cli-parameter-variant.json`: native CLI checks.
- `housing-in-extrudo.jpg`: actual web-app screenshot.

Updated skill ZIP: `dist/agent-skills/makers-supply-cad.zip`, eight files, rebuilt
with identical bytes in a second output directory. SHA-256:
`89e1eb25f37f4b1f6de0ce8b649a3383af150e1ed87c37f1e80316bed2a5b49e`.

Archive tests: **139 passed**. Ruff passed excluding the same pre-existing review
report documented in the initial validation receipt; mypy passed for the 24 core
source files. Skill validation, Node syntax/help, realpath/output rejection checks,
local documentation links and `git diff --check` passed. No catalog bytes, private
parts-list data, agent configuration, release or remote repository was modified.

This is a CAD prototype with no axial retainer. Physical fit, manufacturing process,
retention and load performance have not been tested. Other CAD runtimes and the
Extrudo desktop MCP transport have not been certified by this test.

## Agent self-evaluation

Overall **4.4/5**. Accuracy 4: real-kernel, independent mesh and UI evidence support
the result, while desktop MCP is untested. Completeness 5: native model, exports,
BOM, reproducible example and integration fixes are delivered. Clarity 4: the
source-runtime setup adds complexity, now covered in a separate guide. Actionability
5: the native file opens with its own attachment and the runner reproduces it.
Conciseness 4: detailed validation stays in this receipt and the tool-specific
reference. No axis scores 3 or below. The useful next validation, when a connected
desktop is available, is exercising the same handoff through MCP. The assessment
matches the delivered modeling result without claiming physical qualification.
