#!/usr/bin/env python3
"""K1602: Tax-loss-harvesting crowding and the year-end single-stock RV reversal.

Tests the tax-loss-selling hypothesis (Roll 1983; Ritter 1988) as a cross-sectional
single-stock anomaly, and whether it is amplified in the direct-indexing era (2015+).

Signal (lag-safe): YTD return through Nov 30 of year Y -> loser (bottom tercile) vs
winner (top tercile) groups. Outcomes (strictly after Nov 30): December return / RV
and the January (Y+1) reversal return / RV. Inference is on the per-year loser-minus-
winner differential series (year is the cluster unit; NOT pooled stock-year iid).

Differentiation from K676 (personal-TLH-useless): K1602 is a market/cross-sectional
anomaly question, not a personal after-tax-return question.

Run standalone or via compute_queue. Writes experiments/k1602/k1602_results.json.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager

for _font in ["Arial Unicode MS", "PingFang TC", "Heiti TC", "Hiragino Sans GB"]:
    try:
        font_manager.findfont(_font, fallback_to_default=False)
        plt.rcParams["font.sans-serif"] = [_font]
        break
    except Exception:
        continue
plt.rcParams["axes.unicode_minus"] = False

HERE = Path(__file__).resolve().parent
DATA_DIR = HERE / "data"
FIG_DIR = HERE / "figures"
DATA_DIR.mkdir(exist_ok=True)
FIG_DIR.mkdir(exist_ok=True)

SEED = 42
START = "2004-01-01"
GROUP_Q = 0.30            # bottom/top tercile-ish split
MIN_PER_GROUP = 8         # minimum names per group to keep a year
MIN_CLASS_OBS = 120       # min trading days in Jan1..Nov30 window to classify a stock
MIN_DEC_OBS = 10          # min trading days in December for RV
MIN_JAN_OBS = 10          # min trading days in January for reversal
BOOT_REPS = 10000
DI_ERA_YEAR = 2015        # direct-indexing era split

TICKERS = [
    # mega / large tech + semis
    "AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "AVGO", "ORCL", "CSCO", "ADBE",
    "CRM", "INTC", "AMD", "QCOM", "TXN", "IBM", "MU", "LRCX", "AMAT",
    # consumer disc / staples
    "HD", "MCD", "NKE", "SBUX", "TGT", "LOW", "COST", "WMT", "PG", "KO", "PEP", "DIS",
    # financials
    "JPM", "BAC", "WFC", "C", "GS", "MS", "AXP", "BLK", "SCHW",
    # health care
    "JNJ", "PFE", "MRK", "ABBV", "UNH", "LLY", "BMY", "AMGN", "GILD", "CVS",
    # industrials
    "BA", "CAT", "GE", "HON", "UNP", "MMM", "DE", "LMT", "RTX",
    # energy
    "XOM", "CVX", "COP", "SLB", "EOG", "OXY",
    # comm / media / telecom
    "T", "VZ", "CMCSA", "NFLX",
    # materials
    "LIN", "FCX", "NEM", "DOW",
    # cyclical / high-beta loser generators
    "F", "GM", "DAL", "UAL", "CCL", "NCLH", "MGM", "WYNN", "X", "CLF",
]
MARKET = "SPY"


# ---------------------------------------------------------------------------
# data
# ---------------------------------------------------------------------------
def download_close(ticker: str, refresh: bool) -> pd.Series:
    cache = DATA_DIR / f"{ticker}.csv"
    if cache.exists() and not refresh:
        s = pd.read_csv(cache, parse_dates=["Date"]).set_index("Date")["Close"].sort_index()
        return s
    import yfinance as yf

    hist = yf.Ticker(ticker).history(start=START, auto_adjust=True)
    if hist is None or hist.empty:
        raise RuntimeError(f"empty yfinance history for {ticker}")
    close = hist["Close"].copy()
    close.index = pd.to_datetime(close.index).tz_localize(None)
    close = close[~close.index.duplicated(keep="last")].sort_index()
    close.to_frame("Close").reset_index().rename(columns={"index": "Date"}).to_csv(
        cache, index=False
    )
    return close


def load_prices(refresh: bool) -> tuple[pd.DataFrame, list[str]]:
    closes, failed = {}, []
    for t in TICKERS + [MARKET]:
        try:
            closes[t] = download_close(t, refresh)
        except Exception as exc:  # noqa: BLE001
            failed.append(f"{t}: {exc}")
    df = pd.DataFrame(closes).sort_index()
    return df, failed


# ---------------------------------------------------------------------------
# window helpers
# ---------------------------------------------------------------------------
def window_slice(prices: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    """Rows with index in [start, end] (inclusive)."""
    return prices.loc[(prices.index >= start) & (prices.index <= end)]


def period_return(px: pd.Series) -> float:
    px = px.dropna()
    if len(px) < 2:
        return np.nan
    return float(px.iloc[-1] / px.iloc[0] - 1.0)


def annualized_rv(px: pd.Series, min_obs: int) -> float:
    px = px.dropna()
    if len(px) < min_obs:
        return np.nan
    r = np.log(px / px.shift(1)).dropna()
    if len(r) < 2:
        return np.nan
    return float(r.std(ddof=1) * np.sqrt(252.0))


# ---------------------------------------------------------------------------
# per-year cross-section
# ---------------------------------------------------------------------------
def build_year_panel(prices: pd.DataFrame) -> pd.DataFrame:
    """One row per (year, ticker) with the lag-safe loss signal + outcome metrics."""
    rows = []
    available_tickers = [t for t in TICKERS if t in prices.columns]
    years = sorted({d.year for d in prices.index})
    for y in years:
        class_start = pd.Timestamp(y, 1, 1)
        class_end = pd.Timestamp(y, 11, 30)
        dec_start = pd.Timestamp(y, 12, 1)
        dec_end = pd.Timestamp(y, 12, 31)
        dec15_start = pd.Timestamp(y, 12, 15)
        jan_start = pd.Timestamp(y + 1, 1, 1)
        jan_end = pd.Timestamp(y + 1, 1, 31)

        # need next-January data to exist for the reversal outcome
        if prices.loc[prices.index >= jan_start].shape[0] == 0:
            continue

        class_px = window_slice(prices, class_start, class_end)
        dec_px = window_slice(prices, dec_start, dec_end)
        dec15_px = window_slice(prices, dec15_start, dec_end)
        jan_px = window_slice(prices, jan_start, jan_end)
        if jan_px.shape[0] < MIN_JAN_OBS or dec_px.shape[0] < MIN_DEC_OBS:
            continue

        for t in available_tickers:
            cser = class_px[t].dropna()
            if len(cser) < MIN_CLASS_OBS:
                continue
            ytd = float(cser.iloc[-1] / cser.iloc[0] - 1.0)
            dec_ret = period_return(dec_px[t])
            dec15_ret = period_return(dec15_px[t])
            jan_ret = period_return(jan_px[t])
            dec_rv = annualized_rv(dec_px[t], MIN_DEC_OBS)
            jan_rv = annualized_rv(jan_px[t], MIN_JAN_OBS)
            if np.isnan(jan_ret) or np.isnan(dec_ret):
                continue
            rows.append(
                dict(year=y, ticker=t, ytd=ytd, dec_ret=dec_ret, dec15_ret=dec15_ret,
                     jan_ret=jan_ret, dec_rv=dec_rv, jan_rv=jan_rv)
            )
    return pd.DataFrame(rows)


def year_differentials(panel: pd.DataFrame) -> pd.DataFrame:
    """Per year: loser-group mean minus winner-group mean of each outcome."""
    recs = []
    for y, g in panel.groupby("year"):
        g = g.dropna(subset=["ytd"])
        n = len(g)
        if n < 2 * MIN_PER_GROUP:
            continue
        lo = g["ytd"].quantile(GROUP_Q)
        hi = g["ytd"].quantile(1 - GROUP_Q)
        losers = g[g["ytd"] <= lo]
        winners = g[g["ytd"] >= hi]
        if len(losers) < MIN_PER_GROUP or len(winners) < MIN_PER_GROUP:
            continue
        rec = dict(year=int(y), n=n, n_loser=len(losers), n_winner=len(winners),
                   loser_ytd=float(losers["ytd"].mean()), winner_ytd=float(winners["ytd"].mean()))
        for m in ["dec_ret", "dec15_ret", "jan_ret", "dec_rv", "jan_rv"]:
            rec[f"d_{m}"] = float(losers[m].mean() - winners[m].mean())
        recs.append(rec)
    return pd.DataFrame(recs).sort_values("year").reset_index(drop=True)


# ---------------------------------------------------------------------------
# inference
# ---------------------------------------------------------------------------
def ttest_mean_zero(x: np.ndarray) -> dict:
    x = np.asarray(x, dtype=float)
    x = x[~np.isnan(x)]
    n = len(x)
    if n < 3:
        return dict(n=n, mean=float(np.mean(x)) if n else float("nan"),
                    t=float("nan"), p=float("nan"))
    mean = float(np.mean(x))
    se = float(np.std(x, ddof=1) / np.sqrt(n))
    t = mean / se if se > 0 else float("nan")
    # two-sided p via Student-t; the Harvey |t| gate and bootstrap CI are primary.
    from scipy import stats as scipy_stats

    p = float(2 * scipy_stats.t.sf(abs(t), df=n - 1)) if np.isfinite(t) else float("nan")
    return dict(n=n, mean=mean, se=se, t=t, p=p)


def year_bootstrap_ci(x: np.ndarray, reps: int, seed: int) -> dict:
    x = np.asarray(x, dtype=float)
    x = x[~np.isnan(x)]
    n = len(x)
    if n < 3:
        return dict(lo=float("nan"), hi=float("nan"), frac_pos=float("nan"))
    rng = np.random.default_rng(seed)
    means = np.empty(reps)
    for b in range(reps):
        idx = rng.integers(0, n, size=n)
        means[b] = x[idx].mean()
    return dict(lo=float(np.percentile(means, 2.5)),
                hi=float(np.percentile(means, 97.5)),
                frac_pos=float(np.mean(means > 0)))


def analyse_metric(diffs: pd.DataFrame, col: str) -> dict:
    # per-year differentials are stored with a "d_" prefix by year_differentials()
    dcol = f"d_{col}"
    x = diffs[dcol].to_numpy()
    out = ttest_mean_zero(x)
    out.update(year_bootstrap_ci(x, BOOT_REPS, SEED))
    # subsample: pre vs DI era
    pre = diffs[diffs["year"] < DI_ERA_YEAR][dcol].to_numpy()
    post = diffs[diffs["year"] >= DI_ERA_YEAR][dcol].to_numpy()
    out["pre2015"] = ttest_mean_zero(pre)
    out["post2015"] = ttest_mean_zero(post)
    return out


# ---------------------------------------------------------------------------
# figures
# ---------------------------------------------------------------------------
def make_figures(diffs: pd.DataFrame, stats: dict) -> list[str]:
    paths = []
    # Fig A: per-year January reversal differential (H2)
    fig, ax = plt.subplots(figsize=(9, 4.5))
    colors = ["#2b8cbe" if v >= 0 else "#e34a33" for v in diffs["d_jan_ret"]]
    ax.bar(diffs["year"], diffs["d_jan_ret"] * 100, color=colors)
    ax.axhline(0, color="black", lw=0.8)
    m = stats["jan_ret"]["mean"] * 100
    ax.axhline(m, color="#31a354", ls="--", lw=1.2, label=f"mean {m:+.2f}%")
    ax.set_title("H2 January reversal: loser−winner Jan return by year")
    ax.set_xlabel("classification year")
    ax.set_ylabel("loser−winner Jan return (%)")
    ax.legend()
    fig.tight_layout()
    p = FIG_DIR / "fig_a_jan_reversal.png"
    fig.savefig(p, dpi=130)
    plt.close(fig)
    paths.append(str(p))

    # Fig B: summary bar of the four primary metric means with bootstrap CI
    fig, ax = plt.subplots(figsize=(8, 4.5))
    metrics = [("dec_ret", "Dec ret (H1)"), ("jan_ret", "Jan ret (H2)"),
               ("dec_rv", "Dec RV (H3)"), ("dec15_ret", "Dec15 ret")]
    means = [stats[m]["mean"] * 100 for m, _ in metrics]
    los = [stats[m]["lo"] * 100 for m, _ in metrics]
    his = [stats[m]["hi"] * 100 for m, _ in metrics]
    xs = np.arange(len(metrics))
    ax.bar(xs, means, color="#756bb1")
    ax.errorbar(xs, means, yerr=[np.array(means) - np.array(los), np.array(his) - np.array(means)],
                fmt="none", ecolor="black", capsize=4)
    ax.axhline(0, color="black", lw=0.8)
    ax.set_xticks(xs)
    ax.set_xticklabels([lbl for _, lbl in metrics])
    ax.set_ylabel("loser−winner mean (%), 95% year-bootstrap CI")
    ax.set_title("K1602 primary metrics: loser vs winner (year-clustered)")
    fig.tight_layout()
    p = FIG_DIR / "fig_b_summary.png"
    fig.savefig(p, dpi=130)
    plt.close(fig)
    paths.append(str(p))
    return paths


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
def verdict_from(stats: dict) -> str:
    jr = stats["jan_ret"]
    t = jr.get("t", float("nan"))
    frac = jr.get("frac_pos", float("nan"))
    ci_excludes_zero = np.isfinite(jr.get("lo", np.nan)) and (jr["lo"] > 0 or jr["hi"] < 0)
    if np.isfinite(t) and abs(t) >= 3.0 and ci_excludes_zero:
        return "PASS"
    if np.isfinite(t) and abs(t) >= 2.0 and ci_excludes_zero:
        return "SUGGESTIVE"
    return "NULL"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--refresh", action="store_true", help="refresh yfinance cache")
    args = ap.parse_args()

    prices, failed = load_prices(args.refresh)
    panel = build_year_panel(prices)
    diffs = year_differentials(panel)

    primary_cols = ["dec_ret", "dec15_ret", "jan_ret", "dec_rv", "jan_rv"]
    stats = {c: analyse_metric(diffs, c) for c in primary_cols}
    verdict = verdict_from(stats) if len(diffs) else "INSUFFICIENT_DATA"

    fig_paths = make_figures(diffs, stats) if len(diffs) else []
    loaded_tickers = [t for t in TICKERS if t in prices.columns]

    results = dict(
        experiment_id="K1602",
        title="Tax-loss-harvesting crowding and the year-end single-stock RV reversal",
        generated_at=datetime.now(timezone.utc).isoformat(),
        data_source="yfinance adjusted close (auto_adjust=True)",
        sample_start=START,
        n_tickers=len(TICKERS),
        n_tickers_loaded=len(loaded_tickers),
        market_loaded=bool(MARKET in prices.columns),
        failed_downloads=failed,
        n_years=int(len(diffs)),
        years=[int(y) for y in diffs["year"].tolist()],
        config=dict(group_q=GROUP_Q, min_per_group=MIN_PER_GROUP,
                    min_class_obs=MIN_CLASS_OBS, boot_reps=BOOT_REPS,
                    seed=SEED, di_era_year=DI_ERA_YEAR),
        hypotheses=dict(
            H1_selling_pressure="loser-winner Dec return < 0",
            H2_reversal="loser-winner Jan return > 0 (primary)",
            H3_rv="loser-winner Dec RV > 0",
            H4_crowding="H2 stronger post-2015",
        ),
        stats=stats,
        year_differentials=diffs.to_dict(orient="records"),
        figures=fig_paths,
        verdict=verdict,
        lookahead_note=("classification uses data <= Nov 30 of year Y; all outcome "
                        "windows start Dec 1 (Y) or Jan 1 (Y+1), strictly after the "
                        "signal. Inference on per-year loser-winner differentials "
                        "(year is the cluster unit, not pooled stock-year iid)."),
        caveats=[
            "yfinance survivorship bias: delisted losers excluded -> biases AGAINST "
            "the tax-loss effect (conservative).",
            "fixed universe, not point-in-time index membership.",
            "US-only; year-level N is moderate (~20).",
        ],
    )

    out = HERE / "k1602_results.json"
    out.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"[K1602] years={len(diffs)} tickers_loaded={len(loaded_tickers)} failed={len(failed)}")
    for c in ["dec_ret", "jan_ret", "dec_rv"]:
        s = stats[c]
        print(f"  {c:10s} mean={s['mean']*100:+.3f}% t={s.get('t', float('nan')):+.2f} "
              f"CI=[{s['lo']*100:+.2f},{s['hi']*100:+.2f}]% frac_pos={s.get('frac_pos', float('nan')):.2f}")
    print(f"  VERDICT={verdict}")
    print(f"  results -> {out}")


if __name__ == "__main__":
    main()
