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


def _run_pillow_script(tmp_path: Path, body: str, *, audit_only: bool = False):
    script = tmp_path / "render_pillow.py"
    source = (
        "from pathlib import Path\n"
        "from PIL import Image, ImageDraw\n\n"
        f"OUT = Path(r\"{tmp_path}\")\n\n"
        + textwrap.dedent(body).strip()
        + "\n"
    )
    script.write_text(source, encoding="utf-8")
    cmd = [sys.executable, str(GUARD)]
    if audit_only:
        cmd.append("--audit-only")
    cmd.append(str(script))
    return subprocess.run(cmd, capture_output=True, text=True, timeout=120)


def test_clean_pillow_render_under_guard_succeeds(tmp_path):
    """Pillow was the structural blind spot: its clean path must stay usable."""
    proc = _run_pillow_script(tmp_path, """
        img = Image.new("RGB", (500, 250), "white")
        draw = ImageDraw.Draw(img)
        draw.rounded_rectangle((20, 20, 480, 220), radius=16,
                               fill="#f8fafc", outline="#94a3b8", width=2)
        draw.text((45, 65), "Clean Pillow title", fill="#0f172a")
        draw.text((45, 125), "Body on its own row", fill="#475569")
        img.save(OUT / "clean.png")
    """)
    assert proc.returncode == 0, proc.stderr
    assert (tmp_path / "clean.png").exists()


def test_pillow_text_running_off_canvas_is_clipped(tmp_path):
    proc = _run_pillow_script(tmp_path, """
        img = Image.new("RGB", (500, 250), "white")
        draw = ImageDraw.Draw(img)
        draw.text((455, 100), "far beyond the edge", fill="black")
        img.save(OUT / "clipped.png")
    """)
    combined = proc.stderr + proc.stdout
    assert proc.returncode != 0
    assert "CLIPPED" in combined, combined
    assert not (tmp_path / "clipped.png").exists()


def test_pillow_text_on_text_is_overlap(tmp_path):
    proc = _run_pillow_script(tmp_path, """
        img = Image.new("RGB", (500, 250), "white")
        draw = ImageDraw.Draw(img)
        draw.text((60, 90), "OVERLAPPING TITLE", fill="black")
        draw.text((64, 90), "subtitle beneath", fill="#475569")
        img.save(OUT / "overlap.png")
    """)
    combined = proc.stderr + proc.stdout
    assert proc.returncode != 0
    assert "OVERLAP" in combined, combined
    assert not (tmp_path / "overlap.png").exists()


def test_pillow_text_bursting_out_of_card_is_overflow(tmp_path):
    """Still inside the image, but outside its rounded-rectangle card."""
    proc = _run_pillow_script(tmp_path, """
        img = Image.new("RGB", (700, 250), "white")
        draw = ImageDraw.Draw(img)
        draw.rounded_rectangle((20, 20, 230, 220), radius=16,
                               fill="#f8fafc", outline="#94a3b8", width=2)
        draw.text((45, 100), "this sentence is much too long for the card", fill="black")
        img.save(OUT / "overflow.png")
    """)
    combined = proc.stderr + proc.stdout
    assert proc.returncode != 0
    assert "OVERFLOW" in combined, combined
    assert "CLIPPED" not in combined, combined
    assert not (tmp_path / "overflow.png").exists()


def test_pillow_label_hugging_its_pill_is_not_overflow(tmp_path):
    """FP pin: pills/chips are deliberately sized to hug their label."""
    proc = _run_pillow_script(tmp_path, """
        img = Image.new("RGB", (500, 250), "white")
        draw = ImageDraw.Draw(img)
        box = draw.textbbox((0, 0), "PILL")
        w, h = box[2] - box[0], box[3] - box[1]
        draw.rounded_rectangle((30, 30, 30 + w, 30 + h), radius=6, fill="#dbeafe")
        draw.text((30, 30 - box[1]), "PILL", fill="#1d4ed8")
        img.save(OUT / "pill.png")
    """)
    assert proc.returncode == 0, proc.stderr
    assert (tmp_path / "pill.png").exists()


def test_pillow_collects_every_bad_panel_in_one_run(tmp_path):
    """Both rejected Pillow panels reach one repair prompt; the clean one still saves."""
    proc = _run_pillow_script(tmp_path, """
        for name, x in [("1_bad", 455), ("2_bad", 465), ("3_clean", 30)]:
            img = Image.new("RGB", (500, 250), "white")
            draw = ImageDraw.Draw(img)
            draw.text((x, 100), "a long Pillow line", fill="black")
            img.save(OUT / f"{name}.png")
    """)
    combined = proc.stderr + proc.stdout
    assert proc.returncode != 0
    assert "1_bad.png" in combined and "2_bad.png" in combined, combined
    assert (tmp_path / "3_clean.png").exists()


def test_pillow_audit_only_does_not_replace_clean_png(tmp_path):
    """Corpus calibration must inspect production renderers without touching PNGs."""
    proc = _run_pillow_script(tmp_path, """
        img = Image.new("RGB", (500, 250), "white")
        draw = ImageDraw.Draw(img)
        draw.text((30, 100), "clean audit panel", fill="black")
        img.save(OUT / "audit.png")
    """, audit_only=True)
    assert proc.returncode == 0, proc.stderr
    assert not (tmp_path / "audit.png").exists()


def test_matplotlib_audit_only_does_not_replace_clean_png(tmp_path):
    out = tmp_path / "matplotlib_audit.png"
    script = tmp_path / "render_matplotlib_audit.py"
    script.write_text(textwrap.dedent(f"""
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        fig = plt.figure(figsize=(10, 6), dpi=100)
        fig.text(0.1, 0.8, "Clean audit title", fontsize=20)
        fig.savefig(r"{out}")
    """), encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, str(GUARD), "--audit-only", str(script)],
        capture_output=True, text=True, timeout=120,
    )
    assert proc.returncode == 0, proc.stderr
    assert not out.exists()


def test_pillow_multiline_text_is_recorded_once(tmp_path):
    """Pillow delegates multiline_text to self.text; double-patching would self-overlap."""
    proc = _run_pillow_script(tmp_path, """
        img = Image.new("RGB", (500, 250), "white")
        draw = ImageDraw.Draw(img)
        draw.multiline_text((30, 60), "line one\\nline two", fill="black", spacing=8)
        img.save(OUT / "multiline.png")
    """)
    assert proc.returncode == 0, proc.stderr
    assert (tmp_path / "multiline.png").exists()


def test_pillow_textbbox_probe_is_not_phantom_text(tmp_path):
    proc = _run_pillow_script(tmp_path, """
        img = Image.new("RGB", (500, 250), "white")
        draw = ImageDraw.Draw(img)
        draw.textbbox((490, 20), "measurement only")
        img.save(OUT / "probe.png")
    """)
    assert proc.returncode == 0, proc.stderr


def test_pillow_font_size_kwarg_is_measured_at_actual_size(tmp_path):
    proc = _run_pillow_script(tmp_path, """
        img = Image.new("RGB", (500, 250), "white")
        draw = ImageDraw.Draw(img)
        draw.text((420, 80), "XX", fill="black", font_size=80)
        img.save(OUT / "font_size.png")
    """)
    combined = proc.stderr + proc.stdout
    assert proc.returncode != 0
    assert "CLIPPED" in combined, combined


def test_pillow_anchor_is_forwarded_to_textbbox(tmp_path):
    proc = _run_pillow_script(tmp_path, """
        img = Image.new("RGB", (500, 250), "white")
        draw = ImageDraw.Draw(img)
        draw.text((480, 60), "right aligned", anchor="ra", fill="black")
        img.save(OUT / "anchor.png")
    """)
    assert proc.returncode == 0, proc.stderr


def test_pillow_invisible_rectangle_is_not_a_phantom_card(tmp_path):
    proc = _run_pillow_script(tmp_path, """
        img = Image.new("RGB", (700, 250), "white")
        draw = ImageDraw.Draw(img)
        draw.rectangle((20, 20, 230, 220))
        draw.text((45, 100), "this line crosses the nonexistent card edge", fill="black")
        img.save(OUT / "invisible.png")
    """)
    assert proc.returncode == 0, proc.stderr


def test_pillow_nested_rectangle_coordinates_are_guarded(tmp_path):
    proc = _run_pillow_script(tmp_path, """
        img = Image.new("RGB", (700, 250), "white")
        draw = ImageDraw.Draw(img)
        draw.rectangle(((20, 20), (230, 220)), fill="#f8fafc", outline="#94a3b8")
        draw.text((45, 100), "this sentence is much too long for the card", fill="black")
        img.save(OUT / "nested.png")
    """)
    combined = proc.stderr + proc.stdout
    assert proc.returncode != 0
    assert "OVERFLOW" in combined, combined


def test_matplotlib_vertical_edge_message_keeps_bottom_orientation():
    fig = plt.figure(figsize=(10, 6), dpi=100)
    fig.text(0.1, -0.05, "below canvas", fontsize=20)
    violations = find_violations(fig)
    assert any("bottom by" in v for v in violations if v.startswith("CLIPPED")), violations


def test_collect_report_keeps_later_panel_visible_after_noisy_first(tmp_path):
    """MAX_REPORTED must not let panel 1 hide panel 2 from the repair prompt."""
    proc = _run_pillow_script(tmp_path, """
        first = Image.new("RGB", (500, 250), "white")
        draw = ImageDraw.Draw(first)
        for i in range(6):
            draw.text((60 + i, 90), f"stacked {i}", fill="black")
        first.save(OUT / "1_noisy.png")

        second = Image.new("RGB", (500, 250), "white")
        draw = ImageDraw.Draw(second)
        draw.text((470, 90), "clipped second panel", fill="black")
        second.save(OUT / "2_later.png")
    """)
    combined = proc.stderr + proc.stdout
    assert proc.returncode != 0
    assert "1_noisy.png" in combined and "2_later.png" in combined, combined
