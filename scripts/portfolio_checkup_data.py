#!/usr/bin/env python3
"""Data behind the 投資健檢 tab: what a reader's holdings do *together*.

The existing risk forecast answers "how volatile is EEM", one ticker at a time.
Nobody holds one ticker. They hold four and believe that makes them safe. This
file produces the structure needed to tell them whether it does.

## The measure, and the one that was rejected

The tab reports an **effective number of holdings**: the diversification ratio
(sum of weighted individual volatilities over portfolio volatility) squared.
Hold four things that never move together and it reads 4; hold four things that
move as one and it reads 1. It needs only a covariance matrix.

It is computed twice -- over all days, and over the worst decile of days for the
common equity factor (SPY). The second is what the reader actually fears: not
"are these correlated on average" but "when the market breaks, do these all
break together".

An earlier version used exceedance correlation: correlation among days when
*both* assets sat in their own worst 20%, benchmarked against a Gaussian copula
of the same unconditional rho. It was thrown away, and the reason is worth
keeping. Conditioning on two left tails at once attenuates measured correlation
severely, and by an amount that depends on the shape of the joint distribution:
the Gaussian benchmark for SPY/QQQ collapsed from rho 0.92 to 0.75, and for
SPY/EEM from 0.74 to 0.37. The "excess" over that benchmark was therefore
mostly a statement about how differently double truncation bit the two
distributions, not about tail dependence. The tell was that all fifteen pairs
came out positive -- fifteen findings sharing a sign is an estimator signature,
not fifteen discoveries -- and that it contradicted this platform's own
published GLD/SPY near-zero tail dependence result. Standardising returns by a
lagged rolling volatility did not fix it, which ruled out volatility clustering
as the cause.

Conditioning on a *single* common factor keeps the selection one-dimensional,
applies the identical condition to every asset, and is the scenario a reader is
actually asking about.

## Honesty boundary

This is a conditional-covariance statement over a specific historical window,
not a copula tail-dependence estimate and not a forecast. The tab says so.

Output: storage/portfolio_checkup.json (read by the /checkup route).
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from volpred.data.manager import DataManager  # noqa: E402

# The same six the risk forecast already models, so a per-asset number can
# never disagree between this tab and /risk-forecast. This file adds structure
# *between* them; it does not re-forecast them.
TICKERS: dict[str, str] = {
    "SPY": "美國大型股 (S&P 500)",
    "QQQ": "美國科技股 (Nasdaq 100)",
    "GLD": "黃金",
    "TLT": "美國長期公債",
    "0050.TW": "台灣 50",
    "EEM": "新興市場",
}

STRESS_PROXY = "SPY"      # the common factor whose bad days define a crisis
STRESS_Q = 0.10           # worst decile of that factor
LOOKBACK_START = "2019-01-01"   # includes COVID, the 2022 bear, and 2025-26
MIN_STRESS_OBS = 60       # below this the crisis matrix is not reported at all


def _returns() -> pd.DataFrame:
    dm = DataManager()
    end = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    series = {}
    for ticker in TICKERS:
        frame = dm.get_price_data(ticker, LOOKBACK_START, end)
        close = frame["Close"] if "Close" in frame.columns else frame.iloc[:, 0]
        series[ticker] = np.log(close / close.shift(1))
    # Inner join: only days every market traded, so a Taiwan holiday cannot
    # masquerade as a calm day and dilute the covariance.
    return pd.DataFrame(series).dropna()


def _matrix(frame: pd.DataFrame) -> dict[str, dict[str, float]]:
    corr = frame.corr()
    return {a: {b: round(float(corr.loc[a, b]), 4) for b in corr.columns} for a in corr.index}


def _vols(frame: pd.DataFrame) -> dict[str, float]:
    return {t: round(float(frame[t].std() * np.sqrt(252) * 100), 3) for t in frame.columns}


def main() -> int:
    rets = _returns()

    stress_cut = float(rets[STRESS_PROXY].quantile(STRESS_Q))
    stressed = rets[rets[STRESS_PROXY] <= stress_cut]
    if len(stressed) < MIN_STRESS_OBS:
        print(
            f"ERROR: only {len(stressed)} stress days (need {MIN_STRESS_OBS}); "
            "refusing to publish a crisis matrix on this sample",
            file=sys.stderr,
        )
        return 1

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "sample": {
            "start": str(rets.index[0].date()),
            "end": str(rets.index[-1].date()),
            "trading_days": int(len(rets)),
            "stress_days": int(len(stressed)),
            "stress_proxy": STRESS_PROXY,
            "stress_threshold_pct": round(stress_cut * 100, 2),
        },
        "method": {
            "measure": "diversification_ratio_squared",
            "definition": "(Σ wᵢσᵢ / σ_portfolio)²",
            "crisis_condition": f"{STRESS_PROXY} 當日報酬落在最差 {int(STRESS_Q*100)}%",
            "note_zh": (
                "「幾檔的分散效果」= 分散比率的平方。持有四檔完全不同步的資產會讀到 4，"
                "持有四檔同進同出的會讀到 1。危機欄位是同一個算法，只是改用美股最差 "
                f"{int(STRESS_Q*100)}% 的日子重算相關性。"
            ),
            "limits_zh": (
                "這是特定歷史期間的條件共變異數，不是尾部相依估計，也不是預測。"
                "換一段期間、換一個危機定義，數字會變。"
            ),
        },
        "assets": {
            t: {
                "label": label,
                "ann_vol_pct": _vols(rets)[t],
                "ann_vol_stress_pct": _vols(stressed)[t],
                "worst_day_pct": round(float(rets[t].min() * 100), 2),
            }
            for t, label in TICKERS.items()
        },
        "correlations": {"normal": _matrix(rets), "crisis": _matrix(stressed)},
        "vols": {"normal": _vols(rets), "crisis": _vols(stressed)},
    }

    out = ROOT / "storage" / "portfolio_checkup.json"
    out.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"wrote {out}")
    print(f"  sample {rets.index[0].date()} → {rets.index[-1].date()}  "
          f"({len(rets)} days, {len(stressed)} stress days, "
          f"{STRESS_PROXY} ≤ {stress_cut*100:.2f}%)")
    print("  平常 → 危機 相關性：")
    cols = list(rets.columns)
    for i, a in enumerate(cols):
        for b in cols[i + 1:]:
            n = payload["correlations"]["normal"][a][b]
            c = payload["correlations"]["crisis"][a][b]
            flag = "  ← 明顯上升" if c - n > 0.15 else ""
            print(f"    {a:>8} / {b:<8} {n:+.2f} → {c:+.2f}{flag}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
