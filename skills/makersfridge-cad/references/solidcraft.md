# SolidCraft catalog workflow

Checked on **2026-11-14** against the official
[tangency-labs/solidcraft](https://github.com/tangency-labs/solidcraft) release
**v0.41.0**, revision `3c8efdb51952ed9a5f3ebc722c2bad1454fe6d80`.
Its released Linux CLI, isolated stdio MCP server and native desktop MCP bridge
were exercised locally. Other operating systems were not exercised.

SolidCraft includes its own agent skills. Read its
[modeling skill and reference](https://github.com/tangency-labs/solidcraft/tree/v0.41.0/skills/solidcraft-modeling)
and [checking skill](https://github.com/tangency-labs/solidcraft/tree/v0.41.0/skills/solidcraft-checking)
for modeling operations. This catalog skill selects hardware, verifies reference
files and preserves the BOM/source information around that workflow.

## Choose the session

The [official MCP guide](https://github.com/tangency-labs/solidcraft/blob/v0.41.0/docs/mcp.md)
documents a stdio server launched by the agent client:

```bash
solidcraft-cli mcp --headless --allow-path /absolute/path/to/cad-project
```

`--headless` creates an isolated in-process design. Plain `mcp` can discover a
running app, so use the explicit mode for disposable tests. For the user's desktop,
enable its agent control channel through the app's documented setup and use the
documented `--connect` or discovery configuration. Inspect the current design
before editing; preserve the user's work rather than replacing it with a test.

For the executed native-app workflow, follow the
[desktop MCP example](solidcraft-desktop.md). It builds the same housing through
the actual app, verifies a native-window capture and checks saved/exported geometry.

At session start, load `skill_reference {"skill":"solidcraft-modeling"}` and use
`inspect_design {"measure":false,"sketches":false}`. The tested server exposes
`execute`, `batch`, `measure`, `body_topology`, `set_parameter`, `save` and `export`.
Use `describe_command` for the specific installed command schema when needed.
Do not assume its commands match another CAD server's names.

Create the project's reference/output directories before starting a session.
MCP file grants are separate from the working directory: cwd alone grants no
access. Give a new session the project directory needed for the requested work.
If an existing server refuses a path, follow its configuration instructions;
do not bypass the restriction through the desktop control channel or broaden
access to the entire machine. No client configuration is changed by this skill.

## Import the verified hardware

Use `catalog.py` to inspect the exact regional variant and export selected assets,
as described in [catalog-workflow.md](catalog-workflow.md). Use the manifest's
`package_path` and verify its hash before CAD use.

- `file.insert_step` takes a `path` and optional `name`, `up` and rigid `matrix`.
  It creates an imported **component**, preserving all readable solids. Read its
  returned body/occurrence names and warnings instead of assuming one loose body.
- Native `.sc` files embed the imported STEP text. Save and reopen the design to
  check portability; Extrudo's attachment-serialization procedure does not apply.
- `inspect.measure` reports placed world bounds. A body's bounds inside
  `document.inspect` can be in component-definition coordinates and cannot alone
  prove that its placement is correct.
- STEP's own product labels can differ from the catalog filename. The tested EA028
  asset contains internal EA029-like labels. Preserve the selected catalog ID,
  source path and hash; do not reclassify the hardware from those labels.

The tested EA028 STEP is 8 × 22 × 7 mm and has its rotation axis along world X.
For the example housing, this whole-import transform rotates -90° about Y and
moves its center to z=8.3 mm, placing both solids at z=4.8..11.8 mm:

```json
{
  "command": "file.insert_step",
  "params": {
    "path": "/absolute/path/to/verified/608ZZ P5 - EA028.stp",
    "name": "EA028 reference",
    "matrix": [0, 0, -1, 0, 0, 1, 0, 0, 1, 0, 0, 8.3]
  }
}
```

That transform is specific to this source model and housing. Inspect actual
dimensions and orientation before placing a different file.

## Repeatable CLI workflow

SolidCraft's [command scripts](https://github.com/tangency-labs/solidcraft/blob/v0.41.0/docs/scripts.md)
use `{"commands":[{"command":"…","params":{…}}]}`. `solidcraft-cli run` executes
them in a separate session, without changing a running desktop design. The bundled
example accepts the same verified reference export as the Extrudo example:

```bash
mkdir -p ./references ./cad
python "$SKILL_DIR/scripts/catalog.py" --catalog "$CATALOG" \
  export ea028-high-performance-bearings \
  --asset-id model-3f4ff15eee8cf265bc90 --output ./references/ea028
python "$SKILL_DIR/scripts/solidcraft_bearing_housing.py" \
  --solidcraft-cli /absolute/path/to/solidcraft-cli \
  --reference ./references/ea028 --output ./cad/ea028-solidcraft
```

Use the released CLI already selected for the project; it is an optional external
dependency. The adapter itself uses Python's standard library, retains the verified
STEP and BOM provenance, and writes its command script and validation evidence.
Output must be a new directory. It does not install SolidCraft or register MCP.

Use `file.export` with `bodies:["Housing"]` for STEP/STL/3MF manufacturing files.
CLI `--out` without explicit body selection exports the assembly, including
purchased reference hardware. Save `.sc` for editable feature history; neutral
STEP files retain geometry rather than the original parametric history.

## Check the model

Read feature errors **and warnings**, body closure, world placement and measured
volume. A cut can report success while missing its target. Compare with analytic
dimensions/volume and change a parameter to establish that geometry recomputes.
Native measurements can have small numerical error; use a tolerance appropriate
to the kernel rather than copying Extrudo's near-exact volume threshold.

`inspect.interference` must report completed checks. Zero overlaps alone is
inconclusive if pairs are unverified or the report has `unchecked`,
`pairs_not_checked`, `truncated` or `budget_exceeded`. Do not treat a zero nearest
distance at the supporting shoulder as an overlap.

The example uses the same 44 × 32 × 12 mm open-top housing described in
[the Extrudo example's dimension table](extrudo-e2e.md#dimensions-and-validation).
Its clearance and mounting dimensions are prototype design choices, not source
tolerances. Physical fit, axial retention, manufacturing and loading remain to be
evaluated. Source assets keep their recorded third-party rights.
