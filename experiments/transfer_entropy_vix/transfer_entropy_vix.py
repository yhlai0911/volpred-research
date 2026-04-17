"""
K128: Transfer Entropy — VIX 對資產波動率的真實資訊貢獻量化
============================================================
[提出: Gemini G1, 執行: Claude]

背景：VIX sufficient statistic 已確認 16+ 次（regression/correlation），
但從未用資訊理論方法驗證。Transfer Entropy (Schreiber 2000) 可量化
VIX→資產 RV 的「真實資訊傳遞量」，排除線性相關性干擾。

方法論：
- Transfer Entropy via Frenzel-Pompe (2007) direct kNN CMI estimator
- Vectorized kNN using cKDTree for performance
- 雙向 TE：VIX→asset_RV 和 asset_RV→VIX
- Surrogate shuffle test (200 reps) for statistical significance
- Rolling TE for regime stability
- Multi-lag structure analysis
"""

import warnings
warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd
import yfinance as yf
from scipy.spatial import cKDTree
from scipy.special import digamma
import json
from datetime import datetime
import time

# ============================================================
# 1. Frenzel-Pompe (2007) kNN-based CMI Estimator (Vectorized)
# ============================================================

def frenzel_pompe_cmi(x, y, z, k=5):
    """
    Estimate conditional mutual information I(X;Y|Z) using
    Frenzel & Pompe (2007) direct estimator (vectorized).

    I(X;Y|Z) = psi(k) - <psi(n_xz) + psi(n_yz) - psi(n_z)>
    """
    if x.ndim == 1:
        x = x.reshape(-1, 1)
    if y.ndim == 1:
        y = y.reshape(-1, 1)
    if z.ndim == 1:
        z = z.reshape(-1, 1)

    n = x.shape[0]

    # Add small noise to break ties
    rng = np.random.RandomState(42)
    x = x + rng.randn(*x.shape) * 1e-10
    y = y + rng.randn(*y.shape) * 1e-10
    z = z + rng.randn(*z.shape) * 1e-10

    # Joint and marginal spaces
    xyz = np.hstack([x, y, z])
    xz = np.hstack([x, z])
    yz = np.hstack([y, z])

    # Build trees with Chebyshev norm
    tree_xyz = cKDTree(xyz)
    tree_xz = cKDTree(xz)
    tree_yz = cKDTree(yz)
    tree_z = cKDTree(z)

    # Find k-th neighbor distances in joint space (vectorized)
    dists, _ = tree_xyz.query(xyz, k=k+1, p=np.inf)
    eps = dists[:, -1]  # k-th neighbor distance

    # Vectorized: count neighbors in marginal spaces
    # query_ball_point can be slow in loop; use count_neighbors approach
    n_xz = np.zeros(n, dtype=np.float64)
    n_yz = np.zeros(n, dtype=np.float64)
    n_z = np.zeros(n, dtype=np.float64)

    for i in range(n):
        e = eps[i]
        n_xz[i] = len(tree_xz.query_ball_point(xz[i], e, p=np.inf)) - 1
        n_yz[i] = len(tree_yz.query_ball_point(yz[i], e, p=np.inf)) - 1
        n_z[i] = len(tree_z.query_ball_point(z[i], e, p=np.inf)) - 1

    # Floor at 1
    n_xz = np.maximum(n_xz, 1)
    n_yz = np.maximum(n_yz, 1)
    n_z = np.maximum(n_z, 1)

    cmi = digamma(k) - np.mean(digamma(n_xz) + digamma(n_yz) - digamma(n_z))
    return cmi


def transfer_entropy(source, target, lag=1, k=5, embedding_dim=1):
    """
    TE(source → target) = I(target_t; source_{t-lag} | target_{t-1})
    Using Frenzel-Pompe CMI.
    """
    n = len(source)
    max_delay = max(lag + embedding_dim - 1, embedding_dim)
    start = max_delay

    target_future = target[start:]

    target_past = np.column_stack([
        target[start - i - 1: n - i - 1] for i in range(embedding_dim)
    ])

    source_past = np.column_stack([
        source[start - lag - i: n - lag - i] for i in range(embedding_dim)
    ])

    min_len = min(len(target_future), target_past.shape[0], source_past.shape[0])
    target_future = target_future[:min_len]
    target_past = target_past[:min_len]
    source_past = source_past[:min_len]

    te = frenzel_pompe_cmi(target_future, source_past, target_past, k=k)
    return te


def surrogate_test(source, target, lag=1, k=5, embedding_dim=1, n_surrogates=200):
    """Circular-shift surrogate test."""
    te_real = transfer_entropy(source, target, lag=lag, k=k, embedding_dim=embedding_dim)

    te_surrogates = np.zeros(n_surrogates)
    rng = np.random.RandomState(0)
    for i in range(n_surrogates):
        shift = rng.randint(len(source) // 4, 3 * len(source) // 4)
        source_shifted = np.roll(source, shift)
        te_surrogates[i] = transfer_entropy(source_shifted, target, lag=lag, k=k, embedding_dim=embedding_dim)

    p_value = np.mean(te_surrogates >= te_real)
    return te_real, p_value, te_surrogates


# ============================================================
# 2. Download Data
# ============================================================
print("=" * 70)
print("K128: Transfer Entropy — VIX Information Flow to Asset Volatility")
print("[提出: Gemini G1, 執行: Claude]")
print("=" * 70)

print("\n[1/6] Downloading data...")

assets = {
    "SPY": "SPY",
    "QQQ": "QQQ",
    "GLD": "GLD",
    "TLT": "TLT",
    "EEM": "EEM"
}

start_date = "2007-01-01"
end_date = "2025-01-01"

vix_raw = yf.download("^VIX", start=start_date, end=end_date, progress=False)
if isinstance(vix_raw.columns, pd.MultiIndex):
    vix_raw.columns = vix_raw.columns.get_level_values(0)
vix = vix_raw["Close"].copy()
vix.name = "VIX"

asset_data = {}
for name, ticker in assets.items():
    df = yf.download(ticker, start=start_date, end=end_date, progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    close_col = "Adj Close" if "Adj Close" in df.columns else "Close"
    asset_data[name] = df[close_col].copy()
    print(f"  {name}: {len(df)} days")
print(f"  VIX: {len(vix)} days")

# ============================================================
# 3. Compute Realized Volatility
# ============================================================
print("\n[2/6] Computing realized volatility (22-day rolling)...")

rv_data = {}
for name in assets:
    aligned = pd.DataFrame({"price": asset_data[name], "vix": vix}).dropna()
    ret = aligned["price"].pct_change().dropna()
    rv = ret.rolling(22).std() * np.sqrt(252) * 100
    rv = rv.dropna()
    rv_data[name] = rv
    print(f"  {name}: {len(rv)} RV observations")

# ============================================================
# 4. Main TE Analysis
# ============================================================
SUBSAMPLE = 1000  # Last ~4 years for speed
N_SURROGATES = 200
K_NN = 5
EMBED_DIM = 1  # Single lag embedding (faster, standard)

print(f"\n[3/6] Computing Transfer Entropy (n={SUBSAMPLE}, surr={N_SURROGATES}, k={K_NN}, d={EMBED_DIM})...")
print(f"  Method: Frenzel-Pompe (2007) direct CMI estimator")

results = {}

for name in assets:
    print(f"\n  --- {name} ---")
    t0 = time.time()

    aligned = pd.DataFrame({"rv": rv_data[name], "vix": vix}).dropna()
    if len(aligned) > SUBSAMPLE:
        aligned = aligned.iloc[-SUBSAMPLE:]

    rv_series = aligned["rv"].values
    vix_series = aligned["vix"].values

    rv_std = (rv_series - rv_series.mean()) / rv_series.std()
    vix_std = (vix_series - vix_series.mean()) / vix_series.std()

    n_obs = len(rv_std)

    # TE(VIX → RV)
    print(f"    TE(VIX → {name}_RV)...", end=" ", flush=True)
    te_v2r, p_v2r, surr_v2r = surrogate_test(
        vix_std, rv_std, lag=1, k=K_NN, embedding_dim=EMBED_DIM, n_surrogates=N_SURROGATES
    )
    print(f"TE={te_v2r:.4f}, p={p_v2r:.4f}")

    # TE(RV → VIX)
    print(f"    TE({name}_RV → VIX)...", end=" ", flush=True)
    te_r2v, p_r2v, surr_r2v = surrogate_test(
        rv_std, vix_std, lag=1, k=K_NN, embedding_dim=EMBED_DIM, n_surrogates=N_SURROGATES
    )
    print(f"TE={te_r2v:.4f}, p={p_r2v:.4f}")

    net_te = te_v2r - te_r2v
    elapsed = time.time() - t0
    print(f"    Net TE: {net_te:+.4f} ({elapsed:.1f}s)")

    results[name] = {
        "n_obs": n_obs,
        "te_vix_to_rv": float(te_v2r),
        "te_rv_to_vix": float(te_r2v),
        "net_te": float(net_te),
        "p_vix_to_rv": float(p_v2r),
        "p_rv_to_vix": float(p_r2v),
        "surr_mean_v2r": float(np.mean(surr_v2r)),
        "surr_std_v2r": float(np.std(surr_v2r)),
        "z_score_v2r": float((te_v2r - np.mean(surr_v2r)) / max(np.std(surr_v2r), 1e-10)),
        "z_score_r2v": float((te_r2v - np.mean(surr_r2v)) / max(np.std(surr_r2v), 1e-10)),
        "te_ratio": float(te_v2r / te_r2v) if abs(te_r2v) > 1e-6 else float('inf'),
    }

# ============================================================
# 5. Multi-Lag Structure
# ============================================================
print("\n[4/6] Lag structure (lags 1-10, SPY & GLD)...")

lag_results = {}
for name in ["SPY", "GLD"]:
    print(f"\n  --- {name} ---")
    aligned = pd.DataFrame({"rv": rv_data[name], "vix": vix}).dropna()
    if len(aligned) > SUBSAMPLE:
        aligned = aligned.iloc[-SUBSAMPLE:]

    rv_std = (aligned["rv"].values - aligned["rv"].values.mean()) / aligned["rv"].values.std()
    vix_std = (aligned["vix"].values - aligned["vix"].values.mean()) / aligned["vix"].values.std()

    lag_te = {}
    for lag in range(1, 11):
        te = transfer_entropy(vix_std, rv_std, lag=lag, k=K_NN, embedding_dim=EMBED_DIM)
        lag_te[lag] = float(te)
        print(f"    Lag {lag:2d}: TE={te:.4f}")

    lag_results[name] = lag_te
    best = max(lag_te, key=lag_te.get)
    print(f"    Best: lag={best} (TE={lag_te[best]:.4f})")

# ============================================================
# 6. Rolling TE
# ============================================================
print("\n[5/6] Rolling TE (500-day windows, step=100)...")

WINDOW = 500
STEP = 100

rolling_results = {}
for name in ["SPY", "QQQ", "GLD"]:
    print(f"\n  --- {name} ---")
    aligned = pd.DataFrame({"rv": rv_data[name], "vix": vix}).dropna()

    rv_vals = aligned["rv"].values
    vix_vals = aligned["vix"].values
    dates = aligned.index

    r_v2r, r_r2v, r_dates = [], [], []

    for si in range(0, len(rv_vals) - WINDOW, STEP):
        rv_w = rv_vals[si:si+WINDOW]
        vix_w = vix_vals[si:si+WINDOW]

        rv_s = (rv_w - rv_w.mean()) / rv_w.std()
        vix_s = (vix_w - vix_w.mean()) / vix_w.std()

        te_v = transfer_entropy(vix_s, rv_s, lag=1, k=K_NN, embedding_dim=EMBED_DIM)
        te_r = transfer_entropy(rv_s, vix_s, lag=1, k=K_NN, embedding_dim=EMBED_DIM)

        r_v2r.append(float(te_v))
        r_r2v.append(float(te_r))
        mid = dates[si + WINDOW // 2]
        r_dates.append(str(mid.date()) if hasattr(mid, 'date') else str(mid))

    rolling_results[name] = {
        "dates": r_dates,
        "te_vix_to_rv": r_v2r,
        "te_rv_to_vix": r_r2v,
        "net_te": [v - r for v, r in zip(r_v2r, r_r2v)]
    }

    net_arr = np.array(rolling_results[name]["net_te"])
    pct = np.mean(net_arr > 0) * 100
    print(f"    {len(r_v2r)} windows, VIX dominates {pct:.1f}%, mean net={np.mean(net_arr):.4f}")

# ============================================================
# 7. Linear Comparison
# ============================================================
print("\n[6/6] Linear comparison...")

linear_results = {}
for name in assets:
    aligned = pd.DataFrame({"rv": rv_data[name], "vix": vix}).dropna()
    if len(aligned) > SUBSAMPLE:
        aligned = aligned.iloc[-SUBSAMPLE:]

    rv_a = aligned["rv"].values
    vix_a = aligned["vix"].values

    corr_level = np.corrcoef(rv_a, vix_a)[0, 1]
    corr_lag = np.corrcoef(vix_a[:-1], rv_a[1:])[0, 1]

    # Incremental R²
    from numpy.linalg import lstsq
    y = rv_a[1:]
    X1 = np.column_stack([np.ones(len(y)), rv_a[:-1]])
    X2 = np.column_stack([np.ones(len(y)), rv_a[:-1], vix_a[:-1]])

    b1, _, _, _ = lstsq(X1, y, rcond=None)
    b2, _, _, _ = lstsq(X2, y, rcond=None)

    ss_tot = np.sum((y - y.mean())**2)
    r2_1 = 1 - np.sum((y - X1 @ b1)**2) / ss_tot
    r2_2 = 1 - np.sum((y - X2 @ b2)**2) / ss_tot

    linear_results[name] = {
        "corr_contemporaneous": float(corr_level),
        "corr_lagged": float(corr_lag),
        "r2_own_lag": float(r2_1),
        "r2_with_vix": float(r2_2),
        "delta_r2": float(r2_2 - r2_1),
    }
    print(f"  {name}: corr={corr_level:.3f}, lag_corr={corr_lag:.3f}, dR2={r2_2-r2_1:.4f}")

# ============================================================
# 8. Summary
# ============================================================
print("\n" + "=" * 70)
print("RESULTS SUMMARY")
print("=" * 70)

print("\n--- Table 1: Transfer Entropy (VIX <-> Asset RV) ---")
print(f"{'Asset':<6} {'TE(VIX→RV)':>12} {'p':>8} {'z':>6} {'TE(RV→VIX)':>12} {'p':>8} {'z':>6} {'Net':>8}")
print("-" * 75)

for name in ["SPY", "QQQ", "EEM", "GLD", "TLT"]:
    r = results[name]
    s1 = "***" if r["p_vix_to_rv"]<0.001 else "**" if r["p_vix_to_rv"]<0.01 else "*" if r["p_vix_to_rv"]<0.05 else ""
    s2 = "***" if r["p_rv_to_vix"]<0.001 else "**" if r["p_rv_to_vix"]<0.01 else "*" if r["p_rv_to_vix"]<0.05 else ""
    print(f"{name:<6} {r['te_vix_to_rv']:>10.4f}{s1:<2} {r['p_vix_to_rv']:>8.4f} {r['z_score_v2r']:>6.1f} "
          f"{r['te_rv_to_vix']:>10.4f}{s2:<2} {r['p_rv_to_vix']:>8.4f} {r['z_score_r2v']:>6.1f} "
          f"{r['net_te']:>+8.4f}")

print("\n--- Table 2: TE vs Linear ---")
print(f"{'Asset':<6} {'TE(V→R)':>10} {'corr':>8} {'lag_corr':>10} {'dR2':>8}")
print("-" * 45)
for name in ["SPY", "QQQ", "EEM", "GLD", "TLT"]:
    r = results[name]; lr = linear_results[name]
    print(f"{name:<6} {r['te_vix_to_rv']:>10.4f} {lr['corr_contemporaneous']:>8.3f} "
          f"{lr['corr_lagged']:>10.3f} {lr['delta_r2']:>8.4f}")

print("\n--- Table 3: Lag Structure ---")
print(f"{'Lag':>4}", end="")
for name in lag_results: print(f"  {name:>8}", end="")
print()
for lag in range(1, 11):
    print(f"{lag:>4}", end="")
    for name in lag_results: print(f"  {lag_results[name][lag]:>8.4f}", end="")
    print()

print("\n--- Table 4: Rolling TE Stability ---")
for name in rolling_results:
    net_arr = np.array(rolling_results[name]["net_te"])
    print(f"  {name}: VIX dominates {np.mean(net_arr>0)*100:.1f}%, "
          f"mean={np.mean(net_arr):.4f}, std={np.std(net_arr):.4f}")

# Conclusions
print("\n--- Key Findings ---")
ranked = sorted(results.items(), key=lambda x: x[1]["te_vix_to_rv"], reverse=True)
print(f"1. TE ranking: {' > '.join([f'{n}({r['te_vix_to_rv']:.3f})' for n, r in ranked])}")

sig_n = sum(1 for r in results.values() if r["p_vix_to_rv"] < 0.05)
print(f"2. Significant TE(VIX→RV): {sig_n}/5 at p<0.05")

eq = np.mean([results[n]["te_vix_to_rv"] for n in ["SPY","QQQ","EEM"]])
ne = np.mean([results[n]["te_vix_to_rv"] for n in ["GLD","TLT"]])
print(f"3. Equity={eq:.4f} vs Non-equity={ne:.4f} ({eq/ne:.1f}x)" if ne > 1e-6 else "")

apn = all(r["net_te"] > 0 for r in results.values())
print(f"4. VIX net sender for all 5: {apn}")

print("\n--- Conclusion ---")
if sig_n >= 4 and apn:
    print("  STRONG SUPPORT: VIX is information sender to asset vol (info theory confirms)")
elif sig_n >= 3:
    print("  PARTIAL SUPPORT: VIX info flow significant for majority of assets")
else:
    print("  WEAK/MIXED: Information flow is asset-dependent")

# ============================================================
# 9. Save
# ============================================================
output = {
    "experiment": "K128",
    "title": "Transfer Entropy: VIX Information Flow to Asset Volatility",
    "proposed_by": "Gemini G1",
    "executed_by": "Claude",
    "timestamp": datetime.now().isoformat(),
    "methodology": {
        "estimator": "Frenzel-Pompe (2007) direct kNN CMI",
        "k": K_NN, "embedding_dim": EMBED_DIM,
        "n_surrogates": N_SURROGATES, "subsample": SUBSAMPLE,
        "rv_window": 22, "rolling_window": WINDOW, "rolling_step": STEP,
        "data_period": f"{start_date} to {end_date}",
    },
    "main_results": results,
    "lag_structure": {k: {str(l): v for l, v in lags.items()} for k, lags in lag_results.items()},
    "rolling_summary": {
        name: {
            "pct_vix_dominant": float(np.mean(np.array(d["net_te"]) > 0) * 100),
            "mean_net_te": float(np.mean(d["net_te"])),
            "std_net_te": float(np.std(d["net_te"])),
            "n_windows": len(d["dates"]),
        } for name, d in rolling_results.items()
    },
    "linear_comparison": linear_results,
    "conclusions": {
        "vix_net_sender_all_5": apn,
        "significant_count": f"{sig_n}/5",
        "equity_te_mean": float(eq),
        "non_equity_te_mean": float(ne),
    }
}

out_path = "/Users/yhlai0911/Desktop/volpred-research/.claude/worktrees/agent-a961c101/experiments/transfer_entropy_results.json"
with open(out_path, "w") as f:
    json.dump(output, f, indent=2, default=str)

print(f"\nSaved: {out_path}")
print("K128 complete.")
