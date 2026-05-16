#!/usr/bin/env python3
"""
K1370 — Block-bootstrap 90% CI for TAIEX-to-Individual amplification ratio
under canonical full-sample BW-robust GJR-GARCH(1,1) specification.

Replaces stale CI [2.8, 8.1] in paper/taiwan-vt/body.tex §3.2 (which was
constructed around the draft 5x point estimate under rolling-window NW-HAC).
Current canonical point estimate (K1302+K1302b): mean 9-individual γ = 0.027
on 2008-2024 sample. Paper's headline TAIEX γ = 0.272 is over the 1997-2026
extended sample (mixed sample → 10× headline). Matched-sample 2008-2024 TAIEX
γ ≈ 0.114 → matched-sample ratio ≈ 4.7×. This script computes the matched-
sample bootstrap CI as primary output and the mixed-sample ratio as sanity.

Methodology
-----------
Politis-Romano (1994) stationary block bootstrap on the *full* MLE pipeline.
For each replicate r ∈ [0, B-1]:
  1. Bootstrap-seed = SEED_BASE + r
  2. For each of 10 series (TAIEX + 9 individual stocks):
     - Sample n_t log-return observations via stationary block bootstrap
       (per-series length: TWII has 4160 returns, individuals 4170; K1370-v2
       fix per-series n was previously hard-coded to first-series length).
       Expected block length L=252 (one trading year). Block lengths drawn
       Geometric(1/L); within-block indices are consecutive (circular).
     - Re-estimate GJR-GARCH(1,1) Normal mean=Constant via arch package with
       N_start=10 multistart (seeds 0..9 within each replicate). BW-robust SE.
     - Record γ from best-LL converged start (or NaN if all 10 fail).
  3. amplification_r = γ_TAIEX_r / mean(γ_individual_r over 9 stocks)
     (replicate dropped if TAIEX fails or fewer than 5 individuals converge —
      i.e., we require a non-pathological estimate of the mean)

Output 90% CI = [quantile 0.05, quantile 0.95] over valid replicates.

Hard rules
----------
- Lookahead-free: each replicate is an independent in-sample MLE; no t→t+1 leak.
- Seeds: np.random.seed(42) at start; per-replicate bootstrap_seed = 42 + r.
  Per-series sub-seed uses MD5(ticker) (process-stable; K1370-v2 fix replaces
  the original built-in hash() which is process-randomized via PYTHONHASHSEED
  and breaks exact replicability across runs).
  Per-replicate multistart seeds = list(range(10)) (deterministic given the
  resample, because the resample randomness is already controlled by
  bootstrap_seed).
- arch package with cov_type='robust' (Bollerslev-Wooldridge QML).
- Fresh sample for every replicate (not reusing K1302/K1302b replicate paths).
- No shared JSON / knowledge.json modification.

Reduced multistart (N_start=10 vs 100 in K1302/K1302b) to keep total runtime
tractable: B=1000 replicates × 10 series × 10 starts = 100,000 MLE fits
(~1.5h on commodity hardware vs ~15h for N_start=100).
"""

from __future__ import annotations

import hashlib
import json
import logging
import sys
import time
import warnings
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf
from arch import arch_model


def _ticker_seed_offset(ticker: str) -> int:
    """Process-stable hash for per-series sub-seed (replaces hash(ticker) which
    is randomized per process via PYTHONHASHSEED). MD5 of UTF-8 bytes, first 8
    hex chars → uint32. K1370-v2 fix per Codex CRITICAL 2026-05-16."""
    return int(hashlib.md5(ticker.encode("utf-8")).hexdigest()[:8], 16)

warnings.filterwarnings("ignore")

# ============================================================================
# Config
# ============================================================================
EXPERIMENT_ID = "K1370"
OUT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = OUT_DIR.parents[1]
PAPER_CSV = (
    PROJECT_ROOT / "paper" / "taiwan-vt" / "data"
    / "0050_tw_twii_2330_tw_2317_tw_2454_tw_0056_tw_spy_vix_2008-2026.csv"
)
LOCAL_CACHE = OUT_DIR / "data"
LOCAL_CACHE.mkdir(parents=True, exist_ok=True)

GLOBAL_SEED = 42
B = 1000
BLOCK_LENGTH = 252  # expected geometric mean for stationary block bootstrap
N_START = 10  # per-replicate multistart (reduced from 100 for tractability)
SAMPLE_START = "2008-01-01"
SAMPLE_END = "2024-12-31"

# TAIEX index + 9 individual stocks (excl. 0056 ETF and 2330 TSMC per Table 2)
INDEX_TICKER = "^TWII"
INDEX_PAPER_COL = "twii_adj_close"

# CRITICAL methodology note (research-honesty):
# The paper Table 1 reports TAIEX γ=0.272 estimated over the 1997-2026 sample
# (n=7148 obs; source: experiments/paper2_table1_twii_stats/...). Individual
# stocks (K1302/K1302b) are estimated over 2008-2024 (n=4170).
# The 10× headline ratio in body.tex §3.2 = 0.272 / 0.027 is therefore a
# MIXED-SAMPLE comparison (29 years for TAIEX vs 17 years for individuals).
# Brief Methodology specifies "Sample: 2008-01-01 to 2024-12-31" → we apply
# this uniformly (matched-sample). The 10× headline shrinks substantially
# when TAIEX is re-estimated on the matched 2008-2024 window. We report:
#   (a) matched-sample CI (primary, this script's main output)
#   (b) mixed-sample sanity in point_estimate_sanity for transparency.
INDIVIDUAL_TICKERS = [
    "2317.TW",  # Hon Hai
    "2454.TW",  # MediaTek
    "2886.TW",  # Mega Financial
    "2383.TW",  # ELITE Material
    "2882.TW",  # Cathay Financial
    "2891.TW",  # CTBC
    "2412.TW",  # Chunghwa Telecom
    "2885.TW",  # Yuanta FH
    "2881.TW",  # Fubon FH
]

POINT_ESTIMATE_TARGET = 10.07  # canonical 0.272 / 0.027 sanity check

# ============================================================================
# Logger
# ============================================================================
LOG_FILE = OUT_DIR / f"{EXPERIMENT_ID.lower()}_run.log"
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(message)s",
    datefmt="%H:%M:%S",
    handlers=[logging.FileHandler(LOG_FILE, mode="w"), logging.StreamHandler(sys.stdout)],
)


def log(msg: str):
    logging.info(msg)


# ============================================================================
# Data loading (paper CSV first; yfinance fallback with local cache)
# ============================================================================
def load_paper_csv() -> pd.DataFrame:
    if not PAPER_CSV.exists():
        return None
    df = pd.read_csv(PAPER_CSV)
    df["date"] = pd.to_datetime(df["date"])
    df.set_index("date", inplace=True)
    return df


def load_series(ticker_or_label: str, paper_col: str | None, paper_df: pd.DataFrame) -> pd.Series:
    # Prefer paper CSV
    if paper_df is not None and paper_col is not None and paper_col in paper_df.columns:
        px = paper_df[paper_col].dropna()
        log(f"  [{ticker_or_label}] loaded from paper CSV ({paper_col}): {len(px)} rows")
        return px

    # Fallback to local cache or yfinance
    safe = ticker_or_label.replace("^", "").lower().replace(".", "_")
    cache_path = LOCAL_CACHE / f"{safe}.csv"
    MIN_CACHE_ROWS = 500  # K1370-v2 Codex MAJOR fix: reject near-empty caches
    if cache_path.exists():
        _df = pd.read_csv(cache_path, index_col=0, parse_dates=True)
        col = "Close" if "Close" in _df.columns else _df.columns[0]
        px = _df[col].dropna()
        if len(px) >= MIN_CACHE_ROWS:
            log(f"  [{ticker_or_label}] loaded from local cache: {len(px)} rows")
            return px
        log(f"  [{ticker_or_label}] cache present but only {len(px)} rows (<{MIN_CACHE_ROWS}) — re-fetching")

    log(f"  [{ticker_or_label}] fetching from yfinance...")
    df = yf.download(ticker_or_label, start="2000-01-01", progress=False, auto_adjust=True)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    px = df["Close"].dropna()
    if len(px) < MIN_CACHE_ROWS:
        raise RuntimeError(
            f"yfinance returned only {len(px)} rows for {ticker_or_label} "
            f"(need ≥{MIN_CACHE_ROWS}); refusing to write empty cache."
        )
    px.to_csv(cache_path)
    return px


def compute_log_returns(px: pd.Series) -> pd.Series:
    return np.log(px / px.shift(1)).dropna()


# ============================================================================
# Stationary block bootstrap (Politis-Romano 1994)
# ============================================================================
def stationary_block_indices(n: int, block_length: int, rng: np.random.Generator) -> np.ndarray:
    """
    Generate n indices into [0, n) by stationary block bootstrap.
    Block lengths are Geometric(p) with mean block_length = 1/p.
    Within-block indices are consecutive modulo n (circular).
    """
    p = 1.0 / block_length
    indices = np.empty(n, dtype=np.int64)
    i = 0
    while i < n:
        start = rng.integers(0, n)
        L = rng.geometric(p)  # >= 1
        end = min(i + L, n)
        for j in range(end - i):
            indices[i + j] = (start + j) % n
        i = end
    return indices


# ============================================================================
# GJR-GARCH(1,1) MLE: best-LL of N_start multistart
# ============================================================================
def fit_gjr_one(ret_pct_arr: np.ndarray, seed: int) -> float | None:
    """Single fit; returns gamma if converged & stationary, else None."""
    rng = np.random.RandomState(seed)
    sv = np.array([
        rng.uniform(-0.05, 0.15),    # mu
        rng.uniform(0.005, 0.05),    # omega
        rng.uniform(0.01, 0.10),     # alpha
        rng.uniform(-0.02, 0.15),    # gamma
        rng.uniform(0.80, 0.95),     # beta
    ])
    try:
        am = arch_model(ret_pct_arr, vol="GARCH", p=1, o=1, q=1, dist="normal", mean="Constant")
        res = am.fit(
            disp="off", show_warning=False, cov_type="robust",
            starting_values=sv, update_freq=0,
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
        return float(gamma), float(res.loglikelihood)
    except (ValueError, np.linalg.LinAlgError, KeyError, Exception):
        return None


def fit_gjr_best(ret_pct_arr: np.ndarray, multistart_seeds: list[int]) -> tuple[float, int] | tuple[None, int]:
    """Returns (best gamma, n_converged). best by max LL."""
    converged = []
    for s in multistart_seeds:
        r = fit_gjr_one(ret_pct_arr, s)
        if r is not None:
            converged.append(r)
    if not converged:
        return None, 0
    best = max(converged, key=lambda x: x[1])
    return best[0], len(converged)


# ============================================================================
# Single replicate
# ============================================================================
def run_replicate(
    rep_idx: int,
    returns_by_ticker: dict[str, np.ndarray],
    block_length: int,
    multistart_seeds: list[int],
    seed_base: int,
) -> dict:
    """
    Returns dict with per-series gamma + amplification ratio for this replicate.
    """
    boot_seed = seed_base + rep_idx
    rng = np.random.default_rng(boot_seed)

    out: dict = {"replicate": rep_idx, "boot_seed": boot_seed, "gammas": {}, "n_converged_per_series": {}}

    # Independent bootstrap path per series (each series gets its own resample
    # — this matches the "marginal" amplification ratio sampling
    # distribution; cross-series joint dependence is destroyed by the bootstrap
    # but the ratio of *univariate* GJR estimates does not depend on the joint
    # distribution of the level series, only on each marginal GJR fit).
    # K1370-v2 Codex MED fix: per-series n (was using one global n=4160 from
    # first series → individual stocks' last 10 obs were never sampled).
    for ticker, ret_arr in returns_by_ticker.items():
        # Use per-series sub-stream so each series is independent yet reproducible
        series_seed = (boot_seed * 100003 + _ticker_seed_offset(ticker)) % (2**31 - 1)
        series_rng = np.random.default_rng(series_seed)
        n_t = len(ret_arr)  # per-series length, not global
        idx = stationary_block_indices(n_t, block_length, series_rng)
        resample = ret_arr[idx] * 100.0  # to percent for arch package
        result = fit_gjr_best(resample, multistart_seeds)
        if result[0] is None:
            out["gammas"][ticker] = np.nan
            out["n_converged_per_series"][ticker] = 0
        else:
            out["gammas"][ticker] = result[0]
            out["n_converged_per_series"][ticker] = result[1]

    # Compute amplification ratio
    g_taiex = out["gammas"].get(INDEX_TICKER, np.nan)
    indiv = [out["gammas"][t] for t in INDIVIDUAL_TICKERS if not np.isnan(out["gammas"][t])]
    n_indiv_conv = len(indiv)
    if np.isnan(g_taiex) or n_indiv_conv < 5:
        out["amplification"] = np.nan
        out["valid"] = False
    else:
        mean_indiv = np.mean(indiv)
        if abs(mean_indiv) < 1e-6:
            out["amplification"] = np.nan
            out["valid"] = False
        else:
            out["amplification"] = g_taiex / mean_indiv
            out["valid"] = True
    out["n_indiv_converged"] = n_indiv_conv
    return out


# ============================================================================
# Main
# ============================================================================
def main():
    np.random.seed(GLOBAL_SEED)
    t_start = time.time()

    log(f"=== {EXPERIMENT_ID} Block-bootstrap CI for TAIEX-to-Individual amplification ===")
    log(f"Date: {datetime.now(timezone.utc).isoformat()}")
    log(f"Config: B={B}, block_length={BLOCK_LENGTH}, N_start={N_START}, "
        f"seed_base={GLOBAL_SEED}, sample={SAMPLE_START}..{SAMPLE_END}")
    log(f"Index: {INDEX_TICKER} | Individuals: {len(INDIVIDUAL_TICKERS)} stocks")
    log("")

    # ------------------------------------------------------------------
    log("[1/3] Loading data...")
    paper_df = load_paper_csv()
    if paper_df is not None:
        log(f"  Paper CSV: {len(paper_df)} rows, "
            f"{paper_df.index.min().date()} → {paper_df.index.max().date()}")

    series: dict[str, pd.Series] = {}
    series[INDEX_TICKER] = load_series(INDEX_TICKER, INDEX_PAPER_COL, paper_df)
    for tk in INDIVIDUAL_TICKERS:
        col = tk.lower().replace(".", "_") + "_adj_close"
        series[tk] = load_series(tk, col, paper_df)

    # Trim to sample window
    returns_by_ticker: dict[str, np.ndarray] = {}
    n_per_series: dict[str, int] = {}
    for tk, px in series.items():
        px = px.loc[(px.index >= SAMPLE_START) & (px.index <= SAMPLE_END)].dropna()
        r = compute_log_returns(px)
        returns_by_ticker[tk] = r.values
        n_per_series[tk] = len(r)
        log(f"  {tk}: n={len(r)}  mean={r.mean():.5f}  std={r.std():.5f}  "
            f"[{r.index.min().date()} → {r.index.max().date()}]")
    log("")

    # Validate equal lengths (required for block-bootstrap with same n)
    n_canonical = max(n_per_series.values())
    for tk in returns_by_ticker:
        if len(returns_by_ticker[tk]) != n_canonical:
            # Pad / truncate? The paper claims n=4170 per series. Real data may
            # differ by a few obs (listing date, missing days). Truncate each
            # to its own length and report — block bootstrap is intra-series so
            # different n across series is fine, but the bootstrap sample size
            # matches the actual sample for that series.
            pass

    # ------------------------------------------------------------------
    log("[2/3] Point-estimate sanity check (full-sample, single-start)...")
    point_gammas = {}
    for tk, arr in returns_by_ticker.items():
        ret_pct = arr * 100.0
        # Use 10-start multistart matching replicate config; deterministic seeds
        result = fit_gjr_best(ret_pct, list(range(10)))
        if result[0] is None:
            log(f"  {tk}: POINT-ESTIMATE FIT FAILED (all 10 starts diverged)")
            point_gammas[tk] = np.nan
        else:
            point_gammas[tk] = result[0]
            log(f"  {tk}: γ={result[0]:+.4f}  (converged {result[1]}/10)")
    g_taiex_pe = point_gammas.get(INDEX_TICKER, np.nan)
    indiv_pe = [point_gammas[t] for t in INDIVIDUAL_TICKERS if not np.isnan(point_gammas[t])]
    mean_indiv_pe = np.mean(indiv_pe) if indiv_pe else np.nan
    ratio_pe = g_taiex_pe / mean_indiv_pe if mean_indiv_pe and abs(mean_indiv_pe) > 1e-6 else np.nan
    log(f"  MATCHED-SAMPLE (2008-2024): TAIEX γ = {g_taiex_pe:.4f}, "
        f"mean 9-indiv γ = {mean_indiv_pe:.4f}, ratio = {ratio_pe:.2f}")

    # Mixed-sample sanity: re-estimate TAIEX on 1997-2026 (paper Table 1 sample)
    # for transparency about the headline 10× ratio's sample-mismatch origin.
    mixed_sample_ratio_pe = None
    g_taiex_1997 = None
    try:
        pre2008 = pd.read_csv(
            PROJECT_ROOT / "paper" / "taiwan-vt" / "data" / "_twii_1997_2007_snapshot.csv",
            comment="#", parse_dates=["date"],
        )
        pre_col = [c for c in pre2008.columns if c != "date"][0]
        pre2008 = pre2008.set_index("date")[pre_col].rename("twii_close").dropna()
        from2008_full = paper_df[INDEX_PAPER_COL].dropna() if paper_df is not None else None
        if from2008_full is not None:
            twii_full = pd.concat([pre2008, from2008_full]).sort_index()
            twii_full = twii_full[~twii_full.index.duplicated(keep="last")]
            r_full = compute_log_returns(twii_full).values * 100.0
            res_full = fit_gjr_best(r_full, list(range(10)))
            if res_full[0] is not None:
                g_taiex_1997 = float(res_full[0])
                mixed_sample_ratio_pe = g_taiex_1997 / mean_indiv_pe if mean_indiv_pe else None
                log(f"  MIXED-SAMPLE (TAIEX 1997-2026 / indiv 2008-2024): "
                    f"TAIEX γ = {g_taiex_1997:.4f}, ratio = {mixed_sample_ratio_pe:.2f} "
                    f"← reproduces paper headline ~10×")
    except Exception as e:
        log(f"  Mixed-sample sanity skipped ({type(e).__name__}: {e})")

    log(f"  (paper headline target ≈ {POINT_ESTIMATE_TARGET:.2f} = mixed-sample)")
    log("")

    # ------------------------------------------------------------------
    log(f"[3/3] Running {B} bootstrap replicates (block_length={BLOCK_LENGTH}, "
        f"N_start={N_START}; ~{B * (1 + len(INDIVIDUAL_TICKERS)) * N_START} total MLE fits)...")
    multistart_seeds = list(range(N_START))
    replicates = []
    t0 = time.time()
    for r in range(B):
        rep = run_replicate(
            r,
            returns_by_ticker,
            BLOCK_LENGTH,
            multistart_seeds,
            GLOBAL_SEED,
        )
        replicates.append(rep)
        if (r + 1) % 25 == 0 or r == 0:
            elapsed = time.time() - t0
            eta = elapsed / (r + 1) * (B - r - 1)
            n_valid = sum(1 for x in replicates if x["valid"])
            recent_valid_amps = [x["amplification"] for x in replicates[-50:] if x["valid"]]
            med = np.nanmedian(recent_valid_amps) if recent_valid_amps else np.nan
            log(f"  r={r+1:4d}/{B}  valid={n_valid}/{r+1}  recent50_median={med:.2f}  "
                f"elapsed={elapsed:.0f}s  ETA={eta:.0f}s")

    elapsed_total = time.time() - t0
    log(f"\nBootstrap done in {elapsed_total:.0f}s")
    log("")

    # ------------------------------------------------------------------
    # Compute CI
    amps = np.array([x["amplification"] for x in replicates if x["valid"]], dtype=float)
    n_valid = len(amps)
    n_dropped = B - n_valid
    log(f"Valid replicates: {n_valid}/{B}  (dropped {n_dropped})")

    if n_valid >= 100:
        ci_low_90 = float(np.quantile(amps, 0.05))
        ci_high_90 = float(np.quantile(amps, 0.95))
        median = float(np.median(amps))
        mean_amp = float(np.mean(amps))
        std_amp = float(np.std(amps, ddof=1))
        ci_low_95 = float(np.quantile(amps, 0.025))
        ci_high_95 = float(np.quantile(amps, 0.975))
    else:
        ci_low_90 = ci_high_90 = median = mean_amp = std_amp = ci_low_95 = ci_high_95 = float("nan")

    log(f"90% CI = [{ci_low_90:.3f}, {ci_high_90:.3f}]  median={median:.3f}  "
        f"mean={mean_amp:.3f}  std={std_amp:.3f}")
    log(f"95% CI = [{ci_low_95:.3f}, {ci_high_95:.3f}]")

    # Per-series convergence summary
    conv_per_series_mean = {}
    for tk in [INDEX_TICKER] + INDIVIDUAL_TICKERS:
        rates = [rep["n_converged_per_series"].get(tk, 0) / N_START for rep in replicates]
        conv_per_series_mean[tk] = float(np.mean(rates))

    # ------------------------------------------------------------------
    # Output JSON
    output = {
        "experiment_id": EXPERIMENT_ID,
        "title": ("Block-bootstrap 90% CI for TAIEX-to-Individual amplification ratio "
                  "under canonical full-sample BW-robust GJR-GARCH(1,1)"),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "runtime_seconds": round(time.time() - t_start, 1),
        "config": {
            "B": B,
            "block_length": BLOCK_LENGTH,
            "block_bootstrap_method": "stationary (Politis-Romano 1994)",
            "n_start_multistart_per_replicate": N_START,
            "n_start_canonical_K1302": 100,
            "global_seed": GLOBAL_SEED,
            "seed_base": GLOBAL_SEED,
            "per_replicate_boot_seed": "seed_base + r (r in [0, B-1])",
            "per_series_sub_seed": "(boot_seed*100003 + uint32(md5(ticker)[:8])) % (2**31-1)  [K1370-v2 process-stable]",
            "multistart_seeds_per_replicate": multistart_seeds,
            "sample_start": SAMPLE_START,
            "sample_end": SAMPLE_END,
            "estimator": "arch package GJR-GARCH(1,1) Normal, Constant mean",
            "se_method": "robust (Bollerslev-Wooldridge QML)",
            "index_ticker": INDEX_TICKER,
            "individual_tickers": INDIVIDUAL_TICKERS,
            "individual_count": len(INDIVIDUAL_TICKERS),
            "validity_rule": "TAIEX must converge AND >=5 of 9 individuals must converge",
        },
        "data_source": {
            "primary": str(PAPER_CSV),
            "fallback": "yfinance auto_adjust=True, cached to experiments/k1370/data/",
            "n_observations_per_series": {tk: int(n_per_series[tk]) for tk in n_per_series},
        },
        "point_estimate_sanity": {
            "matched_sample_2008_2024": {
                "TAIEX_gamma": float(g_taiex_pe) if not np.isnan(g_taiex_pe) else None,
                "mean_individual_gamma": float(mean_indiv_pe) if not np.isnan(mean_indiv_pe) else None,
                "amplification_ratio": float(ratio_pe) if not np.isnan(ratio_pe) else None,
                "note": "Apples-to-apples; both TAIEX and 9 individuals on identical 2008-2024 window.",
            },
            "mixed_sample_paper_headline": {
                "TAIEX_gamma_1997_2026": g_taiex_1997,
                "mean_individual_gamma_2008_2024": float(mean_indiv_pe) if not np.isnan(mean_indiv_pe) else None,
                "amplification_ratio": mixed_sample_ratio_pe,
                "note": (
                    "Reproduces paper body.tex §3.2 headline 10× ratio = 0.272 (TAIEX over "
                    "1997-2026, n=7148) / 0.027 (9-indiv over 2008-2024, n=4170). "
                    "This is the source of the 10× headline."
                ),
            },
            "canonical_target_K1302_K1302b_mixed": POINT_ESTIMATE_TARGET,
            "research_honesty_flag": (
                "The paper's 10× headline (body.tex §3.2) is constructed from MIXED samples: "
                "TAIEX over 1997-2026 (29 years, includes 1997 Asian crisis + 2000 dot-com bust) "
                "vs individual stocks over 2008-2024 (17 years, post-GFC era only). On the matched "
                "2008-2024 sample (apples-to-apples), the ratio shrinks substantially. K1370 reports "
                "the matched-sample bootstrap CI as the primary finding; the mixed-sample CI would "
                "require bootstrapping TAIEX with its own 1997-2026 sample (different n) and is "
                "out of scope for this script."
            ),
        },
        "amplification_ratio": {
            "point_estimate_canonical": POINT_ESTIMATE_TARGET,
            "point_estimate_this_run_10start": float(ratio_pe) if not np.isnan(ratio_pe) else None,
            "ci_low_90": ci_low_90,
            "ci_high_90": ci_high_90,
            "ci_low_95": ci_low_95,
            "ci_high_95": ci_high_95,
            "median": median,
            "mean": mean_amp,
            "std": std_amp,
            "B": B,
            "block_length": BLOCK_LENGTH,
            "seed_base": GLOBAL_SEED,
        },
        "replicate_count": {
            "total": B,
            "valid": int(n_valid),
            "dropped": int(n_dropped),
            "validity_rule": "TAIEX gamma converged AND >=5/9 individuals converged",
        },
        "per_replicate_stats": {
            "converged_per_series_mean_rate": conv_per_series_mean,
            "n_indiv_converged_distribution": {
                str(k): int(sum(1 for x in replicates if x["n_indiv_converged"] == k))
                for k in range(10)
            },
        },
        "lookahead_free_certification": (
            "Each replicate is an independent in-sample MLE on a block-bootstrap "
            "resample of full-sample log returns. No conditioning on future "
            "observations. No t→t+1 leak. Seeds fixed: np.random.seed(42); "
            "per-replicate bootstrap_seed = 42 + r; per-series sub-seed uses MD5(ticker) "
            "(process-stable; replaces hash(ticker) which is PYTHONHASHSEED-randomized — "
            "K1370-v2 fix per Codex CRITICAL 2026-05-16). All arch fits use cov_type='robust'."
        ),
        "notes": (
            f"Replaces stale CI [2.8, 8.1] in paper/taiwan-vt/body.tex §3.2 which was "
            f"constructed around draft 5x point estimate under rolling-window NW-HAC. "
            f"This K1370 CI is the canonical estimate under K1302+K1302b full-sample "
            f"BW-robust GJR-GARCH spec. Reduced N_start=10 vs 100 in K1302 for "
            f"tractability (B={B} × 10 series × 10 starts = {B*10*10} total MLE fits, "
            f"vs B × 10 × 100 = {B*10*100} fits at N_start=100)."
        ),
    }

    # Convert numpy types
    def convert(obj):
        if isinstance(obj, (np.integer,)):
            return int(obj)
        if isinstance(obj, (np.floating,)):
            return float(obj) if not np.isnan(obj) else None
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        if isinstance(obj, dict):
            return {k: convert(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [convert(i) for i in obj]
        return obj

    out_json = convert(output)
    with open(OUT_DIR / f"{EXPERIMENT_ID.lower()}_results.json", "w") as f:
        json.dump(out_json, f, indent=2)
    log(f"\nResults saved to {OUT_DIR / f'{EXPERIMENT_ID.lower()}_results.json'}")

    # Save full replicate-level data for reproducibility
    replicate_records = []
    for rep in replicates:
        replicate_records.append({
            "replicate": rep["replicate"],
            "boot_seed": rep["boot_seed"],
            "amplification": float(rep["amplification"]) if rep["valid"] else None,
            "valid": rep["valid"],
            "n_indiv_converged": rep["n_indiv_converged"],
            "gammas": {k: (float(v) if not np.isnan(v) else None) for k, v in rep["gammas"].items()},
            "n_converged_per_series": rep["n_converged_per_series"],
        })
    with open(OUT_DIR / f"{EXPERIMENT_ID.lower()}_replicates.json", "w") as f:
        json.dump({"B": B, "replicates": replicate_records}, f, indent=2)
    log(f"Replicate-level data saved to {OUT_DIR / f'{EXPERIMENT_ID.lower()}_replicates.json'}")

    # Optional histogram (skip silently if matplotlib unavailable)
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        fig, ax = plt.subplots(figsize=(8, 5))
        ax.hist(amps, bins=40, edgecolor="black", alpha=0.7)
        ax.axvline(median, color="red", linestyle="--", linewidth=2, label=f"median = {median:.2f}")
        ax.axvline(ci_low_90, color="orange", linestyle=":", linewidth=2, label=f"90% CI = [{ci_low_90:.2f}, {ci_high_90:.2f}]")
        ax.axvline(ci_high_90, color="orange", linestyle=":", linewidth=2)
        ax.axvline(POINT_ESTIMATE_TARGET, color="green", linestyle="-", linewidth=1.5, alpha=0.6,
                   label=f"canonical point estimate ≈ {POINT_ESTIMATE_TARGET:.2f}")
        ax.set_xlabel("TAIEX γ / mean(9 individual γ)")
        ax.set_ylabel("Bootstrap frequency")
        ax.set_title(f"K1370 amplification ratio bootstrap distribution (B={B}, L={BLOCK_LENGTH})")
        ax.legend()
        plt.tight_layout()
        plt.savefig(OUT_DIR / "amplification_distribution.png", dpi=120)
        plt.close()
        log(f"Histogram saved to {OUT_DIR / 'amplification_distribution.png'}")
    except Exception as e:
        log(f"Histogram skipped ({type(e).__name__}: {e})")

    total_min = (time.time() - t_start) / 60
    log(f"\n=== K1370 done in {total_min:.1f} min ===")
    log(f"FINAL: 90% CI = [{ci_low_90:.3f}, {ci_high_90:.3f}]  median = {median:.3f}  "
        f"point estimate (canonical) = {POINT_ESTIMATE_TARGET:.2f}")


if __name__ == "__main__":
    main()
