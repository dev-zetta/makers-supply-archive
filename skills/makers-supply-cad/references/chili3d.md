# Chili3D catalog workflow

Verified 2026-11-16 with Chili3D **0.8.0**, commit
`e35a8eecba803a463698f2e49a7404f25c607ba5`, and the official
[`@chili3d/mcp`](https://github.com/xiangechen/chili3d-mcp) **0.1.0** at
`dd08fe36616a93ee247553f17297535588974173`.
The [GitHub release](https://github.com/xiangechen/chili3d/releases/tag/0.8.0)
has no installer assets: this is a browser CAD app. A local production build runs
its OpenCascade WASM kernel in the browser, with no in-app AI subscription/key needed
when an external agent drives the official bridge.

## Connect an existing installation

Preserve the user's open work. Inspect `chili3d_status` and
`chili3d_get_document_state` before creating or importing anything. Only one page
owns a bridge; opening another connected tab replaces it. Keep that page visible.
A fresh page has no document; `chili3d_new_document` creates one and refuses to replace
an existing document. Tool discovery is dynamic: re-list tools after connecting.

The local install provides `chili3d` (starts the localhost app and opens a browser)
and `chili3d-mcp`. An MCP configuration can use an absolute installed CLI path:

```toml
[mcp_servers.chili3d]
command = "/absolute/path/to/chili3d-mcp"
args = ["mcp"]
```

For Claude Code or other hosts, use the equivalent stdio command/args. The official
bridge's `init` supplies host notes, but do not overwrite project instructions or
replace a pinned local command with mutable `npx` configuration unnecessarily.
The shell fallback uses the same registry:

```bash
chili3d-mcp status
chili3d-mcp list
chili3d-mcp schema run_parametric
chili3d-mcp call load_skill --json - <<'JSON'
{"name":"parametric-modeling"}
JSON
```

Call `load_skill` separately for `app-guide`, `parametric-modeling`, `modeling-api`
and `shape-query` as needed. Its argument is singular `name`, not `names`.
Use live schemas: `select_nodes` takes `nodeIds`, whereas `export_nodes` takes `ids`.

## Catalog handoff and editable modeling

Export the exact local catalog STEP with `catalog.py` first. Use the file path in
its verified manifest. In Chili3D 0.8.0, the bridge has no file-import or native-save
tool: use the app's **Import** control and save/download toolbar. `.cd` is the native
editable document; **Save** stores it in that browser's IndexedDB, and **Download**
writes the transferable `.cd`. There is no autosave. `?url=<local-file-URL>` also
loads a file at startup when a local server explicitly exposes that file. Do not
serve the catalog root or upload it to the public app to work around file access.

Use `run_parametric` for editable sketches/features and document variables for fit
allowances. `run_program` is useful for measurements and temporary geometry. Its
edit-style booleans consume their input nodes: pass copies when testing interference
so that the parametric feature tree and purchased reference solids survive.

**Coordinate trap in 0.8.0:** `shape.boundingBox` and other shape queries read a
node's underlying geometry, ignoring its display `transform_node` placement. The
example uses `transformedMul` to create reference copies with placement baked into
the geometry, then hides the imported originals. Validate those copies' envelope;
do not claim a world-space fit from the untransformed bounds. An imported STEP may
contain multiple solids and misleading internal names: match catalog IDs, checksums,
source dimensions, solid counts and volumes rather than those labels.

## EA028 bearing-housing example

Prepare from a verified EA028 export (EU variant `48795653767516`, 608ZZ P5,
8 × 22 × 7 mm, one pack of two bearings):

```bash
python "$SKILL_DIR/scripts/chili3d_bearing_housing.py" \
  --reference ./references/ea028 --output ./chili3d-model
```

This verifies provenance/asset integrity and writes the STEP reference, ordered
variables, feature program and BOM. Import `chili3d-model/ea028-reference.stp` into
an isolated new document. Read `get_document_state` for the **two solid node IDs**
inside the imported groups, then build with the official CLI:

```bash
python "$SKILL_DIR/scripts/chili3d_bearing_housing.py" \
  --output ./chili3d-model --mcp-cli /absolute/path/to/chili3d-mcp \
  --bearing-node-id FIRST_SOLID_ID --bearing-node-id SECOND_SOLID_ID
python "$SKILL_DIR/scripts/chili3d_bearing_housing.py" \
  --output ./chili3d-model --mcp-cli /absolute/path/to/chili3d-mcp --verify
```

The adapter rejects unrelated document content and existing variables. It checks
both STEP solids before modeling, creates eight editable extrusion features, bakes
the reference's X-to-Z placement, and checks shape validity and analytic dimensions.
The verifier edits clearance to 0.4 mm and -0.2 mm, measures cloned-solid overlap,
and restores the 0.2 mm baseline even when a later check fails. If a connection is
lost, reconnect and verify the restored value before saving; a disconnected page
cannot accept a restoration command.

Expected baseline: 44 × 32 × 12 mm overall, Ø22.2 × 7.2 mm seat starting at Z4.8,
Ø18 shaft relief, four Ø3.4 mount holes at (±17, ±10). Volume is
7133.2037663 mm³. Bearing copies span [-11,-11,4.8] to [11,11,11.8]. Baseline and
0.4 mm allowance have zero overlap; -0.2 mm detects about 46.1618345 mm³.

Save/download the `.cd`, reopen it and check that all eight features and variables
survive. `export_nodes` downloads STEP/STL in the browser; select **only the housing
ID**. A returned `ok: true` and byte count prove conversion, not that a download
was saved. Collect the file, confirm its bytes and reimport it before claiming a
round trip.

The repository's optional local integration patch adds `returnData: true` to the
`export_nodes` schema. It returns `dataBase64` instead of requesting a browser
download. If that field is advertised by the installed app, the adapter can write
and hash-check the actual bytes:

```bash
python "$SKILL_DIR/scripts/chili3d_bearing_housing.py" \
  --output ./chili3d-model --mcp-cli /absolute/path/to/chili3d-mcp --export
```

Stock 0.8.0 does not have this option; without it, collect the browser download.
The adapter fails explicitly instead of inventing saved files. The patch modifies
the app, not the official MCP bridge. The tested local installer retains the pinned
upstream source and integration patch separately.

This is an open-top prototype without an axial retainer. The 0.2 mm diametral
allowance is a design assumption, not a fit specification or a physical-fit test.
The BOM uses one bearing from one two-bearing pack, leaving one spare. Keep the
catalog asset's rights and the original bytes with the handoff.
