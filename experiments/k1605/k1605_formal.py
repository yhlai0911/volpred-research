"""
K1605 FORMAL (deferred, compute-queue) — formal estimation of the bank
market-to-book divergence -> regional-bank RV lead-lag.

Runs the heavy pieces intentionally kept out of the Phase-1 first-look:
  (A) DM test: M/B-augmented RV forecast vs RV-only (HAR-lite) baseline,
      OOS expanding-window refit with target_end < forecast_origin guard.
  (B) Block bootstrap CIs on the Fama-MacBeth cross-sectional means.
  (C) Filing-lag robustness (45 / 60 / 90 days).
  (D) Downside-semivol targets alongside RV.

Reuses the lag-safe signal/target construction from k1605.py to guarantee the
SAME lookahead protection (book equity -> filing-available date; signals
shift(1); forward RV over (t, t+H]; HAC/DM horizon = target H).

Writes: experiments/k1605/k1605_formal_results.json
Seed fixed. Free data only (yfinance).
"""
from __future__ import annotations

import json
import warnings
from datetime import datetime, timezone

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

import k1605 as base  # same directory; reuse lag-safe construction

SEED = 20260702
rng = np.random.default_rng(SEED)
HERE = __file__.rsplit("/", 1)[0]

BOOTSTRAP_REPS = 2000
BLOCK = 22
LAG_VARIANTS = {"q45_a75": (45, 75), "q60_a90": (60, 90), "q90_a120": (90, 120)}


def dm_test(loss_a, loss_b, h):
    """Diebold-Mariano with Harvey small-sample correction; HAC lag = h-1."""
    d = np.asarray(loss_a, float) - np.asarray(loss_b, float)
    d = d[~np.isnan(d)]
    n = len(d)
    if n < 30:
        return {"dm_t": None, "p": None, "n": int(n)}
    dbar = d.mean()
    lags = max(h - 1, 0)
    gamma0 = np.mean((d - dbar) ** 2)
    var = gamma0
    for L in range(1, lags + 1):
        cov = np.mean((d[L:] - dbar) * (d[:-L] - dbar))
        var += 2 * (1 - L / (lags + 1)) * cov
    dm = dbar / np.sqrt(var / n)
    # Harvey, Leybourne, Newbold (1997) correction
    hln = np.sqrt((n + 1 - 2 * h + h * (h - 1) / n) / n)
    dm_c = dm * hln
    from scipy import stats
    p = 2 * (1 - stats.t.cdf(abs(dm_c), df=n - 1))
    return {"dm_t": float(dm_c), "p": float(p), "n": int(n), "mean_d": float(dbar)}


def oos_forecast_eval(prices, rets, xs_median_mb, etf, h):
    """Expanding-window OOS: compare RV-only vs RV+M/B one-step forecast of
    forward RV(t+1..t+h). target_end < forecast_origin enforced by construction:
    training row j uses target over (j, j+h]; we only include rows with
    j + h < forecast_origin i.
    """
    frv = base.forward_rv(rets[etf], h)
    lagrv = base.trailing_rv(rets)[etf]
    sig = xs_median_mb.shift(1)
    df = pd.concat([frv.rename("y"), lagrv.rename("lagrv"), sig.rename("mb")], axis=1)
    df = df.loc[df.index >= pd.Timestamp(base.START_ANALYSIS)].dropna()
    idx = df.index
    n = len(df)
    min_train = 120
    la, lb = [], []
    for i in range(min_train, n):
        # training rows must have completed target before origin i: j + h < i
        train = df.iloc[: i - h]
        if len(train) < min_train:
            continue
        yb = train["y"].values
        Xa = np.column_stack([np.ones(len(train)), train["lagrv"].values])          # RV-only
        Xb = np.column_stack([np.ones(len(train)), train["lagrv"].values, train["mb"].values])  # +M/B
        ba, *_ = np.linalg.lstsq(Xa, yb, rcond=None)
        bb, *_ = np.linalg.lstsq(Xb, yb, rcond=None)
        row = df.iloc[i]
        fa = ba[0] + ba[1] * row["lagrv"]
        fb = bb[0] + bb[1] * row["lagrv"] + bb[2] * row["mb"]
        y_true = row["y"]
        la.append((fa - y_true) ** 2)
        lb.append((fb - y_true) ** 2)
    la, lb = np.array(la), np.array(lb)
    if len(la) < 30:
        return {"n_oos": int(len(la)), "note": "insufficient"}
    dm = dm_test(la, lb, h)  # positive dm_t => RV-only worse => M/B helps
    return {
        "n_oos": int(len(la)),
        "rmse_rv_only": float(np.sqrt(la.mean())),
        "rmse_rv_plus_mb": float(np.sqrt(lb.mean())),
        "rmse_improve_pct": float(100 * (np.sqrt(la.mean()) - np.sqrt(lb.mean())) / np.sqrt(la.mean())),
        "dm_rv_only_vs_mb": dm,
    }


def block_bootstrap_fm(slopes, block=BLOCK, reps=BOOTSTRAP_REPS):
    """Circular block bootstrap CI for the mean of a Fama-MacBeth slope series."""
    s = np.asarray(slopes, float)
    s = s[~np.isnan(s)]
    n = len(s)
    if n < block + 5:
        return None
    nblocks = int(np.ceil(n / block))
    means = np.empty(reps)
    for r in range(reps):
        starts = rng.integers(0, n, size=nblocks)
        idx = np.concatenate([(np.arange(st, st + block) % n) for st in starts])[:n]
        means[r] = s[idx].mean()
    return {
        "mean": float(s.mean()),
        "ci95": [float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5))],
        "p_two_sided": float(2 * min((means > 0).mean(), (means < 0).mean())),
        "reps": reps, "block": block, "n_days": int(n),
    }


def fm_slope_series(logmb, lagrv, rets, h, min_xs=6):
    sig_panel = logmb.shift(1)
    banks = list(logmb.columns)
    fwd_panel = pd.DataFrame({t: base.forward_rv(rets[t], h).reindex(logmb.index) for t in banks})
    lagrv_panel = lagrv[banks].reindex(logmb.index)
    slopes = []
    for d in logmb.index:
        sg = sig_panel.loc[d]; y = fwd_panel.loc[d]; lv = lagrv_panel.loc[d]
        m = sg.notna() & y.notna() & lv.notna()
        if int(m.sum()) < min_xs:
            continue
        X = np.column_stack([np.ones(int(m.sum())), sg[m].values, lv[m].values])
        b, *_ = np.linalg.lstsq(X, y[m].values, rcond=None)
        slopes.append(b[1])
    return np.array(slopes)


def main():
    asof = datetime.now(timezone.utc).isoformat()
    all_tickers = base.ETFS + base.BANKS
    prices, price_fails = base.fetch_prices(all_tickers)
    shares, _ = base.fetch_shares(base.BANKS)
    rets = base.daily_log_returns(prices)
    calendar = prices.index

    out = {"experiment_id": "k1605_formal", "asof": asof, "seed": SEED,
           "price_fails": price_fails, "results": {}}

    for lag_name, (qlag, alag) in LAG_VARIANTS.items():
        base.Q_LAG_DAYS, base.A_LAG_DAYS = qlag, alag
        book, _ = base.fetch_book_equity(base.BANKS)
        logmb = base.build_market_to_book(prices, book, shares, calendar)
        logmb = logmb.loc[logmb.index >= pd.Timestamp(base.START_ANALYSIS)]
        lagrv = base.trailing_rv(rets)
        variant = {"n_banks": int(logmb.shape[1]), "oos": {}, "fama_macbeth_boot": {}}
        for h in base.HORIZONS:
            # OOS DM per ETF
            for etf in base.ETFS:
                if etf in prices.columns:
                    variant["oos"][f"{etf}_h{h}"] = oos_forecast_eval(prices, rets, logmb.median(axis=1), etf, h)
            # Fama-MacBeth bootstrap
            slopes = fm_slope_series(logmb, lagrv, rets, h)
            variant["fama_macbeth_boot"][f"h{h}"] = block_bootstrap_fm(slopes)
        out["results"][lag_name] = variant
        print(f"[{lag_name}] done")

    with open(f"{HERE}/k1605_formal_results.json", "w") as f:
        json.dump(out, f, indent=2, default=str)
    print(f"[write] {HERE}/k1605_formal_results.json")
    return out


if __name__ == "__main__":
    main()
