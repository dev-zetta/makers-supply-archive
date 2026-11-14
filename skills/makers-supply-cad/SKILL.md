---
name: makers-supply-cad
description: Find Maker's Supply hardware, inspect exact variants and dimensions, and export verified local reference files for CAD projects using SolidCraft, Extrudo, build123d, CadQuery, FreeCAD, or OpenSCAD. Use when designing around catalog parts or preparing a hardware BOM from Maker's Supply Archive.
license: MIT
metadata:
  requires-python: "3.10+"
---

# Maker's Supply CAD

Use the archive to select real hardware and carry its measurements, files, and source
information into an editable CAD design. The bundled helper runs offline using only
the Python standard library; it does not require the catalog web server.

## Locate the catalog

Resolve `SKILL_DIR` to the directory containing this loaded `SKILL.md`, and `CATALOG`
to the user's archive checkout or extracted portable data directory. These are path
placeholders to set, not agent-specific environment variables. The helper also accepts
the SQLite file itself. Use the interpreter available as `python` or `python3`.

```bash
python "$SKILL_DIR/scripts/catalog.py" --catalog "$CATALOG" search "bearing" --region eu
python "$SKILL_DIR/scripts/catalog.py" --catalog "$CATALOG" show ea028-high-performance-bearings
```

Use a catalog path already supplied by the user or project configuration. If absent,
check the working project for `data/products/` or `catalog.sqlite`, then ask for its
location. Prefer canonical JSON in a checkout; use the adjacent `assets/` with a
portable database. Do not use the private user-state database as the catalog.

Read [catalog-workflow.md](references/catalog-workflow.md) for command details,
asset availability, BOM fields, or working with an existing parts-list export.

## Select hardware before modeling

1. Search by hardware name, product ID, SKU, or part number; inspect the full product.
   Search matches all whitespace-separated terms literally, ignores case, and defaults
   to active products. Broaden the query if it returns no results.
2. Resolve the exact regional variant and part number. A product family may contain
   several sizes or quantities. `box_contents` can describe a kit rather than one part.
   Distinguish physical part count from purchasable pack count in the BOM and costing.
3. Read `measurements`, `specifications`, and `source_tables`. Preserve `raw_value`,
   units, `applies_to`, and provenance. Missing normalized values do not mean zero.
   Keep official dimensions, measurements made by the user, CAD-derived dimensions,
   and design assumptions distinguishable. Ask for a missing fit-critical dimension
   when it cannot be established from a source drawing or verified model.
4. Select specific asset IDs from `show`. Match part numbers against filenames and
   `archive_member_path`; shared files and ambiguous matches need inspection. Prefer
   STEP/STP for solid reference geometry, and use STL/3MF with mesh limitations in mind.
   A product having a model record does not prove the file is local or variant-correct.

## Export reference files

Export only the chosen files to a new directory in the CAD project:

```bash
mkdir -p ./references
python "$SKILL_DIR/scripts/catalog.py" --catalog "$CATALOG" \
  export ea028-high-performance-bearings \
  --asset-id model-3f4ff15eee8cf265bc90 --output ./references/ea028
```

The example ID must still appear in the selected local snapshot. The helper verifies
SHA-256 and size while copying and writes `product.json` and `manifest.json` with file
paths, source URLs, rights, and archive ancestry. Use the emitted `package_path` rather
than guessing a filename. It refuses existing output directories and unusable files.

If files are missing or still Git LFS pointers, explain what is unavailable. A
metadata-only checkout can still answer metadata questions. Use an existing hydrated
copy, or obtain the corresponding release data packs/Git LFS objects when requested.
The helper never downloads, extracts archives, or executes downloaded content.

## Hand off to CAD

Read the relevant section of [cad-tools.md](references/cad-tools.md) for the chosen
tool. Preserve an already selected modeling tool. Extrudo supplies its own modeling
skill and MCP interface; use those alongside this catalog skill. Other tools can use
their installed Python, macro, or CLI interface. Discover the installed version's
capabilities before invoking it; this skill does not install or configure CAD servers.

For SolidCraft, read [solidcraft.md](references/solidcraft.md). Use its bundled
modeling/checking skills alongside this catalog skill, and choose explicitly
between an isolated headless session and the user's connected desktop. The
included Python example runs its released CLI against the verified EA028 export.
When testing the native desktop bridge, follow the
[desktop MCP example](references/solidcraft-desktop.md), which preserves existing
work and verifies the real app window as well as saved/exported geometry.

For a reproducible Extrudo test without a connected desktop session, use the
[tested EA028 housing example](references/extrudo-e2e.md). Its optional Node script
executes Extrudo's real kernel, embeds the reference STEP in the native design,
checks placement and interference, and exports only the printable housing.

Keep purchased hardware as reference geometry and author the surrounding part with
named dimensions and clearance parameters. An imported STEP solid does not recover
the original feature history. Confirm units, orientation, and a known physical
dimension before using it for fit. Mesh formats can require an explicit scale.

Keep generated CAD source and exports separate from the archive originals. Check
model validity, dimensions, interference, and export/reimport behavior using the
selected tool where available. Distinguish checks actually run from proposed checks;
do not claim physical fit from a screenshot or a successful export alone.

Return the editable source, requested manufacturing/reference exports, and a concise
hardware BOM with product/variant IDs, quantities, source files, and unresolved
dimensions or clearance assumptions. When costing is requested, use the chosen
region's currency and retrieval date; catalog prices are snapshots, exclude tax and
shipping, and must not be combined across currencies.

Catalog files retain their recorded third-party rights; the skill's MIT license does
not license those assets. Preserve `rights_status`, including `unknown`, in handoffs.
