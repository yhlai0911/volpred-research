"""The tofu-chart gate has to fire BEFORE publish, not after.

A CI ratchet for CJK chart fonts already existed when k1703 shipped (2026-07-14),
and it did its job — it turned CI red. But CI runs on push, and publish happens
before that, so readers saw three PNGs of empty boxes while the ratchet was busy
being correct in the background. Same verdict, wrong side of the boundary.

These tests pin the verdict at the publish boundary. The scenario is k1703's
verbatim shape: an article embedding /article-images/<kid>/fig*.png whose
generator script calls plt without ever establishing a CJK font.
"""
from __future__ import annotations

from pathlib import Path

from volpred.publisher.prepublish_audit import audit_chart_cjk_fonts

TOFU_SCRIPT = """
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

fig, ax = plt.subplots()
ax.set_ylabel("平均年化實現波動率 (%)")
fig.savefig("fig1_rv_by_week_type.png")
"""

CLEAN_SCRIPT = """
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
from plot_style import apply_cjk_style

apply_cjk_style()

fig, ax = plt.subplots()
ax.set_ylabel("平均年化實現波動率 (%)")
fig.savefig("fig1_rv_by_week_type.png")
"""

ARTICLE = (
    "圖表如下。\n\n"
    "![SPY 結算週波動]"
    "(https://x.supabase.co/storage/v1/object/public/article-images/k1703/fig1_rv_by_week_type.png)\n"
)


def _experiment(root: Path, k_id: str, source: str) -> None:
    exp = root / "experiments" / k_id
    exp.mkdir(parents=True)
    (exp / f"{k_id}.py").write_text(source, encoding="utf-8")


def test_tofu_generator_is_caught_before_the_article_ships(tmp_path: Path) -> None:
    _experiment(tmp_path, "k1703", TOFU_SCRIPT)

    result = audit_chart_cjk_fonts(ARTICLE, root=tmp_path)

    assert [v["k_id"] for v in result["violations"]] == ["k1703"]
    assert result["violations"][0]["path"].endswith("k1703.py")


def test_a_script_that_sets_the_font_publishes_clean(tmp_path: Path) -> None:
    _experiment(tmp_path, "k1703", CLEAN_SCRIPT)

    result = audit_chart_cjk_fonts(ARTICLE, root=tmp_path)

    assert result["violations"] == []
    assert result["checked"]  # the script really was inspected, not skipped


def test_image_key_with_no_experiment_dir_fails_open(tmp_path: Path) -> None:
    """An unresolvable key is not evidence of tofu — blocking on it would be a
    content black hole, which `.claude/rules/dedup-gate-audit.md` forbids."""
    result = audit_chart_cjk_fonts(ARTICLE, root=tmp_path)

    assert result == {"violations": [], "checked": []}


def test_article_with_no_experiment_charts_is_not_audited(tmp_path: Path) -> None:
    _experiment(tmp_path, "k1703", TOFU_SCRIPT)
    lazypack_only = (
        "![懶人包]"
        "(https://x.supabase.co/storage/v1/object/public/article-images/lazypack/panel_results.png)\n"
    )

    result = audit_chart_cjk_fonts(lazypack_only, root=tmp_path)

    assert result == {"violations": [], "checked": []}
