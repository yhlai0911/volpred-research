"""Regression coverage for scripts/repin_provider_identity.py.

2026-08-05/06: the executable and settings_surface pins in
config/provider_registry.json drifted three times in two days (CLI
auto-upgrade + a settings.json edit), each time stopping every provider
spawn until someone manually recomputed the sha256 and wrote it back. This
tool is the one-click replacement for that manual step
(next_tasks.json#assign_4e4e8030); these tests pin its behavior against a
throwaway registry + files so the real registry/CLI never has to move.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "repin_provider_identity", ROOT / "scripts" / "repin_provider_identity.py"
    )
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    return mod


MOD = _load_module()


@pytest.fixture()
def sandbox(tmp_path, monkeypatch):
    settings = tmp_path / "settings.json"
    settings.write_text('{"a": 1}', encoding="utf-8")
    actual_sha = MOD._sha256_file(settings)

    registry_path = tmp_path / "provider_registry.json"
    registry = {
        "providers": [
            {
                "provider_id": "widget-cli",
                "executables": [{"realpath": "/opt/widget/1.0", "sha256": "0" * 64}],
                "auth": {
                    "settings_surface": {
                        "path": "settings.json",
                        "sha256": "stale" + "0" * 59,
                    }
                },
            }
        ]
    }
    registry_path.write_text(json.dumps(registry), encoding="utf-8")

    monkeypatch.setattr(MOD, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(MOD, "REGISTRY_PATH", registry_path)
    return {"registry_path": registry_path, "actual_sha": actual_sha}


def test_check_reports_settings_surface_drift(sandbox, monkeypatch, capsys):
    monkeypatch.setattr(MOD.shutil, "which", lambda _name: None)
    rc = MOD.cmd_check(argparse_ns())
    out = capsys.readouterr().out
    assert rc == 1
    assert "DRIFT" in out
    assert sandbox["actual_sha"] in out


def test_pin_settings_surface_dry_run_does_not_write(sandbox):
    before = sandbox["registry_path"].read_text(encoding="utf-8")
    rc = MOD.cmd_pin_settings_surface(argparse_ns(provider="widget-cli", apply=False))
    assert rc == 1
    assert sandbox["registry_path"].read_text(encoding="utf-8") == before


def test_pin_settings_surface_apply_writes_recomputed_sha(sandbox):
    rc = MOD.cmd_pin_settings_surface(argparse_ns(provider="widget-cli", apply=True))
    assert rc == 0
    registry = json.loads(sandbox["registry_path"].read_text(encoding="utf-8"))
    written = registry["providers"][0]["auth"]["settings_surface"]["sha256"]
    assert written == sandbox["actual_sha"]


def test_add_executable_appends_without_touching_existing_pins(sandbox, tmp_path):
    new_binary = tmp_path / "widget-2.0"
    new_binary.write_bytes(b"new version bytes")
    rc = MOD.cmd_add_executable(
        argparse_ns(provider="widget-cli", path=str(new_binary), apply=True)
    )
    assert rc == 0
    registry = json.loads(sandbox["registry_path"].read_text(encoding="utf-8"))
    execs = registry["providers"][0]["executables"]
    assert len(execs) == 2
    assert execs[0] == {"realpath": "/opt/widget/1.0", "sha256": "0" * 64}
    assert execs[1]["realpath"] == str(new_binary)
    assert execs[1]["sha256"] == MOD._sha256_file(new_binary)


def test_add_executable_refuses_to_silently_overwrite_a_changed_pinned_file(
    sandbox, tmp_path
):
    pinned = tmp_path / "already-pinned"
    pinned.write_bytes(b"original bytes")
    original_sha = MOD._sha256_file(pinned)
    registry = json.loads(sandbox["registry_path"].read_text(encoding="utf-8"))
    registry["providers"][0]["executables"].append(
        {"realpath": str(pinned), "sha256": original_sha}
    )
    sandbox["registry_path"].write_text(json.dumps(registry), encoding="utf-8")

    pinned.write_bytes(b"tampered bytes")  # file content changed under a pinned path
    rc = MOD.cmd_add_executable(
        argparse_ns(provider="widget-cli", path=str(pinned), apply=True)
    )
    assert rc == 1
    reread = json.loads(sandbox["registry_path"].read_text(encoding="utf-8"))
    entry = next(
        e for e in reread["providers"][0]["executables"] if e["realpath"] == str(pinned)
    )
    assert entry["sha256"] == original_sha  # not overwritten


def argparse_ns(**kwargs):
    import argparse

    return argparse.Namespace(**kwargs)
