#!/usr/bin/env python3
"""Platform predictor-zoo multiple-testing audit.

This script is intentionally a meta-audit: it scans prior platform artifacts for
reported external-predictor volatility tests, collapses them to source-level
best-case hypotheses, and applies reproducible multiple-testing corrections.

It does not mutate source artifacts.
"""

from __future__ import annotations

import csv
import json
import math
import re
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import matplotlib.pyplot as plt
import numpy as np
from scipy import stats


ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = Path(__file__).resolve().parent
EXPERIMENT_ID = "research_predictor_zoo_30_predictor_romano_wolf_fdr_oos"
RESULTS_PATH = OUT_DIR / f"{EXPERIMENT_ID}_results.json"
AUDIT_CSV_PATH = OUT_DIR / "predictor_zoo_audit_table.csv"
FIG_PATH = OUT_DIR / "fig_predictor_zoo_corrections.png"
SEED = 42


VOL_CONTEXT_RE = re.compile(
    r"\b(RV|realized[- ]?vol|volatility|variance|QLIKE|GARCH|HAR|VIX|"
    r"downside|drawdown|tail|risk|VaR|ES|波動|方差)\b",
    re.IGNORECASE,
)
FORECAST_CONTEXT_RE = re.compile(
    r"\b(OOS|out[- ]of[- ]sample|forecast|predict|prediction|predictive|"
    r"lead|lagged|shift|Granger|forward|fwd|next[- ]?(day|week|month)|"
    r"DM|HLN|Harvey|HAC|Newey|Bonferroni|Holm|BH|FDR|bootstrap|"
    r"預測|領先|未來|校正)\b",
    re.IGNORECASE,
)

FAMILY_PATTERNS: dict[str, list[str]] = {
    "ai_power_utility": [
        r"\bAI power\b",
        r"AI 電力",
        r"\bdata[- ]?center\b",
        r"\bhyperscaler\b",
        r"\bPJM\b",
        r"\bMISO\b",
        r"\bcapacity[- ]auction\b",
        r"公用事業",
    ],
    "air_pollution": [r"\bPM2\.?5\b", r"\bAQI\b", r"\bAirData\b", r"\bpollution\b"],
    "gpr_geopolitical": [r"\bGPR\b", r"geopolitical", r"地緣政治"],
    "epu_disagreement": [
        r"\bEPU\b",
        r"economic policy uncertainty",
        r"policy uncertainty",
        r"\bJLN\b",
        r"\bSPF\b",
        r"disagreement",
        r"agreed vs disagreed",
    ],
    "credit_liquidity_stress": [
        r"credit[- ]spread",
        r"\bHYG[-_/ ]LQD\b",
        r"\bTED Spread\b",
        r"\bHY Spread\b",
        r"\bNFCI\b",
        r"\bSTLFSI\b",
        r"repo[- ]basis",
        r"merchant[- ]platform credit",
        r"bond mutual fund",
        r"\bAP fragmentation\b",
        r"office[- ]?CRE",
        r"bank market[- ]to[- ]book",
        r"EM sovereign[- ]credit",
        r"credit[- ]stress",
    ],
    "stablecoin_crypto_funding": [
        r"stablecoin",
        r"\bUSDT\b",
        r"\bUSDC\b",
        r"\bDefiLlama\b",
        r"tokeni[sz]ed Treasury",
        r"Ethereum gas",
        r"blockspace",
        r"funding rate",
        r"crypto[- ]to[- ]Treasury",
    ],
    "sentiment_attention_text": [
        r"Google Trends",
        r"investor attention",
        r"\battention\b",
        r"\bsentiment\b",
        r"FRBSF",
        r"Fedspeak",
        r"Stocktwits",
        r"Fear ?& ?Greed",
        r"put[-/ ]call",
        r"option[- ]flow",
        r"call demand",
        r"GDELT",
        r"news sentiment",
        r"新聞情緒",
    ],
    "macro_cross_asset": [
        r"\bMOVE\b",
        r"VIX[- ]MOVE",
        r"\bDXY\b",
        r"dollar index",
        r"yield curve",
        r"term[- ]spread",
        r"term structure",
        r"\bFOMC\b",
        r"macro news",
        r"tariff",
        r"defence[- ]spending",
        r"defense[- ]spending",
        r"\bNATO\b",
        r"\bVRP\b",
    ],
    "taiwan_external_flow": [
        r"SPY_ret_L1",
        r"retail participation",
        r"institutional sentiment",
        r"margin activity",
        r"retail share",
        r"foreign flow",
        r"外資",
        r"融資",
        r"台股情緒",
    ],
    "regulatory_filing_event": [
        r"Federal Register",
        r"\bEDGAR\b",
        r"\b10[- ]?[KQ]\b",
        r"\bS-1\b",
        r"filing",
        r"rule[- ]flow",
        r"antitrust",
    ],
}

T_KEYS = (
    "dm_t",
    "DM_HLN_t",
    "hln_t",
    "harvey_t",
    "hac_t",
    "hac_tstat",
    "nw_t",
    "newey_west_t",
    "t_stat",
    "tstat",
    "t_value",
    "welch_t",
    "ols_t",
    "z_stat",
    "z",
    "stat",
    "t",
)
RAW_P_KEYS = (
    "p_value",
    "p_val",
    "pvalue",
    "p",
    "dm_p",
    "DM_HLN_p",
    "hln_p",
    "harvey_p",
    "hac_p",
    "welch_p",
)
ADJUSTED_P_KEYS = (
    "p_holm",
    "holm_p",
    "p_bonf",
    "bonferroni_p",
    "p_bonferroni",
    "bh_q",
    "q_value",
)
NON_TEST_PATH_RE = re.compile(
    r"(metadata|config|reference|literature|output|figure|preview|"
    r"event_group_panel_preview|price_fails)",
    re.IGNORECASE,
)
PRIMARY_INCLUDE_RE = re.compile(
    r"(oos|out[-_ ]of[-_ ]sample|forecast|dm_tests?|dm_|DM_HLN|qlike|"
    r"harvey|fwd|forward|next|target|predictive|prediction|hac)",
    re.IGNORECASE,
)
PRIMARY_EXCLUDE_RE = re.compile(
    r"(in[-_ ]sample|full[-_ ]sample|joint_regression_IS|"
    r"descriptive|data_diagnostic)",
    re.IGNORECASE,
)
PRIMARY_EXCLUDE_ALWAYS_RE = re.compile(
    r"((^|[._])(intercept|const)($|[._])|diagnostic|ljung|normality|"
    r"stationarity|adf|jarque|arch_lm|residual|posterior|mcmc|"
    r"correlation|partial_correlations|lead_lag|granger|acf|pacf)",
    re.IGNORECASE,
)


@dataclass
class TestRow:
    source_group: str
    source_file: str
    source_kind: str
    source_priority: int
    k_id: str | None
    family: str
    secondary_families: str
    source_field_path: str
    statistic: float | None
    p_value: float
    p_source: str
    p_is_adjusted: bool
    abs_z: float
    context: str
    selected_primary: bool = False
    holm_p: float | None = None
    bh_q: float | None = None
    rw_style_independent_maxT_p: float | None = None
    harvey_abs_t_ge_3: bool = False
    holm_05_pass: bool = False
    bh_q10_pass: bool = False
    rw_style_05_pass: bool = False


def clamp_p(p: float) -> float:
    if not math.isfinite(p):
        return 1.0
    return min(max(float(p), 1e-300), 1.0)


def numeric(v: Any) -> float | None:
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)) and math.isfinite(float(v)):
        return float(v)
    if isinstance(v, str):
        try:
            parsed = float(v.strip().replace("<", ""))
        except ValueError:
            return None
        return parsed if math.isfinite(parsed) else None
    return None


def detect_families(text: str) -> list[str]:
    hits: list[str] = []
    for family, patterns in FAMILY_PATTERNS.items():
        if any(re.search(pattern, text, re.IGNORECASE) for pattern in patterns):
            hits.append(family)
    return hits


def has_vol_forecast_context(text: str) -> bool:
    return bool(VOL_CONTEXT_RE.search(text) and FORECAST_CONTEXT_RE.search(text))


def rel(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def detect_k_id(source_file: str, text: str) -> str | None:
    for candidate in (source_file, text[:1000]):
        m = re.search(r"(?<![A-Za-z0-9])K[_-]?(\d{2,4})(?![A-Za-z0-9])", candidate, re.IGNORECASE)
        if m:
            return f"K{m.group(1)}"
    return None


def source_group_for_file(path: Path) -> str:
    parts = path.parts
    if "experiments" in parts:
        idx = parts.index("experiments")
        if idx + 1 < len(parts):
            return f"experiments/{parts[idx + 1]}"
    return rel(path)


def choose_family(row_context: str, source_families: list[str]) -> tuple[str | None, list[str]]:
    row_families = detect_families(row_context)
    if row_families:
        return row_families[0], row_families[1:]
    if source_families:
        return source_families[0], source_families[1:]
    return None, []


def p_from_stat(stat: float | None) -> tuple[float | None, float | None]:
    if stat is None or not math.isfinite(stat):
        return None, None
    abs_z = abs(float(stat))
    p = 2.0 * stats.norm.sf(abs_z)
    return clamp_p(p), abs_z


def get_stat_and_p(node: dict[str, Any]) -> tuple[float | None, float | None, str | None, bool]:
    stat_value: float | None = None
    for key in T_KEYS:
        if key in node:
            value = numeric(node.get(key))
            if value is not None and abs(value) < 100:
                stat_value = value
                break

    for key in RAW_P_KEYS:
        if key in node:
            p = numeric(node.get(key))
            if p is not None and 0 <= p <= 1:
                return stat_value, clamp_p(p), key, False

    for key in ADJUSTED_P_KEYS:
        if key in node:
            p = numeric(node.get(key))
            if p is not None and 0 <= p <= 1:
                return stat_value, clamp_p(p), key, True

    estimated_p, _ = p_from_stat(stat_value)
    if estimated_p is not None:
        return stat_value, estimated_p, "estimated_from_t_normal", False
    return stat_value, None, None, False


def walk_json(node: Any, path: list[str]) -> Iterable[tuple[list[str], dict[str, Any]]]:
    if isinstance(node, dict):
        yield path, node
        for key, value in node.items():
            yield from walk_json(value, path + [str(key)])
    elif isinstance(node, list):
        for idx, value in enumerate(node):
            yield from walk_json(value, path + [f"[{idx}]"])


def compact_context(value: Any, max_chars: int = 600) -> str:
    try:
        text = json.dumps(value, ensure_ascii=False, sort_keys=True)
    except Exception:
        text = str(value)
    text = re.sub(r"\s+", " ", text)
    return text[:max_chars]


def iter_json_rows(path: Path) -> list[TestRow]:
    source_file = rel(path)
    source_group = source_group_for_file(path)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []

    source_text = compact_context(data, 12000)
    metadata_bits = [source_file, source_group]
    if isinstance(data, dict):
        for key in ("experiment_id", "slug", "title", "description", "verdict"):
            if key in data:
                metadata_bits.append(compact_context(data.get(key), 1000))
    source_id_text = " ".join(metadata_bits)
    source_families = detect_families(source_id_text)
    if not has_vol_forecast_context(source_text):
        return []

    k_id = detect_k_id(source_file, source_text)
    rows: list[TestRow] = []
    for path_parts, node in walk_json(data, []):
        stat_value, p_value, p_source, p_adjusted = get_stat_and_p(node)
        if p_value is None:
            continue
        field_path = ".".join(path_parts)
        path_text = f"{field_path} {compact_context(node)}"
        if NON_TEST_PATH_RE.search(field_path) and not FORECAST_CONTEXT_RE.search(path_text):
            continue
        if not has_vol_forecast_context(f"{path_text} {source_text[:2000]}"):
            continue
        family, secondary = choose_family(path_text, source_families)
        if family is None:
            continue
        _, abs_z = p_from_stat(stat_value)
        if abs_z is None:
            abs_z = float(stats.norm.isf(clamp_p(p_value) / 2.0))
        rows.append(
            TestRow(
                source_group=source_group,
                source_file=source_file,
                source_kind="json_results",
                source_priority=0,
                k_id=k_id,
                family=family,
                secondary_families=";".join(secondary),
                source_field_path=field_path,
                statistic=stat_value,
                p_value=clamp_p(p_value),
                p_source=p_source or "unknown",
                p_is_adjusted=p_adjusted,
                abs_z=float(abs_z),
                context=path_text[:500],
            )
        )
    return rows


TEXT_T_RE = re.compile(
    r"(?P<label>(?:DM|HLN|HAC|Newey[- ]West|NW|Welch|OLS|t[- ]?stat|t)\b"
    r"[^.;\n]{0,90}?)"
    r"(?<![A-Za-z])t\s*[=:]\s*(?P<t>[+-]?\d+(?:\.\d+)?)",
    re.IGNORECASE,
)
BARE_T_RE = re.compile(
    r"\b(?P<label>DM|HLN|HAC|Welch|NW)[-_ ]?t\s*[=:]\s*(?P<t>[+-]?\d+(?:\.\d+)?)",
    re.IGNORECASE,
)
P_RE = re.compile(r"\bp(?:_value|_val)?\s*(?:=|<|<=)\s*(?P<p>\d*\.?\d+(?:e[-+]?\d+)?)", re.IGNORECASE)


def iter_text_rows(path: Path | None, text: str, source_group: str, source_kind: str, priority: int) -> list[TestRow]:
    source_file = rel(path) if path else "storage/memory/knowledge.json"
    source_id_text = f"{source_file} {source_group} {text[:1500]}"
    source_families = detect_families(source_id_text)
    if not has_vol_forecast_context(text):
        return []
    k_id = detect_k_id(source_file, text)
    rows: list[TestRow] = []
    matches = list(TEXT_T_RE.finditer(text)) + list(BARE_T_RE.finditer(text))
    seen_spans: set[tuple[int, int]] = set()
    for match in sorted(matches, key=lambda m: m.start()):
        span = (match.start(), match.end())
        if span in seen_spans:
            continue
        seen_spans.add(span)
        stat_value = numeric(match.group("t"))
        if stat_value is None or abs(stat_value) >= 100:
            continue
        start = max(0, match.start() - 220)
        end = min(len(text), match.end() + 220)
        window = re.sub(r"\s+", " ", text[start:end])
        if not has_vol_forecast_context(window):
            continue
        p_value = None
        p_source = "estimated_from_t_normal"
        p_search = text[match.end() : min(len(text), match.end() + 140)]
        for p_match in P_RE.finditer(p_search):
            p_candidate = numeric(p_match.group("p"))
            if p_candidate is not None and 0 <= p_candidate <= 1:
                p_value = clamp_p(p_candidate)
                p_source = "text_regex_p"
                break
        if p_value is None:
            p_value, _ = p_from_stat(stat_value)
        if p_value is None:
            continue
        family, secondary = choose_family(window, source_families)
        if family is None:
            continue
        _, abs_z = p_from_stat(stat_value)
        rows.append(
            TestRow(
                source_group=source_group,
                source_file=source_file,
                source_kind=source_kind,
                source_priority=priority,
                k_id=k_id,
                family=family,
                secondary_families=";".join(secondary),
                source_field_path="text_regex",
                statistic=stat_value,
                p_value=clamp_p(p_value),
                p_source=p_source,
                p_is_adjusted=False,
                abs_z=float(abs_z or 0.0),
                context=window[:500],
            )
        )
    return rows


def load_knowledge_rows() -> list[TestRow]:
    path = ROOT / "storage/memory/knowledge.json"
    try:
        items = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    if not isinstance(items, list):
        return []
    rows: list[TestRow] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        item_id = str(item.get("item_id") or item.get("id") or "unknown")
        text = " ".join(
            compact_context(item.get(key), 3000)
            for key in ("title", "content", "summary", "evidence", "data_source", "tags", "category")
        )
        rows.extend(
            iter_text_rows(
                None,
                text,
                source_group=f"knowledge/{item_id}",
                source_kind="knowledge",
                priority=2,
            )
        )
    return rows


def load_file_rows() -> list[TestRow]:
    rows: list[TestRow] = []
    for path in sorted((ROOT / "experiments").rglob("*")):
        if not path.is_file():
            continue
        if OUT_DIR in path.parents:
            continue
        if path.stat().st_size > 2_500_000:
            continue
        name = path.name
        if name.endswith("_results.json") or name == "results.json":
            rows.extend(iter_json_rows(path))
        elif name == "README.md":
            try:
                text = path.read_text(encoding="utf-8")
            except Exception:
                continue
            rows.extend(
                iter_text_rows(
                    path,
                    text,
                    source_group=source_group_for_file(path),
                    source_kind="readme",
                    priority=1,
                )
            )
    return rows


def select_primary(rows: list[TestRow]) -> list[TestRow]:
    grouped: dict[tuple[str, str], list[TestRow]] = defaultdict(list)
    eligible_rows = [row for row in rows if is_primary_eligible(row)]
    json_source_groups = {row.source_group for row in eligible_rows if row.source_kind == "json_results"}
    for row in eligible_rows:
        if row.source_kind == "knowledge":
            continue
        if row.source_kind == "readme" and row.source_group in json_source_groups:
            continue
        key_source = row.k_id or row.source_group
        grouped[(key_source, row.family)].append(row)

    primary: list[TestRow] = []
    for candidates in grouped.values():
        candidates.sort(key=lambda r: (r.p_value, r.source_priority, -r.abs_z, r.source_file))
        chosen = candidates[0]
        chosen.selected_primary = True
        primary.append(chosen)
    primary.sort(key=lambda r: (r.p_value, r.source_group, r.family))
    return primary


def is_primary_eligible(row: TestRow) -> bool:
    """Keep only forecast/OOS-like predictor tests for the correction table."""
    context = f"{row.source_field_path} {row.context}"
    if PRIMARY_EXCLUDE_ALWAYS_RE.search(row.source_field_path):
        return False
    if PRIMARY_EXCLUDE_ALWAYS_RE.search(row.context):
        return False
    if not PRIMARY_INCLUDE_RE.search(context):
        return False
    if PRIMARY_EXCLUDE_RE.search(context):
        # A DM/QLIKE/OOS node is still a model-comparison test; otherwise
        # diagnostics/correlations/Granger screens are not primary OOS evidence.
        if not re.search(r"(oos|out[-_ ]of[-_ ]sample|dm_tests?|dm_|DM_HLN|qlike)", context, re.IGNORECASE):
            return False
    return True


def adjust_bh(p_values: list[float]) -> list[float]:
    m = len(p_values)
    order = sorted(range(m), key=lambda i: p_values[i])
    q = [1.0] * m
    running = 1.0
    for rank_from_end, idx in enumerate(reversed(order), start=1):
        rank = m - rank_from_end + 1
        running = min(running, p_values[idx] * m / rank)
        q[idx] = clamp_p(running)
    return q


def adjust_holm(p_values: list[float]) -> list[float]:
    m = len(p_values)
    order = sorted(range(m), key=lambda i: p_values[i])
    adjusted = [1.0] * m
    running = 0.0
    for rank, idx in enumerate(order, start=1):
        val = min(1.0, (m - rank + 1) * p_values[idx])
        running = max(running, val)
        adjusted[idx] = clamp_p(running)
    return adjusted


def adjust_rw_style_independent(abs_z: list[float]) -> list[float]:
    """Stepdown independent maxT approximation.

    This is not a formal Romano-Wolf result because no joint loss/test matrix is
    available. It is a transparent maxT reference under independent N(0,1) nulls.
    """
    m = len(abs_z)
    order = sorted(range(m), key=lambda i: abs_z[i], reverse=True)
    adjusted = [1.0] * m
    running = 0.0
    for j, idx in enumerate(order):
        remaining = m - j
        prob_inside = max(0.0, min(1.0, 2.0 * stats.norm.cdf(abs_z[idx]) - 1.0))
        p = 1.0 - prob_inside**remaining
        running = max(running, p)
        adjusted[idx] = clamp_p(running)
    return adjusted


def apply_corrections(primary: list[TestRow]) -> None:
    p_values = [row.p_value for row in primary]
    abs_z = [row.abs_z for row in primary]
    holm = adjust_holm(p_values)
    bh = adjust_bh(p_values)
    rw = adjust_rw_style_independent(abs_z)
    for row, holm_p, bh_q, rw_p in zip(primary, holm, bh, rw):
        row.holm_p = holm_p
        row.bh_q = bh_q
        row.rw_style_independent_maxT_p = rw_p
        row.harvey_abs_t_ge_3 = bool(row.abs_z >= 3.0)
        row.holm_05_pass = bool(holm_p <= 0.05)
        row.bh_q10_pass = bool(bh_q <= 0.10)
        row.rw_style_05_pass = bool(rw_p <= 0.05)


def write_audit_csv(rows: list[TestRow]) -> None:
    fieldnames = list(asdict(rows[0]).keys()) if rows else list(TestRow.__dataclass_fields__.keys())
    with AUDIT_CSV_PATH.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(asdict(row))


def make_figure(primary: list[TestRow]) -> None:
    family_counts = Counter(row.family for row in primary)
    correction_counts = {
        "raw p<0.05": sum(row.p_value <= 0.05 for row in primary),
        "|t|>=3": sum(row.harvey_abs_t_ge_3 for row in primary),
        "BH q<=0.10": sum(row.bh_q10_pass for row in primary),
        "Holm p<=0.05": sum(row.holm_05_pass for row in primary),
        "maxT p<=0.05": sum(row.rw_style_05_pass for row in primary),
    }

    fig, axes = plt.subplots(1, 2, figsize=(14, 5))
    fam_items = family_counts.most_common()
    axes[0].barh([x[0] for x in fam_items][::-1], [x[1] for x in fam_items][::-1], color="#3a7ca5")
    axes[0].set_title("Primary hypotheses by family")
    axes[0].set_xlabel("count")

    axes[1].bar(correction_counts.keys(), correction_counts.values(), color="#b86442")
    axes[1].set_title("Survivors after correction")
    axes[1].set_ylabel("count")
    axes[1].tick_params(axis="x", rotation=35)
    for idx, value in enumerate(correction_counts.values()):
        axes[1].text(idx, value + 0.2, str(value), ha="center", va="bottom", fontsize=9)

    fig.tight_layout()
    fig.savefig(FIG_PATH, dpi=160)
    plt.close(fig)


def summarize(rows: list[TestRow], primary: list[TestRow]) -> dict[str, Any]:
    family_summary = {}
    for family in sorted({row.family for row in primary}):
        fam_rows = [row for row in primary if row.family == family]
        family_summary[family] = {
            "n_primary": len(fam_rows),
            "raw_p_lt_0_05": sum(row.p_value <= 0.05 for row in fam_rows),
            "harvey_abs_t_ge_3": sum(row.harvey_abs_t_ge_3 for row in fam_rows),
            "bh_q10_pass": sum(row.bh_q10_pass for row in fam_rows),
            "holm_05_pass": sum(row.holm_05_pass for row in fam_rows),
            "rw_style_05_pass": sum(row.rw_style_05_pass for row in fam_rows),
            "best_p": min((row.p_value for row in fam_rows), default=None),
        }

    survivors_bh = [row for row in primary if row.bh_q10_pass]
    survivors_holm = [row for row in primary if row.holm_05_pass]
    survivors_rw = [row for row in primary if row.rw_style_05_pass]
    adjusted_raw_sources = sum(row.p_is_adjusted for row in primary)

    return {
        "experiment_id": EXPERIMENT_ID,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "seed": SEED,
        "data_sources": {
            "knowledge_json": "storage/memory/knowledge.json",
            "experiment_files": "experiments/**/README.md, experiments/**/*_results.json, experiments/**/results.json",
        },
        "scope": {
            "all_extracted_test_rows": len(rows),
            "primary_source_family_hypotheses": len(primary),
            "primary_eligibility": "OOS/forecast/QLIKE/DM/forward/HAC-predictive experiment rows only; knowledge text excluded from primary correction, README regex used only when no structured JSON row exists for the same source, and diagnostics/intercepts/const/correlation/Granger/lead-lag plus IS/full-sample/descriptive rows are excluded.",
            "unique_source_groups": len({row.source_group for row in primary}),
            "unique_k_ids": len({row.k_id for row in primary if row.k_id}),
            "families": sorted({row.family for row in primary}),
        },
        "correction_policy": {
            "primary_unit": "best available p-value per (k_id_or_source_group, external_predictor_family)",
            "favorable_to_discovery": True,
            "harvey_screen": "abs(t_or_z) >= 3",
            "holm_alpha": 0.05,
            "bh_fdr_q": 0.10,
            "formal_romano_wolf_feasible": False,
            "formal_romano_wolf_blocker": "Historical artifacts do not store a common loss-differential/test-stat matrix for resampling dependence.",
            "rw_style_independent_maxT": "reported only as an independent-null maxT stepdown approximation, not formal Romano-Wolf",
        },
        "summary": {
            "raw_p_lt_0_05": sum(row.p_value <= 0.05 for row in primary),
            "harvey_abs_t_ge_3": sum(row.harvey_abs_t_ge_3 for row in primary),
            "bh_q10_pass": len(survivors_bh),
            "holm_05_pass": len(survivors_holm),
            "rw_style_05_pass": len(survivors_rw),
            "primary_rows_using_already_adjusted_p": adjusted_raw_sources,
        },
        "family_summary": family_summary,
        "top_20_by_raw_p": [asdict(row) for row in primary[:20]],
        "bh_q10_survivors": [asdict(row) for row in survivors_bh],
        "holm_05_survivors": [asdict(row) for row in survivors_holm],
        "rw_style_05_survivors": [asdict(row) for row in survivors_rw],
        "outputs": {
            "results_json": rel(RESULTS_PATH),
            "audit_csv": rel(AUDIT_CSV_PATH),
            "figure": rel(FIG_PATH),
        },
        "verdict": (
            "META_AUDIT_WITH_INFRA_GAP"
            if primary
            else "NO_CANDIDATE_ROWS_EXTRACTED"
        ),
        "interpretation": (
            "This run can answer the FDR/Holm summary-stat audit, but it cannot "
            "honestly claim a formal Romano-Wolf resampling result until old "
            "experiments persist aligned pointwise loss differentials."
        ),
    }


def main() -> int:
    np.random.seed(SEED)
    all_rows = load_file_rows() + load_knowledge_rows()
    # Remove exact duplicate extraction artifacts.
    deduped: list[TestRow] = []
    seen: set[tuple[Any, ...]] = set()
    for row in all_rows:
        key = (
            row.source_group,
            row.source_file,
            row.family,
            row.source_field_path,
            round(row.p_value, 12),
            round(row.abs_z, 8),
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(row)

    primary = select_primary(deduped)
    apply_corrections(primary)
    for row in deduped:
        row.selected_primary = False
    for row in primary:
        row.selected_primary = True

    write_audit_csv(deduped)
    make_figure(primary)
    result = summarize(deduped, primary)
    RESULTS_PATH.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result["summary"], ensure_ascii=False, indent=2))
    print(f"Wrote {RESULTS_PATH}")
    print(f"Wrote {AUDIT_CSV_PATH}")
    print(f"Wrote {FIG_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
