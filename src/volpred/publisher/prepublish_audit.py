"""Pre-publish content-vs-source provenance gate.

Three-Strike structural fix (2026-06-03, refactor plan
`docs/refactor_plan_prepublish_content_gate.md`).

WHY this exists
---------------
"reader-facing 文章發佈後才被 Codex 24h-review 抓到 content-vs-source FAIL" 是同
一根因、同一症狀的反覆復發 (≥4 次)：
  - #1 2026-05-06 mile_291f9029 (K263)  數字 / lookahead 與 source 不符
  - #2 2026-05-18 mile_7ba7ee54         策略 spec 混用 (NW t 來自 A、OOS 來自 C)
  - #3 2026-05-27 mile_91af7c48 (K562)  headline Sharpe 不在任何 results.json
  - #4 2026-06-03 mile_31b2b0bb (K1413) 現況結論挑錯最大值 + 框架失準

歷史對策一直是「更嚴格執行發佈後 24h Codex review」= **表面補丁**：review 永遠
在 publish 之後，錯誤照樣先進線上 + FB，只能事後 retract / 更正。正確的 domain
model：**對外發佈前，cited 數字與結論必須先對得上 cited results.json**（研究誠實
的 pre-condition，不是 post-hoc 稽核）。

This module owns the pre-publish gate (mirrors the proven two-layer pattern of
`live_verify` / `markdown_table_sanitizer`):

  - Tier-1 (deterministic, ~ms) — numeric provenance: every statistics-context
    number in the article must appear in the cited K-id's flattened
    results.json value set (rel-tol 1e-3 / abs-tol 0.01, with 0.42<->42% unit
    handling). A miss is a FABRICATION-grade finding → hard block.
  - Tier-2 (fast LLM, ~seconds) — conclusion consistency: feed key claims +
    source summary to `agy -p` (gemini-flash, free) and ask whether any
    conclusion contradicts / mis-superlatives the source. Degrades to SKIP on
    any failure; never blocks publish.

The 24h Codex review is NOT removed — it stays as a backstop (defence in
depth), but it is no longer the *only* reliance for content correctness.
"""
from __future__ import annotations

import json
import math
import re
import subprocess
from pathlib import Path

# Statistics-context keywords. A numeric token is only audited if at least one
# of these appears within +/-15 chars of it. Keeps pure prose numbers (page
# counts, "3 個籃子", years) out of the gate while catching every reported
# statistic.
_STAT_KEYWORDS = [
    "Sharpe", "sharpe", "夏普",
    "t-stat", "t-stats", "t值", "t 值", "t統計", "t 統計",
    "p-value", "p值", "p 值", "p-val",
    "波動率", "波動度", "annualized vol", "vol",
    "相關係數", "相關性", "相關", "correlation", "corr",
    "勝率", "win rate", "winrate",
    "年化", "annualized", "annual",
    "報酬", "收益", "return",
    "MDD", "回撤", "drawdown", "max drawdown",
    "QLIKE", "RMSE", "MAE",
    "VaR", "ES", "expected shortfall",
    # NOTE: bare "%" is intentionally NOT a stat keyword (code-review Issue 2,
    # 2026-06-03). A "%" sign alone made every prose percentage ("上漲 3%") a
    # checked claim, widening both false-block and false-pass surface. A
    # statistical percentage (年化波動率 51.7%) is still caught via the real
    # keyword (波動率/年化/…) in its ±15-char context.
    "係數", "coefficient", "beta", "alpha",
    "標準差", "std", "stdev",
    "lag", "領先", "落後",
]

# Pure-year / pure-label tokens to exclude even if a stat keyword is nearby.
_YEAR_RE = re.compile(r"^(?:19|20)\d{2}$")

# Non-statistic numeric labels that legitimately sit next to stat keywords but
# are NOT reported result-statistics (2026-06-08 K1423 false-positive fix):
#   - Ticker symbols (0050, 2330, …) — appear next to 報酬/迴歸/alpha etc.
#   - Index names (標普 500 / S&P 500) — "500" sits next to 迴歸/alpha.
#   - Methodology constants — HAC lag (lag=5) and annualization (× 252).
# These would otherwise trip the provenance gate on every TW/US factor article.
_METHODOLOGY_PREFIX_RE = re.compile(r"(?:lag\s*[=＝]\s*|[×*xX]\s*)$")
_ANNUALIZATION_VALUES = {"252", "252.0"}


def _is_non_stat_label(raw_num: str, is_pct: bool, start: int, end: int, content: str, context: str) -> bool:
    if is_pct:
        return False
    # .TW ticker suffix immediately after the number → ticker, not a stat.
    if content[end:end + 3].upper() == ".TW":
        return True
    # Index names: 標普 500 / S&P 500 — "500" sits next to 迴歸/alpha.
    if raw_num in ("500", "500.0"):
        pre8 = content[max(0, start - 8):start]
        if "標普" in pre8 or "s&p" in context.lower():
            return True
    # 4-digit token whose surrounding text marks it as a TW ticker.
    if re.fullmatch(r"\d{4}", raw_num):
        # Leading-zero ticker (0050) or TW ticker in explicit ticker-list context.
        if raw_num.startswith("0") or "．TW" in context or ".TW" in context:
            return True
    # Annualization factor (× 252 / *252) and HAC lag parameter (lag=N).
    pre6 = content[max(0, start - 6):start]
    if _METHODOLOGY_PREFIX_RE.search(pre6):
        return True
    if raw_num in _ANNUALIZATION_VALUES:
        return True
    return False

# Numeric token: percentages (-42.4%), decimals (-0.79), thousands-separated
# (-1,234.5), plain integers. Optional leading "-" is required so Tier-1
# provenance matches negative Sharpe / delta claims verbatim.
_NUM_RE = re.compile(r"(?<![\w.])(-?(?:\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?))(\s*%)?")

_REL_TOL = 1e-3
_ABS_TOL = 0.01


def _parse_number(raw: str) -> float | None:
    """Parse a numeric token (strip thousands separators) to float."""
    try:
        return float(raw.replace(",", ""))
    except (ValueError, TypeError):
        return None


def _has_stat_context(context: str) -> bool:
    return any(kw in context for kw in _STAT_KEYWORDS)


def extract_numeric_claims(content: str) -> list[dict]:
    """Extract numbers that sit in a statistical context.

    Returns a list of {value: float, raw: str, context: str(+/-15 chars)}.
    Only numbers with a stat keyword within +/-15 chars are kept. Pure years
    (1900-2099 with no decimal/percent) are excluded.
    """
    if not content or not isinstance(content, str):
        return []
    claims: list[dict] = []
    for m in _NUM_RE.finditer(content):
        raw_num = m.group(1)
        is_pct = bool(m.group(2))
        start, end = m.start(1), m.end()
        ctx_lo = max(0, start - 15)
        ctx_hi = min(len(content), end + 15)
        context = content[ctx_lo:ctx_hi]

        # Exclude pure years unless explicitly a percent (a percent can never be
        # a bare year label).
        if not is_pct and _YEAR_RE.match(raw_num):
            continue
        if _is_non_stat_label(raw_num, is_pct, start, end, content, context):
            continue
        if not _has_stat_context(context):
            continue

        value = _parse_number(raw_num)
        if value is None:
            continue
        raw_full = raw_num + ("%" if is_pct else "")
        claims.append({"value": value, "raw": raw_full, "context": context.strip()})
    return claims


def _k_results_path(k_id: str, root: str | Path) -> Path:
    k_lower = k_id.lower()
    return Path(root) / "experiments" / k_lower / f"{k_lower}_results.json"


def _flatten_numbers(obj) -> list[float]:
    """Recursively collect all int/float leaves (excluding bool)."""
    out: list[float] = []
    if isinstance(obj, bool):
        return out
    if isinstance(obj, (int, float)):
        out.append(float(obj))
    elif isinstance(obj, dict):
        for v in obj.values():
            out.extend(_flatten_numbers(v))
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            out.extend(_flatten_numbers(v))
    return out


def load_source_values(k_ids: list[str], root: str | Path = ".") -> set[float]:
    """Load and flatten every numeric value from each cited K's results.json.

    Source values are stored VERBATIM only. The fraction<->percent flexibility
    (article writes 42.4% while source stores 0.4244) is applied per-CLAIM in
    audit_content_provenance, bounded to the % case. We deliberately do NOT seed
    n*100 / n/100 here: blanket cross-scale seeding turns every small decimal
    (a correlation 0.025, a coefficient, a p-value) into a large-magnitude match
    (2.5), so a fabricated "Sharpe 2.5" would spuriously pass against an
    unrelated 0.025 source leaf (code-review Issue 1, 2026-06-03). Missing files
    are skipped.
    """
    values: set[float] = set()
    for k_id in k_ids:
        path = _k_results_path(k_id, root)
        if not path.exists():
            continue
        try:
            data = json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            continue
        for n in _flatten_numbers(data):
            values.add(n)
    return values


def _matches_any(value: float, source: set[float]) -> bool:
    """True if `value` is within tolerance of any source value."""
    for s in source:
        if math.isclose(value, s, rel_tol=_REL_TOL, abs_tol=_ABS_TOL):
            return True
    return False


def audit_content_provenance(
    content: str, k_ids: list[str], root: str | Path = "."
) -> dict:
    """Tier-1 deterministic numeric-vs-source provenance check.

    Returns:
      - no cited K-id / no readable results.json:
          {"tier1_findings": [], "skipped": True, "reason": "no_cited_source"}
      - otherwise:
          {"tier1_findings": [<claim dicts>], "skipped": False,
           "n_claims": N, "n_source_values": M}
        where tier1_findings are the claims whose value is NOT in the source
        set (candidate fabrication / stale numbers).
    """
    if not k_ids:
        return {"tier1_findings": [], "skipped": True, "reason": "no_cited_source"}

    source = load_source_values(k_ids, root)
    if not source:
        return {"tier1_findings": [], "skipped": True, "reason": "no_cited_source"}

    claims = extract_numeric_claims(content)
    findings: list[dict] = []
    for claim in claims:
        value = claim["value"]
        candidates = {value}
        # Percent token (42.4%) -> also test the decimal form 0.424, since source
        # commonly stores volatility/correlation as fractions. A BARE number
        # (Sharpe 2.5, t-stat 3.87, correlation 0.79) is tested verbatim ONLY —
        # we do NOT also probe value*100, which would let a fabricated bare
        # number match an unrelated source leaf two orders of magnitude away
        # (code-review Issue 1, 2026-06-03). A legitimately-percent number
        # written without its % sign is a rare authoring slip Tier-2 / review
        # catches; a false-pass on fabrication is the costlier error.
        if claim["raw"].endswith("%"):
            candidates.add(value / 100.0)
        if not any(_matches_any(c, source) for c in candidates):
            findings.append(claim)

    return {
        "tier1_findings": findings,
        "skipped": False,
        "n_claims": len(claims),
        "n_source_values": len(source),
    }


def run_llm_consistency_check(key_claims: str, source_summary: str) -> dict:
    """Tier-2 fast LLM conclusion-consistency check via `agy -p`.

    Asks gemini-flash whether any article conclusion contradicts the source,
    picks the wrong superlative (e.g. "最抖" pointing at a non-maximum), or
    mixes incompatible specs.

    Returns {"contradictions": [...], "verdict": "PASS"|"FLAG"} on success, or
    {"verdict": "SKIP", "error": "..."} if agy is unavailable / times out /
    returns unparseable output. This function NEVER raises and NEVER blocks
    publish — it degrades gracefully.
    """
    # zh-Hant multi-line prompt: build via heredoc-equivalent (Python string)
    # then pass as a single -p argument. agy -p takes the prompt as an arg
    # (not stdin). Today's date is embedded to avoid stale-date misjudgement.
    prompt = (
        "今天是 2026-06-03。你是一個研究文章事實查核助手。\n"
        "以下是一篇波動率研究文章的『關鍵結論句』與其引用實驗的『來源數據攤平摘要』。\n"
        "請判斷文章結論是否與來源數據衝突，特別檢查以下三類錯誤：\n"
        "1. 結論挑錯最大值/最小值（例如說某層『最抖』但其實另一層波動率更高）。\n"
        "2. 框架描述失準（例如說『五層』但實作只有四籃）。\n"
        "3. 混用不同 spec 的數字（例如把策略 A 的 t 值與策略 C 的 OOS 混為一談）。\n\n"
        "=== 文章關鍵結論 ===\n"
        f"{key_claims}\n\n"
        "=== 來源數據攤平摘要 ===\n"
        f"{source_summary}\n\n"
        "只回傳一個 JSON 物件，格式：\n"
        '{"contradictions": ["...具體衝突描述..."], "verdict": "PASS" 或 "FLAG"}\n'
        "若無任何衝突，verdict 設為 PASS 且 contradictions 為空陣列。\n"
        "不要輸出 JSON 以外的任何文字、不要用 markdown code fence 包起來。"
    )
    try:
        proc = subprocess.run(
            ["agy", "-p", prompt],
            capture_output=True,
            text=True,
            timeout=60,
        )
    except FileNotFoundError:
        return {"verdict": "SKIP", "error": "agy_not_found"}
    except subprocess.TimeoutExpired:
        return {"verdict": "SKIP", "error": "agy_timeout"}
    except Exception as exc:  # pragma: no cover — defensive catch-all
        return {"verdict": "SKIP", "error": f"agy_exception:{exc}"}

    if proc.returncode != 0:
        return {"verdict": "SKIP", "error": f"agy_returncode_{proc.returncode}"}

    out = (proc.stdout or "").strip()
    if not out:
        return {"verdict": "SKIP", "error": "agy_empty_output"}

    parsed = _extract_json_object(out)
    if parsed is None:
        return {"verdict": "SKIP", "error": "agy_unparseable_output"}

    verdict = str(parsed.get("verdict", "")).upper()
    if verdict not in ("PASS", "FLAG"):
        return {"verdict": "SKIP", "error": "agy_invalid_verdict"}
    contradictions = parsed.get("contradictions") or []
    if not isinstance(contradictions, list):
        contradictions = [str(contradictions)]
    return {"contradictions": contradictions, "verdict": verdict}


def _extract_json_object(text: str) -> dict | None:
    """Best-effort: parse the first top-level JSON object out of `text`.

    Tolerates models that wrap the JSON in prose or a code fence.
    """
    text = text.strip()
    # Strip a leading/trailing markdown fence if present.
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text).strip()
    try:
        obj = json.loads(text)
        return obj if isinstance(obj, dict) else None
    except json.JSONDecodeError:
        pass
    # Fall back to scanning for the first {...} balanced block.
    start = text.find("{")
    if start == -1:
        return None
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                candidate = text[start : i + 1]
                try:
                    obj = json.loads(candidate)
                    return obj if isinstance(obj, dict) else None
                except json.JSONDecodeError:
                    return None
    return None


# ── Pre-publish image-URL gate (2026-06-08) ────────────────────────────────
# 缺圖 incident (2026-06-08): 20 published articles shipped with image URLs on
# paths the frontend never serves (/experiments/, /api/storage/, /figures/,
# _PLACEHOLDER, github raw, local abs) → HTTP 404 broken images. The image
# normalization at publish time (publish_draft.normalize_image_paths) transforms
# local refs but missed absolute zeabur /experiments/ URLs. This is a
# DETERMINISTIC path-based verification gate: every embedded image must live on a
# canonical *served* path (Supabase public storage bucket OR frontend /charts/),
# else block (修流程不修資料 — stop broken images at publish, not after).
import re as _img_re

# Markdown ![alt](url) and HTML <img src="url">.
_IMG_MD_RE = _img_re.compile(r"!\[[^\]]*\]\(\s*(?P<url>[^)\s]+)")
_IMG_HTML_RE = _img_re.compile(r"<img\b[^>]*?\bsrc=[\"'](?P<url>[^\"']+)", _img_re.IGNORECASE)

# Canonical SERVED locations (an image here is reachable in production).
_CANONICAL_IMG_SUBSTRINGS = (
    "/storage/v1/object/public/",   # any Supabase public bucket (article-images, paper-images…)
)
# Frontend-served static charts: volpred.zeabur.app/charts/... or relative /charts/...
_CANONICAL_CHARTS_RE = _img_re.compile(r"(^|//[^/]+)/charts/[^)\s]+\.(png|svg|jpe?g|webp)$", _img_re.IGNORECASE)

# Known-broken markers (used to give a precise reason; anything non-canonical is
# blocked regardless, but these explain WHY for the most common cases).
_BROKEN_IMG_MARKERS = (
    ("/experiments/", "experiments/ path is not served by the frontend (repo-only)"),
    ("/api/storage/", "/api/storage/ is not a served route"),
    ("/figures/", "/figures/ path is not served"),
    ("_PLACEHOLDER", "placeholder filename — real chart was never wired"),
    ("raw.githubusercontent.com", "github raw is not the canonical asset host"),
    ("github.com", "github URL is not the canonical asset host"),
    ("file://", "local file:// path is not reachable in production"),
    ("/Users/", "local absolute path is not reachable in production"),
)


def _is_canonical_image_url(url: str) -> bool:
    u = (url or "").strip()
    if not u:
        return False
    if any(s in u for s in _CANONICAL_IMG_SUBSTRINGS):
        return True
    if _CANONICAL_CHARTS_RE.search(u):
        return True
    return False


def audit_image_urls(content: str) -> dict:
    """Deterministic path-based image gate.

    Returns {"broken": [{"url","reason"}...], "total": int}. `broken` lists every
    embedded image whose URL is NOT on a canonical served path. Network-free.
    """
    text = content or ""
    urls: list[str] = []
    for m in _IMG_MD_RE.finditer(text):
        urls.append(m.group("url"))
    for m in _IMG_HTML_RE.finditer(text):
        urls.append(m.group("url"))
    broken: list[dict] = []
    for u in urls:
        if _is_canonical_image_url(u):
            continue
        reason = "non-canonical image path (not Supabase public storage or /charts/)"
        for marker, why in _BROKEN_IMG_MARKERS:
            if marker in u:
                reason = why
                break
        broken.append({"url": u, "reason": reason})
    return {"broken": broken, "total": len(urls)}
