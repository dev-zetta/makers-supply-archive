#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import platform
import shutil
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

from makers_supply import __version__
from makers_supply.portable import build_portable_catalog
from makers_supply.release import INSTALLATION, write_bundled_manifest, write_checksums
from makers_supply.storage import Catalog, atomic_write


def platform_tag() -> str:
    systems = {"darwin": "macos", "linux": "linux", "win32": "windows"}
    system = systems.get(sys.platform, sys.platform)
    machine = platform.machine().casefold().replace("amd64", "x86_64").replace("aarch64", "arm64")
    return f"{system}-{machine}"


def clear_linux_executable_stacks(directory: Path) -> None:
    """Clear stale executable-stack flags in bundled ELF libraries."""
    if sys.platform != "linux":
        return
    for path in directory.rglob("*"):
        if not path.is_file():
            continue
        with path.open("r+b") as stream:
            header = stream.read(64)
            if len(header) < 52 or header[:4] != b"\x7fELF":
                continue
            elf_class, byte_order = header[4], header[5]
            endian = "<" if byte_order == 1 else ">" if byte_order == 2 else ""
            if not endian or elf_class not in {1, 2}:
                continue
            if elf_class == 2:
                program_offset = struct.unpack_from(f"{endian}Q", header, 32)[0]
                entry_size, entry_count = struct.unpack_from(f"{endian}HH", header, 54)
                flags_offset = 4
            else:
                program_offset = struct.unpack_from(f"{endian}I", header, 28)[0]
                entry_size, entry_count = struct.unpack_from(f"{endian}HH", header, 42)
                flags_offset = 24
            for index in range(entry_count):
                entry_offset = program_offset + index * entry_size
                stream.seek(entry_offset)
                entry = stream.read(entry_size)
                if len(entry) != entry_size:
                    break
                segment_type = struct.unpack_from(f"{endian}I", entry, 0)[0]
                if segment_type != 0x6474E551:  # PT_GNU_STACK
                    continue
                flags = struct.unpack_from(f"{endian}I", entry, flags_offset)[0]
                if flags & 1:  # PF_X
                    stream.seek(entry_offset + flags_offset)
                    stream.write(struct.pack(f"{endian}I", flags & ~1))


def build_electron_shell(project_root: Path, workspace: Path, backend: Path) -> Path:
    desktop = project_root / "apps/catalog-desktop"
    builder = desktop / "node_modules/.bin/electron-builder"
    if sys.platform == "win32":
        builder = builder.with_suffix(".cmd")
    if not builder.is_file():
        raise FileNotFoundError(f"Electron dependencies are missing; run npm ci in {desktop}")

    electron_output = workspace / "electron-dist"
    config = workspace / "electron-builder.json"
    atomic_write(
        config,
        json.dumps(
            {
                "appId": "org.makerssupply.catalog",
                "productName": "Maker's Supply Catalog",
                "asar": True,
                "npmRebuild": False,
                "directories": {
                    "app": str(desktop),
                    "output": str(electron_output),
                },
                "files": ["main.cjs", "package.json"],
                "extraResources": [{"from": str(backend), "to": "backend"}],
                "linux": {
                    "category": "Utility",
                    "executableName": "makers-supply-catalog",
                    "target": "dir",
                },
                "mac": {"category": "public.app-category.utilities", "target": "dir"},
                "win": {"executableName": "makers-supply-catalog", "target": "dir"},
            },
            indent=2,
        )
        + "\n",
    )
    command = [str(builder), "--dir", "--config", str(config)]
    if sys.platform == "win32":
        command = ["cmd.exe", "/d", "/s", "/c", subprocess.list2cmdline(command)]
    subprocess.run(command, cwd=desktop, check=True)

    candidates = [path for path in electron_output.iterdir() if path.is_dir()]
    if len(candidates) != 1:
        names = ", ".join(path.name for path in candidates) or "none"
        raise RuntimeError(f"expected one unpacked Electron app, found: {names}")
    return candidates[0]


def main() -> None:
    project_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(
        description="Build a login-free, portable Maker's Supply Catalog app"
    )
    parser.add_argument("--root", type=Path, default=project_root)
    parser.add_argument("--output", type=Path, default=Path("dist/standalone"))
    parser.add_argument("--no-archive", action="store_true")
    parser.add_argument("--layout", choices=("bundled", "split"), default="bundled")
    parser.add_argument("--revision", default=None)
    args = parser.parse_args()
    revision = (
        args.revision
        or subprocess.check_output(
            ["git", "-C", str(project_root), "rev-parse", "HEAD"], text=True
        ).strip()
    )

    try:
        import PyInstaller.__main__
    except ImportError as error:
        parser.error(
            "PyInstaller is not installed; run with --package makers-supply-web --extra standalone"
        )
        raise AssertionError from error

    root = args.root.resolve()
    output = args.output.resolve()
    destination = output / f"makers-supply-catalog-{platform_tag()}"
    if destination.exists():
        parser.error(f"destination already exists: {destination}")
    output.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="makers-supply-build-", dir=output) as temporary:
        workspace = Path(temporary)
        portable = (
            build_portable_catalog(Catalog(root), workspace / "portable")
            if args.layout == "bundled"
            else None
        )
        pyinstaller_dist = workspace / "pyinstaller-dist"
        PyInstaller.__main__.run(
            [
                "--noconfirm",
                "--clean",
                "--onedir",
                "--console",
                "--name",
                "makers-supply-backend",
                "--paths",
                str(project_root / "src"),
                "--paths",
                str(project_root / "apps/catalog-web/src"),
                "--collect-data",
                "makers_supply_web",
                "--distpath",
                str(pyinstaller_dist),
                "--workpath",
                str(workspace / "pyinstaller-work"),
                "--specpath",
                str(workspace / "pyinstaller-spec"),
                str(project_root / "scripts/standalone_entry.py"),
            ]
        )
        backend = pyinstaller_dist / "makers-supply-backend"
        clear_linux_executable_stacks(backend)
        electron_app = build_electron_shell(project_root, workspace, backend)
        shutil.move(electron_app, destination)
        if portable:
            shutil.move(portable.database, destination / "catalog.sqlite")
            shutil.move(portable.assets, destination / "assets")
            write_bundled_manifest(Catalog(root), destination, revision=revision)
        for filename in ("LICENSE", "NOTICE.md"):
            shutil.copyfile(project_root / filename, destination / filename)
        atomic_write(destination / "INSTALL.txt", INSTALLATION)
        atomic_write(
            destination / "app-build.json",
            json.dumps(
                {
                    "version": __version__,
                    "revision": revision,
                    "platform": platform_tag(),
                    "layout": args.layout,
                },
                sort_keys=True,
                indent=2,
            )
            + "\n",
        )
        atomic_write(
            destination / "README.txt",
            "Maker's Supply Catalog — standalone desktop app\n"
            "\n"
            "Run makers-supply-catalog on Linux, makers-supply-catalog.exe on Windows, "
            "or the Maker's Supply Catalog app on macOS. The catalog opens in its own "
            "application window. No Docker installation, account, password, or internet "
            "connection is required.\n"
            "\n"
            "Keep catalog.sqlite and the assets folder in this directory. Assets are ordinary "
            "files grouped by product ID, then into shallow Images, Models, Archives, "
            "Documents, and Other folders. They retain their original filenames. Closing the "
            "app window also stops its private local service.\n",
        )

    archive: Path | None = None
    if not args.no_archive:
        archive_format = "zip" if sys.platform == "win32" else "gztar"
        archive = Path(
            shutil.make_archive(
                str(output / f"makers-supply-catalog-{__version__}-{platform_tag()}"),
                archive_format,
                destination if args.layout == "split" else destination.parent,
                "." if args.layout == "split" else destination.name,
            )
        )
    print(f"built {destination}")
    if portable:
        print(f"materialized {portable.file_count} named asset files")
    if archive:
        print(f"archive {archive}")
    write_checksums(output)


if __name__ == "__main__":
    main()
