"""K1140: HAC Newey-West rolling θ_EAV trend re-test (K1114 follow-up).

Re-does K1114's 9 tests with HAC-robust standard errors.

K1114 caveat: rolling window=500, step=21 → consecutive θ observations share
479/500 ≈ 96% of data. OLS-SE assumes independence → massively underestimated
and t-stats massively inflated. Classic Newey-West naive rule L≈floor(4*(T/100)^(2/9))≈5
is also too small here because effective independent sample ≈ T/(window/step) = T/24.

K1140 reuses K1114's rolling θ_EAV series (no re-fitting) and applies:
1. HAC Newey-West SE for OLS trend regression at three lag settings:
     - L=5  (naive Newey-West rule, reference only)
     - L=24 (conservative: covers 1 full window-overlap period)
     - L=48 (very conservative: covers 2 window-overlap periods)
2. Block-permutation p-value for Spearman rank correlation θ vs VIX (block=24)
3. KS regime split: already a distribution test, relatively robust. Report
   a deflated-n version where effective n = n/24 per regime for reference.
4. BH-FDR correction across all 9 tests at each L setting.

Decision tree:
- HAC L=24 t>3 AND BH-adj p<0.05 → K1114 PASS survives conservative HAC →
    Paper 2 narrative pivot ("temporal heterogeneity" story) defensible.
- HAC L=24 t<2 → K1114 3/9 PASS was OLS artifact → Paper 2 true
    cross-sectional + temporal double NULL.

Reference: Newey & West (1987), Benjamini & Hochberg (1995), Harvey (2016),
Politis & Romano (1994) block bootstrap.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Dict, List, Sequence

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import statsmodels.api as sm
from scipy.stats import ks_2samp, spearmanr


HERE = Path(__file__).resolve().parent
K1114_RESULTS = HERE.parent / "k1114" / "k1114_results.json"

# If not present in worktree, fall back to repo root copy
if not K1114_RESULTS.exists():
    # walk up until repo root
    candidate = Path("/Users/yhlai0911/Desktop/volpred-research/experiments/k1114/k1114_results.json")
    if candidate.exists():
        K1114_RESULTS = candidate

L_SETTINGS = [5, 24, 48]
VIX_LOW_Q = 0.33
VIX_HIGH_Q = 0.67
N_PERM = 5000
BLOCK_SIZE = 24  # matches window/step ratio = 500/21
SEED = 42


def newey_west_trend(theta: Sequence[float], lag: int) -> Dict[str, float]:
    """OLS regress θ_t = α + β·t + ε with HAC Newey-West SE."""
    y = np.asarray(theta, dtype=float)
    n = len(y)
    x = np.arange(n, dtype=float)
    X = sm.add_constant(x)
    model = sm.OLS(y, X).fit(cov_type="HAC", cov_kwds={"maxlags": int(lag)})
    # Also run plain OLS for reference
    ols = sm.OLS(y, X).fit()
    return {
        "n": int(n),
        "slope_per_window_step": float(model.params[1]),
        # Each window step is 21 trading days; convert to per-day for comparability
        "slope_per_day": float(model.params[1] / 21.0),
        "hac_se": float(model.bse[1]),
        "hac_t": float(model.tvalues[1]),
        "hac_p": float(model.pvalues[1]),
        "ols_se": float(ols.bse[1]),
        "ols_t": float(ols.tvalues[1]),
        "ols_p": float(ols.pvalues[1]),
        "lag": int(lag),
    }


def block_permutation_spearman(theta: Sequence[float], vix: Sequence[float],
                                block_size: int = BLOCK_SIZE,
                                n_perm: int = N_PERM,
                                seed: int = SEED) -> Dict[str, float]:
    """Spearman ρ with block-permutation null.

    We permute blocks of size `block_size` of θ-series then correlate with
    the original vix-series. This preserves local autocorrelation structure
    within blocks while destroying the block-level coupling to VIX.
    """
    rng = np.random.default_rng(seed)
    t = np.asarray(theta, dtype=float)
    v = np.asarray(vix, dtype=float)
    n = len(t)
    if n != len(v):
        raise ValueError("theta and vix length mismatch")

    # Observed
    rho_obs, p_asym = spearmanr(t, v)

    # Block indices
    n_blocks_full = n // block_size
    remainder = n - n_blocks_full * block_size
    block_starts = [i * block_size for i in range(n_blocks_full)]
    if remainder > 0:
        block_starts.append(n_blocks_full * block_size)

    count_extreme = 0
    rho_null: List[float] = []
    for _ in range(int(n_perm)):
        order = list(block_starts)
        rng.shuffle(order)
        pieces = []
        for s in order:
            end = min(s + block_size, n)
            pieces.append(t[s:end])
        t_perm = np.concatenate(pieces)
        # Length preserved by construction
        rho_b, _ = spearmanr(t_perm, v)
        rho_null.append(rho_b)
        if abs(rho_b) >= abs(rho_obs):
            count_extreme += 1
    p_block = (count_extreme + 1) / (n_perm + 1)
    # Approximate block-HAC t-stat using block-bootstrap SE
    rho_null_arr = np.array(rho_null)
    se_rho = float(np.std(rho_null_arr, ddof=1))
    t_block = float(rho_obs / se_rho) if se_rho > 0 else float("nan")
    return {
        "rho": float(rho_obs),
        "asymptotic_p": float(p_asym),
        "block_perm_p": float(p_block),
        "block_bootstrap_se": se_rho,
        "block_t_stat": t_block,
        "n_perm": int(n_perm),
        "block_size": int(block_size),
    }


def ks_with_effective_n(theta_low: Sequence[float], theta_high: Sequence[float],
                        effective_divisor: float = BLOCK_SIZE) -> Dict[str, float]:
    """KS 2-sample with raw and deflated effective-n p-values.

    The standard KS p assumes each observation is independent. With 96% overlap,
    effective n per group ≈ n_raw / 24. We recompute p using the effective n in
    the Kolmogorov-Smirnov asymptotic formula.
    """
    a = np.asarray(theta_low, dtype=float)
    b = np.asarray(theta_high, dtype=float)
    ks_stat, p_raw = ks_2samp(a, b)

    # KS effective-n adjusted: p = 2 * sum_{k=1..inf}(-1)^(k-1) * exp(-2 k^2 λ^2)
    # where λ = sqrt(n_eff) * D, n_eff = (n1*n2)/(n1+n2)  adjusted by divisor
    n1, n2 = len(a), len(b)
    n_eff_raw = (n1 * n2) / (n1 + n2)
    n_eff_deflated = n_eff_raw / effective_divisor
    if n_eff_deflated <= 0:
        p_deflated = 1.0
    else:
        lam = np.sqrt(n_eff_deflated) * ks_stat
        # Kolmogorov distribution via series expansion
        k = np.arange(1, 101)
        p_deflated = 2.0 * np.sum(((-1) ** (k - 1)) * np.exp(-2.0 * (k * lam) ** 2))
        p_deflated = float(np.clip(p_deflated, 0.0, 1.0))
    return {
        "ks_stat": float(ks_stat),
        "raw_p": float(p_raw),
        "effective_n_divisor": float(effective_divisor),
        "effective_n": float(n_eff_deflated),
        "effective_n_p": float(p_deflated),
        "n_low": int(n1),
        "n_high": int(n2),
        "mean_theta_low": float(np.mean(a)) if n1 > 0 else float("nan"),
        "mean_theta_high": float(np.mean(b)) if n2 > 0 else float("nan"),
    }


def block_bootstrap_trend(theta: Sequence[float], block_size: int = BLOCK_SIZE,
                           n_boot: int = N_PERM, seed: int = SEED) -> Dict[str, float]:
    """Block-permutation test for OLS trend slope.

    Under H0 (no trend), breaking θ into blocks and permuting preserves the
    within-block autocorrelation while destroying the between-block order.
    Regress the permuted series on the original index x and compute the
    slope's null distribution. This is a stricter test than Newey-West HAC
    when the series has structural curvature that HAC underestimates.
    """
    rng = np.random.default_rng(seed)
    t = np.asarray(theta, dtype=float)
    n = len(t)
    x = np.arange(n, dtype=float)
    slope_obs = float(np.polyfit(x, t, 1)[0])

    n_blocks = n // block_size
    block_starts = [i * block_size for i in range(n_blocks)]
    if n - n_blocks * block_size > 0:
        block_starts.append(n_blocks * block_size)

    slopes = np.empty(n_boot, dtype=float)
    for i in range(int(n_boot)):
        order = list(block_starts)
        rng.shuffle(order)
        pieces = [t[s:min(s + block_size, n)] for s in order]
        t_perm = np.concatenate(pieces)
        slopes[i] = np.polyfit(x, t_perm, 1)[0]

    p_block = (np.sum(np.abs(slopes) >= abs(slope_obs)) + 1) / (n_boot + 1)
    se_block = float(np.std(slopes, ddof=1))
    t_block = float(slope_obs / se_block) if se_block > 0 else float("nan")
    # Lag-1 autocorrelation of θ for diagnostics
    tc = t - np.mean(t)
    rho1 = float(np.corrcoef(tc[:-1], tc[1:])[0, 1])
    return {
        "slope_obs": slope_obs,
        "slope_per_day": slope_obs / 21.0,
        "block_perm_p": float(p_block),
        "block_bootstrap_se": se_block,
        "block_t_stat": t_block,
        "lag1_acf": rho1,
        "block_size": int(block_size),
        "n_boot": int(n_boot),
    }


def bh_fdr(pvals: Sequence[float]) -> np.ndarray:
    """Benjamini-Hochberg FDR adjusted p-values."""
    p = np.asarray(pvals, dtype=float)
    n = len(p)
    order = np.argsort(p)
    ranked = p[order]
    adj = ranked * n / (np.arange(n) + 1)
    # Enforce monotonicity from the right
    adj = np.minimum.accumulate(adj[::-1])[::-1]
    adj = np.clip(adj, 0.0, 1.0)
    out = np.empty_like(adj)
    out[order] = adj
    return out


def main() -> None:
    t0 = time.time()
    print(f"K1140: HAC Newey-West rolling θ_EAV trend re-test")
    print(f"Reading K1114 series from: {K1114_RESULTS}")

    with open(K1114_RESULTS, "r", encoding="utf-8") as f:
        k1114 = json.load(f)

    config_in = k1114["config"]
    print(f"K1114 config: window={config_in['window_obs']} step={config_in['step_obs']}")
    print(f"  Implied L_conservative = window/step = {config_in['window_obs']/config_in['step_obs']:.2f}")
    print(f"  L settings to test: {L_SETTINGS}")

    stocks = ["TSMC", "UMC", "MediaTek"]
    per_stock: Dict[str, dict] = {}

    # Collect all p-values per L setting for BH-FDR (9 per L)
    # Test labels: {stock} {trend|spearman|regime}
    pval_groups = {L: [] for L in L_SETTINGS}
    label_order: List[str] = []

    for stock in stocks:
        s = k1114["per_stock_results"][stock]
        theta = np.array(s["theta2_series"], dtype=float)
        window_info = s["window_info"]
        vix_end = np.array([w["vix_end"] for w in window_info], dtype=float)
        assert len(theta) == len(vix_end)
        print(f"\n=== {stock}: n_obs={len(theta)} ===")
        print(f"  θ mean={np.mean(theta):.3e}, std={np.std(theta):.3e}")

        entry: Dict[str, dict] = {
            "n_obs": int(len(theta)),
            "theta2_mean": float(np.mean(theta)),
            "theta2_std": float(np.std(theta)),
            "k1114_test1_trend": s["test1_trend"],
            "k1114_test2_spearman_vix": s["test2_spearman_vix"],
            "k1114_test3_regime_ks": s["test3_regime_ks"],
        }

        # --- Test 1: HAC trend at multiple lags ---
        entry["hac_trend"] = {}
        for L in L_SETTINGS:
            nw = newey_west_trend(theta, L)
            entry["hac_trend"][f"L{L}"] = nw
            print(f"  Trend (L={L}): slope/day={nw['slope_per_day']:.3e}, "
                  f"HAC t={nw['hac_t']:.3f}, HAC p={nw['hac_p']:.4g} "
                  f"(OLS t={nw['ols_t']:.3f}, OLS p={nw['ols_p']:.4g})")

        # --- Test 1b: Block-bootstrap trend slope (stricter than HAC) ---
        bbt = block_bootstrap_trend(theta, block_size=BLOCK_SIZE,
                                     n_boot=N_PERM, seed=SEED)
        entry["block_bootstrap_trend"] = bbt
        print(f"  Trend (block-boot, blk={BLOCK_SIZE}): slope/day={bbt['slope_per_day']:.3e}, "
              f"block t={bbt['block_t_stat']:.3f}, block-perm p={bbt['block_perm_p']:.4g}, "
              f"lag1 ACF={bbt['lag1_acf']:.3f}")

        # --- Test 2: Block-permutation Spearman ---
        bp = block_permutation_spearman(theta, vix_end, block_size=BLOCK_SIZE,
                                          n_perm=N_PERM, seed=SEED)
        entry["block_spearman"] = bp
        print(f"  Spearman: ρ={bp['rho']:.3f}, asym p={bp['asymptotic_p']:.4g}, "
              f"block-perm p={bp['block_perm_p']:.4g}, block t={bp['block_t_stat']:.3f}")

        # --- Test 3: KS with effective n ---
        vix_low_thr = np.quantile(vix_end, VIX_LOW_Q)
        vix_high_thr = np.quantile(vix_end, VIX_HIGH_Q)
        mask_low = vix_end <= vix_low_thr
        mask_high = vix_end >= vix_high_thr
        theta_low = theta[mask_low]
        theta_high = theta[mask_high]
        ks_res = ks_with_effective_n(theta_low, theta_high, effective_divisor=BLOCK_SIZE)
        entry["ks_regime"] = ks_res
        print(f"  KS regime: D={ks_res['ks_stat']:.3f}, raw p={ks_res['raw_p']:.4g}, "
              f"effective-n p={ks_res['effective_n_p']:.4g} "
              f"(n_low={ks_res['n_low']}, n_high={ks_res['n_high']}, "
              f"n_eff={ks_res['effective_n']:.2f})")

        # Populate pval_groups (one entry per L for trend; Spearman uses block-perm p at every L;
        # KS uses effective-n p at every L)
        for L in L_SETTINGS:
            pval_groups[L].append(entry["hac_trend"][f"L{L}"]["hac_p"])
            label_order_idx = len(label_order)
            if L == L_SETTINGS[0]:
                label_order.append(f"{stock}:trend")
        # Spearman and KS don't depend on L
        for L in L_SETTINGS:
            pval_groups[L].append(bp["block_perm_p"])
            if L == L_SETTINGS[0]:
                label_order.append(f"{stock}:spearman_block")
        for L in L_SETTINGS:
            pval_groups[L].append(ks_res["effective_n_p"])
            if L == L_SETTINGS[0]:
                label_order.append(f"{stock}:regime_effn")

        per_stock[stock] = entry

    # BH-FDR per L setting (9 p-values each)
    bh_results: Dict[str, list] = {}
    for L in L_SETTINGS:
        raw = np.array(pval_groups[L])
        adj = bh_fdr(raw)
        bh_table = []
        for i, label in enumerate(label_order):
            bh_table.append({
                "label": label,
                "raw_p": float(raw[i]),
                "bh_adj_p": float(adj[i]),
                "bh_pass": bool(adj[i] < 0.05),
            })
        bh_results[f"L{L}"] = bh_table

    # Strictest layer: replace trend p-values with block-bootstrap p-values
    # (keeps Spearman block-perm and KS effective-n the same)
    strictest_pvals: List[float] = []
    strictest_labels: List[str] = []
    for stock in stocks:
        strictest_labels.append(f"{stock}:trend_blockboot")
        strictest_pvals.append(per_stock[stock]["block_bootstrap_trend"]["block_perm_p"])
        strictest_labels.append(f"{stock}:spearman_block")
        strictest_pvals.append(per_stock[stock]["block_spearman"]["block_perm_p"])
        strictest_labels.append(f"{stock}:regime_effn")
        strictest_pvals.append(per_stock[stock]["ks_regime"]["effective_n_p"])
    strictest_adj = bh_fdr(np.array(strictest_pvals))
    bh_results["block_bootstrap_strictest"] = [
        {
            "label": strictest_labels[i],
            "raw_p": float(strictest_pvals[i]),
            "bh_adj_p": float(strictest_adj[i]),
            "bh_pass": bool(strictest_adj[i] < 0.05),
        }
        for i in range(len(strictest_pvals))
    ]

    # ---------- Core verdict ----------
    print("\n" + "=" * 70)
    print("CORE VERDICT (conservative L=24, Newey-West HAC)")
    print("=" * 70)
    survived = []
    for row in bh_results["L24"]:
        tag = "PASS" if row["bh_pass"] else "NS"
        print(f"  {row['label']:30s} raw p={row['raw_p']:.4g}  BH-adj p={row['bh_adj_p']:.4g}  [{tag}]")
        if row["bh_pass"]:
            survived.append(row["label"])
    print()
    if survived:
        print(f"  SURVIVED BH-FDR @ L=24: {survived}")
    else:
        print("  NO BH-FDR survivors @ L=24 → K1114 3/9 PASS collapse under HAC.")

    print("\n" + "=" * 70)
    print("STRICTEST VERDICT (block-bootstrap trend + block-perm Spearman + effective-n KS)")
    print("=" * 70)
    survived_strict = []
    for row in bh_results["block_bootstrap_strictest"]:
        tag = "PASS" if row["bh_pass"] else "NS"
        print(f"  {row['label']:30s} raw p={row['raw_p']:.4g}  BH-adj p={row['bh_adj_p']:.4g}  [{tag}]")
        if row["bh_pass"]:
            survived_strict.append(row["label"])
    print()
    if survived_strict:
        print(f"  STRICTEST SURVIVORS: {survived_strict}")
    else:
        print("  NO STRICTEST SURVIVORS → all K1114 PASS are overlap artifacts.")

    # ---------- Plots ----------
    # Plot 1: OLS vs HAC t-stat comparison for trend
    fig, ax = plt.subplots(1, 1, figsize=(9, 5))
    x = np.arange(len(stocks))
    width = 0.18
    ols_t = [per_stock[s]["hac_trend"]["L5"]["ols_t"] for s in stocks]
    hac_t_5 = [per_stock[s]["hac_trend"]["L5"]["hac_t"] for s in stocks]
    hac_t_24 = [per_stock[s]["hac_trend"]["L24"]["hac_t"] for s in stocks]
    hac_t_48 = [per_stock[s]["hac_trend"]["L48"]["hac_t"] for s in stocks]
    ax.bar(x - 1.5 * width, ols_t, width, label="OLS t (K1114)", color="#888")
    ax.bar(x - 0.5 * width, hac_t_5, width, label="HAC L=5", color="#4e79a7")
    ax.bar(x + 0.5 * width, hac_t_24, width, label="HAC L=24 (conservative)", color="#f28e2b")
    ax.bar(x + 1.5 * width, hac_t_48, width, label="HAC L=48 (very conservative)", color="#e15759")
    ax.axhline(3.0, color="red", ls="--", alpha=0.6, label="Harvey |t|>3.0")
    ax.axhline(-3.0, color="red", ls="--", alpha=0.6)
    ax.axhline(2.0, color="orange", ls=":", alpha=0.6, label="|t|>2.0")
    ax.axhline(-2.0, color="orange", ls=":", alpha=0.6)
    ax.axhline(0.0, color="black", lw=0.5)
    ax.set_xticks(x)
    ax.set_xticklabels(stocks)
    ax.set_ylabel("t-statistic for trend slope")
    ax.set_title("K1140: OLS vs Newey-West HAC t-stat for θ_EAV trend\n(K1114 rolling window=500, step=21)")
    ax.legend(loc="best", fontsize=8)
    ax.grid(True, alpha=0.3)
    plt.tight_layout()
    p1 = HERE / "k1140_hac_vs_ols_tstat.png"
    plt.savefig(p1, dpi=130)
    plt.close()
    print(f"saved {p1}")

    # Plot 2: HAC SE and t-stat as function of L for each stock
    fig, axes = plt.subplots(1, 2, figsize=(12, 5), sharex=True)
    Ls_plot = list(range(1, 61))
    for stock in stocks:
        theta = np.array(k1114["per_stock_results"][stock]["theta2_series"], dtype=float)
        ses = []
        ts = []
        for L in Ls_plot:
            nw = newey_west_trend(theta, L)
            ses.append(nw["hac_se"])
            ts.append(nw["hac_t"])
        axes[0].plot(Ls_plot, ses, label=stock)
        axes[1].plot(Ls_plot, ts, label=stock)
    for L_ref, c in zip(L_SETTINGS, ["#4e79a7", "#f28e2b", "#e15759"]):
        axes[0].axvline(L_ref, color=c, ls="--", alpha=0.5)
        axes[1].axvline(L_ref, color=c, ls="--", alpha=0.5, label=f"L={L_ref}")
    axes[1].axhline(3.0, color="red", ls=":", alpha=0.6, label="Harvey |t|>3")
    axes[1].axhline(-3.0, color="red", ls=":", alpha=0.6)
    axes[1].axhline(2.0, color="orange", ls=":", alpha=0.4)
    axes[1].axhline(-2.0, color="orange", ls=":", alpha=0.4)
    axes[0].set_xlabel("Newey-West lag L")
    axes[0].set_ylabel("HAC SE(slope)")
    axes[0].set_title("HAC SE vs lag")
    axes[0].legend()
    axes[0].grid(True, alpha=0.3)
    axes[1].set_xlabel("Newey-West lag L")
    axes[1].set_ylabel("HAC t(slope)")
    axes[1].set_title("HAC t-stat vs lag")
    axes[1].legend(fontsize=8)
    axes[1].grid(True, alpha=0.3)
    plt.tight_layout()
    p2 = HERE / "k1140_L_sensitivity.png"
    plt.savefig(p2, dpi=130)
    plt.close()
    print(f"saved {p2}")

    # ---------- Save results ----------
    results = {
        "experiment_id": "K1140",
        "title": "HAC Newey-West rolling θ_EAV trend re-test (K1114 follow-up)",
        "author": "VolPred Research System (Claude)",
        "timestamp_utc": pd.Timestamp.utcnow().isoformat(),
        "source": str(K1114_RESULTS),
        "config": {
            "k1114_window_obs": config_in["window_obs"],
            "k1114_step_obs": config_in["step_obs"],
            "L_settings": L_SETTINGS,
            "block_size": BLOCK_SIZE,
            "n_perm": N_PERM,
            "vix_low_quantile": VIX_LOW_Q,
            "vix_high_quantile": VIX_HIGH_Q,
            "random_seed": SEED,
        },
        "per_stock": per_stock,
        "bh_fdr_table_by_L": bh_results,
        "label_order": label_order,
        "core_verdict": {
            "conservative_L": 24,
            "survivors_hac_L24_bh_fdr": survived,
            "survivors_strictest_bh_fdr": survived_strict,
            "k1114_3_of_9_pass_fully_collapses": len(survived_strict) == 0,
        },
        "elapsed_seconds": time.time() - t0,
    }

    out = HERE / "k1140_results.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False, default=str)
    print(f"\nsaved {out}")
    print(f"elapsed: {results['elapsed_seconds']:.1f}s")


if __name__ == "__main__":
    main()
