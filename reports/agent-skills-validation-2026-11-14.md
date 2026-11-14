# Maker's Supply CAD skill validation — 2026-11-14

Follow-up: Extrudo has now been exercised with real geometry and its web app; see
`reports/extrudo-bearing-housing-e2e-2026-11-14.md`. The evidence below records the
initial skill implementation, before that follow-up. The skill ZIP was rebuilt.
SolidCraft was subsequently added and exercised through its released CLI and MCP;
see `reports/solidcraft-agent-support-2026-11-14.md`. The current skill-package identity
is in the subsequent `reports/solidcraft-desktop-mcp-e2e-2026-11-14.md`.

Implemented `skills/makers-supply-cad/`, with a standard Agent Skills entrypoint,
Codex UI metadata, standalone Python helper, tool references and bundled MIT license.
Installation instructions cover Codex, Claude Code and other Agent Skills clients.
No agent configuration, catalog data, private state, release, or remote repository
was changed. The pre-existing `reports/makershelf-review-2026-11-13/` was preserved.

## Automated evidence

| Check | Result |
| --- | --- |
| `.venv/bin/pytest tests -q` | 139 passed, including 15 agent-helper cases |
| Skill creator `quick_validate.py` | Valid skill |
| Ruff on skill/helper tests/packager | Passed |
| Repository Ruff excluding the pre-existing review report | Passed |
| `.venv/bin/mypy` | Passed, 24 existing source files |
| Strict mypy on the helper and ZIP packager | Passed, 2 files |
| `git diff --check` | Passed |
| Local links in skill Markdown | All resolved |
| ZIP rebuilt twice | Identical bytes; archive integrity passed |
| ZIP extracted to `/tmp`, helper run with Python `-I` | Offline search and full product inspection passed |

The helper tests cover JSON and SQLite query behavior, regional data, decimal price
and timestamp preservation, measurement provenance, actual portable
directory paths, verified export, and read-only database hash/mtime/sidecar behavior.
Failure cases cover malformed catalogs, hash/size mismatches, Git LFS pointers,
missing/rejected files, path traversal, escaping symlinks, existing output and
temporary export cleanup.

Unqualified repository-wide `ruff check .` reports three existing errors in
`reports/makershelf-review-2026-11-13/scripts/run-archive.py`: two import-order errors
and one overlong line. That unrelated report was not modified.

## Independent workflow test

A separate agent used the skill and this checkout to select the EU EA028 608ZZ
bearing, export its STEP reference and create a local BOM for two physical bearings.
All generated workflow artifacts stayed in `/tmp/makers-supply-forward-Bqfs1D/`.

- Exact EU variant: `48795653767516`, `608ZZ P5 Steel (2PCS)`; two bearings require
  one purchasable pack.
- Asset: `model-3f4ff15eee8cf265bc90`, `608ZZ P5 - EA028.stp`, 116,193 bytes.
- Independently verified SHA-256:
  `aeabc6c29cf32455b634f805e92e9f9ffb41d143d911a635c68d0034b7d288cf`.
- The vendor source table supplies 8 mm ID, 22 mm OD and 7 mm width despite empty
  normalized `measurements`; its US source URL remains recorded for the EU selection.
- STEP declares millimetres; `rights_status` remains `unknown`.

The test found that export requires an existing parent directory and that BOM
quantities need explicit pack units. Both findings were incorporated into skill
examples and instructions. No housing was modeled; CAD geometry validity,
orientation, clearances and physical fit were not certified.

## Portable artifact

Build with `python scripts/build-agent-skills.py`. The six-file ZIP contains the
complete skill folder, helper, references, license and UI metadata, without catalog
assets or Python caches.

- Output: `dist/agent-skills/makers-supply-cad.zip`
- SHA-256: `d5a5119a89164dac52939935d616cb253611b99e4902b1d527a92a1cc9e11225`

CAD integration instructions were checked against the linked upstream GitHub and
official documentation on 2026-11-14. Extrudo's vendor skill/MCP, build123d,
CadQuery, FreeCAD and OpenSCAD were researched, not exercised as local installations.
No third-party bridge was installed and no public artifact was published.

## Agent self-evaluation

Summary: 4.2/5 across the five quality axes; deliver with the local CAD testing
limitation stated.

| Axis | Score | Evidence and improvement |
| --- | --- | --- |
| Accuracy | 4 | Tests, independent real-file hash check and primary-source research support the instructions; a future installed-CAD smoke test would verify runtime/version compatibility. |
| Completeness | 4 | Skill, offline helper, two catalog layouts, five CAD routes, install guide and portable ZIP are delivered; the CAD routes have documentation evidence rather than application execution evidence. |
| Clarity | 4 | Entrypoint routes to catalog/tool references and examples now create their output parent and name pack units; installation remains client-specific and requires choosing a destination. |
| Actionability | 5 | A complete ZIP and installation commands are provided; the independent agent completed search, selection, verified export and BOM creation. |
| Conciseness | 4 | Tool-specific guidance is separate from the entrypoint; some export and rights constraints recur in the standalone catalog reference for usability. |

No critical issues or axes scoring 3 or below. Highest-value follow-up is an actual
CAD runtime smoke test when an installed tool or connected design is available.
Self-check: the implementation is immediately usable for local lookup/export, while
the distinction between research and exercised CAD integration remains explicit.
