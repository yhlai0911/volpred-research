"""Monthly persistence stability check for adaptive window selection.

Run monthly to verify if asset-specific optimal windows need updating.
Rule: persistence_std < 0.02 → w=504, > 0.05 → w=252, in between → w=378

Current recommendations (Phase H, 2026-03-15):
  SPY: w=504 (stable, std=0.007-0.012)
  TLT: w=252 (unstable, std=0.064-0.214)
  GLD: w=252→504 transition (stabilizing, std dropped to 0.019)
  BTC: w=252 (was unstable, 2025 std=0.026 suggests stabilizing)
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

import numpy as np
import pandas as pd
from arch import arch_model
from volpred.data.manager import DataManager


def _warn_persistence(message, *, exc=None, **context):
    parts = [f"{key}={value}" for key, value in context.items() if value is not None]
    if exc is not None:
        parts.append(f"error={type(exc).__name__}: {exc}")
    suffix = f" {' '.join(parts)}" if parts else ""
    print(f"[persistence-stability] WARN {message}{suffix}", file=sys.stderr)


def check_persistence_stability(asset, start="2022-01-01"):
    dm = DataManager()
    data = dm.get_model_data(asset, start, "2026-12-31")
    returns = data["returns"]

    persistences = []
    dates = []
    fit_failures = 0
    for i in range(504, len(returns)):
        train = returns.iloc[i-252:i]
        am = arch_model(train * 100, vol="GARCH", p=1, o=1, q=1,
                        mean="Zero", dist="normal")
        try:
            res = am.fit(disp="off")
            p = res.params
            pers = p.get("alpha[1]", 0) + p.get("gamma[1]", 0)/2 + p.get("beta[1]", 0)
            persistences.append(pers)
            dates.append(returns.index[i])
        except Exception as exc:
            fit_failures += 1
            if fit_failures <= 5:
                _warn_persistence(
                    "GARCH fit failed; skipping rolling window",
                    asset=asset,
                    date=returns.index[i],
                    exc=exc,
                )
            continue
    if fit_failures > 5:
        _warn_persistence(
            "additional GARCH fit failures suppressed",
            asset=asset,
            count=fit_failures - 5,
        )

    pers_series = pd.Series(persistences, index=dates[:len(persistences)])
    pers_std = pers_series.rolling(60).std()

    # Recent 60-day stability
    recent_std = float(pers_std.iloc[-1]) if len(pers_std) > 0 else float('nan')
    recent_pers = float(pers_series.iloc[-60:].mean()) if len(pers_series) >= 60 else float('nan')

    # Recommend window
    if recent_std < 0.02:
        recommended_window = 504
        status = "STABLE"
    elif recent_std > 0.05:
        recommended_window = 252
        status = "UNSTABLE"
    else:
        recommended_window = 378
        status = "MODERATE"

    return {
        'asset': asset,
        'recent_std': recent_std,
        'recent_pers': recent_pers,
        'recommended_window': recommended_window,
        'status': status,
    }


def main():
    print("=== Persistence Stability Check ===")
    print(f"Date: {pd.Timestamp.now().strftime('%Y-%m-%d')}")
    print()

    assets = ['SPY', 'TLT', 'GLD']
    for asset in assets:
        try:
            result = check_persistence_stability(asset)
            print(f"{result['asset']}: std={result['recent_std']:.4f}, "
                  f"pers={result['recent_pers']:.4f}, "
                  f"→ w={result['recommended_window']} ({result['status']})")
        except Exception as e:
            print(f"{asset}: ERROR - {e}")

    print()
    print("Rule: std<0.02→w=504, std>0.05→w=252, between→w=378")


if __name__ == '__main__':
    main()
