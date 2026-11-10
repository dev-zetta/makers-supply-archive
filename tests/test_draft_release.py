import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import pytest

from makers_supply import __version__


@pytest.mark.parametrize(
    "pages",
    [
        [{"tag_name": "v1.1.0"}],
        [[{"tag_name": "v1.1.0"}], [{"tag_name": "v1.1.0"}]],
    ],
)
def test_draft_lookup_rejects_invalid_or_ambiguous_listings(
    monkeypatch: pytest.MonkeyPatch, pages: object
) -> None:
    script = Path(__file__).parents[1] / "scripts/prepare-draft.py"
    spec = importlib.util.spec_from_file_location("prepare_draft_lookup_test", script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "gh_json", lambda *_: pages)
    with pytest.raises(ValueError, match="invalid|ambiguous"):
        module.find_release("owner/repo", "v1.1.0")


@pytest.mark.parametrize(
    "case", ["published", "other-draft", "other-tag", "same-draft", "new-draft"]
)
def test_draft_guards_never_publish_or_replace_other_commits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, case: str
) -> None:
    script = Path(__file__).parents[1] / "scripts/prepare-draft.py"
    spec = importlib.util.spec_from_file_location("prepare_draft_test", script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    packet = tmp_path / "release"
    packet.mkdir()
    evidence = tmp_path / "evidence"
    snapshot, revision = "a" * 64, "b" * 40
    (packet / "release-validation.json").write_text("{}")
    (packet / "release-manifest.json").write_text(
        json.dumps(
            {
                "snapshot_id": snapshot,
                "revision": revision,
                "app_version": __version__,
                "data_manifest_sha256": "c" * 64,
                "packs": [],
            }
        )
    )
    for platform in module.PLATFORMS:
        app = packet / f"{platform}.zip"
        app.write_bytes(platform.encode())
        directory = evidence / platform
        directory.mkdir(parents=True)
        (directory / "validation.json").write_text(
            json.dumps(
                {
                    "passed": True,
                    "version": __version__,
                    "revision": revision,
                    "snapshot_id": snapshot,
                    "platform": platform,
                    "app_archive": app.name,
                    "app_sha256": hashlib.sha256(app.read_bytes()).hexdigest(),
                }
            )
        )
    monkeypatch.setattr(module, "snapshot_identity", lambda _: snapshot)
    monkeypatch.setattr(module, "verify_acceptance", lambda *_: None)
    monkeypatch.setenv("GITHUB_SHA", revision)
    monkeypatch.setenv("GITHUB_REPOSITORY", "owner/repo")
    monkeypatch.setenv("RELEASE_VERSION", __version__)
    monkeypatch.setenv("RELEASE_RUN_URL", "https://example.com/run")
    commands = []
    monkeypatch.setattr(module.subprocess, "run", lambda cmd, **_: commands.append(cmd))

    def gh(*args: str, **_: object) -> object:
        endpoint = args[-1]
        if "/git/ref/" in endpoint:
            return {} if case == "other-tag" else None
        if "/commits/" in endpoint:
            return {"sha": "wrong"}
        assert args[:3] == ("api", "--paginate", "--slurp")
        assert endpoint == "repos/owner/repo/releases?per_page=100"
        if case == "other-tag" or (case == "new-draft" and not commands):
            return [[]]
        return [
            [{"tag_name": "v0.0.1"}],
            [
                {
                    "tag_name": f"v{__version__}",
                    "draft": case != "published",
                    "target_commitish": "wrong" if case == "other-draft" else revision,
                }
            ],
        ]

    monkeypatch.setattr(module, "gh_json", gh)
    monkeypatch.setattr(
        sys, "argv", [str(script), "--directory", str(packet), "--evidence", str(evidence)]
    )
    if case in {"same-draft", "new-draft"}:
        module.main()
        assert commands[-1][:3] == ["gh", "release", "upload"]
        if case == "new-draft":
            assert len(commands) == 2
            assert commands[0][:3] == ["gh", "release", "create"]
            assert "--draft" in commands[0]
        else:
            assert len(commands) == 1
    else:
        with pytest.raises(ValueError, match="refusing"):
            module.main()
        assert commands == []
