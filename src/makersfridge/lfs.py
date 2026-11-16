from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class LfsReport:
    files: int
    bytes: int
    largest_file: int
    errors: tuple[str, ...]


def lfs_preflight(
    root: Path,
    *,
    max_total_bytes: int,
    max_file_bytes: int,
    require_git_lfs: bool = True,
) -> LfsReport:
    errors: list[str] = []
    if require_git_lfs:
        result = subprocess.run(
            ["git", "lfs", "version"],
            cwd=root,
            capture_output=True,
            check=False,
            text=True,
        )
        if result.returncode != 0:
            errors.append("Git LFS is not installed or is not available on PATH")
    blobs = [path for path in (root / "data" / "blobs").rglob("*") if path.is_file()]
    sizes = [path.stat().st_size for path in blobs]
    total = sum(sizes)
    largest = max(sizes, default=0)
    if total > max_total_bytes:
        errors.append(f"blob total {total} exceeds configured limit {max_total_bytes}")
    for path in blobs:
        size = path.stat().st_size
        if size > max_file_bytes:
            errors.append(
                f"{path.relative_to(root).as_posix()} is {size} bytes; limit is {max_file_bytes}"
            )
    return LfsReport(len(blobs), total, largest, tuple(errors))

