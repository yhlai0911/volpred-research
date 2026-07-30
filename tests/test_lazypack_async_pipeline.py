"""Tests for the async lazypack pipeline (2026-07-02, error_log 15:15 #4).

Covers the three seams that moved the codex render off the writing agent's
50-min cap onto the compute_queue lane:

  1. enqueue  — scripts/lazypack_async_render.py writes a compute_queue job
                whose command re-invokes itself in `run` mode; idempotent per
                article while a job is queued/running.
  2. install  — volpred.publisher.lazypack_install appends/replaces the
                `## 懶人包圖組` section under the publisher_feed lock and
                stamps last_updated_at/errata.
  3. release  — volpred.ops.content release gate refuses to flip a general
                draft to published until the section exists, reusing the
                release-audit skip/escalation machinery.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from types import SimpleNamespace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "src"), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import compute_queue as cq  # noqa: E402
import lazypack_async_render as lar  # noqa: E402
from volpred.publisher.lazypack_install import (  # noqa: E402
    install_lazypack_section,
    upload_panels,
)
from volpred.publisher.publisher import has_lazypack_section  # noqa: E402

def _make_plan(tmp_path: Path) -> dict:
    evidence = tmp_path / "evidence.json"
    evidence.write_text(
        json.dumps({"result": {"value": 0.123}}, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    digest = hashlib.sha256(evidence.read_bytes()).hexdigest()
    binding = {
        "source": "main", "path": "result.value",
        "format": {"kind": "percent", "digits": 1},
    }
    return {
        "schema_version": 1,
        "title": "測試懶人包",
        "evidence": {
            "main": {"path": str(evidence), "sha256": digest, "label": "測試 evidence.json"}
        },
        "panels": [
            {
                "name": "1_framework", "info": "concept", "style": "professional",
                "title": "核心問題", "alt": "懶人包圖一", "sources": ["main"],
                "blocks": [{
                    "kind": "text", "heading": "問題", "body": ["先分清楚熱度與成果。"],
                }],
            },
            {
                "name": "2_results", "info": "results", "style": "bento-grid",
                "title": "主要數字", "alt": "結果圖", "sources": ["main"],
                "blocks": [{"kind": "metric", "label": "結果", "value": binding}],
            },
        ],
    }


def _write_feed(storage_dir: Path, items: list[dict]) -> Path:
    feed_path = storage_dir / "reports" / "feed.json"
    feed_path.parent.mkdir(parents=True, exist_ok=True)
    feed_path.write_text(json.dumps(items, ensure_ascii=False, indent=2),
                         encoding="utf-8")
    return feed_path


def _patch_queue(monkeypatch, tmp_path: Path) -> Path:
    qdir = tmp_path / "queue"
    monkeypatch.setattr(cq, "QUEUE_DIR", qdir)
    monkeypatch.setattr(cq, "LOCK_FILE", qdir / ".worker.lock")
    monkeypatch.setattr(cq, "LOG_DIR", tmp_path / "compute_logs")
    return qdir


def _enqueue_ns(tmp_path: Path, **over) -> argparse.Namespace:
    base = dict(
        article_id="mile_lz1",
        experiment=["K9001"],
        source=[],
        title=None,
        storage_dir=str(tmp_path / "storage"),
        plan=str(tmp_path / "plan.json"),
        timeout=300,
        force=False,
    )
    base.update(over)
    return argparse.Namespace(**base)


@pytest.fixture()
def storage(tmp_path: Path) -> Path:
    storage_dir = tmp_path / "storage"
    _write_feed(storage_dir, [{
        "id": "mile_lz1",
        "status": "draft",
        "audience": "general",
        "title": "白話文章等待懶人包",
        "content": "# 標題\n\n正文，白話故事。\n",
    }])
    (tmp_path / "plan.json").write_text(
        json.dumps(_make_plan(tmp_path), ensure_ascii=False), encoding="utf-8"
    )
    return storage_dir


# ------------------------------------------------------------------ enqueue --

def test_enqueue_writes_selfcontained_compute_job(storage, tmp_path, monkeypatch):
    qdir = _patch_queue(monkeypatch, tmp_path)
    rc = lar.cmd_enqueue(_enqueue_ns(tmp_path))
    assert rc == 0
    job_path = qdir / "lazypack-mile_lz1.json"
    assert job_path.exists()
    job = json.loads(job_path.read_text(encoding="utf-8"))
    assert job["status"] == "queued"
    assert job["script_path"] == "scripts/lazypack_async_render.py"
    assert job["interpreter"] == "uv run python"
    assert job["args"][0] == "run"
    assert "--job-id" in job["args"] and "lazypack-mile_lz1" in job["args"]
    assert "--article-id" in job["args"] and "mile_lz1" in job["args"]
    assert "--experiment" in job["args"] and "K9001" in job["args"]
    assert job["claude_followup"] is None  # job completes itself — 0 Claude tokens
    # plan persisted next to the job artifacts (reproducible worker run)
    run_dir = storage / "lazypack_jobs" / "mile_lz1" / "runs" / "lazypack-mile_lz1"
    stored_plan = run_dir / "plan.json"
    assert stored_plan.exists()
    assert json.loads(stored_plan.read_text(encoding="utf-8")) == json.loads(
        (tmp_path / "plan.json").read_text(encoding="utf-8")
    )
    panels_dir = run_dir / "panels"
    assert job["output_paths"] == [
        str(stored_plan),
        str(panels_dir / "1_framework.png"),
        str(panels_dir / "2_results.png"),
    ]


def test_enqueue_idempotent_while_queued(storage, tmp_path, monkeypatch, capsys):
    qdir = _patch_queue(monkeypatch, tmp_path)
    assert lar.cmd_enqueue(_enqueue_ns(tmp_path)) == 0
    stored = (
        storage / "lazypack_jobs" / "mile_lz1" / "runs"
        / "lazypack-mile_lz1" / "plan.json"
    )
    first = stored.read_bytes()
    changed = json.loads((tmp_path / "plan.json").read_text(encoding="utf-8"))
    changed["title"] = "第二版不應覆寫執行中的計畫"
    (tmp_path / "plan.json").write_text(
        json.dumps(changed, ensure_ascii=False), encoding="utf-8"
    )
    assert lar.cmd_enqueue(_enqueue_ns(tmp_path)) == 0  # second call: skip
    assert len(list(qdir.glob("lazypack-mile_lz1*.json"))) == 1
    assert stored.read_bytes() == first
    assert "already queued" in capsys.readouterr().out


def test_enqueue_force_refuses_shared_path_race(storage, tmp_path, monkeypatch):
    _patch_queue(monkeypatch, tmp_path)
    assert lar.cmd_enqueue(_enqueue_ns(tmp_path)) == 0
    assert lar.cmd_enqueue(_enqueue_ns(tmp_path, force=True)) == 2


def test_enqueue_requeues_after_failure_with_suffix(storage, tmp_path, monkeypatch):
    qdir = _patch_queue(monkeypatch, tmp_path)
    assert lar.cmd_enqueue(_enqueue_ns(tmp_path)) == 0
    job_path = qdir / "lazypack-mile_lz1.json"
    job = json.loads(job_path.read_text(encoding="utf-8"))
    job["status"] = "failed"
    job_path.write_text(json.dumps(job), encoding="utf-8")
    assert lar.cmd_enqueue(_enqueue_ns(tmp_path)) == 0
    assert (qdir / "lazypack-mile_lz1-r2.json").exists()


def test_enqueue_unknown_article_fails_fast(storage, tmp_path, monkeypatch):
    _patch_queue(monkeypatch, tmp_path)
    rc = lar.cmd_enqueue(_enqueue_ns(tmp_path, article_id="mile_nope"))
    assert rc == 2


# ------------------------------------------------------------------ install --

def test_install_appends_section_and_stamps_errata(storage):
    result = install_lazypack_section(
        "mile_lz1",
        [("https://x.test/a.png", "概念"), ("https://x.test/b.png", "結果")],
        storage_dir=storage,
        sync=False,
    )
    assert result["panels"] == 2 and result["replaced"] is False
    feed = json.loads((storage / "reports" / "feed.json").read_text(encoding="utf-8"))
    art = feed[0]
    assert has_lazypack_section(art["content"])
    assert art["content"].rstrip().endswith("![結果](https://x.test/b.png)")
    assert art["last_updated_at"]
    assert art["errata"]["update_action"] == "lazypack_install"


def test_install_replaces_existing_section(storage):
    for i in range(2):
        result = install_lazypack_section(
            "mile_lz1",
            [(f"https://x.test/v{i}.png", "圖")],
            storage_dir=storage,
            sync=False,
        )
    assert result["replaced"] is True
    feed = json.loads((storage / "reports" / "feed.json").read_text(encoding="utf-8"))
    content = feed[0]["content"]
    assert content.count("## 懶人包圖組") == 1  # replaced, not stacked
    assert "v1.png" in content and "v0.png" not in content


def test_install_unknown_article_raises(storage):
    with pytest.raises(KeyError):
        install_lazypack_section("mile_nope", [("https://x/a.png", "x")],
                                 storage_dir=storage, sync=False)


def test_upload_panels_fails_loud_on_missing_png(tmp_path):
    with pytest.raises(FileNotFoundError):
        upload_panels("mile_lz1", tmp_path, [("missing_panel", "alt")],
                      uploader=lambda p: "https://x.test/ok.png")


def test_upload_panel_object_name_is_content_addressed(tmp_path):
    panel = tmp_path / "1_panel.png"
    seen = []

    def uploader(path):
        seen.append(Path(path).name)
        return f"https://x.test/{Path(path).name}"

    panel.write_bytes(b"first")
    first = upload_panels("mile_lz1", tmp_path, [("1_panel", "圖")], uploader=uploader)
    panel.write_bytes(b"second")
    second = upload_panels("mile_lz1", tmp_path, [("1_panel", "圖")], uploader=uploader)
    assert seen[0] != seen[1]
    assert "codex" not in seen[0] + seen[1]
    assert first[0][0] != second[0][0]


# ---------------------------------------------------------------- run mode ---

def test_run_pipeline_end_to_end_with_stub_render_and_upload(
    storage, tmp_path, monkeypatch
):
    """Full `run` seam: stub render writes the PNGs, in-process uploader stub
    returns URLs, section lands in feed.json. No codex / Supabase involved."""
    out_dir = storage / "lazypack_jobs" / "mile_lz1" / "panels"
    stub = tmp_path / "stub_render.py"
    stub.write_text(
        "import json, sys\n"
        "from pathlib import Path\n"
        "plan, out = json.loads(Path(sys.argv[1]).read_text()), Path(sys.argv[2])\n"
        "out.mkdir(parents=True, exist_ok=True)\n"
        "for p in plan['panels']:\n"
        "    (out / (p['name'] + '.png')).write_bytes(b'P' * 2048)\n",
        encoding="utf-8",
    )
    ns = argparse.Namespace(
        article_id="mile_lz1",
        experiment=[], source=[], title=None,
        storage_dir=str(storage),
        plan=str(tmp_path / "plan.json"),
        out_dir=str(out_dir),
        render_cmd=f"{sys.executable} {stub}",
        upload_cmd=f"{sys.executable} -c "
                   f"\"import sys; print('https://x.test/' + sys.argv[1].split('/')[-1])\"",
        no_sync=True,
    )
    assert lar.cmd_run(ns) == 0
    feed = json.loads((storage / "reports" / "feed.json").read_text(encoding="utf-8"))
    assert has_lazypack_section(feed[0]["content"])
    assert "![結果圖](" in feed[0]["content"]  # plan alt override honored
    assert feed[0]["errata"]["update_summary"].startswith("Installed test-hook")


def test_run_fails_when_render_produces_no_pngs(storage, tmp_path):
    ns = argparse.Namespace(
        article_id="mile_lz1",
        experiment=[], source=[], title=None,
        storage_dir=str(storage),
        plan=str(tmp_path / "plan.json"),
        out_dir=str(tmp_path / "empty_panels"),
        render_cmd=f"{sys.executable} -c pass",
        upload_cmd=None,
        no_sync=True,
    )
    assert ns and lar.cmd_run(ns) == 3


def test_run_does_not_accept_rc0_hook_that_reuses_stale_pngs(storage, tmp_path):
    out_dir = tmp_path / "stale_panels"
    out_dir.mkdir()
    for stem in ("1_framework", "2_results"):
        (out_dir / f"{stem}.png").write_bytes(b"OLD" * 800)
    ns = argparse.Namespace(
        article_id="mile_lz1",
        experiment=[], source=[], title=None,
        storage_dir=str(storage),
        plan=str(tmp_path / "plan.json"),
        out_dir=str(out_dir),
        render_cmd=f"{sys.executable} -c pass",
        upload_cmd=None,
        no_sync=True,
    )
    assert lar.cmd_run(ns) == 3


def test_run_default_is_codex_bespoke_renderer_and_replaces_stale_pngs(
    storage, tmp_path, monkeypatch
):
    from volpred.publisher import lazypack_install

    out_dir = storage / "lazypack_jobs" / "mile_lz1" / "panels"
    out_dir.mkdir(parents=True, exist_ok=True)
    stale = out_dir / "1_framework.png"
    stale.write_bytes(b"S" * 2048)
    captured = []

    def fake_run(cmd, cwd, **kwargs):
        captured.append(cmd)
        assert Path(cmd[1]).name == "gen_lazypack_codex.py"
        assert "lazypack_render.py" not in " ".join(cmd)
        assert str(tmp_path / "plan.json") in [
            cmd[i + 1] for i, value in enumerate(cmd[:-1]) if value == "--source"
        ]
        plan = json.loads(Path(cmd[cmd.index("--plan") + 1]).read_text(encoding="utf-8"))
        target = Path(cmd[cmd.index("--out-dir") + 1])
        target.mkdir(parents=True, exist_ok=True)
        for panel in plan["panels"]:
            (target / f"{panel['name']}.png").write_bytes(b"N" * 2048)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(lar.subprocess, "run", fake_run)
    monkeypatch.setattr(
        lazypack_install, "upload_panels",
        lambda article_id, panel_dir, specs, uploader=None: [
            (f"https://x.test/{stem}.png", alt) for stem, alt in specs
        ],
    )
    monkeypatch.setattr(
        lazypack_install, "install_lazypack_section",
        lambda *args, **kwargs: {"status": "draft", "synced": False, "panels": 2},
    )
    ns = argparse.Namespace(
        article_id="mile_lz1",
        experiment=[], source=[], title=None,
        storage_dir=str(storage),
        plan=str(tmp_path / "plan.json"),
        out_dir=str(out_dir),
        render_cmd=None,
        upload_cmd=None,
        no_sync=True,
    )
    assert lar.cmd_run(ns) == 0
    assert len(captured) == 1  # stale file-size heuristic no longer bypasses render
    assert stale.read_bytes() == b"N" * 2048


def test_run_codex_failure_uses_logged_deterministic_fallback(
    storage, tmp_path, monkeypatch
):
    from volpred.publisher import lazypack_install

    _patch_queue(monkeypatch, tmp_path)
    out_dir = storage / "lazypack_jobs" / "mile_lz1" / "panels"
    captured = []

    def fake_run(cmd, cwd, **kwargs):
        captured.append(cmd)
        renderer = Path(cmd[1]).name
        if renderer == "gen_lazypack_codex.py":
            # A partial primary output must not leak into the fallback receipt.
            out_dir.mkdir(parents=True, exist_ok=True)
            (out_dir / "1_framework.png").write_bytes(b"P" * 2048)
            return SimpleNamespace(
                returncode=17,
                stdout="",
                stderr="ERROR: You've hit your usage limit. Try again at Jul 25th.",
            )
        if renderer == "gen_lazypack_agy.py":
            # A partial middle-layer output must not leak either.
            (out_dir / "1_framework.png").write_bytes(b"A" * 2048)
            return SimpleNamespace(returncode=11, stdout="", stderr="agy wrote nothing")
        assert renderer == "lazypack_render.py"
        plan_path = Path(cmd[cmd.index("--plan") + 1])
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        target = Path(cmd[cmd.index("--out-dir") + 1])
        for panel in plan["panels"]:
            (target / f"{panel['name']}.png").write_bytes(b"F" * 2048)
        receipt = Path(cmd[cmd.index("--receipt") + 1])
        token = cmd[cmd.index("--run-token") + 1]
        receipt.write_text(json.dumps({
            "schema_version": 1,
            "renderer": "scripts/lazypack_render.py",
            "run_token": token,
            "plan_sha256": hashlib.sha256(plan_path.read_bytes()).hexdigest(),
            "panels": [
                {
                    "name": f"{panel['name']}.png",
                    "sha256": hashlib.sha256(
                        (target / f"{panel['name']}.png").read_bytes()
                    ).hexdigest(),
                }
                for panel in plan["panels"]
            ],
        }), encoding="utf-8")
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(lar.subprocess, "run", fake_run)
    monkeypatch.setattr(
        lazypack_install, "upload_panels",
        lambda article_id, panel_dir, specs, uploader=None: [
            (f"https://x.test/{stem}.png", alt) for stem, alt in specs
        ],
    )
    monkeypatch.setattr(
        lazypack_install, "install_lazypack_section",
        lambda *args, **kwargs: {"status": "draft", "synced": False, "panels": 2},
    )
    ns = argparse.Namespace(
        job_id="lazypack-mile_lz1",
        article_id="mile_lz1",
        experiment=[], source=[], title=None,
        storage_dir=str(storage),
        plan=str(tmp_path / "plan.json"),
        out_dir=str(out_dir),
        render_cmd=None,
        upload_cmd=None,
        no_sync=True,
    )

    assert lar.cmd_run(ns) == 0
    assert [Path(cmd[1]).name for cmd in captured] == [
        "gen_lazypack_codex.py", "gen_lazypack_agy.py", "lazypack_render.py",
    ]
    # The agy layer receives an explicit remaining wall budget so a slow codex
    # cannot starve the deterministic layer's window.
    assert "--budget-s" in captured[1]
    assert (out_dir / "1_framework.png").read_bytes() == b"F" * 2048
    work_log = json.loads((storage / "work_log.json").read_text(encoding="utf-8"))
    assert len(work_log) == 2  # both layer hand-offs are persisted, never silent
    codex_to_agy, agy_to_det = work_log
    assert codex_to_agy["outcome"] == "fallback_failed"  # agy rc=11
    assert codex_to_agy["fallback_event_id"] == (
        "lazypack_fallback:lazypack-mile_lz1:codex->agy"
    )
    assert codex_to_agy["primary_renderer"] == "scripts/gen_lazypack_codex.py"
    assert codex_to_agy["fallback_renderer"] == "scripts/gen_lazypack_agy.py"
    # The quota wall in codex's stderr must be classified for the fast-skip.
    assert codex_to_agy["failure_class"] == "quota"
    assert agy_to_det["outcome"] == "fallback_succeeded"
    assert agy_to_det["fallback_event_id"] == (
        "lazypack_fallback:lazypack-mile_lz1:agy->deterministic"
    )
    assert agy_to_det["primary_renderer"] == "scripts/gen_lazypack_agy.py"
    assert agy_to_det["fallback_renderer"] == "scripts/lazypack_render.py"
    assert agy_to_det["failure_class"] is None  # agy failure was not quota-class


def test_failed_render_writes_back_partial_panel_ownership(
    storage,
    tmp_path,
    monkeypatch,
):
    qdir = _patch_queue(monkeypatch, tmp_path)
    assert lar.cmd_enqueue(_enqueue_ns(tmp_path)) == 0
    job_path = qdir / "lazypack-mile_lz1.json"
    run_dir = storage / "lazypack_jobs" / "mile_lz1" / "runs" / "lazypack-mile_lz1"
    stored_plan = run_dir / "plan.json"
    out_dir = run_dir / "panels"
    stub = tmp_path / "partial_then_fail.py"
    stub.write_text(
        "import sys\n"
        "from pathlib import Path\n"
        "out = Path(sys.argv[2]); out.mkdir(parents=True, exist_ok=True)\n"
        "(out / '1_framework.png').write_bytes(b'P' * 2048)\n"
        "raise SystemExit(9)\n",
        encoding="utf-8",
    )
    ns = argparse.Namespace(
        job_id="lazypack-mile_lz1",
        article_id="mile_lz1",
        experiment=[], source=[], title=None,
        storage_dir=str(storage),
        plan=str(stored_plan),
        out_dir=str(out_dir),
        render_cmd=f"{sys.executable} {stub}",
        upload_cmd=None,
        no_sync=True,
    )

    assert lar.cmd_run(ns) == 2
    job = json.loads(job_path.read_text(encoding="utf-8"))
    assert job["output_paths_updated_at"]
    assert str(out_dir / "1_framework.png") in job["output_paths"]
    assert (out_dir / "1_framework.png").exists()


def test_primary_bespoke_script_is_added_to_job_output_ownership(
    storage, tmp_path, monkeypatch
):
    qdir = _patch_queue(monkeypatch, tmp_path)
    assert lar.cmd_enqueue(_enqueue_ns(tmp_path)) == 0
    job_path = qdir / "lazypack-mile_lz1.json"
    run_dir = storage / "lazypack_jobs" / "mile_lz1" / "runs" / "lazypack-mile_lz1"
    out_dir = run_dir / "panels"
    before = lar._snapshot_outputs(out_dir, [("1_framework", "圖")])
    script = out_dir / lar.BESPOKE_SCRIPT_NAME
    out_dir.mkdir(parents=True, exist_ok=True)
    script.write_text("# reproducible data-bound renderer\n", encoding="utf-8")

    lar._record_job_outputs(
        "lazypack-mile_lz1", out_dir, [("1_framework", "圖")], before
    )

    job = json.loads(job_path.read_text(encoding="utf-8"))
    assert str(script) in job["output_paths"]


def test_failed_render_does_not_claim_unchanged_stale_panels(
    storage, tmp_path, monkeypatch
):
    _patch_queue(monkeypatch, tmp_path)
    assert lar.cmd_enqueue(_enqueue_ns(tmp_path)) == 0
    run_dir = storage / "lazypack_jobs" / "mile_lz1" / "runs" / "lazypack-mile_lz1"
    stored_plan = run_dir / "plan.json"
    out_dir = run_dir / "panels"
    out_dir.mkdir(parents=True, exist_ok=True)
    for stem in ("1_framework", "2_results"):
        (out_dir / f"{stem}.png").write_bytes(b"OLD" * 800)
    recorded = []
    monkeypatch.setattr(cq, "record_output_paths", lambda job_id, paths: recorded.append(paths))
    ns = argparse.Namespace(
        job_id="lazypack-mile_lz1",
        article_id="mile_lz1",
        experiment=[], source=[], title=None,
        storage_dir=str(storage),
        plan=str(stored_plan),
        out_dir=str(out_dir),
        render_cmd=f"{sys.executable} -c 'raise SystemExit(9)'",
        upload_cmd=None,
        no_sync=True,
    )
    assert lar.cmd_run(ns) == 2
    assert recorded == []


# ------------------------------------------------------------- release gate --

def _freeze_content_now(monkeypatch, frozen_now: datetime) -> None:
    from volpred.ops import content

    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            if tz is None:
                return frozen_now.replace(tzinfo=None)
            return frozen_now.astimezone(tz)

    monkeypatch.setattr(content, "datetime", FrozenDateTime)


def _stub_release_side_effects(monkeypatch) -> None:
    from volpred.ops import content
    from volpred.publisher import live_verify
    from volpred.publisher.email_notifier import EmailNotifier

    monkeypatch.setattr(content, "sync_article", lambda *a, **k: None)
    monkeypatch.setattr(content, "_mark_questions_answered_on_publish",
                        lambda *a, **k: 0)
    monkeypatch.setattr(content, "_patch_where", lambda *a, **k: True)
    monkeypatch.setattr(content.Publisher, "_sync_feed_to_remote",
                        lambda self: None)
    monkeypatch.setattr(EmailNotifier, "notify_article_published",
                        lambda *a, **k: None)
    monkeypatch.setattr(live_verify, "verify_article_live", lambda *a, **k: True)
    monkeypatch.setattr(live_verify, "stamp_verified", lambda *a, **k: None)
    monkeypatch.setattr(live_verify, "emit_verify_alert", lambda *a, **k: None)


def test_release_gate_holds_general_draft_without_lazypack(tmp_path, monkeypatch):
    from volpred.ops import content

    frozen_now = datetime(2026, 7, 2, 8, 0, tzinfo=timezone.utc)
    _freeze_content_now(monkeypatch, frozen_now)
    _stub_release_side_effects(monkeypatch)
    storage_dir = tmp_path / "storage"
    _write_feed(storage_dir, [{
        "id": "mile_wait_lz",
        "status": "draft",
        "audience": "general",
        "created_at": (frozen_now - timedelta(days=2)).isoformat(),
        "title": "白話文章等待懶人包",
        "content": "# 標題\n\n正文，白話故事，還沒有補圖。\n",
    }])

    res = content.release_pool_articles(
        limit=1, due_only=False, include_drafts=True,
        storage_dir=str(storage_dir),
    )
    assert res["released_count"] == 0
    assert len(res["audit_skipped"]) == 1
    issues = res["audit_skipped"][0]["issues"]
    assert any("懶人包圖組" in i and "lazypack-mile_wait_lz" in i for i in issues)
    feed = json.loads((storage_dir / "reports" / "feed.json").read_text(encoding="utf-8"))
    assert feed[0]["status"] == "draft"
    assert feed[0]["details"]["release_audit_skipped_count"] == 1
    decisions = [
        json.loads(line)
        for line in (
            storage_dir / "logs" / "control_gate_decisions.jsonl"
        ).read_text(encoding="utf-8").splitlines()
    ]
    assert decisions[-1]["gate_id"] == "release_lazypack_completeness"
    assert decisions[-1]["decision"] == "block"
    assert decisions[-1]["candidate_id"] == "mile_wait_lz"
    assert (
        decisions[-1]["protected_edge"]
        == "lazypack_section -> release_candidate"
    )


def test_release_gate_fails_open_when_block_receipt_is_not_durable(
    tmp_path,
    monkeypatch,
):
    from volpred.ops import content
    from volpred.ops import control_gate_lifecycle

    monkeypatch.setattr(content, "_audit_general_content", lambda *_a: [])
    monkeypatch.setattr(content, "has_lazypack_section", lambda _text: False)
    monkeypatch.setattr(
        content,
        "_lazypack_gate_issue",
        lambda *_a, **_k: "missing lazypack",
    )
    monkeypatch.setattr(
        content,
        "_run_publish_anti_ai_gate",
        lambda *_a, **_k: [],
    )
    monkeypatch.setattr(
        control_gate_lifecycle,
        "record_control_gate_decision",
        lambda **_kwargs: (_ for _ in ()).throw(OSError("disk full")),
    )

    issues = content.release_content_gate_issues(
        {
            "id": "mile-no-receipt",
            "audience": "general",
            "content": "body",
        },
        storage_dir=str(tmp_path / "storage"),
        record=True,
    )

    assert issues == []


def test_content_audit_gate_fails_open_when_receipt_is_not_durable(
    tmp_path,
    monkeypatch,
):
    from volpred.ops import content
    from volpred.ops import control_gate_lifecycle

    monkeypatch.setattr(
        content,
        "_audit_general_content",
        lambda *_a: ["audience mismatch"],
    )
    monkeypatch.setattr(content, "has_lazypack_section", lambda _text: True)
    monkeypatch.setattr(
        content,
        "_run_publish_anti_ai_gate",
        lambda *_a, **_k: [],
    )
    monkeypatch.setattr(
        control_gate_lifecycle,
        "record_control_gate_decision",
        lambda **_kwargs: (_ for _ in ()).throw(OSError("disk full")),
    )

    issues = content.release_content_gate_issues(
        {
            "id": "mile-no-audit-receipt",
            "audience": "general",
            "content": "body",
        },
        storage_dir=str(tmp_path / "storage"),
        record=True,
    )

    assert issues == []


def test_release_gate_releases_after_section_installed(tmp_path, monkeypatch):
    from volpred.ops import content

    frozen_now = datetime(2026, 7, 2, 8, 0, tzinfo=timezone.utc)
    _freeze_content_now(monkeypatch, frozen_now)
    _stub_release_side_effects(monkeypatch)
    storage_dir = tmp_path / "storage"
    _write_feed(storage_dir, [{
        "id": "mile_lz_ready",
        "status": "draft",
        "audience": "general",
        "created_at": (frozen_now - timedelta(days=2)).isoformat(),
        "title": "白話文章補圖完成",
        "content": "# 標題\n\n正文，白話故事。\n",
    }])
    # the compute worker's install step
    install_lazypack_section(
        "mile_lz_ready", [("https://x.test/a.png", "概念")],
        storage_dir=storage_dir, sync=False,
    )

    res = content.release_pool_articles(
        limit=1, due_only=False, include_drafts=True,
        storage_dir=str(storage_dir),
    )
    assert res["released_count"] == 1
    feed = json.loads((storage_dir / "reports" / "feed.json").read_text(encoding="utf-8"))
    assert feed[0]["status"] == "published"


def test_release_gate_ignores_research_drafts(tmp_path, monkeypatch):
    from volpred.ops import content

    frozen_now = datetime(2026, 7, 2, 8, 0, tzinfo=timezone.utc)
    _freeze_content_now(monkeypatch, frozen_now)
    _stub_release_side_effects(monkeypatch)
    storage_dir = tmp_path / "storage"
    _write_feed(storage_dir, [{
        "id": "mile_research",
        "status": "draft",
        "audience": "research",
        "created_at": (frozen_now - timedelta(days=2)).isoformat(),
        "title": "研究文章不需懶人包",
        "content": "# 研究\n\n專業內容。\n",
    }])
    res = content.release_pool_articles(
        limit=1, due_only=False, include_drafts=True,
        storage_dir=str(storage_dir),
    )
    assert res["released_count"] == 1


def test_release_gate_reads_content_not_seo_description(tmp_path, monkeypatch):
    """The section lives in item['content']; item['description'] is the ≤200-char
    SEO snippet. The gate must read content-first or every installed article
    would stay blocked forever."""
    from volpred.ops import content

    frozen_now = datetime(2026, 7, 2, 8, 0, tzinfo=timezone.utc)
    _freeze_content_now(monkeypatch, frozen_now)
    _stub_release_side_effects(monkeypatch)
    storage_dir = tmp_path / "storage"
    _write_feed(storage_dir, [{
        "id": "mile_snippet",
        "status": "draft",
        "audience": "general",
        "created_at": (frozen_now - timedelta(days=2)).isoformat(),
        "title": "有 SEO 摘要的文章",
        "description": "這是不含懶人包的 SEO 摘要。",
        "content": ("# 標題\n\n正文。\n\n## 懶人包圖組\n\n"
                    "![圖](https://x.test/a.png)\n"),
    }])
    res = content.release_pool_articles(
        limit=1, due_only=False, include_drafts=True,
        storage_dir=str(storage_dir),
    )
    assert res["released_count"] == 1


# ------------------------------------------------- requeue-stranded (D4a) ----

def _failed_job(
    qdir: Path,
    job_id: str,
    article_id: str,
    *,
    completed_at: str = "2026-07-20T02:00:00+00:00",
    persist_plan: bool = True,
) -> Path:
    qdir.mkdir(parents=True, exist_ok=True)
    path = qdir / f"{job_id}.json"
    plan_path = (
        qdir.parent / "storage" / "lazypack_jobs" / article_id
        / "runs" / job_id / "plan.json"
    )
    panels_dir = plan_path.parent / "panels"
    if persist_plan:
        plan_path.parent.mkdir(parents=True, exist_ok=True)
        plan_path.write_text(
            json.dumps(_make_plan(qdir.parent), ensure_ascii=False),
            encoding="utf-8",
        )
    path.write_text(json.dumps({
        "id": job_id,
        "title": f"lazypack render {article_id}",
        "status": "failed",
        "exit_code": 2,
        "queued_at": "2026-07-20T01:00:00+00:00",
        "completed_at": completed_at,
        "script_path": "scripts/lazypack_async_render.py",
        "interpreter": "uv run python",
        "args": ["run", "--job-id", job_id, "--article-id", article_id,
                 "--plan", str(plan_path),
                 "--out-dir", str(panels_dir)],
        "result_artifact": str(panels_dir),
        "output_paths": [str(plan_path)],
        "timeout_seconds": 1800,
    }, ensure_ascii=False), encoding="utf-8")
    return path


def test_requeue_stranded_is_idempotent_and_attempt_capped(
    storage, tmp_path, monkeypatch
):
    """D4a: the alert path's promised retry — once per failed job, capped."""
    qdir = _patch_queue(monkeypatch, tmp_path)
    original = _failed_job(qdir, "lazypack-mile_lz1", "mile_lz1")

    summary = lar.requeue_stranded(storage_dir=str(storage))
    assert [r["new_job_id"] for r in summary["requeued"]] == ["lazypack-mile_lz1-r2"]
    retry = json.loads((qdir / "lazypack-mile_lz1-r2.json").read_text(encoding="utf-8"))
    assert retry["status"] == "queued"
    job_id_flag = retry["args"].index("--job-id")
    assert retry["args"][job_id_flag + 1] == "lazypack-mile_lz1-r2"
    plan_flag = retry["args"].index("--plan")
    retry_plan = Path(retry["args"][plan_flag + 1])
    assert retry_plan.is_file()
    assert retry_plan != Path(
        json.loads(original.read_text(encoding="utf-8"))["args"][plan_flag + 1]
    )
    assert retry_plan.parent.name == "lazypack-mile_lz1-r2"
    out_dir_flag = retry["args"].index("--out-dir")
    retry_out_dir = Path(retry["args"][out_dir_flag + 1])
    assert retry_out_dir.parent == retry_plan.parent
    assert retry["result_artifact"] == str(retry_out_dir)
    assert retry["output_paths"] == [
        str(retry_plan),
        str(retry_out_dir / "1_framework.png"),
        str(retry_out_dir / "2_results.png"),
    ]
    assert json.loads(original.read_text(encoding="utf-8"))["alert_requeued_as"] == (
        "lazypack-mile_lz1-r2"
    )

    # Re-run while the retry is queued: the article is owned, nothing new.
    summary = lar.requeue_stranded(storage_dir=str(storage))
    assert summary["requeued"] == []

    # The retry fails too → a second (final) retry is allowed...
    retry["status"] = "failed"
    retry["completed_at"] = "2026-07-20T03:00:00+00:00"
    (qdir / "lazypack-mile_lz1-r2.json").write_text(
        json.dumps(retry, ensure_ascii=False), encoding="utf-8")
    summary = lar.requeue_stranded(storage_dir=str(storage))
    assert [r["new_job_id"] for r in summary["requeued"]] == ["lazypack-mile_lz1-r3"]

    # ...but the third failure hits the attempt ceiling: escalation belongs to
    # the P1 repair task, not an unbounded retry ladder.
    third = json.loads((qdir / "lazypack-mile_lz1-r3.json").read_text(encoding="utf-8"))
    third["status"] = "failed"
    third["completed_at"] = "2026-07-20T04:00:00+00:00"
    (qdir / "lazypack-mile_lz1-r3.json").write_text(
        json.dumps(third, ensure_ascii=False), encoding="utf-8")
    summary = lar.requeue_stranded(storage_dir=str(storage))
    assert summary["requeued"] == []
    assert any(s["reason"] == "attempt_ceiling" for s in summary["skipped"])


def test_requeue_stranded_missing_plan_fails_closed(
    storage, tmp_path, monkeypatch
):
    """A retry without its frozen input is not self-healing; never enqueue it."""
    qdir = _patch_queue(monkeypatch, tmp_path)
    original = _failed_job(
        qdir,
        "lazypack-mile_lz1",
        "mile_lz1",
        persist_plan=False,
    )

    summary = lar.requeue_stranded(storage_dir=str(storage))

    assert summary["requeued"] == []
    assert summary["skipped"] == [{
        "article_id": "mile_lz1",
        "job_id": "lazypack-mile_lz1",
        "reason": "plan_missing",
    }]
    assert not (qdir / "lazypack-mile_lz1-r2.json").exists()
    assert "alert_requeued_as" not in json.loads(
        original.read_text(encoding="utf-8")
    )


def test_requeue_stranded_skips_article_that_got_its_section(
    tmp_path, monkeypatch
):
    qdir = _patch_queue(monkeypatch, tmp_path)
    storage_dir = tmp_path / "storage"
    _write_feed(storage_dir, [{
        "id": "mile_ok",
        "status": "draft",
        "audience": "general",
        "title": "已補圖的文章",
        "content": "# 標題\n\n正文。\n\n## 懶人包圖組\n\n![圖](https://x.test/a.png)\n",
    }])
    _failed_job(qdir, "lazypack-mile_ok", "mile_ok")
    summary = lar.requeue_stranded(storage_dir=str(storage_dir))
    assert summary["requeued"] == []
    assert not (qdir / "lazypack-mile_ok-r2.json").exists()
