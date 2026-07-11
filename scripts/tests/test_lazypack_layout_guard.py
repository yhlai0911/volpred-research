"""The lazypack layout gate: a garbled panel must FAIL, a clean one must pass.

Regression for 2026-07-11 (boss email-12062/12066): mile_531e4c87 shipped three
panels with text clipped by the canvas and text stacked on text. Every one of them
passed the old success criterion — "the PNG exists, >1KB" — so no repair round
ever fired. These tests pin the two defects that criterion was blind to.
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
