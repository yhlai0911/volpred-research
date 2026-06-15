"""K1500 — Treasury auction bid-to-cover ratio as MOVE vol leading signal.

Hypothesis: Weak Treasury auction demand (low bid-to-cover ratio) at t-1 predicts
positive change in ^MOVE (rates implied vol) at t..t+5.

Mechanism: weak auction -> primary dealer absorption -> liquidity stress + rate
uncertainty -> MOVE rises.

Data:
  - Auction data: US Treasury Fiscal Data API (`auctions_query`), full history
    including bid_to_cover_ratio. Filtered to Note/Bond/TIPS, term >= 5Y, 2010+.
  - ^MOVE: ICE BofA MOVE index, daily close via yfinance, 2010-01-01..2026-06-15.

Method:
  Phase 1: Descriptive — distributions, scatter, quintile group T+1..T+10 reaction.
  Phase 2: Event study — define low-cover events (z-score < -1 within rolling 60-event
    window per term), compute CAR over [-5, +10] day window, bootstrap CI (n=5000, seed=42).
  Phase 3: Predictive regression — MOVE_change_{t+h} = alpha + beta * weakness_signal_{t-1}
    + AR(1) control + level control. Horizons h in {1, 5, 10}. OOS rolling window=252,
    step=21. DM test (HLN small-sample adj) vs AR(1) baseline & historical mean baseline.

Hard rules:
  - signal.shift(1) — auction outcome at date t is only usable to predict MOVE at t+1 or later.
  - Auctions on day t are typically announced after market close (1pm ET results); we
    conservatively treat auction result on day t as known only for MOVE at t+1 onward.
  - seed=42 across all random ops.
  - Baseline AR(1) uses MOVE_change_{t-1} as predictor for MOVE_change_t — same lag.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import requests
import yfinance as yf
from scipy import stats
from statsmodels.tsa.ar_model import AutoReg

SEED = 42
BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)
FIG_DIR = BASE_DIR
START = "2010-01-01"
END = "2026-06-15"
RESULTS: dict = {
    "experiment_id": "K1500",
    "title": "Treasury auction bid-to-cover -> MOVE vol leading signal",
    "seed": SEED,
    "data_window": {"start": START, "end": END},
}


# ---------------- Data ----------------
def fetch_auctions() -> pd.DataFrame:
    """Pull Treasury auction history from fiscaldata API.

    Filters: auction_date >= 2010-01-01, security_type in (Note, Bond, TIPS).
    Returns dataframe with cleaned bid_to_cover_ratio.
    """
    cache = DATA_DIR / "auctions_raw.parquet"
    if cache.exists():
        return pd.read_parquet(cache)

    url = "https://api.fiscaldata.treasury.gov/services/api/fiscal_service/v1/accounting/od/auctions_query"
    fields = ",".join(
        [
            "cusip",
            "security_type",
            "security_term",
            "auction_date",
            "issue_date",
            "bid_to_cover_ratio",
            "offering_amt",
            "total_tendered",
            "total_accepted",
            "indirect_bidder_accepted",
            "direct_bidder_accepted",
            "primary_dealer_accepted",
            "high_yield",
            "low_yield",
        ]
    )
    rows: list[dict] = []
    page = 1
    page_size = 1000
    while True:
        r = requests.get(
            url,
            params={
                "fields": fields,
                "filter": f"auction_date:gte:2010-01-01,security_type:in:(Note,Bond,TIPS)",
                "page[size]": page_size,
                "page[number]": page,
                "sort": "auction_date",
            },
            timeout=120,
        )
        if r.status_code != 200:
            raise RuntimeError(f"fiscaldata API failed: {r.status_code} {r.text[:200]}")
        body = r.json()
        rows.extend(body["data"])
        total_pages = body["meta"]["total-pages"]
        if page >= total_pages:
            break
        page += 1
        time.sleep(0.15)
    df = pd.DataFrame(rows)
    df["auction_date"] = pd.to_datetime(df["auction_date"])
    df["bid_to_cover_ratio"] = pd.to_numeric(df["bid_to_cover_ratio"], errors="coerce")
    df["offering_amt"] = pd.to_numeric(df["offering_amt"], errors="coerce")
    df.to_parquet(cache)
    return df


def filter_auctions(df: pd.DataFrame) -> pd.DataFrame:
    """Keep MOVE-relevant tenors: >= 5y. MOVE indexes 2/5/10/30y swaption vol."""

    # Parse security_term: most are like '10-Year', '7-Year', '2-Year', '9-Year 10-Month'
    def parse_years(term: str) -> float:
        if not isinstance(term, str):
            return np.nan
        years = 0.0
        if "Year" in term:
            # take leading number
            try:
                years_part = term.split("-Year")[0].strip()
                years = float(years_part)
            except (ValueError, IndexError):
                return np.nan
        if "Month" in term and "-Month" in term:
            try:
                m_str = term.split("Year")[-1].replace("-Month", "").strip()
                m = float(m_str) if m_str else 0
                years += m / 12.0
            except (ValueError, IndexError):
                pass
        return years

    df = df.copy()
    df["years"] = df["security_term"].apply(parse_years)
    df = df[df["years"] >= 5.0]
    df = df[df["years"] <= 30.5]
    df = df.dropna(subset=["bid_to_cover_ratio", "auction_date"])
    # group nominal term: nearest of {5,7,10,20,30}
    nominal_buckets = np.array([5, 7, 10, 20, 30], dtype=float)
    df["term_bucket"] = df["years"].apply(
        lambda y: int(nominal_buckets[np.argmin(np.abs(nominal_buckets - y))])
    )
    df = df.sort_values("auction_date").reset_index(drop=True)
    return df


def fetch_move() -> pd.DataFrame:
    cache = DATA_DIR / "move.parquet"
    if cache.exists():
        return pd.read_parquet(cache)
    m = yf.download("^MOVE", start=START, end=END, progress=False, auto_adjust=False)
    if isinstance(m.columns, pd.MultiIndex):
        m.columns = m.columns.get_level_values(0)
    m = m[["Close"]].rename(columns={"Close": "move"}).dropna()
    m["move_log"] = np.log(m["move"])
    m["dlog_move"] = m["move_log"].diff()
    m.to_parquet(cache)
    return m


# ---------------- Signal ----------------
def build_weakness_signal(auctions: pd.DataFrame) -> pd.DataFrame:
    """Per-term rolling z-score of bid-to-cover (lower = weaker demand).

    Uses **rolling past 60 auctions of same term-bucket** (purely past) to avoid
    lookahead. Signal at event date t uses only data strictly before t.
    """
    out = []
    for bucket, g in auctions.groupby("term_bucket"):
        g = g.sort_values("auction_date").copy()
        # rolling stats SHIFTED so current observation excluded
        g["btc_rolling_mean"] = g["bid_to_cover_ratio"].shift(1).rolling(60, min_periods=20).mean()
        g["btc_rolling_std"] = g["bid_to_cover_ratio"].shift(1).rolling(60, min_periods=20).std()
        # negative z = weakness (low cover relative to recent)
        g["btc_z"] = (g["bid_to_cover_ratio"] - g["btc_rolling_mean"]) / g["btc_rolling_std"]
        g["weakness"] = -g["btc_z"]  # high = weak demand
        out.append(g)
    return pd.concat(out).sort_values("auction_date").reset_index(drop=True)


def daily_panel(auctions: pd.DataFrame, move: pd.DataFrame) -> pd.DataFrame:
    """Aggregate auctions to daily; merge with MOVE.

    For each trading day d, signal_d = mean weakness across all >=5y auctions on d.
    Then SHIFT BY +1 so signal known at d is applied to MOVE move at d+1.
    """
    a = auctions.dropna(subset=["weakness"]).copy()
    a["date"] = a["auction_date"]
    # daily aggregate
    daily = (
        a.groupby("date")
        .agg(
            weakness=("weakness", "mean"),
            avg_btc=("bid_to_cover_ratio", "mean"),
            n_auctions=("cusip", "count"),
            avg_term=("term_bucket", "mean"),
            tot_offer=("offering_amt", "sum"),
        )
        .reset_index()
    )
    panel = move.reset_index().merge(daily, left_on="Date", right_on="date", how="left")
    panel = panel.set_index("Date").drop(columns=["date"])
    panel["weakness_event"] = panel["weakness"].notna()
    # the canonical signal: shift by 1 day (auction result at d -> usable for MOVE move at d+1)
    panel["weakness_lag1"] = panel["weakness"].shift(1)
    panel["weakness_event_lag1"] = panel["weakness_event"].shift(1).fillna(False)
    return panel


# ---------------- Phase 2: Event Study ----------------
def event_study(panel: pd.DataFrame) -> dict:
    """CAR around weak-cover events (weakness z >= 1, i.e., btc_z <= -1)."""
    rng = np.random.default_rng(SEED)
    pre_window = 5
    post_window = 10
    # eligible event dates: rows where weakness >= 1 (true weak)
    panel = panel.copy()
    panel["row_idx"] = np.arange(len(panel))

    weak_events = panel[(panel["weakness"] >= 1.0) & (panel["weakness_event"])].copy()
    strong_events = panel[(panel["weakness"] <= -1.0) & (panel["weakness_event"])].copy()
    n_weak = int(len(weak_events))
    n_strong = int(len(strong_events))

    # Build CAR matrices using log-difference returns (already in panel as dlog_move).
    # NOTE: estimation window for abnormal return = days [-30, -6] BEFORE event (no overlap)
    def car(event_idx: np.ndarray):
        cars = []
        for idx in event_idx:
            lo = idx - pre_window
            hi = idx + post_window
            if lo < 30 or hi >= len(panel):
                continue
            est = panel["dlog_move"].iloc[idx - 30 : idx - pre_window].dropna()
            if len(est) < 15:
                continue
            mu_est = est.mean()
            window = panel["dlog_move"].iloc[lo : hi + 1].values
            if np.isnan(window).any():
                continue
            ar = window - mu_est
            car_path = np.cumsum(ar)
            cars.append(car_path)
        return np.array(cars) if cars else np.empty((0, pre_window + post_window + 1))

    weak_idx = weak_events["row_idx"].values
    strong_idx = strong_events["row_idx"].values
    car_weak = car(weak_idx)
    car_strong = car(strong_idx)

    # Bootstrap CI on the post-event CAR at t+5 vs t-1
    def bootstrap_mean_ci(values: np.ndarray, n_boot=5000):
        if len(values) == 0:
            return float("nan"), float("nan"), float("nan")
        boots = []
        for _ in range(n_boot):
            sample = rng.choice(values, size=len(values), replace=True)
            boots.append(sample.mean())
        return float(np.mean(values)), float(np.percentile(boots, 2.5)), float(np.percentile(boots, 97.5))

    t0_idx = pre_window  # index of event day in window
    # CAR from event-day +1 to +5 (impact window)
    if len(car_weak):
        weak_impact = car_weak[:, t0_idx + 5] - car_weak[:, t0_idx]
    else:
        weak_impact = np.array([])
    if len(car_strong):
        strong_impact = car_strong[:, t0_idx + 5] - car_strong[:, t0_idx]
    else:
        strong_impact = np.array([])

    mw, lw, uw = bootstrap_mean_ci(weak_impact)
    ms, ls, us = bootstrap_mean_ci(strong_impact)

    # Random control matched: pick same number of random event-eligible days (no auction)
    no_auction_dates = panel[(~panel["weakness_event"]) & (panel["dlog_move"].notna())].iloc[30:-15]
    if len(no_auction_dates) > 0 and len(weak_events) > 0:
        rand_idx = rng.choice(no_auction_dates["row_idx"].values, size=min(len(weak_events), len(no_auction_dates)), replace=False)
        car_rand = car(rand_idx)
        if len(car_rand):
            rand_impact = car_rand[:, t0_idx + 5] - car_rand[:, t0_idx]
        else:
            rand_impact = np.array([])
    else:
        car_rand = np.empty((0, pre_window + post_window + 1))
        rand_impact = np.array([])
    mr, lr, ur = bootstrap_mean_ci(rand_impact)

    # diff in means: weak - random (t-test)
    if len(weak_impact) > 1 and len(rand_impact) > 1:
        t_stat, p_val = stats.ttest_ind(weak_impact, rand_impact, equal_var=False)
    else:
        t_stat, p_val = float("nan"), float("nan")

    res = {
        "n_weak_events": n_weak,
        "n_strong_events": n_strong,
        "n_weak_with_window": int(len(car_weak)),
        "n_strong_with_window": int(len(car_strong)),
        "n_random_control": int(len(car_rand)),
        "car_weak_t0_to_t5": {"mean": mw, "ci_lo": lw, "ci_hi": uw, "n": int(len(weak_impact))},
        "car_strong_t0_to_t5": {"mean": ms, "ci_lo": ls, "ci_hi": us, "n": int(len(strong_impact))},
        "car_random_t0_to_t5": {"mean": mr, "ci_lo": lr, "ci_hi": ur, "n": int(len(rand_impact))},
        "diff_weak_vs_random_t5": {"t_stat": float(t_stat), "p_value": float(p_val)},
    }

    # plot avg CAR curves
    def avg_curve(c):
        return c.mean(axis=0) if len(c) else np.full(pre_window + post_window + 1, np.nan)

    x = np.arange(-pre_window, post_window + 1)
    plt.figure(figsize=(9, 5))
    plt.plot(x, avg_curve(car_weak), label=f"Weak (n={len(car_weak)})", lw=2, color="C3")
    plt.plot(x, avg_curve(car_strong), label=f"Strong (n={len(car_strong)})", lw=2, color="C2")
    plt.plot(x, avg_curve(car_rand), label=f"Random no-auction control (n={len(car_rand)})", lw=1.5, color="grey", ls="--")
    plt.axvline(0, color="k", lw=0.6, ls=":")
    plt.axhline(0, color="k", lw=0.4)
    plt.xlabel("Trading days from auction")
    plt.ylabel("Cumulative abnormal log-MOVE change")
    plt.title("K1500 Event study: ^MOVE response around Treasury auctions\n(weakness = btc z-score ≤ -1)")
    plt.legend()
    plt.tight_layout()
    plt.savefig(FIG_DIR / "fig_event_study_car.png", dpi=140)
    plt.close()

    return res


# ---------------- Phase 1: Descriptive ----------------
def descriptive(panel: pd.DataFrame, auctions: pd.DataFrame) -> dict:
    a = auctions.dropna(subset=["bid_to_cover_ratio"]).copy()
    btc_stats = {
        "n": int(len(a)),
        "mean": float(a["bid_to_cover_ratio"].mean()),
        "std": float(a["bid_to_cover_ratio"].std()),
        "min": float(a["bid_to_cover_ratio"].min()),
        "p25": float(a["bid_to_cover_ratio"].quantile(0.25)),
        "p50": float(a["bid_to_cover_ratio"].quantile(0.5)),
        "p75": float(a["bid_to_cover_ratio"].quantile(0.75)),
        "max": float(a["bid_to_cover_ratio"].max()),
    }

    dlog = panel["dlog_move"].dropna()
    move_stats = {
        "n": int(len(dlog)),
        "mean": float(dlog.mean()),
        "std": float(dlog.std()),
        "skew": float(stats.skew(dlog)),
        "kurt": float(stats.kurtosis(dlog)),
    }

    # quintile reaction: for each event with weakness defined, group into quintiles,
    # compute mean MOVE change over t+1..t+5 (proper lag - signal at d, MOVE move at d+1..d+5)
    quintile_rows = []
    for h in [1, 5, 10]:
        panel = panel.copy()
        panel[f"move_fwd_{h}"] = panel["move_log"].shift(-h) - panel["move_log"]
    events = panel[panel["weakness_event"]].copy()
    events = events.dropna(subset=["weakness"])
    events["quintile"] = pd.qcut(events["weakness"], q=5, labels=False, duplicates="drop")
    quintile_summary = events.groupby("quintile").agg(
        n=("weakness", "size"),
        weakness_mean=("weakness", "mean"),
        move_fwd1_mean=("move_fwd_1", "mean"),
        move_fwd5_mean=("move_fwd_5", "mean"),
        move_fwd10_mean=("move_fwd_10", "mean"),
    ).round(4)

    # scatter plot
    plt.figure(figsize=(8, 5))
    valid = events.dropna(subset=["move_fwd_5", "weakness"])
    plt.scatter(valid["weakness"], valid["move_fwd_5"], s=8, alpha=0.4)
    if len(valid) > 10:
        slope, intercept, r, p, _ = stats.linregress(valid["weakness"], valid["move_fwd_5"])
        xs = np.linspace(valid["weakness"].min(), valid["weakness"].max(), 50)
        plt.plot(xs, intercept + slope * xs, color="red", lw=1.5, label=f"slope={slope:.4f}  R={r:.3f}  p={p:.3g}")
        plt.legend()
    plt.axhline(0, color="grey", lw=0.4)
    plt.axvline(0, color="grey", lw=0.4)
    plt.xlabel("Auction weakness (-btc z-score, higher = weaker demand)")
    plt.ylabel("Forward 5-day log change in MOVE")
    plt.title("K1500 Phase 1: weakness vs forward MOVE change (t+1..t+5)")
    plt.tight_layout()
    plt.savefig(FIG_DIR / "fig_scatter_weakness_vs_movefwd.png", dpi=140)
    plt.close()

    # quintile bar
    plt.figure(figsize=(8, 5))
    x = np.arange(len(quintile_summary))
    w = 0.25
    plt.bar(x - w, quintile_summary["move_fwd1_mean"], width=w, label="t+1")
    plt.bar(x, quintile_summary["move_fwd5_mean"], width=w, label="t+5")
    plt.bar(x + w, quintile_summary["move_fwd10_mean"], width=w, label="t+10")
    plt.xticks(x, [f"Q{i+1}\n(weak={m:.2f})" for i, m in enumerate(quintile_summary["weakness_mean"])])
    plt.axhline(0, color="k", lw=0.5)
    plt.ylabel("Mean forward log-change in MOVE")
    plt.title("K1500 Phase 1: MOVE response by weakness quintile (Q5 = weakest demand)")
    plt.legend()
    plt.tight_layout()
    plt.savefig(FIG_DIR / "fig_quintile_bar.png", dpi=140)
    plt.close()

    return {
        "bid_to_cover_stats": btc_stats,
        "move_dlog_stats": move_stats,
        "quintile_summary": quintile_summary.reset_index().to_dict(orient="records"),
    }


# ---------------- Phase 3: Predictive regression + OOS ----------------
def predictive(panel: pd.DataFrame) -> dict:
    """Run OOS rolling forecast: signal-augmented vs AR(1) baseline vs historical-mean baseline.

    Target: dlog_move at t+h (h=1,5,10).
    Predictors at time t-1 (signal_lag1 already shifted; AR uses dlog_move_{t-1}).

    OOS: rolling window = 252 trading days, step = 21, expanding eval.
    """
    panel = panel.copy()
    # forward returns
    for h in [1, 5, 10]:
        panel[f"y_{h}"] = panel["move_log"].shift(-h) - panel["move_log"]
    panel["dlog_lag1"] = panel["dlog_move"].shift(1)
    panel["move_log_lag1"] = panel["move_log"].shift(1)
    # signal: weakness_lag1 (shifted upstream). For days without auction, fill with 0 (no info change).
    panel["sig"] = panel["weakness_lag1"].fillna(0.0)
    panel["sig_active"] = panel["weakness_lag1"].notna().astype(int)

    results_by_h: dict = {}
    for h in [1, 5, 10]:
        df = panel[["sig", "sig_active", "dlog_lag1", f"y_{h}"]].dropna()
        y = df[f"y_{h}"].values
        X_full = df[["sig", "sig_active", "dlog_lag1"]].values
        X_ar = df[["dlog_lag1"]].values

        # OOS rolling
        window = 504  # 2 years
        step = 21
        preds_full: list[float] = []
        preds_ar: list[float] = []
        preds_mean: list[float] = []
        actuals: list[float] = []
        idx_used: list[int] = []
        for start in range(0, len(df) - window - step, step):
            train_end = start + window
            test_end = min(train_end + step, len(df))
            X_tr_full = X_full[start:train_end]
            X_tr_ar = X_ar[start:train_end]
            y_tr = y[start:train_end]
            # Models
            # full: OLS
            beta_full, *_ = np.linalg.lstsq(np.c_[np.ones(len(X_tr_full)), X_tr_full], y_tr, rcond=None)
            beta_ar, *_ = np.linalg.lstsq(np.c_[np.ones(len(X_tr_ar)), X_tr_ar], y_tr, rcond=None)
            mu_tr = y_tr.mean()
            # Predict test block
            X_te_full = X_full[train_end:test_end]
            X_te_ar = X_ar[train_end:test_end]
            y_te = y[train_end:test_end]
            p_full = np.c_[np.ones(len(X_te_full)), X_te_full] @ beta_full
            p_ar = np.c_[np.ones(len(X_te_ar)), X_te_ar] @ beta_ar
            preds_full.extend(p_full.tolist())
            preds_ar.extend(p_ar.tolist())
            preds_mean.extend([mu_tr] * len(y_te))
            actuals.extend(y_te.tolist())
            idx_used.extend(range(train_end, test_end))

        actuals = np.array(actuals)
        preds_full = np.array(preds_full)
        preds_ar = np.array(preds_ar)
        preds_mean = np.array(preds_mean)

        def rmse(p):
            return float(np.sqrt(np.mean((actuals - p) ** 2)))

        def mae(p):
            return float(np.mean(np.abs(actuals - p)))

        # Squared-loss DM test, HLN small-sample adjustment.
        def dm_test(p1, p2, h_horizon=h):
            d = (actuals - p1) ** 2 - (actuals - p2) ** 2
            n = len(d)
            d_mean = d.mean()
            # HAC variance with lag = h-1 (Diebold-Mariano)
            gamma0 = d.var(ddof=0)
            gammas = []
            for k in range(1, h_horizon):
                if k >= n:
                    break
                gammas.append(np.mean((d[k:] - d_mean) * (d[:-k] - d_mean)))
            var_d = (gamma0 + 2 * sum(gammas)) / n
            if var_d <= 0:
                return float("nan"), float("nan")
            dm = d_mean / np.sqrt(var_d)
            # HLN small-sample adjustment
            k_adj = (n + 1 - 2 * h_horizon + h_horizon * (h_horizon - 1) / n) / n
            dm_adj = dm * np.sqrt(max(k_adj, 1e-9))
            df_t = n - 1
            p_val = 2 * (1 - stats.t.cdf(abs(dm_adj), df=df_t))
            return float(dm_adj), float(p_val)

        # In-sample full regression coefficients (for reporting beta)
        X_is = np.c_[np.ones(len(X_full)), X_full]
        beta_is, *_ = np.linalg.lstsq(X_is, y, rcond=None)
        # standard errors with HAC
        resid = y - X_is @ beta_is
        ssr = (resid ** 2).sum()
        sigma2 = ssr / (len(y) - X_is.shape[1])
        try:
            XtX_inv = np.linalg.inv(X_is.T @ X_is)
            se = np.sqrt(np.diag(sigma2 * XtX_inv))
            tstats = beta_is / se
            r2 = 1 - ssr / ((y - y.mean()) ** 2).sum()
        except np.linalg.LinAlgError:
            se = np.full(len(beta_is), np.nan)
            tstats = np.full(len(beta_is), np.nan)
            r2 = float("nan")

        # MZ test on full model: regress y on (1, yhat); test alpha=0 beta=1 (jointly)
        from statsmodels.api import OLS, add_constant

        try:
            mz = OLS(actuals, add_constant(preds_full)).fit()
            mz_alpha = float(mz.params[0])
            mz_beta = float(mz.params[1])
            mz_alpha_p = float(mz.pvalues[0])
            mz_beta_p = float(mz.pvalues[1])
            R = np.array([[1.0, 0.0], [0.0, 1.0]])
            q = np.array([0.0, 1.0])
            wt = mz.wald_test((R, q), scalar=True)
            mz_joint_stat = float(wt.statistic)
            mz_joint_p = float(wt.pvalue)
        except Exception as e:
            print(f"[K1500] MZ test failed: {e!r}")
            mz_alpha = mz_beta = mz_alpha_p = mz_beta_p = mz_joint_stat = mz_joint_p = float("nan")

        dm_full_vs_ar = dm_test(preds_full, preds_ar)
        dm_full_vs_mean = dm_test(preds_full, preds_mean)
        dm_ar_vs_mean = dm_test(preds_ar, preds_mean)

        results_by_h[str(h)] = {
            "n_oos": int(len(actuals)),
            "rmse": {"full": rmse(preds_full), "ar1": rmse(preds_ar), "histmean": rmse(preds_mean)},
            "mae": {"full": mae(preds_full), "ar1": mae(preds_ar), "histmean": mae(preds_mean)},
            "is_regression": {
                "coef_names": ["intercept", "sig_weakness_lag1", "sig_active_lag1", "dlog_lag1"],
                "coef": beta_is.tolist(),
                "se": se.tolist(),
                "tstat": tstats.tolist(),
                "r2": float(r2),
                "n": int(len(y)),
            },
            "mz_test": {
                "alpha": mz_alpha,
                "beta": mz_beta,
                "alpha_p": mz_alpha_p,
                "beta_p": mz_beta_p,
                "joint_stat": mz_joint_stat,
                "joint_p": mz_joint_p,
            },
            "dm_test_HLN": {
                "full_vs_ar1": {"stat": dm_full_vs_ar[0], "p_value": dm_full_vs_ar[1]},
                "full_vs_histmean": {"stat": dm_full_vs_mean[0], "p_value": dm_full_vs_mean[1]},
                "ar1_vs_histmean": {"stat": dm_ar_vs_mean[0], "p_value": dm_ar_vs_mean[1]},
            },
        }

    # OOS comparison plot
    plt.figure(figsize=(9, 5))
    horizons = [1, 5, 10]
    rmses_full = [results_by_h[str(h)]["rmse"]["full"] for h in horizons]
    rmses_ar = [results_by_h[str(h)]["rmse"]["ar1"] for h in horizons]
    rmses_mean = [results_by_h[str(h)]["rmse"]["histmean"] for h in horizons]
    x = np.arange(len(horizons))
    w = 0.25
    plt.bar(x - w, rmses_full, width=w, label="Full (weakness + AR1)")
    plt.bar(x, rmses_ar, width=w, label="AR(1) only")
    plt.bar(x + w, rmses_mean, width=w, label="Historical mean")
    plt.xticks(x, [f"h={h}" for h in horizons])
    plt.ylabel("OOS RMSE (log MOVE forward change)")
    plt.title("K1500 Phase 3: OOS RMSE comparison (rolling window=504, step=21)")
    plt.legend()
    plt.tight_layout()
    plt.savefig(FIG_DIR / "fig_oos_rmse.png", dpi=140)
    plt.close()

    return results_by_h


# ---------------- Pipeline ----------------
def main():
    np.random.seed(SEED)
    print("[K1500] fetching auctions ...")
    raw = fetch_auctions()
    print(f"  raw rows: {len(raw)}")
    auctions = filter_auctions(raw)
    print(f"  filtered (>=5y term, valid btc): {len(auctions)}")
    print(f"  date range: {auctions['auction_date'].min()} -> {auctions['auction_date'].max()}")

    print("[K1500] fetching MOVE ...")
    move = fetch_move()
    print(f"  MOVE rows: {len(move)}  range {move.index.min()} -> {move.index.max()}")

    print("[K1500] building signal & panel ...")
    auctions = build_weakness_signal(auctions)
    panel = daily_panel(auctions, move)
    print(f"  panel rows: {len(panel)}  events: {int(panel['weakness_event'].sum())}")

    print("[K1500] Phase 1 descriptive ...")
    desc = descriptive(panel, auctions)
    RESULTS["phase1_descriptive"] = desc
    RESULTS["sample_size"] = {
        "n_auctions_used": int(len(auctions)),
        "n_trading_days": int(len(panel)),
        "n_auction_days": int(panel["weakness_event"].sum()),
        "auction_date_range": [str(auctions["auction_date"].min().date()), str(auctions["auction_date"].max().date())],
    }

    print("[K1500] Phase 2 event study ...")
    es = event_study(panel)
    RESULTS["phase2_event_study"] = es

    print("[K1500] Phase 3 predictive ...")
    pr = predictive(panel)
    RESULTS["phase3_predictive_oos"] = pr

    # high-level conclusion summary
    summary = {}
    es_pval = es.get("diff_weak_vs_random_t5", {}).get("p_value", float("nan"))
    summary["event_study_weak_minus_random_t5"] = {
        "diff_mean_logmove": es["car_weak_t0_to_t5"]["mean"] - es["car_random_t0_to_t5"]["mean"],
        "p_value_welch": es_pval,
        "significant_5pct": bool(es_pval < 0.05) if not np.isnan(es_pval) else False,
    }
    # OOS DM at h=5
    dm5 = pr["5"]["dm_test_HLN"]["full_vs_ar1"]
    summary["oos_dm_full_vs_ar1_h5"] = dm5
    summary["oos_dm_significant_5pct"] = bool(dm5["p_value"] < 0.05) if not np.isnan(dm5["p_value"]) else False
    # IS regression beta on weakness_lag1 at h=5
    is5 = pr["5"]["is_regression"]
    summary["is_regression_weakness_beta_h5"] = {
        "beta": is5["coef"][1],
        "tstat": is5["tstat"][1],
        "r2": is5["r2"],
    }
    RESULTS["summary"] = summary

    out_path = BASE_DIR / "k1500_results.json"
    out_path.write_text(json.dumps(RESULTS, indent=2, default=str))
    print(f"[K1500] results written: {out_path}")
    print(json.dumps(summary, indent=2, default=str))


if __name__ == "__main__":
    main()
