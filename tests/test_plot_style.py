from __future__ import annotations

import warnings

import matplotlib

import scripts.plot_style as plot_style
from volpred.charts import font_style


def test_apply_cjk_style_warns_when_font_resolution_check_fails(monkeypatch):
    matplotlib.use("Agg", force=True)

    def fail_resolver(*args, **kwargs):
        raise RuntimeError("font cache broken")

    monkeypatch.setattr(font_style, "resolve_cjk_font", fail_resolver)

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        plot_style.apply_cjk_style()

    messages = [str(item.message) for item in caught]
    assert any("CJK font resolution check failed" in msg for msg in messages)
    assert any("font cache broken" in msg for msg in messages)


def test_apply_cjk_style_strict_mode_raises_on_resolution_failure(monkeypatch):
    matplotlib.use("Agg", force=True)

    def fail_resolver(*args, **kwargs):
        raise RuntimeError("font cache broken")

    monkeypatch.setattr(font_style, "resolve_cjk_font", fail_resolver)

    import pytest

    with pytest.raises(RuntimeError, match="CJK font resolution check failed"):
        plot_style.apply_cjk_style(strict=True)
