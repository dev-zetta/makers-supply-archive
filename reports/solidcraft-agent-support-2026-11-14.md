# SolidCraft agent support — 2026-11-14

Follow-up: the native desktop MCP bridge has now been exercised. See
`reports/solidcraft-desktop-mcp-e2e-2026-11-14.md` for the new test, fixes and current
skill ZIP identity. The evidence below records the earlier CLI/headless-MCP run.

Added SolidCraft discovery, MCP/vendor-skill instructions and a runnable catalog
bearing adapter to `skills/makers-supply-cad/`. The official project is
[tangency-labs/solidcraft](https://github.com/tangency-labs/solidcraft); interfaces
were checked against tag **v0.41.0**, revision
`3c8efdb51952ed9a5f3ebc722c2bad1454fe6d80`, and its released Linux x86-64 CLI.

## Runtime identity

The portable runtime was downloaded from the official GitHub release and extracted
under `/tmp`, without installing a system package or changing agent configuration.
The official `SHA256SUMS.txt` matched `solidcraft-0.41.0-linux-x86_64.tar.gz`:
`e597e4cb1be24eb14333bf4b8f54807f42443d1751e3cba263ae2e6a810cf070`.
The executable reports `solidcraft-cli 0.41.0`.

Sources: [MCP](https://github.com/tangency-labs/solidcraft/blob/v0.41.0/docs/mcp.md),
[scripts](https://github.com/tangency-labs/solidcraft/blob/v0.41.0/docs/scripts.md),
[STEP import](https://github.com/tangency-labs/solidcraft/blob/v0.41.0/docs/step-import.md),
and the upstream modeling/checking skills. Code licenses are MIT OR Apache-2.0;
upstream brand/UI assets have separate terms. None are bundled with our skill.

## Actual checks

| Check | Result |
| --- | --- |
| Stdio MCP | Real `initialize`, tool discovery, vendor modeling reference and inspection passed; server version 0.41.0, 22 tools |
| MCP catalog handoff | Verified EA028 STEP inserted, both solids positioned and measured in world coordinates, native `.sc` saved |
| MCP isolation | Explicit `--headless`, narrow project `--allow-path`, empty initial design; no desktop session changed |
| CLI model | Parametric 44 × 32 × 12 mm housing; one housing plus two imported closed reference solids |
| Housing volume | 7133.203766351283 mm³ versus analytic 7133.203766332575 mm³ |
| World placement | Reference envelope `[-11,-11,4.8]` to `[11,11,11.8]` mm |
| Default interference | All three body pairs checked; no overlaps, unchecked pairs, truncation or budget exhaustion |
| Exports | Housing-only STEP, STL and 3MF |
| STEP reimport | One closed body, matching analytic volume and bounds, clean timeline |
| Parameter change | 0.4 mm diametral clearance recomputed and saved as a native variant |
| Negative control | -0.2 mm diametral clearance detected 46.16183448921339 mm³ housing/bearing overlap |
| Native portability | Independent copy of `.sc` reopened without its reference directory; three bodies, no feature errors/warnings |
| Independent STL parsing | 8,764 triangles, 13,146 welded edges each shared twice; positive mesh volume 7133.474707 mm³, within 0.0038% of analytic solid |
| Independent OCCT check | Exported STEP read by Extrudo's OCCT runtime as one valid solid, exact volume 7133.203766332579 mm³, bounds 44 × 32 × 12 mm |

The real asset is catalog `ea028-high-performance-bearings`, EU variant
`48795653767516`, part EA028, one two-bearing pack. One bearing is installed and
one is spare. Source-table dimensions are 8 mm bore, 22 mm OD and 7 mm width.
Asset `model-3f4ff15eee8cf265bc90` is 116,193 bytes, SHA-256
`aeabc6c29cf32455b634f805e92e9f9ffb41d143d911a635c68d0034b7d288cf`.
The adapter verifies the bytes and retains provenance/rights (`unknown`) in its BOM.

## SolidCraft-specific integration details

- Use SolidCraft's bundled `solidcraft-modeling` and `solidcraft-checking` skills;
  the catalog skill supplies hardware identity and verified reference files.
- Plain `mcp` may auto-discover a running desktop. Explicit `--headless` isolates
  tests; desktop bridging remains a separate mode.
- MCP cwd does not grant file access. Existing project directories are granted
  explicitly with `--allow-path`; this test did not broaden access elsewhere.
- STEP insertion creates a component and returns its actual body names. Native
  `.sc` stores the source STEP text and editable feature history.
- `document.inspect` can expose component-local bounds. Use `inspect.measure`
  for world placement, and verify the full reference envelope.
- The selected official EA028 STEP contains EA029-like internal product labels.
  The selected catalog asset ID, original archive path and verified hash remain
  authoritative identifiers; the adapter does not infer a variant from those labels.
- The source model is X-axis oriented and has two solids. The adapter discovers
  both, checks the source envelope, then rotates and moves them with named
  parameters so the axial placement can recompute.
- `file.export` explicitly selects `Housing`; generic CLI `--out` would include
  the reference hardware. An empty overlap list is accepted only after all pairs
  have been verified.

## Deliverables and automated validation

- Guide: `skills/makers-supply-cad/references/solidcraft.md`.
- Adapter: `skills/makers-supply-cad/scripts/solidcraft_bearing_housing.py`.
- Tests: `tests/test_solidcraft_adapter.py`: 20 isolated cases plus one optional
  integration test, all 21 exercised with the released CLI.
- Local model/MCP evidence: `dist/agent-cad/ea028-solidcraft-e2e/`.
- Updated portable skill ZIP: `dist/agent-skills/makers-supply-cad.zip`, ten files,
  SHA-256 `523e39ddb6dab6ab08d89ef0776f8a81c15bace1608159ef5dad8c74ce2a9471`.

With `SOLIDCRAFT_CLI` and `SOLIDCRAFT_REFERENCE` pointing to the verified runtime
and export, the full archive suite passed **160 tests**, without skips. Default
runs skip the optional runtime integration if those variables are absent.
Ruff passed excluding the same unrelated pre-existing review report already
documented in earlier receipts. Core mypy, strict adapter mypy, skill validation,
local links, reproducible ZIP packaging and `git diff --check` passed.

No catalog data, private parts-list state, global agent configuration, release or
remote repository was modified. No SolidCraft desktop/UI or other operating system
was tested. The housing is an open-top prototype without an axial retainer;
physical fit, manufacturing and load performance remain unqualified.

## Agent self-evaluation

Overall 4.4/5. Accuracy 4: pinned source, released CLI, actual MCP handoff and
independent geometry checks support the result; desktop transport is untested.
Completeness 5: discovery, guide, adapter, tests, native model and updated package
are delivered. Clarity 4: explicit session and coordinate distinctions address
tool-specific traps, while an external CLI remains a prerequisite. Actionability
5: the packaged adapter recreates the model from a verified reference export.
Conciseness 4: detailed evidence stays here and in the SolidCraft reference.
No score is below 4; the user can use the support now without treating it as
physical qualification or proof of untested desktop/platform behavior.
