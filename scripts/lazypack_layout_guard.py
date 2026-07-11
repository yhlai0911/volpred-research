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
  visible Text artist, and raise on two defects the eye catches instantly:
    - clipped: the text box runs outside the canvas (right/bottom edge cut off)
    - overlap: two text boxes collide (title over subtitle, body over watermark)
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
OVERLAP_MIN_FRACTION = 0.20

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


def find_violations(fig) -> list[str]:
    """Clipped-at-canvas-edge and text-on-text collisions, in reading order."""
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


def install() -> None:
    """Patch Figure.savefig so a broken layout raises instead of shipping."""
    from matplotlib.figure import Figure

    if getattr(Figure.savefig, "_lazypack_guarded", False):
        return

    original = Figure.savefig

    def guarded(self, *args, **kwargs):
        violations = find_violations(self)
        if violations:
            shown = violations[:MAX_REPORTED]
            extra = len(violations) - len(shown)
            lines = "\n".join(f"  - {v}" for v in shown)
            if extra > 0:
                lines += f"\n  - …and {extra} more."
            raise RuntimeError(
                "LAYOUT CHECK FAILED — the panel would ship unreadable:\n"
                f"{lines}\n"
                "Fix the layout in the render script (text must sit inside the "
                "canvas and must not overlap other text), then save again."
            )
        return original(self, *args, **kwargs)

    guarded._lazypack_guarded = True  # type: ignore[attr-defined]
    Figure.savefig = guarded  # type: ignore[assignment]


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print("usage: lazypack_layout_guard.py <render_script.py>", file=sys.stderr)
        return 2
    script = Path(argv[1]).resolve()
    install()
    sys.argv = [str(script), *argv[2:]]
    runpy.run_path(str(script), run_name="__main__")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
