# CAD tool handoff

Checked **2026-11-14** against upstream repositories and documentation. Extrudo
0.10.0 at revision `9631a7071b17014af4bb366fc521d4c74a93aa86` was exercised
with its real headless OCCT kernel and its web app using a catalog EA028 bearing.
SolidCraft 0.41.0 was also exercised through its released CLI, headless MCP and
native desktop MCP bridge; see [the SolidCraft workflow](solidcraft.md) for evidence
and capability limits. Extrudo's desktop MCP transport and the remaining CAD tools
are researched integration routes. Inspect available tools and version before use.

## Choose the existing modeling environment

Preserve the user's selected CAD tool. The following routes are our integration
recommendations, based on the linked upstream capabilities.

| Tool | Verified upstream surface | Useful catalog handoff |
| --- | --- | --- |
| [SolidCraft](https://github.com/tangency-labs/solidcraft) | Built-in stdio MCP, vendor skills and JSON command scripts | Insert verified STEP as a component, inspect world placement, build a parametric housing, and save a native `.sc` design. |
| [Extrudo](https://github.com/zoltanf/extrudo) | Desktop MCP, its own agent skill, TypeScript document API | Supply verified dimensions and product IDs to the running design; follow its vendor skill for modeling. |
| [build123d](https://github.com/gumyr/build123d) | Python parametric BREP modeling | Use dimension parameters or import an available STEP reference; keep editable Python source. |
| [CadQuery](https://github.com/CadQuery/cadquery) | Python library usable without a GUI | Build parametric parts or assemblies around STEP references and DXF profiles. |
| [FreeCAD](https://github.com/FreeCAD/FreeCAD) | Native parametric modeler with Python scripting | Keep an FCStd design and use verified component geometry as a reference. |
| [OpenSCAD](https://github.com/openscad/openscad) | Script-based solid modeling and CLI | Generate a parameterized SCAD design from catalog dimensions and export a manufacturing mesh. |

These projects are open source; see their repository licenses. The separate
[FreeCAD MCP bridge](https://github.com/neka-nat/freecad-mcp) is an independent
project, not a capability bundled with every FreeCAD installation.

## SolidCraft

Use [the SolidCraft catalog workflow](solidcraft.md) for MCP setup, its vendor
skills, file grants, native STEP insertion and the executable EA028 housing example.
Its CLI and command schema are independent of Extrudo's TypeScript API. The source
code is MIT OR Apache-2.0; the upstream brand/UI assets have separate terms.

## Extrudo

Read the vendor's [agent skill](https://github.com/zoltanf/extrudo/blob/main/apps/desktop/skill/extrudo/SKILL.md)
and [desktop MCP setup](https://github.com/zoltanf/extrudo/blob/main/docs/desktop.md#connecting-an-agent-mcp).
The desktop app documents a token-protected endpoint at
`http://127.0.0.1:7474/mcp`; Settings → Desktop → Agents supplies client config.
The browser app alone does not imply that this desktop connection exists.

1. Obtain the vendor skill through the connected server's skill support,
   `get_skill`, or the release skill ZIP. Inspect live tool schemas.
2. Read the design before editing. The documented tools include `get_design`,
   `get_bodies`, parameter changes, feature edits, screenshots, save, and export.
3. Pass verified catalog dimensions as named parameters. The vendor skill uses
   millimetres and degrees, accepts unit expressions, and requires named face
   references rather than indices. Check returned feature problems after changes.
4. Save the editable design and export through available tools. Vendor MCP skill
   documentation lists STL, 3MF, and STEP exports returning a file path.

The app [documents STEP import](https://github.com/zoltanf/extrudo/blob/main/README.md#what-it-does)
as solid bodies, but that does not establish an MCP import tool. Discover an
installed import capability before attempting it. Imported solids do not imply
reconstructed source sketches or a fully editable original feature history.
Do not treat an STL mesh as a STEP solid.

The [TypeScript API](https://github.com/zoltanf/extrudo/blob/main/docs/api/README.md)
constructs documents without a geometry kernel and is documented as a workspace
package; do not assume an npm install. The [headless CLI](https://github.com/zoltanf/extrudo/blob/main/docs/cli.md)
documents source-checkout commands such as `pnpm extrudo info` and `check`;
verify their availability rather than assuming a global `extrudo` command.

For that source runtime, follow the [executed EA028 housing workflow](extrudo-e2e.md).
The test exposed these handoff requirements:

- An import takes a registered attachment ID with a `model/*` media type, not a
  filesystem path or the catalog's `application/p21` MIME value. Preserve the
  catalog MIME in provenance and use `model/step` for Extrudo's attachment.
- Include STEP bytes with storage `writeArchive`; the document API's `toFile()`
  alone omits them. Reopen the native file and check attachment notices.
- Recompute before enumerating imported bodies; the EA028 model has two solids.
  `handle.bodies()` before a recompute can know only its first body.
- STEP units do not specify the mounting axis. The tested EA028 file's axis is X;
  `position: 'centre'` translates without reorienting it. Rotate and place all
  imported solids after inspecting their bounds.
- Explicitly select the housing body for manufacturing exports. A whole-design
  export also includes purchased reference hardware.
- A nearest-body gap can be zero at a supporting shoulder. Check overlap volume
  and the intended radial allowance separately.

## Python modeling: build123d and CadQuery

Use the Python environment already selected for the design. Native CAD kernels
have environment requirements; the catalog helper's Python environment need
not contain these packages.

- [build123d import/export](https://build123d.readthedocs.io/en/latest/import_export.html)
  documents `import_step(filename)` returning a `Compound`, plus STEP and mesh
  export. Keep component labels/product IDs in the model source or handoff
  manifest; file conversion alone does not preserve catalog provenance.
- [CadQuery import/export](https://cadquery.readthedocs.io/en/latest/importexport.html)
  documents `cq.importers.importStep(path)` and DXF import. Its documentation
  explicitly distinguishes neutral geometry from its parametric Python source.

Generate parameters only from supported dimensions. When a component lacks a
CAD asset, a clearly labeled dimensional envelope can support layout; it is not
verified mating geometry. Keep `.py` source with neutral exports.

## FreeCAD

Use the installed FreeCAD Python interface or an already configured bridge.
[FreeCAD MCP setup](https://github.com/neka-nat/freecad-mcp#quick-start) requires
both its addon/RPC server inside FreeCAD and a client-launched MCP process.
Its [tools](https://github.com/neka-nat/freecad-mcp/blob/main/docs/tools.md)
include document/object inspection, screenshots, and Python execution. Other
bridges can expose different schemas; inspect the connected server first.
Recompute and inspect geometry after changes, then save the native FCStd file.

## OpenSCAD

An agent can edit `.scad` directly and invoke an installed CLI without MCP.
The [official CLI source](https://github.com/openscad/openscad/blob/master/src/openscad.cc)
documents `-o` output, `-D` variable definitions, and PNG render options. For
example: `openscad -o part.stl -D 'width=40' part.scad`. Confirm installed flags
with `openscad --help`. Declare the design's unit convention explicitly; retain
SCAD source and do not promise native STEP export.

## Validate the handoff

Our recommended checks: confirm units, bounding dimensions, orientation, body
count, feature errors, and exported file readability; inspect the model visually
when a viewer is available. Use solids for precise mating geometry when supported
and meshes for the intended manufacturing/viewing workflow. Record any clearance
or manufacturing allowance separately from the catalog's nominal dimension.
Catalog matches and successful exports alone do not prove mechanical fit.
