"""VT Alpha Trend Following Decomposition
=========================================
Motivated by Hood & Raughtigan (2024): VT alpha ≈ trend following exposure.
When controlling for TSMOM factor, equity VT alpha disappears.

Hypothesis:
- Equity VT alpha IS trend following (leverage effect → vol-return correlation → trend)
- Commodity VT alpha should NOT disappear (different mechanism: diversification, not leverage)
- This explains gamma-mechanism: works for equity (ρ=0.886) but not cross-asset (ρ=-0.45)

[提出: 用戶, 執行: Claude]
"""
import json
import sys
import warnings
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
from arch import arch_model
from scipy import stats

warnings.filterwarnings("ignore")

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from volpred.data.manager import DataManager

# ─────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────
ASSETS = ["SPY", "GLD", "TLT", "EEM"]
START = "2005-01-01"  # need history for lookback
END = "2026-12-31"
OOS_START = "2008-01-01"  # start after enough history for 252d lookback
WINDOW = 2000
SIGMA_TARGET = 0.12
VIX_THRESHOLD = 12.0
RF_ANNUAL = 0.04
TX_COST = 0.0005

# Sub-periods for robustness
SUB_PERIODS = {
    "full_sample":   ("2008-01-01", "2026-03-20"),
    "pre_covid":     ("2008-01-01", "2020-01-31"),
    "covid":         ("2020-02-01", "2021-06-30"),
    "post_covid":    ("2021-07-01", "2026-03-20"),
    "gfc":           ("2008-01-01", "2010-12-31"),
    "bull_2013_2019": ("2013-01-01", "2019-12-31"),
}


def fetch_data():
    """Fetch price data for all assets + VIX."""
    dm = DataManager()
    data = {}
    for asset in ASSETS:
        print(f"  Fetching {asset}...")
        df = dm.get_model_data(asset, START, END, force_refresh=False)
        data[asset] = df
        print(f"    {asset}: {len(df)} obs, {df.index[0].date()} to {df.index[-1].date()}")

    print("  Fetching ^VIX...")
    vix = dm.get_price_data("^VIX", START, END, force_refresh=False)
    data["VIX"] = vix
    print(f"    VIX: {len(vix)} obs")

    return data


def compute_tsmom_factor(returns: pd.Series, lookback_days: list = [21, 63, 252]):
    """Compute time-series momentum (trend following) factor.

    TSMOM(k) = sign(cumulative return over past k days) × today's return
    Final factor = equal-weight average of all lookback periods.

    Uses LAGGED signals: sign computed from returns up to t-1, applied to return at t.
    """
    tsmom_signals = {}
    tsmom_factors = {}

    for k in lookback_days:
        # Cumulative return over past k trading days (lagged by 1 day)
        cum_ret = returns.rolling(k).sum().shift(1)
        signal = np.sign(cum_ret)
        tsmom_signals[f"tsmom_signal_{k}d"] = signal

        # TSMOM return = signal × today's return
        tsmom_factors[f"tsmom_{k}d"] = signal * returns

    df_signals = pd.DataFrame(tsmom_signals, index=returns.index)
    df_factors = pd.DataFrame(tsmom_factors, index=returns.index)

    # Equal-weight average TSMOM factor
    df_factors["tsmom_avg"] = df_factors.mean(axis=1)

    return df_factors, df_signals


def compute_12vix_strategy(asset_returns: pd.Series, vix_close: pd.Series,
                            monthly_rebal=True):
    """Compute 12/VIX VT strategy returns with lagged weights.

    Weight = min(12/VIX, 1.0), applied with 1-day lag.
    Monthly rebalance: weight updated only on first trading day of each month.
    """
    # Align indices
    common = asset_returns.index.intersection(vix_close.index)
    ret = asset_returns.loc[common]
    vix = vix_close.loc[common]

    # Raw weight (lagged by 1 day)
    raw_weight = (VIX_THRESHOLD / vix).clip(0, 1.0).shift(1)

    if monthly_rebal:
        # Only update weight on first trading day of each month
        weight = raw_weight.copy()
        current_w = np.nan
        current_month = None
        for i, (date, w) in enumerate(raw_weight.items()):
            ym = (date.year, date.month)
            if ym != current_month:
                current_month = ym
                current_w = w
            weight.iloc[i] = current_w
    else:
        weight = raw_weight

    # Strategy return: w * asset + (1-w) * rf_daily
    rf_daily = RF_ANNUAL / 252
    strat_ret = weight * ret + (1 - weight) * rf_daily

    return strat_ret.dropna(), weight.dropna()


def compute_garch_vt_strategy(returns_pct_series: pd.Series, raw_returns: pd.Series,
                               window=2000, target=0.12):
    """Compute GARCH VT strategy (GJR-GARCH, sigma-targeting).

    Refit every 5 days for computational efficiency.
    """
    target_daily = target / np.sqrt(252)
    rf_daily = RF_ANNUAL / 252

    dates = raw_returns.index
    strat_ret = pd.Series(np.nan, index=dates)
    weights = pd.Series(np.nan, index=dates)

    last_sigma = None

    for i in range(window, len(dates)):
        # Refit every 5 days or first time
        if i == window or (i - window) % 5 == 0:
            train = returns_pct_series.iloc[i-window:i].values
            try:
                am = arch_model(train, vol="GARCH", p=1, o=1, q=1,
                               dist="normal", mean="Zero", rescale=False)
                res = am.fit(disp="off", show_warning=False)
                sigma = float(np.sqrt(res.forecast(horizon=1).variance.iloc[-1, 0]) / 100)
                last_sigma = sigma
            except Exception:
                if last_sigma is None:
                    continue
                sigma = last_sigma
        else:
            sigma = last_sigma
            if sigma is None:
                continue

        w = min(max(target_daily / sigma, 0), 2.0)

        # Lagged: weight computed from data up to t, applied to return at t+1
        if i + 1 < len(dates):
            weights.iloc[i+1] = w
            strat_ret.iloc[i+1] = w * raw_returns.iloc[i+1] + (1 - w) * rf_daily

    return strat_ret.dropna(), weights.dropna()


def run_regression(y: pd.Series, X: pd.DataFrame, add_constant=True):
    """Run OLS regression, return results dict."""
    common = y.dropna().index.intersection(X.dropna().index)
    if len(common) < 30:
        return None

    y_c = y.loc[common].values
    X_c = X.loc[common].values

    if add_constant:
        X_c = np.column_stack([np.ones(len(X_c)), X_c])

    # OLS: (X'X)^{-1} X'y
    try:
        beta = np.linalg.lstsq(X_c, y_c, rcond=None)[0]
        y_hat = X_c @ beta
        resid = y_c - y_hat
        n, k = X_c.shape

        # R-squared
        ss_res = np.sum(resid**2)
        ss_tot = np.sum((y_c - y_c.mean())**2)
        r2 = 1 - ss_res / ss_tot if ss_tot > 0 else 0
        adj_r2 = 1 - (1 - r2) * (n - 1) / (n - k) if n > k else r2

        # Standard errors (heteroskedasticity-robust, HC1)
        leverage = np.diag(X_c @ np.linalg.inv(X_c.T @ X_c) @ X_c.T)
        S = np.diag(resid**2 / (1 - leverage)**2)  # HC2
        XtSX = X_c.T @ S @ X_c
        cov = np.linalg.inv(X_c.T @ X_c) @ XtSX @ np.linalg.inv(X_c.T @ X_c)
        se = np.sqrt(np.diag(cov))

        t_stats = beta / se
        p_values = 2 * (1 - stats.t.cdf(np.abs(t_stats), df=n-k))

        # Durbin-Watson
        dw = np.sum(np.diff(resid)**2) / ss_res if ss_res > 0 else 2.0

        return {
            "n_obs": int(n),
            "r2": float(r2),
            "adj_r2": float(adj_r2),
            "dw": float(dw),
            "coefficients": {
                "names": ["const"] + list(X.columns) if add_constant else list(X.columns),
                "beta": [float(b) for b in beta],
                "se": [float(s) for s in se],
                "t_stat": [float(t) for t in t_stats],
                "p_value": [float(p) for p in p_values],
            }
        }
    except Exception as e:
        return {"error": str(e)}


def compute_strategy_metrics(returns: pd.Series):
    """Compute standard performance metrics."""
    if len(returns) < 30:
        return {}

    ann_ret = returns.mean() * 252
    ann_vol = returns.std() * np.sqrt(252)
    rf = RF_ANNUAL
    sharpe = (ann_ret - rf) / ann_vol if ann_vol > 0 else 0

    # MDD
    cum = (1 + returns).cumprod()
    drawdown = cum / cum.cummax() - 1
    mdd = drawdown.min()

    # Sortino
    downside = returns[returns < 0].std() * np.sqrt(252)
    sortino = (ann_ret - rf) / downside if downside > 0 else 0

    # Calmar
    calmar = ann_ret / abs(mdd) if mdd != 0 else 0

    return {
        "ann_return": round(float(ann_ret), 4),
        "ann_vol": round(float(ann_vol), 4),
        "sharpe": round(float(sharpe), 4),
        "mdd": round(float(mdd), 4),
        "sortino": round(float(sortino), 4),
        "calmar": round(float(calmar), 4),
        "n_obs": int(len(returns)),
    }


def main():
    print("=" * 70)
    print("VT Alpha Trend Following Decomposition")
    print("=" * 70)

    # ─────────────────────────────────────────
    # Step 1: Fetch data
    # ─────────────────────────────────────────
    print("\n[1/5] 取得資料...")
    data = fetch_data()

    results = {
        "experiment": "VT Alpha Trend Following Decomposition",
        "description": (
            "Decompose VT alpha into trend following component. "
            "Motivated by Hood & Raughtigan (2024): VT alpha ≈ TSMOM exposure. "
            "Test: regress VT excess returns on MKT + TSMOM. "
            "If alpha drops → VT = trend following."
        ),
        "proposed_by": "用戶",
        "executed_by": "Claude",
        "timestamp": datetime.now().isoformat(),
        "config": {
            "assets": ASSETS,
            "start": START,
            "oos_start": OOS_START,
            "window": WINDOW,
            "sigma_target": SIGMA_TARGET,
            "vix_threshold": VIX_THRESHOLD,
            "tsmom_lookbacks": [21, 63, 252],
            "sub_periods": SUB_PERIODS,
        },
        "asset_results": {},
        "cross_asset_summary": {},
    }

    # ─────────────────────────────────────────
    # Step 2: Process each asset
    # ─────────────────────────────────────────
    for asset in ASSETS:
        print(f"\n{'='*60}")
        print(f"[2/5] 分析 {asset}")
        print(f"{'='*60}")

        asset_data = data[asset]
        returns = asset_data["returns"]
        returns_pct = returns * 100

        # 2a. Compute TSMOM factors
        print(f"  計算趨勢追隨因子 (TSMOM)...")
        tsmom_factors, tsmom_signals = compute_tsmom_factor(returns)

        # 2b. Compute 12/VIX strategy
        print(f"  計算 12/VIX 策略...")
        vix_close = data["VIX"]["close"] if "close" in data["VIX"].columns else data["VIX"]["Close"]
        vt_12vix_ret, vt_12vix_wt = compute_12vix_strategy(returns, vix_close, monthly_rebal=True)

        # 2c. Compute GARCH VT strategy
        print(f"  計算 GARCH VT 策略（w={WINDOW}，每 5 天 refit）...")
        vt_garch_ret, vt_garch_wt = compute_garch_vt_strategy(returns_pct, returns,
                                                                window=WINDOW, target=SIGMA_TARGET)

        # 2d. Buy & Hold
        bh_ret = returns.copy()

        # ─────────────────────────────────────
        # Step 3: Regression Analysis
        # ─────────────────────────────────────
        print(f"\n  [3/5] 迴歸分析...")

        asset_result = {
            "strategies": {},
            "correlations": {},
            "sub_period_results": {},
        }

        strategies = {
            "12/VIX VT": (vt_12vix_ret, vt_12vix_wt),
            "GARCH VT": (vt_garch_ret, vt_garch_wt),
        }

        for strat_name, (strat_ret, strat_wt) in strategies.items():
            print(f"\n  --- {strat_name} ---")

            # Excess return over buy & hold
            common_idx = strat_ret.index.intersection(bh_ret.index).intersection(tsmom_factors.dropna().index)
            if len(common_idx) < 100:
                print(f"    ⚠️ 數據不足 ({len(common_idx)} obs), 跳過")
                continue

            vt_excess = strat_ret.loc[common_idx] - bh_ret.loc[common_idx]
            mkt = bh_ret.loc[common_idx]
            tsmom_avg = tsmom_factors["tsmom_avg"].loc[common_idx]
            tsmom_21 = tsmom_factors["tsmom_21d"].loc[common_idx]
            tsmom_63 = tsmom_factors["tsmom_63d"].loc[common_idx]
            tsmom_252 = tsmom_factors["tsmom_252d"].loc[common_idx]

            strat_result = {
                "metrics": compute_strategy_metrics(strat_ret.loc[common_idx]),
                "bh_metrics": compute_strategy_metrics(bh_ret.loc[common_idx]),
                "regressions": {},
            }

            # ── Regression 1: VT_excess = α + β₁×MKT
            print(f"    Model 1: VT_excess ~ MKT")
            reg1 = run_regression(vt_excess, pd.DataFrame({"MKT": mkt}))
            if reg1 and "error" not in reg1:
                alpha1 = reg1["coefficients"]["beta"][0]
                t_alpha1 = reg1["coefficients"]["t_stat"][0]
                print(f"      α = {alpha1*252*100:.2f}% ann. (t={t_alpha1:.2f}), R²={reg1['r2']:.4f}")
                strat_result["regressions"]["model1_mkt_only"] = reg1

            # ── Regression 2: VT_excess = α + β₁×MKT + β₂×TSMOM_avg
            print(f"    Model 2: VT_excess ~ MKT + TSMOM_avg")
            reg2 = run_regression(vt_excess, pd.DataFrame({"MKT": mkt, "TSMOM_avg": tsmom_avg}))
            if reg2 and "error" not in reg2:
                alpha2 = reg2["coefficients"]["beta"][0]
                t_alpha2 = reg2["coefficients"]["t_stat"][0]
                beta_tsmom = reg2["coefficients"]["beta"][2]
                t_tsmom = reg2["coefficients"]["t_stat"][2]
                print(f"      α = {alpha2*252*100:.2f}% ann. (t={t_alpha2:.2f}), β_TSMOM={beta_tsmom:.4f} (t={t_tsmom:.2f}), R²={reg2['r2']:.4f}")
                strat_result["regressions"]["model2_mkt_tsmom"] = reg2

                # Alpha reduction
                if reg1 and "error" not in reg1:
                    alpha_reduction = 1 - abs(alpha2) / abs(alpha1) if alpha1 != 0 else 0
                    print(f"      ★ Alpha 下降: {alpha_reduction*100:.1f}%")
                    strat_result["alpha_reduction_pct"] = round(float(alpha_reduction * 100), 1)

            # ── Regression 3: VT_excess = α + β₁×MKT + β₂×TSMOM_21 + β₃×TSMOM_63 + β₄×TSMOM_252
            print(f"    Model 3: VT_excess ~ MKT + TSMOM_21 + TSMOM_63 + TSMOM_252")
            reg3 = run_regression(vt_excess, pd.DataFrame({
                "MKT": mkt, "TSMOM_21d": tsmom_21, "TSMOM_63d": tsmom_63, "TSMOM_252d": tsmom_252
            }))
            if reg3 and "error" not in reg3:
                alpha3 = reg3["coefficients"]["beta"][0]
                t_alpha3 = reg3["coefficients"]["t_stat"][0]
                print(f"      α = {alpha3*252*100:.2f}% ann. (t={t_alpha3:.2f}), R²={reg3['r2']:.4f}")
                betas = reg3["coefficients"]["beta"]
                names = reg3["coefficients"]["names"]
                for n, b, t in zip(names[1:], betas[1:], reg3["coefficients"]["t_stat"][1:]):
                    sig = "***" if abs(t) > 2.58 else "**" if abs(t) > 1.96 else "*" if abs(t) > 1.64 else ""
                    print(f"        {n}: β={b:.4f} (t={t:.2f}) {sig}")
                strat_result["regressions"]["model3_mkt_tsmom_decomposed"] = reg3

            # ── Regression 4: Strategy level return ~ MKT + TSMOM (not excess)
            print(f"    Model 4: VT_return ~ MKT + TSMOM_avg (strategy level)")
            strat_ret_aligned = strat_ret.loc[common_idx]
            reg4 = run_regression(strat_ret_aligned, pd.DataFrame({"MKT": mkt, "TSMOM_avg": tsmom_avg}))
            if reg4 and "error" not in reg4:
                alpha4 = reg4["coefficients"]["beta"][0]
                t_alpha4 = reg4["coefficients"]["t_stat"][0]
                mkt_beta = reg4["coefficients"]["beta"][1]
                tsmom_beta = reg4["coefficients"]["beta"][2]
                print(f"      α = {alpha4*252*100:.2f}% ann. (t={t_alpha4:.2f})")
                print(f"      β_MKT = {mkt_beta:.4f}, β_TSMOM = {tsmom_beta:.4f}")
                print(f"      R² = {reg4['r2']:.4f}")
                strat_result["regressions"]["model4_level_mkt_tsmom"] = reg4

            # ─────────────────────────────────
            # Step 4: Correlation Analysis
            # ─────────────────────────────────
            print(f"\n    [4/5] 相關性分析...")

            # Weight changes vs TSMOM signal
            wt_common = strat_wt.index.intersection(tsmom_signals.dropna().index)
            if len(wt_common) > 30:
                wt_changes = strat_wt.loc[wt_common].diff()

                corr_results = {}
                for col in tsmom_signals.columns:
                    sig = tsmom_signals[col].loc[wt_common]
                    r, p = stats.pearsonr(wt_changes.dropna().values,
                                         sig.loc[wt_changes.dropna().index].values)
                    corr_results[col] = {"correlation": round(float(r), 4), "p_value": round(float(p), 6)}
                    print(f"      corr(Δweight, {col}) = {r:.4f} (p={p:.4f})")

                # Also: weight LEVEL vs TSMOM signal
                for col in tsmom_signals.columns:
                    sig = tsmom_signals[col].loc[wt_common]
                    valid = strat_wt.loc[wt_common].dropna().index.intersection(sig.dropna().index)
                    if len(valid) > 30:
                        r, p = stats.pearsonr(strat_wt.loc[valid].values, sig.loc[valid].values)
                        corr_results[f"level_{col}"] = {"correlation": round(float(r), 4), "p_value": round(float(p), 6)}
                        print(f"      corr(weight_level, {col}) = {r:.4f} (p={p:.4f})")

                strat_result["correlations"] = corr_results

            # ─────────────────────────────────
            # Step 5: Sub-period robustness
            # ─────────────────────────────────
            print(f"\n    [5/5] 分期分析...")
            sub_results = {}
            for period_name, (p_start, p_end) in SUB_PERIODS.items():
                mask = (common_idx >= p_start) & (common_idx <= p_end)
                sub_idx = common_idx[mask]
                if len(sub_idx) < 100:
                    continue

                sub_vt_excess = vt_excess.loc[sub_idx]
                sub_mkt = mkt.loc[sub_idx]
                sub_tsmom = tsmom_avg.loc[sub_idx]

                # Model 1
                sub_reg1 = run_regression(sub_vt_excess, pd.DataFrame({"MKT": sub_mkt}))
                # Model 2
                sub_reg2 = run_regression(sub_vt_excess, pd.DataFrame({"MKT": sub_mkt, "TSMOM_avg": sub_tsmom}))

                if sub_reg1 and sub_reg2 and "error" not in sub_reg1 and "error" not in sub_reg2:
                    a1 = sub_reg1["coefficients"]["beta"][0]
                    a2 = sub_reg2["coefficients"]["beta"][0]
                    reduction = 1 - abs(a2) / abs(a1) if a1 != 0 else 0

                    sub_results[period_name] = {
                        "n_obs": int(len(sub_idx)),
                        "alpha_mkt_only_ann": round(float(a1 * 252 * 100), 2),
                        "t_alpha_mkt_only": round(float(sub_reg1["coefficients"]["t_stat"][0]), 2),
                        "alpha_with_tsmom_ann": round(float(a2 * 252 * 100), 2),
                        "t_alpha_with_tsmom": round(float(sub_reg2["coefficients"]["t_stat"][0]), 2),
                        "alpha_reduction_pct": round(float(reduction * 100), 1),
                        "tsmom_beta": round(float(sub_reg2["coefficients"]["beta"][2]), 4),
                        "tsmom_t_stat": round(float(sub_reg2["coefficients"]["t_stat"][2]), 2),
                    }
                    sig = "★" if abs(sub_reg2["coefficients"]["t_stat"][2]) > 1.96 else ""
                    print(f"      {period_name}: α {a1*252*100:.2f}%→{a2*252*100:.2f}% "
                          f"(↓{reduction*100:.0f}%), β_TSMOM t={sub_reg2['coefficients']['t_stat'][2]:.2f} {sig}")

            strat_result["sub_period_results"] = sub_results
            asset_result["strategies"][strat_name] = strat_result

        # ─────────────────────────────────
        # Leverage effect (vol-return correlation)
        # ─────────────────────────────────
        print(f"\n  槓桿效果 (leverage effect) 檢驗...")
        if len(returns) >= 500:
            # Rolling 63-day correlation between returns and squared returns (vol proxy)
            vol_proxy = returns.rolling(21).std()
            lev_corr = returns.rolling(252).corr(vol_proxy.shift(1))
            mean_lev = float(lev_corr.mean())
            print(f"    mean corr(r_t, σ_{'{t-1}'}) = {mean_lev:.4f}")
            asset_result["leverage_effect_corr"] = round(mean_lev, 4)

            # Direct: corr(r_t, |r_{t-1}|)
            abs_ret_lag = returns.abs().shift(1)
            lev_df = pd.DataFrame({"r": returns, "abs_lag": abs_ret_lag}).dropna()
            direct_corr, direct_p = stats.pearsonr(lev_df["r"].values, lev_df["abs_lag"].values)
            print(f"    corr(r_t, |r_{{t-1}}|) = {direct_corr:.4f} (p={direct_p:.4f})")
            asset_result["direct_leverage_corr"] = round(float(direct_corr), 4)

        results["asset_results"][asset] = asset_result

    # ─────────────────────────────────────────
    # Cross-asset summary
    # ─────────────────────────────────────────
    print(f"\n{'='*60}")
    print("跨資產總結")
    print(f"{'='*60}")

    summary = {}
    for asset in ASSETS:
        ar = results["asset_results"].get(asset, {})
        for strat_name in ["12/VIX VT", "GARCH VT"]:
            sr = ar.get("strategies", {}).get(strat_name, {})
            regs = sr.get("regressions", {})

            r1 = regs.get("model1_mkt_only", {})
            r2 = regs.get("model2_mkt_tsmom", {})

            if r1 and r2 and "coefficients" in r1 and "coefficients" in r2:
                key = f"{asset}_{strat_name}"
                a1 = r1["coefficients"]["beta"][0]
                t1 = r1["coefficients"]["t_stat"][0]
                a2 = r2["coefficients"]["beta"][0]
                t2 = r2["coefficients"]["t_stat"][0]
                tsmom_b = r2["coefficients"]["beta"][2]
                tsmom_t = r2["coefficients"]["t_stat"][2]
                reduction = sr.get("alpha_reduction_pct", 0)

                summary[key] = {
                    "asset": asset,
                    "strategy": strat_name,
                    "alpha_mkt_only_ann_pct": round(float(a1 * 252 * 100), 2),
                    "t_alpha_mkt_only": round(float(t1), 2),
                    "alpha_with_tsmom_ann_pct": round(float(a2 * 252 * 100), 2),
                    "t_alpha_with_tsmom": round(float(t2), 2),
                    "alpha_reduction_pct": reduction,
                    "tsmom_beta": round(float(tsmom_b), 4),
                    "tsmom_t_stat": round(float(tsmom_t), 2),
                    "leverage_effect": ar.get("leverage_effect_corr", None),
                }

                is_equity = asset in ["SPY", "EEM"]
                category = "Equity" if is_equity else "Non-Equity"
                print(f"\n  {asset} ({category}) — {strat_name}:")
                print(f"    α (MKT only): {a1*252*100:+.2f}% (t={t1:.2f})")
                print(f"    α (MKT+TSMOM): {a2*252*100:+.2f}% (t={t2:.2f})")
                print(f"    Alpha 下降: {reduction:.1f}%")
                print(f"    β_TSMOM: {tsmom_b:.4f} (t={tsmom_t:.2f})")
                print(f"    Leverage effect: {ar.get('leverage_effect_corr', 'N/A')}")

    results["cross_asset_summary"] = summary

    # ─────────────────────────────────────────
    # Hypothesis test summary
    # ─────────────────────────────────────────
    print(f"\n{'='*60}")
    print("假說檢定")
    print(f"{'='*60}")

    # Check: does equity alpha drop more than commodity/bond?
    equity_reductions = []
    non_equity_reductions = []

    for key, val in summary.items():
        if val["asset"] in ["SPY", "EEM"]:
            equity_reductions.append(val["alpha_reduction_pct"])
        else:
            non_equity_reductions.append(val["alpha_reduction_pct"])

    hypothesis_results = {}

    if equity_reductions and non_equity_reductions:
        avg_eq = np.mean(equity_reductions)
        avg_neq = np.mean(non_equity_reductions)
        print(f"\n  Equity VT 平均 alpha 下降: {avg_eq:.1f}%")
        print(f"  Non-Equity VT 平均 alpha 下降: {avg_neq:.1f}%")
        print(f"  差異: {avg_eq - avg_neq:.1f} pp")

        hypothesis_results["equity_avg_alpha_reduction"] = round(float(avg_eq), 1)
        hypothesis_results["non_equity_avg_alpha_reduction"] = round(float(avg_neq), 1)
        hypothesis_results["difference_pp"] = round(float(avg_eq - avg_neq), 1)

        if avg_eq > avg_neq:
            print(f"\n  ✓ 假說成立方向正確：Equity VT alpha 更容易被 TSMOM 解釋")
        else:
            print(f"\n  ✗ 假說方向相反：Non-Equity VT alpha 被 TSMOM 解釋更多")

    # Check: TSMOM loading correlates with leverage effect?
    leverage_vals = []
    tsmom_loadings = []
    asset_labels = []
    for key, val in summary.items():
        if val["leverage_effect"] is not None and "12/VIX" in val["strategy"]:
            leverage_vals.append(val["leverage_effect"])
            tsmom_loadings.append(val["tsmom_beta"])
            asset_labels.append(val["asset"])

    if len(leverage_vals) >= 3:
        r_lt, p_lt = stats.pearsonr(leverage_vals, tsmom_loadings)
        print(f"\n  corr(leverage_effect, TSMOM_loading): ρ={r_lt:.3f} (p={p_lt:.3f})")
        hypothesis_results["leverage_tsmom_corr"] = round(float(r_lt), 3)
        hypothesis_results["leverage_tsmom_p"] = round(float(p_lt), 3)

    results["hypothesis_results"] = hypothesis_results

    # ─────────────────────────────────────────
    # Theoretical interpretation
    # ─────────────────────────────────────────
    print(f"\n{'='*60}")
    print("理論詮釋")
    print(f"{'='*60}")

    interpretations = []

    # Check dominant TSMOM horizon
    for asset in ASSETS:
        ar = results["asset_results"].get(asset, {})
        sr = ar.get("strategies", {}).get("12/VIX VT", {})
        r3 = sr.get("regressions", {}).get("model3_mkt_tsmom_decomposed", {})
        if r3 and "coefficients" in r3:
            names = r3["coefficients"]["names"]
            t_stats = r3["coefficients"]["t_stat"]
            betas = r3["coefficients"]["beta"]

            # Find most significant TSMOM horizon
            tsmom_names = [n for n in names if "TSMOM" in n]
            tsmom_ts = [t_stats[names.index(n)] for n in tsmom_names]
            tsmom_bs = [betas[names.index(n)] for n in tsmom_names]

            if tsmom_ts:
                max_idx = np.argmax(np.abs(tsmom_ts))
                print(f"  {asset}: 最顯著 TSMOM 頻率 = {tsmom_names[max_idx]} (t={tsmom_ts[max_idx]:.2f}, β={tsmom_bs[max_idx]:.4f})")
                interpretations.append(f"{asset}: dominant TSMOM = {tsmom_names[max_idx]} (t={tsmom_ts[max_idx]:.2f})")

    results["interpretations"] = interpretations

    # ─────────────────────────────────────────
    # Conclusion
    # ─────────────────────────────────────────
    conclusions = []

    # Check if SPY alpha disappears
    spy_12vix = summary.get("SPY_12/VIX VT", {})
    if spy_12vix:
        if spy_12vix.get("alpha_reduction_pct", 0) > 50:
            conclusions.append(
                f"SPY 12/VIX VT alpha 被 TSMOM 解釋 {spy_12vix['alpha_reduction_pct']:.0f}% — "
                f"支持 Hood & Raughtigan (2024): VT ≈ 趨勢追隨"
            )
        elif spy_12vix.get("alpha_reduction_pct", 0) > 20:
            conclusions.append(
                f"SPY 12/VIX VT alpha 部分被 TSMOM 解釋 ({spy_12vix['alpha_reduction_pct']:.0f}%) — "
                f"VT 含趨勢追隨成分但非全部"
            )
        else:
            conclusions.append(
                f"SPY 12/VIX VT alpha 幾乎不受 TSMOM 控制影響 ({spy_12vix['alpha_reduction_pct']:.0f}%) — "
                f"VT alpha 可能來自其他機制"
            )

    # Cross-asset pattern
    if hypothesis_results.get("difference_pp", 0) > 10:
        conclusions.append(
            "Equity vs Non-Equity 差異顯著 — 槓桿效果是 VT-TSMOM 連結的關鍵中介變數"
        )

    results["conclusions"] = conclusions

    for i, c in enumerate(conclusions):
        print(f"\n  結論 {i+1}: {c}")

    # ─────────────────────────────────────────
    # Save results
    # ─────────────────────────────────────────
    output_path = Path("/Users/yhlai0911/Desktop/volpred-research/storage/experiments/vt_trend_decomposition.json")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False, default=str)

    print(f"\n結果已儲存至: {output_path}")
    print("\n" + "=" * 70)
    print("實驗完成")
    print("=" * 70)

    return results


if __name__ == "__main__":
    main()
