"""Narrative-arc level duplicate detection.

Root cause this module fixes (2026-06-10 K1449/K1091 incident, 3rd strike of
the same class after K1396 2026-05-16 and the narrative-arc memo 2026-06-03):

Title-token Jaccard similarity is blind to "same story, different shell".
mile_5af5ec51 (K1449,「銅博士的波動率版本」) and mile_232ce5d4 (K1091,
「銅銀吃不到 VIX 紅利」) share ~0 title tokens and have different experiment
refs, yet tell the reader the exact same thing: copper vol × equity-vol/VIX
→ no incremental information. The correct domain model for "duplicate" is
the **(asset entities, conclusion class, mechanism, time horizon)** tuple —
the narrative arc — not surface text.

Arc key = (frozenset of canonical asset entities, conclusion class,
mechanism axis, time-horizon axis). Two articles whose entity overlap is
significant AND whose conclusion class matches are still allowed through when
both sides identify different mechanisms or different horizons. This prevents
one asset family from absorbing every later experiment that asks a genuinely
different causal/mechanical question.

Callers:
- publisher.publish_milestone — hard gate (last line of defence)
- scripts/refill_task_pool._research_backlog_candidates — direction-level
  filter (first line of defence; cheapest place to stop a duplicate)
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

# --- Canonical entity dictionary -------------------------------------------
# Maps surface forms (tickers, Chinese names, English names) to one canonical
# entity. Keep surface forms lowercase; Chinese matched as-is.
# "Core" entities are so ubiquitous on this platform that overlapping on them
# alone is meaningless (almost every article mentions SPY/VIX/台股). They only
# count toward overlap when combined with at least one distinctive entity.
_ENTITY_SURFACE: dict[str, str] = {
    # equity indices / broad market
    "spy": "US_EQUITY", "s&p": "US_EQUITY", "標普": "US_EQUITY", "美股": "US_EQUITY",
    "qqq": "NASDAQ", "納斯達克": "NASDAQ", "那斯達克": "NASDAQ",
    "iwm": "US_SMALLCAP", "羅素": "US_SMALLCAP",
    "reconstitution": "INDEX_RECONSTITUTION", "index reconstitution": "INDEX_RECONSTITUTION",
    "成分股調整": "INDEX_RECONSTITUTION", "指數調整": "INDEX_RECONSTITUTION",
    "0050": "TW_EQUITY", "台股": "TW_EQUITY", "台指": "TW_EQUITY", "加權指數": "TW_EQUITY",
    "台積電": "TSMC", "tsm": "TSMC", "2330": "TSMC",
    # vol indices
    "vix": "VIX", "恐慌指數": "VIX", "vvix": "VVIX",
    "move": "MOVE_INDEX",
    # metals
    "cper": "COPPER", "銅": "COPPER", "copper": "COPPER",
    "slv": "SILVER", "銀": "SILVER", "silver": "SILVER", "白銀": "SILVER",
    "gld": "GOLD", "黃金": "GOLD", "gold": "GOLD", "金價": "GOLD",
    "金銀比": "GOLD_SILVER_RATIO",
    # energy / commodities
    "uso": "OIL", "原油": "OIL", "oil": "OIL", "wti": "OIL", "石油": "OIL",
    "ung": "NATGAS", "天然氣": "NATGAS",
    "dba": "AGRI", "農產": "AGRI",
    "ura": "URANIUM", "鈾": "URANIUM",
    "krbn": "CARBON", "碳權": "CARBON",
    "dbc": "COMMODITY_BROAD", "商品指數": "COMMODITY_BROAD",
    # fx / rates / bonds
    "uup": "USD", "美元": "USD", "dxy": "USD", "美元指數": "USD",
    "fxy": "JPY", "日圓": "JPY", "日元": "JPY",
    "fxe": "EUR", "歐元": "EUR",
    "fxb": "GBP", "英鎊": "GBP",
    "tlt": "LONG_BOND", "長債": "LONG_BOND", "美債": "US_BOND", "公債": "US_BOND",
    "ief": "MID_BOND", "tip": "TIPS", "抗通膨債": "TIPS",
    "hyg": "HIGH_YIELD", "高收益債": "HIGH_YIELD",
    "lqd": "IG_CREDIT", "投資級債": "IG_CREDIT",
    "信用利差": "CREDIT_SPREAD",
    "殖利率曲線": "YIELD_CURVE", "倒掛": "YIELD_CURVE",
    "sofr": "RATES", "聯邦基金": "RATES", "fomc": "FOMC", "fed": "FOMC", "點陣圖": "FOMC",
    # crypto
    "btc": "BITCOIN", "比特幣": "BITCOIN", "bitcoin": "BITCOIN",
    "eth": "ETHEREUM", "以太": "ETHEREUM",
    # sectors / styles
    "xlk": "TECH_SECTOR", "xle": "ENERGY_SECTOR", "xlu": "UTILITIES", "xlp": "STAPLES",
    "xlf": "FIN_SECTOR", "金融股": "FIN_SECTOR",
    "smh": "SEMIS", "半導體": "SEMIS", "費半": "SEMIS",
    # Style/factor ETF terms. Keep "低波動" out: in this repo it often means
    # a generic low-volatility market regime, not the low-vol factor product.
    "usmv": "LOW_VOL_FACTOR", "splv": "LOW_VOL_FACTOR",
    "低波動 etf": "LOW_VOL_FACTOR", "低波動ETF": "LOW_VOL_FACTOR",
    "低波動因子": "LOW_VOL_FACTOR", "low-vol etf": "LOW_VOL_FACTOR",
    "low volatility etf": "LOW_VOL_FACTOR",
    "動量": "MOMENTUM", "momentum": "MOMENTUM",
    # Strategy / mechanism entities (2026-06-14): VT crowding 類文章原本抽不到
    # 資產實體 → arc-dedup 漏判（mile_ec28b1cc/mile_1a6d9369 同 arc）。這些是
    # distinctive 策略實體，搭配 conclusion class 才觸發 dedup，不會誤擋。
    "波動率目標": "VOL_TARGETING", "波動率目標策略": "VOL_TARGETING",
    "vol target": "VOL_TARGETING", "vol-target": "VOL_TARGETING",
    "volatility target": "VOL_TARGETING", "volatility-target": "VOL_TARGETING",
    "vt 策略": "VOL_TARGETING", "vt策略": "VOL_TARGETING",
    "風險平價": "RISK_PARITY", "risk parity": "RISK_PARITY", "risk-parity": "RISK_PARITY",
    # EM / regional
    "vnm": "VIETNAM", "越南": "VIETNAM", "eido": "INDONESIA", "印尼": "INDONESIA",
    "thd": "THAILAND", "泰國": "THAILAND", "ephe": "PHILIPPINES", "菲律賓": "PHILIPPINES",
    "ewj": "JAPAN_EQ", "日股": "JAPAN_EQ", "日經": "JAPAN_EQ", "n225": "JAPAN_EQ",
    "vgk": "EUROPE_EQ", "歐股": "EUROPE_EQ",
}

# Entities too ubiquitous to be distinctive on their own.
_CORE_ENTITIES = {"US_EQUITY", "VIX", "TW_EQUITY"}
_BROAD_MARKET_ENTITIES = {"NASDAQ", "US_SMALLCAP", "LONG_BOND", "US_BOND", "MID_BOND"}
_MECHANISM_ENTITIES = {"INDEX_RECONSTITUTION", "VOL_TARGETING", "RISK_PARITY", "YIELD_CURVE", "FOMC"}

# Longest-first surface forms for greedy Chinese matching.
_SURFACE_SORTED = sorted(_ENTITY_SURFACE, key=len, reverse=True)

# --- Conclusion classes ------------------------------------------------------
# Keyword votes; class with most hits wins. Falls back to "descriptive".
_CONCLUSION_KEYWORDS: dict[str, list[str]] = {
    "null_no_info": [
        "歸零", "沒用", "無增量", "增量資訊幾乎", "null", "不成立", "接近於零",
        "幾乎沒有", "吃不到", "沒差別", "無法預測", "不顯著", "分不出", "看不到效果",
        "沒有領先", "無預測力", "預測力歸零", "不存在", "站不住",
    ],
    "positive_signal": [
        "顯著改善", "顯著領先", "預測力顯著", "有效降低", "明確領先", "顯著提升",
        "通過檢定", "穩健成立", "顯著為正", "顯著為負",
    ],
    "mixed": [
        "部分成立", "條件成立", "mixed", "好壞參半", "視情況", "regime 而定", "並不總是",
    ],
    # 2026-06-14: crowding / 系統性風險 arc class（mile_ec28b1cc + mile_1a6d9369
    # 同日同 arc「VT crowding → 市場更不安全」漏判教訓）。與 strategy 實體
    # (VOL_TARGETING/RISK_PARITY) 同時匹配才擋 → 不誤擋不同結論的 VT 研究。
    "systemic_crowding": [
        "集體陷阱", "群聚風險", "群聚", "擁擠交易", "擁擠", "系統性風險", "系統風險",
        "閃崩", "踩踏", "同步賣壓", "連鎖", "共振", "herding", "crowding",
        "集體避險", "都用同一套", "同一套規則", "更不安全", "放大波動",
    ],
}


# --- Mechanism and horizon axes ---------------------------------------------
# These axes intentionally remain coarse. They are not used to create a duplicate
# by themselves; they only prevent false-positive blocks after entity+conclusion
# already matched.
_MECHANISM_KEYWORDS: dict[str, list[str]] = {
    "auction_liquidity": [
        "auction", "treasury auction", "bid-to-cover", "bid to cover",
        "弱標", "標售", "demand weakness",
    ],
    "factor_causality": [
        "double-ml", "double ml", "dml", "causal", "causality", "因果",
        "instrument", "instrumental", "sue", "factor", "因子",
    ],
    "event_study": [
        "event study", "event-study", "event window", "事件研究", "事件窗",
        "announcement", "公告", "財報", "reconstitution", "成分股調整",
    ],
    "carry_regime": [
        "backwardation", "contango", "roll yield", "roll-yield",
        "term structure", "期限結構", "regime switch", "regime-switch",
        "regime-switching",
    ],
    "momentum_reversal": [
        "momentum", "動能", "reversal", "反轉", "short-term momentum",
        "短期動能", "mean-revert", "mean revert",
    ],
    "private_credit_stress": [
        "bdc", "private credit", "私募信貸", "nav-discount", "nav discount",
        "bizd", "arcc", "bxsl", "obdc", "fsk", "psec",
    ],
    "tax_friction": [
        "tax friction", "tax", "稅務", "稅", "wash sale", "稅負",
    ],
    "crowding_flow": [
        "crowding", "herding", "擁擠", "群聚", "同步賣壓", "踩踏",
        "forced deleveraging", "volatility targeting", "vol target",
    ],
    "coherence_decay": [
        "coherence", "coherence decay", "co-movement", "comovement",
        "correlation decay",
    ],
    "retail_flow": [
        "retail participation", "retail flow", "retail-flow", "retail proxy",
        "retail-like", "order imbalance", "散戶 proxy", "散戶占比",
        "散戶參與", "散戶活躍", "散戶交易", "散戶下單", "融資", "融券",
        "margin activity", "margin turnover",
    ],
    "tail_risk_allocation": [
        "cvar", "expected shortfall", "tail-risk", "tail risk",
        "risk parity", "risk-parity", "erc", "sigma-rp", "cvar-rp",
    ],
    "vrp_decomposition": [
        "vrp", "variance risk premium", "semivariance", "upside",
        "downside", "上行", "下行",
    ],
    "macro_policy": [
        "fomc", "fed", "cpi", "nfp", "sofr", "credit-spread",
        "credit spread", "利率", "點陣圖",
    ],
    "vol_term_structure": [
        "vix9d", "vix3m", "vvix", "move", "skew", "iv-rv",
        "implied volatility", "option", "選擇權",
    ],
    "cross_asset_spillover": [
        "lead-lag", "lead lag", "spillover", "傳導", "cross-asset",
        "跨市場", "領先", "增量資訊", "incremental information",
        "vix 紅利", "吃不到 vix", "拿同一個 vix",
    ],
    "model_forecast": [
        "garch", "gjr-garch", "egarch", "har-rv", "har rv", "qlike",
        "forecast model", "model comparison", "預測模型",
    ],
}

_GENERIC_MECHANISMS = {"cross_asset_spillover", "model_forecast"}

_MULTI_HORIZON_PATTERNS = [
    r"multi[-\s]?horizon",
    r"across horizons?",
    r"multiple horizons?",
    r"多期",
    r"跨期",
    r"t\s*\+\s*\d+\s*(?:\.\.|-|to|至|到)\s*t?\s*\+?\s*\d+",
    r"h\s*=\s*\d+\s*[,/]\s*\d+",
]

_TIME_HORIZON_KEYWORDS: dict[str, list[str]] = {
    "intraday": [
        "intraday", "intra-day", "5-min", "5 min", "5分鐘", "分鐘",
        "hourly", "小時", "盤中", "日內",
    ],
    "monthly": [
        "next-month", "next month", "monthly", "month", "下月", "月度",
        "1m", "one-month",
    ],
    "weekly": [
        "weekly", "week", "1-week", "one-week", "5d", "5-day", "21d",
        "21-day", "t+5", "t + 5", "t+21", "t + 21", "週", "一週",
        "1-4 weeks", "短期",
    ],
    "daily": [
        "next-day", "next day", "1-day", "one-day", "1d", "daily",
        "t+1", "t + 1", "隔日", "隔天", "明天", "今天", "日後",
    ],
}


def extract_entities(text: str) -> set[str]:
    """Extract canonical asset entities from title+content text."""
    found: set[str] = set()
    lower = text.lower()
    for surface in _SURFACE_SORTED:
        if surface.isascii():
            # word-ish boundary for tickers/english to avoid e.g. 'tip' in 'multiple'
            if re.search(rf"(?<![a-z0-9]){re.escape(surface)}(?![a-z0-9])", lower):
                found.add(_ENTITY_SURFACE[surface])
        else:
            if surface in text:
                found.add(_ENTITY_SURFACE[surface])
    return found


def classify_conclusion(text: str) -> str:
    """Classify the article's conclusion into a coarse class."""
    votes = {cls: 0 for cls in _CONCLUSION_KEYWORDS}
    for cls, kws in _CONCLUSION_KEYWORDS.items():
        for kw in kws:
            if kw.lower() in text.lower():
                votes[cls] += 1
    best = max(votes, key=lambda c: votes[c])
    if votes[best] == 0:
        return "descriptive"
    return best


def classify_mechanisms(text: str) -> set[str]:
    """Classify the article's mechanism axis.

    Returns the strongest specific mechanism(s). Generic "model/forecast" and
    "cross-asset" labels are only used when no more specific mechanism is
    visible; otherwise they would over-link most volatility articles.
    """
    lower = (text or "").lower()
    scores: dict[str, int] = {}
    for mechanism, keywords in _MECHANISM_KEYWORDS.items():
        score = 0
        for keyword in keywords:
            if keyword.lower() in lower:
                score += 1
        if score:
            scores[mechanism] = score
    if not scores:
        return {"unspecified"}

    specific = {m: s for m, s in scores.items() if m not in _GENERIC_MECHANISMS}
    pool = specific or scores
    best = max(pool.values())
    return {mechanism for mechanism, score in pool.items() if score == best}


def classify_time_horizon(text: str) -> str:
    """Classify the primary forecast/event horizon."""
    lower = (text or "").lower()
    if any(re.search(pattern, lower) for pattern in _MULTI_HORIZON_PATTERNS):
        return "multi_horizon"
    for horizon in ("intraday", "monthly", "weekly", "daily"):
        if any(keyword.lower() in lower for keyword in _TIME_HORIZON_KEYWORDS[horizon]):
            return horizon
    return "unspecified"


def arc_signature(title: str, content: str | None = "") -> dict:
    """Return the metadata schema used by the arc-dedup gate.

    The schema is safe to persist in feed item details. Callers should still be
    able to recompute it from title/content because historical articles may not
    have been backfilled yet.
    """
    text = f"{title or ''}\n{content or ''}"
    return {
        "schema_version": "arc_dedup_v2",
        "entities": sorted(extract_entities(text)),
        "conclusion_class": classify_conclusion(text),
        "mechanisms": sorted(classify_mechanisms(text)),
        "time_horizon": classify_time_horizon(text),
    }


def _signature_from_feed_item(item: dict) -> dict:
    details = item.get("details") or {}
    sig = details.get("arc_signature") if isinstance(details, dict) else None
    if isinstance(sig, dict):
        entities = sig.get("entities")
        conclusion = sig.get("conclusion_class")
        mechanisms = sig.get("mechanisms")
        horizon = sig.get("time_horizon")
        if isinstance(entities, list) and isinstance(conclusion, str):
            return {
                "schema_version": str(sig.get("schema_version") or "arc_dedup_v2"),
                "entities": sorted(str(e) for e in entities),
                "conclusion_class": conclusion,
                "mechanisms": sorted(_axis_values(mechanisms)),
                "time_horizon": str(horizon or "unspecified"),
            }
    text = f"{item.get('title', '')}\n{item.get('content') or item.get('description') or ''}"
    return arc_signature("", text)


def _axis_values(raw) -> set[str]:
    if isinstance(raw, str):
        return {raw} if raw else {"unspecified"}
    if isinstance(raw, (list, tuple, set)):
        vals = {str(v) for v in raw if str(v)}
        return vals or {"unspecified"}
    return {"unspecified"}


def _mechanisms_compatible(new_mechanisms: set[str], old_mechanisms: set[str]) -> bool:
    if "unspecified" in new_mechanisms or "unspecified" in old_mechanisms:
        return True
    return bool(new_mechanisms & old_mechanisms)


def _horizons_compatible(new_horizon: str, old_horizon: str) -> bool:
    if new_horizon == "unspecified" or old_horizon == "unspecified":
        return True
    return new_horizon == old_horizon


def _is_significant_overlap(new_ents: set[str], old_ents: set[str]) -> bool:
    """Overlap counts when it includes >=1 distinctive entity and >=2 total,
    OR >=1 distinctive entity when either article has few entities (narrow
    topic — e.g. both articles are about copper).

    Broad-survey asymmetry (2026-06-17): if one side is a broad cross-asset
    survey (>=6 distinctive entities) and the other side is narrow (<=2
    distinctive entities), require >=3 distinctive overlap entities to count
    as a match. Otherwise a single mega-survey article (e.g. "14 assets ×
    GJR-GARCH persistence") absorbs every subsequent single-asset NULL study
    as an arc-dup, draining the refill pool. Single-asset research is a
    different grain than a cross-asset survey and should be allowed.

    Core+single-distinctive guard (2026-06-17): a shared core entity like
    US_EQUITY must not make one distinctive entity look like "two overlaps".
    K1341 Russell/S&P reconstitution was blocked by generic US_SMALLCAP NULL
    articles because the overlap was {US_EQUITY, US_SMALLCAP}. For a single
    distinctive overlap, require either a shared VIX mechanism or both sides
    to be exactly that same narrow entity.

    Broad-market mechanism guard (2026-06-17): sharing only broad ETF/index
    proxies such as NASDAQ/IWM is not enough when one side is about a specific
    mechanism such as index reconstitution.
    """
    overlap = new_ents & old_ents
    if not overlap:
        return False
    distinctive_overlap = overlap - _CORE_ENTITIES
    if not distinctive_overlap:
        return False  # only SPY/VIX/台股 in common — not a topic match
    new_distinctive = new_ents - _CORE_ENTITIES
    old_distinctive = old_ents - _CORE_ENTITIES
    smaller_distinctive = min(len(new_distinctive), len(old_distinctive))
    bigger_distinctive = max(len(new_distinctive), len(old_distinctive))
    # Broad-survey vs narrow-study asymmetry guard.
    if bigger_distinctive >= 6 and smaller_distinctive <= 2:
        if len(distinctive_overlap) < 3:
            return False
    if (
        distinctive_overlap
        and distinctive_overlap <= _BROAD_MARKET_ENTITIES
        and ((new_distinctive ^ old_distinctive) & _MECHANISM_ENTITIES)
    ):
        return False
    if len(distinctive_overlap) >= 2:
        return True
    # Single distinctive entity: significant only when the common story also
    # shares the VIX mechanism (e.g. copper × VIX null) or both sides are the
    # exact same narrow asset/topic. Core US_EQUITY alone is not enough.
    if len(distinctive_overlap) == 1:
        if "VIX" in overlap:
            return True
        return new_distinctive == old_distinctive == distinctive_overlap
    return False


def find_arc_duplicates(
    title: str,
    content: str,
    feed: list[dict],
    days: int = 90,
    max_scan: int = 300,
) -> list[dict]:
    """Return feed articles that are narrative-arc duplicates of the new piece.

    Arc duplicate = significant entity overlap (incl. >=1 distinctive entity)
    AND same conclusion class AND compatible mechanism/horizon, within `days`.
    Direction-agnostic by design.
    """
    new_sig = arc_signature(title, content)
    new_ents = set(new_sig["entities"])
    if not new_ents:
        return []
    new_cls = str(new_sig["conclusion_class"])
    # "descriptive" is the fallback class meaning "no identifiable conclusion".
    # Two articles that both fail to classify are NOT the same narrative arc —
    # matching on it produces false positives whenever unrelated pieces happen
    # to share one distinctive entity (2026-06-14: SpaceX IPO capital-structure
    # piece mile_6159728d falsely blocked against big-tech-vol mile_312204b2 on
    # shared USD+US_EQUITY, both descriptive). An arc needs a real conclusion
    # class on the *new* side to be a defined arc.
    if new_cls == "descriptive":
        return []
    new_mechanisms = _axis_values(new_sig.get("mechanisms"))
    new_horizon = str(new_sig.get("time_horizon") or "unspecified")

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    dups: list[dict] = []
    recent = sorted(
        feed, key=lambda x: x.get("published_at") or x.get("created_at", ""), reverse=True
    )[:max_scan]
    for existing in recent:
        if existing.get("status") in ("unpublished", "retracted"):
            continue
        ts_raw = existing.get("published_at") or existing.get("created_at") or ""
        try:
            from dateutil.parser import parse as dtparse

            if dtparse(ts_raw).astimezone(timezone.utc) < cutoff:
                continue
        except Exception:
            pass  # unparseable timestamp → keep (conservative)
        ex_sig = _signature_from_feed_item(existing)
        ex_ents = set(ex_sig["entities"])
        if not _is_significant_overlap(new_ents, ex_ents):
            continue
        ex_cls = str(ex_sig["conclusion_class"])
        if ex_cls != new_cls:
            continue
        ex_mechanisms = _axis_values(ex_sig.get("mechanisms"))
        if not _mechanisms_compatible(new_mechanisms, ex_mechanisms):
            continue
        ex_horizon = str(ex_sig.get("time_horizon") or "unspecified")
        if not _horizons_compatible(new_horizon, ex_horizon):
            continue
        dups.append(
            {
                "id": existing.get("id", "?"),
                "title": existing.get("title", "?"),
                "shared_entities": sorted(new_ents & ex_ents),
                "conclusion_class": new_cls,
                "shared_mechanisms": sorted(new_mechanisms & ex_mechanisms),
                "new_mechanisms": sorted(new_mechanisms),
                "existing_mechanisms": sorted(ex_mechanisms),
                "time_horizon": new_horizon,
                "existing_time_horizon": ex_horizon,
            }
        )
    return dups
