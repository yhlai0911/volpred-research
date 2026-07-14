"""Narrative-arc level duplicate detection.

Root cause this module fixes (2026-06-10 K1449/K1091 incident, 3rd strike of
the same class after K1396 2026-05-16 and the narrative-arc memo 2026-06-03):

Title-token Jaccard similarity is blind to "same story, different shell".
mile_5af5ec51 (K1449,「銅博士的波動率版本」) and mile_232ce5d4 (K1091,
「銅銀吃不到 VIX 紅利」) share ~0 title tokens and have different experiment
refs, yet tell the reader the exact same thing: copper vol × equity-vol/VIX
→ no incremental information. The correct domain model for "duplicate" is
the **(entity scope, conclusion class, narrative axis, mechanism, time horizon)**
tuple — the narrative arc — not surface text.

Arc key = (frozenset of canonical asset entities, conclusion class,
reader/methodology narrative axis, mechanism axis, time-horizon axis). Two articles whose entity overlap is
significant AND whose conclusion class matches are still allowed through when
both sides identify different reader-facing axes, mechanisms, or horizons. This
prevents one asset family or paper-methodology article from absorbing every
later experiment that asks a genuinely different reader question.

Callers:
- publisher.publish_milestone — hard gate (last line of defence)
- scripts/refill_task_pool._research_backlog_candidates — direction-level
  filter (first line of defence; cheapest place to stop a duplicate)
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

LOG = logging.getLogger(__name__)
ARC_SIGNATURE_SCHEMA_VERSION = "arc_dedup_v4"
ARC_NEAR_MISS_REASONS = frozenset({"descriptive_fuzzy_mechanism"})

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
    # Bare 「銀」 also occurs in 銀行 and used to turn every bank article into
    # SILVER.  Keep only unambiguous metal/product surfaces.
    "slv": "SILVER", "silver": "SILVER", "白銀": "SILVER",
    "銀價": "SILVER", "銀期貨": "SILVER", "銀市場": "SILVER",
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
    "usdt": "STABLECOIN", "tether": "STABLECOIN", "泰達幣": "STABLECOIN",
    "usdc": "STABLECOIN", "usd coin": "STABLECOIN",
    "stablecoin": "STABLECOIN", "stablecoins": "STABLECOIN",
    "穩定幣": "STABLECOIN", "稳定币": "STABLECOIN",
    "defi": "DEFI", "decentralized finance": "DEFI",
    "去中心化金融": "DEFI", "去中心化金融服務": "DEFI",
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
    "cta": "MANAGED_FUTURES", "dbmf": "MANAGED_FUTURES", "kmlm": "MANAGED_FUTURES",
    "managed futures": "MANAGED_FUTURES", "managed-futures": "MANAGED_FUTURES",
    "trend following": "TREND_FOLLOWING", "trend-following": "TREND_FOLLOWING",
    "趨勢跟隨": "TREND_FOLLOWING", "危機alpha": "CRISIS_ALPHA", "crisis alpha": "CRISIS_ALPHA",
    # Strategy / mechanism entities (2026-06-14): VT crowding 類文章原本抽不到
    # 資產實體 → arc-dedup 漏判（mile_ec28b1cc/mile_1a6d9369 同 arc）。這些是
    # distinctive 策略實體，搭配 conclusion class 才觸發 dedup，不會誤擋。
    "波動率目標": "VOL_TARGETING", "波動率目標策略": "VOL_TARGETING",
    # 2026-07-01 (K1590): English surface forms require the gerund "targeting".
    # The bare nouns "vol target" / "volatility target" collide with sentences
    # like "MNA is a usable portfolio-level vol target" (= a target *variable*
    # for vol research, NOT the vol-targeting strategy) → spurious VOL_TARGETING
    # extraction that falsely arc-blocked K1590 merger-arb. The strategy is
    # always written "targeting"; Chinese 波動率目標 / VT 策略 keep strategy detection.
    "vol targeting": "VOL_TARGETING", "vol-targeting": "VOL_TARGETING",
    "volatility targeting": "VOL_TARGETING", "volatility-targeting": "VOL_TARGETING",
    "vt 策略": "VOL_TARGETING", "vt策略": "VOL_TARGETING",
    "風險平價": "RISK_PARITY", "risk parity": "RISK_PARITY", "risk-parity": "RISK_PARITY",
    # Merger arbitrage / risk arbitrage (2026-07-01 K1590): deal-spread vol is a
    # brand-new arc. The diagnostic uses SPY/HYG/IWM/VIX only as comparison
    # proxies, so the extractor saw no subject entity and collapsed the article
    # into the generic vol bucket → false arc-dup block. Register merger-arb as a
    # distinctive entity so the true subject is visible and future merger-arb
    # pieces dedupe against each other, not against unrelated VT articles.
    "mna": "MERGER_ARB", "併購套利": "MERGER_ARB", "并购套利": "MERGER_ARB",
    "merger arbitrage": "MERGER_ARB", "merger arb": "MERGER_ARB",
    "risk arbitrage": "MERGER_ARB", "risk-arbitrage": "MERGER_ARB",
    "deal spread": "MERGER_ARB", "deal-spread": "MERGER_ARB",
    "deal break": "MERGER_ARB", "deal-break": "MERGER_ARB", "套利價差": "MERGER_ARB",
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
_LEGACY_FUZZY_CONFIRM_ENTITIES = _CORE_ENTITIES | _BROAD_MARKET_ENTITIES | {
    "USD", "RATES", "US_BOND", "LONG_BOND", "MID_BOND",
}
_EVENT_TOPIC_SURFACE: dict[str, str] = {
    "nfp": "NFP", "非農": "NFP", "非農就業": "NFP", "nonfarm": "NFP",
    "payroll": "NFP", "就業報告": "NFP",
    "cpi": "CPI", "消費者物價": "CPI", "通膨數據": "CPI", "inflation data": "CPI",
    "fomc": "FOMC", "fed": "FOMC", "點陣圖": "FOMC",
}
_EVENT_SURFACE_SORTED = sorted(_EVENT_TOPIC_SURFACE, key=len, reverse=True)

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
        "instrument", "instrumental", "sue", "factor etf", "factor model",
        "factor return", "因子 ETF", "因子模型", "因子報酬", "因子投資",
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
        "cross-market",
        "跨市場", "領先", "增量資訊", "incremental information",
        "vix 紅利", "吃不到 vix", "拿同一個 vix",
    ],
    "model_forecast": [
        "garch", "gjr-garch", "egarch", "har-rv", "har rv", "qlike",
        "forecast model", "model comparison", "預測模型",
    ],
}

_GENERIC_MECHANISMS = {"cross_asset_spillover", "model_forecast"}

_NARRATIVE_AXIS_ORDER = [
    "methodology_robustness",
    "product_myth",
    "market_structure",
    "event_window",
    "portfolio_allocation",
    "regime_signal",
    "cross_asset_signal",
    "model_benchmark",
]

_NARRATIVE_AXIS_KEYWORDS: dict[str, list[str]] = {
    "product_myth": [
        "managed futures", "managed-futures", "trend-following", "trend following",
        "crisis alpha", "cta", "dbmf", "kmlm", "免費 etf", "免費ETF",
        "etf proxy", "商品反迷思", "投資商品", "策略 etf", "strategy etf",
    ],
    "market_structure": [
        "ap concentration", "authorized participant", "premium-discount",
        "nav deviation", "short interest", "borrow rate", "squeeze", "liquidity",
        "microstructure", "index reconstitution", "成分股調整", "流動性",
    ],
    "event_window": [
        "event study", "event-study", "event window", "事件研究", "事件窗",
        "announcement", "公告", "財報", "fomc", "cpi", "nfp", "auction",
    ],
    "portfolio_allocation": [
        "hedge ratio", "currency hedge", "currency hedging", "避險比例",
        "risk parity", "asset allocation", "portfolio", "multi-layer",
        "多層次避險", "貨幣避險",
    ],
    "regime_signal": [
        "regime", "stress regime", "tail risk", "drawdown", "var", "expected shortfall",
        "cvar", "crisis", "危機", "壓力期", "尾部", "回撤",
    ],
    "model_benchmark": [
        "garch", "egarch", "gjr", "har-rv", "har rv", "qlike", "model comparison",
        "forecast model", "模型比較", "預測模型",
    ],
    "cross_asset_signal": [
        "cross-asset", "cross asset", "cross-market", "lead-lag", "lead lag",
        "spillover", "incremental information", "增量資訊", "vix 紅利",
        "吃不到 vix", "拿同一個 vix", "跨市場", "領先",
    ],
}

_METHODOLOGY_PAPER_MARKERS = [
    "paper", "paper 三", "paper3", "論文", "reviewer", "投稿", "body.tex",
    "reproduce", "reproducibility", "provenance", "canonical", "table 3",
    "table 6", "mdd retention", "stationary bootstrap", "hln", "k1192",
    "k1376", "k1417", "gemini", "codex review correction",
]

_METHODOLOGY_TEST_MARKERS = [
    "bootstrap", "confidence interval", "ci", "robustness", "穩健性",
    "驗證", "審查", "baseline", "lower bound", "下界", "重現",
    "復現", "source binding", "溯源",
]

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
        "hourly", "每小時", "小時資料", "小時頻率", "小時級", "小時線",
        "一小時", "盤中", "日內",
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


_ZH_EXCLUSION_MARKERS = (
    r"不涉及|不包含|不討論|不分析|不採用|不處理|不研究|禁做|"
    r"不納入|排除在外|(?:本文|本題|本研究)排除"
)
# 「不看／不做」常是正向依存（「不看 VIX 就無法理解 USDC」），不能
# 單獨視為排除。只有句子後面明確 pivot 到另一個主題時才清掉前半句。
_ZH_PIVOT_ONLY_EXCLUSION_MARKERS = r"不看|不做"
_ZH_POSITIVE_PIVOTS = r"而是|改看|改用|改為|聚焦|只看|只討論|轉向|但是|但"
_ZH_EXCLUSION_WITH_PIVOT_RE = re.compile(
    rf"(?:{_ZH_EXCLUSION_MARKERS}|{_ZH_PIVOT_ONLY_EXCLUSION_MARKERS}|不是|並非|非\s+)\s*"
    rf"[^。！？!?；;\n]*?(?:[，,；;]\s*)?(?={_ZH_POSITIVE_PIVOTS})",
    flags=re.IGNORECASE,
)
_ZH_EXCLUSION_CLAUSE_RE = re.compile(
    rf"(?:{_ZH_EXCLUSION_MARKERS}|(?:這|本文|本題|本研究|此文|主題)\s*(?:不是|並非)|非\s+)"
    rf"\s*[^。！？!?；;，,\n]*",
    flags=re.IGNORECASE,
)
_EN_EXCLUSION_HEAD = (
    r"(?:(?:does\s+not|doesn't|do\s+not|don't)\s+"
    r"(?:cover|include|discuss|analy[sz]e|use|involve|focus\s+on)"
    r"|(?:is\s+not|isn't|not)\s+(?:about|focused\s+on)"
    r"|exclud(?:e|es|ed|ing)|without\s+"
    r"(?:covering|including|discussing|analy[sz]ing|using))"
)
_EN_EXCLUSION_WITH_PIVOT_RE = re.compile(
    rf"\b{_EN_EXCLUSION_HEAD}\b\s*[^.!?;\n]*?\b(?:but|instead)\b\s*",
    flags=re.IGNORECASE,
)
_EN_EXCLUSION_CLAUSE_RE = re.compile(
    rf"\b{_EN_EXCLUSION_HEAD}\b\s*[^.!?;\n]*",
    flags=re.IGNORECASE,
)


def strip_exclusion_scopes(text: str) -> str:
    """Remove explicit *exclusion lists* before building an arc signature.

    Topic briefs commonly explain differentiation with clauses such as
    ``不涉及油價、財報、Fed、VIX``.  Treating those rejected subjects as positive
    evidence manufactured entities/mechanisms and made the gate punish the
    briefs that documented their scope most carefully.  This deliberately
    targets explicit scope verbs and ``不是 X，而是 Y`` pivots; ordinary
    statistical negation (for example ``結果不顯著``) is left untouched so the
    conclusion classifier keeps its meaning.
    """
    cleaned = str(text or "")
    cleaned = _ZH_EXCLUSION_WITH_PIVOT_RE.sub("", cleaned)
    cleaned = _EN_EXCLUSION_WITH_PIVOT_RE.sub("", cleaned)
    cleaned = _ZH_EXCLUSION_CLAUSE_RE.sub("", cleaned)
    cleaned = _EN_EXCLUSION_CLAUSE_RE.sub("", cleaned)
    return cleaned


def extract_entities(text: str) -> set[str]:
    """Extract canonical asset entities from title+content text."""
    found: set[str] = set()
    text = strip_exclusion_scopes(text)
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


def _extract_event_topic_entities(text: str) -> set[str]:
    """Extract event-topic labels for legacy fuzzy fallback only.

    NFP/CPI are deliberately not part of the normal arc entity signature because
    broad macro articles often mention several event types in passing. The legacy
    fallback uses title-level event topics as corroboration for old rows whose
    stored arc signature is explicitly missing/invalid.
    """
    found: set[str] = set()
    lower = (text or "").lower()
    for surface in _EVENT_SURFACE_SORTED:
        if surface.isascii():
            if re.search(rf"(?<![a-z0-9]){re.escape(surface)}(?![a-z0-9])", lower):
                found.add(_EVENT_TOPIC_SURFACE[surface])
        else:
            if surface in (text or ""):
                found.add(_EVENT_TOPIC_SURFACE[surface])
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


def classify_narrative_axis(text: str) -> str:
    """Classify the reader-facing narrative axis.

    Mechanism labels answer "what statistical channel is used"; this axis
    answers "what kind of story is the reader being offered". The distinction
    matters for release dedup: a paper-methodology robustness note and an ETF
    product-myth article can share SPY/VIX/momentum/null keywords while clearly
    not being the same reader-facing arc.
    """
    raw = text or ""
    lower = raw.lower()
    has_paper_marker = any(marker in lower for marker in _METHODOLOGY_PAPER_MARKERS)
    has_method_marker = any(marker in lower for marker in _METHODOLOGY_TEST_MARKERS)
    if has_paper_marker and has_method_marker:
        return "methodology_robustness"

    for axis in _NARRATIVE_AXIS_ORDER:
        if axis == "methodology_robustness":
            continue
        if any(keyword.lower() in lower for keyword in _NARRATIVE_AXIS_KEYWORDS.get(axis, [])):
            return axis
    return "unspecified"


def _entity_groups_for_axis(entities: set[str], narrative_axis: str) -> dict[str, list[str]]:
    """Split entities into reader-facing vs paper-methodology scope.

    The same token (e.g. SPY/VIX/momentum) has a different dedup meaning inside
    a paper reproducibility article than inside an ETF product article. Persisting
    both groups makes this distinction auditable and lets v3 avoid cross-scope
    collisions without losing the original extracted entities.
    """
    if narrative_axis == "methodology_robustness":
        return {
            "reader_narrative": [],
            "paper_methodology": sorted(entities),
        }
    return {
        "reader_narrative": sorted(entities),
        "paper_methodology": [],
    }


def arc_signature(title: str, content: str | None = "") -> dict:
    """Return the metadata schema used by the arc-dedup gate.

    The schema is safe to persist in feed item details. Callers should still be
    able to recompute it from title/content because historical articles may not
    have been backfilled yet.
    """
    text = strip_exclusion_scopes(f"{title or ''}\n{content or ''}")
    entities = extract_entities(text)
    narrative_axis = classify_narrative_axis(text)
    return {
        "schema_version": ARC_SIGNATURE_SCHEMA_VERSION,
        "entities": sorted(entities),
        "entity_groups": _entity_groups_for_axis(entities, narrative_axis),
        "conclusion_class": classify_conclusion(text),
        "narrative_axis": narrative_axis,
        "mechanisms": sorted(classify_mechanisms(text)),
        "time_horizon": classify_time_horizon(text),
    }


def _feed_item_text(item: dict) -> str:
    """Best-effort text for historical feed items that pre-date arc signatures."""
    raw_tags = item.get("tags")
    tags = (
        " ".join(str(t) for t in raw_tags)
        if isinstance(raw_tags, (list, tuple, set))
        else ""
    )
    return "\n".join(
        part for part in (
            str(item.get("title") or ""),
            str(item.get("content") or item.get("description") or ""),
            tags,
        )
        if part
    )


def arc_signature_from_feed_item(item: dict) -> dict:
    """Recompute a signature from the canonical feed-item text surface.

    Runtime stale-schema reads, migrations, and new Publisher writes must use
    the same title/content/tags inputs.  Keeping this as one public helper avoids
    a rollout where a backfilled v4 row differs from the v4 signature that the
    matcher computed immediately before the backfill.
    """
    return arc_signature("", _feed_item_text(item))


def _has_valid_stored_signature(item: dict) -> bool:
    details = item.get("details") or {}
    sig = details.get("arc_signature") if isinstance(details, dict) else None
    return (
        isinstance(sig, dict)
        and sig.get("schema_version") == ARC_SIGNATURE_SCHEMA_VERSION
        and isinstance(sig.get("entities"), list)
        and isinstance(sig.get("conclusion_class"), str)
        and isinstance(sig.get("narrative_axis"), str)
        and isinstance(sig.get("entity_groups"), dict)
    )


def _has_legacy_arc_signature_marker(item: dict) -> bool:
    """True for explicit legacy/invalid arc_signature metadata.

    Missing details on synthetic callers/tests should use the normal recomputed
    signature path. The fuzzy fallback is intentionally limited to articles that
    carry an arc_signature field but not a valid current signature, especially
    historical ``arc_signature=None`` rows.
    """
    details = item.get("details") or {}
    if not isinstance(details, dict) or "arc_signature" not in details:
        return False
    sig = details.get("arc_signature")
    if _has_valid_stored_signature(item):
        return False
    # A previous, structurally valid schema is recomputed from article text; it
    # is stale vocabulary, not the title-only legacy hole this fuzzy fallback
    # exists for.  Treating every v3 row as legacy after the v4 bump would turn
    # on a second, looser matcher for 139 production articles at once.
    if isinstance(sig, dict) and re.fullmatch(
        r"arc_dedup_v\d+", str(sig.get("schema_version") or "")
    ):
        return False
    return True


def _signature_from_feed_item(item: dict) -> dict:
    details = item.get("details") or {}
    sig = details.get("arc_signature") if isinstance(details, dict) else None
    if isinstance(sig, dict):
        entities = sig.get("entities")
        conclusion = sig.get("conclusion_class")
        narrative_axis = sig.get("narrative_axis")
        mechanisms = sig.get("mechanisms")
        horizon = sig.get("time_horizon")
        entity_groups = sig.get("entity_groups")
        if (
            sig.get("schema_version") == ARC_SIGNATURE_SCHEMA_VERSION
            and isinstance(entities, list)
            and isinstance(conclusion, str)
            and isinstance(narrative_axis, str)
            and isinstance(entity_groups, dict)
        ):
            return {
                "schema_version": ARC_SIGNATURE_SCHEMA_VERSION,
                "entities": sorted(str(e) for e in entities),
                "entity_groups": {
                    "reader_narrative": sorted(
                        str(e) for e in _axis_values(entity_groups.get("reader_narrative"))
                        if e != "unspecified"
                    ),
                    "paper_methodology": sorted(
                        str(e) for e in _axis_values(entity_groups.get("paper_methodology"))
                        if e != "unspecified"
                    ),
                },
                "conclusion_class": conclusion,
                "narrative_axis": narrative_axis,
                "mechanisms": sorted(_axis_values(mechanisms)),
                "time_horizon": str(horizon or "unspecified"),
            }
    return arc_signature_from_feed_item(item)


def _normalize_ref(raw: str) -> str:
    """Canonicalize a K-id ref: 'k1054' / 'K1054' / 'k1054b' → 'K1054' / 'K1054b'."""
    s = str(raw or "").strip()
    if re.match(r"^[Kk]\d", s):
        return "K" + s[1:]
    return s.upper()


def _refs_from_feed_item(item: dict) -> set[str]:
    """Extract canonical experiment_refs (K-ids) from a feed item.

    Reads details.experiment_refs / experiment_ids, then falls back to scanning
    the title + content for K-id tokens (older articles pre-date the metadata
    field). Used by the same-experiment-refs gate (vuln 2 / ghost recycle).
    """
    refs: set[str] = set()
    details = item.get("details") or {}
    if isinstance(details, dict):
        for key in ("experiment_refs", "experiment_ids"):
            raw = details.get(key) or []
            if isinstance(raw, (list, tuple, set)):
                for r in raw:
                    nr = _normalize_ref(r)
                    if nr:
                        refs.add(nr)
    text = f"{item.get('title', '')} {item.get('content') or item.get('description') or ''}"
    for m in re.findall(r"[Kk]\d{2,}[a-z]?", text):
        refs.add(_normalize_ref(m))
    return refs


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


def _narrative_axes_compatible(new_axis: str, old_axis: str) -> bool:
    if new_axis == "unspecified" or old_axis == "unspecified":
        return True
    return new_axis == old_axis


def _axis_mismatch_raw_entity_backstop(new_raw_ents: set[str], old_raw_ents: set[str]) -> bool:
    """Keep a broad-overlap backstop even when narrative axes differ.

    Task constraint (2026-06-24): v3 must not become "all different axes are
    automatically not duplicates". If two pieces share five or more raw entities,
    keep evaluating them as a possible duplicate despite an axis mismatch.
    """
    return len(new_raw_ents & old_raw_ents) >= 5


def _entities_for_matching(sig: dict) -> set[str]:
    groups = sig.get("entity_groups")
    axis = str(sig.get("narrative_axis") or "unspecified")
    if isinstance(groups, dict):
        key = "paper_methodology" if axis == "methodology_robustness" else "reader_narrative"
        vals = groups.get(key)
        if isinstance(vals, list):
            return {str(v) for v in vals}
    return set(sig.get("entities") or [])


def arc_match_anchors(sig: dict, refs: set[str] | list[str] | None = None) -> dict:
    """The signals `find_arc_duplicates` can actually anchor a comparison on.

    Single source of truth for "could the arc gate even look?", deliberately
    living in the module that DEFINES what an anchor is. The 2026-07-13 fix put
    its own, narrower version of this test inside scripts/check_arc_dedup.py;
    the two definitions drifted apart within a day (see `is_arc_anchorless`).

    Anchors, mirroring the matcher exactly:
      * distinctive entity — every match path runs through
        `_is_significant_overlap`, which subtracts `_CORE_ENTITIES`
        (US_EQUITY / VIX / TW_EQUITY). A core-only entity list can therefore
        never produce a significant overlap.
      * experiment ref — the same-K short-circuit.

    Mechanisms are deliberately NOT an anchor. They can corroborate a soft
    near-miss, but never make a hard match without an entity/ref anchor.
    """
    ents = _entities_for_matching(sig)
    ref_set = {_normalize_ref(r) for r in (refs or []) if str(r or "").strip()}
    return {
        "distinctive_entities": sorted(ents - _CORE_ENTITIES),
        "experiment_refs": sorted(ref_set),
    }


def is_arc_anchorless(sig: dict, refs: set[str] | list[str] | None = None) -> bool:
    """True when `find_arc_duplicates` has nothing to anchor an arc match on.

    Its `[]` then means "I could not look", NOT "I looked and it is clean", and
    no caller may render it as `clean`.

    Two incidents, one day apart, same theme, same victims:

      2026-07-13 — entities=[]. The trending topic 「AI營收不如預期？科技股選擇權
      偏斜率」 carried no K-id and no ticker, and passed with a green tick while
      four live articles already told that exact story. Fix defined thin as
      `not entities and not refs`, in the CLI.

      2026-07-14 — entities=[US_EQUITY]. The same theme returned as 「AI變現挑戰：
      從期權波動率解析科技巨頭的資本定價分歧」. entities was non-empty, so `thin`
      was False and the CLI again printed `clean` — against the very same
      articles (mile_8a5e80b0 / mile_49616ac2 / mile_622a2b73 / mile_f5f4cb43).

    A core-only entity list is exactly as anchor-less as an empty one, and only
    the matcher knows that. Hence this predicate lives here, not at the call
    site. The one path still open on an anchor-less piece is the legacy
    near-identical-title check, which catches a byte-recycle but cannot see a
    same-arc piece written fresh — that is a recycle detector, not an arc gate.

    Callers stay fail-OPEN (`.claude/rules/dedup-gate-audit.md`): anchor-less is
    not evidence of duplication. It just must never be reported as clean.
    """
    anchors = arc_match_anchors(sig, refs)
    return not anchors["distinctive_entities"] and not anchors["experiment_refs"]


def _title_tokens(title: str) -> set[str]:
    """Tokenize a title for Jaccard similarity.

    Mixed zh-Hant/ASCII: split on whitespace/punctuation for ASCII words, and
    emit individual CJK characters as tokens. Drops 1-char ASCII noise. This is
    deliberately coarse — it only needs to separate "near-identical title"
    (ghost-recycle: bb520db8 vs c481c8cf) from "unrelated title".
    """
    if not title:
        return set()
    lower = title.lower()
    tokens: set[str] = set()
    # ASCII word runs (>=2 chars, e.g. "spy", "garch", "vix")
    for m in re.findall(r"[a-z0-9]{2,}", lower):
        tokens.add(m)
    # Individual CJK characters
    for ch in re.findall(r"[一-鿿]", title):
        tokens.add(ch)
    return tokens


def _title_jaccard(a: str, b: str) -> float:
    """Jaccard overlap of title tokens. 0.0 when either is empty."""
    ta, tb = _title_tokens(a), _title_tokens(b)
    if not ta or not tb:
        return 0.0
    inter = len(ta & tb)
    union = len(ta | tb)
    return inter / union if union else 0.0


def _legacy_title_entity_fuzzy_dup(
    new_raw_ents: set[str],
    old_raw_ents: set[str],
    new_title: str,
    old_title: str,
    shared_refs: set[str],
) -> bool:
    """Conservative fallback for feed items with no stored v3 arc signature.

    Historical articles can be too thin to reconstruct a full conclusion/mechanism
    signature from content, especially when they only carry a title, tags, or a
    short description. Use this only for legacy missing-signature items, and only
    when a concrete event/topic entity is corroborated by a market entity or an
    explicit shared K-ref. This closes the NFP T+0 stale-duplicate blind spot
    without turning generic fuzzy similarity into a broad hard block.
    """
    shared = new_raw_ents & old_raw_ents
    if not shared:
        return False
    distinctive_shared = shared - _CORE_ENTITIES
    title_sim = _title_jaccard(new_title, old_title)
    if shared_refs and (distinctive_shared or title_sim >= 0.18):
        return True
    if title_sim >= 0.35 and _is_significant_overlap(new_raw_ents, old_raw_ents):
        return True
    old_title_ents = extract_entities(old_title)
    new_title_ents = extract_entities(new_title)
    shared_title_events = (
        _extract_event_topic_entities(old_title)
        & _extract_event_topic_entities(new_title)
    )
    if (
        shared_title_events
        and (shared & _LEGACY_FUZZY_CONFIRM_ENTITIES)
        and (old_title_ents or new_title_ents)
    ):
        return True
    return False


# Title-token Jaccard at/above this counts a descriptive pair as the same
# recycled article. bb520db8 ("波動率模型換一把尺子量還是贏，這才叫真的贏")
# vs c481c8cf ("同一個模型，換一把尺子量還是贏，這才叫真的贏") share almost
# every CJK token → ~0.8. Genuinely different descriptive articles share far
# fewer tokens. Kept high to avoid false positives on the descriptive path.
_DESCRIPTIVE_TITLE_JACCARD = 0.55


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
        (single,) = tuple(distinctive_overlap)
        # A broad-market proxy (IWM/NASDAQ/bonds) shared alongside VIX is still a
        # generic "US market" overlap, not a distinctive topic anchor. Requiring
        # the VIX shortcut only for genuinely narrow entities prevents a
        # multi-proxy diagnostic from matching any unrelated descriptive piece
        # that happens to reference the same broad proxies. (2026-07-01 K1590:
        # merger-arb diagnostic shared only US_SMALLCAP+VIX with unrelated
        # AI-capex / regulatory-flow articles.)
        if "VIX" in overlap and single not in _BROAD_MARKET_ENTITIES:
            return True
        return new_distinctive == old_distinctive == distinctive_overlap
    return False


def _arc_item_audience(item: dict) -> str:
    audience = item.get("audience") or (item.get("details") or {}).get("audience")
    if isinstance(audience, str) and audience.strip():
        return audience.strip().lower()
    return "uncategorized"


_SERIES_REGISTRY_PATH = (
    Path(__file__).resolve().parents[3] / "config" / "article_series.json"
)
_SERIES_SPEC_CACHE: list[tuple[str, str, dict]] | None = None  # (prefix, registry_key, spec)


def _series_specs() -> list[tuple[str, str, dict]]:
    """Registered title_prefix series specs (config/article_series.json is the SoT)."""
    global _SERIES_SPEC_CACHE
    if _SERIES_SPEC_CACHE is None:
        specs: list[tuple[str, str, dict]] = []
        try:
            raw = json.loads(_SERIES_REGISTRY_PATH.read_text(encoding="utf-8"))
            for key, spec in (raw.get("series") or {}).items():
                prefix = str(spec.get("prefix") or "").strip()
                if prefix and spec.get("branding") == "title_prefix":
                    specs.append((prefix, str(key), spec))
        except Exception as exc:
            LOG.warning(
                "arc_dedup series registry unreadable path=%s (%s: %s) — series exemption off",
                _SERIES_REGISTRY_PATH, type(exc).__name__, exc,
            )
        _SERIES_SPEC_CACHE = specs
    return _SERIES_SPEC_CACHE


def _series_prefixes() -> list[str]:
    return [prefix for prefix, _key, _spec in _series_specs()]


def series_spec_for_title(title: str) -> tuple[str, dict] | None:
    """(registry_key, spec) of the registered series this title belongs to, else None."""
    t = (title or "").strip()
    for prefix, key, spec in _series_specs():
        if t.startswith(prefix):
            return key, spec
        name_part = prefix.split(" ", 1)[-1]
        if name_part and t.startswith(name_part):
            return key, spec
    return None


def _series_of(title: str) -> str | None:
    t = (title or "").strip()
    for prefix in _series_prefixes():
        if t.startswith(prefix):
            return prefix
        # 前綴的 emoji 可能被去掉/換掉，退回比對「系列名｜」部分
        name_part = prefix.split(" ", 1)[-1]
        if name_part and t.startswith(name_part):
            return prefix
    return None


def _same_series_different_episode(
    new_title: str, old_title: str, shared_refs: set[str]
) -> bool:
    """Two chapters of the SAME registered series are not duplicates of each other.

    Boss directive 2026-07-13 (Telegram msg 662): a multi-part series published in
    one week is by design a sequence of chapters over one entity family with one
    conclusion family — exactly the shape arc dedup is built to catch. Blocking a
    series is a false positive. But we do NOT open a blanket hole: the exemption
    only applies when the two episode titles are genuinely different AND they do
    not rest on the same experiment refs (which is what a real re-run looks like).
    """
    series = _series_of(new_title)
    if not series or series != _series_of(old_title):
        return False
    if shared_refs:
        return False
    return _title_jaccard(new_title, old_title) < 0.6


def find_arc_duplicates(
    title: str,
    content: str,
    feed: list[dict],
    days: int = 90,
    max_scan: int | None = None,
    new_refs: set[str] | list[str] | None = None,
    audience: str | None = None,
    include_fuzzy: bool = False,
) -> list[dict]:
    """Return feed articles that are narrative-arc duplicates of the new piece.

    Arc duplicate = significant entity overlap (incl. >=1 distinctive entity)
    AND same conclusion class AND compatible mechanism/horizon, within `days`.
    Direction-agnostic by design.

    `new_refs`: optional experiment_refs (K-ids) for the NEW article. Used by
    the descriptive-mode gate and the same-experiment-refs short-circuit (vuln 2
    of the 2026-06-19 K1054 ghost-recycle incident: mile_bb520db8 byte-for-byte
    re-published mile_c481c8cf, both K1054, both 'descriptive', neither blocked).

    `audience`: when the caller knows which audience the new piece is FOR, the
    corpus is narrowed to that audience. Publishing a research write-up and a
    general-reader write-up of the same K is the product design (74 K-ids carry
    both audiences live), so judging a general twin against its research sibling
    is a false positive — and a permanent one, since the sibling stays published
    forever. That mis-scoping froze the release pool for 30+ consecutive fires
    (2026-07-11) and still skips general candidates at task refill. Callers that
    genuinely span audiences (the publish-time warn) leave this None and keep the
    old cross-audience behaviour.

    `include_fuzzy`: additionally return descriptive entity+mechanism near
    misses.  They carry ``match_level="near_miss"`` and must never be treated as
    hard duplicates.  The default preserves the historical list API; callers
    that render a verdict should opt in so the evidence stays visible.
    """
    new_sig = arc_signature(title, content)
    new_ents = _entities_for_matching(new_sig)
    new_raw_ents = set(new_sig.get("entities") or [])
    new_cls = str(new_sig["conclusion_class"])
    new_axis = str(new_sig.get("narrative_axis") or "unspecified")
    new_mechanisms = _axis_values(new_sig.get("mechanisms"))
    new_horizon = str(new_sig.get("time_horizon") or "unspecified")
    new_ref_set = {_normalize_ref(r) for r in (new_refs or []) if str(r or "").strip()}
    # Also harvest K-ids embedded in the new title/content (drafts often carry
    # the K-id in the title even when no explicit refs are passed).
    for m in re.findall(r"[Kk]\d{2,}[a-z]?", f"{title or ''} {content or ''}"):
        new_ref_set.add(_normalize_ref(m))

    # "descriptive" is the fallback class meaning "no identifiable conclusion".
    # We do NOT match the arc on descriptive alone (2026-06-14: SpaceX IPO
    # mile_6159728d was falsely blocked against big-tech-vol mile_312204b2 on
    # incidental USD+US_EQUITY overlap, both descriptive). BUT returning [] for
    # every descriptive article opened the 2026-06-19 ghost-recycle hole: a
    # model-robustness piece whose conclusion wording isn't in _CONCLUSION_KEYWORDS
    # falls to 'descriptive' and bypasses arc dedup entirely. So on the
    # descriptive path we apply a STRICTER, separate test (`_descriptive_dup`):
    # require a strong same-article signal (near-identical title or shared
    # experiment_ref). Entity+mechanism alone is advisory when include_fuzzy=True.
    descriptive_mode = (new_cls == "descriptive")
    # With no entities AND no refs there is nothing to anchor a match on.
    if not new_ents and not new_ref_set:
        return []

    want_audience = str(audience or "").strip().lower() or None

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    dups: list[dict] = []
    recent = sorted(
        feed, key=lambda x: x.get("published_at") or x.get("created_at", ""), reverse=True
    )
    if max_scan is not None:
        recent = recent[:max_scan]
    for existing in recent:
        if existing.get("status") in ("unpublished", "retracted"):
            continue
        if want_audience:
            existing_audience = _arc_item_audience(existing)
            # Only an audience we can positively identify as DIFFERENT is out of
            # scope. Untagged legacy articles (75 live, audience=null) stay in the
            # corpus — "unknown" is not evidence of a different audience, and
            # dropping them would quietly weaken the gate.
            if existing_audience not in (want_audience, "uncategorized"):
                continue
        ts_raw = existing.get("published_at") or existing.get("created_at") or ""
        try:
            from dateutil.parser import parse as dtparse

            if dtparse(ts_raw).astimezone(timezone.utc) < cutoff:
                continue
        except Exception as exc:
            # Unparseable timestamp -> keep candidate, but surface bad feed metadata.
            LOG.warning(
                "arc_dedup keeping item with invalid timestamp id=%r timestamp=%r (%s: %s)",
                existing.get("id"),
                ts_raw,
                type(exc).__name__,
                exc,
            )
        ex_sig = _signature_from_feed_item(existing)
        legacy_missing_sig = _has_legacy_arc_signature_marker(existing)
        ex_ents = _entities_for_matching(ex_sig)
        ex_raw_ents = set(ex_sig.get("entities") or [])
        ex_cls = str(ex_sig["conclusion_class"])
        ex_axis = str(ex_sig.get("narrative_axis") or "unspecified")
        ex_mechanisms = _axis_values(ex_sig.get("mechanisms"))
        ex_horizon = str(ex_sig.get("time_horizon") or "unspecified")
        ex_refs = _refs_from_feed_item(existing)
        shared_refs = new_ref_set & ex_refs
        if _same_series_different_episode(title, existing.get("title", ""), shared_refs):
            LOG.info(
                "arc_dedup series exemption: %r vs %r (same registered series, different episode)",
                title, existing.get("title", ""),
            )
            continue
        axis_raw_backstop = False
        legacy_fuzzy_match = False
        descriptive_fuzzy_match = False

        if descriptive_mode:
            # Stricter descriptive-path test (vuln 1 fix). Avoids the SpaceX
            # false positive (no shared ref, low title overlap, different
            # mechanism sets) while catching the K1054 ghost recycle (shared
            # ref K1054 AND ~identical title).
            match = _descriptive_dup(
                new_ents, ex_ents,
                title, existing.get("title", ""),
                shared_refs,
            )
            if not match:
                legacy_fuzzy_match = (
                    legacy_missing_sig
                    and _legacy_title_entity_fuzzy_dup(
                        new_raw_ents, ex_raw_ents,
                        title, existing.get("title", ""),
                        shared_refs,
                    )
                )
                if not legacy_fuzzy_match:
                    specific_shared = (
                        (new_mechanisms & ex_mechanisms)
                        - _GENERIC_MECHANISMS
                        - {"unspecified"}
                    )
                    descriptive_fuzzy_match = bool(
                        include_fuzzy
                        and _is_significant_overlap(new_ents, ex_ents)
                        and specific_shared
                    )
                    if not descriptive_fuzzy_match:
                        continue
        else:
            axes_compatible = _narrative_axes_compatible(new_axis, ex_axis)
            axis_raw_backstop = (
                not axes_compatible
                and _axis_mismatch_raw_entity_backstop(new_raw_ents, ex_raw_ents)
            )
            significant_overlap = _is_significant_overlap(new_ents, ex_ents) or (
                axis_raw_backstop and _is_significant_overlap(new_raw_ents, ex_raw_ents)
            )
            if not significant_overlap:
                # Same explicit experiment_ref is itself a duplicate signal even
                # when the surface entities are all core (US_EQUITY/VIX). Without
                # this, a recycled K-article with only core entities would slip
                # through the entity gate. Require same conclusion class so a
                # genuine follow-up with a different verdict is still allowed.
                legacy_fuzzy_match = (
                    legacy_missing_sig
                    and _legacy_title_entity_fuzzy_dup(
                        new_raw_ents, ex_raw_ents,
                        title, existing.get("title", ""),
                        shared_refs,
                    )
                )
                if not ((shared_refs and ex_cls == new_cls) or legacy_fuzzy_match):
                    continue
            else:
                legacy_fuzzy_match = (
                    legacy_missing_sig
                    and _legacy_title_entity_fuzzy_dup(
                        new_raw_ents, ex_raw_ents,
                        title, existing.get("title", ""),
                        shared_refs,
                    )
                )
            if ex_cls != new_cls and not legacy_fuzzy_match:
                continue
            if not axes_compatible and not axis_raw_backstop and not legacy_fuzzy_match:
                continue
            if (
                not _mechanisms_compatible(new_mechanisms, ex_mechanisms)
                and not legacy_fuzzy_match
            ):
                continue
            if (
                not _horizons_compatible(new_horizon, ex_horizon)
                and not legacy_fuzzy_match
            ):
                continue
        dups.append(
            {
                "id": existing.get("id", "?"),
                "title": existing.get("title", "?"),
                "shared_entities": sorted(
                    (new_raw_ents & ex_raw_ents)
                    if axis_raw_backstop
                    else (new_ents & ex_ents)
                ),
                "conclusion_class": new_cls,
                "narrative_axis": new_axis,
                "existing_narrative_axis": ex_axis,
                "shared_mechanisms": sorted(new_mechanisms & ex_mechanisms),
                "shared_legacy_event_topics": (
                    sorted(
                        _extract_event_topic_entities(title)
                        & _extract_event_topic_entities(existing.get("title", ""))
                    )
                    if legacy_fuzzy_match
                    else []
                ),
                "new_mechanisms": sorted(new_mechanisms),
                "existing_mechanisms": sorted(ex_mechanisms),
                "time_horizon": new_horizon,
                "existing_time_horizon": ex_horizon,
                "shared_experiment_refs": sorted(shared_refs),
                "match_level": (
                    "near_miss" if descriptive_fuzzy_match else "duplicate"
                ),
                "match_reason": (
                    "legacy_title_entity_fuzzy"
                    if legacy_fuzzy_match
                    else (
                        "descriptive_fuzzy_mechanism"
                        if descriptive_fuzzy_match
                        else (
                            "descriptive_strict"
                            if descriptive_mode
                            else (
                                "shared_experiment_ref"
                                if (
                                    shared_refs
                                    and not _is_significant_overlap(new_ents, ex_ents)
                                )
                                else "entity_conclusion_arc"
                            )
                        )
                    )
                ),
            }
        )
    return dups


def is_arc_near_miss(match: dict) -> bool:
    """True for advisory evidence that must never become a hard arc block."""
    return (
        str(match.get("match_level") or "") == "near_miss"
        or str(match.get("match_reason") or "") in ARC_NEAR_MISS_REASONS
    )


def _descriptive_dup(
    new_ents: set[str],
    old_ents: set[str],
    new_title: str,
    old_title: str,
    shared_refs: set[str],
) -> bool:
    """Stricter duplicate test for the 'descriptive' (unclassifiable) path.

    'descriptive' means we could not read a conclusion arc, so we must NOT block
    on entity+conclusion alone (that produced the SpaceX false positive). A
    descriptive pair is a duplicate ONLY when there is a strong same-article
    signal:

      (A) shared experiment_ref (same K-id) AND (entity overlap OR near title) —
          this is the K1054 ghost-recycle case (same K, ~identical title); OR
      (B) any entity overlap AND near-identical title (token Jaccard
          >= threshold) — catches recycled descriptive pieces with no ref; OR
    SpaceX (mile_6159728d) vs big-tech-vol (mile_312204b2): no shared ref,
    distinctive entity overlap is only {USD} (a core/incidental ratio), titles
    share few tokens → neither (A) nor (B) fires → NOT blocked. ✓
    """
    title_sim = _title_jaccard(new_title, old_title)
    near_title = title_sim >= _DESCRIPTIVE_TITLE_JACCARD

    # (A) Same experiment_ref is the most robust signal. Pair it with a weak
    # corroboration (any entity overlap or a near-identical title) so a
    # legitimately differentiated follow-up on the same K (different title AND
    # different assets) is not blocked.
    if shared_refs and (bool(new_ents & old_ents) or near_title):
        return True
    # (B) recycled descriptive piece, no ref, near-identical title. A title-token
    # Jaccard >= _DESCRIPTIVE_TITLE_JACCARD (0.55) is itself a strong recycle
    # signal — require only some entity overlap (even a core entity) so two
    # genuinely unrelated titles that happen to score high without sharing any
    # asset don't collide. The ghost case (bb520db8/c481c8cf) shares
    # {US_EQUITY, VIX} with a ~0.8 title overlap.
    if near_title and bool(new_ents & old_ents):
        return True
    # A shared mechanism without a shared K or near-identical title is fuzzy,
    # not duplicate evidence.  The removed mechanism-only branch blocked a real
    # FOMC preview against an NFP article and a generic VIX explainer.
    return False


# --- Shared dedup primitives (moved from scripts/check_arc_dedup.py) --------
# These were library-grade all along but lived in a CLI script, so the task
# GENERATORS (refill_reader_facing_pool / event_jobs) could not reuse them and
# shipped duplicate topics instead. Kept here as the single implementation;
# scripts/check_arc_dedup.py re-imports them.

# Feed statuses that are not reader-visible; they cannot constitute coverage.
DEAD_STATUSES = ("unpublished", "retracted")

LEXICAL_HINT_THRESHOLD = 0.18
LEXICAL_HINT_LIMIT = 5


def tokenize(text: str) -> set[str]:
    """Latin words + CJK character bigrams — a script-agnostic bag of tokens."""
    toks: set[str] = set()
    word = ""
    cjk_run = ""

    def flush_cjk() -> None:
        for i in range(len(cjk_run) - 1):
            toks.add(cjk_run[i : i + 2])

    for ch in text.lower():
        if ch.isascii() and ch.isalnum():
            word += ch
            flush_cjk()
            cjk_run = ""
        elif "一" <= ch <= "鿿":
            cjk_run += ch
            if len(word) >= 3:
                toks.add(word)
            word = ""
        else:
            if len(word) >= 3:
                toks.add(word)
            word = ""
            flush_cjk()
            cjk_run = ""
    if len(word) >= 3:
        toks.add(word)
    flush_cjk()
    return toks


def find_lexical_hints(title: str, text: str, feed: list[dict]) -> list[dict]:
    """Live articles whose titles share a lot of surface vocabulary with this one.

    ADVISORY ONLY — never a block. 2026-07-14 calibration on the real incident
    proved title-only overlap cannot discriminate: the incident title scored
    0.25 against a true dup and 0.25 against an unrelated article. Use
    `theme_saturation` for an actual verdict.
    """
    probe = tokenize(f"{title}\n{text[:400]}")
    if not probe:
        return []
    hits: list[dict] = []
    for item in feed:
        if item.get("status") in DEAD_STATUSES:
            continue
        cand_title = str(item.get("title") or "")
        cand = tokenize(cand_title)
        if not cand:
            continue
        shared = probe & cand
        score = len(shared) / min(len(probe), len(cand))
        if score >= LEXICAL_HINT_THRESHOLD:
            hits.append(
                {
                    "id": item.get("id", "?"),
                    "title": cand_title,
                    "status": item.get("status", "?"),
                    "audience": _arc_item_audience(item),
                    "published_at": (item.get("published_at") or item.get("created_at") or "")[:10],
                    "score": round(score, 3),
                }
            )
    hits.sort(key=lambda h: h["score"], reverse=True)
    return hits[:LEXICAL_HINT_LIMIT]


def find_k_coverage(k_id: str, feed: list[dict], audience: str | None) -> list[dict]:
    """Live feed articles already carrying this K-id (optionally same audience).

    Exact-match gate — no text classifier in the path.
    """
    want = _normalize_ref(k_id)
    want_audience = str(audience or "").strip().lower() or None
    hits: list[dict] = []
    for item in feed:
        if item.get("status") in DEAD_STATUSES:
            continue
        if want not in _refs_from_feed_item(item):
            continue
        item_audience = _arc_item_audience(item)
        if want_audience and item_audience not in (want_audience, "uncategorized"):
            continue
        hits.append(
            {
                "id": item.get("id", "?"),
                "title": item.get("title", "?"),
                "status": item.get("status", "?"),
                "audience": item_audience,
                "published_at": (item.get("published_at") or item.get("created_at") or "")[:10],
            }
        )
    return hits


# --- Theme saturation ------------------------------------------------------
# Why this exists (2026-07-13 trending incident, root-caused 2026-07-14):
#
# The arc gate is ENTITY-ANCHORED. Measured on the five same-story articles of
# the incident (mile_f5f4cb43 / mile_8a5e80b0 / mile_0941e2f0 / mile_49616ac2 /
# mile_622a2b73), `extract_entities` mapped ONE underlying subject (AI capex ->
# tech/semi option skew) onto five near-disjoint entity sets -- {USD},
# {NASDAQ,USD}, {SEMIS,VIX}, {US_EQUITY}, {USD} -- and every conclusion class
# collapsed to "descriptive". Consequence, verified: those five articles do not
# arc-match EACH OTHER (0 of 10 pairs). So the arc gate could never have caught
# this family, at publish time or at generation time. Wiring find_arc_duplicates
# into the generators was necessary but NOT sufficient.
#
# The signal that does survive is thematic vocabulary. Rather than pairwise
# similarity (proved useless above), we ask a COUNT question:
#
#   "How many live articles in the window already crowd this topic's theme?"
#
# Distinctive terms only: a term appearing in >12% of the corpus is ambient
# platform vocabulary (波動率 / 市場), not a theme marker, so it is dropped --
# a crude IDF filter.
#
# Calibrated 2026-07-14 against the real 90-day live corpus (831 live articles),
# measured through THIS function (not a reimplementation):
#     incident (AI/tech skew) ............ 12    -> block  (canonical probe)
#     TAIFEX night-session order flow .....   9  -> block  (5 prior pieces; real dup)
#     NFP/DXY event preview ...............   3  -> pass
#     FOMC event preview ..................   8  -> warn  (recurring event-window)
#     stablecoin depeg contagion .......... 0-2  -> pass
#     EU carbon/ETS seasonality ...........   0  -> pass
#
# Threshold 5 preserves a clear labelled-probe gap: the canonical incident is
# 12 while the NFP control is 3. FOMC is intentionally evaluated separately:
# its recurring event-window theme score is advisory even above the threshold,
# while any exact K/high-confidence arc match still blocks. The daily live-corpus
# sentinel warns if these calibrated verdicts drift. The asymmetry is deliberate:
# at GENERATION
# time a false positive costs one swapped topic; a false negative costs a duplicate
# article. Regression-pinned in tests/test_topic_dedup_at_generation.py so corpus
# drift cannot silently move it.

THEME_SATURATION_THRESHOLD = 5
THEME_TERM_COUNT = 6
THEME_MIN_TERMS = 3
THEME_MIN_SHARED = 3
THEME_AMBIENT_DF_RATIO = 0.12
# Floor for the ambient-vocabulary cutoff. Without it a SMALL corpus silently
# disables the gate: at N=9 the ratio cutoff is 1.08, so every term appearing in
# >=2 articles is discarded as "ambient", the theme comes out empty, and the gate
# no-ops while reporting saturation 0 (indistinguishable from "clean"). A silent
# no-op is the exact failure class this module exists to kill. On the production
# corpus (N=831 live/90d) the ratio gives 99.7 and dominates the floor, so this
# does not move the calibrated numbers -- it only makes small corpora behave.
THEME_AMBIENT_DF_MIN = 3

# Generator metadata and generic writing verbs are not topic evidence.  The
# six-term theme vector is intentionally tiny, so one leaked task-type prefix
# or boilerplate verb can displace the actual subject and flip the verdict.
_THEME_TASK_PREFIXES = (
    "trending_repost", "event_article", "daily_article", "daily_digest",
    "member_qa", "research_article", "paper_review",
)
_THEME_PROBE_PREFIX_RE = re.compile(
    rf"^\s*(?:\[(?:{'|'.join(_THEME_TASK_PREFIXES)})\]\s*)+",
    flags=re.IGNORECASE,
)
_THEME_GENERIC_PHRASES = (
    "量化角度", "歷史分析", "historical analysis", "quantitative angle",
    # Instrument/measurement boilerplate is not a subject. On the real 831-item
    # corpus these six high-DF tokens displaced NFP/DXY from a six-slot vector
    # and falsely saturated a new payroll preview against eight AI/earnings
    # option articles.
    "隱含波動率", "隐含波动率", "隱含波動", "隐含波动",
    "選擇權", "选择权", "下一次", "本次",
    "implied volatility", "定價", "定价",
    "分析", "歷史", "量化", "角度", "解析", "觀察", "檢視", "检视", "探討", "美股",
    "本文", "本篇", "文章", "主題", "報告", "研究",
    "analysis", "history", "historical", "topic", "report",
)
_THEME_GENERIC_PHRASE_RE = re.compile(
    "|".join(re.escape(p) for p in sorted(_THEME_GENERIC_PHRASES, key=len, reverse=True)),
    flags=re.IGNORECASE,
)
_THEME_PROBE_STOPWORDS = {
    "trending", "repost", "article", "daily", "general", "report",
    "analysis", "history", "historical", "topic", "option", "options",
    "分析", "歷史", "文章", "主題", "本文", "本篇", "報告", "研究", "定價", "定价",
}


def _theme_probe_tokens(title: str, description: str) -> set[str]:
    clean_title = _THEME_PROBE_PREFIX_RE.sub("", str(title or ""))
    clean_text = strip_exclusion_scopes(f"{clean_title} {description or ''}")
    clean_text = _THEME_GENERIC_PHRASE_RE.sub(" ", clean_text)
    return tokenize(clean_text) - _THEME_PROBE_STOPWORDS


def _recent_live(feed: list[dict], days: int) -> list[dict]:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    out = []
    for item in feed:
        if item.get("status") in DEAD_STATUSES:
            continue
        stamp = str(item.get("published_at") or item.get("created_at") or "")
        if stamp and stamp < cutoff:
            continue
        out.append(item)
    return out


def theme_saturation(
    title: str,
    description: str,
    feed: list[dict],
    days: int = 90,
) -> dict:
    """Count live articles in the window that already crowd this topic's theme.

    Returns {"theme_terms": [...], "saturation": int, "matches": [...],
    "corpus_size": int}.  Exposing the denominator lets the daily calibration
    sentinel detect a shrunken/expanded corpus instead of silently trusting a
    threshold fitted on a different regime.
    `saturation` is the number of live articles sharing >= THEME_MIN_SHARED of
    the topic's distinctive theme terms. A topic whose theme is too thin to
    characterise (< THEME_MIN_TERMS distinctive terms) returns saturation 0 with
    an empty theme -- "could not judge", NOT "clean"; callers must not read that
    as a pass.
    """
    corpus = _recent_live(feed, days)
    if not corpus:
        return {"theme_terms": [], "saturation": 0, "matches": [], "corpus_size": 0}

    docs: list[tuple[dict, set[str]]] = []
    df: dict[str, int] = {}
    for item in corpus:
        tags = " ".join(str(t) for t in (item.get("tags") or []))
        toks = tokenize(f"{item.get('title', '')} {tags}")
        docs.append((item, toks))
        for tok in toks:
            df[tok] = df.get(tok, 0) + 1

    ambient_cutoff = max(THEME_AMBIENT_DF_MIN, THEME_AMBIENT_DF_RATIO * len(corpus))
    probe = _theme_probe_tokens(title, description)
    scored = [(t, df.get(t, 0)) for t in probe if 0 < df.get(t, 0) <= ambient_cutoff]
    scored.sort(key=lambda x: (-x[1], x[0]))
    theme = [t for t, _ in scored[:THEME_TERM_COUNT]]
    if len(theme) < THEME_MIN_TERMS:
        return {
            "theme_terms": theme,
            "saturation": 0,
            "matches": [],
            "corpus_size": len(corpus),
        }

    theme_set = set(theme)
    matches: list[dict] = []
    for item, toks in docs:
        shared = theme_set & toks
        if len(shared) >= THEME_MIN_SHARED:
            matches.append(
                {
                    "id": item.get("id", "?"),
                    "title": str(item.get("title") or "")[:80],
                    "status": item.get("status", "?"),
                    "shared_terms": sorted(shared),
                    "published_at": (item.get("published_at") or item.get("created_at") or "")[:10],
                }
            )
    matches.sort(key=lambda m: len(m["shared_terms"]), reverse=True)
    return {
        "theme_terms": theme,
        "saturation": len(matches),
        "matches": matches[:8],
        "corpus_size": len(corpus),
    }
