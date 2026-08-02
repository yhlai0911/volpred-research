import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _module():
    path = ROOT / "scripts" / "graphify_integration.py"
    spec = importlib.util.spec_from_file_location("graphify_integration", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_canonical_graphify_corpus_is_clean_and_covers_non_src_surfaces():
    config = json.loads((ROOT / "config" / "graphify_integration.json").read_text())
    included = config["corpus_policy"]["included_surfaces"]
    excluded = config["corpus_policy"]["excluded_surfaces"]

    assert {"src/", "scripts/", "tests/", "config/", "docs/", "ops/"} <= set(included)
    assert {"storage/", "experiments/", "paper/", "frontend-v2-fix/"} <= set(excluded)
    assert [item["id"] for item in config["graphs"]] == ["root", "active_frontend"]
    assert (ROOT / ".graphifyignore").exists()


def test_usage_report_distinguishes_proxy_records_from_actual_ab(tmp_path, monkeypatch):
    module = _module()
    monkeypatch.setattr(module, "ROOT", tmp_path)
    ledger = tmp_path / "usage.jsonl"
    ledger.write_text(
        "\n".join(
            [
                json.dumps({"record_type": "graphify_treatment", "comparison_id": "a", "observed_model_tokens": 120}),
                json.dumps({"record_type": "control", "comparison_id": "a", "observed_model_tokens": 300}),
                json.dumps({"record_type": "graphify_treatment", "comparison_id": "proxy-only", "observed_model_tokens": None}),
                json.dumps({"record_type": "invalidation", "comparison_id": "proxy-only"}),
            ]
        ) + "\n"
    )

    report = module.usage_report({"usage_ledger": "usage.jsonl"})

    assert report["records"] == 4
    assert report["invalidated_records"] == 1
    assert report["graphify_treatments"] == 1
    assert report["paired_observed_model_ab"] == 1
    assert "not billed-token evidence" in report["note"]
