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
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
from scripts.dispatch_supervisor import procutil  # noqa: E402
from volpred.ops.execution.registry import (  # noqa: E402
    ProviderRegistryError,
    authorize_provider_spawn,
    verify_spawn_receipt,
)

AGY_AUDIT_MODEL = "gemini-3.6-flash-high"

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
    # Window / period length: "20 日"/"20日"/"60 天"/"5 分鐘" — a day/week/min count
    # is a methodology window (RV window, lookback), not a reported result-stat.
    post3 = content[end:end + 3]
    # NOTE: 分 deliberately excluded — would swallow 分位 (percentile), a real stat.
    if re.match(r"\s*[日天週月年]", post3):
        return True
    # Date fragments: "6/5" / "2026/6" / "2026-06-09" — month/day pieces are
    # labels, not result statistics, even near phrases such as daily returns.
    if re.match(r"/\d", content[end:end + 2]):
        return True
    if re.search(r"(?:19|20)\d{2}-$|\d{1,2}-$", content[max(0, start - 6):start]):
        return True
    if len(raw_num) <= 2 and re.match(r"-\d{1,2}(?!\d)", content[end:end + 3]):
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


_CRITERIA_KEY_RE = re.compile(
    r"(gate|criteri|threshold|decision_rule|pass_rule|spec)", re.IGNORECASE
)
_NUMERIC_LITERAL_RE = re.compile(r"[-+]?\d+(?:\.\d+)?")


def _flatten_criteria_numbers(obj, key: str | None = None) -> list[float]:
    """Collect numeric literals declared inside criteria/gate STRING values.

    Experiments routinely record their pass thresholds as prose, e.g.
    `"gate": "improvement>0, HLN-DM t<-3, BH q<0.05, ..."` (k1683). Those
    thresholds are legitimately source-backed, but `_flatten_numbers` only sees
    numeric leaves, so an article quoting "門檻 -3" was flagged as fabricated.

    Scope is deliberately narrow — only string leaves whose KEY looks like a
    criteria/gate declaration. Parsing numbers out of every string leaf would
    dump dates, ids and sample labels into the whitelist and blunt the gate.
    """
    out: list[float] = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            out.extend(_flatten_criteria_numbers(v, key=k))
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            out.extend(_flatten_criteria_numbers(v, key=key))
    elif isinstance(obj, str) and key and _CRITERIA_KEY_RE.search(key):
        for token in _NUMERIC_LITERAL_RE.findall(obj):
            try:
                out.append(float(token))
            except ValueError:
                pass  # silent-ok: token came from _NUMERIC_LITERAL_RE, float() is total
    return out


def _warn_source_values_load(path: Path, exc: Exception) -> None:
    print(
        "[prepublish_audit] WARN source results JSON read failed; skipping "
        f"path={path} error={type(exc).__name__}: {exc}",
        file=sys.stderr,
    )


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
        except (json.JSONDecodeError, OSError) as exc:
            _warn_source_values_load(path, exc)
            continue
        for n in _flatten_numbers(data):
            values.add(n)
        for n in _flatten_criteria_numbers(data):
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
    # (not stdin). Today's date is embedded DYNAMICALLY to avoid stale-date
    # misjudgement — 2026-07-10 incident: this line was hardcoded "2026-06-03"
    # (authoring date), so a month later the auditor flagged the REAL current
    # date as "future date conflict" on mile_e3cede77. Exactly the bug the
    # embedding was meant to prevent.
    today_taipei = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d")
    prompt = (
        f"今天是 {today_taipei}。你是一個研究文章事實查核助手。\n"
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
    # `agy` spawns tool subprocesses of its own, so a plain subprocess.run timeout
    # would kill only the pid we hold and leave its workers running unsupervised.
    # Own process group + kill_pgid. Gate: scripts/tests/test_agentic_cli_timeout_killpg.py
    agy_bin = shutil.which("agy")
    if not agy_bin:
        return {"verdict": "SKIP", "error": "agy_not_found"}
    child_env = {**os.environ, "ANTIGRAVITY_MODEL": AGY_AUDIT_MODEL}
    try:
        receipt = authorize_provider_spawn(
            contract_id="prepublish-audit.agy",
            model_id=AGY_AUDIT_MODEL,
            executable_path=agy_bin,
            environment=child_env,
        )
        verify_spawn_receipt(receipt)
    except ProviderRegistryError as exc:
        return {
            "verdict": "SKIP",
            "error": f"provider_policy_denied:{exc}",
        }
    child_env.update(receipt.environment())
    try:
        proc = subprocess.Popen(
            [receipt.resolved_executable, "-p", prompt],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,
            env=child_env,
        )
    except FileNotFoundError:
        return {"verdict": "SKIP", "error": "agy_not_found"}
    except Exception as exc:  # pragma: no cover — defensive catch-all
        return {"verdict": "SKIP", "error": f"agy_exception:{exc}"}

    try:
        stdout, stderr = proc.communicate(timeout=60)
    except subprocess.TimeoutExpired:
        from volpred.ops import termination

        try:
            pgid = os.getpgid(proc.pid)
            intent = termination.arm(
                target_kind="pgid", target_id=pgid,
                reason="prepublish_audit_timeout",
                actor="prepublish_audit",
                signal_sequence=termination.terminating_signals(),
            )
            procutil.kill_pgid(pgid, intent=intent)
        except (ProcessLookupError, PermissionError) as kill_exc:
            print(f"[prepublish_audit] agy timed out; killpg failed: {kill_exc}", file=sys.stderr)
        proc.wait()
        return {"verdict": "SKIP", "error": "agy_timeout"}
    except Exception as exc:  # pragma: no cover — defensive catch-all
        return {"verdict": "SKIP", "error": f"agy_exception:{exc}"}

    proc = subprocess.CompletedProcess(proc.args, proc.returncode, stdout, stderr)

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


# Repo roots that must NEVER appear in details.charts provenance again.
# ~/Desktop location was retired 2026-07-02 (TCC migration); a stale absolute
# path breaks future re-publish normalization once the compat symlink goes away.
_STALE_REPO_ROOTS = ("/Users/yhlai0911/Desktop/volpred-research",)


def audit_details_chart_paths(details: dict | None) -> dict:
    """Warn-only provenance check on details.charts / image fields.

    Flags (a) stale repo roots (pre-migration ~/Desktop path) and (b) any
    machine-absolute /Users/ path — chart refs should be repo-relative so the
    provenance survives host/path migrations. Never blocks publish (fail-open
    is the caller's responsibility); network-free.

    Returns {"flagged": [{"where","value","reason"}...]}.
    """
    flagged: list[dict] = []
    if not isinstance(details, dict):
        return {"flagged": flagged}

    def _check(value, where: str) -> None:
        if not isinstance(value, str) or not value:
            return
        for root in _STALE_REPO_ROOTS:
            if root in value:
                flagged.append({"where": where, "value": value,
                                "reason": f"stale repo root ({root}) — repo moved 2026-07-02"})
                return
        if value.startswith("/Users/"):
            flagged.append({"where": where, "value": value,
                            "reason": "machine-absolute path (prefer repo-relative ref)"})

    charts = details.get("charts")
    if isinstance(charts, list):
        for i, entry in enumerate(charts):
            if isinstance(entry, str):
                _check(entry, f"charts[{i}]")
            elif isinstance(entry, dict):
                for key in ("path", "url", "image_url", "src"):
                    _check(entry.get(key), f"charts[{i}].{key}")
    _check(details.get("image_url"), "image_url")
    for list_key in ("image_urls", "chart_urls"):
        values = details.get(list_key)
        if isinstance(values, list):
            for i, v in enumerate(values):
                _check(v, f"{list_key}[{i}]")
    return {"flagged": flagged}


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


# Experiment-scoped image keys look like `.../article-images/k1703/fig1_...png`.
_EXPERIMENT_IMG_KEY_RE = _img_re.compile(
    r"/article-images/(?P<kid>k\d+[a-z0-9_\-]*)/", _img_re.IGNORECASE
)


def audit_chart_cjk_fonts(content: str, root: Path | None = None) -> dict:
    """Block articles whose charts were drawn without a CJK font (tofu boxes).

    matplotlib's default font has no CJK glyphs, so a Chinese axis label renders as
    empty boxes. Nothing raises, nothing logs — only a human looking at the PNG can
    tell. It has now shipped to readers three times (2026-06-11 k202, 2026-07-13 CPI
    T-2, 2026-07-14 k1703).

    A CI ratchet for this already exists, and it *did* fire on k1703 — but CI runs on
    push, which is after publish, so it turned red while the tofu charts were already
    live on the site. Same verdict, wrong side of the publish boundary. This is that
    verdict moved to the point where it can still prevent the damage.

    Deterministic (AST over the generator script), so a hit is a hard block rather
    than a warning; unresolvable inputs fail open per `.claude/rules/dedup-gate-audit.md`.
    """
    repo_root = root or _REPO_ROOT
    text = content or ""
    urls: list[str] = []
    for m in _IMG_MD_RE.finditer(text):
        urls.append(m.group("url"))
    for m in _IMG_HTML_RE.finditer(text):
        urls.append(m.group("url"))

    k_ids: list[str] = []
    for u in urls:
        m = _EXPERIMENT_IMG_KEY_RE.search(u)
        if m:
            kid = m.group("kid").lower()
            if kid not in k_ids:
                k_ids.append(kid)
    if not k_ids:
        return {"violations": [], "checked": []}

    try:
        from scripts import audit_cjk_chart_fonts as cjk_audit
    except Exception as exc:  # noqa: BLE001
        print(f"  [prepublish_audit] CJK font gate unavailable (fail-open): {exc}")
        return {"violations": [], "checked": [], "degraded": str(exc)}

    violations: list[dict] = []
    checked: list[str] = []
    for kid in k_ids:
        exp_dir = repo_root / "experiments" / kid
        if not exp_dir.is_dir():
            # Image key that does not map to an experiment dir (renamed / external
            # asset). Nothing to inspect — fail open rather than block on a guess.
            continue
        for script in sorted(exp_dir.glob("*.py")):
            checked.append(str(script.relative_to(repo_root)))
            verdict = cjk_audit.check_file(script)
            if verdict is not None:
                violations.append({**verdict, "k_id": kid})
    return {"violations": violations, "checked": checked}
