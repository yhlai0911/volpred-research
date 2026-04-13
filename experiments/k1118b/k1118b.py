"""
K1118b: Currency cross-asset extension of Paper 4 Universal IV Sufficiency.

Research question (Paper 4 boundary): Native IV sufficiency has been confirmed for
  Equity (SPY / 0050.TW), Commodity (GLD), Bond (TLT partial), Crypto (BTC-FAILED; K1119 DVOL also fail)
  across K473/K750/K789/K504/K1098/K1116/K1118. Currency is the remaining untested class.

Hypotheses:
  H1 (currency IV works): ^EVZ (EuroCurrency VIX) suffices for EUR/USD; cross-market
      ^VIX suffices for DXY/JPY — Paper 4 claim extends to FX universally.
  H2 (currency IV fails): FX volatility driven by central-bank policy / carry trade, not
      risk-premium term structure — IV insufficient across all 3 currencies.
  H3 (reserve-currency specific): DXY/EUR work via dollar channel, JPY fails (safe-haven /
      carry dynamics different from equity-VIX channel).

Data availability findings (yfinance probe 2026-04-13):
  - ^EVZ (CBOE EuroCurrency Volatility): 2010-01-04 to 2025-03-05 (CBOE discontinued
    2025-03; 792 weekly obs, no gaps, no NaN). Last live IV value 2025-03-05.
  - ^JYVIX, ^BPVIX, CVIX: NOT AVAILABLE on yfinance (delisted / never mirrored).
  - ^VIX, UUP (DXY ETF), EURUSD=X, JPY=X, FXY, FXE, DX-Y.NYB: all available 2010-present.

Design (adapted to data availability):
  Sample period 2010-01 to 2025-03 (constrained by ^EVZ end date; 15 years weekly ~= 790 obs).
  IS: 2010-01 to 2018-12 (9 years). OOS: 2019-01 to 2025-03 (6.2 years, covers COVID +
    Fed hike + BOJ YCC end + ECB policy shift — robust stress panel).
  Weekly RV = sqrt(sum(r_d^2)) of daily log-returns; W-FRI aggregation.

Asset list & IV source mapping (each asset tested under 3 alternative IV sources):
  1. EUR/USD (FXE ETF, USD-based, cleaner than EURUSD=X FX spot):
       - Native-EV: ^EVZ (true native currency IV)
       - Cross-VIX: ^VIX (equity proxy)
       - Realized30: 30-day trailing RV (purely backward-looking proxy)
  2. JPY/USD (FXY ETF):
       - Native: N/A (no ^JYVIX) -> Cross-only design
       - Cross-VIX: ^VIX
       - Cross-EVZ: ^EVZ (FX-family IV but not native JPY)
       - Realized30
  3. UUP (DXY ETF):
       - Native-proxy: composite ^EVZ (inverse of EUR weight in DXY basket ~58%)
       - Cross-VIX: ^VIX
       - Realized30

Models (same 5-spec battery as K1116/K1118 for direct compendium comparability):
  M1: AR(1) baseline (y_lag1 only)
  M2: AR(1) + candidate IV (varies per asset - see above)
  M3: AR(1) + EPU composite (USEPU + WLEMU)
  M4: AR(1) + financial stress (NFCI + ANFCI + STLFSI4)
  M5: AR(1) + all

Baseline for DM tests: M2 (the candidate IV model) — testing whether alt-data adds
  value beyond that IV signal. This is the K1116/K1118 convention.

Additionally, for each asset we compare M2 specifications head-to-head:
  - M2_native vs M2_VIX (is native IV better than equity VIX proxy?)
  - M2_native vs M2_Realized30 (does implied IV add beyond realized?)
  This addresses H1 / H2 / H3 directly.

Triple-gate verdict (K1116 convention):
  - DM-HLN |t| > 2 (Harvey threshold 3.0 applied for strong claim)
  - QLIKE improvement > 5% vs baseline
  - Sub-period stability: challenger wins in >= 2 of 3 year-bins
  Triple-gate PASS = alt-data has niche; NULL = IV sufficient.

H2 rejection condition (for Paper 4 narrative):
  If all 3 currencies show M2 DM t < -2 vs M1 (IV has no explanatory power beyond AR),
  H2 confirmed: Paper 4 boundary narrows to equity/bond/commodity, FX joins crypto.

Random seed: 42 (for any bootstrap / resampling).
Lookahead: all regressors use .shift(1); weekly aggregation precludes intra-week leak.

References:
  - Paper 4 predecessors: K473, K750, K789, K504, K1098, K1116, K1116b, K1118, K1119
  - Baker, Bloom, Davis (2016) QJE - EPU
  - Brave, Butters (2011) - NFCI
  - Patton (2011) - QLIKE proxy-robust
  - Harvey, Leybourne, Newbold (1997) - HLN DM correction
  - Menkhoff, Sarno, Schmeling, Schrimpf (2012) "Carry Trades and Global FX Volatility" JF
    — motivates FX vol distinct from equity VIX channel (H2 rationale)
  - Lustig, Roussanov, Verdelhan (2011) "Common Risk Factors in Currency Markets" RFS
    — dollar factor / carry factor may override VIX in FX vol prediction
"""
import json
import warnings
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

OUT_DIR = Path(__file__).parent
RESULTS = {
    "experiment_id": "K1118b",
    "title": "Currency cross-asset extension of Paper 4 Universal IV Sufficiency",
    "started_utc": datetime.utcnow().isoformat() + "Z",
    "data_source": "yfinance (FXE, FXY, UUP, ^EVZ, ^VIX) + FRED (USEPUINDXD, WLEMUINDXD, NFCI, ANFCI, STLFSI4)",
    "period": "2010-01 to 2025-03 weekly (W-FRI); constrained by ^EVZ discontinuation 2025-03-05",
    "is_period": "2010-01 to 2018-12 (9 years)",
    "oos_period": "2019-01 to 2025-03 (6.2 years: COVID / Fed hike / BOJ YCC end / ECB pivot)",
    "predecessors": {
        "K1116": "SPY EPU+NFCI+STLFSI vs VIX NULL",
        "K1118": "GLD/TLT/BTC: 3/3 NULL (GVZ/MOVE sufficient; BTC-RV30 proxy failed)",
        "K1119": "BTC DVOL sufficient vs alt-data (still failed vs GJR baseline)",
        "K1098": "0050.TW VIXTWN sufficient",
    },
    "hypotheses": {
        "H1_currency_IV_universal": "EVZ/VIX suffices for all 3 FX — Paper 4 boundary extends to FX",
        "H2_currency_IV_fails": "All 3 M2 DM t<-2 vs M1 OR all 3 triple-gate NULL -> FX joins crypto in IV-insufficient class",
        "H3_reserve_currency_specific": "DXY/EUR work, JPY fails (safe-haven channel distinct)",
    },
    "references": [
        "Baker, Bloom, Davis (2016) QJE - EPU",
        "Brave, Butters (2011) - NFCI",
        "Patton (2011) - QLIKE proxy-robust",
        "Harvey, Leybourne, Newbold (1997) - HLN DM",
        "Menkhoff, Sarno, Schmeling, Schrimpf (2012) JF - FX carry vol",
        "Lustig, Roussanov, Verdelhan (2011) RFS - currency risk factors",
    ],
}


def log(msg):
    ts = datetime.utcnow().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


def fetch_series(ticker, start, end, col="Close"):
    import yfinance as yf

    df = yf.download(ticker, start=start, end=end, progress=False, auto_adjust=True)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    if df is None or len(df) == 0:
        raise RuntimeError(f"empty series for {ticker}")
    return df[[col]].rename(columns={col: ticker}).copy()


def fetch_asset_weekly(ticker, start, end):
    """Daily prices -> weekly RV (sqrt sum r^2) + realized-30d proxy (trailing)
    + weekly signed log-return (for VaR backtest)."""
    df = fetch_series(ticker, start, end)
    df["r"] = np.log(df[ticker]).diff()
    df["rv30"] = df["r"].rolling(30).apply(
        lambda x: np.sqrt(np.sum(x.dropna() ** 2) * (252.0 / 30.0))
    )
    df["week"] = df.index.to_period("W-FRI").to_timestamp("W-FRI")
    wk = df.groupby("week").agg(
        rv=("r", lambda x: np.sqrt(np.sum(x.dropna() ** 2))),
        r_wk=("r", "sum"),  # signed weekly log-return
        n=("r", "count"),
        rv30_mean=("rv30", "mean"),
        rv30_last=("rv30", "last"),
    )
    wk = wk[wk["n"] >= 4].copy()
    return wk


def fetch_iv_weekly(ticker, start, end):
    import yfinance as yf

    df = yf.download(ticker, start=start, end=end, progress=False, auto_adjust=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    if df is None or len(df) == 0:
        raise RuntimeError(f"empty IV series for {ticker}")
    df = df[["Close"]].rename(columns={"Close": "iv"}).copy()
    df["week"] = df.index.to_period("W-FRI").to_timestamp("W-FRI")
    out = df.groupby("week").agg(
        iv_mean=("iv", "mean"),
        iv_last=("iv", "last"),
    )
    return out


def fetch_fred_altdata(start, end):
    import io
    import requests

    codes = {
        "USEPU": "USEPUINDXD",
        "WLEMU": "WLEMUINDXD",
        "NFCI": "NFCI",
        "ANFCI": "ANFCI",
        "STLFSI": "STLFSI4",
    }
    log(f"FRED fetch: {list(codes.values())}")
    sess = requests.Session()
    sess.headers.update(
        {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"}
    )
    frames = {}
    for name, code in codes.items():
        url = (
            f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={code}"
            f"&cosd={start}&coed={end}"
        )
        r = sess.get(url, timeout=90)
        r.raise_for_status()
        s = pd.read_csv(io.StringIO(r.text))
        date_col = s.columns[0]
        s[date_col] = pd.to_datetime(s[date_col])
        s = s.set_index(date_col)
        s.columns = [name]
        s[name] = pd.to_numeric(s[name], errors="coerce")
        s = s.dropna()
        log(f"  {code}: n={len(s)} first={s.index[0].date()} last={s.index[-1].date()}")
        s["week"] = s.index.to_period("W-FRI").to_timestamp("W-FRI")
        frames[name] = s.groupby("week").agg({name: "mean"})
    out = frames["USEPU"]
    for n in ["WLEMU", "NFCI", "ANFCI", "STLFSI"]:
        out = out.join(frames[n], how="outer")
    out = out.sort_index().ffill(limit=2)
    return out


# ----- stats utilities -----

def qlike(actual, pred):
    eps = 1e-10
    a = np.maximum(actual, eps)
    p = np.maximum(pred, eps)
    return float(np.mean(np.log(p) + a / p))


def kupiec_lr(x, alpha):
    """Kupiec (1995) unconditional coverage LR test.
    x: indicator array of violations (1 if violated, 0 otherwise). alpha: target rate.
    Returns (LR stat, p-value).
    """
    from scipy import stats as st

    x = np.asarray(x, dtype=int)
    n = len(x)
    if n < 50:
        return np.nan, np.nan
    k = int(x.sum())
    if k == 0:
        # no violations: model very conservative
        lr = -2 * (k * np.log(1e-10) + (n - k) * np.log(1 - alpha))
    elif k == n:
        lr = -2 * (k * np.log(alpha) + (n - k) * np.log(1e-10))
    else:
        phat = k / n
        ll0 = k * np.log(alpha) + (n - k) * np.log(1 - alpha)
        ll1 = k * np.log(phat) + (n - k) * np.log(1 - phat)
        lr = -2 * (ll0 - ll1)
    p = 1 - st.chi2.cdf(lr, df=1)
    return float(lr), float(p)


def christoffersen_cc(x, alpha):
    """Christoffersen (1998) conditional coverage joint test.
    Tests independence of violations + unconditional coverage.
    """
    from scipy import stats as st

    x = np.asarray(x, dtype=int)
    n = len(x)
    if n < 50:
        return np.nan, np.nan
    k = int(x.sum())
    if k == 0 or k == n:
        lr_u, _ = kupiec_lr(x, alpha)
        return lr_u, float(1 - st.chi2.cdf(lr_u, df=2)) if not np.isnan(lr_u) else np.nan

    # Transition counts
    n00 = n01 = n10 = n11 = 0
    for i in range(1, n):
        if x[i - 1] == 0 and x[i] == 0:
            n00 += 1
        elif x[i - 1] == 0 and x[i] == 1:
            n01 += 1
        elif x[i - 1] == 1 and x[i] == 0:
            n10 += 1
        elif x[i - 1] == 1 and x[i] == 1:
            n11 += 1
    pi01 = n01 / (n00 + n01) if (n00 + n01) > 0 else 0
    pi11 = n11 / (n10 + n11) if (n10 + n11) > 0 else 0
    pi = (n01 + n11) / (n00 + n01 + n10 + n11) if (n00 + n01 + n10 + n11) > 0 else 0

    def _safe_log(x):
        return np.log(max(x, 1e-15))

    ll_ind = (
        n00 * _safe_log(1 - pi) + n01 * _safe_log(pi)
        + n10 * _safe_log(1 - pi) + n11 * _safe_log(pi)
    )
    ll_dep = (
        n00 * _safe_log(1 - pi01) + n01 * _safe_log(pi01)
        + n10 * _safe_log(1 - pi11) + n11 * _safe_log(pi11)
    )
    lr_ind = -2 * (ll_ind - ll_dep)
    lr_uc, _ = kupiec_lr(x, alpha)
    lr_cc = lr_uc + lr_ind
    p = 1 - st.chi2.cdf(lr_cc, df=2)
    return float(lr_cc), float(p)


def var_trinity(actual_ret, pred_vol, alpha=0.05):
    """VaR Trinity (Kupiec UC + Christoffersen CC + traffic light).
    actual_ret: realized weekly returns (SIGNED, not |r|). pred_vol: predicted vol (sigma).
    VaR = -z * pred_vol (one-sided left tail).
    """
    from scipy import stats as st

    z = st.norm.ppf(alpha)  # negative for alpha<0.5
    actual_ret = np.asarray(actual_ret)
    pred_vol = np.asarray(pred_vol)
    var = z * pred_vol  # negative number (loss threshold)
    viol = (actual_ret < var).astype(int)
    n = len(viol)
    k = int(viol.sum())
    uc_lr, uc_p = kupiec_lr(viol, alpha)
    cc_lr, cc_p = christoffersen_cc(viol, alpha)
    # Basel traffic light (normally applied to 250-day windows, approximated here)
    target_k = alpha * n
    if k <= target_k + 1.65 * np.sqrt(n * alpha * (1 - alpha)):
        light = "Green"
    elif k <= target_k + 2.33 * np.sqrt(n * alpha * (1 - alpha)):
        light = "Yellow"
    else:
        light = "Red"
    trinity = (
        (not np.isnan(uc_p)) and uc_p > 0.05
        and (not np.isnan(cc_p)) and cc_p > 0.05
        and light == "Green"
    )
    return {
        "alpha": alpha,
        "n": int(n),
        "k_violations": int(k),
        "target_k": float(target_k),
        "violation_rate": float(k / n) if n else None,
        "Kupiec_LR": uc_lr,
        "Kupiec_p": uc_p,
        "Christoffersen_LR": cc_lr,
        "Christoffersen_p": cc_p,
        "Basel_light": light,
        "trinity_PASS": bool(trinity),
    }


def dm_hln(e1, e2, h=1):
    """DM-HLN. e1=baseline loss, e2=challenger loss. Positive t => challenger beats baseline."""
    from scipy import stats as st

    d = np.asarray(e1, dtype=float) - np.asarray(e2, dtype=float)
    d = d[~np.isnan(d)]
    n = len(d)
    if n < 10:
        return np.nan, np.nan
    dbar = d.mean()
    gamma0 = np.var(d, ddof=1)
    if gamma0 <= 0:
        return np.nan, np.nan
    hln = np.sqrt((n + 1 - 2 * h + h * (h - 1) / n) / n)
    se = np.sqrt(gamma0 / n)
    t = (dbar / se) * hln
    p = 2 * (1 - st.t.cdf(abs(t), df=n - 1))
    return float(t), float(p)


# ----- per-asset model battery -----

def run_asset(
    asset_name,
    price_ticker,
    iv_candidates,  # dict: {label: ticker_or_None}. None => realized30 proxy
    altdata,
    start,
    end,
    is_end="2018-12-31",
    oos_start="2019-01-01",
):
    import statsmodels.api as sm

    log(f"\n===== Asset: {asset_name} (price={price_ticker}) IVs={list(iv_candidates)} =====")
    market = fetch_asset_weekly(price_ticker, start, end)
    log(
        f"  Weekly panel: n={len(market)}, "
        f"{market.index.min().date()} to {market.index.max().date()}, "
        f"RV mean={market['rv'].mean():.4f} std={market['rv'].std():.4f}"
    )

    # Build IV candidate columns
    iv_data = {}
    for label, tck in iv_candidates.items():
        if tck is None:
            # realized-30 proxy (already in market as rv30_mean)
            iv_data[label] = market[["rv30_mean"]].rename(
                columns={"rv30_mean": "iv_mean"}
            )
        else:
            iv_w = fetch_iv_weekly(tck, start, end)
            iv_data[label] = iv_w
            log(
                f"  IV {label} ({tck}): n={len(iv_w)}, "
                f"{iv_w.index.min().date()} to {iv_w.index.max().date()}, "
                f"mean={iv_w['iv_mean'].mean():.3f}"
            )

    # Merge altdata (keep r_wk for VaR backtest)
    base_panel = market[["rv", "r_wk"]].join(altdata, how="inner").dropna()
    log(f"  Panel+altdata: n={len(base_panel)}")

    results_by_iv = {}
    for iv_label, iv_df in iv_data.items():
        df = base_panel.join(iv_df[["iv_mean"]], how="inner").dropna()
        df_is = df.loc[:is_end].copy()
        df_oos = df.loc[oos_start:].copy()
        if len(df_is) < 50 or len(df_oos) < 50:
            log(f"  IV {iv_label}: insufficient sample (IS={len(df_is)}, OOS={len(df_oos)})")
            continue
        log(f"  IV {iv_label}: IS n={len(df_is)}, OOS n={len(df_oos)}")

        alt_cols = list(altdata.columns)

        def make_X(df_sub, spec):
            X = pd.DataFrame(index=df_sub.index)
            X["y_lag1"] = df_sub["rv"].shift(1)
            if spec == "base":
                return X.dropna()
            if spec == "iv":
                X["iv_lag1"] = df_sub["iv_mean"].shift(1)
            elif spec == "epu":
                X["USEPU_lag1"] = df_sub["USEPU"].shift(1)
                X["WLEMU_lag1"] = df_sub["WLEMU"].shift(1)
            elif spec == "finstress":
                X["NFCI_lag1"] = df_sub["NFCI"].shift(1)
                X["ANFCI_lag1"] = df_sub["ANFCI"].shift(1)
                X["STLFSI_lag1"] = df_sub["STLFSI"].shift(1)
            elif spec == "all":
                X["iv_lag1"] = df_sub["iv_mean"].shift(1)
                X["USEPU_lag1"] = df_sub["USEPU"].shift(1)
                X["WLEMU_lag1"] = df_sub["WLEMU"].shift(1)
                X["NFCI_lag1"] = df_sub["NFCI"].shift(1)
                X["ANFCI_lag1"] = df_sub["ANFCI"].shift(1)
                X["STLFSI_lag1"] = df_sub["STLFSI"].shift(1)
            return X.dropna()

        specs = ["base", "iv", "epu", "finstress", "all"]
        model_names = {
            "base": "M1_AR1",
            "iv": "M2_AR1_IV",
            "epu": "M3_AR1_EPU",
            "finstress": "M4_AR1_FinStress",
            "all": "M5_AR1_All",
        }

        is_results = {}
        fitted = {}
        oos_losses = {}
        oos_forecasts = {}

        for spec in specs:
            name = model_names[spec]
            X_is = make_X(df_is, spec)
            y_is = df_is["rv"].loc[X_is.index]
            Xc_is = sm.add_constant(X_is, has_constant="add")
            ols = sm.OLS(y_is, Xc_is).fit()
            fitted[name] = (ols, Xc_is.columns.tolist())
            is_results[name] = {
                "r2": float(ols.rsquared),
                "adj_r2": float(ols.rsquared_adj),
                "aic": float(ols.aic),
                "bic": float(ols.bic),
                "n_is": int(len(y_is)),
                "params": {k: float(v) for k, v in ols.params.to_dict().items()},
                "pvalues": {k: float(v) for k, v in ols.pvalues.to_dict().items()},
            }
            X_oos = make_X(df_oos, spec)
            Xc_oos = sm.add_constant(X_oos, has_constant="add").reindex(
                columns=Xc_is.columns, fill_value=0.0
            )
            pred = ols.predict(Xc_oos).clip(lower=1e-6)
            actual = df_oos["rv"].loc[X_oos.index]
            oos_forecasts[name] = {"pred": pred, "actual": actual}
            oos_losses[name] = np.log(pred) + actual / pred

        # Align common OOS index
        baseline = "M2_AR1_IV"
        common_idx = oos_losses[baseline].index
        for m in oos_losses:
            common_idx = common_idx.intersection(oos_losses[m].index)
        base_loss = oos_losses[baseline].reindex(common_idx)

        # Primary DM: baseline vs each challenger
        dm_tests = {}
        for m in ["M1_AR1", "M3_AR1_EPU", "M4_AR1_FinStress", "M5_AR1_All"]:
            m_loss = oos_losses[m].reindex(common_idx)
            t, p = dm_hln(base_loss.values, m_loss.values)
            challenger_wins = (not np.isnan(t)) and (t > 2.0)
            baseline_wins = (not np.isnan(t)) and (t < -2.0)
            dm_tests[f"{baseline}_vs_{m}"] = {
                "t_stat": None if np.isnan(t) else t,
                "p_value": None if np.isnan(p) else p,
                "challenger_wins_harvey": bool(challenger_wins),
                "baseline_wins_harvey": bool(baseline_wins),
            }

        # H1/H2 direct test: does M2 (IV) beat M1 (no IV)?
        m1_loss = oos_losses["M1_AR1"].reindex(common_idx)
        t_iv, p_iv = dm_hln(m1_loss.values, base_loss.values)
        # e1=M1, e2=M2 => positive t => M2 (IV) beats M1
        iv_vs_ar1 = {
            "t_stat": None if np.isnan(t_iv) else t_iv,
            "p_value": None if np.isnan(p_iv) else p_iv,
            "iv_beats_ar1_harvey": (not np.isnan(t_iv)) and (t_iv > 2.0),
            "ar1_beats_iv_harvey": (not np.isnan(t_iv)) and (t_iv < -2.0),
        }

        # IS / OOS QLIKE table
        is_oos_table = {}
        for name in model_names.values():
            ols, cols = fitted[name]
            spec = [k for k, v in model_names.items() if v == name][0]
            X_is = make_X(df_is, spec)
            Xc_is = sm.add_constant(X_is, has_constant="add").reindex(
                columns=cols, fill_value=0.0
            )
            pred_is = ols.predict(Xc_is).clip(lower=1e-6)
            actual_is = df_is["rv"].loc[X_is.index]
            is_q = qlike(actual_is.values, pred_is.values)
            actual_oos = oos_forecasts[name]["actual"].reindex(common_idx)
            pred_oos = oos_forecasts[name]["pred"].reindex(common_idx)
            oos_q = qlike(actual_oos.values, pred_oos.values)
            oos_r = float(np.sqrt(np.mean((actual_oos.values - pred_oos.values) ** 2)))
            is_oos_table[name] = {
                "IS_R2": is_results[name]["r2"],
                "IS_QLIKE": is_q,
                "OOS_QLIKE": oos_q,
                "OOS_RMSE": oos_r,
                "OOS_n": int(len(common_idx)),
                "divergence_IS_OOS": oos_q - is_q,
            }

        # Sub-period stability — bucket years; here we have 2019-2024 windows (>= 2 obs)
        subperiod_dm = {}
        # Use 2-year bins for FX sample
        bins = [(2019, 2020), (2021, 2022), (2023, 2025)]
        for bin_ in bins:
            yrs = list(range(bin_[0], bin_[1] + 1))
            mask = pd.Series(
                [d.year in yrs for d in common_idx], index=common_idx
            )
            n_yr = int(mask.sum())
            if n_yr < 15:
                subperiod_dm[f"{bin_[0]}-{bin_[1]}"] = {"n": n_yr, "note": "insufficient"}
                continue
            subperiod_dm[f"{bin_[0]}-{bin_[1]}"] = {"n": n_yr}
            base_sub = base_loss[mask].values
            for m in ["M3_AR1_EPU", "M4_AR1_FinStress", "M5_AR1_All"]:
                m_sub = oos_losses[m].reindex(common_idx)[mask].values
                t, p = dm_hln(base_sub, m_sub)
                subperiod_dm[f"{bin_[0]}-{bin_[1]}"][f"{baseline}_vs_{m}"] = {
                    "t_stat": None if np.isnan(t) else t,
                    "p_value": None if np.isnan(p) else p,
                    "challenger_wins_harvey": (not np.isnan(t)) and (t > 2.0),
                    "baseline_wins_harvey": (not np.isnan(t)) and (t < -2.0),
                }

        # VaR Trinity on baseline IV model (M2) at 5% and 1%
        var_results = {}
        baseline_pred = oos_forecasts[baseline]["pred"].reindex(common_idx)
        actual_rwk = df_oos["r_wk"].reindex(common_idx).dropna()
        shared = baseline_pred.index.intersection(actual_rwk.index)
        if len(shared) >= 50:
            for a in (0.05, 0.01):
                var_results[f"alpha_{a:.2f}"] = var_trinity(
                    actual_rwk.loc[shared], baseline_pred.loc[shared], alpha=a
                )

        # Triple-gate
        base_oos_q = is_oos_table[baseline]["OOS_QLIKE"]
        alt_models = ["M3_AR1_EPU", "M4_AR1_FinStress", "M5_AR1_All"]
        best_alt = min(alt_models, key=lambda m: is_oos_table[m]["OOS_QLIKE"])
        best_alt_q = is_oos_table[best_alt]["OOS_QLIKE"]
        qlike_imp = float((base_oos_q - best_alt_q) / abs(base_oos_q) * 100)

        h1_chal_wins = any(
            v["challenger_wins_harvey"] for k, v in dm_tests.items() if k != f"{baseline}_vs_M1_AR1"
        )
        bw_count = sum(
            1 for k, v in dm_tests.items()
            if k != f"{baseline}_vs_M1_AR1" and v["baseline_wins_harvey"]
        )
        qlike_pass = qlike_imp > 5.0
        stability = sum(
            1 for yr, d in subperiod_dm.items()
            if isinstance(d, dict) and d.get("n", 0) >= 15
            and any(
                isinstance(v, dict) and v.get("challenger_wins_harvey", False)
                for v in d.values()
            )
        )
        h3_stability = stability >= 2

        triple_gate = h1_chal_wins and qlike_pass and h3_stability
        active_harm = bw_count >= 2
        if triple_gate:
            verdict = "POSITIVE (triple-gate passed)"
        elif active_harm:
            verdict = "NULL (IV baseline actively beats alt-data)"
        else:
            verdict = "NULL (no significant improvement)"

        results_by_iv[iv_label] = {
            "iv_source": iv_candidates[iv_label],
            "n_is": int(len(df_is)),
            "n_oos": int(len(df_oos)),
            "n_common_oos": int(len(common_idx)),
            "is_results": is_results,
            "is_oos_comparison": is_oos_table,
            "dm_tests_full_oos": dm_tests,
            "iv_vs_ar1_DM": iv_vs_ar1,
            "subperiod_dm": subperiod_dm,
            "var_trinity_M2": var_results,
            "best_alt_model": best_alt,
            "qlike_improvement_pct": qlike_imp,
            "gates": {
                "H1_any_challenger_beats_IV": bool(h1_chal_wins),
                "baseline_beats_challengers_count": int(bw_count),
                "QLIKE_improvement_gt_5pct": bool(qlike_pass),
                "subperiod_stability_ge_2of3": bool(h3_stability),
                "triple_gate_PASS": bool(triple_gate),
                "active_harm_alt_data_worse_than_IV": bool(active_harm),
            },
            "verdict": verdict,
        }

    return {
        "asset": asset_name,
        "price_ticker": price_ticker,
        "iv_candidates": iv_candidates,
        "by_iv": results_by_iv,
    }


def main():
    np.random.seed(42)
    start = "2010-01-01"
    end = "2025-03-15"

    altdata = fetch_fred_altdata(start, end)
    log(f"Altdata panel: n={len(altdata)}, {altdata.index.min().date()} to {altdata.index.max().date()}")
    RESULTS["alt_data_columns"] = list(altdata.columns)

    asset_configs = [
        ("EUR_USD",
         "FXE",
         {"Native_EVZ": "^EVZ", "Cross_VIX": "^VIX", "Realized30": None}),
        ("JPY_USD",
         "FXY",
         {"Cross_VIX": "^VIX", "Cross_EVZ": "^EVZ", "Realized30": None}),
        ("DXY",
         "UUP",
         {"Native_EVZ": "^EVZ", "Cross_VIX": "^VIX", "Realized30": None}),
    ]

    asset_results = {}
    for name, pt, iv_cfg in asset_configs:
        try:
            asset_results[name] = run_asset(
                name, pt, iv_cfg, altdata, start, end
            )
        except Exception as e:
            import traceback

            log(f"Asset {name} FAILED: {e}")
            traceback.print_exc()
            asset_results[name] = {"error": str(e)}

    RESULTS["asset_results"] = asset_results

    # Synthesis — for each asset, use the Native IV first (if available) else Cross_VIX
    log("\n===== Cross-asset synthesis =====")
    preferred_iv = {
        "EUR_USD": "Native_EVZ",
        "JPY_USD": "Cross_VIX",
        "DXY": "Native_EVZ",
    }
    synth = {}
    for name, r in asset_results.items():
        if "error" in r:
            synth[name] = {"status": "error", "error": r["error"]}
            continue
        iv_key = preferred_iv[name]
        by_iv = r["by_iv"]
        primary = by_iv.get(iv_key, list(by_iv.values())[0] if by_iv else None)
        if primary is None:
            synth[name] = {"status": "no_primary_iv"}
            continue
        synth[name] = {
            "primary_iv_source": iv_key,
            "iv_vs_ar1_t": primary["iv_vs_ar1_DM"]["t_stat"],
            "iv_vs_ar1_p": primary["iv_vs_ar1_DM"]["p_value"],
            "iv_beats_ar1": primary["iv_vs_ar1_DM"]["iv_beats_ar1_harvey"],
            "ar1_beats_iv": primary["iv_vs_ar1_DM"]["ar1_beats_iv_harvey"],
            "verdict_vs_altdata": primary["verdict"],
            "triple_gate": primary["gates"]["triple_gate_PASS"],
            "active_harm": primary["gates"]["active_harm_alt_data_worse_than_IV"],
            "qlike_improvement_pct": primary["qlike_improvement_pct"],
            "best_alt_model": primary["best_alt_model"],
        }
    RESULTS["cross_asset_synthesis"] = synth

    # Hypothesis resolution — evaluate each asset at both "primary" (prefer native) and
    # "any IV" levels. H1 requires at least one IV source beats AR1 at Harvey |t|>2
    # (i.e., *some* implied-vol signal suffices); H2 requires all IV sources fail;
    # H3 is mixed outcome by asset with primary-IV rule.

    def any_iv_beats_ar1(asset_res):
        """Does any IV source (including realized30 proxy) beat AR1 at Harvey threshold?"""
        out = {"any_iv_wins": False, "ar1_wins_all": True, "sources_win": [], "best_t": None}
        for label, ivr in asset_res.get("by_iv", {}).items():
            t = ivr["iv_vs_ar1_DM"]["t_stat"]
            if t is None:
                continue
            if out["best_t"] is None or t > out["best_t"]:
                out["best_t"] = t
            if ivr["iv_vs_ar1_DM"]["iv_beats_ar1_harvey"]:
                out["any_iv_wins"] = True
                out["ar1_wins_all"] = False
                out["sources_win"].append(label)
            elif not ivr["iv_vs_ar1_DM"]["ar1_beats_iv_harvey"]:
                out["ar1_wins_all"] = False
        return out

    iv_success_primary = {}
    iv_success_any = {}
    iv_any_detail = {}
    for name, s in synth.items():
        if "error" in s or "status" in s:
            iv_success_primary[name] = None
            iv_success_any[name] = None
            continue
        iv_success_primary[name] = bool(s.get("iv_beats_ar1", False))
        ar = asset_results.get(name, {})
        any_info = any_iv_beats_ar1(ar)
        iv_success_any[name] = bool(any_info["any_iv_wins"])
        iv_any_detail[name] = any_info

    n_any_success = sum(1 for v in iv_success_any.values() if v is True)
    n_any_fail = sum(1 for v in iv_success_any.values() if v is False)
    n_valid = sum(1 for v in iv_success_any.values() if v is not None)

    # Refined hypothesis classification (prefer any-IV rule for H1/H2)
    iv_success = iv_success_any

    n_iv_success = sum(1 for v in iv_success.values() if v is True)
    n_iv_fail = sum(1 for v in iv_success.values() if v is False)

    h1_universal = n_iv_success == n_valid and n_valid == 3
    h2_all_fail = n_iv_success == 0 and n_valid >= 2
    h3_mixed = (
        iv_success.get("DXY") is True
        and iv_success.get("EUR_USD") is True
        and iv_success.get("JPY_USD") is False
    ) or (
        # symmetric: DXY fails but EUR/JPY pass — any mixed pattern
        n_iv_success in (1, 2) and n_valid == 3
    )

    RESULTS["hypothesis_tests"] = {
        "H1_currency_IV_universal": bool(h1_universal),
        "H2_currency_IV_fails_all": bool(h2_all_fail),
        "H3_reserve_currency_specific": bool(h3_mixed),
        "iv_success_per_asset_any": iv_success_any,
        "iv_success_per_asset_primary": iv_success_primary,
        "iv_any_detail": iv_any_detail,
        "n_iv_success_any": int(n_any_success),
        "n_iv_fail_any": int(n_any_fail),
        "n_valid": int(n_valid),
    }

    # Paper 4 boundary implication
    # Narrative string
    pass_str = ", ".join(f"{k}={v}" for k, v in iv_success.items())
    if h1_universal:
        impl = (
            f"EXTENDS: All 3 FX have at least one IV source beating AR1 at Harvey |t|>2. "
            f"Per-asset: {pass_str}. Paper 4 compendium covers equity+bond+commodity+FX; "
            f"only crypto remains IV-insufficient. Universal claim strengthened."
        )
    elif h2_all_fail:
        impl = (
            f"NARROWS: No IV source beats AR1 for any tested FX. Per-asset: {pass_str}. "
            f"Paper 4 boundary = equity + bond + commodity; FX joins crypto in the "
            f"IV-insufficient class. Menkhoff et al. (2012) FX carry vol channel "
            f"supports this reading."
        )
    elif iv_success.get("DXY") is True and iv_success.get("EUR_USD") is True and iv_success.get("JPY_USD") is False:
        impl = (
            f"RESERVE-CURRENCY SPECIFIC: {pass_str}. DXY + EUR work via dollar/Euro IV "
            f"channel; JPY fails (safe-haven / BOJ policy dynamics distinct). "
            f"Paper 4 compendium extends to dollar-bloc FX only. Lustig-Roussanov-"
            f"Verdelhan (2011) dollar-factor reading."
        )
    elif h3_mixed:
        impl = (
            f"MIXED (asset-specific): {pass_str}. Some FX admit IV signal, others do not. "
            f"Paper 4 needs FX sub-class nuance rather than universal claim."
        )
    else:
        impl = f"See per-asset verdicts; {pass_str}."

    RESULTS["paper4_boundary_implication"] = impl
    RESULTS["finished_utc"] = datetime.utcnow().isoformat() + "Z"

    with open(OUT_DIR / "k1118b_results.json", "w") as f:
        json.dump(RESULTS, f, indent=2, default=str)
    log(f"Saved -> {OUT_DIR / 'k1118b_results.json'}")

    # Summary print
    print("\n" + "=" * 90)
    print("K1118b SUMMARY — Currency cross-asset extension")
    print("=" * 90)
    for name, r in asset_results.items():
        if "error" in r:
            print(f"\n[{name}] ERROR: {r['error']}")
            continue
        print(f"\n[{name}] price={r['price_ticker']}")
        for iv_label, ivr in r["by_iv"].items():
            iv_src = r["iv_candidates"][iv_label]
            iv_src_str = iv_src if iv_src else "realized30"
            ivar = ivr["iv_vs_ar1_DM"]
            print(f"  [{iv_label} <- {iv_src_str}]")
            print(
                f"    IV vs AR1 DM: t={ivar['t_stat']:+.3f} p={ivar['p_value']:.4f} "
                f"iv_beats_ar1={ivar['iv_beats_ar1_harvey']} ar1_beats_iv={ivar['ar1_beats_iv_harvey']}"
            )
            print(f"    Best alt: {ivr['best_alt_model']}  QLIKE imp: {ivr['qlike_improvement_pct']:+.2f}%")
            print(f"    Verdict vs alt-data: {ivr['verdict']}")
    print("\nHypothesis tests:")
    for k, v in RESULTS["hypothesis_tests"].items():
        print(f"  {k}: {v}")
    print(f"\nPaper 4 boundary implication:\n  {RESULTS['paper4_boundary_implication']}")


if __name__ == "__main__":
    main()
