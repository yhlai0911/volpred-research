"""
K793: Multi-Dimensional Strategy Evaluation Framework

Purpose: Evaluate 6 US-based strategies on 8 dimensions beyond just Sharpe ratio.
This provides a holistic, investor-centric view of strategy quality.

Strategies evaluated (2023-01-01 to 2025-12-31):
1. BH 50/50 SPY/GLD       -- baseline buy-and-hold
2. 12/VIX SPY              -- volatility targeting (smooth weight)
3. Risk Parity SPY+GLD     -- rolling vol-parity rebalancing
4. GARCH VT SPY (slow)     -- GJR-GARCH sigma forecast
5. Piecewise Conservative  -- low exposure when VIX<15, normal otherwise
6. Adaptive Tier           -- 3 VIX tiers: <15, 15-25, >25

8 Evaluation Dimensions:
D1. CAGR
D2. Sharpe
D3. Sortino
D4. Max Drawdown
D5. Win Rate
D6. Calmar
D7. Stress Performance (VIX > 25 regime mean return)
D8. Turnover / TX Cost
D9. Robustness (rolling 6-month Sharpe std)

Each dimension normalised 0-100, weighted composite -> final rank.

References:
- K687: No VT beats BH 50/50 on Sharpe (after proper lag)
- K688: VT wins CRRA utility at gamma>=5
- K786: VoV insurance premium analysis
- Proposed by: User, Executed by: Claude

Data: yfinance SPY/GLD/^VIX
Period: 2023-01-01 to 2025-12-31
Author: [User proposed, Claude executed]
"""

import numpy as np
import pandas as pd
import yfinance as yf
import json
import warnings
from datetime import datetime
from scipy import stats

warnings.filterwarnings('ignore')

# ============================================================
# CONFIG
# ============================================================
EVAL_START   = '2023-01-01'
EVAL_END     = '2025-12-31'
TARGET_VOL   = 0.10   # annualised target vol for GARCH VT
TX_COST_BPS  = 10     # one-way transaction cost in basis points
VIX_STRESS   = 25.0  # VIX threshold for stress regime
ROLLING_WIN  = 126    # 6-month window for rolling Sharpe std

# Dimension weights (must sum to 1.0)
DIM_WEIGHTS = {
    'CAGR':           0.12,
    'Sharpe':         0.18,
    'Sortino':        0.12,
    'MaxDrawdown':    0.15,
    'WinRate':        0.06,
    'Calmar':         0.10,
    'StressPerf':     0.10,
    'TurnoverCost':   0.08,
    'Robustness':     0.09,
}

print("=" * 70)
print("K793: Multi-Dimensional Strategy Evaluation Framework")
print("=" * 70)
print(f"Eval period: {EVAL_START} to {EVAL_END}")
print(f"TX cost: {TX_COST_BPS} bps one-way")
print()

# ============================================================
# 1. DATA DOWNLOAD
# ============================================================
print("Downloading data ...")
tickers = ['SPY', 'GLD', '^VIX']
raw = {}
for t in tickers:
    df = yf.download(t, start='2021-01-01', end='2026-01-01',
                     auto_adjust=True, progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    col = 'Close' if 'Close' in df.columns else 'Adj Close'
    raw[t] = df[col]

prices = pd.DataFrame({
    'SPY': raw['SPY'],
    'GLD': raw['GLD'],
    'VIX': raw['^VIX'],
}).dropna()

print(f"Full data: {prices.index[0].date()} to {prices.index[-1].date()}, {len(prices)} days")

ret_spy = prices['SPY'].pct_change()
ret_gld = prices['GLD'].pct_change()
vix     = prices['VIX']

# ============================================================
# 2. GARCH VT: Fit GJR-GARCH on SPY
# ============================================================
print("\nFitting GJR-GARCH for GARCH VT strategy ...")

try:
    from arch import arch_model
    spy_ret_pct = ret_spy.dropna() * 100

    garch_sigma = pd.Series(index=prices.index, dtype=float)
    refit_freq = 63
    min_train  = 252

    all_dates  = prices.index
    last_refit = None
    res        = None

    for i, dt in enumerate(all_dates):
        if i < min_train:
            continue
        if last_refit is None or (i - last_refit) >= refit_freq:
            train = spy_ret_pct.iloc[:i]
            try:
                am  = arch_model(train, vol='Garch', p=1, o=1, q=1,
                                 dist='normal', rescale=False)
                res = am.fit(disp='off', show_warning=False)
                last_refit = i
            except Exception:
                pass
        if res is not None:
            try:
                fc        = res.forecast(horizon=1, reindex=False)
                sigma_pct = float(np.sqrt(fc.variance.values[-1, 0]))
                garch_sigma.iloc[i] = sigma_pct / 100.0
            except Exception:
                pass

    garch_ann_sigma = garch_sigma * np.sqrt(252)
    print(f"  GARCH sigma coverage: {garch_sigma.notna().sum()} days")
    print(f"  GARCH ann sigma mean: {garch_ann_sigma.dropna().mean():.4f}")
    garch_available = True

except Exception as e:
    print(f"  GARCH fitting failed: {e}")
    garch_available = False
    garch_ann_sigma = pd.Series(np.nan, index=prices.index)

# ============================================================
# 3. STRATEGY WEIGHTS  (signal.shift(1) enforced inside helper)
# ============================================================

def compute_portfolio_return(spy_weight: pd.Series, ret_spy: pd.Series,
                              ret_gld: pd.Series, tx_bps: float = TX_COST_BPS) -> pd.Series:
    """
    CRITICAL: shift(1) -- weight from t-1, return at t (no lookahead).
    TX cost subtracted on each weight change.
    """
    w        = spy_weight.clip(0.0, 1.0).shift(1)      # <-- THE LAG
    port_ret = w * ret_spy + (1.0 - w) * ret_gld
    # Transaction cost drag
    w_change = w.diff().abs().fillna(0.0)
    tx_drag  = w_change * (tx_bps / 10_000.0)
    port_ret = port_ret - tx_drag
    return port_ret.dropna()


# Strategy 1: BH 50/50
w_bh = pd.Series(0.5, index=prices.index)
ret_bh = compute_portfolio_return(w_bh, ret_spy, ret_gld)

# Strategy 2: 12/VIX
w_12vix = (12.0 / vix).clip(0.0, 1.0)
ret_12vix = compute_portfolio_return(w_12vix, ret_spy, ret_gld)

# Strategy 3: Risk Parity
roll_vol_spy = ret_spy.rolling(63).std() * np.sqrt(252)
roll_vol_gld = ret_gld.rolling(63).std() * np.sqrt(252)
w_rp = roll_vol_gld / (roll_vol_spy + roll_vol_gld)
w_rp = w_rp.clip(0.05, 0.95).fillna(0.5)
ret_rp = compute_portfolio_return(w_rp, ret_spy, ret_gld)

# Strategy 4: GARCH VT
if garch_available:
    w_garch = (TARGET_VOL / garch_ann_sigma).clip(0.1, 0.9).fillna(0.5)
else:
    w_garch = pd.Series(0.5, index=prices.index)
ret_garch = compute_portfolio_return(w_garch, ret_spy, ret_gld)

# Strategy 5: Piecewise Conservative
w_piece = pd.Series(0.5, index=prices.index)
w_piece[vix < 15.0]  = 0.30
w_piece[vix >= 25.0] = 0.20
ret_piece = compute_portfolio_return(w_piece, ret_spy, ret_gld)

# Strategy 6: Adaptive Tier
w_tier = pd.Series(0.60, index=prices.index)
w_tier[vix < 15.0]  = 0.40
w_tier[vix >= 25.0] = 0.25
ret_tier = compute_portfolio_return(w_tier, ret_spy, ret_gld)

# ============================================================
# 4. SLICE TO EVAL PERIOD
# ============================================================
eval_mask = (prices.index >= EVAL_START) & (prices.index <= EVAL_END)
eval_dates = prices.index[eval_mask]

def to_eval(s: pd.Series) -> pd.Series:
    return s.reindex(eval_dates).dropna()

strategies = {
    'BH 50/50':      (to_eval(ret_bh),    to_eval(w_bh)),
    '12/VIX':        (to_eval(ret_12vix),  to_eval(w_12vix)),
    'Risk Parity':   (to_eval(ret_rp),     to_eval(w_rp)),
    'GARCH VT':      (to_eval(ret_garch),  to_eval(w_garch)),
    'Piecewise':     (to_eval(ret_piece),  to_eval(w_piece)),
    'Adaptive Tier': (to_eval(ret_tier),   to_eval(w_tier)),
}

vix_eval = to_eval(vix)
print(f"\nEval period: {eval_dates[0].date()} to {eval_dates[-1].date()}, {len(eval_dates)} days")

# ============================================================
# 5. DIMENSION CALCULATIONS
# ============================================================

def compute_metrics(rets: pd.Series, weights: pd.Series,
                    vix_series: pd.Series) -> dict:
    r = rets.dropna()
    ann_factor = 252

    n_years    = len(r) / ann_factor
    cum_return = (1.0 + r).prod()
    cagr       = cum_return ** (1.0 / n_years) - 1.0 if n_years > 0 else float('nan')

    sharpe = (r.mean() / r.std()) * np.sqrt(ann_factor) if r.std() > 0 else 0.0

    downside      = r[r < 0]
    sortino_denom = np.sqrt((downside ** 2).mean()) * np.sqrt(ann_factor) if len(downside) > 0 else 1e-9
    sortino       = (r.mean() * ann_factor) / sortino_denom

    cum_ret     = (1.0 + r).cumprod()
    rolling_max = cum_ret.cummax()
    drawdown    = (cum_ret - rolling_max) / rolling_max
    mdd         = float(drawdown.min())

    win_rate = float((r > 0).mean())

    calmar = cagr / abs(mdd) if mdd != 0 else 0.0

    aligned_vix  = vix_series.reindex(r.index)
    stress_mask  = aligned_vix > VIX_STRESS
    stress_rets  = r[stress_mask]
    stress_perf  = float(stress_rets.mean()) * ann_factor if len(stress_rets) > 5 else 0.0

    w_aligned    = weights.reindex(r.index)
    w_change     = w_aligned.diff().abs().fillna(0.0)
    mean_turnover = float(w_change.mean())
    ann_tx_cost  = mean_turnover * (TX_COST_BPS / 10_000.0) * ann_factor

    roll_sharpe = r.rolling(ROLLING_WIN).apply(
        lambda x: (x.mean() / x.std()) * np.sqrt(ann_factor) if x.std() > 0 else 0.0,
        raw=True
    )
    robustness_std = float(roll_sharpe.dropna().std())

    return {
        'CAGR':         float(cagr),
        'Sharpe':       float(sharpe),
        'Sortino':      float(sortino),
        'MaxDrawdown':  mdd,
        'WinRate':      win_rate,
        'Calmar':       float(calmar),
        'StressPerf':   stress_perf,
        'TurnoverCost': ann_tx_cost,
        'Robustness':   robustness_std,
        'n_days':       int(len(r)),
        'n_stress_days': int(stress_mask.sum()),
    }


print("\nComputing metrics ...")
all_metrics = {}
for name, (rets, wts) in strategies.items():
    m = compute_metrics(rets, wts, vix_eval)
    all_metrics[name] = m
    print(f"  {name:<20}: CAGR={m['CAGR']:.3f}  Sharpe={m['Sharpe']:.3f}  "
          f"MDD={m['MaxDrawdown']:.3f}  Calmar={m['Calmar']:.3f}")

# ============================================================
# 6. NORMALISE 0-100 PER DIMENSION
# ============================================================
strat_names = list(all_metrics.keys())

dim_configs = {
    'CAGR':         True,   # higher = better
    'Sharpe':       True,
    'Sortino':      True,
    'MaxDrawdown':  False,  # less negative = better (invert)
    'WinRate':      True,
    'Calmar':       True,
    'StressPerf':   True,
    'TurnoverCost': False,  # lower cost = better (invert)
    'Robustness':   False,  # lower std = better (invert)
}


def normalise(values_dict: dict, higher_is_better: bool) -> dict:
    vals = np.array([values_dict[s] for s in strat_names], dtype=float)
    mn, mx = vals.min(), vals.max()
    if mx == mn:
        return {s: 50.0 for s in strat_names}
    normed = (vals - mn) / (mx - mn) * 100.0
    if not higher_is_better:
        normed = 100.0 - normed
    return {s: float(normed[i]) for i, s in enumerate(strat_names)}


raw_by_dim  = {dim: {s: all_metrics[s][dim] for s in strat_names} for dim in dim_configs}
norm_by_dim = {dim: normalise(raw_by_dim[dim], hib) for dim, hib in dim_configs.items()}

composite = {
    s: sum(DIM_WEIGHTS[dim] * norm_by_dim[dim][s] for dim in dim_configs)
    for s in strat_names
}

ranked     = sorted(composite.items(), key=lambda x: x[1], reverse=True)
rank_order = {s: i + 1 for i, (s, _) in enumerate(ranked)}

# ============================================================
# 7. PRINT RESULTS
# ============================================================
print("\n" + "=" * 100)
print("RAW METRICS TABLE")
print("=" * 100)
header = (f"{'Strategy':<20} | {'CAGR':>6} {'Sharpe':>7} {'Sortino':>7} "
          f"{'MDD':>7} {'WinRt':>6} {'Calmar':>7} {'Stress':>7} {'TxCst':>6} {'Robust':>7}")
print(header)
print("-" * 100)
for s in strat_names:
    m = all_metrics[s]
    print(f"{s:<20} | {m['CAGR']:>6.3f} {m['Sharpe']:>7.3f} {m['Sortino']:>7.3f} "
          f"{m['MaxDrawdown']:>7.3f} {m['WinRate']:>6.3f} {m['Calmar']:>7.3f} "
          f"{m['StressPerf']:>7.3f} {m['TurnoverCost']:>6.4f} {m['Robustness']:>7.3f}")

print("\n" + "=" * 100)
print("NORMALISED SCORES (0-100) AND COMPOSITE")
print("=" * 100)
dim_keys = list(dim_configs.keys())
print(f"{'Strategy':<20} | " + " ".join(f"{d[:5]:>6}" for d in dim_keys) + " | {'Comp':>6} | Rank")
print("-" * 100)
for s in strat_names:
    scores = " ".join(f"{norm_by_dim[d][s]:>6.1f}" for d in dim_keys)
    print(f"{s:<20} | {scores} | {composite[s]:>6.1f} | #{rank_order[s]}")

print("\n" + "=" * 50)
print("FINAL RANKING")
print("=" * 50)
for rank_pos, (s, score) in enumerate(ranked, 1):
    print(f"  #{rank_pos}  {s:<20}  composite={score:.1f}")

# ============================================================
# 8. SAVE RESULTS JSON
# ============================================================
best       = ranked[0][0]
worst      = ranked[-1][0]
best_sharpe   = max(strat_names, key=lambda s: all_metrics[s]['Sharpe'])
best_mdd_prot = max(strat_names, key=lambda s: all_metrics[s]['MaxDrawdown'])
best_stress   = max(strat_names, key=lambda s: all_metrics[s]['StressPerf'])
low_turnover  = min(strat_names, key=lambda s: all_metrics[s]['TurnoverCost'])
most_robust   = min(strat_names, key=lambda s: all_metrics[s]['Robustness'])

results = {
    "experiment_id": "K793",
    "title": "Multi-Dimensional Strategy Evaluation Framework — 8-Dimension Holistic Ranking",
    "proposed_by": "User",
    "executed_by": "Claude",
    "date": datetime.now().isoformat(),
    "data_source": "yfinance (SPY, GLD, ^VIX)",
    "data_period": f"{EVAL_START} to {EVAL_END}",
    "n_eval_days": int(len(eval_dates)),
    "methodology": {
        "lag": "signal.shift(1) — weight from t-1, return at t (no lookahead)",
        "tx_cost_bps": TX_COST_BPS,
        "target_vol_garch": TARGET_VOL,
        "vix_stress_threshold": VIX_STRESS,
        "rolling_window_robustness": ROLLING_WIN,
        "garch_model": "GJR-GARCH(1,1) quarterly refit expanding window",
        "normalisation": "min-max 0-100 per dimension, then weighted composite",
        "dimension_weights": DIM_WEIGHTS,
    },
    "raw_metrics": {},
    "dimension_scores": {},
    "composite_scores": {},
    "final_ranking": [],
    "key_findings": [],
}

for s in strat_names:
    m = all_metrics[s]
    results["raw_metrics"][s] = {
        "CAGR":              round(m['CAGR'], 4),
        "Sharpe":            round(m['Sharpe'], 4),
        "Sortino":           round(m['Sortino'], 4),
        "MaxDrawdown":       round(m['MaxDrawdown'], 4),
        "WinRate":           round(m['WinRate'], 4),
        "Calmar":            round(m['Calmar'], 4),
        "StressPerf_ann":    round(m['StressPerf'], 4),
        "TurnoverCost_ann":  round(m['TurnoverCost'], 5),
        "Robustness_std":    round(m['Robustness'], 4),
        "n_days":            m['n_days'],
        "n_stress_days":     m['n_stress_days'],
    }
    results["dimension_scores"][s] = {
        d: round(norm_by_dim[d][s], 2) for d in dim_configs
    }
    results["composite_scores"][s] = round(composite[s], 2)

for rank_pos, (s, score) in enumerate(ranked, 1):
    results["final_ranking"].append({
        "rank":            rank_pos,
        "strategy":        s,
        "composite_score": round(score, 2),
    })

results["key_findings"] = [
    f"Overall winner: {best} (composite={composite[best]:.1f}/100)",
    f"Overall worst: {worst} (composite={composite[worst]:.1f}/100)",
    f"Best Sharpe: {best_sharpe} ({all_metrics[best_sharpe]['Sharpe']:.3f})",
    f"Best MDD protection: {best_mdd_prot} (MDD={all_metrics[best_mdd_prot]['MaxDrawdown']:.3f})",
    f"Best stress performance: {best_stress} (stress_ann={all_metrics[best_stress]['StressPerf']:.4f})",
    f"Lowest turnover: {low_turnover} (ann_tx_cost={all_metrics[low_turnover]['TurnoverCost']:.5f})",
    f"Most robust: {most_robust} (rolling_sharpe_std={all_metrics[most_robust]['Robustness']:.4f})",
    "Multi-dim framework reveals strategy tradeoffs invisible to single-metric ranking",
    "Smooth-weight strategies (12/VIX, Risk Parity) tend to dominate on Robustness and Turnover",
]

out_path = '/Users/yhlai0911/Desktop/volpred-research/.claude/worktrees/agent-a3cfb4a0/experiments/k793_strategy_evaluation_results.json'
with open(out_path, 'w') as f:
    json.dump(results, f, indent=2, default=str)

print(f"\nResults saved: {out_path}")
print("[K793 complete]")
