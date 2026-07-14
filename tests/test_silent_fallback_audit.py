from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "audit_silent_fallbacks.py"
SPEC = importlib.util.spec_from_file_location("audit_silent_fallbacks", MODULE_PATH)
audit_silent_fallbacks = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = audit_silent_fallbacks
SPEC.loader.exec_module(audit_silent_fallbacks)


def test_audit_flags_silent_pass_continue_and_default_return(tmp_path: Path) -> None:
    source = tmp_path / "sample.py"
    source.write_text(
        """
def a():
    try:
        risky()
    except ValueError:
        return None

def b(items):
    for item in items:
        try:
            parse(item)
        except OSError:
            continue

def c():
    try:
        cleanup()
    except FileNotFoundError:
        pass
""",
        encoding="utf-8",
    )

    findings = audit_silent_fallbacks.audit_file(source, root=tmp_path)

    assert [(item.line, item.exception, item.action) for item in findings] == [
        (5, "ValueError", "return None"),
        (12, "OSError", "continue"),
        (18, "FileNotFoundError", "pass"),
    ]


def test_audit_ignores_warned_or_reraised_handlers(tmp_path: Path) -> None:
    source = tmp_path / "sample.py"
    source.write_text(
        """
import logging

LOG = logging.getLogger(__name__)

def a():
    try:
        risky()
    except ValueError as exc:
        LOG.warning("fallback", exc_info=exc)
        return None

def b():
    try:
        risky()
    except OSError:
        raise
""",
        encoding="utf-8",
    )

    findings = audit_silent_fallbacks.audit_file(source, root=tmp_path)

    assert findings == []


def test_audit_accepts_returned_exception_findings_collector(tmp_path: Path) -> None:
    """`bad.append(exc); continue` is observable when the collector truly escapes."""

    source = tmp_path / "sample.py"
    source.write_text(
        """
def audit(items):
    bad: list[str] = []
    checked = 0
    for item in items:
        try:
            parse(item)
        except SyntaxError as exc:
            bad.append(f"BAD {item}: {exc}")
            continue
        checked += 1
    return bad, checked
""",
        encoding="utf-8",
    )

    assert audit_silent_fallbacks.audit_file(source, root=tmp_path) == []


def test_audit_does_not_whitelist_arbitrary_append_collectors(tmp_path: Path) -> None:
    source = tmp_path / "sample.py"
    source.write_text(
        """
def dead_local(items):
    findings = []
    for item in items:
        try:
            parse(item)
        except ValueError as exc:
            findings.append(str(exc))
            continue
    return []

def payload_omits_exception(items):
    bad = []
    for item in items:
        try:
            parse(item)
        except ValueError as exc:
            bad.append("generic failure")
            continue
    return bad

def cleared_before_return(items):
    bad = []
    for item in items:
        try:
            parse(item)
        except ValueError as exc:
            bad.append(str(exc))
            continue
    bad.clear()
    return bad

def default_return_is_unobservable(items):
    bad = []
    for item in items:
        try:
            parse(item)
        except ValueError as exc:
            bad.append(str(exc))
            return None
    return bad

def conditional_append_is_not_enough(items, verbose):
    bad = []
    for item in items:
        try:
            parse(item)
        except ValueError as exc:
            if verbose:
                bad.append(str(exc))
            continue
    return bad

def clear_result_is_not_the_collector(items):
    bad = []
    for item in items:
        try:
            parse(item)
        except ValueError as exc:
            bad.append(str(exc))
            continue
    return bad.clear()

def length_is_not_the_collector(items):
    bad = []
    for item in items:
        try:
            parse(item)
        except ValueError as exc:
            bad.append(str(exc))
            continue
    return len(bad)

def intermediate_return_can_hide_the_collector(items, stop):
    bad = []
    for item in items:
        try:
            parse(item)
        except ValueError as exc:
            bad.append(str(exc))
            continue
    if stop:
        return None
    return bad

def slice_clear_destroys_the_collector(items):
    bad = []
    for item in items:
        try:
            parse(item)
        except ValueError as exc:
            bad.append(str(exc))
            continue
    bad[:] = []
    return bad

def boolean_exception_marker_loses_the_detail(items):
    bad = []
    for item in items:
        try:
            parse(item)
        except ValueError as exc:
            bad.append(bool(exc))
            continue
    return bad

def alias_can_clear_the_collector(items):
    bad = []
    for item in items:
        try:
            parse(item)
        except ValueError as exc:
            bad.append(str(exc))
            continue
    alias = bad
    alias.clear()
    return bad

def annotated_alias_can_clear_the_collector(items):
    bad = []
    for item in items:
        try:
            parse(item)
        except ValueError as exc:
            bad.append(str(exc))
            continue
    alias: list = bad
    alias.clear()
    return bad

def raise_makes_the_return_unreachable(items):
    bad = []
    for item in items:
        try:
            parse(item)
        except ValueError as exc:
            bad.append(str(exc))
            continue
    raise RuntimeError("stop")
    return bad

def multiplying_detail_away_is_not_observable(items):
    bad = []
    for item in items:
        try:
            parse(item)
        except ValueError as exc:
            bad.append(str(exc) * 0)
            continue
    return bad

def escaped_collector_can_be_cleared_by_callee(items):
    bad = []
    for item in items:
        try:
            parse(item)
        except ValueError as exc:
            bad.append(str(exc))
            continue
    zap(bad)
    return bad

def unknown_collector_method_can_mutate(items):
    bad = []
    for item in items:
        try:
            parse(item)
        except ValueError as exc:
            bad.append(str(exc))
            continue
    bad.__setitem__(slice(None), [])
    return bad

def pre_handler_call_alias_can_mutate(items):
    bad = []
    alias = identity(bad)
    for item in items:
        try:
            parse(item)
        except ValueError as exc:
            bad.append(str(exc))
            continue
    alias.clear()
    return bad

def post_handler_container_alias_can_mutate(items):
    bad = []
    for item in items:
        try:
            parse(item)
        except ValueError as exc:
            bad.append(str(exc))
            continue
    aliases = [bad]
    aliases[0].clear()
    return bad
""",
        encoding="utf-8",
    )

    findings = audit_silent_fallbacks.audit_file(source, root=tmp_path)

    assert [finding.action for finding in findings] == [
        "continue",
        "continue",
        "continue",
        "return None",
        "continue",
        "continue",
        "continue",
        "continue",
        "continue",
        "continue",
        "continue",
        "continue",
        "continue",
        "continue",
        "continue",
        "continue",
        "continue",
        "continue",
    ]


def test_audit_ignores_inline_silent_ok_comments(tmp_path: Path) -> None:
    source = tmp_path / "sample.py"
    source.write_text(
        """
def cleanup(tmp):
    try:
        tmp.unlink()
    except FileNotFoundError:
        pass  # silent-ok: cleanup race-safe
""",
        encoding="utf-8",
    )

    findings = audit_silent_fallbacks.audit_file(source, root=tmp_path)

    assert findings == []


def test_baseline_diff_reports_only_new_findings() -> None:
    existing = audit_silent_fallbacks.Finding("scripts/a.py", 10, "Exception", "return None")
    new = audit_silent_fallbacks.Finding("scripts/b.py", 20, "ValueError", "continue")

    new_findings, resolved_findings = audit_silent_fallbacks.diff_against_baseline(
        [existing, new],
        [existing],
    )

    assert new_findings == [new]
    assert resolved_findings == []


def test_baseline_diff_ignores_line_shift_when_signature_matches() -> None:
    before = audit_silent_fallbacks.Finding(
        "scripts/a.py",
        10,
        "ValueError",
        "return None",
        signature="v1:stable",
    )
    after = audit_silent_fallbacks.Finding(
        "scripts/a.py",
        25,
        "ValueError",
        "return None",
        signature="v1:stable",
    )

    new_findings, resolved_findings = audit_silent_fallbacks.diff_against_baseline(
        [after],
        [before],
    )

    assert new_findings == []
    assert resolved_findings == []


def test_baseline_diff_counts_duplicate_stable_findings() -> None:
    existing = audit_silent_fallbacks.Finding(
        "scripts/a.py",
        10,
        "ValueError",
        "return None",
        signature="v1:stable",
    )
    duplicate = audit_silent_fallbacks.Finding(
        "scripts/a.py",
        20,
        "ValueError",
        "return None",
        signature="v1:stable",
    )

    new_findings, resolved_findings = audit_silent_fallbacks.diff_against_baseline(
        [existing, duplicate],
        [existing],
    )

    assert new_findings == [duplicate]
    assert resolved_findings == []


def test_signature_survives_line_shift_but_new_bare_pass_is_new(tmp_path: Path) -> None:
    source = tmp_path / "sample.py"
    source.write_text(
        """
def parse_value():
    try:
        risky()
    except ValueError:
        return None
""",
        encoding="utf-8",
    )
    baseline = audit_silent_fallbacks.audit_file(source, root=tmp_path)

    source.write_text(
        """


def parse_value():
    try:
        risky()
    except ValueError:
        return None

def cleanup():
    try:
        remove_temp()
    except:
        pass
""",
        encoding="utf-8",
    )
    current = audit_silent_fallbacks.audit_file(source, root=tmp_path)

    new_findings, resolved_findings = audit_silent_fallbacks.diff_against_baseline(
        current,
        baseline,
    )

    assert baseline[0].line != current[0].line
    assert baseline[0].stable_key() == current[0].stable_key()
    assert [(item.exception, item.action) for item in new_findings] == [("bare", "pass")]
    assert resolved_findings == []


def test_human_report_prints_summary(capsys) -> None:
    findings = [
        audit_silent_fallbacks.Finding("scripts/a.py", 10, "Exception", "return None"),
        audit_silent_fallbacks.Finding("scripts/a.py", 20, "ValueError", "continue"),
        audit_silent_fallbacks.Finding("src/volpred/b.py", 30, "OSError", "continue"),
    ]

    audit_silent_fallbacks._human_report(findings, limit=1)

    out = capsys.readouterr().out
    assert "[silent-fallback-audit] findings=3" in out
    assert "[silent-fallback-audit] by_action: continue=2, return None=1" in out
    assert "[silent-fallback-audit] by_root: scripts=2, src=1" in out
    assert "[silent-fallback-audit] top_paths: scripts/a.py=2" in out


def test_load_baseline_accepts_metadata_object(tmp_path: Path) -> None:
    baseline_path = tmp_path / "baseline.json"
    baseline_path.write_text(
        """
{
  "schema": "silent_fallback_baseline.v1",
  "count": 1,
  "findings": [
    {
      "path": "scripts/a.py",
      "line": 10,
      "exception": "Exception",
      "action": "return None"
    }
  ]
}
""",
        encoding="utf-8",
    )

    baseline = audit_silent_fallbacks.load_baseline(baseline_path)

    assert baseline == [
        audit_silent_fallbacks.Finding("scripts/a.py", 10, "Exception", "return None")
    ]


def test_write_baseline_persists_line_insensitive_signatures(tmp_path: Path) -> None:
    source = tmp_path / "sample.py"
    source.write_text(
        """
def parse_value():
    try:
        risky()
    except ValueError:
        return None
""",
        encoding="utf-8",
    )
    baseline_path = tmp_path / "baseline.json"
    findings = audit_silent_fallbacks.audit_file(source, root=tmp_path)

    audit_silent_fallbacks.write_baseline(baseline_path, findings)

    raw = baseline_path.read_text(encoding="utf-8")
    assert '"schema": "silent_fallback_baseline.v2"' in raw
    assert '"signature": "v1:' in raw


def test_main_strict_with_baseline_fails_for_new_finding(
    tmp_path: Path,
    monkeypatch,
) -> None:
    source = tmp_path / "sample.py"
    source.write_text(
        """
def a():
    try:
        risky()
    except ValueError:
        return None
""",
        encoding="utf-8",
    )
    baseline_path = tmp_path / "baseline.json"
    baseline_path.write_text('{"findings": []}\n', encoding="utf-8")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "audit_silent_fallbacks.py",
            "--strict",
            "--baseline",
            str(baseline_path),
            str(source),
        ],
    )

    assert audit_silent_fallbacks.main() == 1


def test_iter_python_files_skips_test_directories_by_default(tmp_path: Path) -> None:
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    prod = scripts / "prod.py"
    prod.write_text("def ok():\n    return 1\n", encoding="utf-8")
    test_dir = scripts / "tests"
    test_dir.mkdir()
    (test_dir / "test_helper.py").write_text("def helper():\n    return 1\n", encoding="utf-8")

    files = audit_silent_fallbacks.iter_python_files([scripts])

    assert files == [prod]
