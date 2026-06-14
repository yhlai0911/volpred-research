"""Narrative-arc level duplicate detection.

Root cause this module fixes (2026-06-10 K1449/K1091 incident, 3rd strike of
the same class after K1396 2026-05-16 and the narrative-arc memo 2026-06-03):

Title-token Jaccard similarity is blind to "same story, different shell".
mile_5af5ec51 (K1449,「銅博士的波動率版本」) and mile_232ce5d4 (K1091,
「銅銀吃不到 VIX 紅利」) share ~0 title tokens and have different experiment
refs, yet tell the reader the exact same thing: copper vol × equity-vol/VIX
→ no incremental information. The correct domain model for "duplicate" is
the **(asset entities, conclusion class)** pair — the narrative arc — not
surface text.

Arc key = (frozenset of canonical asset entities, conclusion class).
Two articles whose entity overlap is significant AND whose conclusion class
matches are arc-duplicates regardless of direction (A→B null vs B→A null is
the same story to a reader) or wording.

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


def _is_significant_overlap(new_ents: set[str], old_ents: set[str]) -> bool:
    """Overlap counts when it includes >=1 distinctive entity and >=2 total,
    OR >=1 distinctive entity when either article has few entities (narrow
    topic — e.g. both articles are about copper)."""
    overlap = new_ents & old_ents
    if not overlap:
        return False
    distinctive = overlap - _CORE_ENTITIES
    if not distinctive:
        return False  # only SPY/VIX/台股 in common — not a topic match
    if len(overlap) >= 2:
        return True
    # single distinctive entity: significant when it dominates either side
    smaller = min(len(new_ents - _CORE_ENTITIES), len(old_ents - _CORE_ENTITIES))
    return smaller <= 2


def find_arc_duplicates(
    title: str,
    content: str,
    feed: list[dict],
    days: int = 90,
    max_scan: int = 300,
) -> list[dict]:
    """Return feed articles that are narrative-arc duplicates of the new piece.

    Arc duplicate = significant entity overlap (incl. >=1 distinctive entity)
    AND same conclusion class, within `days`. Direction-agnostic by design.
    """
    new_text = f"{title}\n{content or ''}"
    new_ents = extract_entities(new_text)
    if not new_ents:
        return []
    new_cls = classify_conclusion(new_text)

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
        ex_text = f"{existing.get('title', '')}\n{existing.get('content') or existing.get('description') or ''}"
        ex_ents = extract_entities(ex_text)
        if not _is_significant_overlap(new_ents, ex_ents):
            continue
        ex_cls = classify_conclusion(ex_text)
        if ex_cls != new_cls:
            continue
        dups.append(
            {
                "id": existing.get("id", "?"),
                "title": existing.get("title", "?"),
                "shared_entities": sorted(new_ents & ex_ents),
                "conclusion_class": new_cls,
            }
        )
    return dups
