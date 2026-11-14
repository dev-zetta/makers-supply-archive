# SolidCraft desktop MCP end-to-end test — 2026-11-14

**Passed:** the real SolidCraft native desktop built the EA028 bearing housing
through its authenticated MCP bridge, recomputed parameter changes, saved a clean
baseline, exported the housing alone and produced a native-window screenshot.
Separate CLI sessions reopened the saved assembly and exported STEP successfully.

## Desktop isolation and connection

SolidCraft desktop and CLI **0.41.0** came from the previously verified official
Linux x86-64 release, source tag revision
`3c8efdb51952ed9a5f3ebc722c2bad1454fe6d80`. The actual native app ran on the
host's Wayland session, using Vulkan with MSAA 4x and GPU tessellation.

The launch used explicit temporary settings, XDG data/cache, recovery and crash
directories under `/tmp/solidcraft-desktop-e2e-2026-11-14/`. Explicit settings
prevented legacy preference adoption; `--control 28789` prevented reopening a
previous session and enabled an authenticated loopback channel for this launch.
No user preferences, global MCP registration or existing designs were changed.

The MCP process used explicit `--connect 127.0.0.1:28789`, the same private data
directory for token discovery, strict parameter checking and a narrow project
file grant. The token was neither printed nor passed on the command line.
Successful live inspection showed a pristine `Untitled` design at revision 1.
A pre-build `source: "window"` capture showed the actual native app, rather than
accepting initialization text as connection proof.

## Input and geometric evidence

The reference was exported from the local catalog using the skill's helper:
product `ea028-high-performance-bearings`, EU variant `48795653767516`, EA028,
8 mm bore × 22 mm OD × 7 mm width. The verified source STEP was 116,193 bytes,
SHA-256 `aeabc6c29cf32455b634f805e92e9f9ffb41d143d911a635c68d0034b7d288cf`.
Both source solids were imported, rotated from X to Z and placed on the shoulder.

| Check | Result |
| --- | --- |
| Native construction | All batches completed; clean feature state; three closed solids |
| Housing | 44 × 32 × 12 mm, bounds `[-22,-16,0]` to `[22,16,12]` mm |
| Measured housing volume | 7133.203766351283 mm³ |
| Independent analytic volume | 7133.203766332575 mm³ |
| Bearing world envelope | `[-11,-11,4.8]` to `[11,11,11.8]` mm |
| Default interference | All three pairs checked, zero overlaps, no unchecked/truncated/budget-limited results |
| Parameter variant | 0.4 mm diametral clearance recomputed, measured and saved |
| Negative control | -0.2 mm diametral clearance detected 46.16183448921339 mm³ overlap |
| Restoration | 0.2 mm baseline restored and measured before final save/export |
| Final desktop | Revision 64, `dirty: false`, saved to the stable final project path |
| Manufacturing exports | STEP/STL/3MF explicitly selected only `Housing` |
| Native reopen | Three closed solids, matching baseline, clean timeline and 0.2 mm clearance |
| STEP reimport | One closed solid, matching volume and bounds, clean timeline |
| Explicit window screenshot | Actual native frame, 2400 × 1500 PNG, `source: "window"`, no fallback |
| Independent STL parse | 8,764 triangles; all 13,146 welded edges shared twice; correct bounds; positive mesh volume 7133.474707180752 mm³ |
| Native-only portability | An independent copy of `.sc` reopened without its reference directory; embedded STEP blob matched the verified source hash |
| Existing-design protection | Running the finished runner against the completed design refused before mutation; before/after desktop snapshots were identical at revision 64 |

The native window was visually inspected and showed the seated bearing, mounting
flange, holes, model browser and editable feature history. The saved native and
exported geometry correspond to the restored baseline, not the test variant.
The isolated desktop was stopped after verification; the saved files remain.

## Integration changes

Added `skills/makers-supply-cad/scripts/solidcraft_desktop_housing.py` and its
[workflow guide](../skills/makers-supply-cad/references/solidcraft-desktop.md).
The desktop runner reuses the existing catalog/reference and geometry validators.

- Every file path sent to the app is absolute and contained in the granted project
  directory. The app and MCP server can have different working directories.
- MCP batches are unwrapped and accepted only with `ok: true`, the expected
  `completed` count and every raw result present. CLI result-list assumptions
  are not applied to desktop replies.
- The initial desktop must be pristine, including no parameters, saved path,
  undo history or unsaved work. The runner never calls `new_design` or `open`.
- Import-name discovery is a separate step; both actual returned solid names are
  used for parameterized placement.
- Final output paths stay stable while the app has files open. Failed runs keep
  partial artifacts and diagnostics rather than deleting files referenced by the app.
- The runner restores and measures the 0.2 mm baseline before saving/exporting,
  then requires a real-window screenshot and reopens files through separate CLI
  sessions, preserving the desktop's current work.
- Large/fragmented JSONL image replies, notifications, plain-text tool failures
  and uncertain timeouts are handled explicitly. A timed-out mutation is never
  automatically resent; the error instructs inspection of pending work/state.

The existing headless workflow is preserved. This adds actual desktop transport
support without changing upstream SolidCraft or registering a global MCP server.

## Artifacts and automated checks

Local project: `dist/agent-cad/ea028-solidcraft-desktop-e2e/`.

- `model/bearing-housing.sc`, `clearance-0.4.sc`.
- `model/housing.step`, `housing.stl`, `housing.3mf`.
- `model/desktop-window.png`: actual final native-window capture.
- `model/hardware-bom.json`, verified reference copy and source metadata.
- `model/validation.json`, `native-reopen.json`, `step-reimport.json`.
- `desktop-probe.json` and `existing-design-protection.json`.

The updated skill ZIP has **12 files**, rebuilt identically in a second directory:
`dist/agent-skills/makers-supply-cad.zip`, SHA-256
`038602ebfb42c9ae618932e8897b2383ff177044f5a3afe8a5a8d05bc9d24029`.

The full archive suite passed **187 tests**, with the optional released-CLI
integration enabled. The 27 new desktop tests cover fragmented large protocol
replies, notifications, timeout/no-resend behavior, non-pristine refusal, absolute
paths, partial batches, false screenshot proof and plain-text tool errors.
Ruff passed excluding the same unrelated pre-existing review report documented
earlier. Core mypy, strict adapter/desktop-runner mypy, skill validation, local
links, reproducible ZIP integrity and `git diff --check` passed.

Catalog bytes, private parts lists, global settings, releases and remote Git
repositories were unchanged. Other operating systems were not tested. The
open-top housing remains a prototype without an axial retainer; physical fit,
manufacturing and load performance were not tested.

## Agent self-evaluation

Overall 4.6/5. Accuracy 5: native frame, live state, reopened geometry and independent
mesh checks agree. Completeness 5: desktop execution, integration fixes, model,
exports, guide and regression tests are delivered. Clarity 4: the external app and
isolated token/profile environment require setup, now documented explicitly.
Actionability 5: the runnable example and saved native file can be used directly.
Conciseness 4: detailed evidence is kept in this receipt and desktop reference.
No axis scores below 4; the outcome is desktop CAD verification on the tested
Linux release, without claiming physical or other-platform qualification.
