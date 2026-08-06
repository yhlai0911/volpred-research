"""One glyph-aware CJK font resolver for every VolPred matplotlib chart."""
from __future__ import annotations

import warnings
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Iterable

# Ordered by production preference. Linux's fonts-noto-cjk package often
# registers a TTC as "Noto Sans CJK JP" even though it carries the common CJK
# glyphs needed by Traditional Chinese labels, so JP/KR faces remain valid
# portability fallbacks after the TC/SC faces.
CJK_FONT_CHAIN = [
    "PingFang TC",
    "PingFang HK",
    "Heiti TC",
    "STHeiti",
    "Songti TC",
    "Arial Unicode MS",
    "Noto Sans CJK TC",
    "Noto Sans CJK SC",
    "Noto Sans CJK JP",
    "Noto Sans CJK KR",
    "Microsoft JhengHei",
    "Hiragino Sans GB",
    "SimHei",
]

# Representative Traditional-Chinese glyphs. A family name alone is not proof:
# the incident this module fixes was precisely a named CJK family resolving to
# DejaVu Sans, which has no such glyphs.
CJK_GLYPH_PROBE = "股價風險測試"
_CJK_FAMILY_TOKENS = tuple(name.casefold() for name in CJK_FONT_CHAIN)


@dataclass(frozen=True)
class ResolvedCJKFont:
    family: str
    path: str


def _family_rank(family: str) -> int:
    normalized = family.casefold()
    for index, preferred in enumerate(_CJK_FAMILY_TOKENS):
        if normalized == preferred or preferred in normalized:
            return index
    return len(CJK_FONT_CHAIN)


def _font_has_glyphs(path: str | Path, glyphs: str = CJK_GLYPH_PROBE) -> bool:
    from matplotlib.ft2font import FT2Font

    try:
        charmap = FT2Font(str(path)).get_charmap()
    except (OSError, RuntimeError, ValueError):
        return False
    return all(ord(character) in charmap for character in glyphs)


def _refresh_system_fonts() -> None:
    """Register fonts missing from matplotlib's cache without patching mpl-data."""
    from matplotlib import font_manager as fm

    known = {str(Path(entry.fname).resolve()) for entry in fm.fontManager.ttflist}
    for path in fm.findSystemFonts(fontpaths=None, fontext="ttf"):
        resolved = str(Path(path).resolve())
        if resolved in known:
            continue
        try:
            fm.fontManager.addfont(path)
        except (OSError, RuntimeError, ValueError):
            continue
        known.add(resolved)


def _weight_penalty(weight: object) -> int:
    if isinstance(weight, (int, float)):
        return int(abs(float(weight) - 400.0))
    normalized = str(weight or "normal").casefold()
    return {
        "normal": 0,
        "regular": 0,
        "book": 50,
        "medium": 100,
        "semibold": 200,
        "demibold": 200,
        "bold": 300,
        "black": 500,
        "light": 100,
        "thin": 300,
    }.get(normalized, 400)


def _resolve_from_entries(entries: Iterable[object]) -> ResolvedCJKFont | None:
    ranked: list[tuple[int, int, int, str, str]] = []
    fallback: list[tuple[int, int, str, str]] = []
    seen_paths: set[str] = set()

    for entry in entries:
        family = str(getattr(entry, "name", "") or "")
        path = str(getattr(entry, "fname", "") or "")
        if not family or not path:
            continue
        normalized_path = str(Path(path).resolve())
        if normalized_path in seen_paths:
            continue
        seen_paths.add(normalized_path)
        rank = _family_rank(family)
        style_penalty = 0 if str(getattr(entry, "style", "normal")) == "normal" else 1
        weight_penalty = _weight_penalty(getattr(entry, "weight", "normal"))
        if rank < len(CJK_FONT_CHAIN):
            ranked.append(
                (rank, style_penalty, weight_penalty, family, normalized_path)
            )
        else:
            fallback.append(
                (style_penalty, weight_penalty, family, normalized_path)
            )

    for _, _, _, family, path in sorted(ranked):
        if _font_has_glyphs(path):
            return ResolvedCJKFont(family=family, path=path)

    # A platform may expose a CJK-capable face under an unexpected family name.
    # Glyph coverage is the authoritative contract, so allow it only after all
    # named CJK preferences have been exhausted.
    for _, _, family, path in sorted(fallback):
        if _font_has_glyphs(path):
            return ResolvedCJKFont(family=family, path=path)
    return None


@lru_cache(maxsize=1)
def _resolve_cached() -> ResolvedCJKFont | None:
    from matplotlib import font_manager as fm

    return _resolve_from_entries(fm.fontManager.ttflist)


def resolve_cjk_font(*, refresh: bool = False) -> ResolvedCJKFont | None:
    """Return a real font file whose charmap covers the CJK probe."""
    if refresh:
        _resolve_cached.cache_clear()
        _refresh_system_fonts()
    return _resolve_cached()


def apply_cjk_style(*, dpi: int | None = None, strict: bool = False) -> ResolvedCJKFont | None:
    """Apply a verified PingFang TC / Noto Sans CJK TC font to matplotlib.

    The function returns the resolved family and file path. It warns by default,
    or raises when ``strict=True``, if no installed font covers the representative
    Traditional-Chinese glyph probe.
    """
    import matplotlib.pyplot as plt
    from matplotlib import font_manager as fm

    resolved = resolve_cjk_font()
    if resolved is None:
        resolved = resolve_cjk_font(refresh=True)

    if resolved is None:
        message = (
            "apply_cjk_style: no installed font covers the CJK probe "
            f"{CJK_GLYPH_PROBE!r}; Chinese text will render incorrectly"
        )
        if strict:
            raise RuntimeError(message)
        warnings.warn(message, stacklevel=2)
        families = [*CJK_FONT_CHAIN, "DejaVu Sans", "sans-serif"]
    else:
        # Ensure a font discovered during cache refresh is visible to the global
        # manager used by subsequent findfont/draw calls.
        try:
            fm.fontManager.addfont(resolved.path)
        except (OSError, RuntimeError, ValueError):
            pass
        families = [
            resolved.family,
            *(family for family in CJK_FONT_CHAIN if family != resolved.family),
            "DejaVu Sans",
            "sans-serif",
        ]

    plt.rcParams["font.family"] = "sans-serif"
    plt.rcParams["font.sans-serif"] = families
    plt.rcParams["axes.unicode_minus"] = False
    if dpi is not None:
        plt.rcParams["savefig.dpi"] = dpi
    return resolved
