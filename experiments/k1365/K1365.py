#!/usr/bin/env python3
"""K1365: same-index ETF liquidity-clientele concentration as a vol proxy.

Question
--------
Within ETF families tracking the same broad index, does short-run secondary
market liquidity concentrating in the legacy high-turnover ETF predict higher
next-day / forward realized volatility or within-family tracking dispersion?

This is a free-data proxy experiment. It uses yfinance OHLCV only, so it does
not claim to measure true ETF NAV premiums/discounts, creations/redemptions,
historical AUM, or investor-level clientele. The "premium-discount proxy" is
therefore replaced by same-index ETF return dispersion.

Lookahead protection
--------------------
Every liquidity signal is trailing/rolling and then uses `signal.shift(1)`.
The target at date t is next trading-day information relative to the signal
formed at t-1 close. Forward 5-day targets are evaluated with HAC maxlags=5.
"""

from __future__ import annotations

import argparse
import json
import math
import warnings
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import statsmodels.api as sm
import yfinance as yf

warnings.filterwarnings("ignore", category=FutureWarning)


HERE = Path(__file__).resolve().parent
DATA_DIR = HERE / "data"
RAW_DIR = DATA_DIR / "raw"
FIG_DIR = HERE / "figures"
for directory in (DATA_DIR, RAW_DIR, FIG_DIR):
    directory.mkdir(parents=True, exist_ok=True)

EXPERIMENT_ID = "K1365"
SEED = 42
np.random.seed(SEED)

START = "2010-01-01"
END = "2026-06-23"
ROLL_Z = 63
HAC_LAGS = 5
ANNUALIZER = float(np.sqrt(252.0))
EPS = 1e-10
HARVEY_T = 3.0

ETF_GROUPS: "OrderedDict[str, dict[str, Any]]" = OrderedDict(
    [
        (
            "sp500",
            {
                "label": "S&P 500 same-index ETFs",
                "tickers": ["SPY", "IVV", "VOO"],
                "leader": "SPY",
                "primary": "SPY",
            },
        ),
        (
            "nasdaq100",
            {
                "label": "Nasdaq-100 same-index ETFs",
                "tickers": ["QQQ", "QQQM"],
                "leader": "QQQ",
                "primary": "QQQ",
            },
        ),
        (
            "russell2000",
            {
                "label": "Russell 2000 same-index ETFs",
                "tickers": ["IWM", "VTWO"],
                "leader": "IWM",
                "primary": "IWM",
            },
        ),
        (
            "em",
            {
                "label": "Emerging-market same-index ETF pair",
                "tickers": ["EEM", "IEMG"],
                "leader": "EEM",
                "primary": "EEM",
            },
        ),
    ]
)

LITERATURE = [
    {
        "citation": "Khomyn, Putnins, and Zoican (2024), The Value of ETF Liquidity, Review of Financial Studies 37(10), 3092-3148",
        "url": "https://academic.oup.com/rfs/article/37/10/3092/7738093",
        "role": "same-index ETF liquidity clienteles; high-liquidity ETFs can sustain fee premia and short-horizon investors",
    },
    {
        "citation": "Ben-David, Franzoni, and Moussawi (2018), Do ETFs Increase Volatility?, Journal of Finance 73(6), 2471-2535",
        "url": "https://onlinelibrary.wiley.com/doi/abs/10.1111/jofi.12727",
        "role": "ETF trading can transmit liquidity/noise-trader shocks into volatility of linked securities",
    },
    {
        "citation": "Agarwal, Hanouna, Moussawi, and Stahel (2018/2021), Do ETFs Increase the Commonality in Liquidity of Underlying Stocks?",
        "url": "https://papers.ssrn.com/sol3/papers.cfm?abstract_id=3001524",
        "role": "ETF ownership and arbitrage activity can increase liquidity commonality",
    },
    {
        "citation": "Box, Davis, Evans, and Lynch (2021), Intraday Arbitrage Between ETFs and Their Underlying Portfolios, Journal of Financial Economics 141(3), 1078-1095",
        "url": "https://ideas.repec.org/a/eee/jfinec/v141y2021i3p1078-1095.html",
        "role": "ETF arbitrage and market-quality channel motivating within-family tracking-dispersion diagnostics",
    },
]


@dataclass
class GroupPanel:
    group: str
    label: str
    tickers: list[str]
    leader: str
    primary: str
    panel: pd.DataFrame
    signals: pd.DataFrame
    targets: pd.DataFrame


def _json_default(obj: Any) -> Any:
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        value = float(obj)
        return None if not math.isfinite(value) else value
    if isinstance(obj, (np.ndarray,)):
        return obj.tolist()
    if isinstance(obj, (pd.Timestamp,)):
        return obj.isoformat()
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")


def _clean_float(value: Any) -> float | None:
    try:
        fval = float(value)
    except (TypeError, ValueError):
        return None
    return fval if math.isfinite(fval) else None


def rolling_zscore(series: pd.Series, window: int = ROLL_Z) -> pd.Series:
    mean = series.rolling(window, min_periods=window).mean()
    std = series.rolling(window, min_periods=window).std()
    return (series - mean) / std.replace(0.0, np.nan)


def _extract_ticker_frame(downloaded: pd.DataFrame, ticker: str) -> pd.DataFrame:
    if isinstance(downloaded.columns, pd.MultiIndex):
        if ticker in downloaded.columns.get_level_values(0):
            block = downloaded[ticker].copy()
        elif ticker in downloaded.columns.get_level_values(1):
            block = downloaded.xs(ticker, level=1, axis=1).copy()
        else:
            return pd.DataFrame()
    else:
        block = downloaded.copy()

    cols = {}
    for col in ["Open", "High", "Low", "Close", "Volume"]:
        if col in block.columns:
            cols[col] = block[col]
    if set(cols) != {"Open", "High", "Low", "Close", "Volume"}:
        return pd.DataFrame()
    out = pd.DataFrame(cols).sort_index()
    out.index = pd.to_datetime(out.index).tz_localize(None)
    out = out.dropna(subset=["Close", "Volume"])
    out = out.loc[out["Volume"] > 0]
    return out


def fetch_ohlcv(refresh: bool = False) -> dict[str, pd.DataFrame]:
    tickers = sorted({t for spec in ETF_GROUPS.values() for t in spec["tickers"]})
    cached = {
        ticker: RAW_DIR / f"{ticker}_{START}_{END}_ohlcv.csv"
        for ticker in tickers
    }

    if not refresh and all(path.exists() for path in cached.values()):
        frames = {}
        for ticker, path in cached.items():
            df = pd.read_csv(path, parse_dates=["Date"], index_col="Date")
            frames[ticker] = df.sort_index()
        return frames

    print(f"[fetch] yfinance {tickers} {START} -> {END}")
    downloaded = yf.download(
        tickers,
        start=START,
        end=END,
        auto_adjust=True,
        progress=False,
        threads=True,
        group_by="ticker",
    )

    frames: dict[str, pd.DataFrame] = {}
    for ticker, path in cached.items():
        frame = _extract_ticker_frame(downloaded, ticker)
        if frame.empty:
            print(f"[warn] no usable OHLCV for {ticker}")
            continue
        frame.to_csv(path, index_label="Date")
        frames[ticker] = frame
        print(
            f"[cache] {ticker}: {len(frame)} rows "
            f"{frame.index.min().date()}..{frame.index.max().date()} -> {path.relative_to(HERE)}"
        )
    return frames


def build_group_panel(group: str, spec: dict[str, Any], frames: dict[str, pd.DataFrame]) -> GroupPanel:
    tickers = [t for t in spec["tickers"] if t in frames]
    missing = sorted(set(spec["tickers"]) - set(tickers))
    if missing:
        raise RuntimeError(f"{group}: missing tickers {missing}")

    close = pd.DataFrame({t: frames[t]["Close"] for t in tickers}).dropna()
    high = pd.DataFrame({t: frames[t]["High"] for t in tickers}).reindex(close.index).dropna()
    low = pd.DataFrame({t: frames[t]["Low"] for t in tickers}).reindex(close.index).dropna()
    volume = pd.DataFrame({t: frames[t]["Volume"] for t in tickers}).reindex(close.index).dropna()
    common_index = close.index.intersection(high.index).intersection(low.index).intersection(volume.index)
    close = close.loc[common_index]
    high = high.loc[common_index]
    low = low.loc[common_index]
    volume = volume.loc[common_index]

    returns = np.log(close).diff()
    dollar_volume = close * volume
    total_dollar_volume = dollar_volume.sum(axis=1)
    volume_share = dollar_volume.div(total_dollar_volume.replace(0, np.nan), axis=0)

    hhi = (volume_share ** 2).sum(axis=1)
    leader = spec["leader"]
    primary = spec["primary"]
    leader_share = volume_share[leader]
    fragmentation = 1.0 - hhi
    entropy = (-(volume_share * np.log(volume_share.replace(0.0, np.nan))).sum(axis=1)
               / np.log(float(len(tickers))))
    total_volume_z = rolling_zscore(np.log(total_dollar_volume.replace(0, np.nan)))

    signals = pd.DataFrame(
        {
            # This exact shift is the lookahead guard required by project rules.
            "hhi_z_l1": rolling_zscore(hhi).shift(1),
            "leader_share_z_l1": rolling_zscore(leader_share).shift(1),
            "fragmentation_z_l1": rolling_zscore(fragmentation).shift(1),
            "entropy_z_l1": rolling_zscore(entropy).shift(1),
            "total_dollar_volume_z_l1": total_volume_z.shift(1),
        },
        index=common_index,
    )

    primary_ret = returns[primary]
    primary_range = np.log(high[primary] / low[primary]).replace([np.inf, -np.inf], np.nan)
    pair_dispersion = returns.std(axis=1)
    pair_tracking_range = returns.max(axis=1) - returns.min(axis=1)
    targets = pd.DataFrame(
        {
            "next_abs_return": primary_ret.abs(),
            "next_squared_return": primary_ret.pow(2.0),
            "next_range_vol": primary_range,
            "forward5_rv": primary_ret.rolling(5).std().shift(-4) * ANNUALIZER,
            "same_index_return_dispersion": pair_dispersion,
            "same_index_tracking_range": pair_tracking_range.abs(),
        },
        index=common_index,
    )

    panel = pd.concat(
        [
            hhi.rename("volume_hhi"),
            leader_share.rename("leader_volume_share"),
            fragmentation.rename("volume_fragmentation"),
            entropy.rename("volume_entropy"),
            total_dollar_volume.rename("total_dollar_volume"),
        ],
        axis=1,
    )

    return GroupPanel(
        group=group,
        label=spec["label"],
        tickers=tickers,
        leader=leader,
        primary=primary,
        panel=panel,
        signals=signals,
        targets=targets,
    )


def _zscore_in_sample(series: pd.Series) -> pd.Series:
    std = series.std(ddof=1)
    if not math.isfinite(float(std)) or std <= 0:
        return pd.Series(np.nan, index=series.index)
    return (series - series.mean()) / std


def hac_predictive_regression(
    gp: GroupPanel,
    signal_name: str,
    target_name: str,
) -> dict[str, Any]:
    raw = pd.DataFrame(
        {
            "target": gp.targets[target_name],
            "signal": gp.signals[signal_name],
            "target_lag1": gp.targets[target_name].shift(1),
            "total_volume": gp.signals["total_dollar_volume_z_l1"],
        }
    ).replace([np.inf, -np.inf], np.nan).dropna()

    raw = raw.loc[(raw["target"] > 0) & (raw["target_lag1"] > 0)].copy()
    if len(raw) < 252:
        return {
            "group": gp.group,
            "signal": signal_name,
            "target": target_name,
            "n_obs": int(len(raw)),
            "status": "insufficient",
        }

    # Positive targets are log-scaled to reduce tail leverage. Coefficients are
    # reported in standardized target units for comparability across groups.
    y_log = np.log(raw["target"].clip(lower=EPS))
    y_lag_log = np.log(raw["target_lag1"].clip(lower=EPS))
    design = pd.DataFrame(
        {
            "y": _zscore_in_sample(y_log),
            "signal": _zscore_in_sample(raw["signal"]),
            "target_lag1": _zscore_in_sample(y_lag_log),
            "total_volume": _zscore_in_sample(raw["total_volume"]),
        },
        index=raw.index,
    ).dropna()
    if len(design) < 252:
        return {
            "group": gp.group,
            "signal": signal_name,
            "target": target_name,
            "n_obs": int(len(design)),
            "status": "insufficient_after_standardization",
        }

    x = sm.add_constant(design[["signal", "target_lag1", "total_volume"]], has_constant="add")
    model = sm.OLS(design["y"], x).fit(cov_type="HAC", cov_kwds={"maxlags": HAC_LAGS})
    beta = float(model.params["signal"])
    t_val = float(model.tvalues["signal"])
    p_val = float(model.pvalues["signal"])
    return {
        "group": gp.group,
        "label": gp.label,
        "tickers": gp.tickers,
        "leader": gp.leader,
        "primary": gp.primary,
        "signal": signal_name,
        "target": target_name,
        "n_obs": int(model.nobs),
        "sample_start": str(design.index.min().date()),
        "sample_end": str(design.index.max().date()),
        "beta_signal_std": beta,
        "hac_t": t_val,
        "hac_p": p_val,
        "r2": float(model.rsquared),
        "target_mean_raw": float(raw.loc[design.index, "target"].mean()),
        "signal_mean_raw": float(raw.loc[design.index, "signal"].mean()),
        "status": "ok",
        "hac_maxlags": HAC_LAGS,
        "model": "z(log(target)) ~ z(signal_l1) + z(log(target_l1)) + z(total_dollar_volume_l1), OLS-HAC",
    }


def bh_fdr(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ok_rows = [r for r in rows if r.get("status") == "ok" and _clean_float(r.get("hac_p")) is not None]
    m = len(ok_rows)
    if m == 0:
        return rows
    order = sorted(range(m), key=lambda i: ok_rows[i]["hac_p"])
    adjusted = [float("nan")] * m
    running = 1.0
    for rank_from_end, idx in enumerate(reversed(order), start=1):
        rank = m - rank_from_end + 1
        pval = float(ok_rows[idx]["hac_p"])
        running = min(running, pval * m / rank)
        adjusted[idx] = running
    for row, qval in zip(ok_rows, adjusted):
        row["bh_q_all_regressions"] = float(min(qval, 1.0))
        row["harvey_abs_t_ge_3"] = bool(abs(float(row["hac_t"])) >= HARVEY_T)
        row["positive_harvey_t_ge_3"] = bool(float(row["hac_t"]) >= HARVEY_T)
    return rows


def summarize_group(gp: GroupPanel) -> dict[str, Any]:
    p = gp.panel.dropna()
    s = gp.signals.dropna(how="all")
    out = {
        "label": gp.label,
        "tickers": gp.tickers,
        "leader": gp.leader,
        "primary": gp.primary,
        "sample_start": str(p.index.min().date()) if len(p) else None,
        "sample_end": str(p.index.max().date()) if len(p) else None,
        "n_days_common_ohlcv": int(len(p)),
        "mean_volume_hhi": _clean_float(p["volume_hhi"].mean()),
        "median_volume_hhi": _clean_float(p["volume_hhi"].median()),
        "mean_leader_volume_share": _clean_float(p["leader_volume_share"].mean()),
        "median_leader_volume_share": _clean_float(p["leader_volume_share"].median()),
        "mean_volume_entropy": _clean_float(p["volume_entropy"].mean()),
        "signal_obs_after_lag": int(s.shape[0]),
    }
    return out


def concentration_quintiles(gp: GroupPanel) -> pd.DataFrame:
    signal = gp.signals["leader_share_z_l1"]
    target = gp.targets["forward5_rv"]
    df = pd.DataFrame({"signal": signal, "forward5_rv": target}).dropna()
    if len(df) < 252:
        return pd.DataFrame()
    df["quintile"] = pd.qcut(df["signal"], 5, labels=False, duplicates="drop") + 1
    return df.groupby("quintile", as_index=False)["forward5_rv"].mean()


def plot_t_heatmap(regression_rows: list[dict[str, Any]]) -> str:
    targets = [
        "next_abs_return",
        "next_range_vol",
        "forward5_rv",
        "same_index_return_dispersion",
        "same_index_tracking_range",
    ]
    groups = list(ETF_GROUPS.keys())
    mat = pd.DataFrame(index=groups, columns=targets, dtype=float)
    for row in regression_rows:
        if row.get("signal") != "leader_share_z_l1" or row.get("status") != "ok":
            continue
        mat.loc[row["group"], row["target"]] = row["hac_t"]

    fig, ax = plt.subplots(figsize=(11, 4.8))
    im = ax.imshow(mat.values.astype(float), cmap="coolwarm", vmin=-4, vmax=4, aspect="auto")
    ax.set_xticks(np.arange(len(targets)))
    ax.set_xticklabels(targets, rotation=25, ha="right")
    ax.set_yticks(np.arange(len(groups)))
    ax.set_yticklabels(groups)
    for i, group in enumerate(groups):
        for j, target in enumerate(targets):
            val = mat.loc[group, target]
            if pd.notna(val):
                ax.text(j, i, f"{val:+.2f}", ha="center", va="center", fontsize=9)
    ax.set_title("K1365 leader-share signal: HAC t-stat by group and target")
    cbar = fig.colorbar(im, ax=ax, shrink=0.82)
    cbar.set_label("HAC t-stat")
    fig.tight_layout()
    out = FIG_DIR / "leader_share_hac_t_heatmap.png"
    fig.savefig(out, dpi=140)
    plt.close(fig)
    return str(out.relative_to(HERE))


def plot_quintile_lines(group_panels: dict[str, GroupPanel]) -> str:
    fig, ax = plt.subplots(figsize=(9.5, 5.2))
    for group, gp in group_panels.items():
        q = concentration_quintiles(gp)
        if q.empty:
            continue
        ax.plot(q["quintile"], q["forward5_rv"], marker="o", label=group)
    ax.set_xlabel("Leader volume-share signal quintile (lagged)")
    ax.set_ylabel("Mean forward 5d realized vol (annualized)")
    ax.set_title("K1365 forward RV by lagged leader-share concentration quintile")
    ax.grid(True, alpha=0.3)
    ax.legend()
    fig.tight_layout()
    out = FIG_DIR / "forward5_rv_by_leader_share_quintile.png"
    fig.savefig(out, dpi=140)
    plt.close(fig)
    return str(out.relative_to(HERE))


def main(refresh: bool = False) -> dict[str, Any]:
    frames = fetch_ohlcv(refresh=refresh)
    group_panels = {
        group: build_group_panel(group, spec, frames)
        for group, spec in ETF_GROUPS.items()
    }

    signal_names = ["leader_share_z_l1", "hhi_z_l1", "fragmentation_z_l1", "entropy_z_l1"]
    target_names = [
        "next_abs_return",
        "next_squared_return",
        "next_range_vol",
        "forward5_rv",
        "same_index_return_dispersion",
        "same_index_tracking_range",
    ]

    regression_rows: list[dict[str, Any]] = []
    for gp in group_panels.values():
        for signal_name in signal_names:
            for target_name in target_names:
                regression_rows.append(hac_predictive_regression(gp, signal_name, target_name))
    regression_rows = bh_fdr(regression_rows)

    reg_table = pd.DataFrame(regression_rows)
    reg_table.to_csv(HERE / "K1365_regression_table.csv", index=False)

    primary_rows = [
        r for r in regression_rows
        if r.get("status") == "ok"
        and r.get("signal") == "leader_share_z_l1"
        and r.get("target") in {
            "next_range_vol",
            "forward5_rv",
            "same_index_return_dispersion",
            "same_index_tracking_range",
        }
    ]
    n_primary = len(primary_rows)
    n_positive = sum(1 for r in primary_rows if float(r.get("hac_t", 0.0)) > 0)
    n_harvey = sum(1 for r in primary_rows if r.get("positive_harvey_t_ge_3"))
    n_harvey_fdr = sum(
        1 for r in primary_rows
        if r.get("positive_harvey_t_ge_3")
        and _clean_float(r.get("bh_q_all_regressions")) is not None
        and float(r["bh_q_all_regressions"]) <= 0.05
    )
    n_negative_harvey_fdr = sum(
        1 for r in primary_rows
        if _clean_float(r.get("hac_t")) is not None
        and float(r["hac_t"]) <= -HARVEY_T
        and _clean_float(r.get("bh_q_all_regressions")) is not None
        and float(r["bh_q_all_regressions"]) <= 0.05
    )
    secondary_reverse_rows = [
        r for r in regression_rows
        if r.get("status") == "ok"
        and r.get("signal") in {"fragmentation_z_l1", "entropy_z_l1"}
        and r.get("target") in {"forward5_rv", "next_range_vol"}
        and _clean_float(r.get("hac_t")) is not None
        and float(r["hac_t"]) >= HARVEY_T
        and _clean_float(r.get("bh_q_all_regressions")) is not None
        and float(r["bh_q_all_regressions"]) <= 0.05
    ]

    figure_paths = [
        plot_t_heatmap(regression_rows),
        plot_quintile_lines(group_panels),
    ]

    group_summaries = {group: summarize_group(gp) for group, gp in group_panels.items()}
    top_positive = sorted(
        [
            r for r in regression_rows
            if r.get("status") == "ok" and _clean_float(r.get("hac_t")) is not None
        ],
        key=lambda row: float(row["hac_t"]),
        reverse=True,
    )[:10]

    if n_harvey_fdr >= 2:
        verdict = "PASS"
        verdict_reason = (
            f"{n_harvey_fdr}/{n_primary} primary leader-share tests have positive "
            f"HAC t>=3 and BH q<=0.05 across all regressions."
        )
    elif n_harvey >= 1:
        verdict = "CONDITIONAL_PASS"
        verdict_reason = (
            f"{n_harvey}/{n_primary} primary leader-share tests clear positive HAC t>=3, "
            f"but only {n_harvey_fdr} survive BH q<=0.05 across all regressions."
        )
    else:
        verdict = "NULL_PROXY"
        verdict_reason = (
            f"0/{n_primary} primary leader-share tests clear positive HAC t>=3. "
            f"Directional positives are {n_positive}/{n_primary}, insufficient for a claim."
        )
        if secondary_reverse_rows:
            verdict_reason += (
                f" Secondary fragmentation/entropy diagnostics have "
                f"{len(secondary_reverse_rows)} positive Harvey+BH hits, so the useful "
                f"follow-up is reverse fragmentation stress, not leader concentration."
            )

    result = {
        "k_id": EXPERIMENT_ID,
        "title": "Same-index ETF liquidity-clientele concentration as index RV stress proxy",
        "created_by": "codex-vscode",
        "seed": SEED,
        "data_source": "yfinance daily adjusted OHLCV, auto_adjust=True",
        "period_request": {"start": START, "end": END},
        "groups": group_summaries,
        "literature": LITERATURE,
        "proxy_scope": {
            "included": [
                "within-group dollar-volume share",
                "volume-share HHI / entropy",
                "legacy high-turnover ETF leader-share signal",
                "same-index return dispersion as NAV premium-discount proxy substitute",
            ],
            "not_included": [
                "historical NAV premium/discount",
                "creation/redemption flow",
                "historical ETF AUM share",
                "investor-level clientele",
                "bid-ask spread quotes",
            ],
            "interpretation": "Free-data proxy diagnostic; not a full replication of ETF liquidity-clientele papers.",
        },
        "method": {
            "signal_window_days": ROLL_Z,
            "lookahead_rule": "feature rolling z-score, then signal.shift(1), predicts target at date t",
            "primary_signal": "leader_share_z_l1",
            "primary_targets": [
                "next_range_vol",
                "forward5_rv",
                "same_index_return_dispersion",
                "same_index_tracking_range",
            ],
            "regression": "z(log(target)) ~ z(signal_l1) + z(log(target_l1)) + z(total_dollar_volume_l1)",
            "inference": f"OLS-HAC Newey-West maxlags={HAC_LAGS}; Harvey threshold positive t >= {HARVEY_T}",
            "multiple_testing": "Benjamini-Hochberg q-values over all signal-target-group regressions",
        },
        "regressions": regression_rows,
        "primary_summary": {
            "n_primary_tests": n_primary,
            "n_positive_hac_t": n_positive,
            "n_positive_harvey_t_ge_3": n_harvey,
            "n_positive_harvey_and_bh_q_le_0_05": n_harvey_fdr,
            "n_negative_harvey_and_bh_q_le_0_05": n_negative_harvey_fdr,
        },
        "secondary_reverse_signal": {
            "description": (
                "Rows where higher fragmentation/entropy, rather than leader concentration, "
                "predicts higher vol/range targets with positive HAC t>=3 and BH q<=0.05."
            ),
            "n_hits": len(secondary_reverse_rows),
            "rows": secondary_reverse_rows,
        },
        "top_positive_hac_results": top_positive,
        "verdict": verdict,
        "verdict_reason": verdict_reason,
        "lookahead_protected": True,
        "figures": figure_paths,
        "tables": ["K1365_regression_table.csv"],
        "limitations": [
            "Same-index ETF pairs are small cross-sections; inference is time-series within group, not broad ETF universe inference.",
            "yfinance OHLCV cannot identify ETF NAV premiums, creations/redemptions, or historical AUM/fee dynamics.",
            "Forward 5-day targets overlap; HAC maxlags=5 mitigates but does not replace a non-overlapping robustness design.",
            "The leader ETF is pre-specified by historical liquidity (SPY/QQQ/IWM/EEM), not estimated from future data.",
        ],
    }

    out_path = HERE / "K1365_results.json"
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2, default=_json_default), encoding="utf-8")
    print(f"[done] wrote {out_path}")
    print(f"[done] verdict={verdict}: {verdict_reason}")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--refresh", action="store_true", help="refresh yfinance cache")
    args = parser.parse_args()
    main(refresh=args.refresh)
