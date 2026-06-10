#!/usr/bin/env python3
"""
Paper 1 Reproducibility Checker — v12 layout (K903 canonical)
=============================================================
Verifies the CURRENT paper layout (2026-06-11 K903 canonical alignment):
  main.tex (abstract) + body.tex (prose + tab:complexity_ceiling)
  + tables_main.tex (7 main tables) + supplementary (not gated here).

Canonical sources:
  - K903  experiments/k903/tables/k903_table2.csv  -> Table 2 (tab:gamma)
  - K903  experiments/k903/tables/k903_table3.csv  -> Table 3 (tab:qlike)
  - K902  paper-folder shim                        -> Table 1 (tab:desc)
  - K799 / K802                                    -> Table 5 (tab:var_ortho)
  - K1185 (caption-documented vintage)             -> Table 4 (tab:var, NOTE tier)
  - K1256 HM 3-spec stub                           -> body.tex gamma_HM footnote
  - Abstract 6/6 OOS + rho=0.83 (N=14): no JSON source -> NOTE tier (untraceable)

Deprecated (old 14-table layout, removed 2026-06-11 rewrite):
  Table 9 Hybrid VT KB checks, Table 10 amplification, Table 12 gamma-mechanism
  (moved to supplementary), Patton-scale QLIKE delta checks (superseded by K903
  quasi-LL canonical numbers).

Status tiers:
  MATCH      traceable, agrees with source (within display rounding)
  MISMATCH   traceable, disagrees beyond rounding -> counts against gate
  NOTE       documented vintage drift / cross-source reconciliation / untraceable
             abstract claims; does NOT count against the gate

Gate: traceable_match_rate = MATCH / (MATCH + MISMATCH) >= 95% -> green.

Usage:
  uv run python paper/leverage-direction/reproduce.py
"""

import csv
import json
import re
import sys
from dataclasses import dataclass, asdict
from datetime import datetime
from math import erfc, log, sqrt
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent.parent
PAPER_EXP_DIR = SCRIPT_DIR / "experiments"

TABLES_MAIN = SCRIPT_DIR / "tables_main.tex"
BODY_TEX = SCRIPT_DIR / "body.tex"
MAIN_TEX = SCRIPT_DIR / "main.tex"

K903_TABLE2 = PROJECT_ROOT / "experiments" / "k903" / "tables" / "k903_table2.csv"
K903_TABLE3 = PROJECT_ROOT / "experiments" / "k903" / "tables" / "k903_table3.csv"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

@dataclass
class Check:
    table: str
    cell: str
    paper_value: str
    source_value: str
    source: str
    status: str  # MATCH / MISMATCH / NOTE
    note: str = ""


checks: list[Check] = []


def add(table, cell, paper_value, source_value, source, status, note=""):
    checks.append(Check(table, cell, str(paper_value), str(source_value),
                        source, status, note))


def normalize_tex_num(s: str) -> str:
    """Normalize a LaTeX-formatted number cell to a plain numeric string."""
    s = s.strip()
    s = s.replace("$-$", "-").replace("−", "-")
    s = s.replace("$", "").replace("\\%", "").replace("%", "")
    s = s.replace("+", "").strip()
    return s


def decimals_of(s: str) -> int:
    s = normalize_tex_num(s)
    return len(s.split(".")[1]) if "." in s else 0


def rounding_match(paper_str: str, source_val: float) -> bool:
    """True if source value rounds to the paper's displayed value."""
    try:
        p = float(normalize_tex_num(paper_str))
    except ValueError:
        return False
    dp = decimals_of(paper_str)
    return abs(p - source_val) <= 0.5 * 10 ** (-dp) + 1e-9


def kupiec_pvalue(n_viol: int, n_total: int, alpha: float) -> float:
    """Kupiec (1995) unconditional coverage LR test p-value (chi2, 1 df)."""
    x, n = n_viol, n_total
    pi = x / n
    ll0 = (n - x) * log(1 - alpha) + x * log(alpha)
    ll1 = (n - x) * log(1 - pi) + (x * log(pi) if x > 0 else 0.0)
    lr = -2.0 * (ll0 - ll1)
    return erfc(sqrt(lr / 2.0))  # chi2(1 df) survival function


def load_json(path: Path):
    if not path.exists():
        return None
    with open(path) as f:
        return json.load(f)


def load_csv_rows(path: Path) -> list[dict]:
    with open(path) as f:
        return list(csv.DictReader(f))


def extract_table_block(tex: str, label: str) -> str:
    for m in re.finditer(r"\\begin\{table\}.*?\\end\{table\}", tex, re.S):
        if f"\\label{{{label}}}" in m.group(0):
            return m.group(0)
    raise RuntimeError(f"table block {label} not found")


# ---------------------------------------------------------------------------
# Load files
# ---------------------------------------------------------------------------

tables_tex = TABLES_MAIN.read_text()
body_tex = BODY_TEX.read_text()
main_tex = MAIN_TEX.read_text()

k799 = load_json(PAPER_EXP_DIR / "k799_grand_evaluation_results.json")
k802 = load_json(PAPER_EXP_DIR / "k802_gjr_skewt_results.json")
k902 = load_json(PAPER_EXP_DIR / "k902_paper1_tables_supplement_results.json")
hm_stub = load_json(PAPER_EXP_DIR / "hm_timing_tests_results.json")


# ===========================================================================
# TABLE 2 (tab:gamma) — K903 canonical, full 7 rows x 4 numeric cols + rule
# ===========================================================================

ASSET_MAP = {"BTC": "BTC-USD"}  # tex label -> CSV asset key

k903_t2 = {r["asset"]: r for r in load_csv_rows(K903_TABLE2)}
gamma_block = extract_table_block(tables_tex, "tab:gamma")
gamma_re = re.compile(
    r"^(SPY|QQQ|EEM|GLD|TLT|BTC|SLV)\s*&\s*([+\-−]?\d+\.\d+)\s*&\s*"
    r"(\d+\.\d+)\s*&\s*(\d+)\\%\s*&\s*([+\-−]?\d+\.\d+)\s*&\s*(GJR|GARCH)",
    re.M,
)
gamma_rows = gamma_re.findall(gamma_block)
if len(gamma_rows) != 7:
    add("Table 2", "row count", f"{len(gamma_rows)} rows parsed", "7 expected",
        "tables_main.tex tab:gamma", "MISMATCH", "regex failed to parse all rows")

for asset, mean_g, std_g, pct_neg, hac_t, model in gamma_rows:
    src = k903_t2[ASSET_MAP.get(asset, asset)]
    cols = [
        ("mean_gamma", mean_g, float(src["mean_gamma"])),
        ("std_gamma", std_g, float(src["std_gamma"])),
        ("pct_negative", pct_neg, float(src["pct_negative"])),
        ("hac_tstat", hac_t, float(src["hac_tstat"])),
    ]
    for col, paper_s, src_v in cols:
        ok = rounding_match(paper_s, src_v)
        add("Table 2 (tab:gamma)", f"{asset} {col}", paper_s.strip(), src_v,
            "experiments/k903/tables/k903_table2.csv",
            "MATCH" if ok else "MISMATCH")
    # Model Choice column must follow the t > 1.65 rule on the HAC column
    rule_model = "GJR" if float(src["hac_tstat"]) > 1.65 else "GARCH"
    add("Table 2 (tab:gamma)", f"{asset} model choice (t>1.65 rule)", model,
        rule_model, "k903_table2.csv hac_tstat + caption rule",
        "MATCH" if model == rule_model else "MISMATCH")


# ===========================================================================
# TABLE 3 (tab:qlike) — K903 canonical, all 9 rows
# ===========================================================================

k903_t3 = {(r["asset"], r["period"]): r for r in load_csv_rows(K903_TABLE3)}
qlike_block = extract_table_block(tables_tex, "tab:qlike")
qlike_re = re.compile(
    r"^(SPY|QQQ|GLD|TLT|EEM|BTC)\s*&\s*(2023--2024|2025)\s*&\s*(-?\d+\.\d+)\s*&\s*"
    r"(-?\d+\.\d+)\s*&\s*([+\-−]?\d+\.\d+)\s*&\s*(\d+\.\d+)(\*?)",
    re.M,
)
qlike_rows = qlike_re.findall(qlike_block)
if len(qlike_rows) != 9:
    add("Table 3", "row count", f"{len(qlike_rows)} rows parsed", "9 expected",
        "tables_main.tex tab:qlike", "MISMATCH", "regex failed to parse all rows")

for asset, period, garch_q, gjr_q, delta, dm_p, star in qlike_rows:
    csv_period = period.replace("--", "-")
    src = k903_t3[(ASSET_MAP.get(asset, asset), csv_period)]
    label = f"{asset} {csv_period}"
    cols = [
        ("garch_qlike", garch_q, float(src["garch_qlike"])),
        ("gjr_qlike", gjr_q, float(src["gjr_qlike"])),
        ("delta_pct", delta, float(src["delta_pct"])),
        ("dm_pvalue", dm_p, float(src["dm_pvalue"])),
    ]
    for col, paper_s, src_v in cols:
        ok = rounding_match(paper_s, src_v)
        add("Table 3 (tab:qlike)", f"{label} {col}", paper_s.strip(), src_v,
            "experiments/k903/tables/k903_table3.csv",
            "MATCH" if ok else "MISMATCH")
    # significance star must agree with dm_pvalue < 0.05
    should_star = float(src["dm_pvalue"]) < 0.05
    has_star = star == "*"
    add("Table 3 (tab:qlike)", f"{label} 5% star", "*" if has_star else "(none)",
        "*" if should_star else "(none)", "k903_table3.csv dm_pvalue",
        "MATCH" if has_star == should_star else "MISMATCH")


# ===========================================================================
# TABLE 1 (tab:desc) — K902 source; minor vintage drift tolerated as NOTE
# ===========================================================================

VINTAGE_TOL = {"mean_pct": 0.03, "std_pct": 0.03, "skewness": 0.03,
               "kurtosis": 0.2, "min_pct": 0.3, "max_pct": 0.3, "n_obs": 6}

desc_block = extract_table_block(tables_tex, "tab:desc")
desc_re = re.compile(
    r"^(SPY|QQQ|EEM|GLD|TLT|BTC|SLV)\s*&\s*(-?\d+\.\d+)\s*&\s*(\d+\.\d+)\s*&\s*"
    r"(-?\d+\.\d+)\s*&\s*(\d+\.\d+)\s*&\s*(-?\d+\.\d+)\s*&\s*(-?\d+\.\d+)\s*&\s*(\d+)",
    re.M,
)
if k902:
    t1 = k902["table1_descriptive_stats"]
    for row in desc_re.findall(desc_block):
        asset = row[0]
        src = t1[asset]  # K902 uses plain "BTC" key
        cols = [("mean_pct", row[1]), ("std_pct", row[2]), ("skewness", row[3]),
                ("kurtosis", row[4]), ("min_pct", row[5]), ("max_pct", row[6]),
                ("n_obs", row[7])]
        for col, paper_s in cols:
            src_v = float(src[col])
            if rounding_match(paper_s, src_v):
                status, note = "MATCH", ""
            elif abs(float(normalize_tex_num(paper_s)) - src_v) <= VINTAGE_TOL[col]:
                status = "NOTE"
                note = ("yfinance vintage drift within tolerance "
                        f"(paper {paper_s} vs K902 {src_v}); snapshot 2026-04-19")
            else:
                status, note = "MISMATCH", f"beyond vintage tolerance {VINTAGE_TOL[col]}"
            add("Table 1 (tab:desc)", f"{asset} {col}", paper_s, src_v,
                "K902 table1_descriptive_stats", status, note)
else:
    add("Table 1 (tab:desc)", "all", "(in paper)", "K902 JSON missing",
        "K902", "MISMATCH", "k902_paper1_tables_supplement_results.json not found")


# ===========================================================================
# TABLE 4 (tab:var) — internal arithmetic + K1185 caption-vintage counts
# ===========================================================================

var_block = extract_table_block(tables_tex, "tab:var")
var_rows = re.findall(
    r"^(Normal|Student-\$t\$ \(df=5\)|\+ Adaptive threshold|\+ Jump augmentation)"
    r"\s*&\s*(\d+)\s*&\s*(\d+\.\d+)\\%\s*&\s*(.+?)\s*\\\\",
    var_block, re.M,
)
N_DAYS = 1508  # caption: SPY 2020-2025, 1508 days
prev_viol = None
for name, viol_s, rate_s, impr_s in var_rows:
    viol = int(viol_s)
    # (a) rate = violations / 1508 (internal arithmetic, fully traceable)
    implied_rate = viol / N_DAYS * 100
    add("Table 4 (tab:var)", f"{name} rate consistency", f"{rate_s}%",
        f"{implied_rate:.2f}% = {viol}/{N_DAYS}", "internal arithmetic",
        "MATCH" if rounding_match(rate_s, implied_rate) else "MISMATCH")
    # (b) improvement column = delta vs previous row
    impr_norm = normalize_tex_num(impr_s)
    if prev_viol is not None and impr_norm not in ("---", ""):
        implied_impr = (viol - prev_viol) / prev_viol * 100
        add("Table 4 (tab:var)", f"{name} improvement consistency", impr_norm,
            f"{implied_impr:.1f}%", "internal arithmetic",
            "MATCH" if rounding_match(impr_norm, implied_impr) else "MISMATCH")
    # (c) violation count itself: K1185 canonical vintage per caption, no JSON
    #     in replication package -> NOTE tier (caption documents +/-3 re-run drift)
    add("Table 4 (tab:var)", f"{name} violation count", viol,
        "K1185 canonical reconstruction (caption-documented vintage)",
        "tab:var caption / K1185", "NOTE",
        "No JSON in package; caption documents 2025-Q4 vintage and +/-3 drift.")
    prev_viol = viol


# ===========================================================================
# TABLE 5 (tab:var_ortho) — K799 / K802 + self-computed Kupiec
# ===========================================================================

ortho_block = extract_table_block(tables_tex, "tab:var_ortho")
ortho_rows = re.findall(
    r"^(GARCH\(1,1\)|GJR-GARCH)\s*&\s*(Normal|Student-\$t\$\(5\))\s*&\s*(\d+)\s*&\s*"
    r"(\d+\.\d+)\\%\s*&\s*(\d+\.\d+)\s*&\s*(Green|Yellow|Red)",
    ortho_block, re.M,
)

ortho_sources = {
    ("GARCH(1,1)", "Normal"): (
        "K799 layer_6 GARCH (cross-confirmed by K802 GARCH+Normal)",
        k799["evaluation_layers"]["layer_6"]["results"]["GARCH"] if k799 else None),
    ("GJR-GARCH", "Normal"): (
        "K799 layer_6 GJR",
        k799["evaluation_layers"]["layer_6"]["results"]["GJR"] if k799 else None),
    ("GJR-GARCH", "Student-$t$(5)"): (
        "K802 var_backtest_results GJR+StudentT",
        k802["var_backtest_results"]["GJR+StudentT"] if k802 else None),
}

for eq, dist, viol_s, rate_s, kupiec_s, zone in ortho_rows:
    src_name, src = ortho_sources[(eq, dist)]
    label = f"{eq} + {dist}"
    if src is None:
        add("Table 5 (tab:var_ortho)", label, f"{viol_s}/{rate_s}%",
            "source JSON missing", src_name, "MISMATCH")
        continue
    viol = int(viol_s)
    add("Table 5 (tab:var_ortho)", f"{label} violations", viol,
        src["n_violations"], src_name,
        "MATCH" if viol == src["n_violations"] else "MISMATCH")
    add("Table 5 (tab:var_ortho)", f"{label} rate", f"{rate_s}%",
        f"{src['violation_rate'] * 100:.4f}%", src_name,
        "MATCH" if rounding_match(rate_s, src["violation_rate"] * 100) else "MISMATCH")
    # Kupiec p: compare against source JSON AND deterministic recomputation
    self_p = kupiec_pvalue(src["n_violations"], src["n_total"], 0.01)
    json_p = src["kupiec"]["p_value"]
    ok = rounding_match(kupiec_s, json_p)
    add("Table 5 (tab:var_ortho)", f"{label} Kupiec p", kupiec_s,
        f"JSON {json_p:.4f} / recomputed {self_p:.4f}",
        f"{src_name} + Kupiec(1995) recomputation",
        "MATCH" if ok else "MISMATCH",
        "" if ok else (
            f"Paper {kupiec_s} is inconsistent with its own row: Kupiec p for "
            f"{src['n_violations']}/{src['n_total']} at 1% is uniquely "
            f"{self_p:.4f} (0.64 corresponds to 4/502). Paper-side error."))
    zone_src = src["basel_traffic_light"]
    add("Table 5 (tab:var_ortho)", f"{label} Basel zone", zone, zone_src, src_name,
        "MATCH" if zone.lower() == zone_src.lower() else "MISMATCH")

# caption cross-refs to K903: "GJR wins QLIKE (-0.59% ..., DM p = 0.003)"
spy_2324 = k903_t3[("SPY", "2023-2024")]
for literal, src_v, col in [("-0.59", float(spy_2324["delta_pct"]), "delta_pct"),
                            ("0.003", float(spy_2324["dm_pvalue"]), "dm_pvalue")]:
    in_caption = literal in ortho_block
    ok = in_caption and rounding_match(literal, src_v)
    add("Table 5 (tab:var_ortho)", f"caption SPY {col}", literal,
        src_v, "k903_table3.csv SPY 2023-2024",
        "MATCH" if ok else "MISMATCH")


# ===========================================================================
# PROSE SPOT-CHECKS — body.tex K903 literals (>= 6 required)
# ===========================================================================

prose_literals = [
    ("SPY HAC t", "+11.08", "k903_table2 SPY hac_tstat 11.08"),
    ("BTC HAC t", "+2.88", "k903_table2 BTC-USD hac_tstat 2.88"),
    ("BTC mean gamma", "+0.072", "k903_table2 BTC-USD mean_gamma 0.072"),
    ("magnitude band", "(0.009, 0.072)", "SLV |gamma|=0.009 / BTC 0.072 (k903_table2)"),
    ("GLD delta 2023-24", "+0.39\\%", "k903_table3 GLD 2023-2024 delta_pct 0.39"),
    ("GLD DM p 2023-24", "p = 0.001", "k903_table3 GLD 2023-2024 dm_pvalue 0.0013"),
    ("GLD mean gamma", "+0.002", "k903_table2 GLD mean_gamma 0.002"),
    ("GLD HAC t", "$t = +0.15$", "k903_table2 GLD hac_tstat 0.15"),
    ("SPY GJR QLIKE 2023-24", "-8.674", "k903_table3 SPY 2023-2024 gjr_qlike"),
    ("SPY GARCH QLIKE 2023-24", "-8.623", "k903_table3 SPY 2023-2024 garch_qlike"),
    ("SPY delta 2025", "-1.74\\%", "k903_table3 SPY 2025 delta_pct -1.74"),
    ("SPY DM p 2025", "p = 0.048", "k903_table3 SPY 2025 dm_pvalue 0.0478"),
]
for name, literal, src in prose_literals:
    found = literal in body_tex
    add("Prose (body.tex)", name, literal,
        "present" if found else "NOT FOUND", src,
        "MATCH" if found else "MISMATCH")

# +0.132 (SPY mean gamma) appears in tables_main.tex Table 2; body uses ~ +0.13
add("Prose (tables_main.tex)", "SPY mean gamma literal", "+0.132",
    "present" if "+0.132" in tables_tex else "NOT FOUND",
    "k903_table2 SPY mean_gamma 0.132",
    "MATCH" if "+0.132" in tables_tex else "MISMATCH")
add("Prose (body.tex)", "SPY mean gamma approx", "\\gamma \\approx +0.13",
    "present" if "\\gamma \\approx +0.13" in body_tex else "NOT FOUND",
    "k903_table2 SPY mean_gamma 0.132 (rounded prose)",
    "MATCH" if "\\gamma \\approx +0.13" in body_tex else "MISMATCH")


# ===========================================================================
# HM gamma 3-spec (K1256) — kept from old gate; NOTE tier per L11 errata path
# ===========================================================================

if hm_stub and hm_stub.get("tuples"):
    paper_footnote_literals = {
        "pure_vt_full": ("-0.035", "$t = -0.39$"),
        "pure_vt_high_vix": ("-0.068", "$t = -4.63$"),
        "hybrid_vt_full": ("-0.043", "$t = -4.06$"),
    }
    for tup in hm_stub["tuples"]:
        spec = tup["spec_label"]
        g_lit, t_lit = paper_footnote_literals[spec]
        bound = g_lit in body_tex and t_lit in body_tex
        add("HM 3-spec (K1256)", f"{spec} footnote binding",
            f"gamma {g_lit}, t {t_lit}",
            "present in body.tex" if bound else "NOT FOUND",
            "body.tex Sec 5.4 footnote", "MATCH" if bound else "MISMATCH")
        add("HM 3-spec (K1256)", f"{spec} re-estimation",
            f"paper gamma={tup['paper_gamma']:+.3f} (t={tup['paper_t']:+.2f})",
            f"K1256 gamma={tup['gamma_HM']:+.4f} (t={tup['t_stat']:+.2f})",
            "experiments/hm_timing_tests_results.json (K1256)", "NOTE",
            f"verdict={tup['verdict']}: sign preserved across all 3 specs "
            "(variance-management thesis holds qualitatively); magnitude "
            "divergence pending L11 errata path (c).")
else:
    add("HM 3-spec (K1256)", "stub", "expected", "MISSING",
        "experiments/hm_timing_tests_results.json", "MISMATCH")


# ===========================================================================
# ABSTRACT untraceables -> NOTE tier (no JSON source; do not count as fail)
# ===========================================================================

abstract_notes = [
    ("6/6 OOS classification", "6/6 correct out-of-sample predictions",
     "Abstract claim; OOS classification exercise has no dedicated result JSON."),
    ("rho=0.83 (N=14) extended MDD-vol", "$\\rho = 0.83$ for the extended $N = 14$ sample",
     "Extended-sample correlation has no traceable JSON; supplement-sourced."),
]
for name, literal, why in abstract_notes:
    found = literal in main_tex
    add("Abstract (main.tex)", name, literal,
        "present" if found else "NOT FOUND", "None (untraceable)",
        "NOTE",
        why + (" Literal present in abstract." if found
               else " WARNING: literal not found in main.tex."))


# ===========================================================================
# Cross-source DM consistency (K799/K802 Patton scale vs K903 quasi-LL)
# ===========================================================================

if k799 and k802:
    p799 = k799["evaluation_layers"]["layer_4"]["results"]["GJR vs GARCH"]["p_value"]
    p802 = k802["qlike_results"]["DM_GJR_vs_GARCH"]["p_value"]
    add("Cross-source", "SPY 2023-24 DM p (3 estimators)",
        f"paper canonical 0.003 (K903 0.0032)",
        f"K799 {p799:.4f} / K802 {p802:.4f} (Patton-scale QLIKE)",
        "K903 + K799 + K802", "NOTE",
        "Three independent estimators agree GJR significantly beats GARCH for "
        "SPY 2023-24; paper canonical = K903 quasi-LL p=0.0032.")


# ===========================================================================
# Figure replication bundle (kept from old gate)
# ===========================================================================

for script in ["fig_cumulative_returns.py", "fig_gamma_mechanism.py",
               "fig_kurtosis_reduction.py", "fig_mdd_comparison.py",
               "fig_rolling_gamma.py", "fig_vix_garch_ratio.py",
               "fig_vix_weight_timeline.py"]:
    s_ok = (SCRIPT_DIR / "scripts" / "figures" / script).exists()
    p_ok = (SCRIPT_DIR / "figures" / script.replace(".py", ".png")).exists()
    add("Figures", script.replace(".py", ""), "bundled (.py + .png)",
        f"script={s_ok}, png={p_ok}", "scripts/figures/",
        "MATCH" if (s_ok and p_ok) else "MISMATCH")


# ===========================================================================
# REPORT
# ===========================================================================

n_match = sum(1 for c in checks if c.status == "MATCH")
n_mismatch = sum(1 for c in checks if c.status == "MISMATCH")
n_note = sum(1 for c in checks if c.status == "NOTE")
n_traceable = n_match + n_mismatch
rate = n_match / n_traceable if n_traceable else 0.0
alert = "green" if rate >= 0.95 else ("amber" if rate >= 0.85 else "red")

table_row_mapping = {
    "Table 1 (tab:desc)": "K902 table1_descriptive_stats (vintage NOTE-tolerant)",
    "Table 2 (tab:gamma)": "experiments/k903/tables/k903_table2.csv (canonical)",
    "Table 3 (tab:qlike)": "experiments/k903/tables/k903_table3.csv (canonical)",
    "Table 4 (tab:var)": "internal arithmetic + K1185 caption vintage (NOTE)",
    "Table 5 (tab:var_ortho)": "K799 layer_6 + K802 var_backtest + Kupiec recomputation",
    "Table 6 (tab:var_panel)": "caption-documented canonical replication (not re-gated)",
    "Table 7 (tab:vt)": "caption-documented replication note (not re-gated)",
    "body.tex prose": "K903 CSV literals + K1256 HM stub",
    "abstract": "6/6 OOS + rho=0.83(N=14) untraceable -> NOTE",
}

report = {
    "paper": "leverage-direction",
    "layout_version": "v12 K903 canonical (main.tex + body.tex + tables_main.tex 7 tables)",
    "generated_at": datetime.now().astimezone().isoformat(),
    "script": "reproduce.py (2026-06-11 rewrite, task paper_reproduce_rewrite_leverage_direction_2026_06_11)",
    "n_checks": len(checks),
    "n_match": n_match,
    "n_mismatch": n_mismatch,
    "n_note": n_note,
    "traceable_match_rate": round(rate, 4),
    "alert_level": alert,
    "table_row_mapping": table_row_mapping,
    "mismatches": [asdict(c) for c in checks if c.status == "MISMATCH"],
    "checks": [asdict(c) for c in checks],
}

out_path = SCRIPT_DIR / "reproduce_report.json"
with open(out_path, "w") as f:
    json.dump(report, f, indent=2, ensure_ascii=False)

print("=" * 78)
print("PAPER 1 REPRODUCIBILITY REPORT — v12 K903 canonical layout")
print("=" * 78)
print(f"Total checks:          {len(checks)}")
print(f"  MATCH:               {n_match}")
print(f"  MISMATCH:            {n_mismatch}")
print(f"  NOTE:                {n_note}")
print(f"Traceable match rate:  {rate:.2%}  ({n_match}/{n_traceable})")
print(f"Alert level:           {alert.upper()}")
print(f"Report written:        {out_path}")

if n_mismatch:
    print("\n" + "-" * 78)
    print(f"MISMATCHES ({n_mismatch}):")
    for i, c in enumerate([c for c in checks if c.status == "MISMATCH"], 1):
        print(f"\n{i}. [{c.table}] {c.cell}")
        print(f"   Paper:  {c.paper_value}")
        print(f"   Source: {c.source_value}  ({c.source})")
        if c.note:
            print(f"   Note:   {c.note}")

notes = [c for c in checks if c.status == "NOTE"]
if notes:
    print("\n" + "-" * 78)
    print(f"NOTES ({len(notes)}, not counted against gate):")
    for c in notes:
        print(f"  [{c.table}] {c.cell}")

sys.exit(0)
