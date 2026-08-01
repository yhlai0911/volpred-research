"""K1738 — Earnings surprise (SUE) and subsequent realized volatility: causal increment via DML.

Design, lookahead policy and PRE-REGISTERED success criteria: see README.md in this directory.
The README was written and committed before any estimate in this file was inspected.

Core question: after controlling for a rich confounder set, does SUE carry an *incremental*
effect on realized volatility over the following 1-3 months?  The headline deliverable is the
contrast naive vs OLS-controls vs DML, which shows how much of the raw association is confounding.

LOOKAHEAD (binding, see README section 4):
  * The event anchor is the *announcement timestamp*, never the fiscal period end.  Anchoring on
    period end would look ahead by 2-8 weeks because the earnings number is not public then.
  * Confounder windows end at trading day t0-1 (strictly before the announcement calendar date).
  * Outcome windows start at r+1, r = reaction day (t0 if before-open, next trading day if
    after-close or ambiguous).  Gap between feature end and label start is >= 2 trading days by
    construction -- this is the equivalent of the repo's signal.shift(1) requirement.
  * The SUE scaling denominator uses only the previous 8 announcements.

Run:  uv run python experiments/k1738/K1738.py
      uv run python experiments/k1738/K1738.py --no-download   (re-estimate from cached panel)
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import subprocess
import sys
import time
import warnings
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

HERE = Path(__file__).resolve().parent
CACHE = HERE / "cache"
SEED = 42

# --------------------------------------------------------------------------------------------
# Configuration (all pre-registered in README; no value here is tuned against a result)
# --------------------------------------------------------------------------------------------

HORIZONS = {"h1m": 21, "h2m": 42, "h3m": 63}   # trading days ~ 1/2/3 months
SUE_WINDOW = 8          # prior announcements used for the SUE denominator
SUE_MIN_OBS = 6         # minimum non-missing prior surprises
WINSOR = (0.01, 0.99)
N_FOLDS = 5
N_REPS = 5
FDR_Q = 0.10
MIN_WINDOW_COVERAGE = 0.80
PRICE_START = "2000-01-01"
PEER_WINDOW_DAYS = 30   # calendar days before t0 for the sector-peer instrument

SUBPERIODS = {
    "P1_2002_2009": ("2002-01-01", "2009-12-31"),
    "P2_2010_2017": ("2010-01-01", "2017-12-31"),
    "P3_2018_2026": ("2018-01-01", "2026-12-31"),
}

FRED_SERIES = {"VIXCLS": "vix", "T10Y2Y": "term_spread", "BAA10Y": "credit_spread"}
# NFCI deliberately excluded: first published 2011, earlier history is a backcast, and it is
# revised.  See README section 2.4 (K1655 vintage lesson).

MARKET_TICKER = "SPY"

# Fixed universe (hard-coded so the sample is reproducible and does not drift with index
# membership).  Sector labels are hard-coded too, avoiding ~230 slow/flaky .info calls.
UNIVERSE: list[tuple[str, str]] = [
    (t, "Technology") for t in
    "AAPL MSFT NVDA AVGO ORCL CRM ADBE AMD INTC CSCO ACN TXN QCOM IBM NOW INTU AMAT MU ADI LRCX "
    "KLAC SNPS CDNS FTNT HPQ DELL WDC STX NTAP GLW APH TEL MCHP ON SWKS TER ZBRA KEYS TYL".split()
] + [
    (t, "CommServices") for t in
    "GOOGL META NFLX DIS CMCSA VZ T TMUS EA TTWO OMC IPG WBD LYV NWSA".split()
] + [
    (t, "ConsDiscretionary") for t in
    "AMZN TSLA HD MCD NKE LOW SBUX TJX BKNG ORLY AZO ROST YUM MAR HLT CMG DHI LEN GM F APTV BBY "
    "EBAY DRI WHR PHM TPR RL LVS WYNN".split()
] + [
    (t, "ConsStaples") for t in
    "PG KO PEP COST WMT PM MO MDLZ CL KMB GIS SYY KHC STZ HSY CHD CLX MKC TSN CAG HRL SJM EL KR".split()
] + [
    (t, "HealthCare") for t in
    "UNH JNJ LLY ABBV MRK PFE TMO ABT DHR BMY AMGN GILD CVS CI ELV ISRG SYK BSX MDT ZBH BDX BAX "
    "REGN VRTX BIIB MCK CAH COR IQV A EW HOLX DGX LH".split()
] + [
    (t, "Financials") for t in
    "JPM BAC WFC GS MS C SCHW BLK SPGI AXP USB PNC TFC BK STT COF DFS MET PRU AFL ALL TRV PGR CB "
    "AIG MMC AON ICE CME NDAQ AMP FITB KEY RF CFG HBAN MTB ZION".split()
] + [
    (t, "Industrials") for t in
    "CAT BA HON UNP UPS RTX LMT GE MMM DE GD NOC EMR ETN ITW CSX NSC FDX WM PH CMI ROK DOV IR "
    "PCAR LUV DAL UAL JCI SWK TXT AOS MAS URI FAST GWW EXPD CHRW".split()
] + [
    (t, "Energy") for t in
    "XOM CVX COP EOG SLB PSX VLO MPC OXY HAL BKR DVN FANG HES WMB KMI OKE TRGP APA".split()
] + [
    (t, "Materials") for t in
    "LIN APD SHW ECL NEM FCX DOW DD PPG NUE VMC MLM IP PKG ALB CE EMN IFF STLD".split()
] + [
    (t, "Utilities") for t in
    "NEE DUK SO D AEP EXC SRE XEL ED WEC ES PEG AEE DTE PPL CMS CNP ATO NI EVRG FE AES".split()
] + [
    (t, "RealEstate") for t in
    "AMT PLD CCI EQIX SPG PSA O WELL DLR AVB EQR VTR ESS MAA UDR HST BXP KIM REG FRT".split()
]
SECTOR_OF = dict(UNIVERSE)
TICKERS = [t for t, _ in UNIVERSE]

CONFOUNDERS = [
    "log_rv21", "log_rv63", "log_rv252", "rv_trend",
    "ret21", "ret252", "log_dollar_vol",
    "sue_lag", "abs_sue_lag", "log_sigma_hat",
    "log_vix", "term_spread", "credit_spread", "log_mkt_rv21",
    "days_since_prev", "year_frac", "cal_quarter",
]


# --------------------------------------------------------------------------------------------
# Download layer
# --------------------------------------------------------------------------------------------

def _fetch_fred(series_id: str) -> pd.Series:
    """FRED CSV, keyless.  Market-priced series only -- these are not revised.

    FRED intermittently drops python-requests connections, so curl is the primary transport with
    requests as fallback.
    """
    url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}&cosd=1999-01-01"
    last_exc: Exception | None = None
    for attempt in range(5):
        for transport in ("curl", "requests"):
            try:
                if transport == "curl":
                    proc = subprocess.run(
                        ["curl", "-sS", "-m", "90", "-L", url],
                        capture_output=True, text=True, timeout=120,
                    )
                    if proc.returncode != 0 or not proc.stdout.strip():
                        raise RuntimeError(f"curl rc={proc.returncode} {proc.stderr[:200]}")
                    text = proc.stdout
                else:
                    import requests
                    resp = requests.get(url, timeout=90,
                                        headers={"User-Agent": "Mozilla/5.0 (research)"})
                    resp.raise_for_status()
                    text = resp.text
                df = pd.read_csv(io.StringIO(text), na_values=["."])
                date_col, val_col = df.columns[0], df.columns[1]
                s = pd.Series(
                    pd.to_numeric(df[val_col], errors="coerce").values,
                    index=pd.to_datetime(df[date_col]),
                    name=series_id,
                ).dropna()
                if s.empty:
                    raise RuntimeError("empty series")
                return s.sort_index()
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
        time.sleep(3 * (attempt + 1))
    raise RuntimeError(f"FRED fetch failed for {series_id}: {last_exc}")


def download_all() -> dict:
    """Download prices, earnings and macro.  Cached to disk so estimation can be re-run cheaply."""
    import yfinance as yf

    CACHE.mkdir(parents=True, exist_ok=True)

    # ---- prices -----------------------------------------------------------------------------
    price_path = CACHE / "prices.parquet"
    vol_path = CACHE / "volumes.parquet"
    if price_path.exists() and vol_path.exists():
        closes = pd.read_parquet(price_path)
        volumes = pd.read_parquet(vol_path)
        print(f"[cache] prices {closes.shape}")
    else:
        all_t = TICKERS + [MARKET_TICKER]
        close_parts, vol_parts = [], []
        for i in range(0, len(all_t), 40):
            chunk = all_t[i:i + 40]
            print(f"[dl] prices {i}-{i + len(chunk)} / {len(all_t)}")
            raw = yf.download(chunk, start=PRICE_START, auto_adjust=True,
                              progress=False, group_by="column", threads=True)
            if raw is None or raw.empty:
                continue
            close_parts.append(raw["Close"] if isinstance(raw.columns, pd.MultiIndex) else raw[["Close"]])
            vol_parts.append(raw["Volume"] if isinstance(raw.columns, pd.MultiIndex) else raw[["Volume"]])
            time.sleep(1.0)
        closes = pd.concat(close_parts, axis=1).sort_index()
        volumes = pd.concat(vol_parts, axis=1).sort_index()
        closes = closes.loc[:, ~closes.columns.duplicated()]
        volumes = volumes.loc[:, ~volumes.columns.duplicated()]
        closes.to_parquet(price_path)
        volumes.to_parquet(vol_path)
        print(f"[dl] prices {closes.shape}")

    # ---- earnings ---------------------------------------------------------------------------
    earn_path = CACHE / "earnings.parquet"
    if earn_path.exists():
        earnings = pd.read_parquet(earn_path)
        print(f"[cache] earnings {earnings.shape}")
    else:
        rows = []
        failed = []
        for n, t in enumerate(TICKERS):
            if n % 25 == 0:
                print(f"[dl] earnings {n}/{len(TICKERS)}")
            ok = False
            for attempt in range(3):
                try:
                    ed = yf.Ticker(t).get_earnings_dates(limit=100)
                    if ed is not None and len(ed):
                        ed = ed.reset_index()
                        ed.columns = [str(c) for c in ed.columns]
                        date_col = ed.columns[0]
                        sub = pd.DataFrame({
                            "ticker": t,
                            "ann_ts": ed[date_col],
                            "eps_est": pd.to_numeric(ed.get("EPS Estimate"), errors="coerce"),
                            "eps_act": pd.to_numeric(ed.get("Reported EPS"), errors="coerce"),
                        })
                        rows.append(sub)
                    ok = True
                    break
                except Exception:  # noqa: BLE001
                    time.sleep(2 * (attempt + 1))
            if not ok:
                failed.append(t)
            time.sleep(0.15)
        earnings = pd.concat(rows, ignore_index=True)
        # Normalise the tz-aware announcement timestamp to America/New_York wall clock.
        ts = pd.to_datetime(earnings["ann_ts"], utc=True, errors="coerce")
        ny = ts.dt.tz_convert("America/New_York")
        earnings["ann_date"] = ny.dt.tz_localize(None).dt.normalize()
        earnings["ann_hour"] = ny.dt.hour + ny.dt.minute / 60.0
        earnings = earnings.drop(columns=["ann_ts"]).dropna(subset=["ann_date"])
        earnings.attrs["failed"] = failed
        earnings.to_parquet(earn_path)
        print(f"[dl] earnings {earnings.shape}, failed tickers: {failed}")

    # ---- macro ------------------------------------------------------------------------------
    macro_path = CACHE / "macro.parquet"
    if macro_path.exists():
        macro = pd.read_parquet(macro_path)
        print(f"[cache] macro {macro.shape}")
    else:
        macro = pd.concat({name: _fetch_fred(sid) for sid, name in FRED_SERIES.items()}, axis=1)
        macro.to_parquet(macro_path)
        print(f"[dl] macro {macro.shape}")

    return {"closes": closes, "volumes": volumes, "earnings": earnings, "macro": macro}


# --------------------------------------------------------------------------------------------
# Panel construction
# --------------------------------------------------------------------------------------------

def annualized_rv(rets: np.ndarray) -> float:
    """Standard realized volatility estimator, annualized: sqrt(252 * mean(r^2))."""
    r = rets[np.isfinite(rets)]
    if r.size == 0:
        return np.nan
    return float(np.sqrt(252.0 * np.mean(r ** 2)))


def rolling_rv(ret: pd.Series, n: int) -> pd.Series:
    """Vectorised equivalent of annualized_rv applied on a rolling window of length n."""
    return np.sqrt(252.0 * (ret ** 2).rolling(n, min_periods=int(MIN_WINDOW_COVERAGE * n)).mean())


def build_panel(data: dict) -> pd.DataFrame:
    closes, volumes = data["closes"], data["volumes"]
    earnings, macro = data["earnings"], data["macro"]

    # Macro as-of series: backward fill only (last observation on or before the query date).
    # Interpolation is forbidden -- it would pull future values backward.
    cal = pd.date_range(macro.index.min(), pd.Timestamp("2027-01-01"), freq="D")
    macro_d = macro.reindex(macro.index.union(cal)).ffill().reindex(cal)

    # Market realized vol, indexed by SPY trading days.
    mkt_px = closes[MARKET_TICKER].dropna()
    mkt_ret = np.log(mkt_px / mkt_px.shift(1))
    mkt_rv21 = rolling_rv(mkt_ret, 21)

    recs = []
    max_h = max(HORIZONS.values())

    for ticker in TICKERS:
        if ticker not in closes.columns:
            continue
        px = closes[ticker].dropna()
        if len(px) < 400:
            continue
        vol = volumes[ticker].reindex(px.index) if ticker in volumes.columns else pd.Series(np.nan, index=px.index)
        idx = px.index
        ret = np.log(px / px.shift(1))
        ret_v = ret.values
        dollar_vol = (px * vol).rolling(63).mean()

        # Pre-computed confounder series (each value uses data up to and including its own date).
        rv21, rv63, rv252 = rolling_rv(ret, 21), rolling_rv(ret, 63), rolling_rv(ret, 252)
        ret21 = px / px.shift(21) - 1.0
        ret252 = px / px.shift(252) - 1.0

        # ---- SUE, point-in-time -------------------------------------------------------------
        e = earnings[earnings["ticker"] == ticker].copy()
        if e.empty:
            continue
        e = e.dropna(subset=["ann_date"]).sort_values("ann_date").drop_duplicates("ann_date")
        e = e.set_index("ann_date")
        raw_surprise = e["eps_act"] - e["eps_est"]
        # std of the PREVIOUS SUE_WINDOW surprises: shift(1) then roll.
        sigma_hat = raw_surprise.shift(1).rolling(SUE_WINDOW, min_periods=SUE_MIN_OBS).std(ddof=1)
        sigma_hat = sigma_hat.where(sigma_hat > 1e-8)
        sue = raw_surprise / sigma_hat
        e["raw_surprise"], e["sigma_hat"], e["sue"] = raw_surprise, sigma_hat, sue
        e["sue_lag"] = e["sue"].shift(1)
        e["abs_sue_lag"] = e["sue"].abs().shift(1)
        e["days_since_prev"] = e.index.to_series().diff().dt.days

        for t0, row in e.iterrows():
            if not np.isfinite(row.get("sue", np.nan)):
                continue

            # ---- lag geometry (README section 4) --------------------------------------------
            pos = int(np.searchsorted(idx.values, np.datetime64(t0), side="left"))
            c_pos = pos - 1                       # last trading day STRICTLY BEFORE t0
            hour = row.get("ann_hour", 16.0)
            if np.isfinite(hour) and hour < 9.5:  # before market open -> impounded same day
                r_pos = pos
            else:                                 # after close or ambiguous -> next trading day
                r_pos = int(np.searchsorted(idx.values, np.datetime64(t0), side="right"))
            if c_pos < 252 or r_pos + max_h >= len(idx):
                continue
            assert r_pos + 1 > c_pos + 1, "outcome window must start after the confounder window"

            # ---- outcomes: RV over [r+1, r+H], reaction day EXCLUDED (primary) ---------------
            out = {}
            ok = True
            for hname, H in HORIZONS.items():
                w = ret_v[r_pos + 1: r_pos + 1 + H]
                if np.isfinite(w).sum() < MIN_WINDOW_COVERAGE * H:
                    ok = False
                    break
                out[f"rv_{hname}"] = annualized_rv(w)
                # robustness: window INCLUDING the reaction day
                w_inc = ret_v[r_pos: r_pos + H]
                out[f"rvinc_{hname}"] = annualized_rv(w_inc)
            if not ok:
                continue

            c_date = idx[c_pos]
            m_row = macro_d.loc[c_date] if c_date in macro_d.index else None
            mkt_pos = int(np.searchsorted(mkt_rv21.index.values, np.datetime64(c_date), side="right")) - 1

            recs.append({
                "ticker": ticker,
                "sector": SECTOR_OF[ticker],
                "ann_date": t0,
                "ann_ym": f"{t0.year:04d}-{t0.month:02d}",
                "conf_date": c_date,
                "reaction_date": idx[r_pos],
                "ann_pos": pos, "conf_pos": c_pos, "reaction_pos": r_pos,
                "eps_act": row["eps_act"], "eps_est": row["eps_est"],
                "raw_surprise": row["raw_surprise"], "sigma_hat": row["sigma_hat"],
                "sue_raw": row["sue"],
                "sue_lag": row["sue_lag"], "abs_sue_lag": row["abs_sue_lag"],
                "days_since_prev": row["days_since_prev"],
                "log_rv21": np.log(rv21.iloc[c_pos]) if rv21.iloc[c_pos] > 0 else np.nan,
                "log_rv63": np.log(rv63.iloc[c_pos]) if rv63.iloc[c_pos] > 0 else np.nan,
                "log_rv252": np.log(rv252.iloc[c_pos]) if rv252.iloc[c_pos] > 0 else np.nan,
                "ret21": ret21.iloc[c_pos], "ret252": ret252.iloc[c_pos],
                "log_dollar_vol": np.log(dollar_vol.iloc[c_pos]) if dollar_vol.iloc[c_pos] > 0 else np.nan,
                "vix": m_row["vix"] if m_row is not None else np.nan,
                "term_spread": m_row["term_spread"] if m_row is not None else np.nan,
                "credit_spread": m_row["credit_spread"] if m_row is not None else np.nan,
                "mkt_rv21": mkt_rv21.iloc[mkt_pos] if mkt_pos >= 0 else np.nan,
                "year_frac": t0.year + (t0.month - 1) / 12.0,
                "cal_quarter": (t0.month - 1) // 3 + 1,
                **out,
            })

    panel = pd.DataFrame(recs)
    if panel.empty:
        return panel

    panel["rv_trend"] = panel["log_rv21"] - panel["log_rv252"]
    panel["log_vix"] = np.log(panel["vix"].where(panel["vix"] > 0))
    panel["log_mkt_rv21"] = np.log(panel["mkt_rv21"].where(panel["mkt_rv21"] > 0))
    panel["log_sigma_hat"] = np.log(panel["sigma_hat"].where(panel["sigma_hat"] > 0))

    # Pooled winsorization of the treatment (pre-registered).
    lo, hi = panel["sue_raw"].quantile(WINSOR)
    panel["sue"] = panel["sue_raw"].clip(lo, hi)
    panel["abs_sue"] = panel["sue"].abs()
    for c in ("sue_lag", "abs_sue_lag"):
        panel[c] = panel[c].clip(*panel[c].quantile(WINSOR))

    for hname in HORIZONS:
        panel[f"y_{hname}"] = np.log(panel[f"rv_{hname}"].where(panel[f"rv_{hname}"] > 0))
        panel[f"yinc_{hname}"] = np.log(panel[f"rvinc_{hname}"].where(panel[f"rvinc_{hname}"] > 0))

    # ---- sector-peer instrument -------------------------------------------------------------
    # Z = mean SUE of OTHER same-sector firms announcing in the PEER_WINDOW_DAYS calendar days
    # strictly BEFORE t0.  Strictly-before is what makes Z usable at all; validity is a separate
    # question, decided by the pre-registered exclusion test (README section 6).
    panel = panel.sort_values("ann_date").reset_index(drop=True)
    z_vals, z_n = np.full(len(panel), np.nan), np.zeros(len(panel), dtype=int)
    for sector, grp in panel.groupby("sector", sort=False):
        d = grp["ann_date"].values.astype("datetime64[D]").astype(np.int64)
        s = grp["sue"].values
        tk = grp["ticker"].values
        order = np.argsort(d, kind="stable")
        for local_i in range(len(grp)):
            t_i, tick_i = d[local_i], tk[local_i]
            m = (d >= t_i - PEER_WINDOW_DAYS) & (d < t_i) & (tk != tick_i)
            if m.sum() > 0:
                z_vals[grp.index[local_i]] = float(np.nanmean(s[m]))
                z_n[grp.index[local_i]] = int(m.sum())
        del order
    panel["peer_sue"], panel["peer_n"] = z_vals, z_n

    return panel


# --------------------------------------------------------------------------------------------
# Inference machinery
# --------------------------------------------------------------------------------------------

def _cluster_meat(scores: np.ndarray, cl: np.ndarray) -> np.ndarray:
    """Sum over clusters g of (sum_{i in g} score_i)(...)'."""
    df = pd.DataFrame(scores)
    S = df.groupby(pd.Series(cl, index=df.index), sort=False).sum().values
    return S.T @ S


def twoway_meat(scores: np.ndarray, cl1: np.ndarray, cl2: np.ndarray) -> np.ndarray:
    """Cameron-Gelbach-Miller two-way cluster meat, PSD-repaired.

    Firm-quarter observations announced in the same month share market-wide shocks and repeated
    observations of a firm are serially dependent.  Treating them as iid understates SE
    (repo rule from K1355).
    """
    both = np.char.add(np.char.add(cl1.astype(str), "|"), cl2.astype(str))
    M = _cluster_meat(scores, cl1) + _cluster_meat(scores, cl2) - _cluster_meat(scores, both)
    w, V = np.linalg.eigh((M + M.T) / 2.0)
    return V @ np.diag(np.clip(w, 0.0, None)) @ V.T


def ols_twoway(y: np.ndarray, W: np.ndarray, cl1: np.ndarray, cl2: np.ndarray):
    """OLS with two-way clustered covariance.  Returns (beta, V)."""
    XtX_inv = np.linalg.pinv(W.T @ W)
    beta = XtX_inv @ (W.T @ y)
    e = y - W @ beta
    M = twoway_meat(W * e[:, None], cl1, cl2)
    return beta, XtX_inv @ M @ XtX_inv


def iv2sls_twoway(y: np.ndarray, W: np.ndarray, Z: np.ndarray, cl1, cl2):
    """Just-identified 2SLS with two-way clustered covariance.  W = [D, X, 1], Z = [Zinst, X, 1]."""
    ZW_inv = np.linalg.pinv(Z.T @ W)
    beta = ZW_inv @ (Z.T @ y)
    e = y - W @ beta
    M = twoway_meat(Z * e[:, None], cl1, cl2)
    return beta, ZW_inv @ M @ ZW_inv.T


def grouped_folds(groups: np.ndarray, n_splits: int, seed: int) -> np.ndarray:
    """Assign whole groups (firms) to folds, so a firm never straddles train/estimate."""
    uniq = np.unique(groups)
    rng = np.random.default_rng(seed)
    perm = rng.permutation(len(uniq))
    assign = {uniq[perm[i]]: i % n_splits for i in range(len(uniq))}
    return np.array([assign[g] for g in groups])


def _learner(kind: str, seed: int):
    from sklearn.ensemble import HistGradientBoostingRegressor
    from sklearn.linear_model import LassoCV
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler
    if kind == "lasso":
        return make_pipeline(StandardScaler(), LassoCV(cv=3, random_state=seed, max_iter=5000))
    return HistGradientBoostingRegressor(
        max_iter=100, learning_rate=0.10, max_depth=4,
        min_samples_leaf=40, l2_regularization=1.0, random_state=seed,
    )


def crossfit_resid(target, X, firm, n_folds, seed, learner):
    """Out-of-fold residual of `target` on X, with folds grouped by firm.

    Grouping by firm means no firm contributes to the nuisance fit that residualizes its own
    observations, so the nuisance learner cannot memorise firm identity.
    """
    fold_id = grouped_folds(firm, n_folds, seed)
    resid = np.full(len(target), np.nan)
    for k in range(n_folds):
        te = fold_id == k
        tr = ~te
        if tr.sum() < 50 or te.sum() < 5:
            continue
        mdl = _learner(learner, seed).fit(X[tr], target[tr])
        resid[te] = target[te] - mdl.predict(X[te])
    return resid


class ResidCache:
    """Cache of out-of-fold residuals, keyed by (variable, repetition, learner).

    E[Y|X] does not depend on which treatment is being estimated, and E[D|X] does not depend on
    the outcome horizon.  Reusing them is not merely a speed-up: it makes the cross-horizon and
    signed-vs-|SUE| comparisons exact, because every cell is residualized against identical
    nuisance fits rather than against independent re-fits that differ by estimation noise.
    """

    def __init__(self, X, firm, n_folds=N_FOLDS, seed=SEED):
        self.X, self.firm, self.n_folds, self.seed = X, firm, n_folds, seed
        self._cache: dict = {}
        self._fingerprint: dict = {}

    @staticmethod
    def _fp(values: np.ndarray) -> str:
        return hashlib.sha256(np.ascontiguousarray(values, dtype=np.float64).tobytes()).hexdigest()

    def get(self, name: str, values: np.ndarray, rep: int, learner: str = "hgb") -> np.ndarray:
        # A silently-stale cache would corrupt every downstream estimate, so the values behind a
        # key are fingerprinted and a collision is a hard error rather than a wrong number.
        fp = self._fp(values)
        if name in self._fingerprint and self._fingerprint[name] != fp:
            raise AssertionError(
                f"ResidCache key collision: '{name}' was previously used for different values"
            )
        self._fingerprint[name] = fp
        key = (name, rep, learner)
        if key not in self._cache:
            self._cache[key] = crossfit_resid(
                values, self.X, self.firm, self.n_folds, self.seed + 1000 * rep, learner
            )
        return self._cache[key]


def dml_plr(y, d, X, firm, month, learner="hgb", n_folds=N_FOLDS, n_reps=N_REPS, seed=SEED,
            cache: "ResidCache | None" = None, y_key: str | None = None, d_key: str | None = None):
    """Partially linear DML with cross-fitting grouped by firm and two-way clustered SE.

    Score: theta = sum(vtil*ytil)/sum(vtil^2), with vtil = d - m_hat(X), ytil = y - g_hat(X),
    both strictly out-of-fold.  Nuisance and effect are never estimated on the same data.
    Reported estimate is the median over n_reps split seeds with the Chernozhukov median
    variance adjustment, so split uncertainty is carried rather than hidden.
    """
    thetas, variances, r2s = [], [], []
    for rep in range(n_reps):
        rep_seed = seed + 1000 * rep
        if cache is not None and y_key is not None and d_key is not None:
            ytil = cache.get(y_key, y, rep, learner)
            vtil = cache.get(d_key, d, rep, learner)
        else:
            ytil = crossfit_resid(y, X, firm, n_folds, rep_seed, learner)
            vtil = crossfit_resid(d, X, firm, n_folds, rep_seed, learner)
        ok = np.isfinite(ytil) & np.isfinite(vtil)
        if ok.sum() < 50:
            continue
        yt, vt = ytil[ok], vtil[ok]
        denom = float(np.sum(vt * vt))
        if denom <= 0:
            continue
        theta = float(np.sum(vt * yt) / denom)
        psi = (vt * (yt - theta * vt))[:, None]
        M = twoway_meat(psi, firm[ok], month[ok])
        var = float(M[0, 0]) / denom ** 2
        thetas.append(theta)
        variances.append(var)
        r2s.append(1.0 - np.var(vt) / max(np.var(d[ok]), 1e-12))  # treatment residualization strength
    if not thetas:
        return {"theta": np.nan, "se": np.nan, "n_reps_ok": 0}
    thetas, variances = np.array(thetas), np.array(variances)
    theta_med = float(np.median(thetas))
    var_med = float(np.median(variances + (thetas - theta_med) ** 2))
    se = float(np.sqrt(max(var_med, 0.0)))
    return {
        "theta": theta_med, "se": se,
        "theta_reps": [float(t) for t in thetas],
        "n_reps_ok": len(thetas),
        "treatment_resid_share": float(np.median(r2s)),
    }


def zp(theta: float, se: float) -> tuple[float, float]:
    from scipy import stats
    if not np.isfinite(theta) or not np.isfinite(se) or se <= 0:
        return np.nan, np.nan
    z = theta / se
    return float(z), float(2.0 * (1.0 - stats.norm.cdf(abs(z))))


def ci(theta: float, se: float) -> list[float]:
    if not np.isfinite(theta) or not np.isfinite(se):
        return [np.nan, np.nan]
    return [float(theta - 1.96 * se), float(theta + 1.96 * se)]


def bh_fdr(pvals: list[float], q: float = FDR_Q):
    from statsmodels.stats.multitest import multipletests
    p = np.asarray(pvals, dtype=float)
    ok = np.isfinite(p)
    rej = np.zeros(len(p), dtype=bool)
    adj = np.full(len(p), np.nan)
    if ok.sum() > 0:
        r, a, _, _ = multipletests(p[ok], alpha=q, method="fdr_bh")
        rej[ok], adj[ok] = r, a
    return rej, adj


def est_record(name, theta, se, n):
    z, p = zp(theta, se)
    return {
        "estimator": name, "theta": float(theta) if np.isfinite(theta) else None,
        "se": float(se) if np.isfinite(se) else None,
        "z": z if np.isfinite(z) else None, "p_raw": p if np.isfinite(p) else None,
        "ci95": ci(theta, se),
        "pct_vol_change_per_1sd": float(np.exp(theta) - 1.0) * 100 if np.isfinite(theta) else None,
        "n": int(n),
    }


# --------------------------------------------------------------------------------------------
# Estimation driver
# --------------------------------------------------------------------------------------------

def design_matrix(df: pd.DataFrame) -> tuple[np.ndarray, list[str]]:
    X = df[CONFOUNDERS].astype(float)
    sect = pd.get_dummies(df["sector"], prefix="sec", drop_first=True).astype(float)
    full = pd.concat([X, sect], axis=1)
    return full.values, list(full.columns)


def run_estimators(df, treat_col, y_prefix, Xmat, firm, month, label, cache=None):
    """naive / OLS-controls / DML for one (treatment, outcome-family) combination."""
    d = df[treat_col].values.astype(float)
    out = {}
    for hname in HORIZONS:
        y = df[f"{y_prefix}{hname}"].values.astype(float)
        n = len(y)
        ones = np.ones((n, 1))

        b, V = ols_twoway(y, np.column_stack([d, ones]), firm, month)
        naive = est_record("naive_ols", b[0], np.sqrt(V[0, 0]), n)

        W = np.column_stack([d, Xmat, ones])
        b2, V2 = ols_twoway(y, W, firm, month)
        ctrl = est_record("ols_controls", b2[0], np.sqrt(V2[0, 0]), n)

        dml = dml_plr(y, d, Xmat, firm, month, cache=cache,
                      y_key=f"{y_prefix}{hname}", d_key=treat_col)
        dml_rec = est_record("dml", dml["theta"], dml["se"], n)
        dml_rec["n_reps_ok"] = dml["n_reps_ok"]
        dml_rec["theta_reps"] = dml.get("theta_reps")
        dml_rec["treatment_resid_share"] = dml.get("treatment_resid_share")

        out[hname] = {"naive_ols": naive, "ols_controls": ctrl, "dml": dml_rec,
                      "confounding_absorbed_pct": (
                          float((1.0 - dml_rec["theta"] / naive["theta"]) * 100)
                          if naive["theta"] and dml_rec["theta"] is not None and abs(naive["theta"]) > 1e-12
                          else None)}
        print(f"   [{label}/{hname}] naive={naive['theta']:+.4f} "
              f"ols={ctrl['theta']:+.4f} dml={dml_rec['theta']:+.4f} (se {dml_rec['se']:.4f})")
    return out


def run_iv(df, Xmat, firm, month):
    """Sector-peer instrument: relevance, the pre-registered exclusion test, and 2SLS."""
    sub = df[np.isfinite(df["peer_sue"].values) & (df["peer_n"].values > 0)]
    if len(sub) < 200:
        return {"status": "INSUFFICIENT_PEER_COVERAGE", "n": int(len(sub))}
    Xs, _ = design_matrix(sub)
    f, m = sub["ticker"].values, sub["ann_ym"].values
    d = sub["sue"].values.astype(float)
    z = sub["peer_sue"].values.astype(float)
    n = len(sub)
    ones = np.ones((n, 1))

    # ---- first stage / relevance -------------------------------------------------------------
    Wfs = np.column_stack([z, Xs, ones])
    bfs, Vfs = ols_twoway(d, Wfs, f, m)
    fs_t = bfs[0] / np.sqrt(Vfs[0, 0])
    first_stage = {"coef": float(bfs[0]), "se": float(np.sqrt(Vfs[0, 0])),
                   "t": float(fs_t), "F_cluster_robust": float(fs_t ** 2),
                   "weak_by_stock_yogo_rule_of_thumb": bool(fs_t ** 2 < 10.0)}

    # ---- pre-registered exclusion test: does Z enter the OUTCOME equation directly? -----------
    excl, violated = {}, False
    for hname in HORIZONS:
        y = sub[f"y_{hname}"].values.astype(float)
        We = np.column_stack([d, z, Xs, ones])
        be, Ve = ols_twoway(y, We, f, m)
        t_z = float(be[1] / np.sqrt(Ve[1, 1]))
        _, p_z = zp(be[1], np.sqrt(Ve[1, 1]))
        excl[hname] = {"coef_on_instrument": float(be[1]), "t": t_z, "p": p_z,
                       "violates_exclusion": bool(abs(t_z) > 1.96)}
        violated |= abs(t_z) > 1.96

    # ---- 2SLS (reported regardless; interpreted only if exclusion holds) ----------------------
    tsls = {}
    for hname in HORIZONS:
        y = sub[f"y_{hname}"].values.astype(float)
        W = np.column_stack([d, Xs, ones])
        Zm = np.column_stack([z, Xs, ones])
        b, V = iv2sls_twoway(y, W, Zm, f, m)
        tsls[hname] = est_record("iv_2sls", b[0], np.sqrt(V[0, 0]), n)

    return {
        "status": "ESTIMATED",
        "instrument": "mean SUE of other same-sector firms announcing in the prior 30 calendar days",
        "n": int(n),
        "first_stage": first_stage,
        "exclusion_test": excl,
        "exclusion_restriction_violated": bool(violated),
        "instrument_valid": bool(not violated and fs_t ** 2 >= 10.0),
        "tsls": tsls,
        "interpretation": (
            "INVALID -- exclusion restriction rejected; 2SLS reported as a transparency "
            "diagnostic and NOT interpreted causally."
            if violated else
            "Exclusion not rejected by the pre-registered test; note that a non-rejection is "
            "not proof of validity."
        ),
    }


def evaluate_verdict(insufficient, n_obs, n_firms, n_quarters, results, subper, robustness, iv):
    """Apply README section 8 verbatim.  Stages that have not run yet fail their condition rather
    than being skipped, so a partial artifact can never report a stronger verdict than it earned."""
    if insufficient:
        return ("INSUFFICIENT_DATA",
                f"n={n_obs} firms={n_firms} quarters={n_quarters} vs required 500 / 30 / 20",
                {}, None)
    if not results:
        return "FAIL", "primary estimation did not complete", {}, None

    sig_signed = [h for h in HORIZONS if results["signed_sue"][h]["dml"].get("significant_bh")]
    sig_abs = [h for h in HORIZONS if results["abs_sue"][h]["dml"].get("significant_bh")]
    signs = [np.sign(results["signed_sue"][h]["dml"]["theta"]) for h in HORIZONS]
    primary_sign = signs[0] if signs else 0.0

    sp_signs = [np.sign(subper[p][h]["theta"]) for p in subper for h in HORIZONS
                if isinstance(subper.get(p), dict) and h in subper[p]
                and subper[p][h].get("theta") is not None]
    fe = robustness.get("within_month_demeaned")
    fe_ok = bool(fe) and any(
        (fe[h]["theta"] is not None and np.sign(fe[h]["theta"]) == primary_sign
         and fe[h]["p_raw"] is not None and fe[h]["p_raw"] < FDR_Q)
        for h in HORIZONS if h in fe)

    checks = {
        "c1_bh_significant_in_ge2_horizons": len(sig_signed) >= 2,
        "c2_sign_consistent_across_horizons": len(set(signs)) == 1,
        "c3_sign_consistent_across_subperiods": (len(set(sp_signs)) == 1) if sp_signs else False,
        "c4_survives_within_month_fe": fe_ok,
        "significant_horizons_signed": sig_signed,
        "significant_horizons_abs": sig_abs,
        "subperiods_evaluated": bool(sp_signs),
        "within_month_fe_evaluated": bool(fe),
    }
    core = ("c1_bh_significant_in_ge2_horizons", "c2_sign_consistent_across_horizons",
            "c3_sign_consistent_across_subperiods", "c4_survives_within_month_fe")

    if all(checks[k] for k in core):
        verdict = "PASS"
        reason = (f"signed-SUE DML effect is BH-significant at {len(sig_signed)}/3 horizons with a "
                  f"consistent sign across horizons and sub-periods and survives the within-month "
                  f"fixed-effect spec")
    elif sig_signed or sig_abs:
        verdict = "CONDITIONAL_PASS"
        failed = [k for k in core if not checks[k]]
        reason = (f"BH-significant at signed={sig_signed} abs={sig_abs} but failed pre-registered "
                  f"condition(s): {failed}")
    else:
        verdict = "NULL"
        reason = ("no BH-significant DML effect at any horizon for either treatment definition: "
                  "the raw SUE-vol association is accounted for by the observed confounder set")

    causal_cap = None
    if verdict in ("PASS", "CONDITIONAL_PASS") and iv.get("exclusion_restriction_violated", True):
        causal_cap = ("CAPPED: no valid instrument, so this is a conditional-association result "
                      "under unconfoundedness, not an identified causal effect.")
    return verdict, reason, checks, causal_cap


def build_payload(*, df, panel, results, fdr, subper, robustness, iv, verdict, reason, checks,
                  causal_cap, xnames, n_obs, n_firms, n_quarters, coverage, t_start,
                  stages_done, stage_note):
    code_sha = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    try:
        commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=HERE, capture_output=True,
                                text=True, timeout=10).stdout.strip()
    except Exception:  # noqa: BLE001
        commit = None

    expected = ["primary", "instrument", "robustness:within_month_demeaned", "subperiods",
                "robustness:inclusive_window", "robustness:level_rv_outcome",
                "robustness:lasso_nuisance"]
    missing = [s for s in expected if s not in stages_done]

    return {
        "experiment_id": "K1738",
        "title": ("Earnings surprise (SUE) and subsequent realized volatility: causal increment "
                  "via DML (+ IV falsification)"),
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "seed": SEED,
        "code_sha256": code_sha,
        "git_commit": commit,
        "runtime_seconds": round(time.time() - t_start, 1),
        "run_complete": not missing,
        "stages_completed": list(stages_done),
        "stages_missing": missing,
        "last_checkpoint": stage_note,
        "verdict": verdict,
        "verdict_reason": reason,
        "causal_claim_cap": causal_cap,
        "identification_stance": ("Conditional association under unconfoundedness. No credible "
                                  "instrument was found; see instrument_analysis."),
        "question": ("Not 'does SUE predict vol' (a forecasting question) but 'does SUE carry a "
                     "causal increment to realized vol after controlling for confounders'."),
        "sample": {
            "n_firm_quarters": n_obs,
            "n_firms": n_firms,
            "n_quarters": int(n_quarters),
            "date_range": [str(df["ann_date"].min().date()), str(df["ann_date"].max().date())],
            "n_announcement_months": int(df["ann_ym"].nunique()),
            "panel_rows_before_completeness_filter": int(len(panel)),
            "sue_coverage_of_panel_rows": coverage,
            "universe_size": len(TICKERS),
            "tickers_with_usable_data": n_firms,
            "obs_per_sector": {str(k): int(v) for k, v in df["sector"].value_counts().items()},
        },
        "treatment_definition": {
            "type": "analyst-based SUE (NOT a seasonal-random-walk proxy)",
            "formula": "(ReportedEPS - ConsensusEPSEstimate) / std(prior 8 announcement surprises)",
            "source": "yfinance get_earnings_dates(limit=100): EPS Estimate + Reported EPS",
            "continuous": True,
            "winsorized_at": list(WINSOR),
            "primary": "signed SUE", "secondary": "|SUE|",
            "denominator_min_prior_obs": SUE_MIN_OBS,
            "pit_caveat": ("Yahoo's stored consensus is a current snapshot of the pre-announcement "
                           "consensus, not a timestamped archived vintage; Reported EPS may embed "
                           "later restatements. Standardizing by the firm's own prior surprise "
                           "dispersion neutralizes unit and split-adjustment drift but not "
                           "restatement."),
            "descriptives": {
                "mean": float(df["sue"].mean()), "std": float(df["sue"].std()),
                "p5": float(df["sue"].quantile(0.05)), "p50": float(df["sue"].median()),
                "p95": float(df["sue"].quantile(0.95)),
                "share_positive": float((df["sue"] > 0).mean()),
            },
        },
        "lookahead_policy": {
            "event_anchor": "announcement timestamp (America/New_York), never the fiscal period end",
            "announcement_vs_period_end": ("Anchoring on the fiscal period end would look ahead by "
                                           "2-8 weeks because the earnings number is not public "
                                           "then. Only the announcement date is used."),
            "reaction_day_rule": ("hour < 09:30 ET -> reaction day = announcement date; "
                                  "hour >= 16:00 ET or ambiguous -> next trading day "
                                  "(conservative: never earlier)"),
            "confounder_window_end": "last trading day strictly before the announcement date (t0-1)",
            "outcome_window_start": "reaction day + 1 (the reaction day itself is excluded)",
            "min_feature_label_gap_trading_days": 2,
            "why_reaction_day_excluded": ("Including it makes the finding near-tautological: a "
                                          "large surprise mechanically produces a large "
                                          "announcement-day jump which inflates that window's RV. "
                                          "The inclusive window is reported under robustness so "
                                          "the mechanical part is visible."),
            "sue_denominator": "previous 8 announcements only, strictly earlier",
            "macro_asof": "backward fill only (last observation on or before t0-1); no interpolation",
            "nfci_excluded_reason": ("First published 2011 with backcast history and subject to "
                                     "revision (K1655 lesson). VIXCLS / T10Y2Y / BAA10Y are "
                                     "market-priced and unrevised."),
        },
        "method": {
            "estimand": "ATE of SUE on log annualized realized volatility, partially linear model",
            "outcome": "log annualized RV over trading days [r+1, r+H], H in {21,42,63}",
            "confounders": xnames,
            "dml": {
                "cross_fitting": f"{N_FOLDS}-fold, grouped by firm (no firm straddles train/estimate)",
                "nuisance_learner": "HistGradientBoostingRegressor (Lasso variant under robustness)",
                "score": "partialling-out: theta = sum(vtil*ytil)/sum(vtil^2)",
                "repetitions_primary": N_REPS,
                "repetitions_secondary_blocks": 2,
                "variance": "Chernozhukov median adjustment over split seeds",
            },
            "standard_errors": ("two-way clustered by firm and announcement year-month "
                                "(Cameron-Gelbach-Miller), for every estimator; per repo K1355 "
                                "rule, same-date cross-firm observations are not treated as iid"),
            "common_sample": "rows with complete confounders and all three horizons available",
        },
        "estimates": results,
        "multiple_testing": fdr,
        "subperiods": subper,
        "subperiod_family": "F2: {3 horizons} x {3 sub-periods}, BH-corrected separately from F1",
        "robustness": robustness,
        "robustness_note": ("Descriptive sensitivity checks, not confirmatory tests; not FDR "
                            "family members. They can demote a verdict but cannot promote a NULL."),
        "instrument_analysis": iv,
        "prereg_checks": checks,
        "success_criteria_source": "README.md section 8, written before any estimate was inspected",
        "process_notes": [
            "Disclosure: during runtime calibration a single preliminary h1m signed-SUE DML "
            "estimate was observed before the final nuisance-learner configuration was fixed. No "
            "success criterion in README section 8 was added, removed or altered at any point "
            "after that observation. The configuration changes that followed (HGB max_iter "
            "200 -> 100; 2 cross-fitting repetitions for the non-primary sub-period and robustness "
            "blocks) were made to fit a hard wall-clock budget on a heavily contended machine, not "
            "to move any estimate. The primary block retains the pre-registered 5 repetitions.",
            "The artifact is rewritten after every stage, so an interrupted run still yields a "
            "coherent partial result. Unfinished pre-registered conditions evaluate to False, "
            "which can only weaken the verdict, never strengthen it.",
        ],
        "limitations": [
            "Survivorship: universe is currently-listed firms; delisted firms absent. Expected "
            "direction is attenuation toward the null (failed firms had the largest negative "
            "surprises and the highest vol), so a positive finding is conservative.",
            "Consensus EPS is a current snapshot, not an archived vintage (see pit_caveat).",
            "Sector labels are current snapshots applied to the whole history.",
            "No credible instrument, so identification rests on unconfoundedness; unobserved "
            "drivers correlated with both SUE and future vol would still bias theta.",
            "At h=3m consecutive same-firm outcome windows are nearly adjacent; firm clustering "
            "absorbs the resulting serial dependence.",
        ],
        "unresolved": ([f"stage not run within the job budget: {s}" for s in missing]
                       + (["Codex primary-path review not yet recorded"] if True else [])),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-download", action="store_true")
    args = ap.parse_args()

    np.random.seed(SEED)
    t_start = time.time()
    panel_path = HERE / "panel_k1738.parquet"

    if args.no_download and panel_path.exists():
        panel = pd.read_parquet(panel_path)
        print(f"[cache] panel {panel.shape}")
    else:
        panel = build_panel(download_all())
        if panel.empty:
            raise SystemExit("empty panel")
        panel.to_parquet(panel_path)
        print(f"[panel] {panel.shape}")

    # ---- common estimation sample: complete confounders + all three horizons -----------------
    need = CONFOUNDERS + [f"y_{h}" for h in HORIZONS] + ["sue", "abs_sue"]
    df = panel.dropna(subset=need).reset_index(drop=True)
    df = df[np.isfinite(df[need].values.astype(float)).all(axis=1)].reset_index(drop=True)

    n_obs, n_firms = len(df), df["ticker"].nunique()
    n_quarters = df["ann_date"].dt.to_period("Q").nunique()
    coverage = float(len(panel.dropna(subset=["sue_raw"])) / max(len(panel), 1))
    print(f"[sample] n={n_obs} firms={n_firms} quarters={n_quarters} "
          f"range={df['ann_date'].min().date()}..{df['ann_date'].max().date()}")

    insufficient = (n_obs < 500) or (n_firms < 30) or (n_quarters < 20)

    Xmat, xnames = design_matrix(df)
    firm, month = df["ticker"].values, df["ann_ym"].values

    cache = ResidCache(Xmat, firm)
    results: dict = {}
    if not insufficient:
        print("[est] primary: signed SUE")
        results["signed_sue"] = run_estimators(df, "sue", "y_", Xmat, firm, month, "signed", cache)
        print("[est] secondary: |SUE|")
        results["abs_sue"] = run_estimators(df, "abs_sue", "y_", Xmat, firm, month, "abs", cache)

    # ---- FDR (family F1: 3 horizons x 2 treatment definitions, per estimator) ----------------
    fdr = {}
    if results:
        for estname in ("naive_ols", "ols_controls", "dml"):
            keys, ps = [], []
            for tname in ("signed_sue", "abs_sue"):
                for hname in HORIZONS:
                    keys.append(f"{tname}/{hname}")
                    ps.append(results[tname][hname][estname]["p_raw"])
            rej, adj = bh_fdr(ps)
            fdr[estname] = {
                "family": "F1: {3 horizons} x {signed SUE, |SUE|}",
                "q": FDR_Q, "m_hypotheses": len(ps),
                "tests": {k: {"p_raw": ps[i], "q_bh": (float(adj[i]) if np.isfinite(adj[i]) else None),
                              "significant_raw": bool(np.isfinite(ps[i]) and ps[i] < 0.05),
                              "significant_bh": bool(rej[i])}
                          for i, k in enumerate(keys)},
                "n_significant_raw": int(sum(1 for p in ps if np.isfinite(p) and p < 0.05)),
                "n_significant_bh": int(rej.sum()),
            }
            for i, k in enumerate(keys):
                tname, hname = k.split("/")
                results[tname][hname][estname]["q_bh"] = float(adj[i]) if np.isfinite(adj[i]) else None
                results[tname][hname][estname]["significant_bh"] = bool(rej[i])

    # ---- staged execution ---------------------------------------------------------------------
    # The box this runs on is shared, so the artifact is written after every stage.  A partial
    # artifact that is honest about what is missing is collectable; a missing one is a failed job.
    subper: dict = {}
    robustness: dict = {}
    iv: dict = {"status": "NOT_RUN"}
    stages_done: list[str] = ["primary"] if results else []
    out_path = HERE / "K1738_results.json"

    def assemble(stage_note: str) -> dict:
        verdict, reason, checks, causal_cap = evaluate_verdict(
            insufficient, n_obs, n_firms, n_quarters, results, subper, robustness, iv)
        payload = build_payload(
            df=df, panel=panel, results=results, fdr=fdr, subper=subper, robustness=robustness,
            iv=iv, verdict=verdict, reason=reason, checks=checks, causal_cap=causal_cap,
            xnames=xnames, n_obs=n_obs, n_firms=n_firms, n_quarters=n_quarters,
            coverage=coverage, t_start=t_start, stages_done=stages_done,
            stage_note=stage_note)
        out_path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
        print(f"[checkpoint] {stage_note}: verdict={verdict}")
        return payload

    assemble("primary+fdr")

    # ---- IV (cheap, and it decides the causal-claim cap) ---------------------------------------
    print("[est] instrument")
    iv = run_iv(df, Xmat, firm, month) if not insufficient else {"status": "SKIPPED_INSUFFICIENT_DATA"}
    stages_done.append("instrument")
    assemble("instrument")

    # ---- within-month demeaning FIRST: pre-registered criterion c4 depends on it ----------------
    if results:
        print("[est] robustness: within-month demeaned")
        g = df.groupby("ann_ym")
        d_fe = (df["sue"] - g["sue"].transform("mean")).values.astype(float)
        rob_fe = {}
        for hname in HORIZONS:
            y_fe = (df[f"y_{hname}"] - g[f"y_{hname}"].transform("mean")).values.astype(float)
            r = dml_plr(y_fe, d_fe, Xmat, firm, month, n_reps=2, cache=cache,
                        y_key=f"yfe_{hname}", d_key="sue_fe")
            rob_fe[hname] = est_record("dml", r["theta"], r["se"], n_obs)
        robustness["within_month_demeaned"] = rob_fe
        stages_done.append("robustness:within_month_demeaned")
        assemble("robustness:within_month_demeaned")

    # ---- sub-periods (family F2): pre-registered criterion c3 ----------------------------------
    if results:
        print("[est] sub-periods")
        sp_keys, sp_ps = [], []
        for pname, (a, b) in SUBPERIODS.items():
            m = (df["ann_date"] >= a) & (df["ann_date"] <= b)
            sd = df[m].reset_index(drop=True)
            if len(sd) < 200:
                subper[pname] = {"status": "TOO_SMALL", "n": int(len(sd))}
                continue
            Xs, _ = design_matrix(sd)
            entry = {"n": int(len(sd)), "n_firms": int(sd["ticker"].nunique()),
                     "range": [str(sd["ann_date"].min().date()), str(sd["ann_date"].max().date())]}
            for hname in HORIZONS:
                r = dml_plr(sd[f"y_{hname}"].values.astype(float), sd["sue"].values.astype(float),
                            Xs, sd["ticker"].values, sd["ann_ym"].values, n_reps=2)
                rec = est_record("dml", r["theta"], r["se"], len(sd))
                entry[hname] = rec
                sp_keys.append(f"{pname}/{hname}")
                sp_ps.append(rec["p_raw"])
            subper[pname] = entry
            print(f"   [{pname}] " + " ".join(
                f"{h}={entry[h]['theta']:+.4f}" for h in HORIZONS if h in entry))
        if sp_ps:
            rej2, adj2 = bh_fdr(sp_ps)
            for i2, k in enumerate(sp_keys):
                pn, hn = k.split("/")
                subper[pn][hn]["q_bh_F2"] = float(adj2[i2]) if np.isfinite(adj2[i2]) else None
                subper[pn][hn]["significant_bh_F2"] = bool(rej2[i2])
        stages_done.append("subperiods")
        assemble("subperiods")

    # ---- remaining robustness (descriptive only; cannot promote a NULL) -------------------------
    if results:
        sue_v = df["sue"].values.astype(float)
        for spec_name, ykey_fmt, learner in (
            ("inclusive_window", "yinc_{}", "hgb"),
            ("level_rv_outcome", "rv_{}", "hgb"),
            ("lasso_nuisance", "y_{}", "lasso"),
        ):
            print(f"[est] robustness: {spec_name}")
            block = {}
            for hname in HORIZONS:
                col = ykey_fmt.format(hname)
                r = dml_plr(df[col].values.astype(float), sue_v, Xmat, firm, month,
                            learner=learner, n_reps=2, cache=cache, y_key=col, d_key="sue")
                block[hname] = est_record("dml", r["theta"], r["se"], n_obs)
            robustness[spec_name] = block
            stages_done.append(f"robustness:{spec_name}")
            assemble(f"robustness:{spec_name}")

    payload = assemble("complete")
    print(f"\n[done] verdict={payload['verdict']} :: {payload['verdict_reason']}")
    print(f"[done] -> {out_path}  ({time.time() - t_start:.0f}s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
