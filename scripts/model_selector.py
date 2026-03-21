#!/usr/bin/env python3
"""Automated GARCH model selection based on leverage direction (gamma).

Implements the γ-based model selection rule from the research paper:
- Estimate GJR-GARCH on 4 quarterly windows
- If mean γ > 0.05 AND >50% quarters positive → GJR
- Otherwise → GARCH

Usage:
    uv run python scripts/model_selector.py --asset SPY
    uv run python scripts/model_selector.py --asset GLD --window 504
    uv run python scripts/model_selector.py  # All default assets
"""
import argparse
import sys
from pathlib import Path

import numpy as np
from arch import arch_model

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from volpred.data.manager import DataManager


def estimate_gamma(returns_pct: np.ndarray, window: int = 504) -> dict:
    """Estimate GJR-GARCH gamma on the given window."""
    try:
        import pandas as pd
        series = pd.Series(returns_pct[-window:])
        am = arch_model(series, vol='GARCH', p=1, o=1, q=1,
                       dist='normal', mean='Zero', rescale=False)
        res = am.fit(disp='off', show_warning=False)
        return {
            'gamma': float(res.params.get('gamma[1]', 0)),
            'gamma_tstat': float(res.tvalues.get('gamma[1]', 0)),
            'alpha': float(res.params.get('alpha[1]', 0)),
            'beta': float(res.params.get('beta[1]', 0)),
            'persistence': float(res.params.get('alpha[1]', 0) +
                                res.params.get('gamma[1]', 0) / 2 +
                                res.params.get('beta[1]', 0)),
        }
    except Exception as e:
        return {'gamma': 0, 'gamma_tstat': 0, 'alpha': 0, 'beta': 0,
                'persistence': 0, 'error': str(e)}


def select_model(asset: str, window: int = 504, n_quarters: int = 4,
                 gamma_threshold: float = 0.05, pct_positive_threshold: float = 50) -> dict:
    """Select GARCH or GJR based on multi-window gamma analysis.

    Returns dict with recommendation, gamma stats, and reasoning.
    """
    dm = DataManager()
    data = dm.get_model_data(asset, "2020-01-01", "2026-12-31")

    if len(data) < window + n_quarters * 63:
        return {'asset': asset, 'model': 'garch', 'reason': 'Insufficient data',
                'gammas': [], 'confidence': 'low'}

    returns_pct = data['returns'].values * 100
    step = 63  # Quarterly

    # Estimate gamma on last n_quarters windows
    gammas = []
    for q in range(n_quarters):
        end_idx = len(returns_pct) - q * step
        if end_idx < window:
            break
        result = estimate_gamma(returns_pct[:end_idx], window)
        gammas.append(result)

    if not gammas:
        return {'asset': asset, 'model': 'garch', 'reason': 'No valid estimates',
                'gammas': [], 'confidence': 'low'}

    gamma_values = [g['gamma'] for g in gammas]
    mean_gamma = np.mean(gamma_values)
    pct_positive = sum(1 for g in gamma_values if g > 0) / len(gamma_values) * 100

    # Decision rule
    use_gjr = mean_gamma > gamma_threshold and pct_positive > pct_positive_threshold

    # Confidence assessment
    if abs(mean_gamma) > 0.15:
        confidence = 'high'
    elif abs(mean_gamma) > 0.08:
        confidence = 'medium'
    else:
        confidence = 'low'

    model = 'gjr' if use_gjr else 'garch'

    # Leverage direction classification
    if pct_positive > 75:
        direction = 'standard'
    elif pct_positive < 25:
        direction = 'inverted'
    else:
        direction = 'mixed'

    return {
        'asset': asset,
        'model': model,
        'model_full': f"{'GJR-' if use_gjr else ''}GARCH(1,1)",
        'window': window,
        'mean_gamma': round(mean_gamma, 4),
        'pct_positive': round(pct_positive, 1),
        'direction': direction,
        'confidence': confidence,
        'n_quarters': len(gammas),
        'gammas': [round(g, 4) for g in gamma_values],
        'latest_tstat': round(gammas[0]['gamma_tstat'], 2),
        'persistence': round(gammas[0]['persistence'], 4),
        'reason': (f"mean_γ={mean_gamma:+.4f}, {pct_positive:.0f}% positive → "
                  f"{'GJR (standard leverage)' if use_gjr else 'GARCH (inverted/neutral leverage)'}"),
    }


def main():
    parser = argparse.ArgumentParser(description='GARCH Model Selector')
    parser.add_argument('--asset', default=None, help='Asset ticker (default: all)')
    parser.add_argument('--window', type=int, default=504, help='Estimation window')
    args = parser.parse_args()

    assets = [args.asset] if args.asset else ['SPY', 'QQQ', 'GLD', 'TLT', 'BTC-USD', 'EEM']

    print("=== Automated GARCH Model Selection ===\n")
    print(f"Rule: mean γ > 0.05 AND >50% quarters positive → GJR, else GARCH\n")

    for asset in assets:
        result = select_model(asset, window=args.window)
        direction_emoji = {'standard': '↓', 'inverted': '↑', 'mixed': '≈'}
        d = direction_emoji.get(result['direction'], '?')

        print(f"{asset:>8}: {result['model_full']:>15} | γ={result['mean_gamma']:+.4f} "
              f"({result['pct_positive']:.0f}% pos) | {result['direction']} {d} | "
              f"conf={result['confidence']} | t={result['latest_tstat']:.1f}")


if __name__ == '__main__':
    main()
