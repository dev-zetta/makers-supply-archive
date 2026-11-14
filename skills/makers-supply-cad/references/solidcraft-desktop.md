# SolidCraft desktop MCP example

This workflow drives a real SolidCraft native app through its authenticated
localhost control channel and stdio MCP bridge. It uses the same verified EA028
reference and 44 × 32 × 12 mm housing as the
[headless example](solidcraft.md#repeatable-cli-workflow).

## Start a disposable desktop

Use matching SolidCraft desktop and CLI binaries. The tested release is 0.41.0,
revision `3c8efdb51952ed9a5f3ebc722c2bad1454fe6d80`. The official
[control protocol](https://github.com/tangency-labs/solidcraft/blob/v0.41.0/docs/control-protocol.md)
and [MCP guide](https://github.com/tangency-labs/solidcraft/blob/v0.41.0/docs/mcp.md)
describe the launch token and connection setup.

For repeatable testing on Linux, keep the normal display/session environment and
choose fresh absolute directories for these variables:

```bash
export SOLIDCRAFT_SETTINGS_DIR=/absolute/test-profile/settings
export XDG_DATA_HOME=/absolute/test-profile/data
export XDG_CACHE_HOME=/absolute/test-profile/cache
export SOLIDCRAFT_RECOVERY_DIR=/absolute/test-profile/recovery
export SOLIDCRAFT_CRASH_DIR=/absolute/test-profile/crashes
solidcraft --control 28789
```

Launch this from a separate terminal so the app stays running. Explicit settings
avoid legacy preference adoption; `--control` prevents reopening a prior session's
designs and opens the selected loopback port for this launch. Select a free port.
These example variables apply to the test processes; do not replace a user's
normal profile or change global client configuration.

The CLI must inherit the same `XDG_DATA_HOME`, where this launch writes its private
token. An explicit `SOLIDCRAFT_CONTROL_DIR` can instead isolate the token directory;
if used, give it to both app and CLI. Let the CLI read the token automatically.
Do not print it, embed it in scripts, or pass it on the command line.

If connecting to a normal desktop session, create a new empty design first. The
example requires a pristine design: no bodies, features, parameters, saved path,
undo history or unsaved changes. It never calls `new_design` or `open`
to replace work in the app. Desktop tests should have one driver at a time.

## Export the catalog reference and run

Set `SKILL_DIR` and `CATALOG` to the installed skill and local archive. In a terminal
with the same isolated profile variables as the app:

```bash
mkdir -p ./references ./cad
python "$SKILL_DIR/scripts/catalog.py" --catalog "$CATALOG" \
  export ea028-high-performance-bearings \
  --asset-id model-3f4ff15eee8cf265bc90 --output ./references/ea028
python "$SKILL_DIR/scripts/solidcraft_desktop_housing.py" \
  --solidcraft-cli /absolute/path/to/solidcraft-cli \
  --connect 127.0.0.1:28789 \
  --reference ./references/ea028 --output ./cad/ea028-desktop
```

The wrapper starts `solidcraft-cli mcp --connect … --allow-path … --param-check strict`.
Explicit `--connect` requires the desktop and prevents headless fallback. Only the
project output directory is granted for file access; the verified reference is
copied inside it. Every path sent to the desktop is absolute: the app's working
directory can differ from the MCP client's.

Output must be a new directory. Its final path stays stable once allocated because
the desktop has saved/open files there. A failed run preserves partial artifacts
and diagnostics so the app's state can be inspected; do not rerun over that folder.

## What the test checks

- Successful live inspection of the initially empty native design, plus the
  upstream modeling skill. Initialization text alone is insufficient: a server can
  advertise a desktop connection before an app is listening.
- Parameters and housing features built through MCP, with separate STEP insertion
  so the returned body names can be used for both imported solids.
- Completed MCP batches, clean feature state, three closed bodies, analytic housing
  volume, correct world placement and all three interference pairs checked.
- A 0.4 mm diametral-clearance change, native parameter variant and undersized-seat
  negative control. The 0.2 mm baseline is restored and measured before final save,
  export and screenshots.
- Native `.sc` save and housing-only STEP/STL/3MF export. The saved file and STEP
  export are reopened through separate CLI sessions, preserving the live desktop.
- An explicit MCP `screenshot` with `source: "window"` proves that a real native
  app rendered the model. A default screenshot can fall back to a model render;
  that does not establish desktop execution.

MCP `batch` wraps its raw engine results in `{ok, completed, results}`; the wrapper
validates that envelope before using the shared geometry checks. A failure can
leave some steps applied, so inspect the current design before deciding how to
continue. Do not infer rollback from an error alone.

The client gives slow desktop operations time to finish. If an operation times out,
its mutation may still be running. Use the server's `pending`/`running` inspection
or reconnect and inspect; do not resend the mutation automatically. The wrapper
does not bypass file grants or use the control socket directly.

Keep the native assembly, hardware BOM, reference metadata, exports, validation
receipt and desktop screenshot together. The bearing source retains its recorded
rights. This remains an open-top prototype without an axial retainer; desktop
verification does not establish physical fit or load performance.
