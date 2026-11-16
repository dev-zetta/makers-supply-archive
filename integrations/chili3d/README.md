# Local Chili3D file transfer

`export-data.patch` extends Chili3D 0.8.0's existing `export_nodes` tool with an
optional `returnData` boolean. The default browser-download behavior is unchanged.
When requested, the app returns the actual exporter bytes in `dataBase64`; this
lets a local agent write and verify STEP and binary STL files without relying on
browser download permissions or destination settings. It does not expose a
filesystem, shell, arbitrary JavaScript executor or another network listener.

The patch and its upstream test changes are derivative Chili3D code under
AGPL-3.0 (see LICENSE-AGPL.txt). The Python catalog adapter and installer remain
under this repository's MIT license.

Reproduce the tested local installation with Node 24 and Python 3.10+:

```bash
git clone https://github.com/xiangechen/chili3d.git chili3d
git -C chili3d checkout e35a8eecba803a463698f2e49a7404f25c607ba5
git -C chili3d apply /absolute/path/to/makers-supply-archive/integrations/chili3d/export-data.patch
cd chili3d
npm ci
NODE_ENV=production npm run build
cd ..
git clone https://github.com/xiangechen/chili3d-mcp.git chili3d-mcp
git -C chili3d-mcp checkout dd08fe36616a93ee247553f17297535588974173
cd chili3d-mcp
npm ci
npm test
cd ..
python /absolute/path/to/makers-supply-archive/scripts/install-chili3d-local.py \
  --app-source ./chili3d --bridge-source ./chili3d-mcp --port 18081
```

The installer refuses existing target installations/launchers. It stores the
production web build, pinned upstream source archive, local diff, licenses and
hash receipt in `~/.local/share/makers-supply/cad/chili3d/0.8.0/`, and creates
`~/.local/bin/chili3d`, `~/.local/bin/chili3d-mcp` and an application-menu entry.
`chili3d` starts only loopback servers and opens the default browser. The browser
owns the document; save before closing. Server state/logs live in
`~/.local/state/makers-supply/chili3d-0.8.0/`. Stop the bridge with
`chili3d-mcp stop`; it is started on demand rather than at login.

The portable catalog skill's [Chili3D guide](../../skills/makers-supply-cad/references/chili3d.md)
explains unmodified upstream installations as well as this optional transfer route.
