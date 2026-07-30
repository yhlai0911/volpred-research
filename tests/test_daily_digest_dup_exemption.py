"""Dedup policy（2026-06-23 boss directive「沒發文比重複發文嚴重」）+ daily_digest 豁免。

預設從「default block, 逐類豁免」反轉成「default publish, 只讓 canonical exact
identity 擁有 hard block」。三條契約：

1. 同 experiment_ref + 同 audience + 內文**近乎逐字相同**（K1054 ghost 那種）→ 警告後發佈；
   Jaccard 相似度不是 canonical identity。
2. 同 experiment_ref 但**不同角度/不同寫法**（body_sim < _RECYCLE_SIM）→ 現在照常發佈，
   不再被靜默吞掉（這是 boss directive 的核心）。
3. content_type='daily_digest' → 即使內文與被策展來源近乎相同也照常發佈（curation 本就
   會大量重疊）。

每日精選導讀是 meta-curation，本來就會引用同主題的多篇舊文，必然與被策展文章共享
experiment_refs / 標題主題 / narrative arc / entities。2026-06-23 第一篇正確格式的
MOVE-VIX 專題導讀被它自己 curate 的來源文章（mile_671d4c75）判為 narrative-arc dup
而擋下。narrative-arc / 純標題相似 gate 已降級為 warn-only（見 publisher.py），digest
另有 content_type 豁免做雙重保險。
"""
from __future__ import annotations

import json
import sys
import types
from datetime import datetime, timezone
from pathlib import Path

import pytest

from volpred.publisher.publisher import Publisher

# Deterministic dup trigger: seed and the new article share experiment_ref
# 'K9999' (+ same general audience).
_SHARED_REF = "K9999"
_SEED_ID = "mile_seeddup1"
_SEED_TITLE = "債市和股市同時在怕，但怕的不是同一件事"
_SEED_DESC = (
    "MOVE 是債市的恐慌指數，VIX 是股市的恐慌指數。兩者 60 日滾動相關係數爬到 0.50，"
    "近 90 日平均 0.60，逼近 2022 升息循環水準，顯示 FOMC 與 CPI 訊息下債市股市同步共振。"
    "但 MOVE/VIX 絕對水位比值 3.99 仍落在歷史 P38，動作同步、水位分歧。"
)

# (A) HIGH-SIMILARITY REUSE: byte-for-byte body, title only slightly reworded
# (the K1054 ghost pattern). body_sim ≈ 0.95 → warn-only and publish.
_RECYCLE_TITLE = "債市和股市同時在怕，但怕的不是同一件事（更新版）"
_RECYCLE_DESC = _SEED_DESC

# (B) SAME-K DIFFERENT ANGLE: shares the topic + experiment_ref but is a
# genuinely different writeup. body_sim ≈ 0.19 < _RECYCLE_SIM → must publish
# (boss directive: a missed publish is worse than a duplicate).
_DIFF_TITLE = "MOVE 與 VIX 的跨資產波動率分裂：債市恐懼 vs 股市平靜"
# 2026-07-02 depth floor requires general articles ≥1500 chars + ≥1 table. This
# fixture is a genuinely different-angle writeup of the same topic (low body_sim
# vs the seed), padded to a realistic length so the depth gate is satisfied and
# the DUP logic under test is what's exercised.
_DIFF_DESC = (
    "把過去一個月談 MOVE 與 VIX 的研究串起來，會看到一條反覆出現的裂縫：債券市場先怕、"
    "股票市場後知後覺。MOVE 是債市選擇權隱含波動率指數，反映交易員對利率大幅波動下注的成本；"
    "VIX 則是股市的恐慌溫度計。兩者理論上都吃同一批總體訊息——FOMC 的措辭、CPI 的意外、"
    "就業數據的偏離——照理應該同漲同跌。但過去這段期間，它們的絕對水位卻走出明顯分歧。\n\n"
    "先看動作面。MOVE 與 VIX 的 60 日滾動相關係數爬到 0.50，近 90 日平均更到 0.60，"
    "逼近 2022 那輪升息循環的同步水準。也就是說，當債市因為某個利率訊息抖一下，股市的恐慌"
    "指數大概率也會同向抽動一下——這是『同步共振』。這種共振通常出現在市場把注意力全押在"
    "同一個總體變數（例如降不降息）的時候，任何一則新聞都會被兩個市場同時定價。\n\n"
    "但水位面說的是另一回事。把 MOVE 除以 VIX 得到的相對比值目前落在 3.99，只排在歷史"
    "第 38 百分位，屬於偏低的一端。翻成白話：債市的恐慌『絕對強度』相對股市其實不算高，"
    "甚至比多數時候更溫和。動作同步、水位分歧，這個組合本身就是這段行情最值得記住的特徵——"
    "兩個市場一起抽動，但債市並沒有比股市怕得更兇。\n\n"
    "為什麼要拆成動作跟水位兩層看？因為只看其中一層都會下錯結論。只看相關係數 0.60，你會"
    "以為債市股市已經陷入危機式的高度連動；只看比值 P38，你又會以為兩個市場各走各的、毫無"
    "關係。把兩層疊起來才拼得出真相：市場在同一批訊息下同步反應，但恐慌的絕對強度都還沒到"
    "極端。\n\n"
    "| 觀察面 | 指標 | 數值 | 讀法 |\n"
    "|---|---|---|---|\n"
    "| 動作（連動） | 60 日滾動相關 | 0.50 | 同向抽動 |\n"
    "| 動作（連動） | 近 90 日平均相關 | 0.60 | 逼近 2022 水準 |\n"
    "| 水位（強度） | MOVE/VIX 比值 | 3.99（P38） | 債市恐慌相對溫和 |\n\n"
    "對一般投資人的實務意義：當你看到新聞說『債市大跌、殖利率飆升』時，先別急著認定股市要"
    "跟著崩。這段期間的數據顯示，兩個市場確實會同向抖動，但抖動的幅度都還在歷史的中間偏低"
    "帶。真正需要提高警覺的訊號，是比值從 P38 快速往 P80、P90 爬升——那代表債市的恐慌開始"
    "在絕對強度上甩開股市，通常是流動性或信用出問題的前兆。在那之前，同步只是同步，不是危機。\n\n"
    "再往回看一段歷史脈絡會更有感。2022 年那輪快速升息，MOVE 與 VIX 的相關一度衝到 0.7 以上，"
    "而且比值也一起往高百分位跑——那才是動作與水位同時亮紅燈的真正危機模式，債市股市不只一起抖，"
    "債市還怕得比股市更兇。對照之下，這段期間雖然相關已經逼近當年水準，比值卻仍賴在 P38 的低檔，"
    "兩層訊號沒有同時到位。這也是為什麼我們不建議只用單一指標下結論：相關係數告訴你兩個市場"
    "有沒有在聽同一則新聞，比值告訴你誰真的比較怕，兩者要一起看才不會把『同步的平靜』誤讀成"
    "『同步的恐慌』。方法上，本文所有數值都取自真實市場收盤資料、固定計算窗口與可複現的滾動"
    "統計流程，比值的歷史百分位也以同一段樣本回溯計算，避免用不同期間的口徑混為一談。放到操作上，"
    "這代表現階段比較合理的姿態是持續追蹤比值的爬升速度，而不是被單一則債市新聞嚇著、在兩個"
    "市場都還沒真正失控時就急著砍倉或加碼避險部位。"
)

# 2026-07-02 lazypack gate (publisher.lazypack_required_at) requires a 懶人包圖組
# section for any status='published' general article. These dup-exemption tests
# publish general/digest articles, so their bodies must carry one — otherwise the
# lazypack gate raises before the dup logic under test is even reached. A real
# published reader article always has this section; append it to isolate the dup
# behaviour from the (independent) lazypack gate.
_LAZYPACK = (
    "\n\n## 懶人包\n\n一張圖記住重點。\n\n"
    "![懶人包](https://qxhfgdfzazwpkdgesavm.supabase.co/storage/v1/object/public/article-images/test_lazypack.png)\n"
)


def _seed_storage(tmp_path: Path) -> Path:
    reports = tmp_path / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    feed = [
        {
            "id": _SEED_ID,
            "title": _SEED_TITLE,
            "description": _SEED_DESC,
            "content": _SEED_DESC,
            "status": "published",
            "audience": "general",
            "published_at": datetime.now(timezone.utc).isoformat(),
            "details": {"content_type": "general_article", "experiment_refs": [_SHARED_REF]},
            "tags": ["一般讀者", "MOVE", "VIX"],
        }
    ]
    (reports / "feed.json").write_text(json.dumps(feed, ensure_ascii=False))
    return reports


def _stub_network(monkeypatch, tmp_path: Path) -> None:
    """Hermetic isolation: make it IMPOSSIBLE for this test to touch production.

    2026-06-23 incident: a prior version only stubbed Publisher methods and a
    single supabase_sync reference, AND left SUPABASE_URL/KEY in the env. When
    the `import supabase_sync` stub failed (wrong module path), publish_milestone
    synced the test's MOVE-VIX digest fixture to PRODUCTION Supabase — two stub
    daily_digest rows leaked live and had to be retracted. Defense-in-depth now:
    clear creds, blank REMOTE_URL, stub every sync/notify/verify path, and stub
    sync_article + _post on BOTH module names.
    """
    for var in ("SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY", "SUPABASE_KEY"):
        monkeypatch.delenv(var, raising=False)
    original_exists = Path.exists

    def clean_checkout_exists(path: Path) -> bool:
        if path.name in {".env", ".env.local"}:
            return False
        return original_exists(path)

    monkeypatch.setattr(Path, "exists", clean_checkout_exists)
    monkeypatch.setattr(Publisher, "REMOTE_URL", "", raising=False)

    monkeypatch.setattr(Publisher, "_sync_to_remote", lambda *a, **k: None, raising=False)
    monkeypatch.setattr(Publisher, "_notify_article_published", lambda *a, **k: None, raising=False)
    monkeypatch.setattr(Publisher, "_sync_feed_to_remote", lambda *a, **k: None, raising=False)
    monkeypatch.setattr(Publisher, "_sync_report_to_remote", lambda *a, **k: None, raising=False)

    live_verify_stub = types.ModuleType("volpred.publisher.live_verify")
    live_verify_stub.verify_article_live = lambda *a, **k: True
    live_verify_stub.stamp_verified = lambda *a, **k: None
    live_verify_stub.emit_verify_alert = lambda *a, **k: None
    monkeypatch.setitem(
        sys.modules,
        "volpred.publisher.live_verify",
        live_verify_stub,
    )

    email_stub = types.ModuleType("volpred.publisher.email_notifier")

    class _EmailNotifier:
        def __init__(self, *args, **kwargs):
            pass

        def notify_article_published(self, *args, **kwargs):
            return None

    email_stub.EmailNotifier = _EmailNotifier
    monkeypatch.setitem(
        sys.modules,
        "volpred.publisher.email_notifier",
        email_stub,
    )

    sync_stub = types.ModuleType("supabase_sync")
    sync_stub.sync_article = lambda *a, **k: True
    sync_stub._post = lambda *a, **k: False
    for mod_name in ("supabase_sync", "scripts.supabase_sync"):
        monkeypatch.setitem(sys.modules, mod_name, sync_stub)

    # Isolate the topic-cluster cooldown gate to the tmp feed (otherwise it reads
    # the REAL feed.json and may raise topic_cluster_cooldown_blocked first).
    import volpred.topic_clusters as tc
    monkeypatch.setattr(tc, "FEED_PATH", tmp_path / "reports" / "feed.json", raising=False)

    # Disable the 2026-06-30 pre-publish throttle (burst gate): the seed and the
    # article-under-test are written milliseconds apart, which the rhythm gate
    # reads as a <30min burst. This test isolates the DUP-exemption logic, not
    # the throttle — stub it so the dup behaviour is what's exercised.
    import volpred.publisher.throttle as _throttle
    monkeypatch.setattr(_throttle, "check_publish_throttle", lambda *a, **k: None, raising=False)


def _feed_ids(reports: Path) -> list[str]:
    return [a.get("id") for a in json.loads((reports / "feed.json").read_text())]


def test_non_digest_recycle_warns_and_publishes(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """契約 1：同 ref 高相似度只產生可審計 warning，不吞文。"""
    reports = _seed_storage(tmp_path)
    _stub_network(monkeypatch, tmp_path)
    pub = Publisher(storage_dir=str(tmp_path))
    ret = pub.publish_milestone(
        title=_RECYCLE_TITLE,
        description=_RECYCLE_DESC,
        phase="test",
        details={
            "content_type": "general_article",
            "experiment_refs": [_SHARED_REF],
            "cluster_waiver": "test_dup_isolation",
        },
        tags=["一般讀者", "MOVE", "VIX"],
        status="published",
        audience="general",
        audit_strict=False,
    )
    assert ret != _SEED_ID
    assert set(_feed_ids(reports)) == {_SEED_ID, ret}
    decisions = [
        json.loads(line)
        for line in (
            tmp_path / "logs" / "dedup_decisions.jsonl"
        ).read_text(encoding="utf-8").splitlines()
    ]
    assert any(
        row.get("action") == "warn_same_ref_similarity"
        and row.get("matched_id") == _SEED_ID
        for row in decisions
    )


def test_same_ref_different_angle_publishes(tmp_path: Path, monkeypatch) -> None:
    """契約 2（boss directive 核心）：同 ref 但不同角度/不同寫法 → 照常發佈，不被靜默吞掉。"""
    reports = _seed_storage(tmp_path)
    _stub_network(monkeypatch, tmp_path)
    pub = Publisher(storage_dir=str(tmp_path))
    ret = pub.publish_milestone(
        title=_DIFF_TITLE,
        description=_DIFF_DESC + _LAZYPACK,
        phase="test",
        details={
            "content_type": "general_article",
            "experiment_refs": [_SHARED_REF],
            "cluster_waiver": "test_dup_isolation",
        },
        tags=["一般讀者", "MOVE", "VIX"],
        status="published",
        audience="general",
    )
    # 未被擋 → 回傳新 id，feed 新增一篇
    assert ret != _SEED_ID
    ids = _feed_ids(reports)
    assert _SEED_ID in ids and ret in ids and len(ids) == 2


def test_daily_digest_bypasses_recycle(tmp_path: Path, monkeypatch) -> None:
    """契約 3：daily_digest 即使內文與來源近乎相同也照常發佈（curation 本就會重疊）。"""
    reports = _seed_storage(tmp_path)
    _stub_network(monkeypatch, tmp_path)
    pub = Publisher(storage_dir=str(tmp_path))
    ret = pub.publish_milestone(
        title="每日精選導讀｜" + _SEED_TITLE,
        description=_RECYCLE_DESC + _LAZYPACK,  # near-identical to seed — would block a non-digest
        phase="test",
        details={"content_type": "daily_digest", "digest_articles": [_SEED_ID], "experiment_refs": [_SHARED_REF]},
        tags=["一般讀者", "精選導讀", "daily_digest", "MOVE", "VIX"],
        status="published",
        audience="general",
    )
    # 未被擋 → 回傳新 id（非 seed dup），feed 新增一篇
    assert ret != _SEED_ID
    ids = _feed_ids(reports)
    assert _SEED_ID in ids and ret in ids and len(ids) == 2


def test_second_daily_digest_same_tpe_day_is_blocked(tmp_path: Path, monkeypatch) -> None:
    """The publisher chokepoint enforces the daily digest's calendar invariant."""
    reports = _seed_storage(tmp_path)
    feed_path = reports / "feed.json"
    feed = json.loads(feed_path.read_text())
    feed[0]["details"]["content_type"] = "daily_digest"
    feed_path.write_text(json.dumps(feed, ensure_ascii=False))
    _stub_network(monkeypatch, tmp_path)

    pub = Publisher(storage_dir=str(tmp_path))
    ret = pub.publish_milestone(
        title="第二篇同日精選導讀",
        description=_DIFF_DESC + _LAZYPACK,
        phase="daily_digest",
        details={"content_type": "daily_digest", "digest_articles": [_SEED_ID]},
        tags=["一般讀者", "精選導讀"],
        status="published",
        audience="general",
    )

    assert ret == _SEED_ID
    assert _feed_ids(reports) == [_SEED_ID]


def test_daily_digest_on_next_tpe_day_is_allowed(tmp_path: Path, monkeypatch) -> None:
    """The uniqueness gate does not turn a daily invariant into a permanent lock."""
    reports = _seed_storage(tmp_path)
    feed_path = reports / "feed.json"
    feed = json.loads(feed_path.read_text())
    feed[0]["details"]["content_type"] = "daily_digest"
    feed[0]["published_at"] = "2020-01-01T00:00:00+00:00"
    feed_path.write_text(json.dumps(feed, ensure_ascii=False))
    _stub_network(monkeypatch, tmp_path)

    pub = Publisher(storage_dir=str(tmp_path))
    ret = pub.publish_milestone(
        title="隔日精選導讀",
        description=_DIFF_DESC + _LAZYPACK,
        phase="daily_digest",
        details={"content_type": "daily_digest", "digest_articles": [_SEED_ID]},
        tags=["一般讀者", "精選導讀"],
        status="published",
        audience="general",
    )

    assert ret != _SEED_ID
    assert len(_feed_ids(reports)) == 2
