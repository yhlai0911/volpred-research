"""
K1256 (Paper 1 T-HM): Canonical JSON for 3 Henriksson-Merton γ_HM specifications
================================================================================

Paper:    leverage-direction (Paper 1), body_v3.tex line 433 footnote
Proposal: paper/leverage-direction/review_history/gate_fix_v1/proposal.md §6 T-HM
Gate:     P1 gate-blocker for reproduce.py 3-way γ_HM MATCH

Context
-------
body_v3.tex L433 footnote reconciles three γ_HM values that share the same
symbol but correspond to distinct HM regressions on different samples /
strategies:

  Sec 4.7  γ_HM = -0.035 (t=-0.39)  pure-VT (12/VIX), full sample 2014-2026
  Sec 4.7  γ_HM = -0.068 (t=-4.63)  pure-VT, conditional on VIX > 25
  Sec 5.4  γ_HM = -0.043 (t=-4.06)  Hybrid VT, full sample 2014-2026

Current reproduce.py (lines 486-503) tags these as a HIGH-severity
MISMATCH because it pins a single γ_HM value against three different
specs. The research-honest resolution is (c)-style: the footnote is
correct; the reproduce.py logic must score 3 separate MATCH checks
against a JSON that ties each (γ, t) to a pinned spec+sample.

This script produces that canonical JSON.

Naming note (proposal vs repo state)
------------------------------------
The T-HM line (§6) of proposal.md proposed "tentative K1235" for this
work. K1235 was already allocated to Paper 9 (garch-x-vix, FEZ + STOXX50E
Table 6 reproduction). To avoid double-allocation (CLAUDE.md "同一 K
編號禁止雙 agent") we use K1256 here; the reproduce.py wiring must cite
K1256 going forward.

Specifications
--------------
Common:
  * HM regression:  r^VT_t - r^f_t = α + β (r^m_t - r^f_t) + γ_HM · max(0, r^f_t - r^m_t) + ε_t
  * Standard errors: Newey-West HAC, 10 lags (body_v3 Sec 4.7)
  * Risk-free:       0% daily (HM γ is scale-invariant to uniform rf shift;
                     α absorbs any constant rf offset. We annotate the
                     choice in the output JSON for transparency.)
  * Market proxy:    SPY daily log returns (paper's reference equity)
  * Strategy return: w_t · r^m_t (signal-from-t-1, return-at-t lookahead-safe)
  * Sample:          2014-01-01 to 2026-04-17 (most recent vix_daily.csv date)
  * Data:            yfinance SPY (auto_adjust=False) + paper/leverage-direction/data/vix_daily.csv
  * Seed:            42 (no bootstrap, but fix for determinism)

Spec A — pure_vt_full  (→ γ_HM = -0.035, t = -0.39 in paper Sec 4.7)
  * Strategy:  w_t = clip(0.12 / VIX_{t-1}, 0, 1.5)  (12/VIX rule)
  * Sample:    full 2014-2026
  * N_obs target ~ 3,100

Spec B — pure_vt_high_vix  (→ γ_HM = -0.068, t = -4.63 in paper Sec 4.7)
  * Strategy:  same 12/VIX
  * Sample:    conditional on VIX_{t-1} > 25 (paper-consistent "high VIX episodes")
  * N_obs target ~ 0.21 · 3,100 ≈ 650

Spec C — hybrid_vt_full  (→ γ_HM = -0.043, t = -4.06 in paper Sec 5.4)
  * Strategy:  Hybrid VT per body_v3 Sec 5.4:
       ratio_t = VIX_daily_{t-1} / σ_garch_{t-1}
       if ratio_t > 1.3  → w_t = clip(0.12/VIX_{t-1}, 0, 1.5)
       else              → w_t = clip(σ_tgt_daily / σ_garch_{t-1}, 0, 1.5)
       σ_tgt_daily = 0.10 / sqrt(252)
       σ_garch:    GJR-GARCH(1,1,1), t-dist, mean=Zero, window=2000
  * Sample:    full 2014-2026

Lookahead guard: all signals use t-1 information only
(w_t depends on VIX_{t-1} and σ_garch_{t-1}; strategy return at t is
w_t · r_m_t). This matches CLAUDE.md §"研究誠實原則" #11.

Success criteria
----------------
  * 3 γ_HM values produced with separate spec_label, sample, γ, t, p, N
  * Each within 5% of paper footnote (tolerance; spec C may differ more
    because paper's exact GARCH refit schedule is not fully spec'd)
  * Signs must match (all three negative)
  * Divergence > 5% → reported as-is; NO fitting to paper numbers
    (CLAUDE.md "研究誠實原則" #1: no data forgery)

Outputs
-------
  * experiments/k1256/k1256_results.json
  * experiments/k1256/k1256_run.log (console)
"""

from __future__ import annotations

import json
import sys
import warnings
from datetime import datetime, timezone
from pathlib import Path

warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd
import yfinance as yf
import statsmodels.api as sm
from arch import arch_model


# ------------------------------------------------------------------
# Config
# ------------------------------------------------------------------
EXPERIMENT_ID = "K1256"
OUT_DIR = Path(__file__).resolve().parent
PAPER_DATA = Path(__file__).resolve().parents[2] / "paper" / "leverage-direction" / "data" / "vix_daily.csv"

SEED = 42
RISK_FREE = 0.0            # daily; see docstring
OOS_START = "2014-01-01"
DATA_START = "2004-01-01"  # 10-yr lead for GJR w=2000 warmup before 2014

# Strategy params (body_v3 aligned)
VT_TARGET_ANNUAL = 0.12    # "12/VIX" rule: σ_target = 12%
VIX_THRESHOLD_HIGH = 25.0  # Spec B mask; paper says "VIX > 25" (body_v3 L379 + L433 footnote)
VT_TARGET_HYBRID_ANNUAL = 0.10  # Hybrid VT internal target for GARCH branch (per existing hybrid_vt scripts)
HYBRID_RATIO_SWITCH = 1.3  # VIX/GARCH ratio switch threshold (body_v3 Fig caption L266)
MAX_LEV = 1.5
GARCH_WINDOW = 2000
NEWEY_WEST_LAGS = 10       # body_v3 Sec 4.7 line 367

# Paper footnote target values (for MATCH checks — reported, not fitted to)
PAPER_TARGETS = {
    "pure_vt_full":     {"gamma": -0.035, "t": -0.39, "section": "4.7"},
    "pure_vt_high_vix": {"gamma": -0.068, "t": -4.63, "section": "4.7"},
    "hybrid_vt_full":   {"gamma": -0.043, "t": -4.06, "section": "5.4"},
}

np.random.seed(SEED)

# ------------------------------------------------------------------
# Logging helper
# ------------------------------------------------------------------
LOG_LINES: list[str] = []

def log(msg: str) -> None:
    print(msg, flush=True)
    LOG_LINES.append(msg)


log("=" * 78)
log(f"{EXPERIMENT_ID}: 3-spec Henriksson-Merton γ_HM canonical JSON")
log("Paper 1 (leverage-direction) body_v3.tex L433 footnote T-HM")
log("=" * 78)
log(f"Seed:            {SEED}")
log(f"OOS start:       {OOS_START}")
log(f"Newey-West lags: {NEWEY_WEST_LAGS}")
log(f"GARCH window:    {GARCH_WINDOW}")


# ------------------------------------------------------------------
# 1. Load data
# ------------------------------------------------------------------
log("\n[1/5] Loading SPY + VIX data...")

# SPY from yfinance (auto_adjust=False — paper-workflow canonical per P4 lesson)
spy_end = "2026-12-31"
spy_df = yf.download(
    "SPY", start=DATA_START, end=spy_end, progress=False, auto_adjust=False
)
if isinstance(spy_df.columns, pd.MultiIndex):
    spy_df.columns = spy_df.columns.get_level_values(0)
spy_df = spy_df[["Adj Close"]].rename(columns={"Adj Close": "SPY"})
spy_df.index = pd.to_datetime(spy_df.index).tz_localize(None)

# VIX from pinned snapshot (paper/leverage-direction/data/vix_daily.csv; last row 2026-04-17)
vix_df = pd.read_csv(PAPER_DATA, parse_dates=["date"]).rename(columns={"date": "Date", "vix": "VIX"})
vix_df = vix_df.set_index("Date").sort_index()
vix_df.index = pd.to_datetime(vix_df.index).tz_localize(None)

# Align
df = spy_df.join(vix_df, how="inner").dropna()
df["r_m"] = np.log(df["SPY"] / df["SPY"].shift(1))
df = df.dropna()

log(f"  SPY × VIX merged rows:  {len(df)}")
log(f"  Date range:             {df.index[0].date()}  →  {df.index[-1].date()}")


# ------------------------------------------------------------------
# 2. Rolling GJR-GARCH forecast for Hybrid VT (Spec C)
# ------------------------------------------------------------------
log("\n[2/5] Rolling GJR-GARCH(1,1,1) forecast for Hybrid VT...")


def rolling_gjr_forecast(returns: np.ndarray, window: int) -> np.ndarray:
    """One-step-ahead σ forecast from GJR-GARCH on trailing `window` days.

    Returns daily σ (in return units, NOT annualized). NaN for t < window.
    """
    n = len(returns)
    sigma_hat = np.full(n, np.nan)
    for i in range(window, n):
        r_win = returns[i - window:i] * 100.0  # percent for arch stability
        try:
            m = arch_model(
                r_win, vol="GARCH", p=1, o=1, q=1,
                dist="t", mean="Zero", rescale=False,
            )
            res = m.fit(disp="off", show_warning=False)
            fc = res.forecast(horizon=1)
            var_pct = fc.variance.iloc[-1, 0]
            sigma_hat[i] = np.sqrt(var_pct / 10000.0)
        except Exception:
            sigma_hat[i] = np.std(returns[i - window:i])
    return sigma_hat


df["sigma_gjr"] = rolling_gjr_forecast(df["r_m"].values, GARCH_WINDOW)

n_valid = int(df["sigma_gjr"].notna().sum())
log(f"  GJR forecasts filled: {n_valid} / {len(df)} days")


# ------------------------------------------------------------------
# 3. Build OOS sample + strategy weights (all lagged t-1)
# ------------------------------------------------------------------
log("\n[3/5] Building strategy weights (signal_t-1 → return_t lookahead-safe)...")

# VIX daily-units (annualized VIX % → daily stdev in return units)
df["vix_daily"] = df["VIX"] / 100.0 / np.sqrt(252.0)

# Lag signals (use yesterday's close-of-day VIX / GJR to set today's weight)
df["VIX_lag"] = df["VIX"].shift(1)
df["vix_daily_lag"] = df["vix_daily"].shift(1)
df["sigma_gjr_lag"] = df["sigma_gjr"].shift(1)

oos = df.loc[df.index >= pd.Timestamp(OOS_START)].copy()
oos = oos.dropna(subset=["VIX_lag", "vix_daily_lag", "sigma_gjr_lag", "r_m"])
log(f"  OOS rows after lagging + GJR warmup: {len(oos)}")
log(f"  OOS date range: {oos.index[0].date()}  →  {oos.index[-1].date()}")

# 12/VIX pure VT weight: w = σ_target / VIX where both are in percentage points
# (paper body_v3 L506: "σ_target=12%, rule reduces to w = 12/VIX"). VIX_lag is
# already in percentage-point annualized form, so w = 12/VIX (NOT 0.12/VIX).
oos["w_pure_vt"] = np.clip((VT_TARGET_ANNUAL * 100.0) / oos["VIX_lag"], 0.0, MAX_LEV)

# Hybrid VT weight
# GARCH branch: w = σ_target_daily / σ_GJR_daily (both daily return-unit stdev).
# VIX branch: w = σ_target / VIX (same paper 12/VIX rule — annualized percentage).
w_garch_branch = np.clip(
    (VT_TARGET_HYBRID_ANNUAL / np.sqrt(252.0)) / oos["sigma_gjr_lag"], 0.0, MAX_LEV
)
w_vix_branch = np.clip((VT_TARGET_ANNUAL * 100.0) / oos["VIX_lag"], 0.0, MAX_LEV)
ratio = oos["vix_daily_lag"] / oos["sigma_gjr_lag"]
oos["w_hybrid_vt"] = np.where(ratio > HYBRID_RATIO_SWITCH, w_vix_branch, w_garch_branch)
oos["hybrid_switches"] = (ratio > HYBRID_RATIO_SWITCH).astype(int)

# Strategy returns (no transaction cost; paper Sec 4.7 HM uses raw VT return)
oos["r_pure_vt"] = oos["w_pure_vt"] * oos["r_m"]
oos["r_hybrid_vt"] = oos["w_hybrid_vt"] * oos["r_m"]

log(f"  Pure VT weight:   mean={oos['w_pure_vt'].mean():.3f}, median={oos['w_pure_vt'].median():.3f}, "
    f"pct at MAX_LEV={(oos['w_pure_vt'] >= MAX_LEV - 1e-9).mean()*100:.1f}%")
log(f"  Hybrid VT weight: mean={oos['w_hybrid_vt'].mean():.3f}, "
    f"VIX-branch share={oos['hybrid_switches'].mean()*100:.1f}%")


# ------------------------------------------------------------------
# 4. Run 3 HM regressions
# ------------------------------------------------------------------
log("\n[4/5] Running 3 Henriksson-Merton regressions (Newey-West HAC, 10 lags)...")


def henriksson_merton(
    r_vt: pd.Series, r_m: pd.Series, rf: float = 0.0, nw_lags: int = 10
) -> dict:
    """Fit r_vt - rf = α + β(r_m - rf) + γ · max(0, rf - r_m) + ε.

    Newey-West HAC standard errors with `nw_lags` lags.
    """
    y = (r_vt - rf).astype(float).values
    x_mkt = (r_m - rf).astype(float).values
    x_dn = np.maximum(0.0, rf - r_m.astype(float).values)
    X = sm.add_constant(np.column_stack([x_mkt, x_dn]))

    model = sm.OLS(y, X).fit(cov_type="HAC", cov_kwds={"maxlags": nw_lags})

    alpha, beta, gamma = model.params
    se = model.bse
    t_stats = model.tvalues
    p_values = model.pvalues

    # Annualized alpha (daily intercept × 252)
    alpha_annual = float(alpha * 252.0)

    return {
        "alpha_daily": float(alpha),
        "alpha_annual": alpha_annual,
        "alpha_t": float(t_stats[0]),
        "alpha_p": float(p_values[0]),
        "beta": float(beta),
        "beta_t": float(t_stats[1]),
        "beta_p": float(p_values[1]),
        "gamma_HM": float(gamma),
        "gamma_HM_se": float(se[2]),
        "gamma_HM_t": float(t_stats[2]),
        "gamma_HM_p": float(p_values[2]),
        "n_obs": int(model.nobs),
        "r_squared": float(model.rsquared),
        "nw_lags": int(nw_lags),
    }


results: dict[str, dict] = {}

# Spec A — pure VT, full sample
sA = henriksson_merton(oos["r_pure_vt"], oos["r_m"], RISK_FREE, NEWEY_WEST_LAGS)
sA["spec_label"] = "pure_vt_full"
sA["strategy"] = "12/VIX (w = clip(0.12/VIX_{t-1}, 0, 1.5))"
sA["sample_description"] = "Full OOS 2014-2026"
sA["fit_date_start"] = str(oos.index[0].date())
sA["fit_date_end"] = str(oos.index[-1].date())
results["pure_vt_full"] = sA
log(f"  [A] pure_vt_full        γ = {sA['gamma_HM']:+.4f}  t = {sA['gamma_HM_t']:+.3f}  "
    f"α_ann = {sA['alpha_annual']*100:+.2f}%  N = {sA['n_obs']}")

# Spec B — pure VT, high-VIX regime (VIX_{t-1} > 25)
mask_high = oos["VIX_lag"] > VIX_THRESHOLD_HIGH
sub_high = oos.loc[mask_high]
if len(sub_high) < 50:
    log(f"  WARNING: high-VIX subsample only {len(sub_high)} rows")
sB = henriksson_merton(sub_high["r_pure_vt"], sub_high["r_m"], RISK_FREE, NEWEY_WEST_LAGS)
sB["spec_label"] = "pure_vt_high_vix"
sB["strategy"] = "12/VIX restricted to VIX_{t-1} > 25"
sB["sample_description"] = f"OOS 2014-2026 conditional on VIX_{{t-1}} > {VIX_THRESHOLD_HIGH}"
sB["sample_fraction"] = float(mask_high.mean())
sB["fit_date_start"] = str(sub_high.index[0].date()) if len(sub_high) else None
sB["fit_date_end"] = str(sub_high.index[-1].date()) if len(sub_high) else None
results["pure_vt_high_vix"] = sB
log(f"  [B] pure_vt_high_vix    γ = {sB['gamma_HM']:+.4f}  t = {sB['gamma_HM_t']:+.3f}  "
    f"N = {sB['n_obs']} ({sB['sample_fraction']*100:.1f}% of full)")

# Spec C — Hybrid VT, full sample
sC = henriksson_merton(oos["r_hybrid_vt"], oos["r_m"], RISK_FREE, NEWEY_WEST_LAGS)
sC["spec_label"] = "hybrid_vt_full"
sC["strategy"] = (
    "Hybrid VT: if VIX/σ_GJR > 1.3 → 12/VIX-branch, else σ_target_10/σ_GJR-branch"
)
sC["sample_description"] = "Full OOS 2014-2026"
sC["hybrid_vix_branch_share"] = float(oos["hybrid_switches"].mean())
sC["fit_date_start"] = str(oos.index[0].date())
sC["fit_date_end"] = str(oos.index[-1].date())
results["hybrid_vt_full"] = sC
log(f"  [C] hybrid_vt_full      γ = {sC['gamma_HM']:+.4f}  t = {sC['gamma_HM_t']:+.3f}  "
    f"α_ann = {sC['alpha_annual']*100:+.2f}%  N = {sC['n_obs']}")


# ------------------------------------------------------------------
# 5. Paper-MATCH verdicts
# ------------------------------------------------------------------
log("\n[5/5] Paper-MATCH verdicts (tolerance: γ rel-diff <5% + sign match)...")

TOL_GAMMA_REL = 0.05   # 5% relative
TOL_T = 1.0            # absolute Δt tolerance (t-stats depend on SE computation method)


def classify(spec: str, est: dict) -> dict:
    target = PAPER_TARGETS[spec]
    g_paper = target["gamma"]
    t_paper = target["t"]
    g_est = est["gamma_HM"]
    t_est = est["gamma_HM_t"]
    sign_match = (np.sign(g_paper) == np.sign(g_est)) and (np.sign(t_paper) == np.sign(t_est))
    g_rel = abs(g_est - g_paper) / max(abs(g_paper), 1e-6)
    t_abs = abs(t_est - t_paper)
    if sign_match and g_rel < TOL_GAMMA_REL and t_abs < TOL_T:
        verdict = "MATCH"
    elif sign_match and g_rel < 0.20 and t_abs < 2.0:
        verdict = "BORDERLINE"
    elif sign_match:
        verdict = "DIVERGENT_SAME_SIGN"
    else:
        verdict = "MISMATCH"
    return {
        "paper_gamma": g_paper,
        "paper_t": t_paper,
        "paper_section": target["section"],
        "gamma_rel_diff": float(g_rel),
        "t_abs_diff": float(t_abs),
        "sign_match": bool(sign_match),
        "verdict": verdict,
    }


for spec in results:
    results[spec]["paper_match"] = classify(spec, results[spec])
    v = results[spec]["paper_match"]
    log(f"  [{spec:20s}] γ_est={results[spec]['gamma_HM']:+.4f} vs paper {v['paper_gamma']:+.4f}  "
        f"t_est={results[spec]['gamma_HM_t']:+.3f} vs {v['paper_t']:+.3f}  "
        f"Δγ_rel={v['gamma_rel_diff']*100:5.1f}%  Δt={v['t_abs_diff']:5.2f}  → {v['verdict']}")


# ------------------------------------------------------------------
# Finalize JSON
# ------------------------------------------------------------------
out = {
    "experiment_id": EXPERIMENT_ID,
    "title": "Paper 1 T-HM: Canonical 3-spec Henriksson-Merton γ_HM",
    "paper_ref": {
        "paper": "leverage-direction",
        "body_tex": "body_v3.tex",
        "line": 433,
        "section_sec47": "§4.7 Formal Market Timing Tests",
        "section_sec54": "§5.4 The Nature of VT Alpha",
        "footnote_quote": (
            "The three γ_HM estimates reported in this paper share the same "
            "symbol but correspond to distinct Henriksson–Merton regressions on "
            "different samples: γ_HM=-0.035 (t=-0.39) for the pure-VT strategy "
            "over the full 2014–2026 sample (Section 4.7); γ_HM=-0.068 (t=-4.63) "
            "for the pure-VT strategy conditional on high-VIX episodes (VIX>25); "
            "and γ_HM=-0.043 (t=-4.06) for the Hybrid VT strategy over the full "
            "sample (this section)."
        ),
    },
    "naming_note": (
        "Proposal §6 T-HM tentatively named this task K1235; K1235 was already "
        "allocated to Paper 9 garch-x-vix (FEZ + STOXX50E Table 6). K1256 is the "
        "canonical K-ID for Paper 1 T-HM; reproduce.py must cite K1256."
    ),
    "created_at": datetime.now(timezone.utc).isoformat(),
    "config": {
        "seed": SEED,
        "risk_free_daily": RISK_FREE,
        "risk_free_note": (
            "HM γ is invariant to a uniform rf shift (γ-term is max(0, rf-r_m), "
            "which adds a constant-risk-free-rate offset absorbed by α). rf=0 is "
            "paper-innocuous and sidesteps T-bill data-source dependency."
        ),
        "oos_start": OOS_START,
        "data_start": DATA_START,
        "vt_target_annual_pure": VT_TARGET_ANNUAL,
        "vt_target_annual_hybrid_garch_branch": VT_TARGET_HYBRID_ANNUAL,
        "max_leverage": MAX_LEV,
        "vix_threshold_high": VIX_THRESHOLD_HIGH,
        "hybrid_ratio_switch": HYBRID_RATIO_SWITCH,
        "garch_window": GARCH_WINDOW,
        "garch_model": "GJR-GARCH(1,1,1), t-dist, mean=Zero, rescale=False",
        "newey_west_lags": NEWEY_WEST_LAGS,
        "yfinance_auto_adjust": False,
        "vix_source": str(PAPER_DATA),
    },
    "sample": {
        "n_total_merged": int(len(df)),
        "n_oos": int(len(oos)),
        "oos_date_start": str(oos.index[0].date()),
        "oos_date_end": str(oos.index[-1].date()),
    },
    "results": results,
    "paper_targets": PAPER_TARGETS,
    "verdicts_summary": {
        spec: results[spec]["paper_match"]["verdict"] for spec in results
    },
    "notes": {
        "lookahead_guard": (
            "All signals are t-1 (VIX_lag, sigma_gjr_lag). Strategy return at t "
            "is w_t · r^m_t. No same-day signal × same-day return."
        ),
        "divergence_policy": (
            "Per CLAUDE.md §'研究誠實原則' #1 and paper-workflow.md "
            "'腳本/資料/論文數字必須三方一致', any γ_HM or t divergence beyond "
            "5%/Δt=1.0 is reported as-is. Reconciliation (reproduce.py rewire, "
            "paper errata note, or spec-clarification) must happen on main "
            "thread, not by tuning this script."
        ),
        "hybrid_spec_caveat": (
            "body_v3.tex does not fully pin the Hybrid VT rebalance cadence or "
            "the exact GARCH refit schedule used in Sec 5.4. Script uses daily "
            "rebalance + daily refit (same as experiments/multi_asset_hybrid_vt_v2). "
            "If spec-C divergence > 5%, main thread should pin the exact schedule "
            "in a v3 footnote or adopt path (a)/(b)/(c) per paper-workflow rules."
        ),
    },
}

out_path = OUT_DIR / "k1256_results.json"
with out_path.open("w") as f:
    json.dump(out, f, indent=2, default=str)
log(f"\nWrote {out_path}")

# Write log file
log_path = OUT_DIR / "k1256_run.log"
with log_path.open("w") as f:
    f.write("\n".join(LOG_LINES) + "\n")

# Also write a small hm_timing_tests_results.json snippet that reproduce.py
# can cite from paper/leverage-direction/experiments/ (per proposal §6 T-HM
# file-path contract). We create the paper-side stub too so reproduce.py
# rewire is straightforward.
hm_stub = {
    "produced_by": EXPERIMENT_ID,
    "source_experiment": "experiments/k1256/k1256_results.json",
    "tuples": [
        {
            "spec_label": spec,
            "gamma_HM": results[spec]["gamma_HM"],
            "t_stat": results[spec]["gamma_HM_t"],
            "p_value": results[spec]["gamma_HM_p"],
            "n_obs": results[spec]["n_obs"],
            "paper_section": PAPER_TARGETS[spec]["section"],
            "paper_gamma": PAPER_TARGETS[spec]["gamma"],
            "paper_t": PAPER_TARGETS[spec]["t"],
            "verdict": results[spec]["paper_match"]["verdict"],
        }
        for spec in results
    ],
    "written_at": datetime.now(timezone.utc).isoformat(),
}

paper_side_dir = Path(__file__).resolve().parents[2] / "paper" / "leverage-direction" / "experiments"
paper_side_path = paper_side_dir / "hm_timing_tests_results.json"
if paper_side_dir.exists():
    with paper_side_path.open("w") as f:
        json.dump(hm_stub, f, indent=2, default=str)
    log(f"Wrote {paper_side_path}")
else:
    log(f"SKIPPED paper-side stub (dir not found): {paper_side_path}")

log("\nDONE.")
