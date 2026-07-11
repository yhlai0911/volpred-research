#!/usr/bin/env python3
"""Fail a lazypack render when the LAYOUT is broken — not just when the PNG is missing.

Why (2026-07-11, boss email-12062/12066):
  gen_lazypack_codex.py's repair loop only ever saw two failure signals: the render
  script raised, or an expected PNG was absent. A script that cheerfully saved a
  figure whose text ran off the canvas and overlapped itself counted as SUCCESS —
  so mile_531e4c87 shipped three garbled panels to readers and no round of the
  repair loop could see it. The success criterion was blind to the only thing a
  reader actually looks at.

How:
  We patch Figure.savefig. Before the PNG is written we draw the figure, walk every
  visible Text artist, and raise on three defects the eye catches instantly:
    - clipped:  the text box runs outside the canvas (right/bottom edge cut off)
    - overlap:  two text boxes collide (title over subtitle, body over watermark)
    - overflow: the text runs out of the CARD it lives in, while still on canvas
                (the boss's first-named defect: 「文字溢出容器」)
  The RuntimeError propagates out of the render script → rc != 0 → the EXISTING
  repair round feeds the traceback back to codex, which now gets an actionable
  layout complaint instead of silence. No new mechanism; the gate just gives the
  loop that was already there something true to fail on.

Usage (how gen_lazypack_codex.py runs a render script):
  python scripts/lazypack_layout_guard.py <render_script.py>
"""
from __future__ import annotations

import runpy
import sys
from pathlib import Path

# Text boxes closer than this to the canvas edge are not treated as clipped —
# antialiased glyph extents routinely stick out a hair past their own box.
EDGE_TOL_PX = 2.0

# Two text boxes count as colliding only when the shared area is a real chunk of
# the smaller one. Descenders and kerning make tiny brushes unavoidable.
# Calibrated on mile_531e4c87's panels: a small caption sitting on top of a big
# numeral — plainly broken to the eye — measured 15%, so 0.20 let it through. At
# 0.10 that defect is caught and nothing else in three clean panels trips (probed
# by dropping the threshold to 0.01: exactly one collision, the real one).
OVERLAP_MIN_FRACTION = 0.10

# --- OVERFLOW (text runs out of its card, while still on canvas) ------------------
#
# The lazypack house style is card-based: a Rectangle / FancyBboxPatch is drawn as a
# card and the copy is placed inside it. When a line is too long it bursts out of the
# card and sits on the neighbouring card — plainly broken to the eye, yet CLIPPED and
# OVERLAP both miss it (it is inside the canvas, and it may hit no other text).
#
# Container = the SMALLEST patch whose bbox contains the text's CENTRE point.
# Centre-point (not full-bbox) containment is what makes this survive the obvious
# false-positive traps: an `ax.set_title()` / axis label / colorbar label naturally
# sits OUTSIDE the axes patch, so its centre is in no patch at all and it is simply
# not an overflow question — CLIPPED already owns "did it leave the canvas".
# Text with no container is skipped, never flagged.
#
# Horizontal slack. Glyph side bearings are small, so a text that pokes sideways out of
# its card is real. 6px at the house 1600x1000 canvas is under half a CJK glyph.
OVERFLOW_TOL_PX = 6.0

# Vertical slack is NOT a constant, and this is the one subtlety in the whole check.
# Text.get_window_extent() returns the LINE BOX (full font ascent→descent), not the ink.
# For a single large glyph the whitespace above the ink is a big share of that box, so a
# glyph perfectly centred in a badge still measures as "sticking out the top". Measured
# on the corpus (mile_0f7d1501/1_question.png, a 40pt「?」centred in an ellipse that the
# eye reads as flawless): the line box overhangs the badge by 10.5px on a 79px box —
# 0.13 of the box height, pure font whitespace. Every genuine overflow in the same corpus
# ran 0.35–0.46 of its box height (mile_4fe0a026/2_method 7.1px on 20px = 0.35;
# mile_3a7bd6f6/2_results 10px on 24px = 0.42; mile_3a7bd6f6/3_boundary 13px on 28px =
# 0.46 — all three visually confirmed as text struck through by the card's own border).
# So: allow the text to overhang vertically by up to this fraction of its own line box.
# 0.22 sits clear of the 0.13 artefact and clear below the 0.35 floor of real defects.
INK_WHITESPACE_FRAC = 0.22

# A patch is only treated as a CARD if it is meaningfully bigger than the text sitting
# on it. Pills / chips / bar segments are *sized to hug their label* — a FancyBboxPatch
# with 8px padding legitimately has the glyph box poking through its rounded corner,
# and a value label centred on a bar is routinely wider than the bar. Those are design,
# not defects. Measured on the accepted corpus (see references in the calibration note
# below), every legitimate hug came in under 2.0x; real cards run 6x-400x the text area.
CONTAINER_MIN_AREA_RATIO = 2.0

# Degenerate patches (spines are Patch subclasses and measure 0px on one side, hairline
# rules likewise) are not containers.
CONTAINER_MIN_SIDE_PX = 12.0

# A patch that covers essentially the whole canvas is a background, not a card. Flagging
# against it would just re-derive CLIPPED with a different tolerance.
CONTAINER_MAX_CANVAS_FRACTION = 0.98

MAX_REPORTED = 12


def _bbox_area(b) -> float:
    return max(0.0, b.x1 - b.x0) * max(0.0, b.y1 - b.y0)


def _intersection_area(a, b) -> float:
    dx = min(a.x1, b.x1) - max(a.x0, b.x0)
    dy = min(a.y1, b.y1) - max(a.y0, b.y0)
    if dx <= 0 or dy <= 0:
        return 0.0
    return dx * dy


def _snippet(t: str, n: int = 34) -> str:
    t = " ".join(t.split())
    return t if len(t) <= n else t[:n] + "…"


def _container_boxes(fig, renderer) -> list:
    """Card-like patches, display coords. See the OVERFLOW notes above for the filters."""
    from matplotlib.patches import Patch

    canvas_area = fig.bbox.width * fig.bbox.height
    boxes = []
    for patch in fig.findobj(Patch):
        if not patch.get_visible():
            continue
        if patch is fig.patch:
            continue
        try:
            bb = patch.get_window_extent(renderer=renderer)
        except Exception as e:  # noqa: BLE001
            print(f"[layout_guard] unmeasurable patch skipped: "
                  f"{type(patch).__name__} ({type(e).__name__}: {e})", file=sys.stderr)
            continue
        w, h = bb.x1 - bb.x0, bb.y1 - bb.y0
        if w < CONTAINER_MIN_SIDE_PX or h < CONTAINER_MIN_SIDE_PX:
            continue  # spine / hairline rule / sliver — not a card
        if canvas_area > 0 and _bbox_area(bb) / canvas_area >= CONTAINER_MAX_CANVAS_FRACTION:
            continue  # full-bleed background — CLIPPED already owns the canvas edge
        boxes.append(bb)
    return boxes


def _container_for(text_bb, boxes):
    """Smallest card whose bbox holds the text's centre and is big enough to be a card."""
    cx = 0.5 * (text_bb.x0 + text_bb.x1)
    cy = 0.5 * (text_bb.y0 + text_bb.y1)
    t_area = _bbox_area(text_bb)
    best = None
    best_area = float("inf")
    for bb in boxes:
        if not (bb.x0 <= cx <= bb.x1 and bb.y0 <= cy <= bb.y1):
            continue
        area = _bbox_area(bb)
        if t_area > 0 and area < CONTAINER_MIN_AREA_RATIO * t_area:
            continue  # pill / chip / bar segment hugging its own label — by design
        if area < best_area:
            best, best_area = bb, area
    return best


def find_violations(fig) -> list[str]:
    """Canvas clipping, text-on-text collisions, and text bursting out of its card."""
    from matplotlib.text import Text

    fig.canvas.draw()  # extents are only real once the figure has been laid out
    renderer = fig.canvas.get_renderer()
    fw, fh = fig.bbox.width, fig.bbox.height

    boxed: list[tuple[Text, object]] = []
    for artist in fig.findobj(Text):
        if not artist.get_visible():
            continue
        if not (artist.get_text() or "").strip():
            continue
        try:
            bb = artist.get_window_extent(renderer=renderer)
        except Exception as e:  # noqa: BLE001
            # Not evidence of a defect either way — but a text we could not measure
            # is a hole in the gate's coverage, so say so rather than skip quietly.
            print(f"[layout_guard] unmeasurable text skipped: "
                  f"{_snippet(artist.get_text())!r} ({type(e).__name__}: {e})",
                  file=sys.stderr)
            continue
        if _bbox_area(bb) <= 0:
            continue
        boxed.append((artist, bb))

    violations: list[str] = []

    for artist, bb in boxed:
        over = []
        if bb.x0 < -EDGE_TOL_PX:
            over.append(f"left by {-bb.x0:.0f}px")
        if bb.y0 < -EDGE_TOL_PX:
            over.append(f"bottom by {-bb.y0:.0f}px")
        if bb.x1 > fw + EDGE_TOL_PX:
            over.append(f"right by {bb.x1 - fw:.0f}px")
        if bb.y1 > fh + EDGE_TOL_PX:
            over.append(f"top by {bb.y1 - fh:.0f}px")
        if over:
            violations.append(
                f"CLIPPED: 「{_snippet(artist.get_text())}」 runs off the canvas "
                f"({', '.join(over)}). Shorten it, shrink the font, or widen its box."
            )

    containers = _container_boxes(fig, renderer)
    for artist, bb in boxed:
        card = _container_for(bb, containers)
        if card is None:
            continue  # nothing encloses it (axes title, tick label, footer) — not overflow
        # Vertical slack absorbs the font's own ascent/descent whitespace (see notes above).
        v_tol = max(OVERFLOW_TOL_PX, INK_WHITESPACE_FRAC * (bb.y1 - bb.y0))
        out = []
        if bb.x0 < card.x0 - OVERFLOW_TOL_PX:
            out.append(f"left by {card.x0 - bb.x0:.0f}px")
        if bb.y0 < card.y0 - v_tol:
            out.append(f"bottom by {card.y0 - bb.y0:.0f}px")
        if bb.x1 > card.x1 + OVERFLOW_TOL_PX:
            out.append(f"right by {bb.x1 - card.x1:.0f}px")
        if bb.y1 > card.y1 + v_tol:
            out.append(f"top by {bb.y1 - card.y1:.0f}px")
        if out:
            violations.append(
                f"OVERFLOW: 「{_snippet(artist.get_text())}」 bursts out of its card "
                f"({', '.join(out)}; card is "
                f"{card.x1 - card.x0:.0f}x{card.y1 - card.y0:.0f}px). "
                f"Wrap the line, shrink the font, or enlarge the card."
            )

    for i in range(len(boxed)):
        for j in range(i + 1, len(boxed)):
            a_art, a_bb = boxed[i]
            b_art, b_bb = boxed[j]
            inter = _intersection_area(a_bb, b_bb)
            if inter <= 0:
                continue
            smaller = min(_bbox_area(a_bb), _bbox_area(b_bb))
            if smaller <= 0:
                continue
            frac = inter / smaller
            if frac >= OVERLAP_MIN_FRACTION:
                violations.append(
                    f"OVERLAP: 「{_snippet(a_art.get_text())}」 collides with "
                    f"「{_snippet(b_art.get_text())}」 ({frac:.0%} of the smaller box). "
                    f"Move one, or give each its own row."
                )

    return violations


def _report(violations: list[str], header: str) -> str:
    shown = violations[:MAX_REPORTED]
    extra = len(violations) - len(shown)
    lines = "\n".join(f"  - {v}" for v in shown)
    if extra > 0:
        lines += f"\n  - …and {extra} more."
    return (
        f"LAYOUT CHECK FAILED — {header}:\n{lines}\n"
        "Fix the layout in the render script. Every text must (a) sit inside the canvas, "
        "(b) not overlap another text, and (c) stay inside the card/box it is drawn on — "
        "wrap long lines, drop the font size, or make the card bigger. Then save again."
    )


# Populated in collect mode: [(png_path, [violation, ...]), ...]
COLLECTED: list[tuple[str, list[str]]] = []


def install(collect: bool = False) -> None:
    """Patch Figure.savefig so a broken layout cannot reach disk.

    collect=False: raise on the first bad panel (library / test use).
    collect=True:  record it, skip the write, and let the script carry on to the
      remaining panels. Render scripts save panels one after another, so raising
      on panel 2 means panel 3 is never even drawn — a repair round would then see
      one complaint at a time and three panels could never converge inside the
      round budget. Collecting hands codex every defect in a single round.
    """
    from matplotlib.figure import Figure

    if getattr(Figure.savefig, "_lazypack_guarded", False):
        return

    original = Figure.savefig

    def guarded(self, *args, **kwargs):
        violations = find_violations(self)
        if violations:
            target = str(args[0]) if args else str(kwargs.get("fname", "<figure>"))
            if collect:
                COLLECTED.append((target, violations))
                print(f"[layout_guard] REJECTED {target}", file=sys.stderr)
                return None
            raise RuntimeError(_report(violations, "the panel would ship unreadable"))
        return original(self, *args, **kwargs)

    guarded._lazypack_guarded = True  # type: ignore[attr-defined]
    Figure.savefig = guarded  # type: ignore[assignment]


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print("usage: lazypack_layout_guard.py <render_script.py>", file=sys.stderr)
        return 2
    script = Path(argv[1]).resolve()
    install(collect=True)
    sys.argv = [str(script), *argv[2:]]
    runpy.run_path(str(script), run_name="__main__")

    if COLLECTED:
        flat: list[str] = []
        for target, violations in COLLECTED:
            name = Path(target).name
            flat.extend(f"[{name}] {v}" for v in violations)
        print(_report(flat, f"{len(COLLECTED)} panel(s) would ship unreadable"),
              file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
