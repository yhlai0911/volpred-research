"""K1253: SPY GARCH(1,1) rolling 1-step QLIKE smoke test.

Post-restore environment validation on 2026-04-18.
Data: yfinance SPY Adj Close log returns.
Lookahead-safe: prediction at t uses returns[:t] (excludes t itself).
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf
from arch import arch_model

np.random.seed(42)

DATA_START = "2020-01-01"
OOS_START = "2025-01-01"


def load_spy(end_date: str) -> pd.Series:
    data = yf.download(
        "SPY", start=DATA_START, end=end_date,
        auto_adjust=False, progress=False,
    )
    if isinstance(data.columns, pd.MultiIndex):
        data.columns = data.columns.get_level_values(0)
    price = data["Adj Close"].dropna()
    returns = np.log(price).diff().dropna() * 100.0
    returns.name = "SPY_logret_pct"
    return returns


def rolling_qlike(returns: pd.Series, oos_start: str) -> list[dict]:
    oos_dates = returns.index[returns.index >= oos_start]
    results: list[dict] = []
    for date in oos_dates:
        train_end_idx = returns.index.get_loc(date)
        train = returns.iloc[:train_end_idx]
        if len(train) < 252:
            continue
        model = arch_model(train, vol="GARCH", p=1, q=1, rescale=False)
        fit = model.fit(disp="off", show_warning=False)
        forecast = fit.forecast(horizon=1, reindex=False)
        pred_var = float(forecast.variance.iloc[-1, 0])
        realized = float(returns.loc[date])
        realized_var = realized ** 2
        qlike = float(np.log(pred_var) + realized_var / pred_var)
        results.append({
            "date": str(date.date()),
            "pred_var": pred_var,
            "realized_var": realized_var,
            "qlike": qlike,
        })
    return results


def main() -> None:
    today = datetime.utcnow().strftime("%Y-%m-%d")
    returns = load_spy(end_date=today)
    print(f"Loaded SPY returns: {len(returns)} days, {returns.index[0].date()} to {returns.index[-1].date()}")

    results = rolling_qlike(returns, OOS_START)
    qlike_vals = np.array([r["qlike"] for r in results])

    summary = {
        "experiment_id": "K1253",
        "title": "SPY GARCH(1,1) rolling 1-step QLIKE smoke test",
        "data_source": "yfinance SPY Adj Close log returns",
        "period": f"{DATA_START} to {today}",
        "oos_start": OOS_START,
        "n_oos_days": len(results),
        "mean_qlike": float(qlike_vals.mean()),
        "median_qlike": float(np.median(qlike_vals)),
        "std_qlike": float(qlike_vals.std()),
        "model": "GARCH(1,1) via arch package",
        "seed": 42,
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "lookahead_safe": "prediction at t uses returns[:t], realized is returns[t]",
        "rolling_results": results,
    }

    out = Path(__file__).parent / "k1253_results.json"
    out.write_text(json.dumps(summary, indent=2, ensure_ascii=False))
    print(f"✓ QLIKE mean = {summary['mean_qlike']:.4f} (std = {summary['std_qlike']:.4f})")
    print(f"  OOS days = {summary['n_oos_days']}")
    print(f"  Saved: {out}")


if __name__ == "__main__":
    main()
