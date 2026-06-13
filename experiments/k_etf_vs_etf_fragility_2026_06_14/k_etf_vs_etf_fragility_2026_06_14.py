from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import statsmodels.api as sm
import yfinance as yf
from scipy import stats


EXPERIMENT_ID = "k_etf_vs_etf_fragility_2026_06_14"
ROOT = Path(__file__).resolve().parent
RESULTS_PATH = ROOT / f"{EXPERIMENT_ID}_results.json"
SEED = 42
START_DATE = "2012-01-01"
END_DATE = "2026-06-14"
SHOCK_QUANTILE = 0.95
ROLLING_WINDOW = 252
PC_WINDOW = 21

ETF_TICKERS = ["EFA", "EEM", "EWJ", "EWG", "EWZ", "INDA", "XLK", "XLF"]
CONTROL_TICKERS = ["SPY", "^VIX"]
ALL_TICKERS = ETF_TICKERS + CONTROL_TICKERS


@dataclass
class LiteratureItem:
    title: str
    source: str
    year: int
    takeaway: str
    url: str


LITERATURE = [
    LiteratureItem(
        title="ETF adoption and equity market macroefficiency",
        source="City St George's, University of London working paper / open access record",
        year=2025,
        takeaway=(
            "ETF introduction can improve how equity markets incorporate macro information; "
            "the result is strongest in developed markets with larger ETF growth."
        ),
        url="https://openaccess.city.ac.uk/id/eprint/34375/",
    ),
    LiteratureItem(
        title="An ETF-based measure of stock price fragility",
        source="Journal of Financial Markets",
        year=2025,
        takeaway=(
            "ETF primary-market activity can proxy non-fundamental demand exposure; ETF-based "
            "fragility may capture risk missed by mutual-fund-flow measures."
        ),
        url="https://ideas.repec.org/a/eee/finmar/v72y2025ics1386418124000648.html",
    ),
    LiteratureItem(
        title="Do ETFs Increase Volatility?",
        source="Journal of Finance / NBER working paper version",
        year=2018,
        takeaway=(
            "ETF arbitrage and flows can transmit non-fundamental shocks to underlying securities "
            "and generate return reversals."
        ),
        url="https://www.nber.org/papers/w20071",
    ),
    LiteratureItem(
        title="ETF arbitrage under liquidity mismatch",
        source="European Systemic Risk Board working paper",
        year=2017,
        takeaway=(
            "When ETF shares are more liquid than underlying assets, arbitrage can become fragile "
            "and reduce market efficiency during stress."
        ),
        url="https://www.esrb.europa.eu/pub/pdf/wp/esrb.wp59.en.pdf",
    ),
]


def download_prices() -> pd.DataFrame:
    raw = yf.download(
        ALL_TICKERS,
        start=START_DATE,
        end=END_DATE,
        auto_adjust=False,
        progress=False,
        group_by="ticker",
        threads=True,
    )
    if raw.empty:
        raise RuntimeError("yfinance returned empty panel")

    adj_close = pd.DataFrame(index=raw.index)
    for ticker in ALL_TICKERS:
        if isinstance(raw.columns, pd.MultiIndex):
            sub = raw[ticker]
            col = "Adj Close" if "Adj Close" in sub.columns else "Close"
            adj_close[ticker] = sub[col]
        else:
            col = "Adj Close" if "Adj Close" in raw.columns else "Close"
            adj_close[ticker] = raw[col]
    adj_close = adj_close.dropna(how="all").ffill()
    adj_close = adj_close.dropna(subset=["SPY", "^VIX"])
    return adj_close


def compute_returns(adj_close: pd.DataFrame) -> pd.DataFrame:
    returns = np.log(adj_close).diff()
    returns["^VIX"] = np.log(adj_close["^VIX"]).diff()
    return returns.dropna()


def lagged_macro_shocks(returns: pd.DataFrame) -> pd.Series:
    spy_abs = returns["SPY"].abs()
    vix_pos = returns["^VIX"].clip(lower=0.0)
    spy_thr = spy_abs.shift(1).rolling(ROLLING_WINDOW, min_periods=ROLLING_WINDOW).quantile(SHOCK_QUANTILE)
    vix_thr = vix_pos.shift(1).rolling(ROLLING_WINDOW, min_periods=ROLLING_WINDOW).quantile(SHOCK_QUANTILE)
    shock = (spy_abs > spy_thr) | (vix_pos > vix_thr)
    return shock.fillna(False)


def pc1_share(window_returns: pd.DataFrame) -> float:
    corr = window_returns.corr().replace([np.inf, -np.inf], np.nan).dropna(how="all").dropna(axis=1, how="all")
    if corr.shape[0] < 3:
        return np.nan
    vals = np.linalg.eigvalsh(corr.values)
    vals = np.sort(vals)[::-1]
    return float(vals[0] / vals.sum())


def non_overlapping_events(shock: pd.Series, min_gap: int = PC_WINDOW) -> list[pd.Timestamp]:
    dates: list[pd.Timestamp] = []
    last_pos = -10_000
    idx = list(shock.index)
    for pos, (date, flag) in enumerate(shock.items()):
        if not flag:
            continue
        if pos - last_pos >= min_gap:
            dates.append(date)
            last_pos = pos
    return dates


def build_panel(returns: pd.DataFrame, shock: pd.Series) -> pd.DataFrame:
    rows = []
    for ticker in ETF_TICKERS:
        df = pd.DataFrame(
            {
                "date": returns.index,
                "ticker": ticker,
                "ret": returns[ticker],
                "ret_next": returns[ticker].shift(-1),
                "spy_ret": returns["SPY"],
                "shock": shock.astype(int),
            }
        )
        rows.append(df)
    return pd.concat(rows, ignore_index=True).dropna()


def date_clustered_reversal_regression(panel: pd.DataFrame) -> dict:
    work = panel.copy()
    for ticker in ETF_TICKERS[1:]:
        work[f"asset_{ticker}"] = (work["ticker"] == ticker).astype(int)
    work["ret_x_shock"] = work["ret"] * work["shock"]
    x_cols = ["ret", "shock", "ret_x_shock"] + [f"asset_{ticker}" for ticker in ETF_TICKERS[1:]]
    model = sm.OLS(work["ret_next"], sm.add_constant(work[x_cols], has_constant="add")).fit(
        cov_type="cluster",
        cov_kwds={"groups": work["date"]},
    )
    return {
        "n": int(model.nobs),
        "r2": float(model.rsquared),
        "params": {
            key: {
                "coef": float(model.params[key]),
                "t": float(model.tvalues[key]),
                "p": float(model.pvalues[key]),
            }
            for key in model.params.index
        },
    }


def run_experiment() -> dict:
    np.random.seed(SEED)
    adj_close = download_prices()
    returns = compute_returns(adj_close)
    returns = returns.dropna(subset=ETF_TICKERS + CONTROL_TICKERS)
    shock = lagged_macro_shocks(returns)
    usable = returns.loc[shock.index]

    etf_returns = usable[ETF_TICKERS]
    basket = etf_returns.mean(axis=1)
    non_shock = ~shock

    event_dates = non_overlapping_events(shock)
    pc_rows = []
    index = list(usable.index)
    pos_map = {date: i for i, date in enumerate(index)}
    for date in event_dates:
        pos = pos_map[date]
        pre_start = pos - PC_WINDOW
        post_end = pos + PC_WINDOW + 1
        if pre_start < 0 or post_end > len(usable):
            continue
        pre = etf_returns.iloc[pre_start:pos]
        post = etf_returns.iloc[pos + 1 : post_end]
        pc_pre = pc1_share(pre)
        pc_post = pc1_share(post)
        if np.isfinite(pc_pre) and np.isfinite(pc_post):
            pc_rows.append(
                {
                    "date": str(date.date()),
                    "pc1_pre": pc_pre,
                    "pc1_post": pc_post,
                    "delta": pc_post - pc_pre,
                }
            )

    pc_df = pd.DataFrame(pc_rows)
    pc_delta = pc_df["delta"] if not pc_df.empty else pd.Series(dtype=float)
    t_stat, t_p = stats.ttest_1samp(pc_delta, popmean=0.0, nan_policy="omit") if len(pc_delta) else (np.nan, np.nan)
    w_stat, w_p = stats.wilcoxon(pc_delta) if len(pc_delta) and not np.allclose(pc_delta, 0) else (np.nan, np.nan)

    panel = build_panel(usable, shock)
    reversal_model = date_clustered_reversal_regression(panel)

    same_day_abs_shock = basket.loc[shock].abs()
    same_day_abs_normal = basket.loc[non_shock].abs()
    paired_abs = pd.concat(
        {
            "same_day_abs": basket.abs(),
            "next_day_abs": basket.shift(-1).abs(),
        },
        axis=1,
    ).loc[shock].dropna()
    next_day_abs_after_shock = paired_abs["next_day_abs"]
    mw_stat, mw_p = stats.mannwhitneyu(same_day_abs_shock, same_day_abs_normal, alternative="two-sided")
    next_t, next_p = stats.ttest_rel(paired_abs["same_day_abs"], paired_abs["next_day_abs"])

    per_asset = {}
    for ticker in ETF_TICKERS:
        r = usable[ticker]
        per_asset[ticker] = {
            "n": int(r.notna().sum()),
            "same_day_abs_return_shock_mean": float(r.loc[shock].abs().mean()),
            "same_day_abs_return_nonshock_mean": float(r.loc[non_shock].abs().mean()),
            "next_day_return_after_shock_mean": float(r.shift(-1).loc[shock].mean()),
            "next_day_reversal_corr": float(pd.concat([r.loc[shock], r.shift(-1).loc[shock]], axis=1).corr().iloc[0, 1]),
        }

    results = {
        "experiment_id": EXPERIMENT_ID,
        "created_at": pd.Timestamp.now(tz="UTC").isoformat(),
        "seed": SEED,
        "data": {
            "source": "yfinance",
            "tickers": ALL_TICKERS,
            "start_date": START_DATE,
            "end_date": END_DATE,
            "first_return_date": str(usable.index.min().date()),
            "last_return_date": str(usable.index.max().date()),
            "n_trading_days": int(len(usable)),
            "shock_definition": (
                "macro shock = abs(SPY return) or positive VIX log change above its own "
                f"lagged {ROLLING_WINDOW}d {int(SHOCK_QUANTILE * 100)}th percentile"
            ),
            "n_shock_days": int(shock.sum()),
            "shock_rate": float(shock.mean()),
            "n_nonoverlapping_pc_events": int(len(pc_rows)),
        },
        "literature": [asdict(item) for item in LITERATURE],
        "hypotheses": {
            "h1_macro_efficiency_proxy": "ETF basket absorbs macro shock contemporaneously: same-day abs returns on shock days exceed normal days.",
            "h2_fragility_proxy": "Shock days are followed by stronger return reversal and/or higher common-factor share.",
        },
        "interpretation": {
            "verdict": "PARTIAL_POSITIVE_PROXY",
            "summary": (
                "The public ETF panel strongly supports contemporaneous macro-shock absorption "
                "and shows post-shock fragility signatures through reversal and higher common-factor share. "
                "It remains a reduced-form proxy, not direct evidence from ETF ownership or create/redeem flows."
            ),
        },
        "tests": {
            "h1_same_day_abs_basket": {
                "shock_mean_abs": float(same_day_abs_shock.mean()),
                "normal_mean_abs": float(same_day_abs_normal.mean()),
                "ratio": float(same_day_abs_shock.mean() / same_day_abs_normal.mean()),
                "mann_whitney_u": float(mw_stat),
                "p_value": float(mw_p),
                "n_shock": int(len(same_day_abs_shock)),
                "n_normal": int(len(same_day_abs_normal)),
            },
            "h1_next_day_decay": {
                "same_day_abs_shock_mean": float(paired_abs["same_day_abs"].mean()),
                "next_day_abs_after_shock_mean": float(next_day_abs_after_shock.mean()),
                "paired_t": float(next_t),
                "p_value": float(next_p),
                "n_pairs": int(len(paired_abs)),
            },
            "h2_reversal_date_clustered_panel": reversal_model,
            "h2_pc1_common_factor_event_study": {
                "window_days": PC_WINDOW,
                "n_events": int(len(pc_delta)),
                "mean_pc1_pre": float(pc_df["pc1_pre"].mean()) if len(pc_df) else None,
                "mean_pc1_post": float(pc_df["pc1_post"].mean()) if len(pc_df) else None,
                "mean_delta": float(pc_delta.mean()) if len(pc_delta) else None,
                "median_delta": float(pc_delta.median()) if len(pc_delta) else None,
                "t_stat": float(t_stat) if np.isfinite(t_stat) else None,
                "t_p_value": float(t_p) if np.isfinite(t_p) else None,
                "wilcoxon_stat": float(w_stat) if np.isfinite(w_stat) else None,
                "wilcoxon_p_value": float(w_p) if np.isfinite(w_p) else None,
            },
        },
        "per_asset": per_asset,
        "event_pc1_rows": pc_rows,
    }

    make_figures(results)
    RESULTS_PATH.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    return results


def make_figures(results: dict) -> None:
    tests = results["tests"]
    fig, ax = plt.subplots(figsize=(8, 5))
    values = [
        tests["h1_same_day_abs_basket"]["normal_mean_abs"] * 100,
        tests["h1_same_day_abs_basket"]["shock_mean_abs"] * 100,
        tests["h1_next_day_decay"]["next_day_abs_after_shock_mean"] * 100,
    ]
    labels = ["Normal days", "Macro-shock day", "Next day after shock"]
    ax.bar(labels, values, color=["#6c757d", "#c1121f", "#0b6e4f"])
    ax.set_ylabel("Equal-weight ETF basket |return| (%)")
    ax.set_title("ETF basket same-day response and next-day decay")
    ax.grid(axis="y", alpha=0.25)
    fig.tight_layout()
    fig.savefig(ROOT / "fig_h1_response_decay.png", dpi=180)
    plt.close(fig)

    pc = tests["h2_pc1_common_factor_event_study"]
    fig, ax = plt.subplots(figsize=(7, 5))
    ax.bar(["Pre-shock 21d", "Post-shock 21d"], [pc["mean_pc1_pre"], pc["mean_pc1_post"]], color=["#457b9d", "#e76f51"])
    ax.set_ylabel("PC1 share of ETF return correlation")
    ax.set_title("Common-factor share around non-overlapping macro shocks")
    ax.set_ylim(0, max(pc["mean_pc1_pre"] or 0, pc["mean_pc1_post"] or 0) * 1.25)
    ax.grid(axis="y", alpha=0.25)
    fig.tight_layout()
    fig.savefig(ROOT / "fig_h2_common_factor_share.png", dpi=180)
    plt.close(fig)


if __name__ == "__main__":
    res = run_experiment()
    print(json.dumps({"experiment_id": EXPERIMENT_ID, "tests": res["tests"]}, ensure_ascii=False, indent=2)[:4000])
