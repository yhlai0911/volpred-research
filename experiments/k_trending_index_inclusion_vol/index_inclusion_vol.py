"""
Index inclusion as a predictable volatility event — event study.

Motivation
----------
When trillions of passive AUM (ETFs / pension / target-date funds) are
mechanically forced to buy a newly-included mega-cap within a short rebalance
window, this produces measurable, ex-ante-predictable volatility and volume
anomalies around the inclusion date. Tesla's 2020 S&P 500 inclusion is the
single largest addition in history and serves as the canonical case study.

Three event studies / fact blocks (all from yfinance real data, no lookahead):
  1. Tesla S&P 500 inclusion event study
       announce 2020-11-16, effective 2020-12-21
  2. Russell rebalance day volume spike (IWM), last 3 years
  3. >= 3 independently verifiable quantitative facts

Timing discipline: realized vol uses trailing 20d window (no future bars);
volume multiples use trailing 60d mean known *before* the event day. No random
sampling needed; numpy seed fixed anyway for reproducibility.

Outputs:
  index_inclusion_vol_results.json
  tsla_realized_vol.png
  tsla_volume_multiple.png
"""

import json
import warnings
from datetime import datetime

import numpy as np
import pandas as pd
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import yfinance as yf

warnings.filterwarnings("ignore")
np.random.seed(42)

OUTDIR = "experiments/k_trending_index_inclusion_vol"
TRADING_DAYS = 252


def fetch(ticker, start, end):
    df = yf.download(ticker, start=start, end=end, auto_adjust=False, progress=False)
    if df is None or df.empty:
        raise RuntimeError(f"yfinance returned no data for {ticker} {start}..{end}")
    # flatten possible MultiIndex columns
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    return df


def rolling_realized_vol(close, window=20):
    """Annualized realized vol from trailing `window` daily log returns.

    Uses .rolling(window) which only looks backward => no lookahead.
    """
    logret = np.log(close / close.shift(1))
    rv = logret.rolling(window).std() * np.sqrt(TRADING_DAYS)
    return rv


def main():
    results = {
        "experiment_id": "k_trending_index_inclusion_vol",
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "data_source": "yfinance (Yahoo Finance), auto_adjust=False",
        "timing_note": "20d realized vol = trailing window (no lookahead); "
        "volume multiple = day volume / trailing 60d mean known before event day",
        "events": {},
        "facts": [],
    }

    # ------------------------------------------------------------------
    # 1. Tesla S&P 500 inclusion event study
    # ------------------------------------------------------------------
    announce = pd.Timestamp("2020-11-16")
    effective = pd.Timestamp("2020-12-21")
    tsla = fetch("TSLA", "2020-06-01", "2021-03-31")
    close = tsla["Close"]
    volume = tsla["Volume"]

    # nearest trading day on/after a calendar date
    def trading_on_or_after(idx, ts):
        sub = idx[idx >= ts]
        return sub[0] if len(sub) else None

    def trading_on_or_before(idx, ts):
        sub = idx[idx <= ts]
        return sub[-1] if len(sub) else None

    ann_td = trading_on_or_after(close.index, announce)
    eff_td = trading_on_or_after(close.index, effective)

    # announce -> effective cumulative return (front-running / run-up)
    px_ann = float(close.loc[ann_td])
    # day before effective close (last full session before index funds buy at close)
    eff_prev = trading_on_or_before(close.index, effective - pd.Timedelta(days=1))
    px_eff = float(close.loc[eff_td])
    px_eff_prev = float(close.loc[eff_prev])
    runup_ann_to_eff = px_eff / px_ann - 1.0
    runup_ann_to_effprev = px_eff_prev / px_ann - 1.0

    # 20d realized vol: before announce vs after effective
    rv = rolling_realized_vol(close, 20)
    rv_before = float(rv.loc[:ann_td].dropna().iloc[-1])  # last rv known at announce
    # rv 20 trading days after effective (post-inclusion realized window fully
    # populated by post-event returns)
    post_idx = rv.index[rv.index >= eff_td]
    rv_after_pos = post_idx[min(20, len(post_idx) - 1)]
    rv_after = float(rv.loc[rv_after_pos])

    # volume multiple on effective day vs trailing 60d mean (pre-event known)
    vol60 = volume.rolling(60).mean()
    eff_prev_for_vol = trading_on_or_before(volume.index, effective - pd.Timedelta(days=1))
    base_vol = float(vol60.loc[eff_prev_for_vol])
    eff_day_vol = float(volume.loc[eff_td])
    vol_mult_effective = eff_day_vol / base_vol
    # max single-day volume multiple in announce..effective+5 window
    win_start = ann_td
    win_end = post_idx[min(5, len(post_idx) - 1)]
    win_mask = (volume.index >= win_start) & (volume.index <= win_end)
    vol_mult_series = (volume / vol60.shift(1))[win_mask]
    max_vol_mult = float(vol_mult_series.max())
    max_vol_mult_day = str(vol_mult_series.idxmax().date())

    results["events"]["tesla_sp500"] = {
        "ticker": "TSLA",
        "announce_date": "2020-11-16",
        "effective_date": "2020-12-21",
        "announce_trading_day": str(ann_td.date()),
        "effective_trading_day": str(eff_td.date()),
        "sample_days": int(len(close)),
        "data_period": "2020-06-01..2021-03-31",
        "price_at_announce": round(px_ann, 2),
        "price_at_effective": round(px_eff, 2),
        "price_day_before_effective": round(px_eff_prev, 2),
        "runup_announce_to_effective_pct": round(runup_ann_to_eff * 100, 2),
        "runup_announce_to_day_before_effective_pct": round(runup_ann_to_effprev * 100, 2),
        "rv20_before_announce_annualized": round(rv_before, 4),
        "rv20_20d_after_effective_annualized": round(rv_after, 4),
        "rv_change_pct": round((rv_after / rv_before - 1) * 100, 2),
        "effective_day_volume": int(eff_day_vol),
        "trailing_60d_mean_volume": int(base_vol),
        "volume_multiple_effective_day": round(vol_mult_effective, 2),
        "max_volume_multiple_in_window": round(max_vol_mult, 2),
        "max_volume_multiple_day": max_vol_mult_day,
    }

    # charts
    rv_plot = rv.dropna()
    rv_plot = rv_plot[(rv_plot.index >= "2020-09-01") & (rv_plot.index <= "2021-02-28")]
    fig, ax = plt.subplots(figsize=(10, 5))
    ax.plot(rv_plot.index, rv_plot.values * 100, color="#1f4e79", lw=1.6)
    ax.axvline(ann_td, color="#c0392b", ls="--", lw=1.3, label="納入宣布 2020-11-16")
    ax.axvline(eff_td, color="#27ae60", ls="--", lw=1.3, label="正式生效 2020-12-21")
    ax.set_title("Tesla 納入 S&P 500 前後 20 日年化已實現波動率", fontsize=13)
    ax.set_ylabel("Annualized realized vol (%)")
    ax.set_xlabel("Date")
    ax.legend(prop={"size": 9})
    ax.grid(alpha=0.25)
    fig.tight_layout()
    fig.savefig(f"{OUTDIR}/tsla_realized_vol.png", dpi=130)
    plt.close(fig)

    vm = (volume / vol60.shift(1)).dropna()
    vm = vm[(vm.index >= "2020-09-01") & (vm.index <= "2021-02-28")]
    fig, ax = plt.subplots(figsize=(10, 5))
    ax.bar(vm.index, vm.values, color="#7f8c8d", width=1.0)
    ax.axhline(1.0, color="black", lw=0.8)
    ax.axvline(eff_td, color="#27ae60", ls="--", lw=1.3, label="正式生效 2020-12-21")
    ax.axvline(ann_td, color="#c0392b", ls="--", lw=1.3, label="納入宣布 2020-11-16")
    ax.set_title("Tesla 單日成交量 ÷ 前 60 日均量（倍數）", fontsize=13)
    ax.set_ylabel("Volume / trailing 60d mean (x)")
    ax.set_xlabel("Date")
    ax.legend(prop={"size": 9})
    ax.grid(alpha=0.25, axis="y")
    fig.tight_layout()
    fig.savefig(f"{OUTDIR}/tsla_volume_multiple.png", dpi=130)
    plt.close(fig)

    # ------------------------------------------------------------------
    # 2. Russell rebalance day volume spike (IWM), last 3 years
    # ------------------------------------------------------------------
    iwm = fetch("IWM", "2021-01-01", "2024-12-31")
    iwm_vol = iwm["Volume"]
    iwm_vol60 = iwm_vol.rolling(60).mean()

    # Russell reconstitution effective = last Friday of June (close)
    def last_friday_of_june(year):
        d = pd.Timestamp(year=year, month=6, day=30)
        while d.weekday() != 4:  # Friday
            d -= pd.Timedelta(days=1)
        return d

    russell_rows = []
    for yr in [2022, 2023, 2024]:
        rd = last_friday_of_june(yr)
        td = trading_on_or_before(iwm_vol.index, rd)
        if td is None:
            continue
        prev = trading_on_or_before(iwm_vol.index, rd - pd.Timedelta(days=1))
        base = float(iwm_vol60.loc[prev])
        day_v = float(iwm_vol.loc[td])
        russell_rows.append(
            {
                "year": yr,
                "rebalance_day": str(td.date()),
                "volume": int(day_v),
                "trailing_60d_mean": int(base),
                "volume_multiple": round(day_v / base, 2),
            }
        )

    results["events"]["russell_rebalance_iwm"] = {
        "ticker": "IWM",
        "data_period": "2021-01-01..2024-12-31",
        "sample_days": int(len(iwm_vol)),
        "rebalance_rule": "last Friday of June (Russell reconstitution effective)",
        "years": russell_rows,
        "mean_volume_multiple": round(
            float(np.mean([r["volume_multiple"] for r in russell_rows])), 2
        )
        if russell_rows
        else None,
    }

    # ------------------------------------------------------------------
    # 3. Three independently verifiable facts
    # ------------------------------------------------------------------
    results["facts"] = [
        {
            "id": "F1",
            "statement": "TSLA announce->effective cumulative return",
            "value_pct": round(runup_ann_to_eff * 100, 2),
            "source": "yfinance TSLA Close 2020-11-16 -> 2020-12-21",
        },
        {
            "id": "F2",
            "statement": "TSLA effective-day volume as multiple of trailing 60d mean",
            "value_x": round(vol_mult_effective, 2),
            "source": "yfinance TSLA Volume 2020-12-21 vs trailing-60d mean",
        },
        {
            "id": "F3",
            "statement": "TSLA 20d realized vol change, pre-announce vs 20d post-effective",
            "value_before": round(rv_before, 4),
            "value_after": round(rv_after, 4),
            "change_pct": round((rv_after / rv_before - 1) * 100, 2),
            "source": "yfinance TSLA Close, trailing 20d annualized RV",
        },
        {
            "id": "F4",
            "statement": "IWM Russell rebalance-day mean volume multiple (2022-2024)",
            "value_x": results["events"]["russell_rebalance_iwm"]["mean_volume_multiple"],
            "source": "yfinance IWM Volume on last-Friday-of-June vs trailing 60d mean",
        },
    ]

    with open(f"{OUTDIR}/index_inclusion_vol_results.json", "w") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    print(json.dumps(results["events"]["tesla_sp500"], indent=2, ensure_ascii=False))
    print("\nRussell:")
    print(json.dumps(results["events"]["russell_rebalance_iwm"], indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
