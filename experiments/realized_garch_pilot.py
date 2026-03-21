"""Realized GARCH Pilot Test.

Loads 5-min intraday data, computes daily realized variance,
fetches matching daily returns, and fits the Realized GARCH
model of Hansen, Huang & Shek (2012).

Usage:
    uv run python experiments/realized_garch_pilot.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

# Ensure project root is on path
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root / "src"))

from volpred.models.garch.realized_garch import RealizedGARCH


def load_realized_variance(data_dir: Path) -> pd.Series:
    """Load pre-computed daily realized variance.

    Falls back to computing from 5-min CSVs if the daily file is missing.
    """
    daily_rv_path = data_dir / "SPY_daily_rv.csv"
    if daily_rv_path.exists():
        df = pd.read_csv(daily_rv_path, index_col=0, parse_dates=True)
        return df.iloc[:, 0]

    # Fallback: compute from individual 5-min files
    print("Daily RV file not found. Computing from 5-min CSVs...")
    csv_files = sorted(data_dir.glob("SPY_5min_*.csv"))
    if not csv_files:
        raise FileNotFoundError(f"No 5-min CSV files in {data_dir}")

    records = {}
    for f in csv_files:
        date_str = f.stem.split("_")[-1]
        df = pd.read_csv(f, header=[0, 1], index_col=0, parse_dates=True)
        close_col = [c for c in df.columns if "close" in c[0].lower() or "Close" in c[0]]
        if close_col:
            prices = df[close_col[0]].dropna()
        else:
            prices = df.iloc[:, 0].dropna()

        log_ret = np.log(prices / prices.shift(1)).dropna()
        rv = float(np.sum(log_ret ** 2))
        records[pd.Timestamp(date_str)] = rv

    return pd.Series(records).sort_index()


def load_daily_returns(dates: pd.DatetimeIndex) -> pd.Series:
    """Download SPY daily returns from yfinance aligned to given dates."""
    import yfinance as yf

    start = dates[0] - pd.Timedelta(days=10)
    end = dates[-1] + pd.Timedelta(days=5)

    print(f"Downloading SPY daily data ({start.date()} to {end.date()})...")
    spy = yf.download("SPY", start=start, end=end, progress=False)

    if isinstance(spy.columns, pd.MultiIndex):
        spy.columns = spy.columns.get_level_values(0)
    spy.index = spy.index.tz_localize(None)

    spy["log_return"] = np.log(spy["Close"] / spy["Close"].shift(1))
    spy = spy.dropna(subset=["log_return"])

    return spy["log_return"]


def print_section(title: str, char: str = "-", width: int = 70):
    print(f"\n{char * width}")
    print(f"  {title}")
    print(f"{char * width}")


def main():
    print("=" * 70)
    print("  Realized GARCH Pilot Test")
    print("  Hansen, Huang & Shek (2012, JAE) - Log-Linear Specification")
    print("=" * 70)

    # ---- Load data ----
    data_dir = project_root / "data" / "intraday"
    if not data_dir.exists():
        # Try storage path
        data_dir = project_root / "storage" / "intraday"

    rv_series = load_realized_variance(data_dir)
    print(f"\nRealized variance: {len(rv_series)} days")
    print(f"  Date range: {rv_series.index[0].date()} to {rv_series.index[-1].date()}")
    print(f"  Mean RV:    {rv_series.mean():.6e}")
    print(f"  Ann. vol:   {(rv_series.mean() * 252)**0.5:.2%}")

    daily_ret = load_daily_returns(rv_series.index)

    # Align
    common = rv_series.index.intersection(daily_ret.index)
    print(f"\nCommon dates: {len(common)}")

    if len(common) < 20:
        print(f"ERROR: Only {len(common)} days. Need >= 20.")
        sys.exit(1)

    returns = daily_ret.loc[common].values
    realized_var = rv_series.loc[common].values
    dates = common

    print(f"\nData summary:")
    print(f"  Returns:  mean={returns.mean():.6f}, std={returns.std():.6f}, "
          f"min={returns.min():.6f}, max={returns.max():.6f}")
    print(f"  RV:       mean={realized_var.mean():.6e}, "
          f"min={realized_var.min():.6e}, max={realized_var.max():.6e}")

    # ---- Fit Realized GARCH ----
    print_section("Fitting Realized GARCH (5 starting points)")

    model = RealizedGARCH(n_starts=5)
    result = model.fit(returns, realized_var)

    print(f"  Converged:      {result['converged']}")
    print(f"  Log-likelihood: {result['loglik']:.4f}")
    print(f"  Iterations:     {result['n_iter']}")

    print(f"\n  Estimated parameters:")
    for name, val in result["params"].items():
        print(f"    {name:10s} = {val:12.6f}")

    beta = result["params"]["beta"]
    gamma = result["params"]["gamma"]
    phi = result["params"]["phi"]
    persistence = beta + gamma * phi
    print(f"\n    Persistence (beta + gamma*phi) = {persistence:.4f}")

    tau1 = result["params"]["tau1"]
    tau2 = result["params"]["tau2"]
    if tau1 < 0:
        print(f"    Leverage effect: tau1={tau1:.4f} < 0 (negative shocks increase vol)")
    else:
        print(f"    No leverage via tau1: tau1={tau1:.4f} >= 0")

    # ---- In-sample comparison: h_t vs x_t ----
    print_section("In-sample: model h_t vs realized x_t")

    h_t = model.get_conditional_variance()

    corr_level = np.corrcoef(h_t, realized_var)[0, 1]
    corr_log = np.corrcoef(np.log(h_t), np.log(realized_var))[0, 1]
    qlike_rg = np.mean(realized_var / h_t - np.log(realized_var / h_t) - 1)

    print(f"  Corr(h_t, x_t):       {corr_level:.4f}")
    print(f"  Corr(log h, log x):   {corr_log:.4f}")
    print(f"  Mean(h_t):             {h_t.mean():.6e}")
    print(f"  Mean(x_t):             {realized_var.mean():.6e}")
    print(f"  Ratio mean(h/x):       {(h_t / realized_var).mean():.4f}")
    print(f"  QLIKE(x_t | h_t):     {qlike_rg:.6f}")

    # MSE of log variance
    mse_log = np.mean((np.log(h_t) - np.log(realized_var)) ** 2)
    print(f"  MSE(log h - log x):   {mse_log:.6f}")

    # ---- Measurement residuals ----
    print_section("Measurement equation residuals u_t")

    u_t = model.get_measurement_residuals()
    print(f"  Mean:      {u_t.mean():.6f}  (should be ~0)")
    print(f"  Std:       {u_t.std():.6f}")
    print(f"  sigma_u:   {result['params']['sigma_u2']**0.5:.6f}  (estimated)")
    print(f"  Skewness:  {pd.Series(u_t).skew():.4f}")
    print(f"  Kurtosis:  {pd.Series(u_t).kurtosis():.4f}")

    # Ljung-Box test on u_t
    try:
        from statsmodels.stats.diagnostic import acorr_ljungbox
        lb = acorr_ljungbox(u_t, lags=5, return_df=True)
        print(f"\n  Ljung-Box test on u_t (lags=5):")
        for lag, row in lb.iterrows():
            sig = "***" if row["lb_pvalue"] < 0.01 else "**" if row["lb_pvalue"] < 0.05 else ""
            print(f"    Lag {lag}: Q={row['lb_stat']:.3f}, p={row['lb_pvalue']:.4f} {sig}")
    except ImportError:
        print("  (statsmodels not available for Ljung-Box test)")

    # ---- Forecast ----
    print_section("Forecasts")

    fc1 = model.forecast(horizon=1)
    print(f"  1-day ahead:")
    print(f"    h_{{T+1}}:    {fc1.variance_forecast:.6e}")
    print(f"    vol_{{T+1}}:  {fc1.point_forecast:.6f}")
    print(f"    ann. vol:  {fc1.point_forecast * 252**0.5:.2%}")

    fc5 = model.forecast(horizon=5)
    print(f"  5-day ahead:")
    print(f"    h_{{T+5}}:    {fc5.variance_forecast:.6e}")
    print(f"    vol_{{T+5}}:  {fc5.point_forecast:.6f}")
    print(f"    ann. vol:  {fc5.point_forecast * 252**0.5:.2%}")

    # ---- GJR-GARCH comparison ----
    print_section("Comparison with GJR-GARCH")

    try:
        from arch import arch_model

        ret_pct = returns * 100
        gjr = arch_model(
            ret_pct, vol="GARCH", p=1, o=1, q=1,
            dist="normal", mean="Zero", rescale=False,
        )
        gjr_res = gjr.fit(disp="off", show_warning=False)
        gjr_var = gjr_res.conditional_volatility ** 2 / 10000  # to decimal

        gjr_fc_var = gjr_res.forecast(horizon=1).variance.iloc[-1, 0] / 10000

        print(f"  GJR-GARCH parameters:")
        for k, v in gjr_res.params.items():
            print(f"    {k:10s} = {v:12.6f}")
        print(f"  GJR-GARCH log-lik: {gjr_res.loglikelihood:.4f}")

        qlike_gjr = np.mean(realized_var / gjr_var - np.log(realized_var / gjr_var) - 1)
        mse_gjr = np.mean((np.log(gjr_var) - np.log(realized_var)) ** 2)
        corr_gjr = np.corrcoef(gjr_var, realized_var)[0, 1]

        print(f"\n  {'Metric':<25s} {'RealizedGARCH':>15s} {'GJR-GARCH':>15s} {'Winner':>10s}")
        print(f"  {'-'*65}")

        winner_qlike = "R-GARCH" if qlike_rg < qlike_gjr else "GJR"
        print(f"  {'QLIKE':<25s} {qlike_rg:>15.6f} {qlike_gjr:>15.6f} {winner_qlike:>10s}")

        winner_mse = "R-GARCH" if mse_log < mse_gjr else "GJR"
        print(f"  {'MSE(log)':<25s} {mse_log:>15.6f} {mse_gjr:>15.6f} {winner_mse:>10s}")

        winner_corr = "R-GARCH" if corr_level > corr_gjr else "GJR"
        print(f"  {'Corr(h,x)':<25s} {corr_level:>15.4f} {corr_gjr:>15.4f} {winner_corr:>10s}")

        print(f"\n  Forecast h_{{T+1}}:")
        print(f"    Realized GARCH: {fc1.variance_forecast:.6e}  (vol: {fc1.point_forecast:.4%})")
        print(f"    GJR-GARCH:      {gjr_fc_var:.6e}  (vol: {gjr_fc_var**0.5:.4%})")

        # Cross-correlation
        corr_rg_gjr = np.corrcoef(h_t, gjr_var)[0, 1]
        print(f"\n  Corr(h_RG, h_GJR): {corr_rg_gjr:.4f}")

    except ImportError:
        print("  arch package not installed; skipping GJR comparison.")
    except Exception as e:
        print(f"  GJR comparison error: {e}")
        import traceback
        traceback.print_exc()

    # ---- Time series print ----
    print_section("Daily variance comparison (last 10 days)")
    print(f"  {'Date':>12s}  {'x_t (RV)':>12s}  {'h_t (RG)':>12s}  {'Ratio h/x':>10s}")
    for i in range(-min(10, len(dates)), 0):
        d = dates[i].strftime("%Y-%m-%d")
        x = realized_var[i]
        h = h_t[i]
        print(f"  {d}  {x:12.6e}  {h:12.6e}  {h/x:10.4f}")

    # ---- Summary ----
    print_section("Summary", "=")
    print(f"  Model:        Realized GARCH (Hansen, Huang & Shek, 2012)")
    print(f"  Data:         {len(common)} trading days of SPY")
    print(f"  Log-lik:      {result['loglik']:.4f}")
    print(f"  Persistence:  {persistence:.4f}")
    print(f"  QLIKE:        {qlike_rg:.6f}")
    print(f"  Corr(h,x):    {corr_level:.4f}")
    print(f"")
    print(f"  CAVEAT: {len(common)} days is far below the recommended 252+.")
    print(f"  Parameter estimates may be unreliable. This is a proof-of-concept.")
    print(f"  Full estimation expected ~2027 Q1 when 252+ days are available.")
    print(f"{'=' * 70}")


if __name__ == "__main__":
    main()
