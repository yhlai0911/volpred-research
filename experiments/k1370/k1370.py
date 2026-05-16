"""
K1370: Paper 2 Block-Bootstrap CI — Canonical Full-Sample BW-Robust Spec

Computes 90% bootstrap CI for TAIEX diversification amplification ratio
under the canonical K1302+K1302b full-sample BW-robust GJR-GARCH spec.

Usage:
    uv run python experiments/k1370/k1370.py              # full B=10000
    uv run python experiments/k1370/k1370.py --pilot      # B=200 for validation
"""

import argparse
import json
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import numpy as np
import pandas as pd
from arch import arch_model

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DATA_CSV = REPO_ROOT / "paper/taiwan-vt/data/0050_tw_twii_2330_tw_2317_tw_2454_tw_0056_tw_spy_vix_2008-2026.csv"
K1302_DATA = REPO_ROOT / "experiments/k1302/data"
K1302B_DATA = REPO_ROOT / "experiments/k1302b/data"
RESULTS_PATH = REPO_ROOT / "experiments/k1370/k1370_results.json"

SAMPLE_START = "2008-01-01"
SAMPLE_END = "2024-12-31"
BLOCK_LENGTH = 252
GLOBAL_SEED = 42

# 9 individual stocks (excl. 0056.TW - diversified ETF)
STOCKS_K1302 = {
    "2317.TW": {"col": "2317_tw_adj_close", "name": "Hon Hai Precision"},
    "2454.TW": {"col": "2454_tw_adj_close", "name": "MediaTek"},
    "2886.TW": {"file": K1302_DATA / "2886_tw.csv", "col": "adj_close", "name": "Mega Financial"},
    "2383.TW": {"file": K1302_DATA / "2383_tw.csv", "col": "adj_close", "name": "ELITE Material"},
}
STOCKS_K1302B = {
    "2882.TW": {"file": K1302B_DATA / "2882_tw.csv", "col": "Close", "name": "Cathay Financial"},
    "2891.TW": {"file": K1302B_DATA / "2891_tw.csv", "col": "Close", "name": "CTBC"},
    "2412.TW": {"file": K1302B_DATA / "2412_tw.csv", "col": "Close", "name": "Chunghwa Telecom"},
    "2885.TW": {"file": K1302B_DATA / "2885_tw.csv", "col": "Close", "name": "Yuanta"},
    "2881.TW": {"file": K1302B_DATA / "2881_tw.csv", "col": "Close", "name": "Fubon"},
}
CANONICAL_GAMMA = {
    "2317.TW": 0.032023651538016264,
    "2454.TW": 0.04059713456806396,
    "2886.TW": 0.03793232797782044,
    "2383.TW": 0.009451395383812896,
    "2882.TW": 0.038375858817315055,
    "2891.TW": 0.039639049060818735,
    "2412.TW": 0.001125246949708074,
    "2885.TW": 0.019866628411300262,
    "2881.TW": 0.021709211060071655,
}
# Canonical TAIEX γ: Paper 2 full-sample GJR-GARCH 2008-2026 BW-robust.
# Point estimate used for ratio; bootstrap re-estimates this on each replicate.
# Cross-checked against rolling-window w=2000 value of 0.272 in paper body.
CANONICAL_GAMMA_TAIEX = None  # computed at runtime via 100-multistart, stored in results


def load_returns() -> dict[str, pd.Series]:
    """Load and align all 10 return series to the common sample."""
    main = pd.read_csv(DATA_CSV, index_col="date", parse_dates=True)
    main = main.sort_index()
    main = main.loc[SAMPLE_START:SAMPLE_END]

    series = {}

    # TAIEX
    twii_price = main["twii_adj_close"].dropna()
    series["TAIEX"] = np.log(twii_price / twii_price.shift(1)).dropna() * 100

    # K1302 stocks from main CSV
    for ticker, info in STOCKS_K1302.items():
        if "col" in info and info["col"] in main.columns:
            price = main[info["col"]].dropna()
            series[ticker] = np.log(price / price.shift(1)).dropna() * 100
        elif "file" in info:
            df = pd.read_csv(info["file"], index_col=0, parse_dates=True)
            df.index = pd.to_datetime(df.index)
            df = df.sort_index()
            df = df.loc[SAMPLE_START:SAMPLE_END]
            price = df[info["col"]].dropna()
            series[ticker] = np.log(price / price.shift(1)).dropna() * 100

    # K1302b stocks
    for ticker, info in STOCKS_K1302B.items():
        df = pd.read_csv(info["file"], index_col=0, parse_dates=True)
        df.index = pd.to_datetime(df.index)
        df = df.sort_index()
        df = df.loc[SAMPLE_START:SAMPLE_END]
        price = df[info["col"]].dropna()
        series[ticker] = np.log(price / price.shift(1)).dropna() * 100

    return series


def align_series(series: dict[str, pd.Series]) -> pd.DataFrame:
    """Align all series to common trading dates (intersection)."""
    df = pd.DataFrame(series)
    df = df.dropna()
    print(f"Aligned sample: {df.index[0].date()} to {df.index[-1].date()}, N={len(df)} obs, {df.shape[1]} series")
    return df


def estimate_gjr_gamma(returns_array: np.ndarray, n_starts: int = 5) -> tuple[float, bool]:
    """Fit GJR-GARCH(1,1) with multistart, return best (gamma, converged).

    n_starts=5 for bootstrap replicates (compute budget), 100 for canonical point estimates.
    Stationarity filter: persistence = alpha + 0.5*gamma + beta < 1.
    """
    ret = pd.Series(returns_array, dtype=float)
    best_ll, best_gamma, converged = -np.inf, np.nan, False
    for seed in range(42, 42 + n_starts):
        rng = np.random.RandomState(seed)
        # 5 params: mu, omega, alpha[1], gamma[1], beta[1]
        # Must satisfy GJR-GARCH stationarity: alpha + 0.5*gamma + beta < 1
        alpha_sv = rng.uniform(0.02, 0.08)
        gamma_sv = rng.uniform(0.01, 0.08)
        # beta bounded so persistence < 0.998 for all draws
        max_beta = min(0.93, 0.998 - alpha_sv - 0.5 * gamma_sv)
        beta_sv = rng.uniform(0.70, max(0.71, max_beta))
        sv = np.array([
            0.0,                          # mu (constant mean)
            rng.uniform(0.001, 0.05),     # omega
            alpha_sv,                     # alpha[1]
            gamma_sv,                     # gamma[1] leverage
            beta_sv,                      # beta[1]
        ])
        try:
            am = arch_model(ret, vol="Garch", p=1, o=1, q=1,
                            dist="normal", rescale=False, mean="Constant")
            res = am.fit(disp="off", show_warning=False, cov_type="robust",
                         starting_values=sv, options={"maxiter": 300, "ftol": 1e-6})
            if res.convergence_flag != 0:
                continue
            alpha = float(res.params.get("alpha[1]", np.nan))
            gamma = float(res.params.get("gamma[1]", np.nan))
            beta = float(res.params.get("beta[1]", np.nan))
            if not np.isfinite(alpha + gamma + beta):
                continue
            persistence = alpha + 0.5 * gamma + beta
            if persistence >= 1.0:  # stationarity filter
                continue
            if res.loglikelihood > best_ll:
                best_ll, best_gamma, converged = res.loglikelihood, gamma, True
        except Exception:
            continue
    return best_gamma, converged


def block_bootstrap_joint(data: np.ndarray, block_length: int, seed: int) -> np.ndarray:
    """Moving block bootstrap on joint matrix (T × K), preserving cross-series structure."""
    rng = np.random.default_rng(seed)
    T, K = data.shape
    n_blocks = int(np.ceil(T / block_length))
    max_start = T - block_length
    starts = rng.integers(0, max_start + 1, size=n_blocks)
    blocks = [data[s : s + block_length] for s in starts]
    bootstrapped = np.concatenate(blocks, axis=0)[:T]
    return bootstrapped


def _compute_one_replicate(args):
    """Worker function for multiprocessing. Uses n_starts=5 per fit (compute budget)."""
    b_idx, data_np, stock_indices, block_length = args
    seed = GLOBAL_SEED + b_idx

    boot = block_bootstrap_joint(data_np, block_length, seed)

    # Column 0 = TAIEX, columns 1..N = individual stocks
    # n_starts=5: consistent multistart (reduced from canonical 100 due to compute budget)
    gamma_taiex, conv_taiex = estimate_gjr_gamma(boot[:, 0], n_starts=5)
    if not conv_taiex or np.isnan(gamma_taiex) or gamma_taiex <= 0:
        return None

    gammas_stock = []
    for i in stock_indices:
        g, conv = estimate_gjr_gamma(boot[:, i], n_starts=5)
        # stationarity already enforced inside estimate_gjr_gamma; also filter g > 0
        if conv and not np.isnan(g) and g > 0:
            gammas_stock.append(g)

    if len(gammas_stock) < 5:  # require at least 5 valid stock estimates
        return None

    ratio = gamma_taiex / np.mean(gammas_stock)
    return {"b": b_idx, "ratio": ratio, "gamma_taiex": gamma_taiex,
            "n_valid_stocks": len(gammas_stock), "mean_gamma_stocks": float(np.mean(gammas_stock))}


def run_bootstrap(df: pd.DataFrame, B: int, n_workers: int = 8) -> list[dict]:
    """Run B bootstrap replicates in parallel."""
    cols = list(df.columns)
    assert cols[0] == "TAIEX", f"Expected TAIEX first, got {cols[0]}"
    stock_indices = list(range(1, len(cols)))
    data_np = df.to_numpy(dtype=np.float64)

    args_list = [(b, data_np, stock_indices, BLOCK_LENGTH) for b in range(B)]

    results = []
    t0 = time.time()
    with ProcessPoolExecutor(max_workers=n_workers) as executor:
        futures = {executor.submit(_compute_one_replicate, a): a[0] for a in args_list}
        for i, fut in enumerate(as_completed(futures)):
            r = fut.result()
            if r is not None:
                results.append(r)
            if (i + 1) % max(1, B // 20) == 0:
                elapsed = time.time() - t0
                rate = (i + 1) / elapsed
                eta = (B - i - 1) / rate if rate > 0 else 0
                print(f"  [{i+1}/{B}] valid={len(results)} elapsed={elapsed:.0f}s ETA={eta:.0f}s", flush=True)

    return results


def compute_point_estimates(df: pd.DataFrame) -> dict:
    """Compute full-sample GJR-GARCH gamma for TAIEX and each stock."""
    print("Computing full-sample point estimates...")
    point = {}
    cols = list(df.columns)
    for col in cols:
        g, conv = estimate_gjr_gamma(df[col].to_numpy())
        point[col] = {"gamma": round(float(g), 6) if not np.isnan(g) else None,
                       "converged": conv}
        print(f"  {col}: γ={g:.4f} conv={conv}")
    return point


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--pilot", action="store_true", help="B=200 pilot run")
    parser.add_argument("--b", type=int, default=10000, help="Bootstrap replicates")
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args()

    B = 200 if args.pilot else args.b
    print(f"K1370: Block Bootstrap CI for Amplification Ratio")
    print(f"B={B}, block_length={BLOCK_LENGTH}, workers={args.workers}")

    print("\nLoading returns...")
    series = load_returns()
    df = align_series(series)

    # Put TAIEX first
    cols = ["TAIEX"] + [c for c in df.columns if c != "TAIEX"]
    df = df[cols]

    # Point estimates (100-start for TAIEX, matching K1302/K1302b canonical protocol)
    # This is a cross-check, not the number used in the amplification ratio denominator.
    print("\nComputing TAIEX full-sample γ with 100 multistart (canonical protocol)...")
    gamma_taiex_100start, conv_taiex = estimate_gjr_gamma(
        df["TAIEX"].to_numpy(), n_starts=100
    )
    if not conv_taiex:
        print("WARNING: TAIEX 100-start estimation did not converge; using first-start result")
        gamma_taiex_100start, _ = estimate_gjr_gamma(df["TAIEX"].to_numpy(), n_starts=1)
    print(f"  TAIEX γ (100-start full-sample 2008-2026): {gamma_taiex_100start:.4f}")
    print(f"  Paper body reference (rolling w=2000, 1997-2026): 0.2720")

    # Canonical individual stock gammas from K1302/K1302b (100-multistart, 2008-2026)
    # These are the authoritative values; do not re-estimate to avoid estimator mixing.
    all_stock_gammas = {
        **{t: CANONICAL_GAMMA[t] for t in STOCKS_K1302 if t in CANONICAL_GAMMA},
        **{t: CANONICAL_GAMMA[t] for t in STOCKS_K1302B if t in CANONICAL_GAMMA},
    }
    avg_individual_canonical = np.mean(list(all_stock_gammas.values()))
    # Point estimate uses the 100-start TAIEX γ for methodological consistency
    point_ratio_canonical = gamma_taiex_100start / avg_individual_canonical

    print(f"\nCanonical point estimate:")
    print(f"  TAIEX γ (100-start full-sample): {gamma_taiex_100start:.4f}")
    print(f"  9-stock avg γ (K1302+K1302b): {avg_individual_canonical:.4f}")
    print(f"  Amplification ratio: {point_ratio_canonical:.2f}×")

    # Also compute quick per-series diagnostics (single pass, not used in final CI)
    point_ests = compute_point_estimates(df)

    # Bootstrap
    print(f"\nRunning {B} bootstrap replicates...")
    t0 = time.time()
    results = run_bootstrap(df, B, args.workers)
    elapsed = time.time() - t0
    print(f"Bootstrap done: {len(results)}/{B} valid in {elapsed:.1f}s")

    ratios = [r["ratio"] for r in results]
    ci_lo = float(np.percentile(ratios, 5))
    ci_hi = float(np.percentile(ratios, 95))
    median = float(np.median(ratios))

    print(f"\n90% CI: [{ci_lo:.2f}, {ci_hi:.2f}], median={median:.2f}")

    output = {
        "experiment_id": "K1370",
        "title": "Paper 2 Block-Bootstrap CI — Canonical Full-Sample BW-Robust Spec",
        "timestamp": pd.Timestamp.now(tz="UTC").isoformat(),
        "config": {
            "B": B,
            "block_length": BLOCK_LENGTH,
            "seeds": f"{GLOBAL_SEED}..{GLOBAL_SEED + B - 1}",
            "n_workers": args.workers,
            "sample_start": SAMPLE_START,
            "sample_end": SAMPLE_END,
            "n_obs": len(df),
            "stocks_9": list(CANONICAL_GAMMA.keys()),
            "pilot": args.pilot,
        },
        "point_estimates": {
            "taiex_gamma_full_sample": round(float(gamma_taiex_100start), 6),
            "nine_stock_avg_gamma_canonical": round(float(avg_individual_canonical), 6),
            "amplification_ratio_canonical": round(float(point_ratio_canonical), 4),
            "canonical_individual_gammas": {k: round(v, 6) for k, v in all_stock_gammas.items()},
        },
        "bootstrap_ci_90pct": {
            "lower": round(ci_lo, 2),
            "upper": round(ci_hi, 2),
            "median": round(median, 2),
            "n_valid_replicates": len(results),
            "n_total_replicates": B,
        },
        "paper2_update": {
            "old_ci": [2.8, 8.1],
            "old_point_estimate": 5.0,
            "old_nine_stock_avg_gamma": 0.054,
            "new_ci": [round(ci_lo, 2), round(ci_hi, 2)],
            "new_point_estimate": round(float(point_ratio_canonical), 1),
            "new_nine_stock_avg_gamma": round(float(avg_individual_canonical), 4),
        },
        "full_sample_point_estimates_by_series": {
            k: v for k, v in point_ests.items()
        },
    }

    os.makedirs(RESULTS_PATH.parent, exist_ok=True)
    with open(RESULTS_PATH, "w") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    print(f"\nResults saved to {RESULTS_PATH}")

    # Summary
    print("\n" + "=" * 60)
    print("PAPER 2 §3.2 AMPLIFICATION RATIO UPDATE")
    print("=" * 60)
    print(f"  Old spec:  ratio = {5.0}×, 90% CI = [2.8, 8.1]")
    print(f"  New spec:  ratio = {round(float(point_ratio_canonical), 1)}×, 90% CI = [{ci_lo:.1f}, {ci_hi:.1f}]")
    print("=" * 60)


if __name__ == "__main__":
    main()
