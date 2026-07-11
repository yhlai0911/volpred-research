"""The lazypack layout gate: a garbled panel must FAIL, a clean one must pass.

Regression for 2026-07-11 (boss email-12062/12066): mile_531e4c87 shipped three
panels with text clipped by the canvas and text stacked on text. Every one of them
passed the old success criterion — "the PNG exists, >1KB" — so no repair round
ever fired. These tests pin the three defects that criterion was blind to: text off
the CANVAS (clipped), text on text (overlap), and text out of its CARD (overflow).

The overflow tests carry two explicit false-positive pins (axes title, glyph in a
badge). A layout gate that cries wolf is worse than none — it gets switched off.
"""
from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path

import matplotlib
import pytest

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import Ellipse, Rectangle  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from lazypack_layout_guard import find_violations, install  # noqa: E402

GUARD = ROOT / "scripts" / "lazypack_layout_guard.py"


@pytest.fixture(autouse=True)
def _close_figures():
    yield
    plt.close("all")


def test_clean_layout_has_no_violations():
    """A well-spaced panel must not be flagged — a gate that cries wolf gets bypassed."""
    fig = plt.figure(figsize=(10, 6), dpi=100)
    fig.text(0.05, 0.85, "Title", fontsize=20)
    fig.text(0.05, 0.55, "Body line", fontsize=12)
    fig.text(0.05, 0.20, "Source: K1683", fontsize=8)
    assert find_violations(fig) == []


def test_text_running_off_the_canvas_is_clipped():
    """The right-edge cut that ate '…Leveraged Funds 期貨持倉' on panel 1."""
    fig = plt.figure(figsize=(10, 6), dpi=100)
    fig.text(0.75, 0.5, "a very long sentence that keeps going past the edge",
             fontsize=28)
    violations = find_violations(fig)
    assert any(v.startswith("CLIPPED") for v in violations), violations


def test_text_stacked_on_text_is_an_overlap():
    """The title-over-subtitle collision on every panel of the shipped set."""
    fig = plt.figure(figsize=(10, 6), dpi=100)
    fig.text(0.30, 0.50, "OVERLAPPING TITLE", fontsize=24)
    fig.text(0.32, 0.50, "subtitle underneath it", fontsize=14)
    violations = find_violations(fig)
    assert any(v.startswith("OVERLAP") for v in violations), violations


def test_savefig_raises_once_installed(tmp_path):
    """The gate's teeth: a broken figure cannot reach disk."""
    install()
    fig = plt.figure(figsize=(10, 6), dpi=100)
    fig.text(0.80, 0.5, "text that overruns the right edge by a mile", fontsize=30)
    out = tmp_path / "panel.png"
    with pytest.raises(RuntimeError, match="LAYOUT CHECK FAILED"):
        fig.savefig(out)
    assert not out.exists(), "a garbled panel must not be written at all"


def test_render_script_under_guard_exits_nonzero(tmp_path):
    """End-to-end: gen_lazypack_codex runs scripts this way, so the repair round
    only sees the defect if the guarded subprocess actually fails."""
    script = tmp_path / "render_lazypack.py"
    script.write_text(textwrap.dedent(f"""
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        fig = plt.figure(figsize=(10, 6), dpi=100)
        fig.text(0.85, 0.5, "clipped far past the right edge", fontsize=30)
        fig.savefig(r"{tmp_path / '1_panel.png'}")
    """), encoding="utf-8")

    proc = subprocess.run(
        [sys.executable, str(GUARD), str(script)],
        capture_output=True, text=True, timeout=120,
    )
    assert proc.returncode != 0, "a garbled render must fail, not 'succeed' silently"
    assert "LAYOUT CHECK FAILED" in (proc.stderr + proc.stdout)
    assert not (tmp_path / "1_panel.png").exists()


def _card_fig(text: str, fontsize: int = 12):
    """The lazypack house style: a Rectangle card with the copy laid inside it."""
    fig = plt.figure(figsize=(10, 6), dpi=100)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")
    ax.add_patch(Rectangle((0.10, 0.30), 0.35, 0.40, fill=False, ec="#d6dee8"))
    ax.text(0.12, 0.50, text, fontsize=fontsize, va="center")
    return fig


def test_text_bursting_out_of_its_card_is_an_overflow():
    """The boss's first-named defect (「文字溢出容器」): the line is still ON the canvas,
    so CLIPPED misses it, and it hits no other text, so OVERLAP misses it — yet it runs
    straight through the card's border. Regression for mile_3a7bd6f6/3_boundary.png,
    where 「results.json 註明…」 ran 109px past its card and still shipped."""
    fig = _card_fig("這一行長到直接衝出卡片右緣，讀者一眼就看得出來版面壞掉了", fontsize=16)
    violations = find_violations(fig)
    assert any(v.startswith("OVERFLOW") for v in violations), violations
    assert not any(v.startswith("CLIPPED") for v in violations), \
        "it never leaves the canvas — if CLIPPED fires, the fixture is not testing OVERFLOW"


def test_text_inside_its_card_is_not_an_overflow():
    """A gate that cries wolf on well-behaved cards gets bypassed."""
    fig = _card_fig("短句", fontsize=12)
    assert find_violations(fig) == []


def test_axes_title_above_a_card_is_not_an_overflow():
    """FP pin. `ax.set_title()` sits ABOVE the axes patch by construction, and axis /
    tick labels sit outside it too. Anchoring on 'the axes bbox' would flag every titled
    chart in the corpus. Containment is decided by the text's CENTRE point, so a title
    lands in no card at all and is never an overflow question."""
    fig = plt.figure(figsize=(10, 6), dpi=100)
    ax = fig.add_subplot(111)
    ax.plot([0, 1, 2], [1, 3, 2])
    ax.set_title("台指期波動率：模型比較", fontsize=18)
    ax.set_xlabel("交易日")
    ax.set_ylabel("已實現波動率")
    assert [v for v in find_violations(fig) if v.startswith("OVERFLOW")] == []


def test_glyph_centred_in_a_badge_is_not_an_overflow():
    """FP pin, calibrated on mile_0f7d1501/1_question.png: a 40pt「?」centred in an
    ellipse badge reads as flawless, but get_window_extent returns the FONT LINE BOX
    (ascent→descent), which overhangs the badge by 0.13 of the box height in pure
    whitespace. Real defects in the same corpus ran 0.35-0.46 — hence the vertical
    slack is a fraction of the line box, not a flat pixel count."""
    fig = plt.figure(figsize=(10, 6), dpi=100)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")
    ax.add_patch(Ellipse((0.30, 0.50), 0.10, 0.13, fc="#2563eb"))
    ax.text(0.30, 0.50, "?", fontsize=40, color="white", ha="center", va="center")
    assert [v for v in find_violations(fig) if v.startswith("OVERFLOW")] == []


def test_overflowing_render_script_under_guard_exits_nonzero(tmp_path):
    """End-to-end for the third defect class: gen_lazypack_codex.py only ever learns of a
    broken layout because the guarded subprocess returns non-zero. An overflow that never
    touches the canvas edge must still fail the run, or it ships (mile_531e4c87 did)."""
    out = tmp_path / "1_panel.png"
    script = tmp_path / "render_lazypack.py"
    script.write_text(textwrap.dedent(f"""
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from matplotlib.patches import Rectangle

        fig = plt.figure(figsize=(10, 6), dpi=100)
        ax = fig.add_axes([0, 0, 1, 1])
        ax.set_xlim(0, 1); ax.set_ylim(0, 1); ax.axis("off")
        ax.add_patch(Rectangle((0.10, 0.30), 0.30, 0.40, fill=False))
        ax.text(0.12, 0.50, "text far too long to stay inside this little card",
                fontsize=18, va="center")
        fig.savefig(r"{out}")
    """), encoding="utf-8")

    proc = subprocess.run(
        [sys.executable, str(GUARD), str(script)],
        capture_output=True, text=True, timeout=120,
    )
    combined = proc.stderr + proc.stdout
    assert proc.returncode != 0, "an overflowing render must fail, not 'succeed' silently"
    assert "OVERFLOW" in combined, combined
    assert not out.exists(), "a panel with text outside its card must not be written"


def test_every_bad_panel_is_reported_in_one_run(tmp_path):
    """Convergence: render scripts save panels one by one, so a guard that raised on
    panel 2 left panel 3 undrawn and each repair round saw one defect at a time —
    three panels could never be fixed inside the round budget. One run, all defects."""
    script = tmp_path / "render_lazypack.py"
    script.write_text(textwrap.dedent(f"""
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        for name, x in [("1_a", 0.85), ("2_b", 0.90), ("3_c", 0.1)]:
            fig = plt.figure(figsize=(10, 6), dpi=100)
            fig.text(x, 0.5, "a long line of panel text here", fontsize=30)
            fig.savefig(r"{tmp_path}/" + name + ".png")
            plt.close(fig)
    """), encoding="utf-8")

    proc = subprocess.run(
        [sys.executable, str(GUARD), str(script)],
        capture_output=True, text=True, timeout=120,
    )
    out = proc.stderr + proc.stdout
    assert proc.returncode != 0
    assert "1_a.png" in out and "2_b.png" in out, out
    assert (tmp_path / "3_c.png").exists(), "the clean panel still renders"


def test_clean_render_script_under_guard_still_succeeds(tmp_path):
    """The guard must not break the happy path it wraps."""
    out = tmp_path / "1_panel.png"
    script = tmp_path / "render_lazypack.py"
    script.write_text(textwrap.dedent(f"""
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        fig = plt.figure(figsize=(10, 6), dpi=100)
        fig.text(0.1, 0.8, "Title", fontsize=20)
        fig.text(0.1, 0.4, "Body", fontsize=12)
        fig.savefig(r"{out}")
    """), encoding="utf-8")

    proc = subprocess.run(
        [sys.executable, str(GUARD), str(script)],
        capture_output=True, text=True, timeout=120,
    )
    assert proc.returncode == 0, proc.stderr
    assert out.exists() and out.stat().st_size > 1024
