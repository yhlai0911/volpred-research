"""Backward-compatible entry point for VolPred's canonical CJK chart style.

The implementation lives in ``volpred.charts.font_style`` so article charts,
experiment scripts, and CI all resolve the same glyph-verified font file.  The
local forwarding functions are intentional: the repository's static test-import
auditor requires public symbols imported from this module to be defined here,
not merely rebound through an import statement.
"""
from __future__ import annotations

import sys
from pathlib import Path

try:
    from volpred.charts import font_style as _font_style
except ModuleNotFoundError:
    # Direct ``python scripts/plot_style.py`` execution does not automatically
    # put the src-layout package on sys.path. Import the same canonical module;
    # never maintain a second resolver here.
    repo_src = Path(__file__).resolve().parents[1] / "src"
    sys.path.insert(0, str(repo_src))
    from volpred.charts import font_style as _font_style


CJK_FONT_CHAIN = _font_style.CJK_FONT_CHAIN
ResolvedCJKFont = _font_style.ResolvedCJKFont


def resolve_cjk_font(*, refresh: bool = False) -> ResolvedCJKFont | None:
    """Forward to the single canonical glyph-aware font resolver."""
    return _font_style.resolve_cjk_font(refresh=refresh)


def apply_cjk_style(
    *,
    dpi: int | None = None,
    strict: bool = False,
) -> ResolvedCJKFont | None:
    """Forward to the canonical style implementation without duplicating it."""
    return _font_style.apply_cjk_style(dpi=dpi, strict=strict)


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
