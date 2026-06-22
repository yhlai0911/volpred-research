"""Shared matplotlib style helper — durable CJK (中文) font fix.

2026-06-11 incident (k202 / mile_872abdc3): article figures rendered all
Chinese text as tofu boxes (□) because matplotlib fell back to DejaVu Sans
(no CJK glyphs). Root cause analysis showed the project relied on a *patched*
`.venv/.../mpl-data/matplotlibrc` (font.sans-serif prepended with PingFang HK)
— which is fragile:
  - any `uv sync` / matplotlib reinstall silently wipes the patch
  - worktree agents with fresh venvs never get the patch
  - scripts run with system anaconda python bypass it entirely

Durable path: every figure-producing script calls `apply_cjk_style()` at the
top, so the font chain is explicit in code regardless of environment.

Usage:
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[N] / "scripts"))
    from plot_style import apply_cjk_style
    apply_cjk_style()

or simply (when run from repo root):
    from scripts.plot_style import apply_cjk_style
"""
from __future__ import annotations

# macOS CJK font chain — verified present on this machine (PingFang first).
# Noto Sans CJK included for portability to Linux CI / containers.
CJK_FONT_CHAIN = [
    "PingFang TC",
    "PingFang HK",
    "Heiti TC",
    "Arial Unicode MS",
    "STHeiti",
    "Noto Sans CJK TC",
    "Noto Sans CJK SC",
    "DejaVu Sans",
    "sans-serif",
]


def apply_cjk_style(*, dpi: int | None = None) -> None:
    """Set matplotlib rcParams so Traditional Chinese renders correctly.

    - font.sans-serif → CJK-capable chain (PingFang TC first)
    - axes.unicode_minus → False (CJK fonts lack U+2212 minus glyph)
    - optional dpi for savefig
    """
    import matplotlib
    import matplotlib.pyplot as plt

    plt.rcParams["font.sans-serif"] = list(CJK_FONT_CHAIN)
    plt.rcParams["font.family"] = "sans-serif"
    plt.rcParams["axes.unicode_minus"] = False
    if dpi is not None:
        plt.rcParams["savefig.dpi"] = dpi

    # Loud warning (not silent fallback) if no CJK font actually resolves —
    # better a console warning than tofu on a live article.
    try:
        from matplotlib import font_manager as fm

        resolved = fm.findfont(fm.FontProperties(family=CJK_FONT_CHAIN))
        if not any(
            key in resolved
            for key in ("PingFang", "Heiti", "STHeiti", "Arial Unicode", "NotoSansCJK", "Noto Sans CJK")
        ):
            import warnings

            warnings.warn(
                f"apply_cjk_style: no CJK font resolved (got {resolved}) — "
                "Chinese text WILL render as tofu boxes. Install PingFang/Noto CJK.",
                stacklevel=2,
            )
    except Exception as exc:
        import warnings

        warnings.warn(
            "apply_cjk_style: CJK font resolution check failed "
            f"({type(exc).__name__}: {exc}); Chinese text may render incorrectly.",
            stacklevel=2,
        )


if __name__ == "__main__":
    apply_cjk_style()
    import matplotlib

    print("font.sans-serif =", matplotlib.rcParams["font.sans-serif"][:4])
    print("axes.unicode_minus =", matplotlib.rcParams["axes.unicode_minus"])
