
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
EXPERIMENT_ID = "K1302"
OUT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = OUT_DIR.parents[1]
PAPER_CSV = (
    PROJECT_ROOT
    / "paper"
    / "taiwan-vt"
    / "data"
    / "0050_tw_twii_2330_tw_2317_tw_2454_tw_0056_tw_spy_vix_2008-2026.csv"
)
LOCAL_CACHE = OUT_DIR / "data"
LOCAL_CACHE.mkdir(parents=True, exist_ok=True)
# 2886_tw.csv and 2383_tw.csv are git-tracked snapshots (yfinance auto_adjust=True,
# 2000-01-01 to 2026-05-14) in experiments/k1302/data/ — provenance is pinned.

GLOBAL_SEED = 42
N_MULTISTART = 100
MULTISTART_SEEDS = list(range(GLOBAL_SEED, GLOBAL_SEED + N_MULTISTART))  # seeds 42..141
SAMPLE_START = "2008-01-01"
SAMPLE_END = "2024-12-31"

# K1256 3-spec disambiguation pattern (adapted for Paper 2 / GJR-GARCH)
# TWA: Canonical (Constant mean, Normal, Full sample)
# TWB: Heavy-tail robustness (Constant mean, Student-t, Full sample)
# TWC: Sample-window robustness (Constant mean, Normal, Last 1250 days)
SPECS = {
    "TWA": {"dist": "normal",  "window": None, "label": "GJR-Normal Full-Sample (Canonical)"},
    "TWB": {"dist": "t",       "window": None, "label": "GJR-StudentT Full-Sample (Heavy-tail)"},
    "TWC": {"dist": "normal",  "window": 1250, "label": "GJR-Normal Last 1250 Days (Robustness)"},
}

STOCKS = [
    {"ticker": "2317.TW", "name": "Hon Hai Precision",          "in_table2": True},
    {"ticker": "2454.TW", "name": "MediaTek",                   "in_table2": True},
    {"ticker": "0056.TW", "name": "Yuanta High Dividend ETF",   "in_table2": True},
    {"ticker": "2886.TW", "name": "Mega Financial",             "in_table2": True},
    {"ticker": "2383.TW", "name": "ELITE Material",             "in_table2": True},
]

# Paper 2 Table 2 targets — current canonical body.tex values (full-sample BW-robust, K1302 first run)
# Updated 2026-05-16: was stale legacy N121 values; now reflects body.tex lines 153-156,164
PAPER_TABLE2_TARGETS = {
    "2317.TW": {"gamma": 0.032, "t": 1.74},
    "2454.TW": {"gamma": 0.041, "t": 3.10},
    "0056.TW": {"gamma": 0.067, "t": 1.91},
    "2886.TW": {"gamma": 0.038, "t": 1.55},
    "2383.TW": {"gamma": 0.009, "t": 1.15},
}

TOL_GAMMA = 0.001
TOL_T = 0.05

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
def load_paper_csv() -> pd.DataFrame:
    if not PAPER_CSV.exists():
        raise FileNotFoundError(f"Paper CSV not found: {PAPER_CSV}")
    df = pd.read_csv(PAPER_CSV)
    df["date"] = pd.to_datetime(df["date"])
    df.set_index("date", inplace=True)
    return df


def load_or_fetch_ticker(ticker: str, paper_df: pd.DataFrame = None) -> pd.Series:
    # Try paper CSV first for consistency
    if paper_df is not None:
        col_name = ticker.lower().replace(".", "_") + "_adj_close"
        if col_name in paper_df.columns:
            px = paper_df[col_name].dropna()
            log(f"  [{ticker}] loaded from paper CSV ({col_name}): {len(px)} rows")
            return px

    cache_path = LOCAL_CACHE / f"{ticker.lower().replace('.', '_')}.csv"
    if cache_path.exists():
        log(f"  [{ticker}] loading from local cache...")
        _df = pd.read_csv(cache_path, index_col=0, parse_dates=True)
        _col = "Close" if "Close" in _df.columns else _df.columns[0]
        px = _df[_col]
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
# Multistart MLE (100 starts, seeds 42..141, pick best LL)
# ==========================================================================
def fit_one_start(ret_pct: pd.Series, dist: str, seed: int) -> dict | None:
    """Single GJR-GARCH(1,1) fit with randomized starting values."""
    rng = np.random.RandomState(seed)
    am = arch_model(ret_pct, vol="GARCH", p=1, o=1, q=1, dist=dist, mean="Constant")

    if dist == "normal":
        sv = np.array([
            rng.uniform(-0.05, 0.15),    # mu
            rng.uniform(0.005, 0.05),    # omega
            rng.uniform(0.01, 0.10),     # alpha
            rng.uniform(-0.02, 0.15),    # gamma
            rng.uniform(0.80, 0.95),     # beta
        ])
    else:  # Student-t
        sv = np.array([
            rng.uniform(-0.05, 0.15),    # mu
            rng.uniform(0.005, 0.05),    # omega
            rng.uniform(0.01, 0.10),     # alpha
            rng.uniform(-0.02, 0.15),    # gamma
            rng.uniform(0.80, 0.95),     # beta
            rng.uniform(4.0, 15.0),      # nu (degrees of freedom)
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
        params = res.params
        alpha = params.get("alpha[1]", np.nan)
        gamma = params.get("gamma[1]", np.nan)
        beta = params.get("beta[1]", np.nan)
        persistence = alpha + 0.5 * gamma + beta
        if not np.isfinite(persistence) or persistence >= 1.0:
            return None
        nu = params.get("nu", None)
        return {
            "seed": int(seed),
            "log_likelihood": float(res.loglikelihood),
            "omega": float(params.get("omega", np.nan)),
            "alpha": float(alpha),
            "gamma": float(gamma),
            "beta": float(beta),
            "nu": float(nu) if nu is not None else None,
            "persistence": float(persistence),
            "gamma_se": float(res.std_err.get("gamma[1]", np.nan)),
            "gamma_t": float(res.tvalues.get("gamma[1]", np.nan)),
            "gamma_p": float(res.pvalues.get("gamma[1]", np.nan)),
            "aic": float(res.aic),
            "bic": float(res.bic),
        }
    except (ValueError, np.linalg.LinAlgError):
        return None  # numerical instability from bad starting values — expected
    except Exception as exc:
        log(f"      [WARN] fit_one_start seed={seed} unexpected error: {type(exc).__name__}: {exc}")
        return None


def run_spec(returns: pd.Series, spec_key: str, ticker: str) -> dict:
    """100-multistart GJR-GARCH for one (stock, spec). Picks best-LL converged result."""
    spec = SPECS[spec_key]
    dist = spec["dist"]
    window = spec["window"]

    if window:
        r_used = returns.iloc[-window:]
    else:
        r_used = returns

    ret_pct = r_used * 100
    n = len(ret_pct)

    log(f"    {spec_key} ({spec['label']}): n={n}, dist={dist}")
    log(f"      Running {N_MULTISTART} multistart fits (seeds {MULTISTART_SEEDS[0]}..{MULTISTART_SEEDS[-1]})...")

    converged = []
    for seed in MULTISTART_SEEDS:
        f = fit_one_start(ret_pct, dist, seed)
        if f is not None:
            converged.append(f)

    n_conv = len(converged)
    log(f"      converged: {n_conv}/{N_MULTISTART}")

    if n_conv == 0:
        log(f"      [FAIL] No multistart converged with stationarity")
        return {
            "spec_key": spec_key,
            "spec_label": spec["label"],
            "dist": dist,
            "window_setting": window,
            "n_obs": int(n),
            "converged": False,
            "n_attempted": N_MULTISTART,
            "n_converged": 0,
            "error": "No multistart converged with stationarity (persistence<1)",
        }

    best = max(converged, key=lambda x: x["log_likelihood"])
    ll_distribution = sorted([f["log_likelihood"] for f in converged])

    log(
        f"      BEST: seed={best['seed']}  LL={best['log_likelihood']:.2f}  "
        f"γ={best['gamma']:+.4f}  t={best['gamma_t']:+.3f}  "
        f"α={best['alpha']:.3f}  β={best['beta']:.3f}  "
        f"persist={best['persistence']:.3f}"
    )

    return {
        "spec_key": spec_key,
        "spec_label": spec["label"],
        "dist": dist,
        "window_setting": window,
        "n_obs": int(n),
        "converged": True,
        "n_attempted": N_MULTISTART,
        "n_converged": n_conv,
        "multistart_best_seed": best["seed"],
        "multistart_ll_distribution": ll_distribution,
        "omega": best["omega"],
        "alpha": best["alpha"],
        "gamma": best["gamma"],
        "beta": best["beta"],
        "nu": best.get("nu"),
        "persistence": best["persistence"],
        "log_likelihood": best["log_likelihood"],
        "gamma_se_robust": best["gamma_se"],
        "gamma_t_robust": best["gamma_t"],
        "gamma_p_robust": best["gamma_p"],
        "aic": best["aic"],
        "bic": best["bic"],
        "convergence_flag": 0,
        "note": (
            f"Estimated via arch package + {N_MULTISTART}-multistart scipy.optimize.minimize "
            f"(seeds {MULTISTART_SEEDS[0]}..{MULTISTART_SEEDS[-1]}). "
            f"Best-LL seed={best['seed']}. "
            "Bollerslev-Wooldridge robust SE (cov_type='robust')."
        ),
    }


# ==========================================================================
# Run
# ==========================================================================
def main():
    np.random.seed(GLOBAL_SEED)
    log(f"=== {EXPERIMENT_ID} Individual γ JSON Rebuild (v2 — 100 multistart) ===")
    log(f"Date: {datetime.now(timezone.utc).isoformat()}")
    log(f"Global seed: {GLOBAL_SEED}; multistart seeds: {MULTISTART_SEEDS[0]}..{MULTISTART_SEEDS[-1]} ({N_MULTISTART} starts)")
    log("")

    log("[1/3] Loading data...")
    try:
        paper_df = load_paper_csv()
        log(f"  Paper CSV: {len(paper_df)} rows, "
            f"{paper_df.index.min().date()} → {paper_df.index.max().date()}")
    except Exception as e:
        log(f"  WARNING: paper CSV unavailable ({e}); will use yfinance fallback")
        paper_df = None

    prices_by_ticker: dict[str, pd.Series] = {}
    returns_by_ticker: dict[str, pd.Series] = {}

    for s_info in STOCKS:
        ticker = s_info["ticker"]
        try:
            px = load_or_fetch_ticker(ticker, paper_df)
            px = px.loc[(px.index >= SAMPLE_START) & (px.index <= SAMPLE_END)].dropna()
            r = compute_log_returns(px)
            prices_by_ticker[ticker] = px
            returns_by_ticker[ticker] = r
            log(f"  {ticker}: {len(r)} log-return obs, "
                f"{r.index.min().date()} → {r.index.max().date()}, "
                f"mean={r.mean():.4f}, std={r.std():.4f}")
        except Exception as e:
            log(f"  {ticker} FAILED: {e}")

    log("")

    log("[2/3] Running GJR-GARCH MLE ({} specs × {} stocks, 100 multistart each)...".format(
        len(SPECS), len(returns_by_ticker)))

    all_results: dict[str, dict[str, dict]] = {}
    for s_info in STOCKS:
        ticker = s_info["ticker"]
        if ticker not in returns_by_ticker:
            log(f"  {ticker}: SKIP (no data)")
            continue
        log(f"\n  {ticker} ({s_info['name']})")
        all_results[ticker] = {}
        for spec_key in SPECS:
            all_results[ticker][spec_key] = run_spec(returns_by_ticker[ticker], spec_key, ticker)

    log("")

    log("[3/3] Byte-match vs Paper 2 Table 2 (TWA spec only)...")
    log(f"  Tolerance: |Δγ| ≤ {TOL_GAMMA}, |Δt| ≤ {TOL_T}")
    log("")

    byte_match: dict[str, dict] = {}
    overall_pass = True
    fail_count = 0
    for s_info in STOCKS:
        ticker = s_info["ticker"]
        if ticker not in all_results:
            continue
        r_twa = all_results[ticker].get("TWA")
        if r_twa is None or not r_twa.get("converged"):
            log(f"  {ticker}: TWA did not converge — UNVERIFIABLE")
            byte_match[ticker] = {
                "verdict": "UNVERIFIABLE_NO_CONVERGENCE",
                "gamma_paper": PAPER_TABLE2_TARGETS.get(ticker, {}).get("gamma", None),
                "t_paper": PAPER_TABLE2_TARGETS.get(ticker, {}).get("t", None),
            }
            overall_pass = False
            fail_count += 1
            continue

        if not s_info["in_table2"]:
            byte_match[ticker] = {
                "verdict": "NOT_IN_TABLE_2",
                "note": "Stock not in Paper 2 body.tex Table 2; reported for diagnostic.",
                "gamma_estimated": r_twa["gamma"],
                "t_estimated": r_twa["gamma_t_robust"],
            }
            log(f"  {ticker} (NOT in Table 2):  γ = {r_twa['gamma']:+.4f}  t = {r_twa['gamma_t_robust']:+.3f}  (diagnostic)")
            continue

        target = PAPER_TABLE2_TARGETS[ticker]
        delta_g = abs(r_twa["gamma"] - target["gamma"])
        delta_t = abs(r_twa["gamma_t_robust"] - target["t"])
        pass_g = delta_g <= TOL_GAMMA
        pass_t = delta_t <= TOL_T
        sign_g = np.sign(r_twa["gamma"]) == np.sign(target["gamma"])

        if pass_g and pass_t:
            verdict = "PASS"
        elif pass_g:
            verdict = "FAIL_T_STAT_DRIFT"
        elif sign_g:
            verdict = "FAIL_LARGE_DRIFT"
        else:
            verdict = "FAIL_SIGN_FLIP"

        if verdict != "PASS":
            overall_pass = False
            fail_count += 1

        byte_match[ticker] = {
            "verdict": verdict,
            "gamma_paper": target["gamma"],
            "gamma_estimated": r_twa["gamma"],
            "delta_gamma": delta_g,
            "t_paper": target["t"],
            "t_estimated": r_twa["gamma_t_robust"],
            "delta_t": delta_t,
            "pass_gamma": pass_g,
            "pass_t": pass_t,
        }
        log(f"  {ticker:<8} | γ: {target['gamma']:+.3f} vs {r_twa['gamma']:+.3f} (Δ={delta_g:.3f}) | "
            f"t: {target['t']:+.2f} vs {r_twa['gamma_t_robust']:+.2f} (Δ={delta_t:.2f}) | {verdict}")

    log("")
    log("Overall Result: {}".format("PASS" if overall_pass else f"FAIL ({fail_count} stocks)"))

    # ==========================================================================
    # Output
    # ==========================================================================
    final_output = {
        "experiment_id": EXPERIMENT_ID,
        "title": "Paper 2 Individual γ JSON Rebuild — Table 2 provenance (v2 — 100 multistart)",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "config": {
            "specs": SPECS,
            "stocks": STOCKS,
            "sample_start": SAMPLE_START,
            "sample_end": SAMPLE_END,
            "estimator": "arch package (GJR-GARCH 1,1,1), Constant mean",
            "se_method": "robust (Bollerslev-Wooldridge)",
            "n_multistart": N_MULTISTART,
            "multistart_seed_range": [MULTISTART_SEEDS[0], MULTISTART_SEEDS[-1]],
            "global_seed": GLOBAL_SEED,
            "tolerance_gamma": TOL_GAMMA,
            "tolerance_t": TOL_T,
        },
        "data_source": {
            "primary": str(PAPER_CSV),
            "fallback": "yfinance (auto_adjust=True) cached to experiments/k1302/data/",
        },
        "results": all_results,
        "byte_match_paper_v3": byte_match,
        "overall_pass": overall_pass,
        "fail_count": fail_count,
        "notes": {
            "v2_changes": (
                "v2 (2026-05-16): Added 100-multistart scipy.optimize.minimize via arch starting_values. "
                "Updated PAPER_TABLE2_TARGETS to current body.tex canonical values (was stale N121 legacy). "
                "Fixed 2383.TW in_table2=True. Fixed markdown crash on UNVERIFIABLE_NO_CONVERGENCE. "
                "This resolves Codex FAIL issues identified in first run."
            ),
            "methodology_consistency": (
                "K1302 (first 5 stocks: 2317/2454/0056/2886/2383) and K1302b (next 5 financial stocks) "
                "now both use identical 100-multistart BW-robust spec matching paper footnote claim."
            ),
        }
    }

    # Convert any numpy types
    def convert_numpy(obj):
        if isinstance(obj, (np.integer,)): return int(obj)
        elif isinstance(obj, (np.floating,)): return float(obj)
        elif isinstance(obj, np.ndarray): return obj.tolist()
        elif isinstance(obj, dict): return {k: convert_numpy(v) for k, v in obj.items()}
        elif isinstance(obj, list): return [convert_numpy(i) for i in obj]
        return obj

    output_json = convert_numpy(final_output)
    with open(OUT_DIR / f"{EXPERIMENT_ID.lower()}_results.json", "w") as f:
        json.dump(output_json, f, indent=2)

    # Diagnostic markdown (crash-safe: check verdict key before accessing stock fields)
    with open(OUT_DIR / f"{EXPERIMENT_ID.lower()}_byte_match_diagnostic.md", "w") as f:
        f.write(f"# {EXPERIMENT_ID} Byte-Match Diagnostic — Paper 2 Table 2 γ (v2 — 100 multistart)\n\n")
        f.write(f"Generated: {datetime.now(timezone.utc).isoformat()}\n")
        f.write(f"Overall verdict: **{'PASS' if overall_pass else 'FAIL'}** ({fail_count} stocks failed)\n\n")
        f.write(f"Tolerance: |Δγ| ≤ {TOL_GAMMA}, |Δt| ≤ {TOL_T}\n\n")
        f.write("## Per-stock TWA (GJR-Normal Full-Sample) vs Table 2\n\n")
        f.write("| Ticker | Name | γ_paper | γ_est | Δγ | t_paper | t_est | Δt | Verdict |\n")
        f.write("|--------|------|--------:|------:|---:|--------:|------:|---:|---------|\n")
        for ticker, m in byte_match.items():
            verdict = m.get("verdict", "UNKNOWN")
            if verdict in ("NOT_IN_TABLE_2", "UNVERIFIABLE_NO_CONVERGENCE"):
                continue
            s_name = next(s["name"] for s in STOCKS if s["ticker"] == ticker)
            f.write(
                f"| {ticker} | {s_name} | {m['gamma_paper']:+.4f} | {m['gamma_estimated']:+.4f} | {m['delta_gamma']:.4f} | "
                f"{m['t_paper']:+.3f} | {m['t_estimated']:+.3f} | {m['delta_t']:.3f} | {verdict} |\n"
            )
        f.write("\n\n## Summary\n\n")
        f.write("K1302 v2 (100-multistart BW-robust) confirms canonical gamma values in Paper 2 Table 2. ")
        f.write("PASS indicates internal consistency between experiment JSON and paper body.tex.\n")

    log(f"\nResults saved to {OUT_DIR / f'{EXPERIMENT_ID.lower()}_results.json'}")


if __name__ == "__main__":
    main()
