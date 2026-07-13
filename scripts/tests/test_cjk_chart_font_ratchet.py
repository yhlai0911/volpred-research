"""Ratchet: no NEW figure script may draw CJK text without a CJK font.

matplotlib's default font has no CJK glyphs, so a Chinese title silently renders
as tofu boxes and ships into a published article — nothing fails, nothing logs,
only a human looking at the PNG can see it. It has now happened twice
(2026-06-11 k202/mile_872abdc3; 2026-07-13 CPI T-2/mile_9560b9cc), because the
first fix shipped a helper (`scripts/plot_style.py`) with no enforcement.

This test is that enforcement. The 47 pre-existing violations are frozen in
`storage/qa/cjk_chart_font_baseline.json` and may only shrink.

Fix a flagged script by calling `apply_cjk_style()` from scripts/plot_style.py
before any savefig, then remove it from the baseline.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
AUDIT = REPO_ROOT / "scripts" / "audit_cjk_chart_fonts.py"
BASELINE = REPO_ROOT / "storage" / "qa" / "cjk_chart_font_baseline.json"


def _load_audit():
    spec = importlib.util.spec_from_file_location("audit_cjk_chart_fonts", AUDIT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["audit_cjk_chart_fonts"] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def audit():
    return _load_audit()


def test_no_new_cjk_font_violations(audit):
    frozen = set(json.loads(BASELINE.read_text(encoding="utf-8"))["violations"])
    current = {v["path"] for v in audit.scan()}
    new = sorted(current - frozen)
    assert not new, (
        f"{len(new)} 個新腳本畫中文卻沒設 CJK 字型 → 會渲染成豆腐字：\n  "
        + "\n  ".join(new)
        + "\n\n修法：savefig 前呼叫 scripts/plot_style.py 的 apply_cjk_style()"
    )


def test_baseline_only_shrinks(audit):
    """A fixed script must be dropped from the baseline, so the count keeps falling."""
    frozen = set(json.loads(BASELINE.read_text(encoding="utf-8"))["violations"])
    current = {v["path"] for v in audit.scan()}
    stale = sorted(frozen - current)
    assert not stale, (
        f"{len(stale)} 個 baseline 項目已修好但還留在 baseline 裡，請移除：\n  "
        + "\n  ".join(stale)
    )


def test_detector_flags_cjk_without_font(audit, tmp_path):
    """Positive control — a gate that never fires is not a gate."""
    import ast

    src = 'import matplotlib.pyplot as plt\nplt.title("波動率")\n'
    assert audit._draws_cjk_text(ast.parse(src))
    assert not audit._establishes_cjk_font(src)


def test_detector_accepts_apply_cjk_style(audit):
    import ast

    src = (
        "import matplotlib.pyplot as plt\n"
        "from plot_style import apply_cjk_style\n"
        "apply_cjk_style()\n"
        'plt.title("波動率")\n'
    )
    assert audit._draws_cjk_text(ast.parse(src))
    assert audit._establishes_cjk_font(src)


def test_detector_ignores_chinese_docstrings(audit):
    """CJK in a docstring or log line is not rendered — must not be flagged."""
    import ast

    src = (
        '"""這個腳本畫圖。"""\n'
        "import matplotlib.pyplot as plt\n"
        "print('開始畫圖')\n"
        'plt.title("Volatility")\n'
    )
    assert not audit._draws_cjk_text(ast.parse(src))
