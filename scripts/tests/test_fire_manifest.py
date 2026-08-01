"""Stage-1 gate for declared fire ownership (docs/refactor_commit_ownership_state_machine.md).

Each test below pins one historical incident's trigger condition, so the gate
fails if the property that would have prevented that incident is lost.
"""
from __future__ import annotations

import json
import subprocess
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from volpred.ops import fire_manifest as fm


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=root, check=True)
    return root


def _write(root: Path, rel: str, text: str = "x") -> None:
    target = root / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")


# ── location: the ledger can never become the orphan it prevents ─────────────

def test_manifests_live_in_the_git_dir_and_never_dirty_the_tree(repo: Path) -> None:
    fm.open_manifest(repo, fire_id="f1", actor="test")
    _write(repo, "a.py")
    fm.record(repo, "f1", "a.py")
    proc = subprocess.run(["git", "status", "--porcelain", "-uall"],
                          cwd=repo, capture_output=True, text=True, check=True)
    assert "volpred_fire_manifests" not in proc.stdout
    assert fm.manifest_dir(repo).is_relative_to(repo / ".git")


def test_fire_id_cannot_escape_the_manifest_directory(repo: Path) -> None:
    with pytest.raises(fm.FireManifestError):
        fm.open_manifest(repo, fire_id="../../etc/passwd", actor="test")


def test_actor_is_mandatory_because_an_unnamed_owner_is_not_ownership(repo: Path) -> None:
    with pytest.raises(fm.FireManifestError):
        fm.open_manifest(repo, fire_id="f1", actor="")


# ── ownership is declared, not inferred ──────────────────────────────────────

def test_concurrent_slots_do_not_claim_each_others_output(repo: Path) -> None:
    """telegram-1203 / the 2026-07-19 78-fire pile-up: slot A's baseline is taken
    before slot B writes, so B's bytes land inside A's window. Declaration has no
    window, so A's answer is unchanged by B's activity."""
    fm.open_manifest(repo, fire_id="A", actor="slot-1", slot_id="slot-1")
    fm.open_manifest(repo, fire_id="B", actor="slot-2", slot_id="slot-2")
    _write(repo, "mine.py")
    _write(repo, "theirs.py")
    fm.record(repo, "A", "mine.py")
    fm.record(repo, "B", "theirs.py")

    got = fm.resolve_ownership(repo, {"mine.py", "theirs.py"}, fire_id="A")
    assert got["owned"] == ["mine.py"]
    assert got["foreign"] == {"theirs.py": "B"}
    assert got["orphan"] == []


def test_a_path_dirty_before_the_fire_is_still_owned_when_declared(repo: Path) -> None:
    """`owned = dirty_now - baseline` drops any path already dirty at fire start,
    even when this fire really did edit it (the "contribution vanished" half of
    the external review's three necessary misclassifications)."""
    _write(repo, "pre_existing.py", "old")
    baseline = {"pre_existing.py"}
    fm.open_manifest(repo, fire_id="A", actor="slot-1")
    _write(repo, "pre_existing.py", "edited by this fire")
    fm.record(repo, "A", "pre_existing.py")

    got = fm.resolve_ownership(repo, {"pre_existing.py"}, fire_id="A")
    assert got["owned"] == ["pre_existing.py"]
    # the arithmetic PHASE-Z uses today would have said the opposite
    assert sorted({"pre_existing.py"} - baseline) == []


def test_two_declared_owners_is_contested_and_never_silently_owned(repo: Path) -> None:
    """Two writers on one path cannot be split by a set difference at all; today
    it resolves to whichever fire observed it first. Contested is an explicit
    state with no auto-commit exit."""
    fm.open_manifest(repo, fire_id="A", actor="slot-1")
    fm.open_manifest(repo, fire_id="B", actor="slot-2")
    _write(repo, "shared.json")
    fm.record(repo, "A", "shared.json")
    fm.record(repo, "B", "shared.json")

    got = fm.resolve_ownership(repo, {"shared.json"}, fire_id="A")
    assert got["owned"] == []
    assert got["contested"] == {"shared.json": ["A", "B"]}


def test_undeclared_dirt_is_orphan_not_this_fires_output(repo: Path) -> None:
    """docs/error_log.md 2026-07-10: `git add -A` swept an interactive session's
    half-finished edits into a dispatch commit. An undeclared path is never
    owned — the default answer is "nobody", not "you"."""
    fm.open_manifest(repo, fire_id="A", actor="slot-1")
    _write(repo, "someone_elses_wip.py")
    got = fm.resolve_ownership(repo, {"someone_elses_wip.py"}, fire_id="A")
    assert got["owned"] == []
    assert got["orphan"] == ["someone_elses_wip.py"]


def test_a_dead_producers_claim_expires_but_keeps_its_name(repo: Path) -> None:
    """telegram-1263 (files unclaimed for many fires): an orphan today is
    anonymous, so nobody can be asked about it. A stale claim stops blocking but
    still says who abandoned it."""
    now = time.time()
    fm.open_manifest(repo, fire_id="dead", actor="slot-9", now=now - fm.MAX_AGE_S - 60)
    _write(repo, "stranded.py")
    fm.record(repo, "dead", "stranded.py", now=now - fm.MAX_AGE_S - 60)

    got = fm.resolve_ownership(repo, {"stranded.py"}, fire_id="A", now=now)
    assert got["stale"] == {"stranded.py": "dead"}
    assert got["foreign"] == {} and got["owned"] == []


def test_abandoned_manifest_releases_its_claim(repo: Path) -> None:
    """A gate-blocked or dead fire must not hold paths hostage forever — the
    2026-07-18 "only off switch is deleting the receipt by hand" shape."""
    fm.open_manifest(repo, fire_id="A", actor="slot-1")
    _write(repo, "f.py")
    fm.record(repo, "A", "f.py")
    fm.close(repo, "A", state=fm.STATE_ABANDONED, reason="gate red")
    got = fm.resolve_ownership(repo, {"f.py"}, fire_id="B")
    assert got["orphan"] == ["f.py"]


# ── atomicity: the change set, not the path, is the unit ─────────────────────

def test_seal_pins_the_whole_change_set_with_one_digest(repo: Path) -> None:
    """docs/error_log.md 2026-07-21 00:29: tests and the implementation they
    import were split across two commits and main was red (and running broken
    production code) for 32 minutes. A seal covers all declared paths at once."""
    fm.open_manifest(repo, fire_id="A", actor="slot-1")
    _write(repo, "src/impl.py", "def f(): ...")
    _write(repo, "tests/test_impl.py", "import impl")
    fm.record(repo, "A", "src/impl.py")
    fm.record(repo, "A", "tests/test_impl.py")
    sealed = fm.seal(repo, "A")

    assert sealed["state"] == fm.STATE_SEALED
    assert [p["path"] for p in sealed["seal"]["paths"]] == ["src/impl.py", "tests/test_impl.py"]
    assert len(sealed["seal"]["digest"]) == 64


def test_seal_digest_changes_when_any_member_of_the_set_changes(repo: Path) -> None:
    fm.open_manifest(repo, fire_id="A", actor="slot-1")
    _write(repo, "a.py", "one")
    fm.record(repo, "A", "a.py")
    first = fm.seal(repo, "A")["seal"]["digest"]

    fm.open_manifest(repo, fire_id="B", actor="slot-1")
    _write(repo, "a.py", "two")
    fm.record(repo, "B", "a.py")
    second = fm.seal(repo, "B")["seal"]["digest"]
    assert first != second


def test_a_sealed_fire_cannot_grow_new_output(repo: Path) -> None:
    fm.open_manifest(repo, fire_id="A", actor="slot-1")
    _write(repo, "a.py")
    fm.record(repo, "A", "a.py")
    fm.seal(repo, "A")
    _write(repo, "late.py")
    with pytest.raises(fm.FireManifestError):
        fm.record(repo, "A", "late.py")


def test_recording_without_opening_is_refused(repo: Path) -> None:
    _write(repo, "a.py")
    with pytest.raises(fm.FireManifestError):
        fm.record(repo, "never-opened", "a.py")


def test_reopening_a_live_fire_keeps_one_ledger(repo: Path) -> None:
    """A retried attempt must not split its output across two manifests: half a
    change set landing is exactly the 2026-07-21 partial-commit shape."""
    fm.open_manifest(repo, fire_id="A", actor="slot-1")
    _write(repo, "a.py")
    fm.record(repo, "A", "a.py")
    again = fm.open_manifest(repo, fire_id="A", actor="slot-1")
    assert [e["path"] for e in again["entries"]] == ["a.py"]


def test_deletions_are_declared_output_too(repo: Path) -> None:
    fm.open_manifest(repo, fire_id="A", actor="slot-1")
    fm.record(repo, "A", "gone.py", op=fm.OP_DELETE)
    got = fm.resolve_ownership(repo, {"gone.py"}, fire_id="A")
    assert got["owned"] == ["gone.py"]
    assert fm.read(repo, "A")["entries"][0]["sha256"] is None


# ── robustness: the ledger may not become a new way to wedge ─────────────────

def test_a_corrupt_manifest_degrades_to_no_declaration_not_an_exception(repo: Path) -> None:
    """2026-07-18: a fail-closed unreadable receipt left the module permanently
    unable to record ownership, silently. Corruption must cost attribution for
    one fire, never the whole mechanism."""
    fm.open_manifest(repo, fire_id="good", actor="slot-1")
    _write(repo, "a.py")
    fm.record(repo, "good", "a.py")
    (fm.manifest_dir(repo) / "broken.json").write_text("{not json", encoding="utf-8")

    got = fm.resolve_ownership(repo, {"a.py"}, fire_id="good")
    assert got["owned"] == ["a.py"]


def test_prune_keeps_unfinished_fires_and_drops_old_terminal_ones(repo: Path) -> None:
    old = time.time() - 30 * 24 * 3600
    fm.open_manifest(repo, fire_id="old-done", actor="slot-1", now=old)
    fm.close(repo, "old-done", state=fm.STATE_COMMITTED, commit="deadbeef")
    fm.open_manifest(repo, fire_id="old-open", actor="slot-1", now=old)

    removed = fm.prune(repo)
    assert removed == ["old-done"]
    assert fm.read(repo, "old-open") is not None


def test_absolute_paths_inside_the_repo_are_normalised(repo: Path) -> None:
    fm.open_manifest(repo, fire_id="A", actor="slot-1")
    _write(repo, "sub/a.py")
    fm.record(repo, "A", str(repo / "sub" / "a.py"))
    assert fm.read(repo, "A")["entries"][0]["path"] == "sub/a.py"


def test_paths_outside_the_repo_are_refused(repo: Path, tmp_path: Path) -> None:
    fm.open_manifest(repo, fire_id="A", actor="slot-1")
    with pytest.raises(fm.FireManifestError):
        fm.record(repo, "A", str(tmp_path / "elsewhere.py"))


# ── shadow mode ──────────────────────────────────────────────────────────────

def test_shadow_reports_what_the_arithmetic_would_have_over_claimed(repo: Path) -> None:
    """The measurement that justifies stage 2: paths PHASE-Z would commit under
    this fire's name that nobody declared."""
    fm.open_manifest(repo, fire_id="A", actor="slot-1")
    _write(repo, "mine.py")
    fm.record(repo, "A", "mine.py")
    _write(repo, "not_mine.py")

    got = fm.shadow_compare(repo, dirty_now={"mine.py", "not_mine.py"},
                            baseline=set(), fire_id="A")
    assert got["inferred"] == ["mine.py", "not_mine.py"]
    assert got["declared"] == ["mine.py"]
    assert got["inferred_not_declared"] == ["not_mine.py"]
    assert got["declared_not_inferred"] == []


def test_shadow_reports_what_the_arithmetic_would_have_dropped(repo: Path) -> None:
    fm.open_manifest(repo, fire_id="A", actor="slot-1")
    _write(repo, "pre.py")
    fm.record(repo, "A", "pre.py")
    got = fm.shadow_compare(repo, dirty_now={"pre.py"}, baseline={"pre.py"}, fire_id="A")
    assert got["inferred"] == []
    assert got["declared_not_inferred"] == ["pre.py"]


def test_shadow_is_read_only(repo: Path) -> None:
    """It runs beside a live commit path, so it may not mutate anything it reads."""
    fm.open_manifest(repo, fire_id="A", actor="slot-1")
    _write(repo, "a.py")
    fm.record(repo, "A", "a.py")
    before = json.dumps(fm.read(repo, "A"), sort_keys=True)
    head_before = subprocess.run(["git", "status", "--porcelain", "-uall"],
                                 cwd=repo, capture_output=True, text=True, check=True).stdout

    fm.observe_shadow(repo, dirty_now={"a.py"}, baseline=set(), fire_id="A")

    assert json.dumps(fm.read(repo, "A"), sort_keys=True) == before
    after = subprocess.run(["git", "status", "--porcelain", "-uall"],
                           cwd=repo, capture_output=True, text=True, check=True).stdout
    assert after == head_before


def test_shadow_never_raises_even_when_the_ledger_is_unusable(repo: Path, monkeypatch) -> None:
    """A bug in the shadow path must not be able to affect a commit decision."""
    def _boom(*_a, **_k):
        raise RuntimeError("ledger exploded")

    monkeypatch.setattr(fm, "resolve_ownership", _boom)
    assert fm.observe_shadow(repo, dirty_now={"a.py"}, baseline=set(), fire_id="A") is None


def test_shadow_observations_are_appended_as_jsonl_in_the_git_dir(repo: Path) -> None:
    fm.open_manifest(repo, fire_id="A", actor="slot-1")
    _write(repo, "a.py")
    fm.record(repo, "A", "a.py")
    fm.observe_shadow(repo, dirty_now={"a.py", "b.py"}, baseline=set(), fire_id="A")
    fm.observe_shadow(repo, dirty_now={"a.py"}, baseline=set(), fire_id="A")

    log = fm.shadow_log_path(repo)
    assert log.is_relative_to(repo / ".git")
    rows = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 2
    assert rows[0]["inferred_not_declared"] == ["b.py"]


def test_shadow_marks_a_missing_baseline_instead_of_pretending_to_agree(repo: Path) -> None:
    """"No baseline" and "baseline says nothing is yours" must not collapse."""
    fm.open_manifest(repo, fire_id="A", actor="slot-1")
    _write(repo, "a.py")
    fm.record(repo, "A", "a.py")
    got = fm.shadow_compare(repo, dirty_now={"a.py"}, baseline=None, fire_id="A")
    assert got["baseline_available"] is False
    assert got["declared"] == ["a.py"]


def test_shadow_cohort_counts_declarations_from_every_fire(repo: Path) -> None:
    fm.open_manifest(repo, fire_id="A", actor="slot-1")
    fm.open_manifest(repo, fire_id="B", actor="slot-2")
    _write(repo, "a.py")
    _write(repo, "b.py")
    fm.record(repo, "A", "a.py")
    fm.record(repo, "B", "b.py")

    got = fm.shadow_compare(
        repo,
        dirty_now={"a.py", "b.py"},
        baseline=set(),
        fire_ids={"A", "B"},
    )

    assert got["fire_ids"] == ["A", "B"]
    assert got["declared"] == ["a.py", "b.py"]
    assert got["inferred_not_declared"] == []


# ── stage-2 acceptance is evidence, never legacy cutover authority ──────────

def _shadow_row(
    at: datetime,
    *,
    fire_ids: list[str] | None,
    missing: list[str] | None = None,
    declared: list[str] | None = None,
    baseline_available: bool = True,
) -> dict:
    return {
        "at": at.astimezone(UTC).isoformat().replace("+00:00", "Z"),
        "fire_id": None,
        "fire_ids": fire_ids or [],
        "baseline_available": baseline_available,
        "inferred": sorted(set(missing or []) | set(declared or [])),
        "declared": sorted(declared or []),
        "agree": sorted(declared or []),
        "inferred_not_declared": sorted(missing or []),
        "declared_not_inferred": [],
    }


def _expected_fire(fire_id: str, opened_at: datetime) -> dict:
    return {
        "fire_id": fire_id,
        "opened_at": opened_at.astimezone(UTC).isoformat().replace("+00:00", "Z"),
    }


def _hourly_slots(start: datetime, hours: int) -> list[datetime]:
    return [start + timedelta(hours=index) for index in range(hours + 1)]


def test_stage2_green_metrics_cannot_revive_superseded_manifest_cutover() -> None:
    start = datetime(2026, 7, 25, tzinfo=UTC)
    rows = []
    expected_fires = []
    for index in range(169):
        fire_ids = [] if index < 8 else [f"fire-{index}"]
        rows.append(
            _shadow_row(
                start + timedelta(hours=index),
                fire_ids=fire_ids,
                missing=["storage/ops/state.json"],
                declared=[f"src/output_{index}.py"] if fire_ids else [],
            )
        )
        if fire_ids:
            expected_fires.append(
                _expected_fire(fire_ids[0], start + timedelta(hours=index))
            )

    report = fm.assess_shadow_records(
        rows,
        assessed_at=start + timedelta(days=7),
        expected_fires=expected_fires,
        expected_schedule=_hourly_slots(start, 168),
        classify_path=lambda path: (
            "machine_state" if path.startswith("storage/") else "non_machine"
        ),
    )

    assert report["legacy_stage2_metrics_pass"] is True
    assert report["metrics"]["identity_coverage"] == pytest.approx(161 / 169)
    assert report["metrics"]["expected_fire_coverage"] == 1.0
    assert report["metrics"]["median_inferred_not_declared"] == 1
    assert report["manifest_cutover_eligible"] is False
    assert report["status"] == "superseded_contract_blocked"
    assert report["successor_contract"]["issue_refs"] == ["#41", "#43", "#44"]
    assert "legacy_manifest_stage3_superseded" in report["cutover_blockers"]


def test_stage2_assessment_identifies_failed_metrics_and_missing_path_lanes() -> None:
    start = datetime(2026, 7, 25, tzinfo=UTC)
    rows = [
        _shadow_row(start, fire_ids=None),
        _shadow_row(
            start + timedelta(days=3),
            fire_ids=["fire-1"],
            missing=["storage/next_tasks.json", "src/foreign_wip.py"],
            baseline_available=False,
        ),
        _shadow_row(
            start + timedelta(days=7),
            fire_ids=None,
            missing=["storage/next_tasks.json"],
        ),
    ]

    report = fm.assess_shadow_records(
        rows,
        assessed_at=start + timedelta(days=7),
        expected_fires=[
            _expected_fire("fire-1", start + timedelta(days=3)),
        ],
        expected_schedule=_hourly_slots(start, 168),
        classify_path=lambda path: (
            "machine_state" if path.startswith("storage/") else "non_machine"
        ),
    )

    assert report["legacy_stage2_metrics_pass"] is False
    assert report["metrics"]["identity_coverage"] == pytest.approx(1 / 3)
    # Every observed shift is a "班".  The two identity-less rows may not be
    # discarded from the median merely because the attribution hook missed.
    assert report["metrics"]["median_inferred_not_declared"] == 1
    assert report["metrics"]["baseline_available_throughout"] is False
    assert report["missing_path_occurrences"] == {
        "machine_state": 2,
        "non_machine": 1,
    }
    assert report["legacy_metric_blockers"] == [
        "observation_cadence_incomplete",
        "identity_coverage_below_95pct",
        "baseline_unavailable_in_window",
        "baseline_or_decline_contract_violated",
    ]


def test_stage2_assessment_fails_closed_on_partial_or_malformed_evidence() -> None:
    now = datetime(2026, 8, 1, tzinfo=UTC)
    partial = [
        _shadow_row(now - timedelta(days=1), fire_ids=["fire-1"]),
        _shadow_row(now, fire_ids=["fire-2"]),
    ]

    report = fm.assess_shadow_records(
        partial,
        assessed_at=now,
        expected_fires=[_expected_fire("fire-1", now - timedelta(days=1)),
                        _expected_fire("fire-2", now)],
        expected_schedule=_hourly_slots(now - timedelta(days=7), 168),
    )

    assert report["legacy_stage2_metrics_pass"] is False
    assert "observation_cadence_incomplete" in report["legacy_metric_blockers"]

    with pytest.raises(fm.FireManifestError, match="shadow record 0 has invalid at"):
        fm.assess_shadow_records(
            [{"at": "not-a-time"}],
            assessed_at=now,
            expected_fires=[],
            expected_schedule=_hourly_slots(now - timedelta(days=7), 168),
        )


def test_stage2_sparse_endpoints_cannot_impersonate_continuous_seven_days() -> None:
    start = datetime(2026, 7, 25, tzinfo=UTC)
    end = start + timedelta(days=7)
    rows = [
        _shadow_row(start, fire_ids=["fire-start"]),
        _shadow_row(end, fire_ids=["fire-end"]),
    ]

    report = fm.assess_shadow_records(
        rows,
        assessed_at=end,
        expected_fires=[
            _expected_fire("fire-start", start),
            _expected_fire("fire-end", end),
        ],
        expected_schedule=_hourly_slots(start, 168),
    )

    assert report["window"]["full_window"] is False
    assert report["window"]["max_observation_gap_seconds"] == 7 * 24 * 3600
    assert "observation_cadence_incomplete" in report["legacy_metric_blockers"]


def test_stage2_stale_historical_ledger_is_not_current_evidence() -> None:
    start = datetime(2026, 7, 25, tzinfo=UTC)
    last = start + timedelta(days=7)
    assessed_at = last + timedelta(hours=3)
    rows = [
        _shadow_row(start + timedelta(hours=index), fire_ids=[f"fire-{index}"])
        for index in range(169)
    ]

    report = fm.assess_shadow_records(
        rows,
        assessed_at=assessed_at,
        expected_fires=[
            _expected_fire(f"fire-{index}", start + timedelta(hours=index))
            for index in range(169)
        ],
        expected_schedule=_hourly_slots(assessed_at - timedelta(days=7), 168),
    )

    assert report["window"]["fresh"] is False
    assert "shadow_evidence_stale" in report["legacy_metric_blockers"]


def test_stage2_reconciles_missing_and_unexpected_fire_identities() -> None:
    start = datetime(2026, 8, 1, tzinfo=UTC)
    rows = [
        _shadow_row(
            start + timedelta(hours=index),
            fire_ids=[f"fire-{index}" if index < 24 else "unexpected-fire"],
        )
        for index in range(25)
    ]
    expected = [
        _expected_fire(f"fire-{index}", start + timedelta(hours=index))
        for index in range(24)
    ]
    expected.extend([
        _expected_fire("missing-fire-1", start + timedelta(hours=24)),
        _expected_fire("missing-fire-2", start + timedelta(hours=24)),
    ])

    report = fm.assess_shadow_records(
        rows,
        window_days=1,
        assessed_at=start + timedelta(days=1),
        expected_fires=expected,
        expected_schedule=_hourly_slots(start, 24),
    )

    assert report["metrics"]["identity_coverage"] == 1.0
    assert report["metrics"]["expected_fire_coverage"] == pytest.approx(24 / 26)
    assert report["metrics"]["missing_expected_fire_ids_sample"] == [
        "missing-fire-1",
        "missing-fire-2",
    ]
    assert report["metrics"]["unexpected_observed_fire_ids_sample"] == [
        "unexpected-fire"
    ]
    assert "expected_fire_coverage_below_95pct" in report["legacy_metric_blockers"]
    assert "observed_fire_missing_manifest_receipt" in report["legacy_metric_blockers"]


def test_stage2_all_baselines_missing_cannot_report_measurement_pass() -> None:
    start = datetime(2026, 7, 25, tzinfo=UTC)
    rows = [
        _shadow_row(
            start + timedelta(hours=index),
            fire_ids=[f"fire-{index}"],
            baseline_available=False,
        )
        for index in range(169)
    ]
    report = fm.assess_shadow_records(
        rows,
        assessed_at=start + timedelta(days=7),
        expected_fires=[
            _expected_fire(f"fire-{index}", start + timedelta(hours=index))
            for index in range(169)
        ],
        expected_schedule=_hourly_slots(start, 168),
    )

    assert report["metrics"]["identity_coverage"] == 1.0
    assert report["metrics"]["expected_fire_coverage"] == 1.0
    assert report["metrics"]["median_inferred_not_declared"] == 0
    assert report["legacy_stage2_metrics_pass"] is False
    assert "baseline_unavailable_in_window" in report["legacy_metric_blockers"]


def test_stage2_schema_is_fail_closed_and_median_uses_every_shift() -> None:
    start = datetime(2026, 8, 1, tzinfo=UTC)
    rows = [
        _shadow_row(start, fire_ids=["fire-0"], missing=[]),
        _shadow_row(start + timedelta(hours=12), fire_ids=[], missing=[f"p/{i}" for i in range(10)]),
        _shadow_row(start + timedelta(days=1), fire_ids=[], missing=[f"q/{i}" for i in range(10)]),
    ]
    report = fm.assess_shadow_records(
        rows,
        window_days=1,
        identity_threshold=0.1,
        assessed_at=start + timedelta(days=1),
        expected_fires=[_expected_fire("fire-0", start)],
        expected_schedule=[start, start + timedelta(hours=12), start + timedelta(days=1)],
    )
    assert report["metrics"]["median_inferred_not_declared"] == 10

    invalid_identity = _shadow_row(start, fire_ids=["fire-0"])
    invalid_identity["fire_ids"] = [None]
    with pytest.raises(fm.FireManifestError, match="fire_ids must be a string list"):
        fm.assess_shadow_records(
            [invalid_identity],
            window_days=1,
            assessed_at=start,
            expected_fires=[_expected_fire("fire-0", start)],
            expected_schedule=[start - timedelta(days=1), start],
        )

    legacy_identity_missing = _shadow_row(start, fire_ids=[])
    del legacy_identity_missing["fire_ids"]
    legacy_report = fm.assess_shadow_records(
        [legacy_identity_missing],
        window_days=1,
        assessed_at=start,
        expected_fires=[],
        expected_schedule=[start - timedelta(days=1), start],
    )
    assert legacy_report["metrics"]["identity_observations"] == 0
    assert "identity_coverage_below_95pct" in legacy_report["legacy_metric_blockers"]

    missing_gap_field = _shadow_row(start, fire_ids=["fire-0"])
    del missing_gap_field["inferred_not_declared"]
    with pytest.raises(
        fm.FireManifestError,
        match="inferred_not_declared must be a string list",
    ):
        fm.assess_shadow_records(
            [missing_gap_field],
            window_days=1,
            assessed_at=start,
            expected_fires=[_expected_fire("fire-0", start)],
            expected_schedule=[start - timedelta(days=1), start],
        )
