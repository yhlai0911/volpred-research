"""
K1302b — GJR-GARCH(1,1) full-sample estimation for 5 unlisted Taiwan individual stocks.

Mirrors K1302 estimation framework exactly:
- Sample window: 2008-01-01 → 2024-12-31
- Estimator: arch package (GJR-GARCH p=1,o=1,q=1), Constant mean, Normal distribution
- Robust SE: Bollerslev-Wooldridge (cov_type='robust')
- Multistart: 100 starting points (seeds 42..141) via scipy.optimize.minimize starting_values param
- Sample filter: drop NaN; (volume filter not available from yfinance auto_adjust close-only path)

Tickers (5 additional financial / telecom Taiwan stocks not in original Table 2):
  2882.TW Cathay Financial
  2891.TW CTBC
  2412.TW Chunghwa Telecom
  2885.TW Yuanta
  2881.TW Fubon

Outputs:
  experiments/k1302b/k1302b_results.json
  experiments/k1302b/k1302b_run.log
"""

import json
import logging
import sys
import warnings
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf
from arch import arch_model

warnings.filterwarnings("ignore")

# ==========================================================================
# Config
# ==========================================================================
EXPERIMENT_ID = "K1302b"
OUT_DIR = Path(__file__).resolve().parent
LOCAL_CACHE = OUT_DIR / "data"
LOCAL_CACHE.mkdir(parents=True, exist_ok=True)

GLOBAL_SEED = 42
np.random.seed(GLOBAL_SEED)

SAMPLE_START = "2008-01-01"
SAMPLE_END = "2024-12-31"

N_MULTISTART = 100
MULTISTART_SEEDS = list(range(GLOBAL_SEED, GLOBAL_SEED + N_MULTISTART))  # 42..141

STOCKS = [
    {"ticker": "2882.TW", "name": "Cathay Financial"},
    {"ticker": "2891.TW", "name": "CTBC"},
    {"ticker": "2412.TW", "name": "Chunghwa Telecom"},
    {"ticker": "2885.TW", "name": "Yuanta"},
    {"ticker": "2881.TW", "name": "Fubon"},
]

# ==========================================================================
# Logger
# ==========================================================================
LOG_FILE = OUT_DIR / f"{EXPERIMENT_ID.lower()}_run.log"
logging.basicConfig(
    level=logging.INFO,
    format="%(message)s",
    handlers=[logging.FileHandler(LOG_FILE, mode="w"), logging.StreamHandler(sys.stdout)],
)


def log(msg: str):
    logging.info(msg)


# ==========================================================================
# Data Helpers
# ==========================================================================
def load_or_fetch_ticker(ticker: str) -> pd.Series:
    """Load adjusted close from local cache, else fetch from yfinance."""
    cache_path = LOCAL_CACHE / f"{ticker.lower().replace('.', '_')}.csv"
    if cache_path.exists():
        log(f"  [{ticker}] loading from local cache...")
        _df = pd.read_csv(cache_path, index_col=0, parse_dates=True)
        _col = "Close" if "Close" in _df.columns else _df.columns[0]
        px = _df[_col].dropna()
        return px

    log(f"  [{ticker}] fetching from yfinance (live; will cache locally)...")
    df = yf.download(ticker, start="2000-01-01", progress=False, auto_adjust=True)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    px = df["Close"].dropna()
    px.to_csv(cache_path)
    return px


def compute_log_returns(px: pd.Series) -> pd.Series:
    return np.log(px / px.shift(1)).dropna()


# ==========================================================================
# Multistart MLE
# ==========================================================================
def fit_one_start(ret_pct: pd.Series, seed: int) -> dict | None:
    """Single GJR-GARCH(1,1) fit with arch package, robust SE, randomized starting values."""
    rng = np.random.RandomState(seed)
    am = arch_model(ret_pct, vol="GARCH", p=1, o=1, q=1, dist="normal", mean="Constant")

    # Randomized starting values around plausible region
    # arch param order: mu, omega, alpha[1], gamma[1], beta[1]
    sv = np.array([
        rng.uniform(-0.05, 0.15),                       # mu
        rng.uniform(0.005, 0.05),                       # omega
        rng.uniform(0.01, 0.10),                        # alpha
        rng.uniform(-0.02, 0.15),                       # gamma
        rng.uniform(0.80, 0.95),                        # beta
    ])

    try:
        res = am.fit(
            disp="off",
            show_warning=False,
            cov_type="robust",
            starting_values=sv,
            update_freq=0,
        )
        if res.convergence_flag != 0:
            return None
        # Stationarity sanity: persistence < 1 required
        params = res.params
        alpha = params.get("alpha[1]", np.nan)
        gamma = params.get("gamma[1]", np.nan)
        beta = params.get("beta[1]", np.nan)
        persistence = alpha + 0.5 * gamma + beta
        if not np.isfinite(persistence) or persistence >= 1.0:
            return None
        return {
            "seed": int(seed),
            "log_likelihood": float(res.loglikelihood),
            "omega": float(params.get("omega", np.nan)),
            "alpha": float(alpha),
            "gamma": float(gamma),
            "beta": float(beta),
            "persistence": float(persistence),
            "gamma_se": float(res.std_err.get("gamma[1]", np.nan)),
            "gamma_t": float(res.tvalues.get("gamma[1]", np.nan)),
            "gamma_p": float(res.pvalues.get("gamma[1]", np.nan)),
            "aic": float(res.aic),
            "bic": float(res.bic),
            "convergence_flag": int(res.convergence_flag),
            "res": res,
        }
    except Exception:
        return None


def fit_stock(returns: pd.Series, ticker: str) -> dict:
    """Run 100 multistart fits, return best-LL result with full convergence record."""
    ret_pct = returns * 100  # arch convention
    n = len(ret_pct)

    log(f"  [{ticker}] running {N_MULTISTART} multistart fits, n={n}...")
    converged_fits = []
    for seed in MULTISTART_SEEDS:
        f = fit_one_start(ret_pct, seed)
        if f is not None:
            converged_fits.append(f)

    n_converged = len(converged_fits)
    log(f"    converged: {n_converged}/{N_MULTISTART}")

    if n_converged == 0:
        return {
            "ticker": ticker,
            "n_obs": int(n),
            "n_attempted": N_MULTISTART,
            "n_converged": 0,
            "converged": False,
            "error": "No multistart converged with stationarity (persistence<1)",
        }

    # Best by log-likelihood
    best = max(converged_fits, key=lambda x: x["log_likelihood"])
    ll_distribution = sorted([f["log_likelihood"] for f in converged_fits])

    log(
        f"    BEST: seed={best['seed']}  LL={best['log_likelihood']:.2f}  "
        f"γ={best['gamma']:+.4f}  t={best['gamma_t']:+.3f}  "
        f"α={best['alpha']:.3f}  β={best['beta']:.3f}  "
        f"persist={best['persistence']:.3f}"
    )

    return {
        "ticker": ticker,
        "n_obs": int(n),
        "n_attempted": N_MULTISTART,
        "n_converged": n_converged,
        "converged": True,
        "best_seed": best["seed"],
        "omega": best["omega"],
        "alpha": best["alpha"],
        "gamma": best["gamma"],
        "beta": best["beta"],
        "persistence": best["persistence"],
        "gamma_se_robust": best["gamma_se"],
        "t_stat_gamma": best["gamma_t"],
        "gamma_p_robust": best["gamma_p"],
        "log_likelihood": best["log_likelihood"],
        "aic": best["aic"],
        "bic": best["bic"],
        "convergence_flag": best["convergence_flag"],
        "ll_distribution": {
            "min": float(min(ll_distribution)),
            "p25": float(np.percentile(ll_distribution, 25)),
            "median": float(np.percentile(ll_distribution, 50)),
            "p75": float(np.percentile(ll_distribution, 75)),
            "max": float(max(ll_distribution)),
            "n": n_converged,
        },
        "estimator_note": (
            "arch package GJR-GARCH(1,1) Constant mean Normal dist, "
            "Bollerslev-Wooldridge robust SE, 100 multistart (seeds 42..141), "
            "best by log-likelihood; stationarity filter persistence<1."
        ),
    }


# ==========================================================================
# Run
# ==========================================================================
def main():
    log(f"=== {EXPERIMENT_ID} GJR-GARCH(1,1) — 5 Taiwan individual stocks ===")
    log(f"Date: {datetime.now(timezone.utc).isoformat()}")
    log(f"Sample: {SAMPLE_START} to {SAMPLE_END}")
    log(f"Global seed: {GLOBAL_SEED}; multistart seeds: 42..141 ({N_MULTISTART} starts)")
    log("")

    log("[1/3] Loading data...")
    returns_by_ticker: dict[str, pd.Series] = {}
    for s in STOCKS:
        ticker = s["ticker"]
        try:
            px = load_or_fetch_ticker(ticker)
            px = px.loc[(px.index >= SAMPLE_START) & (px.index <= SAMPLE_END)].dropna()
            r = compute_log_returns(px)
            returns_by_ticker[ticker] = r
            log(
                f"  {ticker}: {len(r)} log-return obs, "
                f"{r.index.min().date()} → {r.index.max().date()}, "
                f"mean={r.mean():.4f}, std={r.std():.4f}"
            )
        except Exception as e:
            log(f"  {ticker} FAILED: {e}")

    log("")
    log(f"[2/3] Running GJR-GARCH(1,1) multistart MLE × {len(returns_by_ticker)} stocks...")

    per_stock: dict[str, dict] = {}
    for s in STOCKS:
        ticker = s["ticker"]
        if ticker not in returns_by_ticker:
            log(f"  {ticker}: SKIP (no data)")
            continue
        log(f"\n  {ticker} ({s['name']})")
        per_stock[ticker] = fit_stock(returns_by_ticker[ticker], ticker)
        per_stock[ticker]["name"] = s["name"]

    log("")
    log("[3/3] Summary...")

    converged_tickers = [t for t, r in per_stock.items() if r.get("converged")]
    gammas = [per_stock[t]["gamma"] for t in converged_tickers]
    persistences = [per_stock[t]["persistence"] for t in converged_tickers]
    avg_gamma = float(np.mean(gammas)) if gammas else float("nan")
    avg_persistence = float(np.mean(persistences)) if persistences else float("nan")

    log("")
    log("Per-stock summary:")
    log(f"  {'Ticker':<10} {'gamma':>8} {'t-stat':>8} {'alpha':>8} {'beta':>8} {'persist':>8}")
    for t in converged_tickers:
        r = per_stock[t]
        log(
            f"  {t:<10} {r['gamma']:>+8.4f} {r['t_stat_gamma']:>+8.3f} "
            f"{r['alpha']:>8.4f} {r['beta']:>8.4f} {r['persistence']:>8.4f}"
        )
    log("")
    log(f"  N converged: {len(converged_tickers)}/{len(STOCKS)}")
    log(f"  avg γ across 5 stocks: {avg_gamma:+.4f}")
    log(f"  avg persistence:       {avg_persistence:.4f}")
    log(f"  gamma>0 count:         {sum(1 for g in gammas if g > 0)}/{len(gammas)}")
    log(f"  persistence<1 count:   {sum(1 for p in persistences if p < 1.0)}/{len(persistences)}")

    # ==========================================================================
    # Output JSON
    # ==========================================================================
    final_output = {
        "experiment_id": EXPERIMENT_ID,
        "title": "GJR-GARCH(1,1) full-sample γ for 5 unlisted Taiwan individual stocks",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "config": {
            "stocks": STOCKS,
            "sample_start": SAMPLE_START,
            "sample_end": SAMPLE_END,
            "estimator": "arch package GJR-GARCH(1,1), Constant mean, Normal distribution",
            "se_method": "robust (Bollerslev-Wooldridge)",
            "n_multistart": N_MULTISTART,
            "multistart_seed_range": [GLOBAL_SEED, GLOBAL_SEED + N_MULTISTART - 1],
            "global_seed": GLOBAL_SEED,
            "stationarity_filter": "persistence (alpha + 0.5*gamma + beta) < 1",
            "best_selection": "highest log-likelihood across converged starts",
        },
        "data_source": {
            "primary": "yfinance (auto_adjust=True) 2000-01-01..present, "
                       "filtered to sample window 2008-01-01..2024-12-31",
            "cache": str(LOCAL_CACHE),
            "filter": "drop NaN returns (zero-volume rows not available in close-only path)",
        },
        "per_stock": per_stock,
        "summary": {
            "n_stocks": len(STOCKS),
            "n_converged": len(converged_tickers),
            "avg_gamma_5stocks": avg_gamma,
            "avg_persistence": avg_persistence,
            "gamma_positive_count": int(sum(1 for g in gammas if g > 0)),
            "persistence_lt_1_count": int(sum(1 for p in persistences if p < 1.0)),
        },
        "success_criteria": {
            "all_5_converged": len(converged_tickers) == 5,
            "all_gamma_positive": (len(gammas) == 5) and all(g > 0 for g in gammas),
            "all_persistence_lt_1": (len(persistences) == 5) and all(p < 1.0 for p in persistences),
        },
        "lookahead_free_certification": (
            "γ is in-sample MLE on full window 2008-01-01..2024-12-31; no forecast / OOS split; "
            "no signal generation; signal.shift not applicable. "
            "All randomness seeded: np.random.seed(42) global; multistart seeds 42..141 explicit."
        ),
        "mirror_of": "K1302 (extends 4 Table-2 stocks + TSMC to 5 additional unlisted stocks)",
        "notes": {
            "purpose": (
                "Closes Paper 2 (taiwan-vt) Table 2 amplification-ratio re-computation: "
                "K1302 produced canonical full-sample BW-robust γ for Hon Hai/MediaTek/Mega/0056; "
                "K1302b adds Cathay/CTBC/Chunghwa Telecom/Yuanta/Fubon to complete the 9-stock average "
                "under uniform canonical specification."
            ),
            "methodology_consistency": (
                "Byte-similar to K1302: same arch package, GJR(1,1), Constant mean, Normal, "
                "robust SE — only difference is multistart (K1302 single-start default; K1302b explicit 100 "
                "multistart per .claude/rules/experiments.md §Pooled-MLE rule for parameter stability)."
            ),
        },
    }

    # Convert any numpy types
    def convert_numpy(obj):
        if isinstance(obj, np.integer):
            return int(obj)
        if isinstance(obj, np.floating):
            return float(obj)
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        if isinstance(obj, dict):
            return {k: convert_numpy(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [convert_numpy(i) for i in obj]
        return obj

    output_json = convert_numpy(final_output)
    out_path = OUT_DIR / f"{EXPERIMENT_ID.lower()}_results.json"
    with open(out_path, "w") as f:
        json.dump(output_json, f, indent=2)
    log(f"\nResults saved to {out_path}")


if __name__ == "__main__":
    main()
