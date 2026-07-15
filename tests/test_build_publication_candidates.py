from __future__ import annotations

import importlib.util
import json
from pathlib import Path


def _load_module():
    script_path = Path(__file__).resolve().parents[1] / "scripts" / "build_publication_candidates.py"
    spec = importlib.util.spec_from_file_location("build_publication_candidates", script_path)
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    return mod


def _write_result(root: Path, kid: str) -> None:
    exp_dir = root / "experiments" / kid.lower()
    exp_dir.mkdir(parents=True, exist_ok=True)
    (exp_dir / f"{kid.lower()}_results.json").write_text("{}", encoding="utf-8")


def test_release_attempt_receipts_do_not_fabricate_audience_coverage(
    tmp_path: Path,
    monkeypatch,
) -> None:
    mod = _load_module()
    knowledge_path = tmp_path / "knowledge.json"
    feed_path = tmp_path / "feed.json"
    next_tasks_path = tmp_path / "next_tasks.json"
    output_path = tmp_path / "publication_candidates.json"
    reader_metrics_path = tmp_path / "latest.json"

    for kid in ("K3001", "K3002", "K3003", "K3004"):
        _write_result(tmp_path, kid)

    knowledge_path.write_text(
        json.dumps(
            [
                {
                    "experiment_id": kid,
                    "title": f"{kid}: robust universal volatility finding",
                    "content": "PASS robust universal methodology warning",
                    "updated_at": f"2026-07-06T00:0{i}:00+00:00",
                    "tags": [],
                }
                for i, kid in enumerate(("K3001", "K3002", "K3003", "K3004"), start=1)
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    feed_path.write_text(
        json.dumps(
            [
                {
                    "id": "mile_k3002",
                    "title": "Research article with structured refs",
                    "status": "published",
                    "audience": "research",
                    "tags": [],
                    "description": "",
                    "content": "",
                    "details": {
                        "experiment_refs": ["K3002"],
                        "audience_correction": {
                            "requires_general_rewrite": True,
                        },
                    },
                },
                {
                    "id": "mile_k3003",
                    "title": "K3003 research article without structured refs",
                    "status": "published",
                    "audience": "research",
                    "tags": [],
                    "description": "",
                    "content": "",
                    "details": {},
                },
                {
                    "id": "mile_k3004_research",
                    "title": "K3004 research coverage",
                    "status": "published",
                    "audience": "research",
                    "tags": [],
                    "description": "",
                    "content": "",
                    "details": {"experiment_refs": ["K3004"]},
                },
                {
                    "id": "mile_k3004_unpublished_general",
                    "title": "K3004 unpublished general draft",
                    "status": "unpublished",
                    "audience": "general",
                    "tags": [],
                    "description": "",
                    "content": "",
                    "details": {"experiment_refs": ["K3004"]},
                },
                {
                    "id": "mile_k3004_wont_fix_general",
                    "title": "K3004 superseded general audit trail",
                    "status": "wont_fix",
                    "audience": "general",
                    "tags": [],
                    "description": "",
                    "content": "",
                    "details": {"experiment_refs": ["K3004"]},
                },
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    next_tasks_path.write_text(
        json.dumps(
            [
                {
                    "id": "K3001_article_general",
                    "task_type": "daily_article",
                    "status": "succeeded",
                    "title": "K3001 succeeded general article task",
                },
                {
                    "id": "K3002_article_general",
                    "task_type": "daily_article",
                    "status": "succeeded",
                    "title": "K3002 succeeded general article task before reclassification",
                },
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(mod, "ROOT", tmp_path)
    monkeypatch.setattr(mod, "KNOWLEDGE_PATH", knowledge_path)
    monkeypatch.setattr(mod, "FEED_PATH", feed_path)
    monkeypatch.setattr(mod, "NEXT_TASKS_PATH", next_tasks_path)
    monkeypatch.setattr(mod, "OUTPUT_PATH", output_path)
    monkeypatch.setattr(mod, "READER_METRICS_LATEST_PATH", reader_metrics_path)
    monkeypatch.setattr(
        mod,
        "cluster_gate_status",
        lambda cluster: {
            "cluster": cluster,
            "count": 0,
            "cap": 15,
            "total": 0,
            "ratio": 0,
            "blocked": False,
            "dominant_ratio_breached": False,
        },
    )

    mod.main()

    payload = json.loads(output_path.read_text(encoding="utf-8"))
    by_kid = {candidate["k_id"]: candidate for candidate in payload["candidates"]}
    uncovered_ids = {row["k_id"] for row in payload["top_10_uncovered"]}
    missing_general_by_kid = {
        row["k_id"]: row for row in payload["missing_general_top5"]
    }
    missing_general_ids = set(missing_general_by_kid)

    assert by_kid["K3001"]["uncovered"] is True
    assert by_kid["K3001"]["audiences_covered"] == []
    assert by_kid["K3001"]["covered_by"] == []
    assert by_kid["K3001"]["release_attempted_by"][0]["source"] == (
        "next_tasks_succeeded_daily_article"
    )
    assert by_kid["K3001"]["release_layer_covered"] is True
    assert "K3001" not in uncovered_ids

    assert by_kid["K3002"]["release_layer_covered"] is True
    assert by_kid["K3002"]["audience_correction_gap"] is True
    assert len(by_kid["K3002"]["covered_by"]) == 1
    assert len(by_kid["K3002"]["release_attempted_by"]) == 1
    assert "K3002" in missing_general_ids
    assert missing_general_by_kid["K3002"]["audience_correction_gap"] is True
    assert len(missing_general_by_kid["K3002"]["release_attempted_by"]) == 1

    assert by_kid["K3003"]["release_layer_covered"] is False
    assert "K3003" in missing_general_ids

    assert by_kid["K3004"]["audiences_covered"] == ["research"]
    assert "K3004" in missing_general_ids


def test_general_rewrite_marker_supports_both_correction_metadata_names() -> None:
    mod = _load_module()

    for key in ("audience_correction", "audience_backfill"):
        assert mod._article_requires_general_rewrite(
            {"details": {key: {"requires_general_rewrite": True}}}
        )
        assert not mod._article_requires_general_rewrite(
            {"details": {key: {"requires_general_rewrite": False}}}
        )

    assert not mod._article_requires_general_rewrite(
        {"details": {"audience_correction": {"reason": "metadata only"}}}
    )

    scoped = {
        "details": {
            "audience_correction": {
                "requires_general_rewrite": True,
                "uncovered_experiment_refs": ["K3001"],
            }
        }
    }
    assert mod._article_requires_general_rewrite(scoped, k_id="K3001")
    assert not mod._article_requires_general_rewrite(scoped, k_id="K3002")


def test_preference_bonus_reads_qualified_conclusions(tmp_path: Path, monkeypatch) -> None:
    """Reader-preference bonus must be additive, capped, and zero when the
    signals file is absent — proving the wiring is live, not silently empty."""
    mod = _load_module()
    analytics = tmp_path / "storage" / "analytics"
    analytics.mkdir(parents=True, exist_ok=True)
    (analytics / "reader_preferences.json").write_text(
        json.dumps({
            "qualified_conclusions": [
                {"dimension": "tag", "higher_bucket": "波動率", "lower_bucket": "GLD"},
                {"dimension": "research_vs_narrative", "higher_bucket": "research", "lower_bucket": "narrative"},
                {"dimension": "chart_bucket", "higher_bucket": "3+", "lower_bucket": "0"},
            ],
        }, ensure_ascii=False),
        encoding="utf-8",
    )
    monkeypatch.setattr(mod, "ROOT", tmp_path)

    high_tags, research_higher = mod._load_preference_signals()
    assert high_tags == {"波動率"}          # only tag-dimension higher buckets
    assert research_higher is True

    # Matching candidate: tag hit + research-type hit, capped at 2.
    bonus, reasons = mod._preference_bonus(["波動率", "misc"], True, high_tags, research_higher)
    assert bonus == 2 and len(reasons) == 2

    # Non-matching candidate gets nothing (no penalty either).
    assert mod._preference_bonus(["misc"], False, high_tags, research_higher) == (0, [])

    # Absent file -> zero signal -> "樣本不足/無檔 → 零影響".
    monkeypatch.setattr(mod, "ROOT", tmp_path / "does_not_exist")
    assert mod._load_preference_signals() == (set(), False)


def test_output_write_is_atomic(tmp_path: Path, monkeypatch) -> None:
    """A SIGKILL mid-write must never leave truncated JSON in tracked state.

    refill_task_pool spawns this builder under a hard timeout that kills uv and
    orphans the python child mid-write (docs/error_log.md 2026-07-10). The write
    must go through a tmp file + os.replace so the tracked candidates file is only
    ever swapped as a whole, never observed half-written.
    """
    mod = _load_module()
    out = tmp_path / "publication_candidates.json"
    out.write_text('{"generated_at": "old"}', encoding="utf-8")
    monkeypatch.setattr(mod, "OUTPUT_PATH", out)

    seen = {}
    real_replace = mod.os.replace

    def spy_replace(src, dst):
        # Until the rename lands, the destination must still hold the OLD content.
        seen["dst_before_replace"] = Path(dst).read_text(encoding="utf-8")
        return real_replace(src, dst)

    monkeypatch.setattr(mod.os, "replace", spy_replace)
    mod._write_output_atomically({"generated_at": "new"})

    assert seen["dst_before_replace"] == '{"generated_at": "old"}'
    assert json.loads(out.read_text(encoding="utf-8"))["generated_at"] == "new"
    assert not out.with_name(out.name + ".tmp").exists()


def test_latest_knowledge_uses_created_at_and_explicit_supersedes() -> None:
    """A correction must replace an older item even when updated_at is absent."""
    mod = _load_module()
    old = {
        "item_id": "k1378_sf1",
        "experiment_id": "k1378",
        "created_at": "2026-05-19T21:07:00",
        "content": "old invalid K1378 conclusion",
    }
    correction = {
        "item_id": "k1378_dm_hac_correction_20260715",
        "experiment_id": "k1378",
        "created_at": "2026-07-15T10:59:32+00:00",
        "supersedes": ["k1378_sf1"],
        "content": "fresh corrected K1378 conclusion",
    }

    selected = mod._latest_knowledge_by_k([old, correction])

    assert selected["K1378"] is correction

    reversed_selected = mod._latest_knowledge_by_k([correction, old])
    assert reversed_selected["K1378"] is correction


def test_latest_knowledge_uses_created_at_when_no_supersedes_edge() -> None:
    mod = _load_module()
    old = {
        "experiment_id": "K3000",
        "created_at": "2026-05-19T21:07:00",
        "content": "old",
    }
    new = {
        "experiment_id": "K3000",
        "created_at": "2026-07-15T10:59:32+00:00",
        "content": "new",
    }

    assert mod._latest_knowledge_by_k([new, old])["K3000"] is new


def test_naive_knowledge_timestamp_is_interpreted_as_taipei_time() -> None:
    mod = _load_module()
    naive_local = {
        "experiment_id": "K3005",
        # Asia/Taipei 11:50 is 03:50 UTC.
        "created_at": "2026-05-26T11:50:00",
    }
    aware_utc = {
        "experiment_id": "K3005",
        "created_at": "2026-05-26T04:00:00+00:00",
    }

    assert mod._latest_knowledge_by_k([aware_utc, naive_local])["K3005"] is aware_utc


def test_latest_knowledge_falls_back_to_append_order_without_timestamps() -> None:
    mod = _load_module()
    old = {"experiment_id": "K3001", "content": "first"}
    new = {"experiment_id": "K3001", "content": "second"}

    assert mod._latest_knowledge_by_k([old, new])["K3001"] is new


def test_explicit_supersedes_outweighs_timestamp_order() -> None:
    """A dated backfill can still explicitly retire a later-timestamped item."""
    mod = _load_module()
    incumbent = {
        "item_id": "old",
        "experiment_id": "K3002",
        "created_at": "2026-07-15T12:00:00+00:00",
    }
    correction = {
        "item_id": "correction",
        "experiment_id": "K3002",
        "created_at": "2026-07-15T11:00:00+00:00",
        "supersedes": ["old"],
    }

    assert mod._latest_knowledge_by_k([incumbent, correction])["K3002"] is correction


def test_transitive_supersedes_chain_is_order_independent() -> None:
    mod = _load_module()
    first = {"item_id": "a", "experiment_id": "K3006"}
    second = {
        "item_id": "b",
        "experiment_id": "K3006",
        "supersedes": ["a"],
    }
    third = {
        "item_id": "c",
        "experiment_id": "K3006",
        "supersedes": ["b"],
    }

    for entries in ([first, second, third], [third, first, second]):
        assert mod._latest_knowledge_by_k(entries)["K3006"] is third
