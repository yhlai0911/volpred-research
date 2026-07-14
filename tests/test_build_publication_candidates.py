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


def test_release_layer_coverage_filters_stale_publication_gaps(
    tmp_path: Path,
    monkeypatch,
) -> None:
    mod = _load_module()
    knowledge_path = tmp_path / "knowledge.json"
    feed_path = tmp_path / "feed.json"
    next_tasks_path = tmp_path / "next_tasks.json"
    output_path = tmp_path / "publication_candidates.json"
    reader_metrics_path = tmp_path / "latest.json"

    for kid in ("K3001", "K3002", "K3003"):
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
                for i, kid in enumerate(("K3001", "K3002", "K3003"), start=1)
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
                    "details": {"experiment_refs": ["K3002"]},
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
                }
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
    missing_general_ids = {row["k_id"] for row in payload["missing_general_top5"]}

    assert by_kid["K3001"]["uncovered"] is False
    assert by_kid["K3001"]["audiences_covered"] == ["general"]
    assert by_kid["K3001"]["covered_by"][0]["source"] == "next_tasks_succeeded_daily_article"
    assert "K3001" not in uncovered_ids

    assert by_kid["K3002"]["release_layer_covered"] is True
    assert "K3002" not in missing_general_ids

    assert by_kid["K3003"]["release_layer_covered"] is False
    assert "K3003" in missing_general_ids


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
