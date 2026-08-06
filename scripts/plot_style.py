"""Backward-compatible entry point for VolPred's canonical CJK chart style.

The implementation lives in ``volpred.charts.font_style`` so article charts,
experiment scripts, and CI all resolve the same glyph-verified font file.
"""
from __future__ import annotations

import sys
from pathlib import Path

try:
    from volpred.charts.font_style import (
        CJK_FONT_CHAIN,
        ResolvedCJKFont,
        apply_cjk_style,
        resolve_cjk_font,
    )
except ModuleNotFoundError:
    # Direct ``python scripts/plot_style.py`` execution does not automatically
    # put the src-layout package on sys.path. Import the same canonical module;
    # never maintain a second resolver here.
    repo_src = Path(__file__).resolve().parents[1] / "src"
    sys.path.insert(0, str(repo_src))
    from volpred.charts.font_style import (
        CJK_FONT_CHAIN,
        ResolvedCJKFont,
        apply_cjk_style,
        resolve_cjk_font,
    )

__all__ = [
    "CJK_FONT_CHAIN",
    "ResolvedCJKFont",
    "apply_cjk_style",
    "resolve_cjk_font",
]


if __name__ == "__main__":
    resolved = apply_cjk_style(strict=True)
    import matplotlib

    print("resolved_cjk_font =", resolved)
    print("font.sans-serif =", matplotlib.rcParams["font.sans-serif"][:4])
    print("axes.unicode_minus =", matplotlib.rcParams["axes.unicode_minus"])
