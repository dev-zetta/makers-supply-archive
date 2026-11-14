#!/usr/bin/env python3
"""Build portable Agent Skills ZIPs without caches or machine-specific files."""

from __future__ import annotations

import argparse
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

ROOT = Path(__file__).resolve().parents[1]


def build(output: Path) -> list[Path]:
    output.mkdir(parents=True, exist_ok=True)
    archives = []
    for entrypoint in sorted((ROOT / "skills").glob("*/SKILL.md")):
        skill = entrypoint.parent
        archive_path = output / f"{skill.name}.zip"
        with ZipFile(archive_path, "w", compression=ZIP_DEFLATED) as archive:
            for path in sorted(skill.rglob("*")):
                relative = path.relative_to(skill.parent)
                if "__pycache__" in relative.parts or path.suffix in {".pyc", ".pyo"}:
                    continue
                if path.is_symlink():
                    raise ValueError(f"Skill packages cannot contain symlinks: {path}")
                if not path.is_file():
                    continue
                info = ZipInfo(relative.as_posix(), date_time=(1980, 1, 1, 0, 0, 0))
                info.compress_type = ZIP_DEFLATED
                info.create_system = 3
                info.external_attr = 0o100644 << 16
                archive.writestr(info, path.read_bytes())
        archives.append(archive_path)
    return archives


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "dist" / "agent-skills")
    args = parser.parse_args()
    for path in build(args.output):
        print(path.resolve())


if __name__ == "__main__":
    main()
