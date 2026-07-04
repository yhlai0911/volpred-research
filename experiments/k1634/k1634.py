#!/usr/bin/env python3
"""K1634: Sell in May myth test for SPY and Taiwan index.

Question
--------
Does the recent 15-year SPY / ^TWII sample still support the old
"Sell in May and go away" / Halloween rule?

Design guardrails
-----------------
* Monthly returns are computed from month-end adjusted closes.
* The calendar signal is deterministic and known before the month begins:
  invest during Nov-Apr, hold cash during May-Oct.
* Primary inference compares Nov-Apr vs May-Oct monthly returns with HAC
  standard errors (monthly maxlags=6) and year-block bootstrap.
* Paired season tests compare each complete Nov-Apr season against the
  following May-Oct season.
* Multiple testing is adjusted across the two primary asset-level HAC tests.
* Random procedures use SEED.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import statsmodels.api as sm
from scipy import stats


HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
SEED = 1634
N_BOOT = 5000
DOWNLOAD_START = "2010-10-01"
DOWNLOAD_END = "2026-07-05"
ANALYSIS_START = pd.Timestamp("2011-07-01")
ANALYSIS_END = pd.Timestamp("2026-06-30")
HAC_MAXLAGS_MONTHLY = 6
TX_COST_ONE_WAY = 0.001  # 10 bps, robustness for two switches per year

ASSETS = {
    "SPY": {
        "symbol": "SPY",
        "label": "SPY",
        "market": "US equity ETF",
        "fallback": HERE.parent / "k1633" / "data" / "spy_full.csv",
        "fallback_col": "SPY",
        "return_note": "SPY adjusted close, dividends/splits included via yfinance auto_adjust=True",
    },
    "TWII": {
        "symbol": "^TWII",
        "label": "^TWII",
        "market": "Taiwan capitalization-weighted index",
        "fallback": Path("storage/macro/yf_TWII.csv"),
        "fallback_col": "Close",
        "return_note": "^TWII price index close; dividends are not included",
    },
}

WINTER_MONTHS = {11, 12, 1, 2, 3, 4}
SUMMER_MONTHS = {5, 6, 7, 8, 9, 10}


@dataclass
class AssetMonthly:
    asset: str
    symbol: str
    source: str
    daily_start: str
    daily_end: str
    monthly: pd.DataFrame


def _flatten_yfinance_columns(df: pd.DataFrame) -> pd.DataFrame:
    if isinstance(df.columns, pd.MultiIndex):
        df = df.copy()
        df.columns = [c[0] for c in df.columns]
    return df


def _download_or_cache(asset: str, cfg: dict) -> tuple[pd.Series, str]:
    DATA.mkdir(exist_ok=True)
    cache_path = DATA / f"{asset.lower()}_close.csv"
    if cache_path.exists():
        close = pd.read_csv(cache_path, index_col=0, parse_dates=True)["Close"]
        return close.sort_index(), f"cache:{cache_path.relative_to(HERE)}"

    try:
        import yfinance as yf

        raw = yf.download(
            cfg["symbol"],
            start=DOWNLOAD_START,
            end=DOWNLOAD_END,
            progress=False,
            auto_adjust=True,
        )
        raw = _flatten_yfinance_columns(raw)
        if raw.empty or "Close" not in raw:
            raise RuntimeError(f"empty yfinance result for {cfg['symbol']}")
        close = raw["Close"].dropna().sort_index()
        close.to_frame("Close").to_csv(cache_path)
        return close, f"yfinance:{cfg['symbol']} auto_adjust=True"
    except Exception as exc:
        close = _load_fallback(cfg)
        if close.empty:
            raise RuntimeError(f"failed to load {asset} via yfinance or fallback") from exc
        close.to_frame("Close").to_csv(cache_path)
        return close, f"fallback:{cfg['fallback']}"


def _load_fallback(cfg: dict) -> pd.Series:
    path = cfg["fallback"]
    if not path.exists():
        return pd.Series(dtype=float)

    # Project yfinance macro snapshots have a 3-row MultiIndex header.
    with path.open() as f:
        first = f.readline().strip()
        second = f.readline().strip()
        third = f.readline().strip()
    if first.startswith("Price,") and second.startswith("Ticker,") and third.startswith("Date,"):
        df = pd.read_csv(path, skiprows=3, names=["Date", "Close", "High", "Low", "Open", "Volume"])
        return pd.Series(df["Close"].astype(float).to_numpy(), index=pd.to_datetime(df["Date"]))

    df = pd.read_csv(path, index_col=0, parse_dates=True)
    col = cfg["fallback_col"]
    if col not in df.columns:
        col = "Close"
    return df[col].astype(float).dropna().sort_index()


def build_monthly(asset: str, cfg: dict) -> AssetMonthly:
    close, source = _download_or_cache(asset, cfg)
    close = close[~close.index.duplicated(keep="first")].dropna().sort_index()
    month_end = close.resample("ME").last().dropna()
    month_end = month_end[(month_end.index >= ANALYSIS_START - pd.offsets.MonthEnd(1))]
    month_end = month_end[month_end.index <= ANALYSIS_END]
    monthly_ret = month_end.pct_change().dropna()
    monthly_ret = monthly_ret[(monthly_ret.index >= ANALYSIS_START) & (monthly_ret.index <= ANALYSIS_END)]
    df = pd.DataFrame({"ret": monthly_ret})
    df["month"] = df.index.month
    df["year"] = df.index.year
    df["winter"] = df["month"].isin(WINTER_MONTHS).astype(int)
    df["season"] = np.where(df["winter"] == 1, "Nov-Apr", "May-Oct")
    return AssetMonthly(
        asset=asset,
        symbol=cfg["symbol"],
        source=source,
        daily_start=str(close.index.min().date()),
        daily_end=str(close.index.max().date()),
        monthly=df,
    )


def hac_winter_test(monthly: pd.DataFrame) -> dict:
    y = monthly["ret"].to_numpy()
    X = sm.add_constant(monthly["winter"].to_numpy(dtype=float))
    model = sm.OLS(y, X).fit(cov_type="HAC", cov_kwds={"maxlags": HAC_MAXLAGS_MONTHLY})
    coef = float(model.params[1])
    tval = float(model.tvalues[1])
    pval = float(model.pvalues[1])
    return {
        "coef_monthly_winter_minus_summer": coef,
        "coef_annualized": coef * 12.0,
        "hac_t": tval,
        "hac_p": pval,
        "hac_maxlags": HAC_MAXLAGS_MONTHLY,
    }


def year_block_bootstrap(monthly: pd.DataFrame, rng: np.random.Generator) -> dict:
    years = np.array(sorted(monthly["year"].unique()))
    by_year = {int(y): monthly.loc[monthly["year"] == y].copy() for y in years}
    diffs = np.empty(N_BOOT)
    for b in range(N_BOOT):
        picks = rng.choice(years, size=len(years), replace=True)
        sample = pd.concat([by_year[int(y)] for y in picks], ignore_index=True)
        w = sample.loc[sample["winter"] == 1, "ret"]
        s = sample.loc[sample["winter"] == 0, "ret"]
        diffs[b] = w.mean() - s.mean()
    point = monthly.loc[monthly["winter"] == 1, "ret"].mean() - monthly.loc[monthly["winter"] == 0, "ret"].mean()
    diffs_centered = diffs - point
    p_two = float((np.abs(diffs_centered) >= abs(point)).mean())
    p_one_winter_gt = float((diffs <= 0).mean())
    return {
        "diff_monthly_ci95": [float(np.percentile(diffs, 2.5)), float(np.percentile(diffs, 97.5))],
        "diff_annualized_ci95": [float(np.percentile(diffs * 12.0, 2.5)), float(np.percentile(diffs * 12.0, 97.5))],
        "p_two_sided_centered_at_zero": p_two,
        "p_one_sided_winter_gt_summer": p_one_winter_gt,
        "block": "calendar_year",
        "n_boot": N_BOOT,
    }


def paired_seasons(monthly: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for year in sorted(monthly["year"].unique()):
        winter_mask = (
            ((monthly["year"] == year - 1) & (monthly["month"].isin([11, 12])))
            | ((monthly["year"] == year) & (monthly["month"].isin([1, 2, 3, 4])))
        )
        summer_mask = (monthly["year"] == year) & (monthly["month"].isin([5, 6, 7, 8, 9, 10]))
        winter = monthly.loc[winter_mask, "ret"]
        summer = monthly.loc[summer_mask, "ret"]
        if len(winter) == 6 and len(summer) == 6:
            winter_comp = float((1.0 + winter).prod() - 1.0)
            summer_comp = float((1.0 + summer).prod() - 1.0)
            rows.append(
                {
                    "season_year": int(year),
                    "winter_return": winter_comp,
                    "summer_return": summer_comp,
                    "winter_minus_summer": winter_comp - summer_comp,
                    "winter_wins": bool(winter_comp > summer_comp),
                }
            )
    return pd.DataFrame(rows)


def paired_test(paired: pd.DataFrame, rng: np.random.Generator) -> dict:
    d = paired["winter_minus_summer"].to_numpy()
    if len(d) < 2:
        return {}
    tstat, pval = stats.ttest_1samp(d, 0.0)
    sign_p = stats.binomtest(int((d > 0).sum()), len(d), 0.5, alternative="greater").pvalue
    boot = np.empty(N_BOOT)
    for b in range(N_BOOT):
        boot[b] = rng.choice(d, size=len(d), replace=True).mean()
    return {
        "n_complete_season_years": int(len(d)),
        "mean_winter_minus_summer": float(d.mean()),
        "median_winter_minus_summer": float(np.median(d)),
        "win_rate_winter_gt_summer": float((d > 0).mean()),
        "paired_t": float(tstat),
        "paired_p": float(pval),
        "sign_test_p_one_sided": float(sign_p),
        "bootstrap_mean_ci95": [float(np.percentile(boot, 2.5)), float(np.percentile(boot, 97.5))],
    }


def sharpe(x: pd.Series) -> float:
    sd = x.std(ddof=1)
    if sd == 0 or np.isnan(sd):
        return float("nan")
    return float(x.mean() * 12.0 / (sd * np.sqrt(12.0)))


def max_drawdown(ret: pd.Series) -> float:
    nav = (1.0 + ret.fillna(0.0)).cumprod()
    peak = nav.cummax()
    return float((nav / peak - 1.0).min())


def cagr(ret: pd.Series) -> float:
    n_years = len(ret) / 12.0
    if n_years <= 0:
        return float("nan")
    return float((1.0 + ret).prod() ** (1.0 / n_years) - 1.0)


def strategy_metrics(monthly: pd.DataFrame) -> dict:
    ret = monthly["ret"].copy()
    pos = monthly["winter"].astype(float)
    gross = ret * pos
    turnover = pos.diff().abs().fillna(0.0)
    after_cost = gross - turnover * TX_COST_ONE_WAY
    bh = ret
    summer_only = ret * (1.0 - pos)
    out = {}
    for name, series in {
        "buy_and_hold": bh,
        "sell_in_may_cash_zero_cost": gross,
        "sell_in_may_cash_after_10bps_switch_cost": after_cost,
        "may_oct_only_cash_otherwise": summer_only,
    }.items():
        out[name] = {
            "n_months": int(series.shape[0]),
            "cagr": cagr(series),
            "annualized_mean": float(series.mean() * 12.0),
            "annualized_vol": float(series.std(ddof=1) * np.sqrt(12.0)),
            "sharpe": sharpe(series),
            "max_drawdown": max_drawdown(series),
            "positive_month_rate": float((series > 0).mean()),
        }

    diff = after_cost - bh
    X = np.ones((len(diff), 1))
    model = sm.OLS(diff.to_numpy(), X).fit(cov_type="HAC", cov_kwds={"maxlags": HAC_MAXLAGS_MONTHLY})
    out["strategy_vs_buyhold_hac"] = {
        "mean_diff_monthly_after_cost_minus_bh": float(diff.mean()),
        "mean_diff_annualized": float(diff.mean() * 12.0),
        "hac_t": float(model.tvalues[0]),
        "hac_p": float(model.pvalues[0]),
        "hac_maxlags": HAC_MAXLAGS_MONTHLY,
        "transaction_cost_one_way": TX_COST_ONE_WAY,
    }
    return out


def descriptive_stats(monthly: pd.DataFrame) -> dict:
    out = {}
    for label, sub in {
        "Nov-Apr": monthly.loc[monthly["winter"] == 1, "ret"],
        "May-Oct": monthly.loc[monthly["winter"] == 0, "ret"],
    }.items():
        out[label] = {
            "n_months": int(len(sub)),
            "mean_monthly": float(sub.mean()),
            "annualized_mean": float(sub.mean() * 12.0),
            "monthly_std": float(sub.std(ddof=1)),
            "annualized_vol": float(sub.std(ddof=1) * np.sqrt(12.0)),
            "sharpe": sharpe(sub),
            "median_monthly": float(sub.median()),
            "positive_month_rate": float((sub > 0).mean()),
            "p10": float(np.percentile(sub, 10)),
            "p90": float(np.percentile(sub, 90)),
        }
    tstat, pval = stats.ttest_ind(
        monthly.loc[monthly["winter"] == 1, "ret"],
        monthly.loc[monthly["winter"] == 0, "ret"],
        equal_var=False,
    )
    out["welch_winter_vs_summer"] = {"t": float(tstat), "p": float(pval)}
    return out


def bh_qvalues(pvals: list[float]) -> list[float]:
    p = np.asarray(pvals, dtype=float)
    order = np.argsort(p)
    ranked = p[order]
    m = len(p)
    q_ranked = np.empty(m)
    running = 1.0
    for i in range(m - 1, -1, -1):
        rank = i + 1
        running = min(running, ranked[i] * m / rank)
        q_ranked[i] = min(running, 1.0)
    q = np.empty(m)
    q[order] = q_ranked
    return [float(x) for x in q]


def make_charts(results: dict, monthly_by_asset: dict[str, pd.DataFrame], paired_by_asset: dict[str, pd.DataFrame]) -> None:
    colors = {"SPY": "#2f6fbb", "TWII": "#c24c3a"}

    fig, axes = plt.subplots(1, 2, figsize=(11, 4.8))
    for ax, metric, title, ylabel in [
        (axes[0], "annualized_mean", "Annualized Mean Return", "% per year"),
        (axes[1], "sharpe", "Monthly-Return Sharpe", "Sharpe"),
    ]:
        x = np.arange(len(results["assets"]))
        width = 0.34
        winter_vals = []
        summer_vals = []
        labels = []
        for asset in results["assets"]:
            labels.append(asset)
            winter_vals.append(results["assets"][asset]["descriptive"]["Nov-Apr"][metric])
            summer_vals.append(results["assets"][asset]["descriptive"]["May-Oct"][metric])
        scale = 100.0 if metric == "annualized_mean" else 1.0
        ax.bar(x - width / 2, np.array(winter_vals) * scale, width, label="Nov-Apr", color="#4c78a8")
        ax.bar(x + width / 2, np.array(summer_vals) * scale, width, label="May-Oct", color="#f58518")
        ax.axhline(0, color="black", lw=0.7)
        ax.set_xticks(x)
        ax.set_xticklabels(labels)
        ax.set_title(title)
        ax.set_ylabel(ylabel)
        ax.grid(axis="y", alpha=0.25)
        ax.legend()
    fig.suptitle("Sell in May test: Nov-Apr vs May-Oct monthly returns")
    fig.tight_layout()
    fig.savefig(HERE / "fig1_season_summary.png", dpi=140)
    plt.close(fig)

    fig, axes = plt.subplots(1, 2, figsize=(12, 4.8), sharey=True)
    for ax, asset in zip(axes, results["assets"]):
        paired = paired_by_asset[asset]
        ax.bar(paired["season_year"].astype(str), paired["winter_minus_summer"] * 100, color=colors[asset])
        ax.axhline(0, color="black", lw=0.8)
        ax.set_title(f"{asset}: paired season return spread")
        ax.set_xlabel("Season year")
        ax.tick_params(axis="x", rotation=45)
        ax.grid(axis="y", alpha=0.25)
    axes[0].set_ylabel("Nov-Apr minus May-Oct return (pp)")
    fig.tight_layout()
    fig.savefig(HERE / "fig2_paired_season_spreads.png", dpi=140)
    plt.close(fig)

    fig, axes = plt.subplots(1, 2, figsize=(12, 4.8))
    for ax, asset in zip(axes, results["assets"]):
        monthly = monthly_by_asset[asset]
        ret = monthly["ret"]
        pos = monthly["winter"].astype(float)
        turnover = pos.diff().abs().fillna(0.0)
        sim = ret * pos - turnover * TX_COST_ONE_WAY
        bh_nav = (1.0 + ret).cumprod()
        sim_nav = (1.0 + sim).cumprod()
        ax.plot(bh_nav.index, bh_nav, label="Buy & hold", color="#555555", lw=2)
        ax.plot(sim_nav.index, sim_nav, label="Sell-in-May strategy", color=colors[asset], lw=2)
        ax.set_title(f"{asset}: cumulative growth")
        ax.set_ylabel("Growth of $1")
        ax.grid(alpha=0.25)
        ax.legend()
    fig.tight_layout()
    fig.savefig(HERE / "fig3_strategy_growth.png", dpi=140)
    plt.close(fig)


def main() -> None:
    rng = np.random.default_rng(SEED)
    monthly_by_asset: dict[str, pd.DataFrame] = {}
    paired_by_asset: dict[str, pd.DataFrame] = {}
    asset_results = {}
    primary = []

    for asset, cfg in ASSETS.items():
        am = build_monthly(asset, cfg)
        monthly = am.monthly
        monthly_by_asset[asset] = monthly
        paired = paired_seasons(monthly)
        paired_by_asset[asset] = paired

        hac = hac_winter_test(monthly)
        boot = year_block_bootstrap(monthly, rng)
        pair = paired_test(paired, rng)
        desc = descriptive_stats(monthly)
        strat = strategy_metrics(monthly)

        asset_results[asset] = {
            "symbol": am.symbol,
            "market": cfg["market"],
            "data_source": am.source,
            "return_note": cfg["return_note"],
            "daily_period": f"{am.daily_start} .. {am.daily_end}",
            "analysis_period": f"{monthly.index.min().date()} .. {monthly.index.max().date()}",
            "n_months": int(len(monthly)),
            "n_winter_months": int(monthly["winter"].sum()),
            "n_summer_months": int((1 - monthly["winter"]).sum()),
            "descriptive": desc,
            "primary_hac_winter_minus_summer": hac,
            "year_block_bootstrap": boot,
            "paired_seasons": pair,
            "strategy_metrics": strat,
        }
        primary.append(
            {
                "asset": asset,
                "test": "HAC monthly return regression ret ~ const + winter_dummy",
                "p": hac["hac_p"],
                "effect_annualized": hac["coef_annualized"],
            }
        )

    qvals = bh_qvalues([x["p"] for x in primary])
    for row, q in zip(primary, qvals):
        row["bh_q"] = q
        row["bh_fdr_5pct"] = bool(q <= 0.05)
        row["bh_fdr_10pct"] = bool(q <= 0.10)

    n_pos = sum(1 for row in primary if row["effect_annualized"] > 0)
    n_fdr5 = sum(1 for row in primary if row["bh_fdr_5pct"])
    n_fdr10 = sum(1 for row in primary if row["bh_fdr_10pct"])

    if n_fdr5 == len(primary) and n_pos == len(primary):
        myth_verdict = "supported_recent_15y"
    elif n_pos == len(primary) and n_fdr10 > 0:
        myth_verdict = "weak_mixed_directional_only"
    else:
        myth_verdict = "not_supported_recent_15y"

    results = {
        "experiment_id": "k1634",
        "title": "Sell in May and go away: recent 15-year SPY/TWII myth test",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "seed": SEED,
        "config": {
            "download_start": DOWNLOAD_START,
            "download_end_exclusive": DOWNLOAD_END,
            "analysis_start": str(ANALYSIS_START.date()),
            "analysis_end_complete_month": str(ANALYSIS_END.date()),
            "winter_months": sorted(WINTER_MONTHS),
            "summer_months": sorted(SUMMER_MONTHS),
            "hac_maxlags_monthly": HAC_MAXLAGS_MONTHLY,
            "n_bootstrap": N_BOOT,
            "transaction_cost_one_way": TX_COST_ONE_WAY,
        },
        "literature": [
            {
                "citation": "Bouman and Jacobsen (2002), American Economic Review",
                "role": "canonical Halloween indicator / Sell in May evidence",
                "doi": "10.1257/000282802762024683",
            },
            {
                "citation": "Sullivan, Timmermann, and White (2001), Journal of Econometrics",
                "role": "calendar effects data-snooping warning",
                "doi": "10.1016/S0304-4076(01)00077-X",
            },
            {
                "citation": "Zhang and Jacobsen (2021), Journal of International Money and Finance",
                "role": "large international re-test of Halloween indicator",
                "doi": "10.1016/j.jimonfin.2020.102268",
            },
        ],
        "assets": asset_results,
        "primary_tests_with_bh_fdr": primary,
        "verdict": {
            "myth_verdict": myth_verdict,
            "n_primary_tests": len(primary),
            "n_positive_effects": n_pos,
            "n_bh_fdr_5pct": n_fdr5,
            "n_bh_fdr_10pct": n_fdr10,
            "interpretation_guardrail": (
                "Primary claim requires Nov-Apr > May-Oct after HAC inference and BH-FDR "
                "across SPY and TWII; strategy metrics are secondary because lower exposure "
                "changes both return and volatility."
            ),
        },
    }

    with (HERE / "k1634_results.json").open("w") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    make_charts(results, monthly_by_asset, paired_by_asset)
    print_summary(results)


def print_summary(results: dict) -> None:
    print("\n=== K1634 SUMMARY ===")
    print("Verdict:", results["verdict"]["myth_verdict"])
    print(f"{'Asset':<6} {'N':>4} {'Nov-Apr ann':>12} {'May-Oct ann':>12} {'Diff ann':>10} {'HAC p':>8} {'BH q':>8}")
    for row in results["primary_tests_with_bh_fdr"]:
        asset = row["asset"]
        a = results["assets"][asset]
        desc = a["descriptive"]
        print(
            f"{asset:<6} {a['n_months']:>4} "
            f"{desc['Nov-Apr']['annualized_mean']*100:>11.2f}% "
            f"{desc['May-Oct']['annualized_mean']*100:>11.2f}% "
            f"{row['effect_annualized']*100:>9.2f}% "
            f"{row['p']:>8.3f} {row['bh_q']:>8.3f}"
        )
    for asset, a in results["assets"].items():
        p = a["paired_seasons"]
        s = a["strategy_metrics"]["sell_in_may_cash_after_10bps_switch_cost"]
        bh = a["strategy_metrics"]["buy_and_hold"]
        dv = a["strategy_metrics"]["strategy_vs_buyhold_hac"]
        print(
            f"{asset}: paired win={p.get('win_rate_winter_gt_summer', float('nan')):.1%}, "
            f"strategy Sharpe={s['sharpe']:.3f} vs BH={bh['sharpe']:.3f}, "
            f"after-cost diff p={dv['hac_p']:.3f}"
        )


if __name__ == "__main__":
    main()
