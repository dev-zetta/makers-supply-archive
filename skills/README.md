# Agent skills

[`makers-supply-cad`](makers-supply-cad/SKILL.md) connects a local Maker's Supply
Archive catalog to an agent's CAD workflow. It includes offline JSON search and
product inspection, verified file exports, a BOM handoff, and researched guidance
for SolidCraft, Extrudo, build123d, CadQuery, FreeCAD, and OpenSCAD.

The same skill folder follows the [Agent Skills format](https://agentskills.io/specification).
It requires Python 3.10+ and either a checkout's `data/products/` or an extracted
portable `catalog.sqlite` with its matching `assets/`. It does not require the web
app, Python project dependencies, or a new MCP service. CAD tools are installed
separately. Metadata-only checkouts work for lookup; exporting requires real files.

## Install

Copy the entire `skills/makers-supply-cad` folder, including its scripts and references,
into your agent's skills directory. From this repository, choose one destination:

| Agent | Per-project destination | Personal destination |
| --- | --- | --- |
| Codex | `<cad-project>/.agents/skills/makers-supply-cad` | `~/.agents/skills/makers-supply-cad` |
| Claude Code | `<cad-project>/.claude/skills/makers-supply-cad` | `~/.claude/skills/makers-supply-cad` |
| Other Agent Skills clients | Follow the client's skill-directory setting | Copy this same complete folder |

For example, to install for a new Claude Code project on Linux/macOS, run from
this repository, replacing `/path/to/cad-project` with your CAD project:

```bash
mkdir -p /path/to/cad-project/.claude/skills
cp -R skills/makers-supply-cad /path/to/cad-project/.claude/skills/
```

For Codex use `.agents/skills` in the same commands. Check for an existing same-named
folder before copying; review upgrades rather than nesting or merging skill versions.
On Windows, copy the folder with Explorer or PowerShell to the corresponding path.
Some older Codex clients use `~/.codex/skills`; follow that client's discovered
skill location. Start a new session if the client has not discovered the new skill.
See the official [Codex skill locations](https://developers.openai.com/codex/skills)
and [Claude Code skill locations](https://code.claude.com/docs/en/skills).

Cloud agents need the catalog and CAD runtime mounted in their execution environment;
copying the skill alone does not provide access to files on your computer.

## Use

In Codex, invoke `$makers-supply-cad`. In Claude Code, invoke `/makers-supply-cad`.
For example:

> Use makers-supply-cad with the catalog at /path/to/archive. Find the EA028 bearing,
> prepare its STEP reference, and use my connected Extrudo to design a parametric
> housing. Keep the bearing source and rights information in the hardware BOM.

For Extrudo, connect its desktop MCP using the configuration in Settings → Desktop →
Agents and load its own CAD skill as described in the
[tool reference](makers-supply-cad/references/cad-tools.md). This catalog skill works
alongside that skill. It does not configure clients or install third-party bridges.

For SolidCraft, use its built-in stdio MCP server and bundled modeling/checking
skills. The [SolidCraft guide](makers-supply-cad/references/solidcraft.md) covers
isolated and desktop sessions, project file access, native STEP import, and a
runnable catalog-bearing housing example using the released CLI.
The [desktop MCP example](makers-supply-cad/references/solidcraft-desktop.md) also
builds and checks the housing in a native app, with a window screenshot and stable
save/export paths. It requires a separate pristine test design.

You can also run the helper directly, from any directory:

```bash
python /path/to/skills/makers-supply-cad/scripts/catalog.py \
  --catalog /path/to/archive search "bearing" --region eu --limit 5
```

Search and inspection are read-only. Export writes chosen files and a provenance
manifest to a new output directory after checking their hashes and sizes. The
archive's original files and private build progress are preserved.

For an executable CAD example, run the [tested Extrudo EA028 housing workflow](makers-supply-cad/references/extrudo-e2e.md).
It uses an optional, separate Extrudo source runtime and Node 24+ to produce an
editable native assembly plus housing-only STEP/STL/3MF files, with geometry and
interference checks. The native file was also opened in Extrudo's web app.

## Maintain and validate

The catalog and SolidCraft adapters have separate tests. Run from the repository:

```bash
uv run pytest tests/test_agent_catalog.py tests/test_solidcraft_adapter.py tests/test_solidcraft_desktop.py
uv run ruff check skills tests/test_agent_catalog.py tests/test_solidcraft_adapter.py tests/test_solidcraft_desktop.py
python scripts/build-agent-skills.py
```

The build command writes a ZIP for each skill under `dist/agent-skills/`, including
its license and helper while excluding Python caches. Extract the skill folder into
the destination above. It packages instructions and code, without catalog data.

The CAD reference records upstream research separately from local verification.
Check the installed CAD version's schema and capabilities before use. Update source
links and guidance when upstream interfaces change. The skill is MIT licensed;
mirrored third-party models and documents retain their own recorded rights.
