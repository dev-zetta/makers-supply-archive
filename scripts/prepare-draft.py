#!/usr/bin/env python3
"""Assemble a validated candidate; this command never publishes a release."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import tarfile
from pathlib import Path

from makers_supply import __version__
from makers_supply.release import PACK_LIMIT, ReleaseManifest, write_checksums
from makers_supply.release_evidence import verify_acceptance
from makers_supply.storage import atomic_write, snapshot_identity
from makers_supply.validation import sha256_file

PLATFORMS = {"linux-x86_64", "windows-x86_64", "macos-x86_64", "macos-arm64"}


def gh_json(*args: str, optional: bool = False) -> object:
    result = subprocess.run(["gh", *args], text=True, capture_output=True)
    if result.returncode:
        if optional and "404" in result.stderr:
            return None
        raise RuntimeError(result.stderr)
    return json.loads(result.stdout)


def find_release(repository: str, tag: str) -> dict[str, object] | None:
    # The by-tag endpoint only returns published releases. Authenticated listings
    # include drafts, including ones whose Git tag has not been created yet.
    pages = gh_json("api", "--paginate", "--slurp", f"repos/{repository}/releases?per_page=100")
    if not isinstance(pages, list) or any(not isinstance(page, list) for page in pages):
        raise ValueError("invalid release listing")
    matches = [
        release
        for page in pages
        for release in page
        if isinstance(release, dict) and release.get("tag_name") == tag
    ]
    if len(matches) > 1:
        raise ValueError("refusing an ambiguous release tag")
    return matches[0] if matches else None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    revision = os.environ["GITHUB_SHA"]
    repository = os.environ["GITHUB_REPOSITORY"]
    version = os.environ["RELEASE_VERSION"]
    if version != __version__ or not re.fullmatch(r"\d+\.\d+\.\d+", version):
        raise ValueError("release version must match package metadata")
    tag = f"v{version}"
    directory = args.directory.resolve()
    release = ReleaseManifest.model_validate_json(
        (directory / "release-manifest.json").read_bytes()
    )
    if (
        release.revision != revision
        or release.app_version != version
        or release.snapshot_id != snapshot_identity(root)
    ):
        raise ValueError("shared data does not match the candidate commit")
    verify_acceptance(root, directory / "release-validation.json")
    for pack in release.packs:
        path = directory / pack.name
        if path.name != pack.name or path.stat().st_size != pack.size:
            raise ValueError(f"invalid data pack: {pack.name}")
        if pack.size > PACK_LIMIT or sha256_file(path) != pack.sha256:
            raise ValueError(f"data pack checksum/size mismatch: {pack.name}")
    records = []
    for path in sorted(args.evidence.rglob("validation.json")):
        record = json.loads(path.read_text())
        if (
            record.get("passed") is not True
            or record.get("version") != version
            or record.get("revision") != revision
            or record.get("snapshot_id") != release.snapshot_id
        ):
            raise ValueError(f"invalid platform acceptance: {path}")
        app = directory / record["app_archive"]
        if app.name != record["app_archive"] or sha256_file(app) != record["app_sha256"]:
            raise ValueError("platform evidence does not match the attached app")
        records.append(record)
    if len(records) != 4 or {r["platform"] for r in records} != PLATFORMS:
        raise ValueError("exactly four successful platform acceptance records are required")
    atomic_write(
        directory / "RELEASE-EVIDENCE.json",
        json.dumps(
            {
                "revision": revision,
                "snapshot_id": release.snapshot_id,
                "validation_run": os.environ["RELEASE_RUN_URL"],
                "platforms": records,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
    )
    with tarfile.open(directory / "platform-evidence.tar.gz", "w:gz") as archive:
        archive.add(args.evidence, arcname="platform-evidence")
    notes = root / "RELEASE.md"
    atomic_write(directory / "RELEASE-NOTES.md", notes.read_text())
    for path in directory.iterdir():
        if path.is_file() and path.stat().st_size >= 2 * 1024**3:
            raise ValueError(f"release asset exceeds GitHub's limit: {path.name}")
    write_checksums(directory)
    existing = find_release(repository, tag)
    if existing is not None and (
        not isinstance(existing, dict)
        or not existing.get("draft")
        or existing.get("target_commitish") != revision
    ):
        raise ValueError("refusing to replace a public release or a different commit")
    ref = gh_json("api", f"repos/{repository}/git/ref/tags/{tag}", optional=True)
    if ref is not None:
        commit = gh_json("api", f"repos/{repository}/commits/{tag}")
        if not isinstance(commit, dict) or commit.get("sha") != revision:
            raise ValueError("refusing to reuse a tag pointing to another commit")
    if existing is None:
        subprocess.run(
            [
                "gh",
                "release",
                "create",
                tag,
                "--repo",
                repository,
                "--draft",
                "--target",
                revision,
                "--title",
                f"Maker's Supply {tag}",
                "--notes-file",
                str(directory / "RELEASE-NOTES.md"),
            ],
            check=True,
        )
    subprocess.run(
        [
            "gh",
            "release",
            "upload",
            tag,
            "--repo",
            repository,
            "--clobber",
            *[str(p) for p in sorted(directory.iterdir()) if p.is_file()],
        ],
        check=True,
    )
    verified = find_release(repository, tag)
    if (
        verified is None
        or verified.get("draft") is not True
        or verified.get("target_commitish") != revision
    ):
        raise RuntimeError("release is unexpectedly not the candidate draft")
    print(f"prepared unpublished {tag} at {revision}")


if __name__ == "__main__":
    main()
