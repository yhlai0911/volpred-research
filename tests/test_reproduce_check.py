from __future__ import annotations

import hashlib
import json
import platform
import subprocess
from pathlib import Path

import pytest

from scripts import reproduce_check


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _spec(entrypoint: str, result: str) -> dict:
    return {
        "schema_version": reproduce_check.SPEC_SCHEMA,
        "entrypoint": {"path": entrypoint, "args": []},
        "canonical_result": result,
        "inputs": [],
        "timeout_seconds": 20,
        "network": "deny",
        "randomness": {
            "status": "declared",
            "seeds": [{"library": "fixture", "value": 7}],
        },
        "comparison": {"rtol": 1e-9, "atol": 1e-12, "ignore_pointers": []},
    }


def test_compare_json_is_strict_about_types_and_nested_metadata() -> None:
    comparison = reproduce_check.compare_json(
        {"n": 10, "value": 1.0, "created_at": "old", "meta": {"created_at": "old"}},
        {"n": 10.0, "value": 1.0 + 5e-13, "created_at": "new", "meta": {"created_at": "new"}},
    )

    assert comparison["mismatch_count"] == 2
    assert {item["path"] for item in comparison["mismatches"]} == {"/n", "/meta/created_at"}


def test_strict_json_rejects_non_finite_numbers() -> None:
    with pytest.raises(ValueError, match="non-finite"):
        reproduce_check._loads_json_strict('{"bad": NaN}')


def test_inventory_filters_unpublished_feed_and_false_paper_token(tmp_path: Path) -> None:
    (tmp_path / "paper" / "p1").mkdir(parents=True)
    (tmp_path / "paper" / "p1" / "experiments.md").write_text(
        "| K1 | primary | `experiments/k1/` |\nMIDAS-RW-K125 is a lag, not an experiment.\n",
        encoding="utf-8",
    )
    (tmp_path / "paper" / "p1" / "main.tex").write_text(
        "Current body adds experiment K3 even though the manifest is stale.\n",
        encoding="utf-8",
    )
    _write_json(
        tmp_path / "storage" / "reports" / "feed.json",
        [
            {
                "status": "published",
                "published_at": "2026-07-14T00:00:00Z",
                "details": {"experiment_refs": ["K2"]},
            },
            {
                "status": "draft",
                "created_at": "2026-07-14T01:00:00Z",
                "details": {"experiment_refs": ["K999"]},
            },
        ],
    )
    k1 = tmp_path / "experiments" / "k1"
    k1.mkdir(parents=True)
    (k1 / "k1.py").write_text("SEED = 7\n", encoding="utf-8")
    _write_json(k1 / "k1_results.json", {"value": 1})
    _write_json(k1 / "reproduce_spec.json", _spec("k1.py", "k1_results.json"))
    k2 = tmp_path / "experiments" / "k2"
    k2.mkdir()
    (k2 / "k2.py").write_text("SEED = 7\n", encoding="utf-8")
    k3 = tmp_path / "experiments" / "k3"
    k3.mkdir()
    (k3 / "k3.py").write_text("SEED = 7\n", encoding="utf-8")
    _write_json(k3 / "k3_results.json", {"value": 3})

    inventory = reproduce_check.build_inventory(tmp_path)

    assert inventory["references"]["priority"] == ["K1", "K2", "K3"]
    assert inventory["counts"]["priority_missing_dirs"] == 0
    assert inventory["counts"]["runnable"] == 1
    assert inventory["counts"]["code_without_results"] == 1
    assert inventory["code_without_results"][0]["experiment"] == "k2"


def test_audit_runs_in_disposable_clone_and_preserves_canonical_result(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    exp = root / "experiments" / "k1"
    exp.mkdir(parents=True)
    payload = {"seed": 7, "value": 1.25}
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n"
    script = (
        "import json\n"
        "from pathlib import Path\n"
        "payload = {'seed': 7, 'value': 1.25}\n"
        "out = Path(__file__).with_name('k1_results.json')\n"
        "out.write_text(json.dumps(payload, sort_keys=True, separators=(',', ':')) + '\\n')\n"
    )
    (exp / "k1.py").write_text(script, encoding="utf-8")
    (exp / "k1_results.json").write_text(encoded, encoding="utf-8")
    _write_json(exp / "reproduce_spec.json", _spec("k1.py", "k1_results.json"))
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.email", "fixture@example.invalid"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "Fixture"], cwd=root, check=True)
    subprocess.run(["git", "add", "."], cwd=root, check=True)
    subprocess.run(["git", "commit", "-qm", "fixture"], cwd=root, check=True)
    before = hashlib.sha256((exp / "k1_results.json").read_bytes()).hexdigest()

    report = reproduce_check.audit_experiment("K1", root=root, timeout=10)

    after = hashlib.sha256((exp / "k1_results.json").read_bytes()).hexdigest()
    if platform.system() == "Darwin" and Path("/usr/bin/sandbox-exec").is_file():
        assert report["outcome"]["status"] == "pass_exact"
        assert report["integrity"] == {"canonical_unchanged": True, "changed_paths": []}
        assert report["canonical_results"][0]["bit_identical"] is True
    else:
        assert report["outcome"]["reason_code"] == "SANDBOX_UNAVAILABLE"
    assert before == after
    assert (exp / "reproduce_report.json").is_file()
    assert reproduce_check.classify_experiment(exp).report_stale is False
    (exp / "k1.py").write_text(script + "# drift\n", encoding="utf-8")
    assert reproduce_check.classify_experiment(exp).report_stale is True
