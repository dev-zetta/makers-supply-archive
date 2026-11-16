# Chili3D catalog skill and local installation — 2026-11-16

Implemented and installed Chili3D support in `makers-supply-cad`, then exercised
its installed helper with the real local EA028 catalog bearing and the official
MCP bridge. The native housing was saved, reopened, edited and checked again.

## Upstream and installed software

- Latest GitHub release checked: [Chili3D 0.8.0](https://github.com/xiangechen/chili3d/releases/tag/0.8.0),
  published 2026-10-30, commit `e35a8eecba803a463698f2e49a7404f25c607ba5`.
  There are no release installer assets; a local production browser build was made.
- [Official MCP bridge](https://github.com/xiangechen/chili3d-mcp): 0.1.0,
  commit `dd08fe36616a93ee247553f17297535588974173`. Its smoke and MCP tests passed.
- Local app includes the optional repository `integrations/chili3d/export-data.patch`.
  This adds exporter byte transfer and fingerprinted JavaScript bundles. It is a
  local integration patch, not an upstream 0.8.0 capability or a new archive release.
  The unchanged upstream source archive, patch, licenses and hash receipt are retained
  with the installed app.
- Persistent installation: `/home/gmax/.local/share/makers-supply/cad/chili3d/0.8.0/`.
  Launchers: `/home/gmax/.local/bin/chili3d`, `/home/gmax/.local/bin/chili3d-mcp`;
  application-menu entry: `chili3d-local.desktop`. Local app origin: `http://127.0.0.1:18081`.
- SolidCraft's existing 0.41.0 release was preserved under
  `/home/gmax/.local/share/makers-supply/cad/solidcraft/0.41.0/`, with `solidcraft`,
  `solidcraft-cli`, and a menu entry. The original installation had been temporary
  under `/tmp`. Its CLI version and real bearing-housing regression both passed.

## Executed catalog and CAD workflow

The installed catalog helper searched the repository and hash-verified an export of
`ea028-high-performance-bearings`, EU variant `48795653767516`, part EA028,
608ZZ P5 Steel (2PCS). The source table supplies 8 × 22 × 7 mm. The exact STEP asset
`model-3f4ff15eee8cf265bc90` is 116193 bytes, SHA-256
`aeabc6c29cf32455b634f805e92e9f9ffb41d143d911a635c68d0034b7d288cf`.
Its two solid volumes and X-axis orientation were checked. Internal EA029 labels
were retained as source metadata, rather than used to identify the bearing.

A fresh browser document imported that reference. The final helper created eight
editable extrusion features and constrained circle sketches, with named variables
for the bearing seat and clearance. Both bearing solids were placed with their
geometry baked into reference copies. The imported originals remain hidden.

| Check | Result |
| --- | --- |
| Housing | One valid solid; bounds [-22,-16,0] to [22,16,12] mm |
| Housing volume | 7133.203766332574 mm³, matching analytic volume |
| Placed bearing envelope | [-11,-11,4.8] to [11,11,11.8] mm |
| 0.2 mm diametral allowance | Zero bearing/housing overlap |
| 0.4 mm diametral allowance | Recomputed volume matched analytic design; zero overlap |
| −0.2 mm control | 46.1618345 mm³ overlap detected |
| Restoration | 0.2 mm restored, valid baseline geometry, all eight features intact |
| Native file | Downloaded `.cd`, reopened in installed app, variables/features rechecked |
| STEP | Actual exporter bytes saved and hashed; SolidCraft SMLib reimport: one closed solid, 7133.203766347451 mm³ |
| Binary STL | 1796 triangles; expected bounds; volume 7130.716324589572 mm³, 0.0349% tessellation difference |
| Official MCP stdio | Real SDK client discovered 32 tools and measured the native housing |

BOM: one bearing used from one purchasable two-bearing pack, leaving one spare.
The 0.2 mm diametral clearance is an assumption; the open-top prototype has no axial
retainer and physical fit was not tested. Source asset rights remain `unknown`.

## Integration fixes

1. Stock shape queries ignore display transforms. The adapter now uses baked
   reference copies, with dimensional/volume checks before and after placement.
2. `export_nodes` success reports conversion, not a saved browser download.
   The optional patch returns exact bytes; the adapter checks encoding, byte count,
   STEP signature and binary STL completeness before writing and hashing files.
3. Production JS filenames were reused by browser caches after an update. The local
   patch fingerprints entry and chunk filenames. The fresh page then advertised
   the actual updated tool schema.
4. Installer copying originally excluded nested dependency `dist` directories,
   breaking stdio MCP while the HTTP CLI worked. Dependencies are now retained;
   the clean installer check and real SDK MCP test both passed.
5. The adapter uses the live `run_parametric` body result rather than guessing node
   class names, handles tool-content errors within successful transport envelopes,
   checks the active document before test edits, and restores baseline clearance on
   failed verification. Interference booleans consume temporary copies only.

## Agent installation and validation

The official Codex skill-installer helper installed the final portable package.
All 14 installed files were SHA-256 matched, with zero mismatches. The original
released v1.2.0 skill is preserved under `/home/gmax/.codex/skill-backups/`.
Codex app-server discovery listed the user skill as enabled from both the repository
and `/tmp`; its description includes Chili3D. The exact installed helper was run
against the local catalog and reopened native model. Codex's `chili3d` stdio MCP
entry points to the pinned local CLI. New Codex sessions can load that server;
the skill is available on the next turn.

Validation: **198 archive tests passed**, including the released SolidCraft CLI
integration; **22 Chili3D file/bridge tests passed**; official bridge smoke/MCP
checks passed; Ruff, strict mypy for new Python code, skill validation, clean
installer checks and `git diff --check` passed. No catalog records were changed.

Artifacts are in `dist/agent-cad/ea028-chili3d-e2e/model-final/`:
`ea028-housing.cd`, `ea028-housing.step`, `ea028-housing.stl`, `bom.json`,
`verification.json`, `roundtrip.json`, `mcp-receipt.json`, `viewport.jpg` and
`artifact-hashes.json`. The portable package is
`dist/agent-skills/makers-supply-cad.zip`.

![Reopened Chili3D housing](../dist/agent-cad/ea028-chili3d-e2e/model-final/viewport.jpg)
