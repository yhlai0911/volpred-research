"""Gate: chart uploads must be namespaced per article.

Why (2026-07-10): `upload_chart` built its Supabase object key from the bare
filename and uploaded with `x-upsert: true`. Lazypack posters use standardised
names (`lazy1_concept.png`, `lazy2_data.png`, `lazy3_takeaway.png`), so
publishing any second lazypack article would have silently overwritten the
first article's live images. Caught while publishing `credit_silence_20260710`,
which would have clobbered `mile_e71ea353` (2026-07-09 semiconductor piece).

The key is derived from the asset folder, which is `storage/reports/assets/<slug>/`.
"""
from __future__ import annotations

import pytest

from volpred.charts.article_charts import _object_key


def test_asset_folder_becomes_namespace():
    key = _object_key("storage/reports/assets/credit_silence_20260710/lazy1_concept.png")
    assert key == "credit_silence_20260710/lazy1_concept.png"


def test_two_articles_sharing_a_filename_do_not_collide():
    """The actual defect: identical basenames, different articles."""
    a = _object_key("storage/reports/assets/trending_semis_vol_20260709/lazy1_concept.png")
    b = _object_key("storage/reports/assets/credit_silence_20260710/lazy1_concept.png")
    assert a != b, "lazypack posters from different articles must not share an object key"


@pytest.mark.parametrize(
    "path",
    [
        "storage/reports/assets/fig.png",
        "/tmp/fig.png",
        "charts/fig.png",
        "images/fig.png",
    ],
)
def test_generic_parents_keep_bare_filename(path):
    """Backwards compatibility: URLs published before the fix must still resolve."""
    assert _object_key(path) == "fig.png"


def test_absolute_paths_use_the_asset_folder_too():
    key = _object_key("/Users/x/repo/storage/reports/assets/k1234/panel.png")
    assert key == "k1234/panel.png"
