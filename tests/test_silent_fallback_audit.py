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
