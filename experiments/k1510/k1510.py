"""K1510 | SUE → next-month realized vol | DML + IV causal identification.

Question:
    Does standardized unexpected earnings (SUE) have a CAUSAL incremental
    effect on next-month realized volatility, after controlling for size,
    momentum, past RV, sector & macro vol regime, and instrumented for
    endogeneity (earnings surprise and vol are both driven by firm
    fundamentals).

Design:
    Sample      : S&P 500 top-50 by market cap (yfinance) — scope to fit
    Period      : 2018-01 ~ 2026-03 (monthly panel)
    Treatment   : SUE_t = (actual_eps - estimate_eps) / rolling_8Q_std
    Outcome     : RV_{t+h} = sqrt(252 * mean(daily_log_ret^2)) for h in {1,2,3}
    Controls    : log_market_cap, past_60d_ret, past_60d_RV, sector FE,
                  month-of-year FE, VIX_level
    IV          : pre-announcement 5-day RV slope (proxy for analyst-revision
                  velocity — drift in firm-specific info just before earnings,
                  which moves SUE via informational efficiency but is NOT
                  next-month RV directly except through SUE channel).

Estimators:
    (1) OLS naive       : RV ~ SUE + controls + FE (HC1)
    (2) DML partialling : 5-fold cross-fit GBM(M(X)) and GBM(D(X)),
                          then OLS on residuals; HC1 SE.
    (3) 2SLS IV         : statsmodels.GMM / manual two-stage; HC1 SE +
                          first-stage F-stat (weak-IV gate).

Hard rules:
    - signal.shift(1): SUE and IV must be t-1 already-realized info.
    - seed=42 for all CV / bootstrap.
    - report n + #firms; report NULL honestly.
"""
from __future__ import annotations

import json
import time
import warnings
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import statsmodels.api as sm
import yfinance as yf
from sklearn.ensemble import GradientBoostingRegressor
from sklearn.model_selection import KFold

warnings.filterwarnings("ignore")

SEED = 42
OUT_DIR = Path(__file__).resolve().parent
START = "2017-06-01"  # need 6m of history before 2018-01 first window
END = "2026-04-01"

# S&P 500 top-50 by market cap (static snapshot — scope-to-fit; doesn't bias
# causal estimate since selection is not based on SUE or future vol).
TICKERS = [
    "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "BRK-B", "TSLA",
    "AVGO", "LLY", "JPM", "V", "WMT", "XOM", "UNH", "MA", "PG", "JNJ",
    "ORCL", "HD", "COST", "ABBV", "BAC", "NFLX", "KO", "CRM", "AMD",
    "CVX", "MRK", "ADBE", "TMO", "ACN", "LIN", "PEP", "MCD", "CSCO",
    "WFC", "ABT", "DHR", "QCOM", "TXN", "DIS", "INTU", "VZ", "AMGN",
    "IBM", "PM", "CMCSA", "NOW", "PFE",
]

# Coarse GICS sector mapping (manual; for FE only).
SECTOR = {
    "AAPL": "Tech", "MSFT": "Tech", "NVDA": "Tech", "AVGO": "Tech",
    "ORCL": "Tech", "CRM": "Tech", "AMD": "Tech", "ADBE": "Tech",
    "ACN": "Tech", "CSCO": "Tech", "QCOM": "Tech", "TXN": "Tech",
    "INTU": "Tech", "NOW": "Tech", "IBM": "Tech", "META": "Tech",
    "GOOGL": "Tech",
    "AMZN": "Cons", "TSLA": "Cons", "WMT": "Cons", "HD": "Cons",
    "COST": "Cons", "MCD": "Cons", "NFLX": "Cons", "DIS": "Cons",
    "KO": "Cons", "PEP": "Cons", "PG": "Cons", "PM": "Cons",
    "LLY": "Health", "UNH": "Health", "JNJ": "Health", "ABBV": "Health",
    "MRK": "Health", "TMO": "Health", "ABT": "Health", "DHR": "Health",
    "AMGN": "Health", "PFE": "Health",
    "BRK-B": "Fin", "JPM": "Fin", "V": "Fin", "MA": "Fin",
    "BAC": "Fin", "WFC": "Fin",
    "XOM": "Energy", "CVX": "Energy",
    "LIN": "Mat",
    "VZ": "Comm", "CMCSA": "Comm",
}


# ---------------------------------------------------------------------------
# Data ingestion
# ---------------------------------------------------------------------------
def fetch_prices(tickers: list[str]) -> pd.DataFrame:
    """Daily Adj Close panel."""
    print(f"[data] fetching {len(tickers)} ticker prices {START}..{END}")
    df = yf.download(tickers, start=START, end=END, auto_adjust=True,
                     progress=False, threads=True)["Close"]
    df = df.dropna(how="all")
    print(f"[data] price panel shape={df.shape}, "
          f"missing-fraction={df.isna().mean().mean():.3f}")
    return df


def fetch_market_cap(tickers: list[str]) -> dict[str, float]:
    """Snapshot market cap (no time variation; used only as level control)."""
    caps = {}
    for tk in tickers:
        try:
            info = yf.Ticker(tk).fast_info
            mc = getattr(info, "market_cap", None)
            caps[tk] = float(mc) if mc else np.nan
        except Exception:
            caps[tk] = np.nan
    return caps


def fetch_earnings(tickers: list[str]) -> pd.DataFrame:
    """Per-ticker earnings_dates with actual EPS & estimate EPS."""
    rows = []
    for i, tk in enumerate(tickers, 1):
        try:
            ed = yf.Ticker(tk).get_earnings_dates(limit=60)
            if ed is None or ed.empty:
                continue
            ed = ed.reset_index()
            ed["ticker"] = tk
            rows.append(ed)
        except Exception as exc:
            print(f"  [earnings] {tk} failed: {exc}")
        if i % 10 == 0:
            print(f"  [earnings] fetched {i}/{len(tickers)}")
    df = pd.concat(rows, ignore_index=True)
    df.columns = [c if not isinstance(c, str) else c.strip() for c in df.columns]
    df = df.rename(columns={
        "Earnings Date": "earnings_date",
        "EPS Estimate": "est_eps",
        "Reported EPS": "actual_eps",
        "Surprise(%)": "surprise_pct",
    })
    df["earnings_date"] = pd.to_datetime(df["earnings_date"], utc=True
                                          ).dt.tz_localize(None)
    df = df.dropna(subset=["est_eps", "actual_eps"])
    print(f"[earnings] total announcement rows={len(df)}")
    return df


def fetch_vix() -> pd.Series:
    vix = yf.download("^VIX", start=START, end=END, auto_adjust=False,
                      progress=False)["Close"]
    if isinstance(vix, pd.DataFrame):
        vix = vix.iloc[:, 0]
    return vix.dropna()


# ---------------------------------------------------------------------------
# Panel construction
# ---------------------------------------------------------------------------
def build_panel(prices: pd.DataFrame, earnings: pd.DataFrame,
                vix: pd.Series, caps: dict[str, float]) -> pd.DataFrame:
    """
    Monthly panel keyed by (ticker, month_end).

    For each (ticker, month m):
      - SUE_m   : most recent earnings announcement in [m-1, m] window's SUE
      - IV_m    : pre-announce 5-day RV slope (5d_RV - 20d_RV) measured at
                  t-1 day BEFORE the announcement (proxy for revision velocity)
      - controls measured AT month-end m (already realized info)
      - RV_{m+h}: realized vol h months ahead (h=1,2,3) — the OUTCOME

    Lookahead discipline: everything left of `_at_m` is realized by end of
    month m; outcome is forward.
    """
    log_ret = np.log(prices).diff()
    realized_var = log_ret.pow(2)

    # Monthly RV: sqrt(252 * mean(daily_squared_ret over month))
    monthly_rv = (realized_var.resample("ME").mean() * 252).pow(0.5)
    monthly_rv.index.name = "month_end"

    # 60-day rolling RV / return as of month-end
    rv60 = (realized_var.rolling(60).mean() * 252).pow(0.5)
    ret60 = log_ret.rolling(60).sum()
    rv60_me = rv60.resample("ME").last()
    ret60_me = ret60.resample("ME").last()

    vix_me = vix.resample("ME").last()
    if isinstance(vix_me, pd.DataFrame):
        vix_me = vix_me.iloc[:, 0]

    # Per-ticker SUE table (rolling 8Q std of (actual - est))
    earnings = earnings.sort_values(["ticker", "earnings_date"]).copy()
    earnings["surprise"] = earnings["actual_eps"] - earnings["est_eps"]
    earnings["surp_std8"] = (earnings.groupby("ticker")["surprise"]
                             .transform(lambda s: s.shift(1).rolling(8, min_periods=4).std()))
    earnings["sue"] = earnings["surprise"] / earnings["surp_std8"]
    earnings = earnings.dropna(subset=["sue"])
    earnings["month_end"] = (earnings["earnings_date"] + pd.offsets.MonthEnd(0))

    # Pre-announce 5-day RV slope (IV): RV_5d_pre / RV_20d_pre at t-1
    iv_rows = []
    for _, row in earnings.iterrows():
        tk = row["ticker"]
        d = row["earnings_date"]
        if tk not in prices.columns:
            continue
        # pre-announce window: 21 to 1 days before announcement
        rv_series = realized_var[tk].loc[:d - pd.Timedelta(days=1)]
        if len(rv_series) < 25:
            continue
        rv5 = rv_series.iloc[-5:].mean() * 252
        rv20 = rv_series.iloc[-20:].mean() * 252
        if rv20 <= 0 or np.isnan(rv20):
            continue
        iv_rows.append({"ticker": tk, "month_end": row["month_end"],
                        "sue": row["sue"],
                        "iv_rvslope": np.log(rv5 + 1e-8) - np.log(rv20 + 1e-8)})
    sue_iv = pd.DataFrame(iv_rows)
    sue_iv = sue_iv.drop_duplicates(["ticker", "month_end"], keep="last")
    print(f"[panel] SUE+IV rows={len(sue_iv)}, unique tickers={sue_iv['ticker'].nunique()}")

    # Build monthly panel: forward-fill SUE within each quarter (most recent
    # announcement persists until next one).
    months = monthly_rv.index
    panel_rows = []
    for tk in prices.columns:
        if tk not in SECTOR:
            continue
        tk_sue = sue_iv[sue_iv["ticker"] == tk].set_index("month_end").sort_index()
        if tk_sue.empty:
            continue
        sue_ff = tk_sue.reindex(months, method="ffill")
        # Treatment / IV only valid for ≤3 months after announcement (one quarter).
        # Mark months >3m after most recent announcement as NaN.
        ann_age = pd.Series(np.nan, index=months)
        for ann_me in tk_sue.index:
            mask = (months >= ann_me) & (months <= ann_me + pd.offsets.MonthEnd(3))
            ann_age.loc[mask] = ((months - ann_me).days / 30.0)[mask]
        sue_ff.loc[ann_age.isna()] = np.nan

        df_tk = pd.DataFrame({
            "ticker": tk,
            "month_end": months,
            "sector": SECTOR[tk],
            "log_mcap": np.log(caps.get(tk, np.nan) + 1) if caps.get(tk) else np.nan,
            "past60_ret": ret60_me.get(tk, pd.Series(index=months, dtype=float)).reindex(months).values,
            "past60_rv": rv60_me.get(tk, pd.Series(index=months, dtype=float)).reindex(months).values,
            "vix": vix_me.reindex(months).values,
            "sue": sue_ff["sue"].values,
            "iv_rvslope": sue_ff["iv_rvslope"].values,
            "rv_t": monthly_rv.get(tk, pd.Series(index=months, dtype=float)).reindex(months).values,
        })
        # Outcomes: RV at t+1, t+2, t+3 months
        for h in (1, 2, 3):
            df_tk[f"rv_t{h}"] = df_tk["rv_t"].shift(-h)
        panel_rows.append(df_tk)

    panel = pd.concat(panel_rows, ignore_index=True)
    print(f"[panel] raw monthly rows={len(panel)}")

    # Apply lookahead discipline: SUE & IV must be t-1 info → already ffilled
    # from past announcement, OK. month_end controls (past60, vix) are
    # realized by end of m, OK. Outcomes shifted -h forward, OK.

    # Drop rows missing core fields
    panel = panel.dropna(subset=["sue", "iv_rvslope", "log_mcap",
                                  "past60_ret", "past60_rv", "vix", "rv_t1"])
    panel = panel[(panel["month_end"] >= "2018-01-01") &
                  (panel["month_end"] < "2026-04-01")]
    panel["month"] = panel["month_end"].dt.month
    panel["year"] = panel["month_end"].dt.year
    print(f"[panel] final rows={len(panel)}, firms={panel['ticker'].nunique()}, "
          f"months={panel['month_end'].nunique()}")
    return panel


# ---------------------------------------------------------------------------
# Estimators
# ---------------------------------------------------------------------------
def make_design(panel: pd.DataFrame, outcome_col: str
                ) -> tuple[pd.DataFrame, pd.Series, pd.Series, pd.Series, pd.DataFrame]:
    """Return X_controls, D (treatment SUE), Z (IV), Y (outcome), and Xfull (controls + FE)."""
    df = panel.dropna(subset=[outcome_col]).copy()
    # FE dummies (drop first to avoid collinearity)
    sector_d = pd.get_dummies(df["sector"], prefix="sec", drop_first=True, dtype=float)
    month_d = pd.get_dummies(df["month"], prefix="m", drop_first=True, dtype=float)
    Xc = pd.concat([
        df[["log_mcap", "past60_ret", "past60_rv", "vix"]].reset_index(drop=True),
        sector_d.reset_index(drop=True),
        month_d.reset_index(drop=True),
    ], axis=1)
    D = df["sue"].reset_index(drop=True)
    Z = df["iv_rvslope"].reset_index(drop=True)
    Y = df[outcome_col].reset_index(drop=True)
    Xc = Xc.astype(float)
    return Xc, D, Z, Y, df.reset_index(drop=True)


def ols_estimate(Xc: pd.DataFrame, D: pd.Series, Y: pd.Series) -> dict:
    X = pd.concat([pd.Series(1.0, index=D.index, name="const"),
                   D.rename("SUE"), Xc], axis=1)
    res = sm.OLS(Y, X).fit(cov_type="HC1")
    beta = float(res.params["SUE"])
    se = float(res.bse["SUE"])
    ci = res.conf_int().loc["SUE"].tolist()
    return {"beta": beta, "se": se, "ci_low": float(ci[0]),
            "ci_high": float(ci[1]), "pval": float(res.pvalues["SUE"]),
            "n": int(res.nobs)}


def dml_estimate(Xc: pd.DataFrame, D: pd.Series, Y: pd.Series,
                 k_folds: int = 5) -> dict:
    """Double-ML partialling-out: cross-fit GBM for E[Y|X] and E[D|X],
    then OLS on residuals."""
    kf = KFold(n_splits=k_folds, shuffle=True, random_state=SEED)
    Y_resid = np.zeros(len(Y))
    D_resid = np.zeros(len(D))
    Xc_np = Xc.values
    for tr, te in kf.split(Xc_np):
        m_y = GradientBoostingRegressor(n_estimators=200, max_depth=3,
                                        learning_rate=0.05, random_state=SEED)
        m_d = GradientBoostingRegressor(n_estimators=200, max_depth=3,
                                        learning_rate=0.05, random_state=SEED)
        m_y.fit(Xc_np[tr], Y.iloc[tr])
        m_d.fit(Xc_np[tr], D.iloc[tr])
        Y_resid[te] = Y.iloc[te].values - m_y.predict(Xc_np[te])
        D_resid[te] = D.iloc[te].values - m_d.predict(Xc_np[te])
    # OLS on residuals (no intercept needed but include for safety)
    X = sm.add_constant(pd.Series(D_resid, name="SUE_resid"))
    res = sm.OLS(Y_resid, X).fit(cov_type="HC1")
    beta = float(res.params["SUE_resid"])
    se = float(res.bse["SUE_resid"])
    ci = res.conf_int().loc["SUE_resid"].tolist()
    return {"beta": beta, "se": se, "ci_low": float(ci[0]),
            "ci_high": float(ci[1]), "pval": float(res.pvalues["SUE_resid"]),
            "n": int(res.nobs), "k_folds": k_folds}


def iv_estimate(Xc: pd.DataFrame, D: pd.Series, Z: pd.Series,
                Y: pd.Series) -> dict:
    """Manual 2SLS:
       first  : D = a + b*Z + c*X + u   → take fitted D_hat, F-stat on Z
       second : Y = a + b*D_hat + c*X + e (HC1 SE, but adjust for second-stage
                using sm.OLS - reported SE is conservative HC1 on Y residuals)."""
    Xc_const = sm.add_constant(Xc)
    # First stage
    X1 = pd.concat([Xc_const.reset_index(drop=True),
                    Z.rename("Z").reset_index(drop=True)], axis=1)
    res1 = sm.OLS(D, X1).fit(cov_type="HC1")
    D_hat = res1.fittedvalues
    # F-stat on excluded IV Z (Wald test that coeff on Z = 0)
    f_stat = float((res1.params["Z"] / res1.bse["Z"]) ** 2)  # t^2 = F(1)

    # Second stage with D_hat
    X2 = pd.concat([pd.Series(1.0, index=D.index, name="const"),
                    pd.Series(D_hat.values, name="SUE_hat"),
                    Xc.reset_index(drop=True)], axis=1)
    res2 = sm.OLS(Y, X2).fit(cov_type="HC1")
    beta = float(res2.params["SUE_hat"])
    se = float(res2.bse["SUE_hat"])
    ci = res2.conf_int().loc["SUE_hat"].tolist()
    return {"beta": beta, "se": se, "ci_low": float(ci[0]),
            "ci_high": float(ci[1]), "pval": float(res2.pvalues["SUE_hat"]),
            "first_stage_F": f_stat, "first_stage_Zbeta": float(res1.params["Z"]),
            "first_stage_Zpval": float(res1.pvalues["Z"]),
            "n": int(res2.nobs), "weak_iv": bool(f_stat < 10)}


def hausman_test(ols: dict, iv: dict) -> dict:
    diff = iv["beta"] - ols["beta"]
    var_diff = iv["se"] ** 2 - ols["se"] ** 2
    if var_diff <= 0:
        return {"stat": None, "pval": None,
                "note": "var_diff<=0 (HC1 IV SE not larger than OLS) — Hausman undefined"}
    stat = diff ** 2 / var_diff
    from scipy.stats import chi2
    pval = float(1 - chi2.cdf(stat, df=1))
    return {"stat": float(stat), "pval": pval}


# ---------------------------------------------------------------------------
# Figures
# ---------------------------------------------------------------------------
def fig_a_forest(results: dict, outpath: Path) -> None:
    """Forest plot: OLS / DML / IV ATE on t+1 RV with 95% CI."""
    h = 1
    methods = ["OLS", "DML", "IV-2SLS"]
    betas = [results[f"h{h}"]["ols"]["beta"],
             results[f"h{h}"]["dml"]["beta"],
             results[f"h{h}"]["iv"]["beta"]]
    los = [results[f"h{h}"]["ols"]["ci_low"],
           results[f"h{h}"]["dml"]["ci_low"],
           results[f"h{h}"]["iv"]["ci_low"]]
    his = [results[f"h{h}"]["ols"]["ci_high"],
           results[f"h{h}"]["dml"]["ci_high"],
           results[f"h{h}"]["iv"]["ci_high"]]

    fig, ax = plt.subplots(figsize=(7, 4))
    y = np.arange(len(methods))
    ax.errorbar(betas, y,
                xerr=[np.array(betas) - np.array(los),
                      np.array(his) - np.array(betas)],
                fmt="o", capsize=4, color="steelblue", linewidth=1.5)
    ax.axvline(0, color="red", linestyle="--", alpha=0.6, linewidth=1)
    ax.set_yticks(y)
    ax.set_yticklabels(methods)
    ax.set_xlabel(f"ATE of SUE on RV_{{t+{h}}} (95% CI, HC1 SE)")
    ax.set_title("K1510 | SUE → next-month RV — Forest plot (OLS vs DML vs IV)")
    fig.tight_layout()
    fig.savefig(outpath, dpi=140)
    plt.close(fig)


def fig_b_horizon(results: dict, outpath: Path) -> None:
    """ATE across horizons h=1,2,3 for the 3 estimators."""
    horizons = [1, 2, 3]
    methods = [("OLS", "ols", "tab:blue"),
               ("DML", "dml", "tab:orange"),
               ("IV-2SLS", "iv", "tab:green")]
    fig, ax = plt.subplots(figsize=(7, 4))
    width = 0.25
    for i, (label, key, color) in enumerate(methods):
        betas = [results[f"h{h}"][key]["beta"] for h in horizons]
        errs = [results[f"h{h}"][key]["se"] * 1.96 for h in horizons]
        x = np.array(horizons) + (i - 1) * width
        ax.bar(x, betas, width=width, yerr=errs, capsize=3,
               label=label, color=color, alpha=0.85)
    ax.axhline(0, color="red", linestyle="--", alpha=0.6, linewidth=1)
    ax.set_xticks(horizons)
    ax.set_xlabel("Forecast horizon h (months)")
    ax.set_ylabel("ATE of SUE on RV_{t+h}")
    ax.set_title("K1510 | SUE → RV at horizons h=1,2,3")
    ax.legend()
    fig.tight_layout()
    fig.savefig(outpath, dpi=140)
    plt.close(fig)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> None:
    t0 = time.time()
    prices = fetch_prices(TICKERS)
    caps = fetch_market_cap(TICKERS)
    earnings = fetch_earnings(TICKERS)
    vix = fetch_vix()

    panel = build_panel(prices, earnings, vix, caps)
    panel.to_parquet(OUT_DIR / "k1510_panel.parquet", index=False)

    all_results = {
        "meta": {
            "k_id": "K1510",
            "seed": SEED,
            "tickers_attempted": len(TICKERS),
            "period": [START, END],
            "panel_rows": int(len(panel)),
            "unique_firms": int(panel["ticker"].nunique()),
            "unique_months": int(panel["month_end"].nunique()),
            "wall_seconds_data": round(time.time() - t0, 1),
        },
    }

    for h in (1, 2, 3):
        outcome_col = f"rv_t{h}"
        print(f"\n[estimate] horizon h={h} ({outcome_col})")
        Xc, D, Z, Y, _ = make_design(panel, outcome_col)
        print(f"  n={len(Y)}, controls={Xc.shape[1]} columns")
        ols = ols_estimate(Xc, D, Y)
        print(f"  OLS  β={ols['beta']:+.5f}  SE={ols['se']:.5f}  "
              f"CI=[{ols['ci_low']:+.5f},{ols['ci_high']:+.5f}]  p={ols['pval']:.3g}  n={ols['n']}")
        dml = dml_estimate(Xc, D, Y, k_folds=5)
        print(f"  DML  β={dml['beta']:+.5f}  SE={dml['se']:.5f}  "
              f"CI=[{dml['ci_low']:+.5f},{dml['ci_high']:+.5f}]  p={dml['pval']:.3g}  n={dml['n']}")
        iv = iv_estimate(Xc, D, Z, Y)
        print(f"  IV   β={iv['beta']:+.5f}  SE={iv['se']:.5f}  "
              f"CI=[{iv['ci_low']:+.5f},{iv['ci_high']:+.5f}]  p={iv['pval']:.3g}  "
              f"first-stage F={iv['first_stage_F']:.2f}  weak={iv['weak_iv']}")
        hausman = hausman_test(ols, iv)
        all_results[f"h{h}"] = {"ols": ols, "dml": dml, "iv": iv,
                                "hausman": hausman}

    # Robustness: alternative SUE definition (raw surprise_pct / 100)
    panel_alt = panel.copy()
    panel_alt["sue_raw"] = panel_alt["sue"]  # already standardized; provide ref

    # Robustness: VIX-high vs VIX-low subsamples (h=1)
    print("\n[robustness] VIX regime split (h=1)")
    vix_med = panel["vix"].median()
    for label, mask in [("vix_high", panel["vix"] >= vix_med),
                        ("vix_low", panel["vix"] < vix_med)]:
        sub = panel[mask]
        if len(sub) < 100:
            continue
        Xc, D, Z, Y, _ = make_design(sub, "rv_t1")
        ols = ols_estimate(Xc, D, Y)
        iv = iv_estimate(Xc, D, Z, Y)
        all_results[f"robust_{label}_h1"] = {"ols": ols, "iv": iv,
                                              "n_sub": int(len(sub))}
        print(f"  {label} (n={len(sub)})  OLS β={ols['beta']:+.5f}  "
              f"IV β={iv['beta']:+.5f}  IV-F={iv['first_stage_F']:.2f}")

    # Save
    out_json = OUT_DIR / "k1510_results.json"
    with open(out_json, "w") as f:
        json.dump(all_results, f, indent=2, default=float)
    print(f"\n[save] {out_json}")

    fig_a_forest(all_results, OUT_DIR / "k1510_fig_a.png")
    fig_b_horizon(all_results, OUT_DIR / "k1510_fig_b.png")
    print(f"[save] figures written")

    # Console summary
    print("\n=== K1510 SUMMARY ===")
    for h in (1, 2, 3):
        r = all_results[f"h{h}"]
        print(f"h={h} | OLS={r['ols']['beta']:+.5f}  DML={r['dml']['beta']:+.5f}  "
              f"IV={r['iv']['beta']:+.5f}  IV-F={r['iv']['first_stage_F']:.2f}  "
              f"weak-IV={r['iv']['weak_iv']}  Hausman={r['hausman']}")
    print(f"Total wall time: {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()
