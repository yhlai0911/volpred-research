from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
import json
import re
import sys


ROOT = Path(__file__).resolve().parents[2]
FEED_PATH = ROOT / "storage" / "reports" / "feed.json"

# 2026-06-30 boss escalation (email-12256「不是改語意分析且動態調整了嗎 立刻檢查」):
# 舊 spy cluster 是 catch-all 災難 — keyword「美股」過廣 + spy 排在 garch/vt/taiwan
# 之前 + 缺粒度主題 cluster → 整個波動率研究 corpus（HAR-RV/GARCH/VaR/避險/隔夜/
# return 預測/事件研究…，全用 SPY 當測試資產）被掃進 spy → 74/40=1.9x 假超標。
# 修法（語意化）：(1) 加粒度「主題」cluster 反映文章「關於什麼」而非「用什麼資料」；
# (2) 排序 = specific market/model/strategy 先、thematic 次、spy catch-all 最後；
# (3) spy 收窄成只認真正 S&P/SPY-index 主題（移除「美股」）。
# classify 仍是 first-match-in-order，但 order 現在 encode 主題優先序（語意近似）。
# 對齊 boss 原則「不重複是主題 不是關鍵字」(line 35-44 註解的 follow-up 落地)。
CLUSTER_VARIANTS: dict[str, list[str]] = {
    # ── 特定市場 / 模型 / 策略（最具體，優先） ──
    "taiwan": ["0050.TW", "0056.TW", "00878", "00919", "00929", "00940", "2330.TW", "台股", "台灣市場", "TAIFEX", "台指期"],
    "vix": ["VIX", "VVIX", "VIX9D", "12/VIX", "恐慌指數", "VIX 條件槓桿"],
    "factor_etf": [
        "MTUM", "QUAL", "USMV", "VLUE", "SPLV", "SPHQ", "USHY",
        "因子 ETF", "因子ETF", "因子投資", "因子輪", "低波動 ETF", "smart beta", "smart-beta", "美股 ETF",
    ],
    "vt": ["VT", "VT策略", "Hybrid-VT", "波動率目標", "volatility targeting", "risk parity", "Risk-Parity", "再平衡"],
    "garch": ["GARCH", "GJR-GARCH", "GJR", "EGARCH", "EWMA", "GARCH-MIDAS", "MF-GJR"],
    # ── 主題型（thematic）：反映文章「關於什麼」，把舊 spy catch-all 拆開 ──
    "risk_mgmt": ["VaR", "ES", "Expected Shortfall", "風險管理", "風險值", "極端風險", "尾端風險", "尾端", "traffic light", "Basel", "回撤", "MDD"],
    "forecast_method": [
        "HAR-RV", "HAR", "RECH", "LSTM", "神經網路", "機器學習", "深度學習",
        "wavelet", "小波", "BMA", "模型評比", "conformal", "transformer",
        "realized vol", "已實現波動", "高頻", "5分鐘", "5 分鐘", "盤中訊號", "集成", "ensemble",
    ],
    "event_study": ["FOMC", "CPI", "NFP", "財報", "earnings", "殖利率曲線", "倒掛", "監管", "Federal Register", "事件研究"],
    "hedging": ["避險", "hedge", "futures-hedging", "hedge-ratio", "hedge ratio", "對沖"],
    "microstructure": ["隔夜", "overnight", "盤中", "order flow", "委託", "買賣壓", "microstructure", "流動性", "薄市場"],
    "return_predict": ["return 預測", "return-predictability", "報酬預測", "動能", "momentum", "反轉", "reversal", "跟單", "選股", "alpha"],
    # ── 一般美股（catch-all，最後；已移除過廣的「美股」，只認真正 index 主題） ──
    "spy": ["SPY", "QQQ", "S&P 500", "標普", "S&P500"],
}

# 2026-06-29 boss decision (email-12132「依照你的建議進行」): for a VOLATILITY
# research platform, the prior caps (vix 5% / spy 3% of a ~306-article month) were
# too tight — they treated the platform's CORE subject as runaway concentration.
# The boss's clarifying principle: "不重複是主題 不是方向/關鍵字" — e.g. 「波動率對
# 風險值的影響」 vs 「波動率對選擇權定價的影響」 are two DIFFERENT topics, not
# over-concentration, even though both keyword-classify as a vol cluster. Since the
# keyword classifier can't see subtopics, caps are raised to give vol/TW core
# clusters realistic headroom (still catching true runaway). Genuine subtopic-level
# concentration is measured by arc_diversity (content_quality), not these caps.
# Follow-up: move concentration measurement to arc/subtopic granularity.
# 2026-06-30：語意化分類後重設 caps。原則（boss）：核心主題（vix/risk_mgmt/garch/
# taiwan）給 ~40% headroom（current count × ~1.4），讓健康狀態 ~0.7x、真正翻倍才 warn；
# 不把平台核心主題當 runaway。相對集中度由 DOMINANT_RATIO_LIMIT（share-based，隨總量
# 動態縮放）兜底。current 30d 分布：vix62 / risk_mgmt55 / taiwan34 / garch28 / spy14 /
# event12 / vt11 / forecast8 / factor6 / return3 / micro2 / hedge1。
CLUSTER_HARD_CAPS: dict[str, int] = {
    "vix": 80,
    "risk_mgmt": 70,
    "taiwan": 45,
    "garch": 40,
    "spy": 30,
    "forecast_method": 25,
    "event_study": 25,
    "vt": 20,
    "factor_etf": 15,
    "return_predict": 15,
    "microstructure": 15,
    "hedging": 15,
}

DEFAULT_CLUSTER_CAP = 15
DOMINANT_RATIO_LIMIT = 0.35  # 2026-06-29: vol is core for a vol platform; was 0.25
                             # (share-based = 動態：隨 30d 總量縮放，補 static cap)

# 2026-06-29: soft cap for timely / topic-bound types (event_article,
# trending_repost, member_qa, daily_*). They are exempt from the HARD cap
# (cluster_gate_status.blocked) because their repetition is by design — a
# trending take responds to a live event; the daily VIX bulletin is templated.
# But "exempt" was a free pass that let vix grow to 92/15 = 6.1x and spy to
# 83/10 = 8.3x in 30d (alerts.py cluster_cap_drift, boss escalation 2026-06-29).
# So even timely types now stop at `hard_cap * SOFT_CAP_MULTIPLIER`. Real events
# can still override via `details['cluster_waiver']='<reason>'` (e.g. an FOMC
# day) — same waiver mechanism the hard cap already supports.
SOFT_CAP_MULTIPLIER = 2.5


def _warn_topic_clusters(
    message: str,
    feed_path: Path,
    exc: Exception,
    *,
    item_id: object | None = None,
    value: object | None = None,
) -> None:
    print(
        "[topic_clusters] WARN "
        f"{message} path={feed_path} item_id={item_id!r} "
        f"value={value!r} error={type(exc).__name__}: {exc}",
        file=sys.stderr,
    )


def _normalize(text: str) -> str:
    return (text or "").strip().lower()


def classify_topic_cluster(title: str, tags: list[str] | None = None, content: str | None = None) -> str | None:
    """Classify article into topic cluster by title + tags only.

    2026-05-27 fix: content scanning was too aggressive — daily_update.py
    boilerplate "市場快照: VIX 17.01, GARCH 11.3%" caused EVERY daily article
    to count toward vix+garch clusters → audit showed VIX=312/30d (vs 109
    when scanning only title). content arg accepted for API compatibility
    but ignored. Cluster = what the article is ABOUT (title/tags), not what
    keywords appear in body.
    """
    haystack_parts = [title or ""]
    if tags:
        haystack_parts.extend(str(t) for t in tags)
    haystack = " ".join(haystack_parts).lower()

    for cluster, variants in CLUSTER_VARIANTS.items():
        for variant in variants:
            if _variant_matches(_normalize(variant), haystack):
                return cluster
    return None


def _variant_matches(variant_norm: str, haystack: str) -> bool:
    """Return True if `variant_norm` (already lowercased) matches `haystack`.

    2026-07-04 fix: plain substring matching over-fired for short ASCII
    keywords — "es" (Expected Shortfall) matched inside "tim**es**tamp" /
    "s**es**sion", "var" (VaR) matched inside "**var**iance" (a VOLATILITY term
    that then wrongly counted toward risk_mgmt), silently corrupting cluster
    counts / caps / dedup. For ≤3-char pure-ASCII-alpha keywords, require an
    ASCII word boundary (no adjacent a–z) so they match as whole tokens.
    CJK-adjacent text still matches (a Chinese char is not a–z, so "vix期限"
    still hits "vix"); only spurious mid-English-word hits are suppressed.
    Longer / non-ASCII keywords keep substring matching unchanged.
    """
    if len(variant_norm) <= 3 and variant_norm.isascii() and variant_norm.isalpha():
        return re.search(r"(?<![a-z])" + re.escape(variant_norm) + r"(?![a-z])", haystack) is not None
    return variant_norm in haystack


def cluster_cap(cluster: str | None) -> int:
    if not cluster:
        return DEFAULT_CLUSTER_CAP
    return CLUSTER_HARD_CAPS.get(cluster, DEFAULT_CLUSTER_CAP)


def load_feed_items(feed_path: Path = FEED_PATH) -> list[dict]:
    if not feed_path.exists():
        return []
    data = json.loads(feed_path.read_text(encoding="utf-8"))
    return data if isinstance(data, list) else data.get("reports", [])


def recent_cluster_counts(
    *,
    days: int = 30,
    feed_path: Path = FEED_PATH,
    statuses: tuple[str, ...] = ("published", "draft", "scheduled"),
) -> tuple[Counter, int]:
    feed = load_feed_items(feed_path)
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    counts: Counter[str] = Counter()
    total = 0
    for item in feed:
        if not isinstance(item, dict):
            continue
        # 2026-06-30: 排除每日操作型 fixture（audience="daily" = 每日策略建議 / 持倉比率），
        # 它們是強制每日自動貼文、非 cap 要 pace 的 discretionary 編輯內容。
        # 過去把 19 篇 daily fixture 全 classify 成 vix → 灌爆 vix cap（87 vs 50）→ 永久
        # false-alarm 並遮蔽真正的編輯集中（spy 73/40=1.8x）。cap/cooldown gate 本就只擋
        # general/research discretionary publish，count 也應同口徑只算 discretionary。
        if (item.get("audience") or "") == "daily":
            continue
        if item.get("status") not in statuses:
            continue
        ts = item.get("published_at") or item.get("created_at")
        if not ts:
            continue
        try:
            dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        except ValueError as exc:
            _warn_topic_clusters(
                "feed timestamp parse failed; skipping item",
                feed_path,
                exc,
                item_id=item.get("id"),
                value=ts,
            )
            continue
        if dt < cutoff:
            continue
        cluster = classify_topic_cluster(
            item.get("title", ""),
            item.get("tags") or [],
            item.get("description") or item.get("content") or "",
        )
        if cluster:
            counts[cluster] += 1
        total += 1
    return counts, total


def cluster_gate_status(cluster: str | None, *, days: int = 30, feed_path: Path = FEED_PATH) -> dict:
    counts, total = recent_cluster_counts(days=days, feed_path=feed_path)
    count = counts.get(cluster or "", 0) if cluster else 0
    cap = cluster_cap(cluster)
    ratio = (count / total) if total else 0.0
    soft_cap = int(cap * SOFT_CAP_MULTIPLIER)
    return {
        "cluster": cluster,
        "count": count,
        "cap": cap,
        "soft_cap": soft_cap,
        "soft_cap_multiplier": SOFT_CAP_MULTIPLIER,
        "total": total,
        "ratio": ratio,
        "blocked": bool(cluster and count >= cap),
        "soft_blocked": bool(cluster and count >= soft_cap),
        "dominant_ratio_breached": bool(cluster and ratio > DOMINANT_RATIO_LIMIT),
    }


def cluster_soft_cap(cluster: str | None) -> int:
    """Hard cap × SOFT_CAP_MULTIPLIER, the ceiling that even timely / topic-bound
    types must respect (FOMC / CPI / trending / daily_digest etc).

    Hard cap blocks discretionary general/research; soft cap blocks everything
    including timely — except an explicit ``details['cluster_waiver']`` set by
    the caller for genuinely critical real-world events.
    """
    return int(cluster_cap(cluster) * SOFT_CAP_MULTIPLIER)
