"""Tests for the 懶人包 (lazypack) publish gate in publish_draft.py.

Boss hard requirement (2026-06-04, re-raised 2026-06-30 at 12% coverage): every
general-audience reader article must append a 懶人包圖組 (cheat-sheet infographic
SET) at the end. The detection layer (content_quality lazypack coverage) only
WARNED, so this gate enforces it deterministically at the publish chokepoint.

See .claude/rules/publishing.md §4 + lazypack-infographic skill.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import publish_draft  # noqa: E402
from publish_draft import (  # noqa: E402
    check_deferred_lazypack_contract,
    check_lazypack_gate,
)

PASS = 0
BLOCK = 6

_LAZYPACK_SECTION = (
    "## 懶人包圖組\n\n"
    "![概念](https://supabase.test/article-images/k1_concept.png)\n\n"
    "![結果](https://supabase.test/article-images/k1_results.png)\n"
)


def test_general_with_lazypack_section_passes():
    body = "# 標題\n\n正文…\n\n" + _LAZYPACK_SECTION
    assert check_lazypack_gate(body, "general", bypass=False) == PASS


def test_general_without_any_lazypack_blocks():
    body = "# 標題\n\n正文…\n\n![圖](https://x/a.png)\n\n## 結論\n收尾。\n"
    assert check_lazypack_gate(body, "general", bypass=False) == BLOCK


def test_general_lazypack_heading_but_no_image_blocks():
    # Heading present but no image after it → empty/placeholder section, must block.
    body = "# 標題\n\n![圖](https://x/a.png)\n\n## 懶人包圖組\n\n（待補圖）\n"
    assert check_lazypack_gate(body, "general", bypass=False) == BLOCK


def test_general_bare_prose_mention_blocks():
    # The word 懶人包 in prose (not a heading) does NOT satisfy the gate.
    body = "# 標題\n\n這篇沒有懶人包，只是順口提到而已。\n\n![圖](https://x/a.png)\n"
    assert check_lazypack_gate(body, "general", bypass=False) == BLOCK


def test_bypass_flag_passes_even_when_missing():
    body = "# 標題\n\n正文，無懶人包。\n"
    assert check_lazypack_gate(body, "general", bypass=True) == PASS


def test_research_audience_exempt():
    body = "# 研究標題\n\n專業內容，無懶人包。\n"
    assert check_lazypack_gate(body, "research", bypass=False) == PASS


def test_member_qa_audience_exempt():
    body = "# 會員問答\n\n回答，無懶人包。\n"
    assert check_lazypack_gate(body, "member_qa", bypass=False) == PASS


def test_image_before_heading_does_not_count():
    # An image that appears BEFORE the 懶人包 heading must not satisfy it.
    body = (
        "# 標題\n\n![前置圖](https://x/a.png)\n\n## 懶人包圖組\n\n（文字，無圖）\n"
    )
    assert check_lazypack_gate(body, "general", bypass=False) == BLOCK


def test_fail_open_on_gate_malfunction():
    # A non-str body makes the internal regex raise TypeError → fail-open (PASS),
    # per no-silent-fallback.md + dedup-gate-audit.md (never over-block on error).
    assert check_lazypack_gate(None, "general", bypass=False) == PASS  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# 2026-07-02 async pipeline (error_log 15:15 #4): enforcement moved to the
# reader-visible boundary — draft/scheduled pass without the section (render
# runs on compute_queue; release gate holds the flip), published still blocks.
# ---------------------------------------------------------------------------

_NO_LZ_BODY = "# 標題\n\n正文，無懶人包。\n"


def test_draft_status_defers_lazypack_to_async(capsys):
    assert check_lazypack_gate(_NO_LZ_BODY, "general", bypass=False,
                               status="draft") == PASS
    out = capsys.readouterr().out
    assert "lazypack_async_render.py enqueue" in out


def test_scheduled_status_defers_lazypack_to_async():
    assert check_lazypack_gate(_NO_LZ_BODY, "general", bypass=False,
                               status="scheduled") == PASS


def test_published_status_still_blocks():
    assert check_lazypack_gate(_NO_LZ_BODY, "general", bypass=False,
                               status="published") == BLOCK


def test_default_status_is_published_enforce():
    # Callers that do not pass status must get the SAFE default (enforce) —
    # a silently-relaxed default would reopen the 12%-coverage hole.
    assert check_lazypack_gate(_NO_LZ_BODY, "general", bypass=False) == BLOCK


def test_draft_with_lazypack_still_passes_quietly(capsys):
    body = "# 標題\n\n正文…\n\n" + _LAZYPACK_SECTION
    assert check_lazypack_gate(body, "general", bypass=False, status="draft") == PASS
    assert "lazypack_async_render" not in capsys.readouterr().out


def test_lazypack_required_at_boundary_semantics():
    from volpred.publisher.publisher import lazypack_required_at

    assert lazypack_required_at("published") is True
    assert lazypack_required_at(None) is True          # safe default
    assert lazypack_required_at(" Published ") is True
    assert lazypack_required_at("draft") is False
    assert lazypack_required_at("scheduled") is False


def test_new_general_draft_without_deferred_plan_fails_before_publish(
    tmp_path, monkeypatch
):
    """A deferred render is not real unless a validated plan can be queued.

    The old CLI returned success after creating a general draft with neither a
    lazypack section nor ``--lazypack-plan``.  Such drafts can never leave the
    release pool, so a daily-article task could be marked succeeded while
    publishing remained deadlocked.  The canonical CLI must reject that
    impossible hand-off before it mutates the feed.
    """
    draft = tmp_path / "general-without-plan.md"
    draft.write_text(
        "\n".join(
            [
                "---",
                "title: 市場波動的簡單觀察",
                "audience: general",
                "tags: [一般讀者, 波動率]",
                "---",
                "",
                "這篇文章用公開資料說明市場波動如何改變。",
                "",
                "## 圖表",
                "",
                "![趨勢](https://example.com/trend.png)",
                "",
                "![比較](https://example.com/comparison.png)",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "publish_draft.py",
            str(draft),
            "--phase",
            "research",
            "--status",
            "draft",
            "--dry-run",
        ],
    )

    assert publish_draft.main() == BLOCK


def test_deferred_lazypack_preflight_fails_closed_when_checker_breaks(
    monkeypatch,
):
    """A broken prerequisite checker cannot recreate an unreleasable draft."""
    import volpred.publisher.publisher as publisher

    def broken_checker(_body):
        raise RuntimeError("checker unavailable")

    monkeypatch.setattr(publisher, "has_lazypack_section", broken_checker)

    assert (
        check_deferred_lazypack_contract(
            _NO_LZ_BODY,
            "general",
            bypass=False,
            status="draft",
            plan=None,
        )
        == BLOCK
    )


def test_deferred_gate_checker_failure_remains_observable(capsys, monkeypatch):
    """Update mode may stay fail-open, but the checker failure cannot disappear."""
    import volpred.publisher.publisher as publisher

    def broken_checker(_body):
        raise RuntimeError("checker unavailable")

    monkeypatch.setattr(publisher, "has_lazypack_section", broken_checker)

    assert (
        check_lazypack_gate(
            _NO_LZ_BODY,
            "general",
            bypass=False,
            status="draft",
        )
        == PASS
    )
    assert "deferred-check warning" in capsys.readouterr().err


def test_published_checker_failure_is_not_reblocked_by_deferred_preflight(
    monkeypatch,
):
    """The deferred contract must preserve the reader-visible gate's fail-open policy."""
    import volpred.publisher.publisher as publisher

    def broken_checker(_body):
        raise RuntimeError("checker unavailable")

    monkeypatch.setattr(publisher, "has_lazypack_section", broken_checker)

    assert (
        check_deferred_lazypack_contract(
            _NO_LZ_BODY,
            "general",
            bypass=False,
            status="published",
            plan=None,
        )
        == PASS
    )


def test_draft_boundary_failure_cannot_bypass_deferred_preflight(monkeypatch):
    """A broken canonical boundary must not create an ownerless draft."""
    import volpred.publisher.publisher as publisher

    def broken_boundary(_status):
        raise RuntimeError("boundary unavailable")

    monkeypatch.setattr(publisher, "lazypack_required_at", broken_boundary)

    assert (
        check_deferred_lazypack_contract(
            _NO_LZ_BODY,
            "general",
            bypass=False,
            status="draft",
            plan=None,
        )
        == BLOCK
    )


def test_published_boundary_failure_preserves_reader_gate_fail_open(monkeypatch):
    """The deferred fallback must not reclassify published content as deferred."""
    import volpred.publisher.publisher as publisher

    def broken_boundary(_status):
        raise RuntimeError("boundary unavailable")

    monkeypatch.setattr(publisher, "lazypack_required_at", broken_boundary)

    assert (
        check_deferred_lazypack_contract(
            _NO_LZ_BODY,
            "general",
            bypass=False,
            status="published",
            plan=None,
        )
        == PASS
    )


def _deferred_plan_fixture(tmp_path: Path) -> dict:
    evidence = tmp_path / "evidence.json"
    evidence.write_text('{"result":{"value":0.123}}\n', encoding="utf-8")
    digest = hashlib.sha256(evidence.read_bytes()).hexdigest()
    binding = {
        "source": "main",
        "path": "/result/value",
        "format": {"kind": "percent", "digits": 1},
    }
    return {
        "schema_version": 1,
        "title": "測試懶人包",
        "evidence": {
            "main": {
                "path": str(evidence),
                "sha256": digest,
                "label": "測試 evidence",
            }
        },
        "panels": [
            {
                "name": "framework",
                "info": "concept",
                "style": "professional",
                "title": "核心問題",
                "alt": "解釋研究問題",
                "sources": ["main"],
                "blocks": [
                    {"kind": "text", "heading": "問題", "body": ["先界定比較。"]}
                ],
            },
            {
                "name": "result",
                "info": "results",
                "style": "professional",
                "title": "主要結果",
                "alt": "呈現主要結果",
                "sources": ["main"],
                "blocks": [
                    {"kind": "metric", "label": "結果", "value": binding}
                ],
            },
        ],
    }


def test_deferred_plan_with_unresolvable_binding_fails_before_publish(tmp_path):
    """Schema-valid plans are not runnable until every evidence pointer resolves."""
    document = _deferred_plan_fixture(tmp_path)
    document["panels"][1]["blocks"][0]["value"]["path"] = "/missing/field"
    invalid_plan = tmp_path / "invalid-binding-plan.json"
    invalid_plan.write_text(
        json.dumps(document, ensure_ascii=False),
        encoding="utf-8",
    )

    assert (
        check_deferred_lazypack_contract(
            _NO_LZ_BODY,
            "general",
            bypass=False,
            status="draft",
            plan=str(invalid_plan),
        )
        == BLOCK
    )


# --- article-id read-back (2026-08-01, K1325 misroute) -----------------------
#
# _settle_deferred_lazypack used to take the FIRST mile_* appearing anywhere in
# the publisher's stdout. That stdout also carries gate notes and a
# publication_candidates refresh naming other articles, so on K1325 the plan was
# queued against mile_80cae4cb — an unrelated article published a month earlier.
# Binding a render to the wrong article corrupts a live body AND strands the new
# draft, so the read-back must come from the publisher's own JSON receipt.


def test_article_id_ignores_ids_that_precede_the_publish_receipt():
    """The exact stdout shape that misrouted K1325 must resolve to K1325's id."""
    stdout = (
        "[publish] lazypack deferred for mile_80cae4cb (status=draft)\n"
        "Stored milestone mile_3445217e\n"
        'JSON: {"action": "publish_milestone", "id": "mile_3445217e", '
        '"status": "draft"}\n'
        "[publish] publication_candidates refreshed after new_publish\n"
    )

    assert publish_draft._article_id_from_publish_stdout(stdout) == "mile_3445217e"


def test_article_id_ignores_unrelated_json_after_publish_receipt():
    """Only the publish-milestone receipt may bind the deferred render owner."""
    stdout = (
        'JSON: {"action": "publish_milestone", "id": "mile_111111aa", '
        '"status": "draft"}\n'
        'JSON: {"id": "mile_222222bb", "status": "draft"}\n'
    )

    assert publish_draft._article_id_from_publish_stdout(stdout) == "mile_111111aa"


def test_article_id_falls_back_to_the_anchored_stored_line():
    """No JSON receipt: the anchored line still beats a bare id floating in noise."""
    stdout = "note about mile_80cae4cb\nStored milestone mile_3445217e\n"

    assert publish_draft._article_id_from_publish_stdout(stdout) == "mile_3445217e"


def test_article_id_returns_none_rather_than_guessing():
    """An unparseable receipt costs one manual enqueue; a guess costs an article."""
    stdout = "candidates refreshed: mile_80cae4cb, mile_47c4bc3e\n"

    assert publish_draft._article_id_from_publish_stdout(stdout) is None


def test_malformed_publish_receipt_is_observable_before_fallback(capsys):
    """Malformed structured output may fall back, but never silently."""
    stdout = "JSON: {not valid json}\nStored milestone mile_3445217e\n"

    assert publish_draft._article_id_from_publish_stdout(stdout) == "mile_3445217e"
    assert "ignored malformed publish receipt" in capsys.readouterr().err


def test_deferred_settlement_fails_when_publish_receipt_has_no_article_id():
    """A successful publish without an identifiable render owner is a hard failure."""
    assert (
        publish_draft.settle_deferred_lazypack(
            stdout="publish completed without a structured receipt\n",
            body=_NO_LZ_BODY,
            audience="general",
            status="draft",
            plan="plan.json",
            bypass=False,
        )
        == 8
    )


def test_deferred_settlement_fails_when_enqueue_transport_errors(monkeypatch):
    """A queued-render transport error cannot be reported as publish success."""
    def timeout(*_args, **_kwargs):
        raise TimeoutError("compute queue unavailable")

    monkeypatch.setattr(publish_draft.subprocess, "run", timeout)

    assert (
        publish_draft.settle_deferred_lazypack(
            stdout=(
                'JSON: {"action": "publish_milestone", '
                '"id": "mile_abcdef12", "status": "draft"}\n'
            ),
            body=_NO_LZ_BODY,
            audience="general",
            status="draft",
            plan="plan.json",
            bypass=False,
        )
        == 8
    )


def test_deferred_settlement_fails_without_render_plan():
    """No caller may turn an ownerless deferred render into a successful publish."""
    assert (
        publish_draft.settle_deferred_lazypack(
            stdout=(
                'JSON: {"action": "publish_milestone", '
                '"id": "mile_abcdef12", "status": "draft"}\n'
            ),
            body=_NO_LZ_BODY,
            audience="general",
            status="draft",
            plan=None,
            bypass=False,
        )
        == 8
    )


def test_valid_plan_flows_from_main_to_exact_durable_enqueue_receipt(
    tmp_path, monkeypatch
):
    """A valid deferred publish reaches a durable render owner for the exact new id."""
    draft = tmp_path / "general-with-plan.md"
    draft.write_text(
        "\n".join(
            [
                "---",
                "title: 市場波動的簡單觀察",
                "audience: general",
                "tags: [一般讀者, 波動率]",
                "---",
                "",
                "這篇文章用公開資料說明市場波動如何改變。",
                "",
                "## 圖表",
                "",
                "![趨勢](https://example.com/trend.png)",
                "",
                "![比較](https://example.com/comparison.png)",
            ]
        ),
        encoding="utf-8",
    )
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(
        json.dumps(_deferred_plan_fixture(tmp_path), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    storage_dir = tmp_path / "storage"
    feed_path = storage_dir / "reports" / "feed.json"
    feed_path.parent.mkdir(parents=True)
    feed_path.write_text(
        json.dumps(
            [
                {
                    "id": "mile_abcdef12",
                    "title": "市場波動的簡單觀察",
                    "status": "draft",
                    "audience": "general",
                    "content": "正文，等待懶人包。",
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    import compute_queue as compute_queue_module
    import lazypack_async_render

    queue_dir = storage_dir / "ops" / "compute_queue"
    monkeypatch.setattr(compute_queue_module, "QUEUE_DIR", queue_dir)
    monkeypatch.setattr(compute_queue_module, "LOCK_FILE", queue_dir / ".worker.lock")
    monkeypatch.setattr(
        compute_queue_module,
        "LOG_DIR",
        storage_dir / "logs" / "compute",
    )

    def run_boundary(command, *args, **kwargs):
        if command[:5] == ["uv", "run", "volpred", "ops", "publish-milestone"]:
            return publish_draft.subprocess.CompletedProcess(
                command,
                0,
                stdout=(
                    'JSON: {"action": "publish_milestone", '
                    '"id": "mile_abcdef12", "status": "draft"}\n'
                ),
                stderr="",
            )
        if "scripts/lazypack_async_render.py" in command:
            enqueue_args = [
                *command[command.index("enqueue"):],
                "--storage-dir",
                str(storage_dir),
            ]
            prior_argv = sys.argv
            try:
                sys.argv = ["lazypack_async_render.py", *enqueue_args]
                returncode = lazypack_async_render.main()
            finally:
                sys.argv = prior_argv
            return publish_draft.subprocess.CompletedProcess(
                command,
                returncode,
                stdout="",
                stderr="",
            )
        raise AssertionError(f"unexpected subprocess boundary: {command}")

    monkeypatch.setattr(publish_draft.subprocess, "run", run_boundary)
    monkeypatch.setattr(
        publish_draft,
        "_refresh_publication_candidates_after_feed_change",
        lambda _reason: None,
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "publish_draft.py",
            str(draft),
            "--phase",
            "research",
            "--status",
            "draft",
            "--lazypack-plan",
            str(plan_path),
            "--force-duplicate",
        ],
    )

    assert publish_draft.main() == PASS

    job_path = storage_dir / "ops" / "compute_queue" / "lazypack-mile_abcdef12.json"
    job = json.loads(job_path.read_text(encoding="utf-8"))
    assert job["status"] == "queued"
    assert job["args"][job["args"].index("--article-id") + 1] == "mile_abcdef12"
    frozen_plan = Path(job["args"][job["args"].index("--plan") + 1])
    assert frozen_plan.is_file()
    assert hashlib.sha256(frozen_plan.read_bytes()).hexdigest() == hashlib.sha256(
        plan_path.read_bytes()
    ).hexdigest()
