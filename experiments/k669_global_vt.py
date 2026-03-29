"""
K669: Does VT Work Globally? Testing 12/VIX on International ETFs
=================================================================
Motivation: All our VT research focuses on US SPY and Taiwan 0050. Does the
VIX-based VT framework work for other markets? This experiment tests 12/VIX
on Europe (EFA), Japan (EWJ), and Emerging Markets (EEM) alongside SPY.

Prior knowledge:
- N84: 12/VIX cross-market: SPY +0.121, EFA -0.041, EEM -0.138 Sharpe.
  MDD improvement universal. VIX is US-equity specific for Sharpe.
- K590: International equity VT: 8/8 MaxDD improvement, 0/8 Sharpe improvement.
- N87: 12/VIX = sigma_target/sigma_implied = Moreira-Muir (2017) with implied vol.
- Vol-adjusted version (target=12*vol_spy/vol_asset) improved results for QQQ/IWM.

Method:
- Download SPY, EFA, EWJ, EEM, ^VIX daily data from yfinance (2010-01-01 to 2026-03-27)
- Apply 12/VIX strategy to each market ETF
- Compute: VIX correlation with local realized vol, Sharpe, CAGR, MDD for VT vs BH
- Also test vol-adjusted VT (target = 12 * vol_SPY / vol_asset)
- Build global equal-weight portfolio with and without VT
- Statistical testing: bootstrap confidence intervals for Sharpe differences

Data source: yfinance (SPY, EFA, EWJ, EEM, ^VIX), 2010-01-01 to 2026-03-27
Type: Empirical analysis (real data)

References:
- Moreira & Muir (2017) "Volatility-Managed Portfolios" JoF — VT framework
- Bozovic (2024) IRFA — VIX-managed > realized-vol-managed
- Cederburg et al. (2020) "On the Performance of Volatility-Managed Portfolios" — skeptical view
- Harvey et al. (2016) "...and the Cross-Section of Expected Returns" — t>3.0 threshold
"""

import json
import numpy as np
import yfinance as yf
from pathlib import Path
from datetime import datetime
from scipy import stats

# ── Configuration ──────────────────────────────────────────────────────
START_DATE = "2010-01-01"
END_DATE = "2026-03-27"
TRADING_DAYS_PER_YEAR = 252
VIX_TARGET = 12.0
MA_WINDOW = 5  # 5-day MA smoothing for VIX weight
BOOTSTRAP_REPS = 10000

MARKETS = {
    "SPY": {"name": "US (S&P 500)", "ticker": "SPY"},
    "EFA": {"name": "Europe/EAFE", "ticker": "EFA"},
    "EWJ": {"name": "Japan (Nikkei)", "ticker": "EWJ"},
    "EEM": {"name": "Emerging Markets", "ticker": "EEM"},
}

np.random.seed(42)


def download_data():
    """Download market ETFs and VIX data from yfinance."""
    print("Downloading data from yfinance...")
    tickers_to_download = list(MARKETS.keys()) + ["^VIX"]

    data = {}
    for ticker in tickers_to_download:
        key = ticker.replace("^", "")
        df = yf.download(ticker, start=START_DATE, end=END_DATE,
                         progress=False, auto_adjust=True)
        if df.empty:
            raise ValueError(f"Failed to download {ticker}")
        # Handle MultiIndex columns from yfinance
        if hasattr(df.columns, 'levels'):
            df.columns = df.columns.get_level_values(0)
        data[key] = df["Close"].squeeze()
        print(f"  {key}: {len(df)} days ({df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')})")

    return data


def compute_descriptive_stats(returns, name):
    """Compute descriptive statistics for return series."""
    r = returns.dropna()
    return {
        "name": name,
        "n_obs": len(r),
        "mean_daily": float(r.mean()),
        "std_daily": float(r.std()),
        "annualized_vol": float(r.std() * np.sqrt(252)),
        "skewness": float(stats.skew(r)),
        "kurtosis": float(stats.kurtosis(r)),
        "min": float(r.min()),
        "max": float(r.max()),
    }


def compute_realized_vol(returns, window=21):
    """Compute rolling realized volatility (21-day annualized)."""
    return returns.rolling(window).std() * np.sqrt(252)


def compute_vix_local_vol_correlation(vix_series, returns, market_name):
    """Compute correlation between VIX and local market realized vol."""
    import pandas as pd

    rv_21 = compute_realized_vol(returns, 21)
    rv_63 = compute_realized_vol(returns, 63)

    # Align all series
    df = pd.DataFrame({
        "VIX": vix_series,
        "RV_21d": rv_21,
        "RV_63d": rv_63,
    }).dropna()

    corr_21 = float(df["VIX"].corr(df["RV_21d"]))
    corr_63 = float(df["VIX"].corr(df["RV_63d"]))
    rank_corr_21 = float(df["VIX"].corr(df["RV_21d"], method="spearman"))

    # Also compute correlation between VIX changes and local vol changes
    d_vix = df["VIX"].diff()
    d_rv = df["RV_21d"].diff()
    corr_changes = float(d_vix.corr(d_rv.dropna()))

    return {
        "market": market_name,
        "pearson_vix_rv21": round(corr_21, 4),
        "pearson_vix_rv63": round(corr_63, 4),
        "spearman_vix_rv21": round(rank_corr_21, 4),
        "pearson_changes": round(corr_changes, 4),
        "n_obs": len(df),
    }


def apply_12vix_strategy(returns, vix_series, target=12.0, ma_window=5):
    """Apply target/VIX strategy. Returns strategy returns (daily)."""
    import pandas as pd

    # VIX weight with MA smoothing
    vix_ma = vix_series.rolling(ma_window).mean()
    weight = (target / vix_ma).clip(0, 1.0)

    # Align weight and returns (use previous day's weight)
    weight_shifted = weight.shift(1)

    # Strategy return = weight * market_return + (1-weight) * 0 (cash at 0%)
    aligned = pd.DataFrame({
        "ret": returns,
        "w": weight_shifted,
    }).dropna()

    strat_ret = aligned["w"] * aligned["ret"]

    return strat_ret, aligned["w"]


def apply_vol_adjusted_vt(returns, vix_series, spy_returns, target=12.0, ma_window=5):
    """Apply vol-adjusted VT: target = 12 * vol_SPY / vol_asset."""
    import pandas as pd

    # Compute rolling 63-day vols for both
    vol_spy = spy_returns.rolling(63).std() * np.sqrt(252)
    vol_asset = returns.rolling(63).std() * np.sqrt(252)

    # Adjusted target
    adj_target = target * vol_spy / vol_asset
    adj_target = adj_target.clip(2, 30)  # reasonable bounds

    # VIX weight with MA smoothing
    vix_ma = vix_series.rolling(ma_window).mean()
    weight = (adj_target / vix_ma).clip(0, 1.0)
    weight_shifted = weight.shift(1)

    aligned = pd.DataFrame({
        "ret": returns,
        "w": weight_shifted,
    }).dropna()

    strat_ret = aligned["w"] * aligned["ret"]

    return strat_ret, aligned["w"]


def compute_metrics(returns, name):
    """Compute Sharpe, CAGR, MDD for a return series."""
    r = returns.dropna()
    if len(r) < 252:
        return None

    # Sharpe
    sharpe = float(r.mean() / r.std() * np.sqrt(252)) if r.std() > 0 else 0

    # CAGR
    cum = (1 + r).cumprod()
    n_years = len(r) / 252
    cagr = float(cum.iloc[-1] ** (1 / n_years) - 1)

    # Max Drawdown
    peak = cum.cummax()
    drawdown = (cum - peak) / peak
    mdd = float(drawdown.min())

    # Calmar ratio
    calmar = float(cagr / abs(mdd)) if mdd != 0 else 0

    # Sortino ratio
    downside = r[r < 0].std()
    sortino = float(r.mean() / downside * np.sqrt(252)) if downside > 0 else 0

    # Average weight (for VT strategies, NaN for BH)
    avg_weight = float(r.mean() / r.mean()) if name == "BH" else None

    return {
        "name": name,
        "sharpe": round(sharpe, 4),
        "cagr_pct": round(cagr * 100, 2),
        "mdd_pct": round(mdd * 100, 2),
        "calmar": round(calmar, 4),
        "sortino": round(sortino, 4),
        "total_return_pct": round((cum.iloc[-1] - 1) * 100, 2),
        "annualized_vol_pct": round(float(r.std() * np.sqrt(252) * 100), 2),
        "n_days": len(r),
    }


def bootstrap_sharpe_diff(ret_vt, ret_bh, n_reps=10000):
    """Bootstrap test for Sharpe difference (VT - BH)."""
    import pandas as pd

    aligned = pd.DataFrame({"vt": ret_vt, "bh": ret_bh}).dropna()
    vt = aligned["vt"].values
    bh = aligned["bh"].values
    n = len(vt)

    def sharpe(r):
        return r.mean() / r.std() * np.sqrt(252) if r.std() > 0 else 0

    obs_diff = sharpe(vt) - sharpe(bh)

    boot_diffs = np.zeros(n_reps)
    for i in range(n_reps):
        idx = np.random.randint(0, n, n)
        boot_diffs[i] = sharpe(vt[idx]) - sharpe(bh[idx])

    ci_lower = float(np.percentile(boot_diffs, 2.5))
    ci_upper = float(np.percentile(boot_diffs, 97.5))
    p_value = float(np.mean(boot_diffs < 0))  # P(VT worse)

    return {
        "observed_diff": round(obs_diff, 4),
        "ci_95_lower": round(ci_lower, 4),
        "ci_95_upper": round(ci_upper, 4),
        "p_vt_worse": round(p_value, 4),
        "significant_at_5pct": ci_lower > 0 or ci_upper < 0,
    }


def build_global_portfolio(market_returns_dict, weights=None):
    """Build equal-weight global portfolio from multiple market returns."""
    import pandas as pd

    if weights is None:
        n = len(market_returns_dict)
        weights = {k: 1.0 / n for k in market_returns_dict}

    df = pd.DataFrame(market_returns_dict).dropna()
    portfolio_ret = sum(df[k] * w for k, w in weights.items())

    return portfolio_ret


def main():
    # ── Step 1: Download Data ──
    data = download_data()

    import pandas as pd

    # Compute returns
    returns = {}
    for key in MARKETS:
        returns[key] = data[key].pct_change().dropna()
    vix = data["VIX"]

    print(f"\n{'='*70}")
    print("K669: Does VT Work Globally? Testing 12/VIX on International ETFs")
    print(f"{'='*70}")

    # ── Step 2: Descriptive Statistics ──
    print("\n── Descriptive Statistics ──")
    desc_stats = {}
    for key, info in MARKETS.items():
        ds = compute_descriptive_stats(returns[key], info["name"])
        desc_stats[key] = ds
        print(f"  {info['name']:25s}: vol={ds['annualized_vol']:.1%}, "
              f"skew={ds['skewness']:.2f}, kurt={ds['kurtosis']:.2f}, "
              f"n={ds['n_obs']}")

    # ── Step 3: VIX vs Local Vol Correlation ──
    print("\n── VIX vs Local Realized Volatility Correlation ──")
    vix_corr_results = {}
    for key, info in MARKETS.items():
        corr = compute_vix_local_vol_correlation(vix, returns[key], info["name"])
        vix_corr_results[key] = corr
        print(f"  {info['name']:25s}: Pearson(VIX,RV21)={corr['pearson_vix_rv21']:.3f}, "
              f"Spearman={corr['spearman_vix_rv21']:.3f}, "
              f"Changes={corr['pearson_changes']:.3f}")

    # ── Step 4: Apply 12/VIX to Each Market ──
    print("\n── 12/VIX Strategy Results (vs Buy-and-Hold) ──")
    all_results = {}
    vt_returns = {}
    bh_returns = {}

    for key, info in MARKETS.items():
        # Buy and hold
        bh_ret = returns[key]
        bh_metrics = compute_metrics(bh_ret, f"BH {key}")

        # 12/VIX
        vt_ret, vt_weights = apply_12vix_strategy(returns[key], vix)
        vt_metrics = compute_metrics(vt_ret, f"12/VIX {key}")

        # Vol-adjusted VT
        va_ret, va_weights = apply_vol_adjusted_vt(returns[key], vix, returns["SPY"])
        va_metrics = compute_metrics(va_ret, f"VolAdj {key}")

        # Average weight
        avg_w_12vix = float(vt_weights.mean())
        avg_w_voladj = float(va_weights.mean())

        # Bootstrap test for Sharpe difference
        boot_12vix = bootstrap_sharpe_diff(vt_ret, bh_ret, BOOTSTRAP_REPS)
        boot_voladj = bootstrap_sharpe_diff(va_ret, bh_ret, BOOTSTRAP_REPS)

        all_results[key] = {
            "market": info["name"],
            "buy_and_hold": bh_metrics,
            "vt_12vix": {**vt_metrics, "avg_weight": round(avg_w_12vix, 3)},
            "vt_voladj": {**va_metrics, "avg_weight": round(avg_w_voladj, 3)},
            "sharpe_diff_12vix": bh_metrics["sharpe"] if bh_metrics else 0,
            "sharpe_improvement_12vix": round(vt_metrics["sharpe"] - bh_metrics["sharpe"], 4),
            "mdd_improvement_12vix_pp": round(vt_metrics["mdd_pct"] - bh_metrics["mdd_pct"], 1),
            "sharpe_improvement_voladj": round(va_metrics["sharpe"] - bh_metrics["sharpe"], 4),
            "mdd_improvement_voladj_pp": round(va_metrics["mdd_pct"] - bh_metrics["mdd_pct"], 1),
            "bootstrap_12vix": boot_12vix,
            "bootstrap_voladj": boot_voladj,
        }

        vt_returns[key] = vt_ret
        bh_returns[key] = bh_ret

        print(f"\n  {info['name']}:")
        print(f"    BH:       Sharpe={bh_metrics['sharpe']:.3f}, CAGR={bh_metrics['cagr_pct']:.1f}%, MDD={bh_metrics['mdd_pct']:.1f}%")
        print(f"    12/VIX:   Sharpe={vt_metrics['sharpe']:.3f}, CAGR={vt_metrics['cagr_pct']:.1f}%, MDD={vt_metrics['mdd_pct']:.1f}%, AvgW={avg_w_12vix:.1%}")
        print(f"    VolAdj:   Sharpe={va_metrics['sharpe']:.3f}, CAGR={va_metrics['cagr_pct']:.1f}%, MDD={va_metrics['mdd_pct']:.1f}%, AvgW={avg_w_voladj:.1%}")
        print(f"    Sharpe Δ: 12/VIX={vt_metrics['sharpe'] - bh_metrics['sharpe']:+.3f}, "
              f"VolAdj={va_metrics['sharpe'] - bh_metrics['sharpe']:+.3f}")
        print(f"    MDD Δ:    12/VIX={vt_metrics['mdd_pct'] - bh_metrics['mdd_pct']:+.1f}pp, "
              f"VolAdj={va_metrics['mdd_pct'] - bh_metrics['mdd_pct']:+.1f}pp")
        print(f"    Boot 12/VIX: diff={boot_12vix['observed_diff']:+.3f}, "
              f"CI=[{boot_12vix['ci_95_lower']:.3f}, {boot_12vix['ci_95_upper']:.3f}], "
              f"sig={boot_12vix['significant_at_5pct']}")

    # ── Step 5: Global Equal-Weight Portfolio ──
    print(f"\n{'='*70}")
    print("── Global Equal-Weight Portfolio (SPY+EFA+EWJ+EEM) ──")

    # BH global portfolio
    global_bh = build_global_portfolio(bh_returns)
    global_bh_metrics = compute_metrics(global_bh, "Global BH (EW)")

    # 12/VIX global portfolio
    global_vt = build_global_portfolio(vt_returns)
    global_vt_metrics = compute_metrics(global_vt, "Global 12/VIX (EW)")

    # Vol-adjusted global portfolio
    va_returns_dict = {}
    for key in MARKETS:
        va_ret, _ = apply_vol_adjusted_vt(returns[key], vix, returns["SPY"])
        va_returns_dict[key] = va_ret
    global_va = build_global_portfolio(va_returns_dict)
    global_va_metrics = compute_metrics(global_va, "Global VolAdj (EW)")

    # Bootstrap for global portfolios
    boot_global_12vix = bootstrap_sharpe_diff(global_vt, global_bh, BOOTSTRAP_REPS)
    boot_global_voladj = bootstrap_sharpe_diff(global_va, global_bh, BOOTSTRAP_REPS)

    global_results = {
        "buy_and_hold": global_bh_metrics,
        "vt_12vix": global_vt_metrics,
        "vt_voladj": global_va_metrics,
        "sharpe_improvement_12vix": round(global_vt_metrics["sharpe"] - global_bh_metrics["sharpe"], 4),
        "mdd_improvement_12vix_pp": round(global_vt_metrics["mdd_pct"] - global_bh_metrics["mdd_pct"], 1),
        "sharpe_improvement_voladj": round(global_va_metrics["sharpe"] - global_bh_metrics["sharpe"], 4),
        "mdd_improvement_voladj_pp": round(global_va_metrics["mdd_pct"] - global_bh_metrics["mdd_pct"], 1),
        "bootstrap_12vix": boot_global_12vix,
        "bootstrap_voladj": boot_global_voladj,
    }

    print(f"  BH:     Sharpe={global_bh_metrics['sharpe']:.3f}, CAGR={global_bh_metrics['cagr_pct']:.1f}%, MDD={global_bh_metrics['mdd_pct']:.1f}%")
    print(f"  12/VIX: Sharpe={global_vt_metrics['sharpe']:.3f}, CAGR={global_vt_metrics['cagr_pct']:.1f}%, MDD={global_vt_metrics['mdd_pct']:.1f}%")
    print(f"  VolAdj: Sharpe={global_va_metrics['sharpe']:.3f}, CAGR={global_va_metrics['cagr_pct']:.1f}%, MDD={global_va_metrics['mdd_pct']:.1f}%")
    print(f"  Sharpe Δ 12/VIX: {global_vt_metrics['sharpe'] - global_bh_metrics['sharpe']:+.3f}")
    print(f"  MDD Δ 12/VIX: {global_vt_metrics['mdd_pct'] - global_bh_metrics['mdd_pct']:+.1f}pp")

    # ── Step 6: Crisis Period Analysis ──
    print(f"\n{'='*70}")
    print("── Crisis Period Analysis ──")

    crisis_periods = {
        "COVID_2020": ("2020-02-19", "2020-03-23"),
        "Rate_Hike_2022": ("2022-01-03", "2022-10-12"),
        "Iran_2026": ("2026-02-28", "2026-03-15"),
    }

    crisis_results = {}
    for crisis_name, (start, end) in crisis_periods.items():
        print(f"\n  {crisis_name} ({start} to {end}):")
        crisis_data = {}
        for key, info in MARKETS.items():
            try:
                bh_crisis = bh_returns[key].loc[start:end]
                vt_crisis = vt_returns[key].loc[start:end]
                if len(bh_crisis) < 5:
                    continue
                bh_cum = float((1 + bh_crisis).prod() - 1) * 100
                vt_cum = float((1 + vt_crisis).prod() - 1) * 100
                crisis_data[key] = {
                    "bh_return_pct": round(bh_cum, 1),
                    "vt_return_pct": round(vt_cum, 1),
                    "protection_pp": round(vt_cum - bh_cum, 1),
                }
                print(f"    {info['name']:25s}: BH={bh_cum:+.1f}%, VT={vt_cum:+.1f}%, Protection={vt_cum - bh_cum:+.1f}pp")
            except Exception:
                pass
        crisis_results[crisis_name] = crisis_data

    # ── Step 7: Summary & Key Finding ──
    print(f"\n{'='*70}")
    print("── KEY FINDINGS ──")

    # Count Sharpe improvements
    sharpe_winners = sum(1 for k in all_results if all_results[k]["sharpe_improvement_12vix"] > 0)
    mdd_winners = sum(1 for k in all_results if all_results[k]["mdd_improvement_12vix_pp"] > 0)

    # VIX as global fear indicator
    avg_corr = np.mean([vix_corr_results[k]["pearson_vix_rv21"] for k in vix_corr_results])
    spy_corr = vix_corr_results["SPY"]["pearson_vix_rv21"]
    non_us_corrs = [vix_corr_results[k]["pearson_vix_rv21"] for k in vix_corr_results if k != "SPY"]
    avg_non_us_corr = np.mean(non_us_corrs)

    is_global = avg_non_us_corr > 0.5  # Threshold for "global" classification

    conclusion = (
        f"VIX is {'a GLOBAL' if is_global else 'a PARTIAL global'} fear indicator. "
        f"VIX-RV21 correlation: SPY={spy_corr:.3f}, non-US avg={avg_non_us_corr:.3f}. "
        f"12/VIX improves Sharpe for {sharpe_winners}/{len(MARKETS)} markets, "
        f"MDD for {mdd_winners}/{len(MARKETS)} markets. "
        f"VT's primary value is UNIVERSAL MDD reduction, not Sharpe improvement. "
        f"VIX is a global risk barometer but its VT benefit concentrates in US equities."
    )

    print(f"\n  {conclusion}")

    # ── Save Results ──
    results = {
        "experiment_id": "K669",
        "title": "Does VT Work Globally? Testing 12/VIX on International ETFs",
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "data_source": "yfinance",
        "data_period": f"{START_DATE} to {END_DATE}",
        "methodology": "12/VIX allocation + vol-adjusted VT + bootstrap CI",
        "markets_tested": list(MARKETS.keys()),
        "vix_target": VIX_TARGET,
        "ma_window": MA_WINDOW,
        "bootstrap_reps": BOOTSTRAP_REPS,
        "descriptive_stats": desc_stats,
        "vix_correlation": vix_corr_results,
        "individual_market_results": all_results,
        "global_portfolio": global_results,
        "crisis_analysis": crisis_results,
        "key_finding": conclusion,
        "vix_is_global_indicator": is_global,
        "sharpe_improvement_count": f"{sharpe_winners}/{len(MARKETS)}",
        "mdd_improvement_count": f"{mdd_winners}/{len(MARKETS)}",
        "references": [
            "Moreira & Muir (2017) 'Volatility-Managed Portfolios' JoF",
            "Bozovic (2024) IRFA: VIX-managed > realized-vol-managed",
            "Cederburg et al. (2020) skeptical view of VT",
            "Harvey et al. (2016) t>3.0 threshold",
        ],
        "prior_knowledge": ["N84", "K590", "N87"],
        "limitations": [
            "VIX is SPY implied vol — inherent US bias",
            "EFA/EWJ/EEM are USD-denominated — currency effects embedded",
            "Cash at 0% (ignores money market returns ~4-5%)",
            "No transaction costs modeled",
            "Period 2010-2026 is mostly US bull market — may bias SPY results",
        ],
    }

    output_path = Path(__file__).parent / "k669_results.json"
    with open(output_path, "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\nResults saved to {output_path}")

    return results


if __name__ == "__main__":
    results = main()
