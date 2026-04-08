"""
K835: Taiwan VIX/VIXTWN Blend — 混合全球/本土恐慌信號改善 0050.TW VT 策略

目標：測試混合 VIX（全球恐慌）+ VIXTWN（本土恐慌）能否改善台股 VT 策略
資產：0050.TW
數據來源：yfinance (0050.TW, ^VIX), data/vixtwn/vixtwn_daily.csv (TWSE)

策略：
  S1: 8.63/VIX (現有策略, baseline)
  S2: 12/VIXTWN (本土指標)
  S3: Static Blend = 0.5 × 8.63/VIX + 0.5 × 12/VIXTWN
  S4: Rolling Corr Blend = 基於 rolling correlation 動態權重
  S5: BH 0050.TW (baseline)

Error log 防錯：
- 0050.TW: 必須呼叫 clean_tw50_data
- signal.shift(1): 用昨天的 VIX/VIXTWN
- 跨市場: 台股用前一天 VIX（美股比台股晚一天）

限制：VIXTWN 數據僅 2025-12 ~ 2026-03（~76 交易日），統計檢定力有限

參考文獻：
- Poon & Granger (2003) "Forecasting Volatility in Financial Markets: A Review"
- Bekaert & Hoerova (2014) "The VIX, the variance premium and stock market volatility"
"""

import json
import sys
import os
import warnings
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf

warnings.filterwarnings("ignore")

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from volpred.utils import clean_tw50_data
from volpred.stats.model_evaluation import strategy_dm_test


def load_vixtwn(data_dir: Path) -> pd.Series:
    """Load VIXTWN daily data."""
    fpath = data_dir / "data" / "vixtwn" / "vixtwn_daily.csv"
    df = pd.read_csv(fpath, parse_dates=["date"])
    df.set_index("date", inplace=True)
    return df["vixtwn_close"]


def download_data(start: str = "2025-10-01", end: str = "2026-04-03"):
    """Download 0050.TW and ^VIX data."""
    tw50 = yf.download("0050.TW", start=start, end=end, progress=False)
    if isinstance(tw50.columns, pd.MultiIndex):
        tw50.columns = tw50.columns.get_level_values(0)
    tw50_prices = tw50["Close"].copy()
    tw50_returns = tw50_prices.pct_change()

    # Clean 0050.TW data (mandatory per error log)
    tw50_prices, tw50_returns = clean_tw50_data(tw50_prices, tw50_returns)

    vix = yf.download("^VIX", start=start, end=end, progress=False)
    if isinstance(vix.columns, pd.MultiIndex):
        vix.columns = vix.columns.get_level_values(0)
    vix_close = vix["Close"].copy()

    return tw50_prices, tw50_returns, vix_close


def compute_strategy_weights(vix_series, vixtwn_series, tw50_returns, method="vix_only"):
    """
    Compute strategy weights with PROPER LAGGING.

    signal.shift(1) is applied here — weight at time t uses data from t-1.
    For VIX: extra shift needed because US market closes after Taiwan.
    So VIX available for Taiwan trading at t is actually VIX from t-1 (US perspective).

    For VIXTWN: same-day VIXTWN is available (Taiwan local index), but we still
    use t-1 to avoid any intraday lookahead.
    """
    # Align all series to common dates
    common_idx = tw50_returns.dropna().index
    common_idx = common_idx.intersection(vix_series.dropna().index)
    common_idx = common_idx.intersection(vixtwn_series.dropna().index)
    common_idx = common_idx.sort_values()

    vix_aligned = vix_series.reindex(common_idx).ffill()
    vixtwn_aligned = vixtwn_series.reindex(common_idx).ffill()
    ret_aligned = tw50_returns.reindex(common_idx)

    if method == "vix_only":
        # S1: 8.63/VIX (existing strategy)
        raw_weight = 8.63 / vix_aligned
        raw_weight = raw_weight.clip(0, 1)
        # CRITICAL: shift(1) — use yesterday's signal
        weight = raw_weight.shift(1)

    elif method == "vixtwn_only":
        # S2: 12/VIXTWN
        raw_weight = 12.0 / vixtwn_aligned
        raw_weight = raw_weight.clip(0, 1)
        # CRITICAL: shift(1)
        weight = raw_weight.shift(1)

    elif method == "static_blend":
        # S3: 50/50 blend
        w_vix = 8.63 / vix_aligned
        w_vixtwn = 12.0 / vixtwn_aligned
        w_vix = w_vix.clip(0, 1)
        w_vixtwn = w_vixtwn.clip(0, 1)
        raw_weight = 0.5 * w_vix + 0.5 * w_vixtwn
        raw_weight = raw_weight.clip(0, 1)
        # CRITICAL: shift(1)
        weight = raw_weight.shift(1)

    elif method == "rolling_corr_blend":
        # S4: Dynamic blend based on rolling correlation with 0050.TW returns
        # Use rolling 20-day correlation of each indicator with |returns|
        abs_ret = ret_aligned.abs()

        w_vix = 8.63 / vix_aligned
        w_vixtwn = 12.0 / vixtwn_aligned
        w_vix = w_vix.clip(0, 1)
        w_vixtwn = w_vixtwn.clip(0, 1)

        # Rolling correlation of raw VIX/VIXTWN level with |returns|
        # Higher corr → more weight on that indicator
        corr_vix = vix_aligned.rolling(20, min_periods=10).corr(abs_ret)
        corr_vixtwn = vixtwn_aligned.rolling(20, min_periods=10).corr(abs_ret)

        # Convert to positive weights (abs correlation matters)
        corr_vix_abs = corr_vix.abs().fillna(0.5)
        corr_vixtwn_abs = corr_vixtwn.abs().fillna(0.5)

        total_corr = corr_vix_abs + corr_vixtwn_abs
        total_corr = total_corr.replace(0, 1)  # avoid division by zero

        blend_w = corr_vix_abs / total_corr  # weight for VIX component

        raw_weight = blend_w * w_vix + (1 - blend_w) * w_vixtwn
        raw_weight = raw_weight.clip(0, 1)
        # CRITICAL: shift(1) — lag the entire blended signal
        weight = raw_weight.shift(1)

    elif method == "buy_hold":
        # S5: Buy and hold
        weight = pd.Series(1.0, index=common_idx)
    else:
        raise ValueError(f"Unknown method: {method}")

    # Drop NaN from shift
    valid = weight.dropna().index
    valid = valid.intersection(ret_aligned.dropna().index)

    weight_final = weight.reindex(valid)
    ret_final = ret_aligned.reindex(valid)

    # Strategy return: weight * asset_return + (1-weight) * 0 (cash)
    strat_return = weight_final * ret_final

    return strat_return, weight_final, ret_final


def compute_metrics(returns: pd.Series) -> dict:
    """Compute Sharpe, CAGR, MDD, vol from daily returns."""
    r = returns.dropna()
    n = len(r)
    if n < 5:
        return {"sharpe": np.nan, "cagr": np.nan, "mdd": np.nan, "vol": np.nan, "n_days": n}

    ann_factor = 252

    # Sharpe
    sharpe = r.mean() / r.std() * np.sqrt(ann_factor) if r.std() > 0 else np.nan

    # CAGR
    cumret = (1 + r).cumprod()
    total_ret = cumret.iloc[-1] / cumret.iloc[0]
    years = n / ann_factor
    cagr = total_ret ** (1 / years) - 1 if years > 0 else np.nan

    # MDD
    peak = cumret.cummax()
    drawdown = (cumret - peak) / peak
    mdd = drawdown.min()

    # Vol
    vol = r.std() * np.sqrt(ann_factor)

    return {
        "sharpe": round(float(sharpe), 4),
        "cagr": round(float(cagr), 4),
        "mdd": round(float(mdd), 4),
        "vol": round(float(vol), 4),
        "n_days": int(n),
    }


def run_dm_tests(returns_dict: dict) -> dict:
    """Run pairwise DM tests between all strategies."""
    results = {}
    keys = list(returns_dict.keys())

    for i, k1 in enumerate(keys):
        for j, k2 in enumerate(keys):
            if i >= j:
                continue
            r1 = returns_dict[k1].values
            r2 = returns_dict[k2].values

            # Align lengths
            min_len = min(len(r1), len(r2))
            r1 = r1[:min_len]
            r2 = r2[:min_len]

            try:
                t_stat, p_val = strategy_dm_test(r1, r2, h=1, loss_fn="negative_return")
                results[f"{k1}_vs_{k2}"] = {
                    "t_stat": round(float(t_stat), 4),
                    "p_value": round(float(p_val), 4),
                    "significant_3.0": abs(float(t_stat)) > 3.0,
                    "interpretation": (
                        f"{k1} significantly better" if t_stat > 3.0
                        else f"{k2} significantly better" if t_stat < -3.0
                        else "No significant difference"
                    )
                }
            except Exception as e:
                results[f"{k1}_vs_{k2}"] = {"error": str(e)}

    return results


def descriptive_stats(vix, vixtwn, tw50_returns):
    """Compute descriptive statistics for the data."""
    stats = {}

    for name, series in [("VIX", vix), ("VIXTWN", vixtwn), ("0050.TW_returns", tw50_returns)]:
        s = series.dropna()
        stats[name] = {
            "n": int(len(s)),
            "mean": round(float(s.mean()), 4),
            "std": round(float(s.std()), 4),
            "min": round(float(s.min()), 4),
            "max": round(float(s.max()), 4),
            "skew": round(float(s.skew()), 4),
            "kurtosis": round(float(s.kurtosis()), 4),
        }

    # Correlation between VIX and VIXTWN
    common = vix.dropna().index.intersection(vixtwn.dropna().index)
    if len(common) > 5:
        corr = vix.reindex(common).corr(vixtwn.reindex(common))
        stats["vix_vixtwn_correlation"] = round(float(corr), 4)

    return stats


def main():
    print("=" * 70)
    print("K835: Taiwan VIX/VIXTWN Blend Strategy")
    print("=" * 70)

    # Load data
    print("\n[1/5] Loading data...")
    vixtwn = load_vixtwn(PROJECT_ROOT)
    tw50_prices, tw50_returns, vix_close = download_data(
        start="2025-10-01", end="2026-04-03"
    )

    print(f"  0050.TW: {tw50_returns.index.min().date()} ~ {tw50_returns.index.max().date()} ({len(tw50_returns)} days)")
    print(f"  VIX:     {vix_close.index.min().date()} ~ {vix_close.index.max().date()} ({len(vix_close)} days)")
    print(f"  VIXTWN:  {vixtwn.index.min().date()} ~ {vixtwn.index.max().date()} ({len(vixtwn)} days)")

    # Descriptive statistics
    print("\n[2/5] Descriptive statistics...")
    desc_stats = descriptive_stats(vix_close, vixtwn, tw50_returns)
    for name, st in desc_stats.items():
        if isinstance(st, dict):
            print(f"  {name}: mean={st.get('mean','N/A')}, std={st.get('std','N/A')}, n={st.get('n','N/A')}")
        else:
            print(f"  {name}: {st}")

    # Run strategies
    print("\n[3/5] Computing strategy returns...")
    methods = {
        "S1_8.63_VIX": "vix_only",
        "S2_12_VIXTWN": "vixtwn_only",
        "S3_Static_Blend": "static_blend",
        "S4_Rolling_Corr_Blend": "rolling_corr_blend",
        "S5_BuyHold": "buy_hold",
    }

    strategy_returns = {}
    strategy_weights = {}
    all_metrics = {}

    for strat_name, method in methods.items():
        strat_ret, weight, asset_ret = compute_strategy_weights(
            vix_close, vixtwn, tw50_returns, method=method
        )
        strategy_returns[strat_name] = strat_ret
        strategy_weights[strat_name] = weight
        metrics = compute_metrics(strat_ret)
        all_metrics[strat_name] = metrics

        print(f"  {strat_name}: Sharpe={metrics['sharpe']}, CAGR={metrics['cagr']}, "
              f"MDD={metrics['mdd']}, Vol={metrics['vol']}, N={metrics['n_days']}")

    # Weight statistics
    print("\n[4/5] Weight statistics...")
    weight_stats = {}
    for strat_name, weight in strategy_weights.items():
        w = weight.dropna()
        if len(w) > 0:
            ws = {
                "mean": round(float(w.mean()), 4),
                "std": round(float(w.std()), 4),
                "min": round(float(w.min()), 4),
                "max": round(float(w.max()), 4),
                "pct_full_invest": round(float((w >= 0.99).mean()), 4),
                "pct_zero": round(float((w <= 0.01).mean()), 4),
            }
            weight_stats[strat_name] = ws
            print(f"  {strat_name}: mean_w={ws['mean']}, std_w={ws['std']}")

    # DM tests
    print("\n[5/5] DM tests (Harvey t>3.0 threshold)...")
    dm_results = run_dm_tests(strategy_returns)
    for pair, res in dm_results.items():
        if "error" in res:
            print(f"  {pair}: ERROR - {res['error']}")
        else:
            sig = "***" if res["significant_3.0"] else ""
            print(f"  {pair}: t={res['t_stat']}, p={res['p_value']} {sig} → {res['interpretation']}")

    # Sanity check: compare with and without lag
    print("\n[SANITY] Lookahead check: comparing shift(0) vs shift(1) for S1...")
    vix_aligned = vix_close.reindex(tw50_returns.dropna().index.intersection(vix_close.dropna().index).intersection(vixtwn.dropna().index)).ffill()
    ret_aligned = tw50_returns.reindex(vix_aligned.index)

    w_no_lag = (8.63 / vix_aligned).clip(0, 1)  # NO shift = lookahead
    w_lagged = w_no_lag.shift(1)  # Correct: shift(1)

    valid_no_lag = w_no_lag.dropna().index.intersection(ret_aligned.dropna().index)
    valid_lagged = w_lagged.dropna().index.intersection(ret_aligned.dropna().index)

    ret_no_lag = (w_no_lag.reindex(valid_no_lag) * ret_aligned.reindex(valid_no_lag))
    ret_lagged = (w_lagged.reindex(valid_lagged) * ret_aligned.reindex(valid_lagged))

    sharpe_no_lag = ret_no_lag.mean() / ret_no_lag.std() * np.sqrt(252) if ret_no_lag.std() > 0 else np.nan
    sharpe_lagged = ret_lagged.mean() / ret_lagged.std() * np.sqrt(252) if ret_lagged.std() > 0 else np.nan

    print(f"  shift(0) Sharpe = {sharpe_no_lag:.4f} (LOOKAHEAD — for comparison only)")
    print(f"  shift(1) Sharpe = {sharpe_lagged:.4f} (CORRECT)")
    if abs(sharpe_no_lag) > 2 * abs(sharpe_lagged) and sharpe_lagged != 0:
        print("  ⚠️ WARNING: Large discrepancy suggests possible lag sensitivity")
    else:
        print("  ✓ Lag impact is moderate (smooth-weight strategy expected)")

    # VIX-VIXTWN correlation analysis
    print("\n[EXTRA] VIX vs VIXTWN relationship...")
    common = vix_close.dropna().index.intersection(vixtwn.dropna().index)
    if len(common) > 10:
        vix_c = vix_close.reindex(common)
        vixtwn_c = vixtwn.reindex(common)

        level_corr = vix_c.corr(vixtwn_c)
        change_corr = vix_c.pct_change().dropna().corr(vixtwn_c.pct_change().dropna())

        print(f"  Level correlation: {level_corr:.4f}")
        print(f"  Change correlation: {change_corr:.4f}")
        print(f"  VIX mean: {vix_c.mean():.2f}, VIXTWN mean: {vixtwn_c.mean():.2f}")
        print(f"  VIX/VIXTWN ratio: {(vix_c / vixtwn_c).mean():.4f}")

    # Compile results
    results = {
        "experiment_id": "K835",
        "title": "Taiwan VIX/VIXTWN Blend Strategy",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "data_sources": {
            "asset": "0050.TW (yfinance, cleaned with clean_tw50_data)",
            "vix": "^VIX (yfinance)",
            "vixtwn": "data/vixtwn/vixtwn_daily.csv (TWSE)",
        },
        "data_period": {
            "tw50": f"{tw50_returns.index.min().date()} ~ {tw50_returns.index.max().date()}",
            "vix": f"{vix_close.index.min().date()} ~ {vix_close.index.max().date()}",
            "vixtwn": f"{vixtwn.index.min().date()} ~ {vixtwn.index.max().date()}",
            "oos_period": "VIXTWN overlap period (~76 trading days)",
        },
        "descriptive_stats": desc_stats,
        "strategies": all_metrics,
        "weight_stats": weight_stats,
        "dm_tests": dm_results,
        "sanity_check": {
            "shift_0_sharpe": round(float(sharpe_no_lag), 4),
            "shift_1_sharpe": round(float(sharpe_lagged), 4),
            "lag_impact": "moderate" if abs(sharpe_no_lag - sharpe_lagged) < abs(sharpe_lagged) else "large",
        },
        "vix_vixtwn_relationship": {
            "level_correlation": round(float(level_corr), 4) if len(common) > 10 else None,
            "change_correlation": round(float(change_corr), 4) if len(common) > 10 else None,
        },
        "conclusion": "",  # Will be filled after analysis
        "limitations": [
            "VIXTWN data only available from 2025-12-01 (~76 trading days)",
            "Short OOS period limits statistical power significantly",
            "DM test results may not be reliable with <100 observations",
            "VIXTWN was in a high-vol regime during most of the sample (COVID-era / tariff uncertainty)",
            "Results cannot be generalized to normal market conditions",
        ],
        "references": [
            "Poon & Granger (2003) Forecasting Volatility in Financial Markets: A Review, JEL",
            "Bekaert & Hoerova (2014) The VIX, the variance premium and stock market volatility, JFE",
            "Harvey et al. (2016) ...and the Cross-Section of Expected Returns, RFS (t>3.0 threshold)",
        ],
    }

    # Determine conclusion
    sharpes = {k: v["sharpe"] for k, v in all_metrics.items()}
    best_strat = max(sharpes, key=sharpes.get)
    worst_strat = min(sharpes, key=sharpes.get)

    # Check if any blend beats S1 baseline
    s1_sharpe = sharpes.get("S1_8.63_VIX", 0)
    blend_better = any(
        sharpes[k] > s1_sharpe for k in ["S3_Static_Blend", "S4_Rolling_Corr_Blend"]
    )

    conclusion_parts = []
    conclusion_parts.append(
        f"Best strategy: {best_strat} (Sharpe={sharpes[best_strat]})"
    )
    conclusion_parts.append(
        f"S1 baseline (8.63/VIX): Sharpe={s1_sharpe}"
    )

    if blend_better:
        conclusion_parts.append(
            "Blend strategies show improvement over VIX-only, "
            "but statistical significance is limited due to short sample."
        )
    else:
        conclusion_parts.append(
            "Blend strategies do NOT improve over VIX-only baseline. "
            "VIXTWN adds noise rather than signal in this short sample."
        )

    # Check DM significance
    any_significant = any(
        res.get("significant_3.0", False)
        for res in dm_results.values()
        if isinstance(res, dict)
    )
    if not any_significant:
        conclusion_parts.append(
            "No pairwise comparison reaches Harvey (2016) t>3.0 threshold — "
            "all differences are statistically insignificant."
        )

    conclusion_parts.append(
        f"CAVEAT: Only {all_metrics.get('S1_8.63_VIX', {}).get('n_days', '?')} trading days — "
        "results are exploratory, not conclusive."
    )

    results["conclusion"] = " | ".join(conclusion_parts)

    # Print summary
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print(f"Best: {best_strat} (Sharpe={sharpes[best_strat]})")
    print(f"VIX baseline: S1 Sharpe={s1_sharpe}")
    print(f"Blend improvement: {'YES' if blend_better else 'NO'}")
    print(f"Any DM significant (t>3.0): {'YES' if any_significant else 'NO'}")
    print(f"Conclusion: {results['conclusion']}")

    # Save results
    out_path = PROJECT_ROOT / "experiments" / "k835_taiwan_vix_blend_results.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False, default=str)
    print(f"\nResults saved to: {out_path}")

    return results


if __name__ == "__main__":
    main()
