#!/usr/bin/env python3
"""Insurance-platform integration and alternative-manager vol beta.

Tests whether publicly listed alternative asset managers show post-integration
shifts in realized volatility, market/financial beta, credit-stress
sensitivity, and downside insurer correlation after major insurance-platform
transactions.
"""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import statsmodels.formula.api as smf
import yfinance as yf


EXP_ID = "research_permanent_capital_insurance_platform_integration"
SEED = 20260624
TRADING_DAYS = 252
START_DATE = "2014-01-01"
PANEL_START = pd.Timestamp("2014-05-05")

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
FIG_DIR = ROOT / "figures"
RESULTS_PATH = ROOT / f"{EXP_ID}_results.json"


@dataclass(frozen=True)
class InsuranceEvent:
    manager: str
    ticker: str
    partner: str
    announcement_date: str
    integration_date: str
    description: str
    source_url: str


EVENTS = [
    InsuranceEvent(
        manager="BX",
        ticker="BX",
        partner="Allstate Life",
        announcement_date="2021-01-26",
        integration_date="2021-11-01",
        description="Blackstone-managed entities acquire Allstate Life Insurance Company.",
        source_url="https://www.allstatenewsroom.com/news/allstate-completes-sale-of-life-and-annuity-businesses/",
    ),
    InsuranceEvent(
        manager="KKR",
        ticker="KKR",
        partner="Global Atlantic",
        announcement_date="2020-07-08",
        integration_date="2021-02-01",
        description="KKR acquires majority ownership of Global Atlantic.",
        source_url="https://www.globalatlantic.com/news/kkr-closes-acquisition-global-atlantic-financial-group-limited",
    ),
    InsuranceEvent(
        manager="APO",
        ticker="APO",
        partner="Athene",
        announcement_date="2021-03-08",
        integration_date="2022-01-03",
        description="Apollo completes full merger with Athene.",
        source_url="https://www.apollo.com/insights-news/pressreleases/2022/01/apollo-completes-merger-with-athene-and-finalizes-key-governance-enhancements-120051006",
    ),
    InsuranceEvent(
        manager="ARES",
        ticker="ARES",
        partner="Aspida / Global Bankers",
        announcement_date="2019-07-08",
        integration_date="2021-07-15",
        description="Ares-backed Aspida closes acquisition of U.S. insurance platform operations.",
        source_url="https://www.businesswire.com/news/home/20210715005357/en/Aspida-Completes-Acquisition-of-U.S.-Based-Insurance-Platform",
    ),
    InsuranceEvent(
        manager="BAM_BN_PROXY",
        ticker="BN",
        partner="American Equity Investment Life",
        announcement_date="2023-07-05",
        integration_date="2024-05-02",
        description="Brookfield Reinsurance completes acquisition of AEL; BN used for longer Brookfield history.",
        source_url="https://bnt.brookfield.com/sites/brookfield-bnt/files/Brookfield-BNT/Press-Releases/2024/bnre-press-release-brookfield-reinsurance-completes-acquisition-ael-f.pdf",
    ),
    InsuranceEvent(
        manager="CG",
        ticker="CG",
        partner="Fortitude Re",
        announcement_date="2019-11-25",
        integration_date="2020-06-03",
        description="Carlyle-led consortium completes majority acquisition of Fortitude Re.",
        source_url="https://www.carlyle.com/media-room/news-release-archive/carlyle-group-and-td-holdings-complete-acquisition-majority",
    ),
]

MANAGER_TICKERS = sorted({event.ticker for event in EVENTS})
CONTROL_TICKERS = ["SPY", "XLF", "KIE", "HYG", "LQD", "MET", "PRU", "EQH", "GL"]
ALL_TICKERS = sorted(set(MANAGER_TICKERS + CONTROL_TICKERS))


def _download_prices() -> pd.DataFrame:
    cache_path = DATA_DIR / "prices.csv"
    if cache_path.exists():
        cached = pd.read_csv(cache_path, index_col=0, parse_dates=True)
        if all(ticker in cached.columns for ticker in ALL_TICKERS):
            print(f"Using cached prices from {cache_path}")
            return cached[ALL_TICKERS].sort_index()

    print(f"Downloading {len(ALL_TICKERS)} tickers via yfinance ...")
    raw = yf.download(
        ALL_TICKERS,
        start=START_DATE,
        auto_adjust=True,
        progress=False,
        group_by="column",
        threads=True,
    )
    if raw.empty:
        raise RuntimeError("yfinance returned no price data")
    if isinstance(raw.columns, pd.MultiIndex):
        prices = raw["Close"].copy()
    else:
        prices = raw[["Close"]].rename(columns={"Close": ALL_TICKERS[0]})
    prices = prices.loc[:, [ticker for ticker in ALL_TICKERS if ticker in prices.columns]]
    missing = sorted(set(ALL_TICKERS) - set(prices.columns))
    if missing:
        raise RuntimeError(f"Missing price columns: {missing}")
    return prices.dropna(how="all").sort_index()


def _load_fred_hy_oas(target_index: pd.DatetimeIndex) -> tuple[pd.Series, dict]:
    cache_path = DATA_DIR / "fred_BAMLH0A0HYM2.csv"
    url = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=BAMLH0A0HYM2"
    meta = {"source": "FRED BAMLH0A0HYM2", "fallback_used": False}
    try:
        fred = pd.read_csv(url)
        fred.to_csv(cache_path, index=False)
    except Exception as exc:  # noqa: BLE001 - recorded in metadata.
        meta["download_error"] = repr(exc)
        if cache_path.exists():
            fred = pd.read_csv(cache_path)
            meta["source"] = "cached FRED BAMLH0A0HYM2"
        else:
            local_path = Path("storage/macro/fred_BAMLH0A0HYM2.csv")
            if local_path.exists():
                fred = pd.read_csv(local_path)
                meta["source"] = "local storage/macro/fred_BAMLH0A0HYM2.csv"
            else:
                return pd.Series(index=target_index, dtype=float), meta

    date_col = "observation_date" if "observation_date" in fred.columns else "date"
    value_col = "BAMLH0A0HYM2"
    fred[date_col] = pd.to_datetime(fred[date_col])
    series = pd.to_numeric(fred[value_col], errors="coerce")
    oas = pd.Series(series.to_numpy(dtype=float), index=fred[date_col]).sort_index()
    oas = oas.reindex(target_index).ffill()
    if oas.dropna().index.min() is not None:
        meta["start"] = oas.dropna().index.min().strftime("%Y-%m-%d")
        meta["end"] = oas.dropna().index.max().strftime("%Y-%m-%d")
        meta["n"] = int(oas.notna().sum())
    return oas, meta


def _prepare_returns(prices: pd.DataFrame) -> tuple[pd.DataFrame, pd.Series, dict]:
    returns = prices.pct_change(fill_method=None).dropna(how="all")
    fred_oas, credit_meta = _load_fred_hy_oas(returns.index)
    credit_stress = fred_oas.diff()
    if credit_stress.dropna().shape[0] < 1500:
        credit_stress = (returns["LQD"] - returns["HYG"]).reindex(returns.index)
        credit_meta["fallback_used"] = True
        credit_meta["source"] = "tradable proxy LQD_return_minus_HYG_return"
        credit_meta["n"] = int(credit_stress.notna().sum())
    return returns, credit_stress.rename("credit_stress"), credit_meta


def _make_panel(returns: pd.DataFrame, credit_stress: pd.Series) -> pd.DataFrame:
    controls = pd.DataFrame(
        {
            "spy": returns["SPY"],
            "xlf": returns["XLF"],
            "kie": returns["KIE"],
            "hyg": returns["HYG"],
            "lqd": returns["LQD"],
            "insurer_basket": returns[["MET", "PRU", "EQH", "GL"]].mean(axis=1),
            "credit_stress": credit_stress,
        }
    ).sort_index()
    controls["credit_z"] = (
        controls["credit_stress"] - controls["credit_stress"].mean()
    ) / controls["credit_stress"].std(ddof=1)
    controls["abs_spy"] = controls["spy"].abs()
    controls["abs_xlf"] = controls["xlf"].abs()
    controls["abs_kie"] = controls["kie"].abs()
    controls["abs_credit_z"] = controls["credit_z"].abs()

    rows = []
    for event in EVENTS:
        manager_ret = returns[event.ticker].rename("ret")
        df = pd.concat([manager_ret, controls], axis=1, join="inner").dropna()
        df = df.loc[df.index >= PANEL_START].copy()
        df["manager"] = event.manager
        df["ticker"] = event.ticker
        df["post"] = (df.index >= pd.Timestamp(event.integration_date)).astype(int)
        df["event_date"] = event.integration_date
        df["abs_ret"] = df["ret"].abs()
        df["r2_annualized"] = df["ret"] ** 2 * TRADING_DAYS
        df["date"] = df.index
        df["year"] = df.index.year.astype(str)
        rows.append(df.reset_index(drop=True))
    panel = pd.concat(rows, ignore_index=True)
    return panel


def _coef_table(model, model_name: str) -> pd.DataFrame:
    conf = model.conf_int()
    rows = []
    for term, coef in model.params.items():
        rows.append(
            {
                "model": model_name,
                "term": term,
                "coef": float(coef),
                "std_err": float(model.bse[term]),
                "t": float(model.tvalues[term]),
                "p": float(model.pvalues[term]),
                "ci_low": float(conf.loc[term, 0]),
                "ci_high": float(conf.loc[term, 1]),
                "harvey_pass": bool(abs(float(model.tvalues[term])) > 3.0),
            }
        )
    return pd.DataFrame(rows)


def _fit_models(panel: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    models = {}
    formulas = {
        "return_beta_shift": (
            "ret ~ C(manager) + C(year) + spy + xlf + kie + credit_z + post "
            "+ spy:post + xlf:post + kie:post + credit_z:post"
        ),
        "rv_shift": (
            "r2_annualized ~ C(manager) + C(year) + abs_spy + abs_xlf + abs_kie "
            "+ abs_credit_z + post"
        ),
        "downside_insurer_beta_shift": (
            "ret ~ C(manager) + C(year) + spy + xlf + kie + credit_z + post + kie:post"
        ),
    }
    for name, formula in formulas.items():
        data = panel.loc[panel["spy"] < 0].copy() if name == "downside_insurer_beta_shift" else panel
        model = smf.ols(formula, data=data).fit(
            cov_type="cluster",
            cov_kwds={"groups": data["date"]},
        )
        models[name] = {
            "n_obs": int(model.nobs),
            "r_squared": float(model.rsquared),
        }
        models[name]["coef_table"] = _coef_table(model, name)

    coef_tables = pd.concat([m["coef_table"] for m in models.values()], ignore_index=True)
    model_meta = {
        name: {k: v for k, v in payload.items() if k != "coef_table"}
        for name, payload in models.items()
    }
    return coef_tables, model_meta


def _ols_betas(df: pd.DataFrame) -> dict[str, float]:
    if df.shape[0] < 126:
        return {
            "n": int(df.shape[0]),
            "beta_spy": np.nan,
            "beta_xlf": np.nan,
            "beta_kie": np.nan,
            "beta_credit_z": np.nan,
        }
    model = smf.ols("ret ~ spy + xlf + kie + credit_z", data=df).fit()
    return {
        "n": int(df.shape[0]),
        "beta_spy": float(model.params.get("spy", np.nan)),
        "beta_xlf": float(model.params.get("xlf", np.nan)),
        "beta_kie": float(model.params.get("kie", np.nan)),
        "beta_credit_z": float(model.params.get("credit_z", np.nan)),
    }


def _manager_metrics(panel: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for manager, df in panel.groupby("manager"):
        for regime, sub in [("pre", df.loc[df["post"] == 0]), ("post", df.loc[df["post"] == 1])]:
            if sub.empty:
                continue
            down = sub.loc[sub["spy"] < 0]
            beta = _ols_betas(sub)
            row = {
                "manager": manager,
                "ticker": sub["ticker"].iloc[0],
                "regime": regime,
                "start": sub["date"].min().strftime("%Y-%m-%d"),
                "end": sub["date"].max().strftime("%Y-%m-%d"),
                "n_days": int(sub.shape[0]),
                "ann_return": float(sub["ret"].mean() * TRADING_DAYS),
                "ann_vol": float(sub["ret"].std(ddof=1) * math.sqrt(TRADING_DAYS)),
                "sharpe": float(sub["ret"].mean() / sub["ret"].std(ddof=1) * math.sqrt(TRADING_DAYS)),
                "downside_corr_kie": float(down["ret"].corr(down["kie"])) if down.shape[0] > 20 else np.nan,
                "downside_corr_insurer_basket": float(down["ret"].corr(down["insurer_basket"]))
                if down.shape[0] > 20
                else np.nan,
            }
            row.update(beta)
            rows.append(row)
    metrics = pd.DataFrame(rows)
    diffs = []
    for manager, df in metrics.groupby("manager"):
        if set(df["regime"]) != {"pre", "post"}:
            continue
        pre = df.loc[df["regime"] == "pre"].iloc[0]
        post = df.loc[df["regime"] == "post"].iloc[0]
        diff = {"manager": manager, "regime": "post_minus_pre", "ticker": post["ticker"]}
        for metric in [
            "ann_vol",
            "sharpe",
            "beta_spy",
            "beta_xlf",
            "beta_kie",
            "beta_credit_z",
            "downside_corr_kie",
            "downside_corr_insurer_basket",
        ]:
            diff[f"{metric}_diff"] = float(post[metric] - pre[metric])
        diffs.append(diff)
    return metrics, pd.DataFrame(diffs)


def _event_windows(returns: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for event in EVENTS:
        series = returns[event.ticker].dropna()
        spy = returns["SPY"].reindex(series.index)
        for date_type, date_str in [
            ("announcement", event.announcement_date),
            ("integration_close", event.integration_date),
        ]:
            event_date = pd.Timestamp(date_str)
            pre = series.loc[(series.index >= event_date - pd.Timedelta(days=35)) & (series.index < event_date)].tail(20)
            post = series.loc[(series.index > event_date) & (series.index <= event_date + pd.Timedelta(days=35))].head(20)
            pre_spy = spy.reindex(pre.index)
            post_spy = spy.reindex(post.index)
            if pre.shape[0] < 10 or post.shape[0] < 10:
                continue
            rows.append(
                {
                    "manager": event.manager,
                    "ticker": event.ticker,
                    "date_type": date_type,
                    "event_date": event_date.strftime("%Y-%m-%d"),
                    "pre_n": int(pre.shape[0]),
                    "post_n": int(post.shape[0]),
                    "pre_ann_vol": float(pre.std(ddof=1) * math.sqrt(TRADING_DAYS)),
                    "post_ann_vol": float(post.std(ddof=1) * math.sqrt(TRADING_DAYS)),
                    "post_pre_vol_ratio": float(post.std(ddof=1) / pre.std(ddof=1)),
                    "post_minus_pre_cum_excess_vs_spy": float(
                        (post - post_spy).sum() - (pre - pre_spy).sum()
                    ),
                }
            )
    return pd.DataFrame(rows)


def _plot_coef_forest(coef_table: pd.DataFrame) -> None:
    terms = [
        ("return_beta_shift", "spy:post", "SPY beta shift"),
        ("return_beta_shift", "xlf:post", "XLF beta shift"),
        ("return_beta_shift", "kie:post", "Insurance ETF beta shift"),
        ("return_beta_shift", "credit_z:post", "Credit-stress beta shift"),
        ("rv_shift", "post", "Residual RV level shift"),
        ("downside_insurer_beta_shift", "kie:post", "Downside insurance beta shift"),
    ]
    rows = []
    for model, term, label in terms:
        row = coef_table.loc[(coef_table["model"] == model) & (coef_table["term"] == term)]
        if not row.empty:
            rec = row.iloc[0].to_dict()
            rec["label"] = label
            rows.append(rec)
    plot_df = pd.DataFrame(rows)
    fig, ax = plt.subplots(figsize=(10, 5.5))
    y = np.arange(plot_df.shape[0])
    ax.errorbar(
        plot_df["coef"],
        y,
        xerr=[plot_df["coef"] - plot_df["ci_low"], plot_df["ci_high"] - plot_df["coef"]],
        fmt="o",
        capsize=4,
    )
    ax.axvline(0, color="black", linewidth=1)
    ax.set_yticks(y)
    ax.set_yticklabels(plot_df["label"])
    ax.set_title("Post-integration coefficient shifts (clustered by date)")
    ax.grid(axis="x", alpha=0.25)
    fig.tight_layout()
    fig.savefig(FIG_DIR / "panel_coefficient_shifts.png", dpi=180)
    plt.close(fig)


def _plot_manager_diffs(diff_df: pd.DataFrame) -> None:
    metrics = [
        ("ann_vol_diff", "Annualized vol diff"),
        ("beta_spy_diff", "SPY beta diff"),
        ("beta_kie_diff", "Insurance ETF beta diff"),
        ("beta_credit_z_diff", "Credit-stress beta diff"),
    ]
    fig, axes = plt.subplots(2, 2, figsize=(12, 8))
    for ax, (metric, title) in zip(axes.ravel(), metrics):
        ax.bar(diff_df["manager"], diff_df[metric])
        ax.axhline(0, color="black", linewidth=1)
        ax.set_title(title)
        ax.tick_params(axis="x", rotation=30)
        ax.grid(axis="y", alpha=0.25)
    fig.suptitle("Manager-level post-minus-pre metric changes")
    fig.tight_layout(rect=[0, 0, 1, 0.96])
    fig.savefig(FIG_DIR / "manager_post_pre_diffs.png", dpi=180)
    plt.close(fig)


def _t_summary(diff_df: pd.DataFrame) -> dict:
    out = {}
    for metric in [
        "ann_vol_diff",
        "beta_spy_diff",
        "beta_kie_diff",
        "beta_credit_z_diff",
        "downside_corr_kie_diff",
    ]:
        values = diff_df[metric].dropna().to_numpy(dtype=float)
        if len(values) < 2:
            continue
        mean = float(values.mean())
        se = float(values.std(ddof=1) / math.sqrt(len(values)))
        t = mean / se if se > 0 else np.nan
        out[metric] = {
            "n_managers": int(len(values)),
            "mean": mean,
            "std": float(values.std(ddof=1)),
            "t_cross_section": float(t),
            "harvey_pass": bool(abs(t) > 3.0) if np.isfinite(t) else False,
        }
    return out


def _record_to_builtin(obj):
    if isinstance(obj, dict):
        return {k: _record_to_builtin(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_record_to_builtin(v) for v in obj]
    if isinstance(obj, (np.integer, np.floating, np.bool_)):
        return obj.item()
    if isinstance(obj, float) and not np.isfinite(obj):
        return None
    return obj


def main() -> None:
    DATA_DIR.mkdir(exist_ok=True)
    FIG_DIR.mkdir(exist_ok=True)
    np.random.seed(SEED)

    prices = _download_prices()
    prices.to_csv(DATA_DIR / "prices.csv")
    returns, credit_stress, credit_meta = _prepare_returns(prices)
    returns.to_csv(DATA_DIR / "daily_returns.csv")
    credit_stress.to_csv(DATA_DIR / "credit_stress.csv")

    events_df = pd.DataFrame([asdict(event) for event in EVENTS])
    events_df.to_csv(DATA_DIR / "insurance_events.csv", index=False)

    panel = _make_panel(returns, credit_stress)
    panel.to_csv(DATA_DIR / "panel.csv", index=False)

    coef_table, model_meta = _fit_models(panel)
    coef_table.to_csv(DATA_DIR / "panel_regressions.csv", index=False)

    manager_metrics, manager_diffs = _manager_metrics(panel)
    manager_metrics.to_csv(DATA_DIR / "manager_pre_post_metrics.csv", index=False)
    manager_diffs.to_csv(DATA_DIR / "manager_post_pre_diffs.csv", index=False)

    event_windows = _event_windows(returns)
    event_windows.to_csv(DATA_DIR / "event_windows.csv", index=False)

    _plot_coef_forest(coef_table)
    _plot_manager_diffs(manager_diffs)

    primary_terms = {
        "market_beta_shift": ("return_beta_shift", "spy:post"),
        "financial_beta_shift": ("return_beta_shift", "xlf:post"),
        "insurance_beta_shift": ("return_beta_shift", "kie:post"),
        "credit_beta_shift": ("return_beta_shift", "credit_z:post"),
        "rv_level_shift": ("rv_shift", "post"),
        "downside_insurance_beta_shift": ("downside_insurer_beta_shift", "kie:post"),
    }
    primary = {}
    for name, (model, term) in primary_terms.items():
        row = coef_table.loc[(coef_table["model"] == model) & (coef_table["term"] == term)]
        if not row.empty:
            primary[name] = row.iloc[0].to_dict()

    harvey_passes = [name for name, row in primary.items() if bool(row["harvey_pass"])]
    beta_pass_count = sum(
        name in harvey_passes
        for name in [
            "market_beta_shift",
            "financial_beta_shift",
            "insurance_beta_shift",
            "downside_insurance_beta_shift",
        ]
    )
    rv_pass = "rv_level_shift" in harvey_passes
    credit_pass = "credit_beta_shift" in harvey_passes
    if beta_pass_count >= 2 and not rv_pass and not credit_pass:
        verdict = "BETA_COMPOSITION_SHIFT_NO_RV_CREDIT_PASS"
    elif not harvey_passes:
        verdict = "NULL_NO_STRONG_REGIME_SHIFT"
    elif len(harvey_passes) <= 2:
        verdict = "MIXED_SELECTIVE_SHIFT"
    else:
        verdict = "REGIME_SHIFT_BROAD"

    results = {
        "experiment_id": EXP_ID,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "seed": SEED,
        "verdict": verdict,
        "data": {
            "source": "yfinance adjusted close; FRED HY OAS or LQD-HYG fallback for credit stress",
            "price_start": prices.index.min().strftime("%Y-%m-%d"),
            "price_end": prices.index.max().strftime("%Y-%m-%d"),
            "panel_start": panel["date"].min().strftime("%Y-%m-%d"),
            "panel_end": panel["date"].max().strftime("%Y-%m-%d"),
            "panel_obs": int(panel.shape[0]),
            "managers": [event.manager for event in EVENTS],
            "manager_tickers": {event.manager: event.ticker for event in EVENTS},
            "credit_stress": credit_meta,
        },
        "events": [asdict(event) for event in EVENTS],
        "model_meta": model_meta,
        "primary_tests": primary,
        "primary_harvey_passes": harvey_passes,
        "manager_diff_summary": _t_summary(manager_diffs),
        "event_window_summary": {
            "median_close_post_pre_vol_ratio": float(
                event_windows.loc[event_windows["date_type"] == "integration_close", "post_pre_vol_ratio"].median()
            ),
            "median_announcement_post_pre_vol_ratio": float(
                event_windows.loc[event_windows["date_type"] == "announcement", "post_pre_vol_ratio"].median()
            ),
        },
        "files": {
            "prices": "data/prices.csv",
            "daily_returns": "data/daily_returns.csv",
            "credit_stress": "data/credit_stress.csv",
            "events": "data/insurance_events.csv",
            "panel": "data/panel.csv",
            "panel_regressions": "data/panel_regressions.csv",
            "manager_metrics": "data/manager_pre_post_metrics.csv",
            "manager_diffs": "data/manager_post_pre_diffs.csv",
            "event_windows": "data/event_windows.csv",
            "figure_coef": "figures/panel_coefficient_shifts.png",
            "figure_manager_diffs": "figures/manager_post_pre_diffs.png",
        },
    }
    RESULTS_PATH.write_text(
        json.dumps(_record_to_builtin(results), indent=2, ensure_ascii=False) + "\n"
    )
    print(
        json.dumps(
            {
                "verdict": verdict,
                "panel_obs": int(panel.shape[0]),
                "primary_harvey_passes": harvey_passes,
                "credit_source": credit_meta["source"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
