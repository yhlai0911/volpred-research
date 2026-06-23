#!/usr/bin/env python3
"""K1542: municipal convenience-premium compression as a vol prior.

The experiment builds free-data ETF proxies for municipal-bond cheapening:
rolling SPY/IEF/AGG/LQD/HYG beta residuals, 21-day drawdown pressure, volume
spikes, and lagged FRED state/local tax-receipt stress. All predictive signals
are shifted by one trading day before being matched to forward outcomes.
"""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import requests
import statsmodels.api as sm
import yfinance as yf

from volpred.stats.model_evaluation import dm_test


ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
FIG = OUT / "figures"

EXPERIMENT_ID = "K1542"
SLUG = "k1542_muni_convenience_premium_tax_liquidity_stress"
SEED = 42

MUNI_TICKERS = ["MUB", "TFI", "HYD", "TAXF"]
CONTROL_TICKERS = ["IEF", "AGG", "LQD", "HYG", "SPY"]
STATE_TICKERS = ["^VIX"]
ALL_TICKERS = MUNI_TICKERS + CONTROL_TICKERS + STATE_TICKERS

START = "2007-01-01"
END = "2026-06-24"
BETA_LOOKBACK = 252
RV_HORIZON = 5
ROLL_Z = 252
OOS_MIN_TRAIN = 756
OOS_REFIT_STEP = 21

FRED_SERIES = {
    "state_local_tax_receipts": "W070RC1Q027SBEA",
    "state_local_tax_receipts_nsa": "NA000328Q",
    "stl_fsi": "STLFSI4",
    "nfci": "NFCI",
}


@dataclass
class RegressionResult:
    target: str
    family: str
    nobs: int
    beta: float
    hac_t: float
    p_value: float
    effect_per_1sd: float
    expected_sign: str
    raw_gate: bool
    bonferroni_p: float | None = None
    bh_q: float | None = None
    gate_pass: bool = False


@dataclass
class OOSResult:
    target: str
    family: str
    nobs: int
    baseline_mse: float
    augmented_mse: float
    mse_improvement_pct: float
    dm_t: float
    dm_p: float
    gate_pass: bool


def download_yfinance() -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    raw = yf.download(
        ALL_TICKERS,
        start=START,
        end=END,
        auto_adjust=True,
        progress=False,
        group_by="ticker",
        threads=True,
    )
    if raw.empty:
        raise RuntimeError("yfinance returned empty panel")

    close: dict[str, pd.Series] = {}
    volume: dict[str, pd.Series] = {}
    availability: dict[str, Any] = {}
    for ticker in ALL_TICKERS:
        if isinstance(raw.columns, pd.MultiIndex) and ticker in raw.columns.get_level_values(0):
            sub = raw[ticker].copy()
        else:
            availability[ticker] = {"available": False, "reason": "missing from yfinance response"}
            continue
        c = sub["Close"].dropna()
        if c.empty:
            availability[ticker] = {"available": False, "reason": "empty adjusted close"}
            continue
        close[ticker] = sub["Close"]
        volume[ticker] = sub["Volume"] if "Volume" in sub else pd.Series(index=sub.index, dtype=float)
        availability[ticker] = {
            "available": True,
            "n_close": int(len(c)),
            "start": str(pd.to_datetime(c.index.min()).date()),
            "end": str(pd.to_datetime(c.index.max()).date()),
        }

    close_df = pd.DataFrame(close).sort_index()
    volume_df = pd.DataFrame(volume).sort_index()
    close_df.index = pd.to_datetime(close_df.index).tz_localize(None)
    volume_df.index = pd.to_datetime(volume_df.index).tz_localize(None)
    return close_df, volume_df, availability


def fred_csv(series_id: str) -> pd.Series:
    url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"
    response = requests.get(url, timeout=45)
    response.raise_for_status()
    rows = []
    for line in response.text.strip().splitlines()[1:]:
        date_s, value_s = line.split(",", 1)
        if value_s in {"", "."}:
            continue
        rows.append((pd.Timestamp(date_s), float(value_s)))
    return pd.Series(dict(rows), name=series_id).sort_index()


def load_fred_features(daily_index: pd.DatetimeIndex) -> tuple[pd.DataFrame, dict[str, Any]]:
    raw = {name: fred_csv(series_id) for name, series_id in FRED_SERIES.items()}
    quarterly = pd.DataFrame(
        {
            "tax_receipts_sa": raw["state_local_tax_receipts"],
            "tax_receipts_nsa": raw["state_local_tax_receipts_nsa"],
        }
    ).sort_index()
    quarterly["tax_receipts_yoy"] = quarterly["tax_receipts_sa"].pct_change(4)
    # Conservative publication lag: a daily date sees only the previous
    # quarterly observation, not the quarter stamped at the same date.
    quarterly["fiscal_stress_lag"] = (-quarterly["tax_receipts_yoy"]).shift(1)

    weekly = pd.DataFrame({"stl_fsi": raw["stl_fsi"], "nfci": raw["nfci"]}).sort_index()
    weekly["stl_fsi_lag"] = weekly["stl_fsi"].shift(1)
    weekly["nfci_lag"] = weekly["nfci"].shift(1)

    daily = pd.DataFrame(index=daily_index)
    daily = daily.join(quarterly[["fiscal_stress_lag"]].reindex(daily_index, method="ffill"))
    daily = daily.join(weekly[["stl_fsi_lag", "nfci_lag"]].reindex(daily_index, method="ffill"))
    meta = {
        "series": FRED_SERIES,
        "state_local_tax_receipts_span": [
            str(raw["state_local_tax_receipts"].index.min().date()),
            str(raw["state_local_tax_receipts"].index.max().date()),
        ],
        "stl_fsi_span": [str(raw["stl_fsi"].index.min().date()), str(raw["stl_fsi"].index.max().date())],
        "lag_policy": "quarterly tax-receipt YoY and weekly financial-stress observations are shifted one release stamp before daily forward fill",
    }
    return daily, meta


def rolling_beta_residuals(
    returns: pd.DataFrame,
    asset: str,
    factors: list[str],
    lookback: int = BETA_LOOKBACK,
) -> tuple[pd.Series, pd.DataFrame]:
    data = returns[[asset, *factors]].dropna()
    y_all = data[asset].to_numpy(dtype=float)
    x_all = data[factors].to_numpy(dtype=float)
    resid = pd.Series(np.nan, index=data.index, name=f"{asset}_beta_resid")
    betas = pd.DataFrame(np.nan, index=data.index, columns=[f"{asset}_beta_{f}" for f in factors])
    for i in range(lookback, len(data)):
        y = y_all[i - lookback : i]
        x = x_all[i - lookback : i]
        valid = np.isfinite(y) & np.all(np.isfinite(x), axis=1)
        if valid.sum() < int(0.8 * lookback):
            continue
        beta = np.linalg.lstsq(x[valid], y[valid], rcond=None)[0]
        betas.iloc[i] = beta
        resid.iloc[i] = float(y_all[i] - x_all[i] @ beta)
    return resid, betas


def rolling_z(series: pd.Series, window: int = ROLL_Z, min_periods: int = 126) -> pd.Series:
    mean = series.rolling(window, min_periods=min_periods).mean()
    std = series.rolling(window, min_periods=min_periods).std()
    return (series - mean) / std


def forward_rv(ret: pd.Series, horizon: int = RV_HORIZON) -> pd.Series:
    acc = sum(ret.shift(-i).pow(2) for i in range(horizon))
    return np.sqrt(acc * 252.0 / horizon)


def forward_drawdown(ret: pd.Series, horizon: int = RV_HORIZON) -> pd.Series:
    paths = pd.concat([sum(ret.shift(-j) for j in range(i + 1)) for i in range(horizon)], axis=1)
    return (-paths.min(axis=1)).clip(lower=0.0)


def forward_corr(a: pd.Series, b: pd.Series, horizon: int = 21) -> pd.Series:
    out = pd.Series(np.nan, index=a.index, name="spy_ief_fwd_corr21")
    av = a.to_numpy(dtype=float)
    bv = b.to_numpy(dtype=float)
    for i in range(0, len(out) - horizon + 1):
        x = av[i : i + horizon]
        y = bv[i : i + horizon]
        valid = np.isfinite(x) & np.isfinite(y)
        if valid.sum() >= 15 and np.std(x[valid]) > 0 and np.std(y[valid]) > 0:
            out.iloc[i] = float(np.corrcoef(x[valid], y[valid])[0, 1])
    return out


def build_panel(close: pd.DataFrame, volume: pd.DataFrame, fred: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
    returns = close.pct_change(fill_method=None)
    factors = ["IEF", "AGG", "LQD", "HYG", "SPY"]
    panel = pd.DataFrame(index=close.index)
    beta_summaries: dict[str, Any] = {}
    resid_z_cols: list[str] = []
    dd_z_cols: list[str] = []
    volume_z_cols: list[str] = []

    for ticker in MUNI_TICKERS:
        if ticker not in returns.columns or returns[ticker].dropna().shape[0] < BETA_LOOKBACK + 252:
            continue
        resid, betas = rolling_beta_residuals(returns, ticker, factors)
        panel[f"{ticker}_ret"] = returns[ticker]
        panel[f"{ticker}_beta_resid"] = resid
        # Negative residual means muni ETF underperformed taxable beta basket:
        # cheapening / convenience-premium compression proxy.
        panel[f"{ticker}_cheapening_z"] = rolling_z(-resid).shift(1)
        resid_z_cols.append(f"{ticker}_cheapening_z")

        dd21 = close[ticker] / close[ticker].rolling(21, min_periods=15).max() - 1.0
        panel[f"{ticker}_drawdown_stress_z"] = rolling_z(-dd21).shift(1)
        dd_z_cols.append(f"{ticker}_drawdown_stress_z")

        vol_log = np.log1p(volume[ticker])
        panel[f"{ticker}_volume_spike_z"] = rolling_z(vol_log).shift(1)
        volume_z_cols.append(f"{ticker}_volume_spike_z")

        panel[f"{ticker}_fwd_rv5"] = forward_rv(returns[ticker])
        panel[f"{ticker}_fwd_drawdown5"] = forward_drawdown(returns[ticker])
        beta_summaries[ticker] = betas.describe(percentiles=[0.1, 0.5, 0.9]).to_dict()

    for ticker in CONTROL_TICKERS + STATE_TICKERS:
        panel[f"{ticker}_ret"] = returns[ticker]
    for ticker in ["LQD", "HYG", "AGG", "IEF"]:
        panel[f"{ticker}_fwd_rv5"] = forward_rv(returns[ticker])
    panel["HYG_LQD_fwd_spread_drawdown5"] = forward_drawdown(returns["HYG"] - returns["LQD"])
    panel["spy_ief_fwd_corr21"] = forward_corr(returns["SPY"], returns["IEF"])

    panel["muni_cheapening_z_lag"] = panel[resid_z_cols].mean(axis=1)
    panel["muni_drawdown_z_lag"] = panel[dd_z_cols].mean(axis=1)
    panel["muni_volume_z_lag"] = panel[volume_z_cols].mean(axis=1)
    panel = panel.join(fred)
    panel["fiscal_stress_z_lag"] = rolling_z(panel["fiscal_stress_lag"], min_periods=36).shift(1)
    panel["stl_fsi_z_lag"] = rolling_z(panel["stl_fsi_lag"], min_periods=52).shift(1)
    panel["nfci_z_lag"] = rolling_z(panel["nfci_lag"], min_periods=52).shift(1)
    stress_components = [
        "muni_cheapening_z_lag",
        "muni_drawdown_z_lag",
        "muni_volume_z_lag",
        "fiscal_stress_z_lag",
        "stl_fsi_z_lag",
    ]
    panel["tax_liquidity_stress_lag"] = panel[stress_components].mean(axis=1)

    panel["SPY_rv21_lag"] = np.sqrt(returns["SPY"].pow(2).rolling(21, min_periods=15).sum() * 252 / 21).shift(1)
    panel["IEF_rv21_lag"] = np.sqrt(returns["IEF"].pow(2).rolling(21, min_periods=15).sum() * 252 / 21).shift(1)
    panel["HYG_rv21_lag"] = np.sqrt(returns["HYG"].pow(2).rolling(21, min_periods=15).sum() * 252 / 21).shift(1)
    panel["log_vix_lag"] = np.log(close["^VIX"]).shift(1)

    meta = {
        "beta_factors": factors,
        "stress_components": stress_components,
        "beta_summaries": beta_summaries,
        "lookahead_policy": "muni cheapening/drawdown/volume/FRED stress components are lagged before forward RV/corr targets",
    }
    return panel, meta


def hac_regression(
    panel: pd.DataFrame,
    target: str,
    family: str,
    controls: list[str],
    expected_sign: str = "positive",
) -> RegressionResult:
    cols = [target, "tax_liquidity_stress_lag", *controls]
    data = panel[cols].replace([np.inf, -np.inf], np.nan).dropna()
    y = data[target]
    x = sm.add_constant(data[["tax_liquidity_stress_lag", *controls]], has_constant="add")
    fit = sm.OLS(y, x).fit(cov_type="HAC", cov_kwds={"maxlags": 5})
    beta = float(fit.params["tax_liquidity_stress_lag"])
    tval = float(fit.tvalues["tax_liquidity_stress_lag"])
    pval = float(fit.pvalues["tax_liquidity_stress_lag"])
    sd = float(data["tax_liquidity_stress_lag"].std())
    raw_gate = tval >= 3.0 if expected_sign == "positive" else tval <= -3.0
    return RegressionResult(
        target=target,
        family=family,
        nobs=int(fit.nobs),
        beta=beta,
        hac_t=tval,
        p_value=pval,
        effect_per_1sd=float(beta * sd),
        expected_sign=expected_sign,
        raw_gate=bool(raw_gate),
    )


def add_multiple_testing(results: list[RegressionResult]) -> None:
    pvals = np.array([r.p_value for r in results], dtype=float)
    m = len(results)
    order = np.argsort(pvals)
    qvals = np.empty(m)
    prev = 1.0
    for rank_from_end, idx in enumerate(order[::-1], start=1):
        rank = m - rank_from_end + 1
        q = min(prev, pvals[idx] * m / rank)
        qvals[idx] = q
        prev = q
    for i, r in enumerate(results):
        r.bonferroni_p = float(min(1.0, pvals[i] * m))
        r.bh_q = float(min(1.0, qvals[i]))
        sign_ok = r.hac_t >= 3.0 if r.expected_sign == "positive" else r.hac_t <= -3.0
        r.gate_pass = bool(sign_ok and r.bonferroni_p < 0.05)


def expanding_oos(
    panel: pd.DataFrame,
    target: str,
    family: str,
    controls: list[str],
) -> OOSResult:
    cols = [target, "tax_liquidity_stress_lag", *controls]
    data = panel[cols].replace([np.inf, -np.inf], np.nan).dropna()
    y = data[target].to_numpy(dtype=float)
    xb = np.column_stack([np.ones(len(data)), data[controls].to_numpy(dtype=float)])
    xa = np.column_stack([np.ones(len(data)), data[["tax_liquidity_stress_lag", *controls]].to_numpy(dtype=float)])

    actual: list[float] = []
    base_pred: list[float] = []
    aug_pred: list[float] = []
    beta_b: np.ndarray | None = None
    beta_a: np.ndarray | None = None
    for i in range(OOS_MIN_TRAIN, len(data)):
        if beta_b is None or (i - OOS_MIN_TRAIN) % OOS_REFIT_STEP == 0:
            beta_b = np.linalg.lstsq(xb[:i], y[:i], rcond=None)[0]
            beta_a = np.linalg.lstsq(xa[:i], y[:i], rcond=None)[0]
        assert beta_b is not None and beta_a is not None
        actual.append(float(y[i]))
        base_pred.append(float(xb[i] @ beta_b))
        aug_pred.append(float(xa[i] @ beta_a))

    actual_arr = np.asarray(actual)
    base_arr = np.asarray(base_pred)
    aug_arr = np.asarray(aug_pred)
    base_loss = (actual_arr - base_arr) ** 2
    aug_loss = (actual_arr - aug_arr) ** 2
    baseline_mse = float(np.mean(base_loss))
    augmented_mse = float(np.mean(aug_loss))
    improvement = 100.0 * (baseline_mse - augmented_mse) / baseline_mse
    tval, pval = dm_test(aug_loss, base_loss, h=RV_HORIZON)
    return OOSResult(
        target=target,
        family=family,
        nobs=int(len(actual_arr)),
        baseline_mse=baseline_mse,
        augmented_mse=augmented_mse,
        mse_improvement_pct=float(improvement),
        dm_t=float(tval),
        dm_p=float(pval),
        gate_pass=bool(tval <= -3.0 and improvement > 0),
    )


def make_figures(panel: pd.DataFrame, regs: list[RegressionResult], oos: list[OOSResult]) -> list[str]:
    FIG.mkdir(exist_ok=True)
    paths: list[str] = []

    fig, ax = plt.subplots(figsize=(11, 4.8))
    panel[["muni_cheapening_z_lag", "muni_drawdown_z_lag", "muni_volume_z_lag", "tax_liquidity_stress_lag"]].dropna().rolling(21).mean().plot(ax=ax)
    ax.set_title("K1542: lagged muni tax-liquidity stress components")
    ax.set_ylabel("z-score / composite")
    ax.grid(alpha=0.25)
    fig.tight_layout()
    path = FIG / "k1542_stress_components.png"
    fig.savefig(path, dpi=160)
    plt.close(fig)
    paths.append(str(path.relative_to(ROOT)))

    reg_df = pd.DataFrame([asdict(r) for r in regs])
    reg_df = reg_df.sort_values("hac_t")
    fig, ax = plt.subplots(figsize=(11, 6))
    colors = ["#2E6F9E" if v >= 0 else "#B45F5F" for v in reg_df["hac_t"]]
    ax.barh(reg_df["target"], reg_df["hac_t"], color=colors)
    ax.axvline(3.0, color="#333333", linestyle="--", linewidth=1)
    ax.axvline(-3.0, color="#333333", linestyle="--", linewidth=1)
    ax.set_title("K1542: HAC t-stat on lagged tax-liquidity stress")
    ax.set_xlabel("HAC t-stat")
    ax.grid(axis="x", alpha=0.25)
    fig.tight_layout()
    path = FIG / "k1542_regression_tstats.png"
    fig.savefig(path, dpi=160)
    plt.close(fig)
    paths.append(str(path.relative_to(ROOT)))

    oos_df = pd.DataFrame([asdict(r) for r in oos]).sort_values("mse_improvement_pct")
    fig, ax = plt.subplots(figsize=(11, 6))
    colors = ["#2F7D4F" if v > 0 else "#B45F5F" for v in oos_df["mse_improvement_pct"]]
    ax.barh(oos_df["target"], oos_df["mse_improvement_pct"], color=colors)
    ax.axvline(0.0, color="#333333", linewidth=1)
    ax.set_title("K1542: OOS MSE improvement from adding stress proxy")
    ax.set_xlabel("MSE improvement vs controls-only (%)")
    ax.grid(axis="x", alpha=0.25)
    fig.tight_layout()
    path = FIG / "k1542_oos_mse_improvement.png"
    fig.savefig(path, dpi=160)
    plt.close(fig)
    paths.append(str(path.relative_to(ROOT)))

    fig, ax = plt.subplots(figsize=(11, 4.8))
    aligned = panel[["tax_liquidity_stress_lag", "MUB_fwd_rv5", "HYG_fwd_rv5", "spy_ief_fwd_corr21"]].dropna()
    if not aligned.empty:
        stress_q = pd.qcut(aligned["tax_liquidity_stress_lag"], 5, labels=False, duplicates="drop")
        bucket = aligned.groupby(stress_q).agg(
            MUB_fwd_rv5=("MUB_fwd_rv5", "mean"),
            HYG_fwd_rv5=("HYG_fwd_rv5", "mean"),
            spy_ief_fwd_corr21=("spy_ief_fwd_corr21", "mean"),
        )
        bucket.plot(ax=ax, marker="o")
    ax.set_title("K1542: forward outcomes by stress quintile")
    ax.set_xlabel("tax-liquidity stress quintile")
    ax.grid(alpha=0.25)
    fig.tight_layout()
    path = FIG / "k1542_stress_quintiles.png"
    fig.savefig(path, dpi=160)
    plt.close(fig)
    paths.append(str(path.relative_to(ROOT)))
    return paths


def main() -> None:
    np.random.seed(SEED)
    close, volume, availability = download_yfinance()
    fred, fred_meta = load_fred_features(close.index)
    panel, panel_meta = build_panel(close, volume, fred)

    controls = ["SPY_rv21_lag", "IEF_rv21_lag", "HYG_rv21_lag", "log_vix_lag", "stl_fsi_z_lag"]
    targets: list[tuple[str, str, str]] = []
    for ticker in MUNI_TICKERS:
        if f"{ticker}_fwd_rv5" in panel.columns and panel[f"{ticker}_fwd_rv5"].notna().sum() > OOS_MIN_TRAIN + 252:
            targets.append((f"{ticker}_fwd_rv5", "muni_rv5", "positive"))
            targets.append((f"{ticker}_fwd_drawdown5", "muni_drawdown5", "positive"))
    for ticker in ["LQD", "HYG", "AGG", "IEF"]:
        targets.append((f"{ticker}_fwd_rv5", "cross_asset_rv5", "positive"))
    targets.append(("HYG_LQD_fwd_spread_drawdown5", "credit_spread_drawdown5", "positive"))
    targets.append(("spy_ief_fwd_corr21", "stock_bond_corr21", "positive"))

    regs = [hac_regression(panel, target, family, controls, expected) for target, family, expected in targets]
    add_multiple_testing(regs)
    oos = [expanding_oos(panel, target, family, controls) for target, family, _ in targets]
    figures = make_figures(panel, regs, oos)

    panel_path = OUT / f"{SLUG}_daily_panel.csv"
    keep = [
        "tax_liquidity_stress_lag",
        "muni_cheapening_z_lag",
        "muni_drawdown_z_lag",
        "muni_volume_z_lag",
        "fiscal_stress_z_lag",
        "stl_fsi_z_lag",
        "nfci_z_lag",
        *[f"{ticker}_fwd_rv5" for ticker in MUNI_TICKERS if f"{ticker}_fwd_rv5" in panel.columns],
        "LQD_fwd_rv5",
        "HYG_fwd_rv5",
        "HYG_LQD_fwd_spread_drawdown5",
        "spy_ief_fwd_corr21",
    ]
    panel[keep].to_csv(panel_path, index_label="date")

    best_reg = sorted(regs, key=lambda r: abs(r.hac_t), reverse=True)[0]
    best_oos = sorted(oos, key=lambda r: r.mse_improvement_pct, reverse=True)[0]
    in_sample_pass = [r for r in regs if r.gate_pass]
    oos_pass = [r for r in oos if r.gate_pass]
    if in_sample_pass and oos_pass:
        verdict = "MUNI_STRESS_PRIOR_PASS"
    elif in_sample_pass or oos_pass:
        verdict = "WEAK_DIAGNOSTIC_ONLY"
    else:
        verdict = "NULL_MUNI_TAX_LIQUIDITY_VOL_PRIOR"

    results = {
        "experiment_id": EXPERIMENT_ID,
        "slug": SLUG,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "random_seed": SEED,
        "verdict": verdict,
        "data": {
            "price_source": "yfinance adjusted daily close via yf.download(auto_adjust=True)",
            "requested_start": START,
            "requested_end": END,
            "availability": availability,
            "fred": fred_meta,
            "effective_panel_start": str(panel.dropna(subset=["tax_liquidity_stress_lag"]).index.min().date()),
            "effective_panel_end": str(panel.dropna(subset=["tax_liquidity_stress_lag"]).index.max().date()),
            "daily_panel_rows": int(len(panel)),
        },
        "method": {
            "proxy_definition": "muni convenience-premium compression is proxied by beta-residual cheapening, 21d drawdown, volume spike, lagged state/local tax-receipt stress, and STLFSI",
            "target_variables": targets,
            "controls": controls,
            "lookahead_policy": panel_meta["lookahead_policy"],
            "formal_gate": "Harvey-style HAC t >= 3 plus Bonferroni p < 0.05 in sample; OOS requires MSE improvement > 0 and DM t <= -3",
            "caveat": "ETF proxy does not identify bond-level convenience premium; it tests whether a free daily proxy has forecast content.",
        },
        "panel_meta": panel_meta,
        "regressions": [asdict(r) for r in regs],
        "oos": [asdict(r) for r in oos],
        "summary": {
            "in_sample_gate_pass": [asdict(r) for r in in_sample_pass],
            "oos_gate_pass": [asdict(r) for r in oos_pass],
            "best_abs_hac": asdict(best_reg),
            "best_oos_improvement": asdict(best_oos),
            "interpretation": (
                "The ETF/FRED proxy must pass formal gates before it can be treated as a cross-asset vol prior. "
                "Directional t-stats or stress-quintile patterns alone are diagnostics, not publishable claims."
            ),
        },
        "outputs": {
            "daily_panel": str(panel_path.relative_to(ROOT)),
            "figures": figures,
        },
        "limitations": [
            "ETF returns are proxies for broad muni portfolios, not bond-level tax-exempt convenience premia.",
            "State/local tax receipts are quarterly and lagged, so they cannot explain high-frequency daily moves alone.",
            "Volume is ETF volume, not underlying municipal bond trading volume.",
            "The stock-bond correlation target is an ex-post 21-day forward realized correlation, used only as a predictive target.",
        ],
    }
    out_path = OUT / f"{SLUG}_results.json"
    out_path.write_text(json.dumps(results, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"ok": True, "verdict": verdict, "results": str(out_path)}, indent=2))


if __name__ == "__main__":
    main()
