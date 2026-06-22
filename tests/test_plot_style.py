from __future__ import annotations

import warnings

import matplotlib
from matplotlib import font_manager as fm

from scripts.plot_style import apply_cjk_style


def test_apply_cjk_style_warns_when_font_resolution_check_fails(monkeypatch):
    matplotlib.use("Agg", force=True)

    def fail_findfont(*args, **kwargs):
        raise RuntimeError("font cache broken")

    monkeypatch.setattr(fm, "findfont", fail_findfont)

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        apply_cjk_style()

    messages = [str(item.message) for item in caught]
    assert any("CJK font resolution check failed" in msg for msg in messages)
    assert any("font cache broken" in msg for msg in messages)
