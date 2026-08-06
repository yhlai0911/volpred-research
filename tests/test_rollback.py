import io
import subprocess
import tarfile
from pathlib import Path

import pytest

from volpred.ops import rollback


def _run(*args: str, cwd: Path):
    subprocess.run(args, cwd=cwd, check=True, capture_output=True, text=True)


def test_create_and_restore_rollback_point(tmp_path: Path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    _run("git", "init", "-b", "main", cwd=repo)
    _run("git", "config", "user.email", "test@example.com", cwd=repo)
    _run("git", "config", "user.name", "Test User", cwd=repo)

    (repo / "tracked.txt").write_text("base\n", encoding="utf-8")
    (repo / "storage").mkdir()
    (repo / "storage" / "state.json").write_text('{"value":"baseline"}\n', encoding="utf-8")
    (repo / "config").mkdir()
    (repo / "config" / "settings.json").write_text('{"mode":"baseline"}\n', encoding="utf-8")
    _run("git", "add", "tracked.txt", "storage/state.json", "config/settings.json", cwd=repo)
    _run("git", "commit", "-m", "baseline", cwd=repo)

    (repo / "tracked.txt").write_text("dirty baseline\n", encoding="utf-8")
    (repo / "baseline_note.txt").write_text("keep me\n", encoding="utf-8")

    monkeypatch.setattr(rollback, "project_path", lambda *parts: repo.joinpath(*parts))

    manifest = rollback.create_rollback_point(point_id="rb_test", storage_dir="storage")
    assert manifest["point_id"] == "rb_test"
    assert (repo / "storage" / "ops" / "rollback_points" / "rb_test" / "manifest.json").exists()

    (repo / "tracked.txt").write_text("mutated after baseline\n", encoding="utf-8")
    (repo / "storage" / "state.json").write_text('{"value":"after"}\n', encoding="utf-8")
    (repo / "config" / "settings.json").write_text('{"mode":"after"}\n', encoding="utf-8")
    (repo / "extra_after.txt").write_text("remove me\n", encoding="utf-8")

    dry_run = rollback.restore_rollback_point("rb_test", storage_dir="storage", dry_run=True)
    assert "extra_after.txt" in dry_run["extra_untracked"]

    rollback.restore_rollback_point("rb_test", storage_dir="storage", force=True)

    assert (repo / "tracked.txt").read_text(encoding="utf-8") == "dirty baseline\n"
    assert (repo / "storage" / "state.json").read_text(encoding="utf-8") == '{"value":"baseline"}\n'
    assert (repo / "config" / "settings.json").read_text(encoding="utf-8") == '{"mode":"baseline"}\n'
    assert (repo / "baseline_note.txt").exists()
    assert not (repo / "extra_after.txt").exists()


def test_create_rollback_point_excludes_rollback_archives_from_storage_snapshot(tmp_path: Path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    _run("git", "init", "-b", "main", cwd=repo)
    _run("git", "config", "user.email", "test@example.com", cwd=repo)
    _run("git", "config", "user.name", "Test User", cwd=repo)

    (repo / "tracked.txt").write_text("base\n", encoding="utf-8")
    (repo / "storage").mkdir()
    (repo / "storage" / "state.json").write_text('{"value":"baseline"}\n', encoding="utf-8")
    _run("git", "add", "tracked.txt", "storage/state.json", cwd=repo)
    _run("git", "commit", "-m", "baseline", cwd=repo)

    monkeypatch.setattr(rollback, "project_path", lambda *parts: repo.joinpath(*parts))

    rollback.create_rollback_point(point_id="rb_archive_guard", storage_dir="storage")

    point_dir = repo / "storage" / "ops" / "rollback_points" / "rb_archive_guard"
    storage_archive = point_dir / "storage.tar.gz"
    untracked_archive = point_dir / "untracked.tar.gz"

    with tarfile.open(storage_archive, "r:gz") as tar:
        storage_names = tar.getnames()
    assert "storage/state.json" in storage_names
    assert not any("rollback_points" in name for name in storage_names)

    if untracked_archive.exists():
        with tarfile.open(untracked_archive, "r:gz") as tar:
            untracked_names = tar.getnames()
        assert not any("rollback_points" in name for name in untracked_names)


def test_safe_extract_rejects_path_traversal_before_writing(tmp_path: Path):
    archive = tmp_path / "traversal.tar.gz"
    payload = b"escape"
    with tarfile.open(archive, "w:gz") as tar:
        member = tarfile.TarInfo("../../outside.txt")
        member.size = len(payload)
        tar.addfile(member, io.BytesIO(payload))

    destination = tmp_path / "restore"
    destination.mkdir()
    with tarfile.open(archive, "r:gz") as tar:
        with pytest.raises(RuntimeError, match="Unsafe rollback archive member"):
            rollback._safe_extract_archive(tar, destination)

    assert not (tmp_path / "outside.txt").exists()
    assert not any(destination.iterdir())


def test_safe_extract_rejects_symlink_outside_destination(tmp_path: Path):
    archive = tmp_path / "symlink.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        member = tarfile.TarInfo("storage/escape-link")
        member.type = tarfile.SYMTYPE
        member.linkname = "../../outside.txt"
        tar.addfile(member)

    destination = tmp_path / "restore"
    destination.mkdir()
    with tarfile.open(archive, "r:gz") as tar:
        with pytest.raises(RuntimeError, match="Unsafe rollback archive member"):
            rollback._safe_extract_archive(tar, destination)

    assert not any(destination.iterdir())


def test_manifest_owned_paths_cannot_escape_rollback_point(tmp_path: Path):
    point_dir = tmp_path / "point"
    point_dir.mkdir()
    with pytest.raises(RuntimeError, match="escapes its point directory"):
        rollback._point_file(point_dir, "../../outside.tar.gz")


def test_rollback_point_id_cannot_escape_rollback_root(tmp_path: Path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    monkeypatch.setattr(rollback, "project_path", lambda *parts: repo.joinpath(*parts))

    with pytest.raises(RuntimeError, match="escapes rollback root"):
        rollback.create_rollback_point(point_id="../../outside")

    with pytest.raises(RuntimeError, match="escapes rollback root"):
        rollback.restore_rollback_point("../../outside", dry_run=True)
