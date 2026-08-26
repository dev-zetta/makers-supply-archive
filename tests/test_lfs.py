from pathlib import Path
from unittest.mock import Mock, patch

from makers_supply.lfs import lfs_preflight


@patch("makers_supply.lfs.subprocess.run")
def test_lfs_preflight_reports_limits(run: Mock, tmp_path: Path) -> None:
    run.return_value = Mock(returncode=0)
    blobs = tmp_path / "data/blobs/sha256/aa"
    blobs.mkdir(parents=True)
    (blobs / "a.bin").write_bytes(b"1234")
    report = lfs_preflight(tmp_path, max_total_bytes=3, max_file_bytes=3)
    assert report.files == 1
    assert report.bytes == 4
    assert len(report.errors) == 2


@patch("makers_supply.lfs.subprocess.run")
def test_lfs_preflight_requires_git_lfs(run: Mock, tmp_path: Path) -> None:
    run.return_value = Mock(returncode=1)
    report = lfs_preflight(tmp_path, max_total_bytes=10, max_file_bytes=10)
    assert "not installed" in report.errors[0]
