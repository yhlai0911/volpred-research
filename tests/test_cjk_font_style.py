from __future__ import annotations

import os
from types import SimpleNamespace

import matplotlib.pyplot as plt
import pytest

from volpred.charts import font_style


def test_resolver_prefers_regular_weight_within_preferred_family(monkeypatch):
    entries = [
        SimpleNamespace(
            name="Noto Sans CJK JP",
            fname="/fonts/NotoSansCJK-Bold.ttc",
            style="normal",
            weight=700,
        ),
        SimpleNamespace(
            name="Noto Sans CJK JP",
            fname="/fonts/NotoSansCJK-Regular.ttc",
            style="normal",
            weight=400,
        ),
    ]
    monkeypatch.setattr(font_style, "_font_has_glyphs", lambda path, glyphs=font_style.CJK_GLYPH_PROBE: True)

    resolved = font_style._resolve_from_entries(entries)

    assert resolved is not None
    assert resolved.family == "Noto Sans CJK JP"
    assert resolved.path.endswith("NotoSansCJK-Regular.ttc")


def test_resolver_requires_actual_glyph_coverage(monkeypatch):
    entries = [
        SimpleNamespace(
            name="PingFang TC",
            fname="/fonts/fake-pingfang.ttf",
            style="normal",
            weight=400,
        ),
        SimpleNamespace(
            name="Noto Sans CJK TC",
            fname="/fonts/real-noto.ttc",
            style="normal",
            weight=400,
        ),
    ]
    monkeypatch.setattr(
        font_style,
        "_font_has_glyphs",
        lambda path, glyphs=font_style.CJK_GLYPH_PROBE: str(path).endswith("real-noto.ttc"),
    )

    resolved = font_style._resolve_from_entries(entries)

    assert resolved is not None
    assert resolved.family == "Noto Sans CJK TC"


def test_apply_cjk_style_sets_the_verified_family(monkeypatch):
    resolved = font_style.ResolvedCJKFont(
        family="Noto Sans CJK TC",
        path="/fonts/NotoSansCJK-Regular.ttc",
    )
    monkeypatch.setattr(font_style, "resolve_cjk_font", lambda refresh=False: resolved)
    monkeypatch.setattr(font_style, "_refresh_system_fonts", lambda: None)

    from matplotlib import font_manager as fm

    monkeypatch.setattr(fm.fontManager, "addfont", lambda path: None)
    result = font_style.apply_cjk_style(dpi=144, strict=True)

    assert result == resolved
    assert plt.rcParams["font.family"] == ["sans-serif"]
    assert plt.rcParams["font.sans-serif"][0] == "Noto Sans CJK TC"
    assert plt.rcParams["axes.unicode_minus"] is False
    assert plt.rcParams["savefig.dpi"] == 144


def test_ci_has_a_font_covering_the_traditional_chinese_probe():
    resolved = font_style.resolve_cjk_font(refresh=True)
    if resolved is None and not os.environ.get("CI"):
        pytest.skip("No CJK font is installed in this local environment")

    assert resolved is not None
    assert font_style._font_has_glyphs(resolved.path)
