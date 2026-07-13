"""Regression: a registered series must not deadlock the release pool.

Incident 2026-07-13 (boss Telegram msg 662-664): 「無人載具｜EP0..EP-Final」是一個
刻意連載的專題。EP0 發出去之後，release pool 的 narrative-cluster 閘門把每一集當
成獨立文章計數 —— 同 cluster 在最近 3 篇裡出現 2 次就整組封鎖，於是 EP1~EP-Final
五篇永遠出不去，池子「有貨但可發 = 0」，靜默零產出 6.5 小時後才由下游「發文空窗」
WARN 間接冒出來。

領域模型的修正：**一個註冊系列 = 一個敘事單位**（config/article_series.json 是 SoT）。
- 計壓時：同系列的多集只算一次
- 選候選時：註冊系列的分集豁免 cluster 閘門（同一集重發仍由 arc-dedup 擋）
"""

from collections import Counter

from volpred.ops.content import (
    _article_series,
    _recent_narrative_cluster_pressure,
)


def _drone_episode(ep: str, published_at: str, status: str = "published") -> dict:
    return {
        "id": f"mile_drone_{ep.lower()}",
        "title": f"🛩️ 無人載具｜{ep}：台廠無人機供應鏈的一段",
        "tags": ["台股", "無人機"],
        "status": status,
        "audience": "general",
        "published_at": published_at,
    }


def test_series_membership_read_from_registry():
    assert _article_series(_drone_episode("EP1", "2026-07-13T02:00:00+00:00"))
    assert _article_series({"title": "爆量之後會漲還會跌？九檔資產只留下鴻海一個例外"}) is None


def test_series_episodes_count_once_toward_cluster_pressure():
    """三集連載擠滿 last-3 視窗時，cluster 壓力仍是 1，不會把後續集數鎖死。"""
    feed = [
        _drone_episode("EP0", "2026-07-13T02:00:00+00:00"),
        _drone_episode("EP1", "2026-07-13T03:00:00+00:00"),
        _drone_episode("EP2", "2026-07-13T04:00:00+00:00"),
    ]
    pressure = _recent_narrative_cluster_pressure(feed, k_cluster={})
    counts = Counter(pressure["counts"])
    assert all(c < pressure["threshold"] for c in counts.values()), (
        f"series must collapse to one narrative unit, got {dict(counts)}"
    )
    assert not pressure["blocked_clusters"], (
        "a serialized 專題 must never block itself out of the release pool"
    )


def test_non_series_flood_still_blocks():
    """豁免只給註冊系列 —— 一般文章洗版同一 cluster 仍要被擋住。"""
    feed = [
        {
            "id": f"mile_tw_{i}",
            "title": f"台股波動率的第 {i} 個觀察",
            "tags": ["台股"],
            "status": "published",
            "audience": "general",
            "published_at": f"2026-07-13T0{i}:00:00+00:00",
        }
        for i in (1, 2, 3)
    ]
    pressure = _recent_narrative_cluster_pressure(feed, k_cluster={})
    assert pressure["blocked_clusters"], "non-series flood must still trip the gate"
