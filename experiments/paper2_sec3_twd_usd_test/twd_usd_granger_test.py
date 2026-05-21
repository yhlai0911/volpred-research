#!/usr/bin/env python3
"""
twd_usd_granger_test.py — Paper 2 (taiwan-vt) Sec 3 backfill

Reproduce the claim in body.tex L201:
    "The TWD/USD exchange rate does not add significant explanatory power
     after controlling for VIX (p = 0.08)."

Test design (nested OLS F-test, NOT bivariate Granger):
  - Dependent: 0050.TW squared log returns (r_t^2 * 1e4 for numerical scale)
  - Restricted (X_r): lagged VIX^2 (lags 1..5)              -- already in K1182
  - Full (X_f):       lagged VIX^2 (1..5) + lagged TWD/USD log-change^2 (1..5)
  - F-test joint significance of the 5 TWD/USD coefficients
  - df_num = 5, df_denom = N - 11 (1 const + 10 regressors)

Lookahead discipline (per CLAUDE.md L46, .claude/rules/experiments.md):
  - All RHS features use `.shift(1)..shift(5)` strictly before t
  - Squared returns at time t are the DEPENDENT only (no contemporaneous RHS)
  - No future leakage; t-1 alignment is explicit

Data source rule (per .claude/rules/paper-workflow.md hard rule #1):
  - Reads PINNED snapshot CSVs only:
      paper/taiwan-vt/data/0050_tw_twii_2330_tw_2317_tw_2454_tw_0056_tw_spy_vix_2008-2026.csv
      paper/taiwan-vt/data/_usdtwd_snapshot.csv
  - NO live yfinance call from this script.
  - The USDTWD snapshot is fetched once (auto_adjust=False) by
    fetch_usdtwd_snapshot.py and then pinned. fetch_date stored in CSV header.

Seed: numpy.random.default_rng(42) — used for any bootstrap (none required
for analytic F-test, but rng is instantiated for reproducibility hygiene).

Outputs:
  twd_usd_granger_test_results.json  — with byte_match_paper verdict
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from datetime import datetime, timezone

import numpy as np
import pandas as pd
from scipy import stats

SEED = 42
rng = np.random.default_rng(SEED)

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent.parent
PAPER_DATA_DIR = REPO_ROOT / "paper" / "taiwan-vt" / "data"
MAIN_CSV = PAPER_DATA_DIR / "0050_tw_twii_2330_tw_2317_tw_2454_tw_0056_tw_spy_vix_2008-2026.csv"
USDTWD_CSV = PAPER_DATA_DIR / "_usdtwd_snapshot.csv"
RESULT_JSON = SCRIPT_DIR / "twd_usd_granger_test_results.json"

PAPER_TARGET_P = 0.08
TOL_PASS = 0.02         # |delta| <= 0.02 -> PASS
TOL_DRIFT_SMALL = 0.05  # 0.02 < |delta| <= 0.05 -> DRIFT_SMALL

# Sample window: paper's adjacent Granger test (VIX -> tw50_sq, F=58.8) was
# verified in K1182 to match at 2014-01-01..2025-12-31 (NOT full 2008-2026 —
# the COVID-2020 outlier shock collapses signal-to-noise on full sample).
# Mirror that window here so the nested test runs on the same support as the
# F=58.8 claim sits in the same paragraph. See K1182/README.md.
SAMPLE_START = "2014-01-01"
SAMPLE_END = "2025-12-31"

# Lag spec (paper's L201 wording does not pin specific maxlag; mirror K1182 maxlag=5)
MAX_LAG = 5


def load_main_snapshot() -> pd.DataFrame:
    if not MAIN_CSV.exists():
        raise FileNotFoundError(f"Pinned main snapshot missing: {MAIN_CSV}")
    df = pd.read_csv(MAIN_CSV, parse_dates=["date"])
    # Pre-existing duplicate dates in snapshot (5 rows in 2026-05, outside our sample);
    # keep first occurrence. This is a snapshot-cleanliness dedup, not a value choice.
    df = df.drop_duplicates(subset=["date"], keep="first")
    df = df.set_index("date").sort_index()
    return df


def load_usdtwd_snapshot() -> pd.DataFrame:
    if not USDTWD_CSV.exists():
        raise FileNotFoundError(
            f"Pinned USDTWD snapshot missing: {USDTWD_CSV}\n"
            f"Run: python experiments/paper2_sec3_twd_usd_test/fetch_usdtwd_snapshot.py"
        )
    # CSV header has a `# fetched_at=...` comment line we preserve in metadata
    fetched_at = None
    with open(USDTWD_CSV) as f:
        for line in f:
            if line.startswith("# fetched_at="):
                fetched_at = line.strip().split("=", 1)[1]
                break
            if not line.startswith("#"):
                break
    df = pd.read_csv(USDTWD_CSV, comment="#", parse_dates=["date"])
    df = df.set_index("date").sort_index()
    df.attrs["fetched_at"] = fetched_at
    return df


def build_design(main_df: pd.DataFrame, twd_df: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """Build the regression frame with strict-before-t lagged regressors.

    Dependent: tw50_sq_t  (squared close-to-close log return, percent units squared)
    Restricted RHS: VIX level lag 1..5
    Full RHS:       VIX level lag 1..5 + USDTWD log-change lag 1..5
    (Mirrors K1182 spec which already matched paper's F=58.8 / p<0.001 in same paragraph.
     Paper's L201 wording does not specify squared vs level on RHS; K1182 confirmed
     VIX-level works.)

    All RHS columns use .shift(k) for k in 1..MAX_LAG explicitly (no future leakage).
    """
    # 0050.TW close
    close = main_df["0050_tw_close"].dropna()
    tw50_ret = np.log(close / close.shift(1)) * 100.0  # percent
    tw50_sq = tw50_ret ** 2

    # VIX level (mirrors K1182 spec where F=58.8 / p<0.001 was matched)
    vix_lvl = main_df["vix_close"].dropna()

    # USDTWD log changes (in percent, like 0050 returns)
    twd_close = twd_df["usdtwd_close"].dropna()
    twd_ret = np.log(twd_close / twd_close.shift(1)) * 100.0

    # Align on Taiwan trading calendar — fwd-fill VIX & TWD to TW dates
    base = pd.DataFrame({"tw50_sq": tw50_sq}).dropna()
    vix_aligned = vix_lvl.reindex(base.index, method="ffill")
    twd_aligned = twd_ret.reindex(base.index, method="ffill")

    df = pd.DataFrame({
        "tw50_sq": base["tw50_sq"],
        "vix": vix_aligned,
        "twd_ret": twd_aligned,
    })

    # Apply sample window
    df = df.loc[SAMPLE_START:SAMPLE_END].copy()

    # Strict-before-t lagged features (explicit .shift(k))
    for k in range(1, MAX_LAG + 1):
        df[f"vix_lag{k}"] = df["vix"].shift(k)
        df[f"twd_lag{k}"] = df["twd_ret"].shift(k)

    df = df.dropna()
    meta = {
        "n_obs": int(len(df)),
        "sample_start": str(df.index[0].date()),
        "sample_end": str(df.index[-1].date()),
        "max_lag": MAX_LAG,
    }
    return df, meta


def ols_fit(y: np.ndarray, X: np.ndarray) -> dict:
    """Plain OLS with intercept already in X. Returns coefs and SSR."""
    # X assumed to include a column of ones
    coefs, ssr_arr, rank, _ = np.linalg.lstsq(X, y, rcond=None)
    resid = y - X @ coefs
    ssr = float(np.sum(resid ** 2))
    n = X.shape[0]
    k = X.shape[1]
    return {"coefs": coefs, "ssr": ssr, "n": n, "k": k, "rank": int(rank)}


def f_test_nested(ssr_r: float, ssr_f: float, df_num: int, df_denom: int) -> tuple[float, float]:
    """F = ((SSR_r - SSR_f)/q) / (SSR_f/(n-k_f))"""
    f_stat = ((ssr_r - ssr_f) / df_num) / (ssr_f / df_denom)
    p_val = 1.0 - stats.f.cdf(f_stat, df_num, df_denom)
    return float(f_stat), float(p_val)


def run_one_spec(df: pd.DataFrame, vix_cols: list[str], twd_cols: list[str]) -> dict:
    y = df["tw50_sq"].to_numpy()
    X_r = np.column_stack([np.ones(len(df)), df[vix_cols].to_numpy()])
    X_f = np.column_stack([np.ones(len(df)), df[vix_cols].to_numpy(), df[twd_cols].to_numpy()])
    fit_r = ols_fit(y, X_r)
    fit_f = ols_fit(y, X_f)
    df_num = len(twd_cols)
    df_denom = fit_f["n"] - fit_f["k"]
    f_stat, p_value = f_test_nested(fit_r["ssr"], fit_f["ssr"], df_num, df_denom)
    return {
        "f_stat": f_stat,
        "p_value": p_value,
        "df_num": df_num,
        "df_denom": int(df_denom),
        "ssr_restricted": fit_r["ssr"],
        "ssr_full": fit_f["ssr"],
        "n_obs": int(fit_f["n"]),
        "coefs_full": [float(c) for c in fit_f["coefs"]],
    }


def main() -> int:
    print("=" * 70)
    print("Paper 2 Sec 3 TWD/USD nested F-test reproduction")
    print("=" * 70)

    main_df = load_main_snapshot()
    twd_df = load_usdtwd_snapshot()
    print(f"Main snapshot rows: {len(main_df)}  (first {main_df.index[0].date()}, last {main_df.index[-1].date()})")
    print(f"USDTWD snapshot rows: {len(twd_df)}  (fetched_at={twd_df.attrs.get('fetched_at')})")

    df, meta = build_design(main_df, twd_df)
    print(f"Design matrix: N={meta['n_obs']}, window {meta['sample_start']} .. {meta['sample_end']}")

    vix_cols = [f"vix_lag{k}" for k in range(1, MAX_LAG + 1)]
    twd_cols = [f"twd_lag{k}" for k in range(1, MAX_LAG + 1)]

    # ─── Primary spec: VIX level lag 1..5 + TWD log-change lag 1..5 ────────────
    primary = run_one_spec(df, vix_cols, twd_cols)
    f_stat = primary["f_stat"]
    p_value = primary["p_value"]
    df_num = primary["df_num"]
    df_denom = primary["df_denom"]

    print(f"\nRestricted (VIX only) SSR: {primary['ssr_restricted']:.4f}")
    print(f"Full (VIX + TWD)    SSR: {primary['ssr_full']:.4f}")
    print(f"PRIMARY  F({df_num}, {df_denom}) = {f_stat:.4f}, p = {p_value:.4f}")

    # ─── Sensitivity sweep: try alternative defensible specs to bound result ──
    # Per research-honesty: we run all specs and report all — no cherry-pick.
    # Specs varied:
    #   (a) lag depth: 1, 3, 5
    #   (b) TWD form: log-change (signed), |log-change| (abs), log-change^2 (squared)
    #   (c) VIX form: level vs squared
    sweep = {}

    # |TWD| and TWD^2 derived columns
    for k in range(1, MAX_LAG + 1):
        df[f"twd_abs_lag{k}"] = df["twd_ret"].shift(k).abs()
        df[f"twd_sq_lag{k}"] = df["twd_ret"].shift(k) ** 2
        df[f"vix_sq_lag{k}"] = df["vix"].shift(k) ** 2
    df_sw = df.dropna()

    spec_grid = [
        # (label, vix_cols_fn, twd_cols_fn, maxlag)
        ("vix_lvl_twd_ret_lag1",  "vix_lag", "twd_lag", 1),
        ("vix_lvl_twd_ret_lag3",  "vix_lag", "twd_lag", 3),
        ("vix_lvl_twd_ret_lag5",  "vix_lag", "twd_lag", 5),
        ("vix_lvl_twd_abs_lag1",  "vix_lag", "twd_abs_lag", 1),
        ("vix_lvl_twd_abs_lag3",  "vix_lag", "twd_abs_lag", 3),
        ("vix_lvl_twd_abs_lag5",  "vix_lag", "twd_abs_lag", 5),
        ("vix_lvl_twd_sq_lag1",   "vix_lag", "twd_sq_lag",  1),
        ("vix_lvl_twd_sq_lag3",   "vix_lag", "twd_sq_lag",  3),
        ("vix_lvl_twd_sq_lag5",   "vix_lag", "twd_sq_lag",  5),
        ("vix_sq_twd_ret_lag1",   "vix_sq_lag", "twd_lag",     1),
        ("vix_sq_twd_ret_lag5",   "vix_sq_lag", "twd_lag",     5),
        ("vix_sq_twd_sq_lag1",    "vix_sq_lag", "twd_sq_lag",  1),
        ("vix_sq_twd_sq_lag5",    "vix_sq_lag", "twd_sq_lag",  5),
    ]

    print("\nSensitivity sweep (alternative defensible specs):")
    print(f"  {'spec':<28} {'lags':>4} {'F':>10} {'p':>10}")
    for label, vix_prefix, twd_prefix, lag in spec_grid:
        v = [f"{vix_prefix}{k}" for k in range(1, lag + 1)]
        t = [f"{twd_prefix}{k}" for k in range(1, lag + 1)]
        r = run_one_spec(df_sw, v, t)
        sweep[label] = {"lag": lag, "f_stat": r["f_stat"], "p_value": r["p_value"],
                        "n_obs": r["n_obs"], "df_num": r["df_num"], "df_denom": r["df_denom"]}
        print(f"  {label:<28} {lag:>4} {r['f_stat']:>10.4f} {r['p_value']:>10.4f}")

    # Closest spec to paper's p=0.08
    closest_label = min(sweep.keys(), key=lambda k: abs(sweep[k]["p_value"] - PAPER_TARGET_P))
    print(f"\nClosest spec to paper's p={PAPER_TARGET_P}: {closest_label} "
          f"(p={sweep[closest_label]['p_value']:.4f}, |delta|={abs(sweep[closest_label]['p_value']-PAPER_TARGET_P):.4f})")

    # ─── Verdict on PRIMARY spec only (closest-spec is diagnostic, not cherry-pick) ─
    delta = p_value - PAPER_TARGET_P
    if abs(delta) <= TOL_PASS:
        verdict = "PASS"
    elif abs(delta) <= TOL_DRIFT_SMALL:
        verdict = "DRIFT_SMALL"
    else:
        verdict = "DRIFT_LARGE"
    print(f"\nPRIMARY verdict: paper target p = {PAPER_TARGET_P}; primary p = {p_value:.4f}; "
          f"delta = {delta:+.4f} -> {verdict}")

    # Also check if ANY defensible spec falls within tolerance — indicates a sample/spec
    # the paper plausibly used. If yes, recommend erratum spec; if no, paper number stands as untraceable.
    sweep_pass = [k for k, v in sweep.items() if abs(v["p_value"] - PAPER_TARGET_P) <= TOL_DRIFT_SMALL]
    print(f"Specs within DRIFT_SMALL tol of paper p: {sweep_pass if sweep_pass else 'NONE'}")

    # Honest reporting: even if DRIFT_LARGE, we record actual numbers (no cherry-pick)
    result = {
        "experiment_id": "paper2_sec3_twd_usd_test",
        "title": "Paper 2 Sec 3 TWD/USD nested F-test reproduction",
        "paper_id": "taiwan-vt",
        "paper_claim_loc": "body.tex L201",
        "paper_claim_text": "TWD/USD exchange rate does not add significant explanatory power after controlling for VIX (p = 0.08)",
        "method": "Nested OLS F-test (full vs restricted) on 0050.TW squared log returns",
        "spec": {
            "dependent": "0050.TW squared close-to-close log returns (percent units squared)",
            "restricted_regressors": [f"VIX level lag {k}" for k in range(1, MAX_LAG + 1)],
            "additional_in_full": [f"USDTWD log-change (%) lag {k}" for k in range(1, MAX_LAG + 1)],
            "intercept": True,
            "alignment": "Taiwan trading calendar; VIX & TWD forward-filled to TW dates (lag>=1 anyway)",
            "lookahead_guard": "All RHS use .shift(k) for k in 1..5 explicitly",
            "max_lag": MAX_LAG,
        },
        "sample": meta,
        "f_stat": f_stat,
        "p_value": p_value,
        "df_num": df_num,
        "df_denom": int(df_denom),
        "restricted_model": {
            "ssr": primary["ssr_restricted"],
            "n_params": 1 + MAX_LAG,
            "coefs_order": ["const"] + [f"vix_lag{k}" for k in range(1, MAX_LAG + 1)],
        },
        "full_model": {
            "ssr": primary["ssr_full"],
            "n_params": 1 + 2 * MAX_LAG,
            "coefs_order": ["const"] + [f"vix_lag{k}" for k in range(1, MAX_LAG + 1)] + [f"twd_lag{k}" for k in range(1, MAX_LAG + 1)],
            "coefs": primary["coefs_full"],
        },
        "byte_match_paper": {
            "target_p": PAPER_TARGET_P,
            "estimated_p": p_value,
            "delta": delta,
            "tolerance_pass": TOL_PASS,
            "tolerance_drift_small": TOL_DRIFT_SMALL,
            "verdict": verdict,
            "note": "Primary spec verdict. See sensitivity_sweep for alternative defensible specs.",
        },
        "sensitivity_sweep": sweep,
        "closest_spec_to_paper": {
            "spec": closest_label,
            "p_value": sweep[closest_label]["p_value"],
            "f_stat": sweep[closest_label]["f_stat"],
            "delta": sweep[closest_label]["p_value"] - PAPER_TARGET_P,
        },
        "specs_within_drift_small_tol": sweep_pass,
        "data_sources": {
            "main_snapshot": str(MAIN_CSV.relative_to(REPO_ROOT)),
            "usdtwd_snapshot": str(USDTWD_CSV.relative_to(REPO_ROOT)),
            "usdtwd_fetched_at": twd_df.attrs.get("fetched_at"),
            "live_fetch": False,
        },
        "seed": SEED,
        "produced_at_utc": datetime.now(timezone.utc).isoformat(),
    }

    with open(RESULT_JSON, "w") as f:
        json.dump(result, f, indent=2)
    print(f"\nWrote {RESULT_JSON.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
