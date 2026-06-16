"""
K1509: TIPS Regime-Conditional Volatility Decomposition
=======================================================

Single research question:
  In high CPI YoY (>3%) regime vs normal regime, do TIPS ETFs (TIP / STIP / LTPZ)
  exhibit a significant difference in RV, tail risk (ES 5%), and their RV gap
  vs nominal Treasury (IEF)?
  Direction: do TIPS carry a vol *premium* (補貼) or vol *discount* (折扣)
  in high-inflation regimes?

Method
------
- Period: 2015-01-01 to 2026-06-15 (daily; yfinance)
- Assets: TIP, STIP, LTPZ (TIPS ladder: short/aggregate/long), IEF (nominal Tsy)
  + AGG, ^TNX for context (descriptive only, no test).
- Regime label: CPI YoY (FRED CPIAUCSL).
  - Conservative lag: use CPI release ~1 mo after observation +
    forward-fill to daily and *lag 21 trading days* (~1 calendar month) again.
    Net: regime label on day t uses CPI YoY observed >=42 calendar days ago.
  - High regime = CPI YoY > 3%, normal otherwise.
- RV: rolling std of daily log returns x sqrt(252), windows 5d / 21d.
  - lookahead-safe: RV on day t built from returns up to t (uses t itself);
    when comparing across regimes we condition on regime label which uses
    only lagged CPI -- no leak. (We do NOT use RV to predict anything,
    only conditionally describe vol by regime.)
- Tail: empirical 5% ES of daily log returns within each regime.
- Tests:
  - Welch t-test on RV by regime (high vs normal), per asset x window
  - Bootstrap 95% CI (5000 reps, seed=42) on mean diff
  - Bonferroni: 3 TIPS x 2 windows = 6 RV tests; alpha = 0.05 / 6.
    (ES diff reported but not in primary multiple-comparison family.)
- Difference series: TIP_RV - IEF_RV, STIP_RV - IEF_RV, LTPZ_RV - IEF_RV;
  Welch t-test on this gap across regimes.

Differentiation vs K557 / K737
------------------------------
- K557: gold regime exposure -- different asset class, no TIPS, no CPI regime
- K737: max diversification basket -- portfolio construction, not regime
  decomposition
- K925: CPI *event* (announcement day) vol study on SPY -- event study,
  not regime conditioning, and on equity (SPY), not TIPS
- K1509 (this): regime-conditional RV/ES decomposition on TIPS ladder
  vs nominal Treasury -- new angle on whether TIPS "inflation protection"
  comes at a vol cost or vol benefit.

Limitations (built-in)
----------------------
- Only one high-CPI regime in sample (2021-2023 post-COVID surge).
  Cannot disentangle "high CPI" from "post-COVID dislocation / Fed hike cycle".
- Daily RV is noisy; intraday TIPS data not used.
- 5% ES is empirical and depends on regime sample size.
- TIP/STIP/LTPZ liquidity asymmetric -- LTPZ thin, may show idiosyncratic vol.

Outputs
-------
- experiments/k1509/k1509_results.json
- experiments/k1509/figures/fig_a_rv_by_regime.png
- experiments/k1509/figures/fig_b_rv_gap_vs_nominal.png
"""

from __future__ import annotations

import json
import os
import warnings
from datetime import datetime, timezone

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import yfinance as yf
from scipy import stats

warnings.filterwarnings('ignore')

SEED = 42
np.random.seed(SEED)

HERE = os.path.dirname(os.path.abspath(__file__))
FIG_DIR = os.path.join(HERE, 'figures')
os.makedirs(FIG_DIR, exist_ok=True)

REPO_ROOT = os.path.normpath(os.path.join(HERE, '..', '..'))
CPI_CSV = os.path.join(REPO_ROOT, 'storage', 'macro', 'fred_CPIAUCSL.csv')

ASSETS_PRIMARY = ['TIP', 'STIP', 'LTPZ', 'IEF']
ASSETS_CONTEXT = ['AGG', '^TNX']
ALL_TICKERS = ASSETS_PRIMARY + ASSETS_CONTEXT

START = '2015-01-01'
END = '2026-06-15'

HIGH_CPI_THRESHOLD = 3.0  # percent YoY
RV_WINDOWS = [5, 21]
LAG_DAYS_CPI_TO_REGIME = 21  # additional trading-day lag on top of FRED release lag
ES_ALPHA = 0.05
BOOTSTRAP_REPS = 5000


# -----------------------------------------------------------------------------
# Data loading
# -----------------------------------------------------------------------------

def load_prices(tickers: list[str], start: str, end: str) -> pd.DataFrame:
    print(f"Downloading prices for {tickers} {start}..{end}")
    df = yf.download(tickers, start=start, end=end, progress=False, auto_adjust=True)
    if isinstance(df.columns, pd.MultiIndex):
        close = df['Close'].copy()
    else:
        close = df[['Close']].copy()
        close.columns = tickers
    close = close.dropna(how='all')
    print(f"  rows: {len(close)}  date range: {close.index[0].date()}..{close.index[-1].date()}")
    print(f"  non-null counts per ticker:\n{close.notna().sum().to_string()}")
    return close


def load_cpi_yoy() -> pd.Series:
    """Load monthly CPI (FRED CPIAUCSL), compute YoY %, return DAILY ffill series.

    NOTE on lag:
      - FRED CPIAUCSL has 'observation_date' = month start; the actual
        release happens ~mid of following month. We treat the CPI value
        for month M as known only on the 1st of month M+2 to be conservative.
      - On top of that we apply LAG_DAYS_CPI_TO_REGIME (21 trading days)
        when building the regime label, so the regime on day t uses
        CPI YoY from >= ~6 weeks earlier. No lookahead.
    """
    print(f"Loading CPI from {CPI_CSV}")
    cpi = pd.read_csv(CPI_CSV)
    # header is 'date,CPIAUCSL'
    cpi['date'] = pd.to_datetime(cpi['date'])
    cpi = cpi.sort_values('date').set_index('date')
    cpi['CPI_YoY'] = cpi['CPIAUCSL'].pct_change(12) * 100.0

    # Conservative release-lag: assume CPI for month M is *known* at month M+2 start
    cpi['known_from'] = cpi.index + pd.DateOffset(months=2)
    cpi_known = cpi[['CPI_YoY', 'known_from']].dropna().reset_index(drop=True)

    # Build a daily series: on each daily date, take latest CPI_YoY whose
    # known_from <= that date.
    daily_idx = pd.date_range(start=START, end=END, freq='D')
    out = pd.Series(index=daily_idx, dtype=float, name='CPI_YoY_known')
    j = 0
    cpi_known_sorted = cpi_known.sort_values('known_from').reset_index(drop=True)
    last_val = np.nan
    for d in daily_idx:
        while j < len(cpi_known_sorted) and cpi_known_sorted.loc[j, 'known_from'] <= d:
            last_val = cpi_known_sorted.loc[j, 'CPI_YoY']
            j += 1
        out.loc[d] = last_val
    print(f"  daily CPI_YoY series: {out.notna().sum()} non-null days, "
          f"range {out.min():.2f}..{out.max():.2f}%")
    return out


# -----------------------------------------------------------------------------
# Construction
# -----------------------------------------------------------------------------

def compute_returns_and_rv(close: pd.DataFrame) -> tuple[pd.DataFrame, dict[int, pd.DataFrame]]:
    logret = np.log(close).diff()
    rv_by_window: dict[int, pd.DataFrame] = {}
    for w in RV_WINDOWS:
        # rolling std over window w of daily log returns, annualized
        rv = logret.rolling(window=w, min_periods=max(2, w // 2)).std() * np.sqrt(252.0)
        rv_by_window[w] = rv
    return logret, rv_by_window


def build_regime(cpi_yoy_daily: pd.Series, trading_index: pd.DatetimeIndex) -> pd.Series:
    """Align daily CPI_YoY to trading days, then apply additional 21-day lag."""
    # align to trading days (forward-fill from daily)
    aligned = cpi_yoy_daily.reindex(trading_index, method='ffill')
    # extra lag to be conservative against any release-timing slop:
    lagged = aligned.shift(LAG_DAYS_CPI_TO_REGIME)
    regime = (lagged > HIGH_CPI_THRESHOLD).astype('Int64')
    regime.name = 'regime_high_cpi'
    return regime, lagged


def welch_diff(a: np.ndarray, b: np.ndarray) -> dict:
    """Welch t-test mean(a) - mean(b)."""
    a = a[~np.isnan(a)]
    b = b[~np.isnan(b)]
    if len(a) < 5 or len(b) < 5:
        return {'mean_a': float('nan'), 'mean_b': float('nan'),
                'diff': float('nan'), 't': float('nan'), 'p': float('nan'),
                'n_a': int(len(a)), 'n_b': int(len(b))}
    t, p = stats.ttest_ind(a, b, equal_var=False, nan_policy='omit')
    return {
        'mean_a': float(np.mean(a)),
        'mean_b': float(np.mean(b)),
        'diff': float(np.mean(a) - np.mean(b)),
        't': float(t),
        'p': float(p),
        'n_a': int(len(a)),
        'n_b': int(len(b)),
    }


def bootstrap_diff_ci(a: np.ndarray, b: np.ndarray, reps: int = BOOTSTRAP_REPS,
                      seed: int = SEED, ci: float = 0.95) -> dict:
    rng = np.random.default_rng(seed)
    a = a[~np.isnan(a)]
    b = b[~np.isnan(b)]
    if len(a) < 5 or len(b) < 5:
        return {'lo': float('nan'), 'hi': float('nan'), 'reps': 0}
    diffs = np.empty(reps)
    for i in range(reps):
        sa = rng.choice(a, size=len(a), replace=True)
        sb = rng.choice(b, size=len(b), replace=True)
        diffs[i] = sa.mean() - sb.mean()
    lo = float(np.quantile(diffs, (1 - ci) / 2))
    hi = float(np.quantile(diffs, 1 - (1 - ci) / 2))
    return {'lo': lo, 'hi': hi, 'reps': reps}


def empirical_es(x: np.ndarray, alpha: float = ES_ALPHA) -> float:
    """Empirical Expected Shortfall at alpha (lower tail)."""
    x = x[~np.isnan(x)]
    if len(x) < 20:
        return float('nan')
    q = np.quantile(x, alpha)
    tail = x[x <= q]
    return float(np.mean(tail)) if len(tail) else float('nan')


# -----------------------------------------------------------------------------
# Main analysis
# -----------------------------------------------------------------------------

def run():
    started_at = datetime.now(timezone.utc).isoformat()

    close = load_prices(ALL_TICKERS, START, END)
    logret, rv_by_window = compute_returns_and_rv(close)

    cpi_yoy_daily = load_cpi_yoy()
    regime, cpi_lagged_aligned = build_regime(cpi_yoy_daily, close.index)

    # Sample size summary
    valid_regime = regime.dropna()
    n_high = int((valid_regime == 1).sum())
    n_low = int((valid_regime == 0).sum())
    print(f"\nRegime sample (valid days): high={n_high}, normal={n_low}, "
          f"high_share={n_high / max(1, n_high + n_low):.3f}")

    # ---------------- RV by regime tests ----------------
    rv_results = {}
    alpha_bonf = 0.05 / (len(ASSETS_PRIMARY[:3]) * len(RV_WINDOWS))  # 3 TIPS x 2 windows = 6 tests
    print(f"\nBonferroni alpha (RV family, 6 tests): {alpha_bonf:.5f}")

    for w in RV_WINDOWS:
        rv = rv_by_window[w]
        for tkr in ASSETS_PRIMARY:
            if tkr not in rv.columns:
                continue
            series = rv[tkr]
            df_pair = pd.concat([series, regime], axis=1).dropna()
            high_vals = df_pair[df_pair[regime.name] == 1][tkr].values
            low_vals = df_pair[df_pair[regime.name] == 0][tkr].values
            res = welch_diff(high_vals, low_vals)
            ci = bootstrap_diff_ci(high_vals, low_vals)
            verdict = 'NA'
            if not np.isnan(res['p']):
                if tkr in ASSETS_PRIMARY[:3]:  # TIPS are in Bonferroni family
                    verdict = 'SIG_BONF' if res['p'] < alpha_bonf else (
                        'SIG_NOMINAL' if res['p'] < 0.05 else 'NULL')
                else:
                    verdict = 'SIG_NOMINAL' if res['p'] < 0.05 else 'NULL'
            rv_results[f'{tkr}_w{w}'] = {
                'asset': tkr, 'window': w,
                **res, 'ci95': ci, 'verdict': verdict,
            }
            print(f"  RV w={w:2d} {tkr:5s}: high={res['mean_a']:.4f} normal={res['mean_b']:.4f} "
                  f"diff={res['diff']:+.4f} p={res['p']:.4g} ci=[{ci['lo']:+.4f},{ci['hi']:+.4f}] -> {verdict}")

    # ---------------- ES (tail) by regime ----------------
    es_results = {}
    for tkr in ASSETS_PRIMARY:
        if tkr not in logret.columns:
            continue
        series = logret[tkr]
        df_pair = pd.concat([series, regime], axis=1).dropna()
        high_vals = df_pair[df_pair[regime.name] == 1][tkr].values
        low_vals = df_pair[df_pair[regime.name] == 0][tkr].values
        es_high = empirical_es(high_vals, ES_ALPHA)
        es_low = empirical_es(low_vals, ES_ALPHA)
        es_results[tkr] = {
            'asset': tkr,
            'es5_high': es_high,
            'es5_normal': es_low,
            'es_diff_high_minus_normal': float(es_high - es_low) if not (np.isnan(es_high) or np.isnan(es_low)) else float('nan'),
            'n_high': int(len(high_vals)),
            'n_normal': int(len(low_vals)),
        }
        print(f"  ES5 {tkr:5s}: high={es_high:+.5f} normal={es_low:+.5f} diff={es_results[tkr]['es_diff_high_minus_normal']:+.5f}")

    # ---------------- TIPS - IEF RV gap by regime ----------------
    gap_results = {}
    for w in RV_WINDOWS:
        rv = rv_by_window[w]
        if 'IEF' not in rv.columns:
            continue
        for tkr in ['TIP', 'STIP', 'LTPZ']:
            if tkr not in rv.columns:
                continue
            gap = (rv[tkr] - rv['IEF']).dropna()
            df_pair = pd.concat([gap.rename('gap'), regime], axis=1).dropna()
            high_vals = df_pair[df_pair[regime.name] == 1]['gap'].values
            low_vals = df_pair[df_pair[regime.name] == 0]['gap'].values
            res = welch_diff(high_vals, low_vals)
            ci = bootstrap_diff_ci(high_vals, low_vals)
            verdict = 'NA'
            if not np.isnan(res['p']):
                verdict = 'SIG_NOMINAL' if res['p'] < 0.05 else 'NULL'
            gap_results[f'{tkr}_minus_IEF_w{w}'] = {
                'pair': f'{tkr}-IEF', 'window': w,
                **res, 'ci95': ci, 'verdict': verdict,
            }
            print(f"  Gap w={w:2d} {tkr}-IEF: high={res['mean_a']:+.4f} normal={res['mean_b']:+.4f} "
                  f"diff={res['diff']:+.4f} p={res['p']:.4g} -> {verdict}")

    # ---------------- Figures ----------------
    plot_fig_a(rv_by_window, regime)
    plot_fig_b(rv_by_window, regime)

    # ---------------- Overall verdict ----------------
    sig_bonf_rv = [k for k, v in rv_results.items()
                   if v['verdict'] == 'SIG_BONF' and v['asset'] in ASSETS_PRIMARY[:3]]
    sig_gap = [k for k, v in gap_results.items() if v['verdict'] == 'SIG_NOMINAL']
    if sig_bonf_rv and sig_gap:
        overall = 'PASS'
    elif sig_bonf_rv or sig_gap:
        overall = 'MIXED'
    else:
        overall = 'NULL'

    one_liner = build_one_liner(rv_results, gap_results, n_high, overall)

    out = {
        'experiment_id': 'k1509',
        'title': 'TIPS regime-conditional volatility decomposition',
        'started_at': started_at,
        'finished_at': datetime.now(timezone.utc).isoformat(),
        'seed': SEED,
        'data': {
            'source': 'yfinance + FRED CPIAUCSL (local CSV)',
            'period': {'start': START, 'end': END},
            'assets_primary': ASSETS_PRIMARY,
            'assets_context': ASSETS_CONTEXT,
            'price_n_obs': int(len(close)),
        },
        'regime': {
            'rule': f'CPI YoY > {HIGH_CPI_THRESHOLD}%',
            'release_lag_months': 2,
            'extra_trading_day_lag': LAG_DAYS_CPI_TO_REGIME,
            'n_high_days': n_high,
            'n_normal_days': n_low,
            'high_share': n_high / max(1, n_high + n_low),
        },
        'bonferroni_alpha_rv_family': alpha_bonf,
        'rv_by_regime': rv_results,
        'es5_by_regime': es_results,
        'gap_vs_IEF': gap_results,
        'overall_verdict': overall,
        'one_line_summary': one_liner,
        'limitations': [
            'Only one high-CPI episode in sample (2021-2023 post-COVID); '
            'cannot disentangle CPI regime from Fed hike cycle / COVID dislocation.',
            'Daily RV is noisy; intraday TIPS data not used.',
            'LTPZ liquidity is thin and may inject idiosyncratic vol unrelated to CPI.',
            'ES5 estimates depend on regime sample size; high regime has fewer obs.',
            'Bonferroni applied only to RV family (6 tests); ES & gap tests are descriptive.',
        ],
    }

    out_path = os.path.join(HERE, 'k1509_results.json')
    with open(out_path, 'w') as f:
        json.dump(out, f, indent=2, default=str)
    print(f"\nWrote results -> {out_path}")
    print(f"Overall verdict: {overall}")
    print(f"One-liner: {one_liner}")


def build_one_liner(rv_results: dict, gap_results: dict, n_high: int, overall: str) -> str:
    tip_w21 = rv_results.get('TIP_w21', {})
    gap_tip_w21 = gap_results.get('TIP_minus_IEF_w21', {})
    diff_rv = tip_w21.get('diff', float('nan'))
    p_rv = tip_w21.get('p', float('nan'))
    diff_gap = gap_tip_w21.get('diff', float('nan'))
    return (f"K1509 {overall}: high-CPI regime n={n_high} days; TIP 21d RV diff="
            f"{diff_rv:+.4f} (p={p_rv:.3g}); TIP-IEF RV gap diff in high regime="
            f"{diff_gap:+.4f}.")


def plot_fig_a(rv_by_window: dict[int, pd.DataFrame], regime: pd.Series):
    """Bar chart: 4 ETFs x 2 regimes, 21d RV."""
    rv = rv_by_window[21]
    means_high = []
    means_low = []
    for tkr in ASSETS_PRIMARY:
        if tkr not in rv.columns:
            means_high.append(np.nan); means_low.append(np.nan); continue
        df_pair = pd.concat([rv[tkr], regime], axis=1).dropna()
        means_high.append(df_pair[df_pair[regime.name] == 1][tkr].mean())
        means_low.append(df_pair[df_pair[regime.name] == 0][tkr].mean())

    x = np.arange(len(ASSETS_PRIMARY))
    width = 0.38
    fig, ax = plt.subplots(figsize=(8, 5))
    ax.bar(x - width / 2, means_high, width, label='High CPI (>3%)', color='#c0392b')
    ax.bar(x + width / 2, means_low, width, label='Normal CPI', color='#2980b9')
    ax.set_xticks(x); ax.set_xticklabels(ASSETS_PRIMARY)
    ax.set_ylabel('Annualized 21d RV')
    ax.set_title('K1509: TIPS ladder & IEF 21d RV by CPI regime (2015-2026)')
    ax.legend()
    ax.grid(axis='y', alpha=0.3)
    fig.tight_layout()
    out = os.path.join(FIG_DIR, 'fig_a_rv_by_regime.png')
    fig.savefig(out, dpi=130)
    plt.close(fig)
    print(f"  fig -> {out}")


def plot_fig_b(rv_by_window: dict[int, pd.DataFrame], regime: pd.Series):
    """TIPS-IEF RV gap by regime, 21d window, 3 TIPS bars x 2 regimes."""
    rv = rv_by_window[21]
    if 'IEF' not in rv.columns:
        return
    tips = ['TIP', 'STIP', 'LTPZ']
    means_high = []
    means_low = []
    for tkr in tips:
        if tkr not in rv.columns:
            means_high.append(np.nan); means_low.append(np.nan); continue
        gap = (rv[tkr] - rv['IEF']).rename('gap')
        df_pair = pd.concat([gap, regime], axis=1).dropna()
        means_high.append(df_pair[df_pair[regime.name] == 1]['gap'].mean())
        means_low.append(df_pair[df_pair[regime.name] == 0]['gap'].mean())

    x = np.arange(len(tips))
    width = 0.38
    fig, ax = plt.subplots(figsize=(8, 5))
    ax.bar(x - width / 2, means_high, width, label='High CPI (>3%)', color='#c0392b')
    ax.bar(x + width / 2, means_low, width, label='Normal CPI', color='#2980b9')
    ax.axhline(0, color='black', linewidth=0.8)
    ax.set_xticks(x); ax.set_xticklabels([f'{t}-IEF' for t in tips])
    ax.set_ylabel('21d RV gap (TIPS - IEF, annualized)')
    ax.set_title('K1509: TIPS-vs-IEF 21d RV gap by CPI regime')
    ax.legend()
    ax.grid(axis='y', alpha=0.3)
    fig.tight_layout()
    out = os.path.join(FIG_DIR, 'fig_b_rv_gap_vs_nominal.png')
    fig.savefig(out, dpi=130)
    plt.close(fig)
    print(f"  fig -> {out}")


if __name__ == '__main__':
    run()
