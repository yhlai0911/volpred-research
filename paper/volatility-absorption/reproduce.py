#!/usr/bin/env python3
"""
Paper 8 Reproducibility Check: "Volatility Absorption Hypothesis"
=================================================================
Loads experiment result JSONs, copies them to paper/volatility-absorption/experiments/,
and verifies key table numbers against the paper's claimed values.

Based on audit: paper/volatility-absorption/reviews/audit_step1_2.md
Paper version: v2 (main_v2.tex, 38 pages, 37 citations)

KNOWN ISSUES (from audit):
- CRITICAL: No .py scripts for K716-K722 (only _results.json)
- HIGH: NFP Table 6 has systematic discrepancies with K741
- HIGH: 63+ numerical claims untraceable (Tables 9-10, t-stats, etc.)
- MEDIUM: Shock type sample sizes (Table 5 N column) don't match K721
"""

import json
import os
import shutil
import sys
import math
from pathlib import Path

# ── Paths ───────────────────────────────────────────────────────────────────
PROJ = Path(__file__).resolve().parent.parent.parent
EXP_DIR = PROJ / "experiments"
PAPER_EXP = Path(__file__).resolve().parent / "experiments"
PAPER_EXP.mkdir(exist_ok=True)

# ── Experiment mapping ──────────────────────────────────────────────────────
EXPERIMENT_FILES = {
    "K716": "k716_results.json",
    "K718": "k718_results.json",
    "K719": "k719_results.json",
    "K720": "k720_results.json",
    "K721": "k721_results.json",
    "K722": "k722_results.json",
    "K741": "k741_nfp_event_study_results.json",
}


# ── Helpers ─────────────────────────────────────────────────────────────────
def load_json(path: Path):
    if not path.exists():
        return None
    with open(path) as f:
        return json.load(f)


def approx_eq(a, b, tol=0.02):
    """Check if a and b are approximately equal (relative tolerance)."""
    if a is None or b is None:
        return False
    if a == 0 and b == 0:
        return True
    if a == 0:
        return abs(b) < tol
    return abs(a - b) / max(abs(a), abs(b)) < tol


class Check:
    def __init__(self, table, field, paper_val, source_val, source_exp, severity="normal"):
        self.table = table
        self.field = field
        self.paper_val = paper_val
        self.source_val = source_val
        self.source_exp = source_exp
        self.severity = severity  # "normal", "high", "critical"

    @property
    def match(self):
        if self.source_val is None:
            return "UNTRACEABLE"
        if isinstance(self.paper_val, str) or isinstance(self.source_val, str):
            return "MATCH" if str(self.paper_val) == str(self.source_val) else "MISMATCH"
        return "MATCH" if approx_eq(self.paper_val, self.source_val) else "MISMATCH"


# ── Main verification ──────────────────────────────────────────────────────
def main():
    results = {}
    checks = []
    missing = []

    # ── Step 1: Copy experiment JSONs ───────────────────────────────────────
    print("=" * 72)
    print("PAPER 8 REPRODUCIBILITY CHECK")
    print("=" * 72)
    print(f"\nSource: {EXP_DIR}")
    print(f"Target: {PAPER_EXP}\n")

    for k, fname in EXPERIMENT_FILES.items():
        src = EXP_DIR / fname
        dst = PAPER_EXP / fname
        if src.exists():
            shutil.copy2(src, dst)
            results[k] = load_json(src)
            print(f"  [OK] {k}: {fname}")
        else:
            missing.append(k)
            results[k] = None
            print(f"  [MISSING] {k}: {fname}")

    print(f"\nLoaded: {sum(1 for v in results.values() if v is not None)}/{len(EXPERIMENT_FILES)}")
    if missing:
        print(f"Missing: {', '.join(missing)}")

    # ── Check for .py scripts ───────────────────────────────────────────────
    print("\n" + "=" * 72)
    print("REPLICATION SCRIPT CHECK")
    print("=" * 72)

    scripts_found = 0
    scripts_missing_list = []
    for k in EXPERIMENT_FILES:
        # Try common naming patterns
        patterns = [
            EXP_DIR / f"{k.lower()}.py",
            EXP_DIR / f"{k.lower()}_*.py",
        ]
        found = False
        for p in patterns:
            import glob
            matches = glob.glob(str(p))
            if matches:
                for m in matches:
                    shutil.copy2(m, PAPER_EXP / os.path.basename(m))
                    print(f"  [OK] {k}: {os.path.basename(m)}")
                found = True
                scripts_found += 1
                break
        if not found:
            scripts_missing_list.append(k)
            print(f"  [NO SCRIPT] {k}: No .py file found")

    print(f"\n  Scripts found: {scripts_found}/{len(EXPERIMENT_FILES)}")
    if scripts_missing_list:
        print(f"  CRITICAL: Missing scripts for {', '.join(scripts_missing_list)}")
        print("  These experiments CANNOT be independently re-run.")

    # ── Step 2: Table 3 — SAR Core (K716) ──────────────────────────────────
    print("\n" + "=" * 72)
    print("TABLE 3: SAR by VIX Regime (K716)")
    print("=" * 72)

    k716 = results.get("K716")
    if k716:
        # Paper Table 3 values
        paper_t3 = {
            "calm (<15)": {"shock_days": 34, "shock_abs_r": 1.24, "normal_abs_r": 0.39, "SAR": 3.16},
            "normal (15-20)": {"shock_days": 168, "shock_abs_r": 1.44, "normal_abs_r": 0.52, "SAR": 2.77},
            "elevated (20-25)": {"shock_days": 189, "shock_abs_r": 1.64, "normal_abs_r": 0.69, "SAR": 2.37},
            "high (25-30)": {"shock_days": 132, "shock_abs_r": 1.93, "normal_abs_r": 0.83, "SAR": 2.32},
            "crisis (>30)": {"shock_days": 244, "shock_abs_r": 2.99, "normal_abs_r": 1.23, "SAR": 2.43},
        }

        # K716 uses slightly different key names — try common patterns
        for regime_key, paper_vals in paper_t3.items():
            # Try exact key first
            src = k716.get(regime_key)
            if src is None:
                # Try case-insensitive
                for key in k716:
                    if key.lower().startswith(regime_key.split()[0].lower()):
                        src = k716[key]
                        break

            if src and isinstance(src, dict):
                checks.append(Check("T3", f"{regime_key} shock_days", paper_vals["shock_days"],
                                     src.get("shock_days"), "K716"))
                checks.append(Check("T3", f"{regime_key} shock_|r|", paper_vals["shock_abs_r"],
                                     src.get("shock_abs_r"), "K716"))
                checks.append(Check("T3", f"{regime_key} normal_|r|", paper_vals["normal_abs_r"],
                                     src.get("normal_abs_r"), "K716"))
                checks.append(Check("T3", f"{regime_key} SAR", paper_vals["SAR"],
                                     src.get("ratio"), "K716"))
            else:
                for field in ["shock_days", "shock_|r|", "normal_|r|", "SAR"]:
                    checks.append(Check("T3", f"{regime_key} {field}", paper_vals.get(field.replace("|", "abs_")),
                                         None, "K716"))

        # Regression slope
        checks.append(Check("T3", "NSI regression slope", -0.00028,
                             k716.get("regression_normalized_slope"), "K716"))
    else:
        print("  K716 not loaded — cannot verify Table 3")

    # ── Step 3: Table 4 — Cross-Asset Absorption (K718) ────────────────────
    print("\n" + "=" * 72)
    print("TABLE 4: Cross-Asset Absorption Coefficients (K718)")
    print("=" * 72)

    k718 = results.get("K718")
    if k718:
        paper_t4 = {
            "SPY": {"slope": -0.00028, "t_stat": -3.42},
            "GLD": {"slope": -0.00043, "t_stat": -4.17},
            "TLT": {"slope": -0.00044, "t_stat": -3.89},
            "0050.TW": {"slope": 0.00019, "t_stat": 1.62},
        }

        for asset, paper_vals in paper_t4.items():
            asset_data = k718.get(asset, {})
            checks.append(Check("T4", f"{asset} slope", paper_vals["slope"],
                                 asset_data.get("normalized_slope"), "K718"))
            # t-stats are NOT stored in K718 JSON
            checks.append(Check("T4", f"{asset} t-stat", paper_vals["t_stat"],
                                 None, "K718 (not stored)"))

        # 0050.TW N
        tw_data = k718.get("0050.TW", {})
        checks.append(Check("T4", "0050.TW n_shocks", 612,
                             tw_data.get("n_shocks"), "K718"))
    else:
        print("  K718 not loaded — cannot verify Table 4")

    # ── Step 4: Table 5 — Shock Types (K721) ──────────────────────────────
    print("\n" + "=" * 72)
    print("TABLE 5: Absorption by Shock Type (K721)")
    print("*** MEDIUM: Sample sizes N don't match K721 ***")
    print("=" * 72)

    k721 = results.get("K721")
    if k721:
        paper_t5 = {
            "rate-shock": {
                "absorption": 0.019,
                "N": 127,
                "t_stat": 2.87,
            },
            "risk-off": {
                "absorption": 0.007,
                "N": 203,
                "t_stat": 1.94,
            },
            "geopolitical": {
                "absorption": -0.003,
                "N": 89,
                "t_stat": -0.68,
            },
        }

        for shock_type, paper_vals in paper_t5.items():
            src = k721.get(shock_type, {})

            # Absorption = low_vix_norm - high_vix_norm
            low_norm = src.get("low_vix_norm")
            high_norm = src.get("high_vix_norm")
            if low_norm is not None and high_norm is not None:
                computed_absorption = round(low_norm - high_norm, 3)
            else:
                computed_absorption = None

            checks.append(Check("T5", f"{shock_type} absorption", paper_vals["absorption"],
                                 computed_absorption, "K721"))

            # N — known discrepancy
            n_low = src.get("n_low", 0)
            n_high = src.get("n_high", 0)
            k721_total = n_low + n_high if n_low and n_high else None
            checks.append(Check("T5", f"{shock_type} N (paper vs K721 n_low+n_high)",
                                 paper_vals["N"], k721_total, "K721", severity="high"))

            # t-stat — NOT stored in K721
            checks.append(Check("T5", f"{shock_type} t-stat", paper_vals["t_stat"],
                                 None, "K721 (not stored)"))
    else:
        print("  K721 not loaded — cannot verify Table 5")

    # ── Step 5: Table 6 — NFP (K741) ───────────────────────────────────────
    print("\n" + "=" * 72)
    print("TABLE 6: NFP Day Volatility (K741)")
    print("*** HIGH: Known systematic discrepancies ***")
    print("=" * 72)

    k741 = results.get("K741")
    if k741:
        pa = k741.get("part_a_historical", {})
        pb = k741.get("part_b_vix_regimes", {})

        # Overall metrics
        checks.append(Check("T6", "Total NFP days", 195, pa.get("n_nfp"), "K741"))
        checks.append(Check("T6", "Overall ratio", 1.17,
                             pa.get("ratio_vs_friday", pa.get("ratio_vs_all")), "K741", severity="high"))
        checks.append(Check("T6", "Overall p-value", 0.037,
                             pa.get("p_vs_friday", pa.get("p_vs_all")), "K741", severity="high"))

        # VIX regime breakdown
        paper_regimes = {
            "Low (VIX<15)": {"n": 63, "abs_r": 0.499},
            "Medium (15-20)": {"n": 76, "abs_r": 0.784},
            "Elevated (20-25)": {"n": 27, "abs_r": 1.053},
            "High (VIX>=25)": {"n": 28, "abs_r": 1.523},
        }

        for regime, paper_vals in paper_regimes.items():
            src = pb.get(regime, {})
            checks.append(Check("T6", f"NFP {regime} n", paper_vals["n"],
                                 src.get("n"), "K741", severity="high"))
            checks.append(Check("T6", f"NFP {regime} |r|%", paper_vals["abs_r"],
                                 src.get("mean_abs_return_pct"), "K741", severity="high"))

        # Per-regime ratios and t-stats NOT stored in K741
        print("\n  NOTE: Per-regime ratios and t-statistics NOT stored in K741 JSON")
        print("  The paper's per-regime ratios (1.24x, 1.30x, 1.18x, 0.95x) are untraceable")
    else:
        print("  K741 not loaded — cannot verify Table 6")

    # ── Step 6: Table 7 — VRP by Regime (K720) ────────────────────────────
    print("\n" + "=" * 72)
    print("TABLE 7: Variance Risk Premium by VIX Regime (K720)")
    print("=" * 72)

    k720 = results.get("K720")
    if k720:
        # K720 is very sparse: only vrp_flip_confirmed and direction_corr
        checks.append(Check("T7", "VRP direction corr", 0.028,
                             k720.get("direction_corr"), "K720"))
        # Paper reports: Calm +3.5%, Elevated +3.1%, High +2.8%
        # Only boundary values can be partially verified from knowledge entry
        checks.append(Check("T7", "Calm VRP +3.5%", 3.5, None, "K720 (not in JSON)"))
        checks.append(Check("T7", "Elevated VRP +3.1%", 3.1, None, "K720 (not in JSON)"))
        checks.append(Check("T7", "High VRP +2.8%", 2.8, None, "K720 (not in JSON)"))
        print("  K720 JSON is sparse — only vrp_flip_confirmed + direction_corr stored")
        print("  VRP regime values (3.5%, 3.1%, 2.8%) are NOT in the JSON")
    else:
        print("  K720 not loaded — cannot verify Table 7")

    # ── Step 7: Table 8 — Hedging Cost-Benefit (K719) ──────────────────────
    print("\n" + "=" * 72)
    print("TABLE 8: Hedging Cost-Benefit Ratio (K719)")
    print("=" * 72)

    k719 = results.get("K719")
    if k719:
        # K719 is mostly qualitative — only experiment citations + implications
        # Paper reports: Calm CB=13.7x, Elevated CB=8.0x, High CB=3.6x
        # From knowledge entry: "hedging payoff ratio 13.7x -> 3.6x"
        checks.append(Check("T8", "Calm CB 13.7x", 13.7, None, "K719 (not in JSON)"))
        checks.append(Check("T8", "Elevated CB 8.0x", 8.0, None, "K719 (not in JSON)"))
        checks.append(Check("T8", "High CB 3.6x", 3.6, None, "K719 (not in JSON)"))
        print("  K719 JSON is qualitative — no numerical cost-benefit data stored")
        print("  Only verifiable from knowledge entry text: '13.7x -> 3.6x'")
    else:
        print("  K719 not loaded — cannot verify Table 8")

    # ── Step 8: Tables 9-10 — Robustness (FULLY UNTRACEABLE) ──────────────
    print("\n" + "=" * 72)
    print("TABLES 9-10: Robustness (Alternative Thresholds + Sub-Period)")
    print("*** FULLY UNTRACEABLE — No experiment JSON ***")
    print("=" * 72)

    # Paper Table 9: Alternative shock thresholds
    paper_t9 = [
        {"tau": 1.0, "N": 1842, "beta": -0.00015},
        {"tau": 1.5, "N": 1287, "beta": -0.00022},
        {"tau": 2.0, "N": 893, "beta": -0.00028},
        {"tau": 2.5, "N": 614, "beta": -0.00033},
        {"tau": 3.0, "N": 417, "beta": -0.00041},
    ]
    for row in paper_t9:
        checks.append(Check("T9", f"tau={row['tau']} N={row['N']} beta={row['beta']}",
                             row["beta"], None, "No experiment"))

    # Paper Table 10: Sub-period stability
    paper_t10 = [
        {"period": "2006-2012", "N": 378, "beta": -0.00035},
        {"period": "2013-2019", "N": 198, "beta": -0.00018},
        {"period": "2020-2026", "N": 317, "beta": -0.00031},
    ]
    for row in paper_t10:
        checks.append(Check("T10", f"{row['period']} N={row['N']} beta={row['beta']}",
                             row["beta"], None, "No experiment"))

    # Internal consistency: sub-period N totals
    total_subperiod_n = sum(r["N"] for r in paper_t10)
    print(f"  Internal consistency: Sub-period N total = {total_subperiod_n}")
    print(f"  Expected (matches tau=2.0 N): 893")
    print(f"  Match: {'YES' if total_subperiod_n == 893 else 'NO'}")

    # ── Step 9: Textual Claims ──────────────────────────────────────────────
    print("\n" + "=" * 72)
    print("KEY TEXTUAL CLAIMS")
    print("=" * 72)

    if k716:
        checks.append(Check("Text", "NSI slope", -0.00028,
                             k716.get("regression_normalized_slope"), "K716"))
        checks.append(Check("Text", "Conclusion: paralysis", "paralysis",
                             k716.get("conclusion"), "K716"))

    # Section 6.2-6.3 VT performance (cited as "prior work", no experiment ID)
    checks.append(Check("Text", "VT overlay Sharpe 0.53 vs 0.68", 0.53, None, "Unlinked prior work"))
    checks.append(Check("Text", "DM t=-2.81", -2.81, None, "Unlinked prior work"))
    checks.append(Check("Text", "Daily rebal Sharpe 1.42", 1.42, None, "Unlinked prior work"))
    checks.append(Check("Text", "Monthly rebal Sharpe 0.82", 0.82, None, "Unlinked prior work"))

    # Section 7.3 alternative normalization
    checks.append(Check("Text", "beta_RV=-0.0031", -0.0031, None, "No experiment"))
    checks.append(Check("Text", "t=-2.76 (RV norm)", -2.76, None, "No experiment"))

    # Section 7.4 controlled regression
    checks.append(Check("Text", "beta=-0.00025 (controlled)", -0.00025, None, "No experiment"))
    checks.append(Check("Text", "t=-3.14 (controlled)", -3.14, None, "No experiment"))

    # ── Summary ─────────────────────────────────────────────────────────────
    print("\n" + "=" * 72)
    print("VERIFICATION SUMMARY")
    print("=" * 72)

    by_table = {}
    for c in checks:
        by_table.setdefault(c.table, []).append(c)

    total_match = 0
    total_mismatch = 0
    total_untraceable = 0

    for table, table_checks in sorted(by_table.items()):
        matches = sum(1 for c in table_checks if c.match == "MATCH")
        mismatches = sum(1 for c in table_checks if c.match == "MISMATCH")
        untraceables = sum(1 for c in table_checks if c.match == "UNTRACEABLE")
        total = len(table_checks)
        total_match += matches
        total_mismatch += mismatches
        total_untraceable += untraceables

        status = "PASS" if mismatches == 0 and untraceables < total else "ISSUES"
        print(f"\n  {table}: {matches}/{total} match, {mismatches} mismatch, "
              f"{untraceables} untraceable  [{status}]")

        for c in table_checks:
            if c.match == "MISMATCH":
                sev = f" [{c.severity.upper()}]" if c.severity != "normal" else ""
                print(f"    !! {c.field}: paper={c.paper_val}, source={c.source_val} ({c.source_exp}){sev}")
            elif c.match == "UNTRACEABLE":
                print(f"    ?? {c.field}: paper={c.paper_val} ({c.source_exp})")

    print(f"\n{'─' * 72}")
    print(f"  TOTAL: {total_match} MATCH, {total_mismatch} MISMATCH, "
          f"{total_untraceable} UNTRACEABLE out of {len(checks)} checks")
    pct_verified = total_match / len(checks) * 100 if checks else 0
    print(f"  Verification rate: {pct_verified:.1f}%")

    # ── Critical issues summary ─────────────────────────────────────────────
    print(f"\n{'─' * 72}")
    print("  CRITICAL ISSUES:")
    print(f"  1. No .py scripts for {', '.join(scripts_missing_list)} — core experiments not replicable")
    print(f"  2. Tables 9-10 FULLY UNTRACEABLE — {sum(1 for c in checks if c.table in ('T9','T10'))} claims")
    print(f"  3. Table 6 (NFP) has systematic discrepancies with K741 data")
    high_mismatches = [c for c in checks if c.match == "MISMATCH" and c.severity == "high"]
    if high_mismatches:
        print(f"  4. {len(high_mismatches)} HIGH-severity mismatches in Table 5/6")

    print(f"\n  RECOMMENDATIONS:")
    print(f"  1. Create replication scripts for K716, K718, K720, K721")
    print(f"  2. Re-run K741 with corrected NFP date identification")
    print(f"  3. Run robustness checks as dedicated experiment, save results")
    print(f"  4. Store t-statistics in experiment JSONs")
    print(f"  5. Link 'prior work' claims to specific K-numbers")

    # ── Save report ─────────────────────────────────────────────────────────
    report = {
        "paper": "volatility-absorption",
        "paper_version": "v2",
        "total_checks": len(checks),
        "matches": total_match,
        "mismatches": total_mismatch,
        "untraceable": total_untraceable,
        "verification_rate": f"{pct_verified:.1f}%",
        "critical_flags": [
            f"No .py scripts for {', '.join(scripts_missing_list)}",
            "Tables 9-10 fully untraceable",
            "Table 6 NFP systematic discrepancies",
            "Table 5 N column methodology unclear",
        ],
        "experiments_loaded": [k for k, v in results.items() if v is not None],
        "experiments_missing": missing,
        "scripts_found": scripts_found,
        "scripts_missing": scripts_missing_list,
        "table_details": {},
    }
    for table, table_checks in sorted(by_table.items()):
        report["table_details"][table] = {
            "total": len(table_checks),
            "match": sum(1 for c in table_checks if c.match == "MATCH"),
            "mismatch": sum(1 for c in table_checks if c.match == "MISMATCH"),
            "untraceable": sum(1 for c in table_checks if c.match == "UNTRACEABLE"),
            "issues": [
                {"field": c.field, "paper": c.paper_val, "source": c.source_val,
                 "exp": c.source_exp, "severity": c.severity}
                for c in table_checks if c.match in ("MISMATCH", "UNTRACEABLE")
            ],
        }

    report_path = Path(__file__).resolve().parent / "reproduce_report.json"
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2, default=str)
    print(f"\n  Report saved: {report_path}")

    return 1 if total_mismatch > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
