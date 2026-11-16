#!/usr/bin/env python3
"""Install an already built, pinned Chili3D checkout and official bridge for one user."""

from __future__ import annotations

import argparse
import hashlib
import json
import shlex
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

LAUNCHER = """#!/usr/bin/env python3
import argparse, http.server, json, subprocess, sys, time, urllib.request, webbrowser
from pathlib import Path
ROOT = Path(__file__).resolve().parent
PORT = __PORT__
URL = f"http://127.0.0.1:{PORT}"
STATE = Path.home() / ".local/state/makers-supply/chili3d-0.8.0"
def healthy():
    try:
        with urllib.request.urlopen(URL + "/makers-supply-install.json", timeout=2) as response:
            expected = json.loads((ROOT / "web/makers-supply-install.json").read_text())
            return json.load(response) == expected
    except (OSError, ValueError):
        return False
parser = argparse.ArgumentParser()
parser.add_argument("--serve", action="store_true")
parser.add_argument("--no-open", action="store_true")
args = parser.parse_args()
if args.serve:
    from functools import partial
    handler = partial(http.server.SimpleHTTPRequestHandler, directory=str(ROOT / "web"))
    http.server.ThreadingHTTPServer(("127.0.0.1", PORT), handler).serve_forever()
    sys.exit(0)
STATE.mkdir(parents=True, exist_ok=True)
if not healthy():
    with (STATE / "web.log").open("ab") as log:
        server = subprocess.Popen(
            [sys.executable, str(ROOT / "launch.py"), "--serve"],
            stdout=log, stderr=log, start_new_session=True)
    for _ in range(40):
        if healthy(): break
        if server.poll() is not None:
            raise SystemExit("Local app server failed; inspect " + str(STATE / "web.log"))
        time.sleep(0.1)
    else: raise SystemExit("Local app server did not become ready")
subprocess.run([str(ROOT / "chili3d-mcp"), "start", "--app-url", URL, "--no-open"], check=True)
if not args.no_open:
    with (STATE / "bridge/session.json").open() as stream:
        session = json.load(stream)
    webbrowser.open(URL + "/?bridge=" + str(session["port"]))
"""


def revision(source: Path) -> str:
    return subprocess.check_output(
        ["git", "-C", str(source), "rev-parse", "HEAD"], text=True
    ).strip()


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--app-source", type=Path, required=True)
    p.add_argument("--bridge-source", type=Path, required=True)
    p.add_argument("--prefix", type=Path, default=Path.home() / ".local")
    p.add_argument("--port", type=int, default=18080)
    args = p.parse_args()
    source, bridge = args.app_source.resolve(), args.bridge_source.resolve()
    if json.loads((source / "package.json").read_text())["version"] != "0.8.0":
        p.error("This installer is verified for Chili3D 0.8.0")
    if json.loads((bridge / "package.json").read_text())["version"] != "0.1.0":
        p.error("This installer is verified for the official MCP bridge 0.1.0")
    if not (source / "dist/index.html").is_file() or not (bridge / "node_modules/ws").is_dir():
        p.error("Build the app and npm ci the bridge first")
    node = shutil.which("node")
    if node is None:
        p.error("Node.js 20+ is required")
    target = args.prefix.resolve() / "share/makers-supply/cad/chili3d/0.8.0"
    if target.exists():
        p.error(f"Installation already exists: {target}")
    for path in [args.prefix / "bin/chili3d", args.prefix / "bin/chili3d-mcp"]:
        if path.exists() or path.is_symlink():
            p.error(f"Launcher already exists: {path}")
    target.mkdir(parents=True)
    shutil.copytree(source / "dist", target / "web")
    # Dependency distributions (notably the MCP SDK) live in nested dist/ folders.
    shutil.copytree(bridge, target / "bridge", ignore=shutil.ignore_patterns(".git"))
    shutil.copy2(source / "LICENSE", target / "LICENSE-chili3d")
    # Keep the exact corresponding source as well as the upstream commit URL.
    with (target / "source.tar").open("wb") as stream:
        subprocess.run(["git", "-C", str(source), "archive", "HEAD"], stdout=stream, check=True)
    patch = subprocess.check_output(["git", "-C", str(source), "diff", "HEAD"], text=True)
    if patch:
        (target / "integration.patch").write_text(patch)
    receipt: dict[str, Any] = {
        "app_version": "0.8.0",
        "app_revision": revision(source),
        "bridge_version": "0.1.0",
        "bridge_revision": revision(bridge),
        "source_url": "https://github.com/xiangechen/chili3d/releases/tag/0.8.0",
        "integration_patch_sha256": hashlib.sha256(patch.encode()).hexdigest() if patch else None,
    }
    (target / "web/makers-supply-install.json").write_text(json.dumps(receipt, indent=2) + "\n")
    launch = target / "launch.py"
    launch.write_text(LAUNCHER.replace("__PORT__", str(args.port)))
    launch.chmod(0o755)
    wrapper = target / "chili3d-mcp"
    app_url = f"http://127.0.0.1:{args.port}"
    wrapper.write_text(
        "#!/bin/sh\nexport CHILI3D_APP_URL="
        + shlex.quote(app_url)
        + '\nexport CHILI3D_MCP_HOME="$HOME/.local/state/makers-supply/chili3d-0.8.0/bridge"\n'
        + 'if [ "$1" = "mcp" ]; then\n  '
        + shlex.quote(sys.executable)
        + " "
        + shlex.quote(str(launch))
        + ' --no-open >&2 || exit $?\nfi\nexec '
        + shlex.quote(node)
        + " "
        + shlex.quote(str(target / "bridge/bin/chili3d-mcp.mjs"))
        + ' "$@"\n'
    )
    wrapper.chmod(0o755)
    binaries = args.prefix / "bin"
    binaries.mkdir(parents=True, exist_ok=True)
    (binaries / "chili3d").symlink_to(launch)
    (binaries / "chili3d-mcp").symlink_to(wrapper)
    applications = args.prefix / "share/applications"
    applications.mkdir(parents=True, exist_ok=True)
    (applications / "chili3d-local.desktop").write_text(
        "[Desktop Entry]\nType=Application\nName=Chili3D 0.8.0\n"
        "Comment=Local parametric CAD with official MCP bridge\n"
        + 'Exec="'
        + str(binaries / "chili3d")
        + '"\nTerminal=false\nCategories=Graphics;Engineering;\n'
    )
    hashes = {
        str(f.relative_to(target)): hashlib.sha256(f.read_bytes()).hexdigest()
        for f in (target / "web").rglob("*")
        if f.is_file()
    }
    receipt["web_sha256"] = hashes
    (target / "install-receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps({"installed": str(target), "launcher": str(binaries / "chili3d")}))


if __name__ == "__main__":
    main()
