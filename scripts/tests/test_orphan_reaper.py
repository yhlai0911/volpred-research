"""產出即交付 — orphan deliverable reaper 的回歸測試（boss msg 624）。

被測的是一個 class bug：**完成的產出走到「丟棄」那一格**。所以測試分兩層：

- 行為層：孤兒認得出來、已交付的不重收、半成品保留不丟。
- Ratchet 層：**沒有任何一條路徑會刪檔**，而且 alert 不再把「丟棄」寫成正當出口。
  第二層是重點 —— 行為 bug 會被使用者發現，但「alert 建議老闆丟掉成品」不會有人抱怨，
  它只會安靜地浪費掉一篇文章。

跑法：uv run --extra dev python -m pytest scripts/tests/test_orphan_reaper.py -q
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import reap_orphan_deliverables as reaper  # noqa: E402

FINISHED_BODY = "分析內容。" * 300  # comfortably past MIN_BODY_CHARS


def _draft(dir_: Path, name: str, *, title: str, body: str = FINISHED_BODY,
           audience: str = "general", kid: str = "", age_hours: float = 5.0) -> Path:
    fm = [f"title: {title}", f"audience: {audience}"]
    if kid:
        fm.append(f"kid: {kid}")
    path = dir_ / name
    path.write_text("---\n" + "\n".join(fm) + "\n---\n\n" + body, encoding="utf-8")
    old = time.time() - age_hours * 3600
    import os
    os.utime(path, (old, old))
    return path


@pytest.fixture()
def env(tmp_path, monkeypatch):
    """Point the reaper at a throwaway tree — never at the real storage/."""
    drafts = tmp_path / "storage" / "drafts"
    drafts.mkdir(parents=True)
    feed = tmp_path / "storage" / "reports" / "feed.json"
    feed.parent.mkdir(parents=True)
    feed.write_text("[]", encoding="utf-8")
    tasks = tmp_path / "storage" / "next_tasks.json"
    tasks.write_text("[]", encoding="utf-8")
    baseline = tmp_path / "storage" / "ops" / "orphan_draft_baseline.json"
    baseline.parent.mkdir(parents=True)
    baseline.write_text(json.dumps({"drafts": []}), encoding="utf-8")

    monkeypatch.setattr(reaper, "ROOT", tmp_path)
    monkeypatch.setattr(reaper, "DRAFTS_DIR", drafts)
    monkeypatch.setattr(reaper, "FEED_PATH", feed)
    monkeypatch.setattr(reaper, "TASKS_PATH", tasks)
    monkeypatch.setattr(reaper, "BASELINE_PATH", baseline)
    monkeypatch.setattr(reaper, "REPORT_PATH", tmp_path / "storage" / "ops" / "report.json")
    return {"root": tmp_path, "drafts": drafts, "feed": feed,
            "tasks": tasks, "baseline": baseline}


def _set_feed(env, articles):
    env["feed"].write_text(json.dumps(articles, ensure_ascii=False), encoding="utf-8")


# ── 行為層 ────────────────────────────────────────────────────────────────────

def test_finished_unregistered_draft_is_an_orphan(env):
    """核心案例：drone EP3 —— 寫完了、沒人收、feed 查無此文。"""
    _draft(env["drafts"], "drone_ep3_general_draft.md", title="無人機系列 EP3 下游深度")
    result = reaper.scan()
    assert [e["path"] for e in result["adoptable"]] == ["storage/drafts/drone_ep3_general_draft.md"]
    assert result["held"] == []


def test_delivered_draft_is_left_alone_via_source_draft(env):
    """有交付憑證（details.source_draft）→ 已經是文章了，不可重發。"""
    rel = "storage/drafts/shipped_draft.md"
    _draft(env["drafts"], "shipped_draft.md", title="已發佈的文章")
    _set_feed(env, [{"id": "mile_abc", "title": "標題後來被編輯過了",
                     "details": {"source_draft": rel}}])
    result = reaper.scan()
    assert result["adoptable"] == []
    assert result["skipped"]["registered"] == 1


def test_delivered_draft_is_left_alone_via_title_fallback(env):
    """provenance 欄位上線前發的文章沒有回連 — 標題比對是唯一誠實的退路。"""
    _draft(env["drafts"], "legacy_draft.md", title="VIX 破 30 抄底有效嗎")
    _set_feed(env, [{"id": "mile_old", "title": "VIX 破 30 抄底有效嗎", "details": {}}])
    assert reaper.scan()["adoptable"] == []


def test_k_coverage_counts_as_delivered(env):
    """同一個 K 在同一 audience 已有文章 → 這份是重複稿，不是孤兒。"""
    _draft(env["drafts"], "k1633_draft.md", title="另一個標題", audience="general", kid="K1633")
    _set_feed(env, [{"id": "mile_k", "title": "不同標題", "audience": "general",
                     "details": {"experiment_refs": ["K1633"]}}])
    assert reaper.scan()["adoptable"] == []


def test_k_coverage_does_not_cross_audiences(env):
    """同 K 的 research 版與 general 版是產品設計，不是重複（publishing.md）。"""
    _draft(env["drafts"], "k99_general.md", title="散戶版", audience="general", kid="K99")
    _set_feed(env, [{"id": "mile_r", "title": "研究版", "audience": "research",
                     "details": {"experiment_refs": ["K99"]}}])
    assert len(reaper.scan()["adoptable"]) == 1


def test_fresh_draft_is_still_being_written(env):
    """grace window 內的檔案可能有人正在打字 —— 半篇文章比晚一小時糟得多。"""
    _draft(env["drafts"], "wip_draft.md", title="還在寫", age_hours=0.2)
    result = reaper.scan()
    assert result["adoptable"] == []
    assert result["skipped"]["grace"] == 1


def test_inflight_task_owns_its_draft(env):
    """有 live task 認領中 = 有 owner，不是孤兒。"""
    _draft(env["drafts"], "claimed_draft.md", title="有人在做")
    env["tasks"].write_text(json.dumps([
        {"id": "t1", "status": "in_progress",
         "description": "寫 storage/drafts/claimed_draft.md"}
    ], ensure_ascii=False), encoding="utf-8")
    result = reaper.scan()
    assert result["adoptable"] == []
    assert result["skipped"]["inflight"] == 1


def test_baseline_drafts_are_out_of_scope(env):
    """cutover 前的 519 份不重新翻案 —— 否則第一次跑就是 519 個偽陽性。"""
    _draft(env["drafts"], "ancient_draft.md", title="遠古草稿")
    env["baseline"].write_text(
        json.dumps({"drafts": ["storage/drafts/ancient_draft.md"]}), encoding="utf-8")
    assert reaper.scan()["adoptable"] == []


def test_stub_is_held_not_discarded(env):
    """半成品保留給作者 —— held，不是 adoptable，更不是刪掉。"""
    _draft(env["drafts"], "stub_draft.md", title="只有標題", body="還沒寫")
    result = reaper.scan()
    assert result["adoptable"] == []
    assert [h["reason"] for h in result["held"]] == ["too_short"]
    assert (env["drafts"] / "stub_draft.md").exists(), "held 的檔案必須原封不動留著"


def test_untitled_draft_is_held_not_discarded(env):
    _draft(env["drafts"], "untitled.md", title="")
    result = reaper.scan()
    assert [h["reason"] for h in result["held"]] == ["no_title"]
    assert (env["drafts"] / "untitled.md").exists()


def test_scan_never_removes_a_file(env):
    """整個 scan 是唯讀的 —— 掃描本身不該有任何 side effect。"""
    paths = [
        _draft(env["drafts"], "orphan.md", title="孤兒"),
        _draft(env["drafts"], "stub.md", title="短", body="x"),
    ]
    reaper.scan()
    assert all(p.exists() for p in paths)


# ── Ratchet 層：class bug 不得復發 ─────────────────────────────────────────────

DESTRUCTIVE = ("unlink", "rmtree", "os.remove", "checkout HEAD --", "git rm")


def test_reaper_source_contains_no_destructive_call():
    """不變量：這支程式**沒有能力**丟棄成品。靠的是 source 裡沒有那種呼叫，不是自律。"""
    src = (REPO_ROOT / "scripts" / "reap_orphan_deliverables.py").read_text(encoding="utf-8")
    code = "\n".join(
        line for line in src.splitlines()
        if not line.lstrip().startswith("#")
    )
    # docstring 裡談論「丟棄」是說明，不是行為 —— 只掃實際呼叫形式。
    for token in DESTRUCTIVE:
        assert token not in code, f"reaper 不得含破壞性呼叫: {token}"


def test_phase_z_alert_never_offers_discard_as_an_exit():
    """PHASE-Z 的 alert 曾把 `git checkout HEAD -- <檔案>` 當成正當出口之一，
    完成的產出就死在那一格（boss msg 624）。這條 ratchet 釘住它不會回來。"""
    src = (REPO_ROOT / "scripts" / "dispatch_supervisor" / "phase_z.py").read_text(encoding="utf-8")
    alert_bodies = src[src.index("def run_phase_z") if "def run_phase_z" in src else 0:]
    assert "丟掉" not in alert_bodies, "alert 不得建議丟掉未提交的檔案"
    assert "commit 或捨棄" not in alert_bodies, "alert 不得把『捨棄』列為二選一的出口"
