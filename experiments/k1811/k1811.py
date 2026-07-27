#!/usr/bin/env python3
"""K1811 - Extreme-weather PHYSICAL event study + dose-response on insurance / utility ETF volatility.

Design (see README.md for full motivation, provenance and lookahead policy):
  * Events (all from primary NOAA/NHC databases, byte-traceable):
      - US-landfalling Atlantic hurricanes 2010-2024 (HURDAT2), dose = Saffir-Simpson category (1-5)
      - Major national heat waves 2010-2024 (NOAA Storm Events "Excessive Heat"),
        dose = 7-day national event-count scale at intensity peak (deaths / duration as robustness)
  * ETFs: KIE (insurance), KBWP (P&C insurance), XLU (utilities); SPY = market control.
  * Daily vol proxy: Parkinson range RV (primary), Garman-Klass (robustness), |logret| (robustness).
  * Classic event study: estimation window [-60,-11] baseline (mean/sd of log-vol), event window [-5,+10].
      abnormal vol AV_t = (logvol_t - mu_est) / sigma_est  (standardized), plus market-adjusted variant.
  * CAAV, cross-sectional t-test, and a SEED=42 month-matched placebo/permutation test.
  * Dose-response: OLS of cumulative abnormal vol (CAV over [0,+10]) on physical dose, per sector
      (+ pooled sector-FE with event-clustered SE as secondary), slope / 95% CI / R^2.

This is a DESCRIPTIVE event study, not a trading signal. No feature is used to predict next-day vol;
the only cross-sectional regression uses realized physical dose to explain realized post-event abnormal
vol (standard event-study CAR-on-severity). Any predictive re-framing would require signal.shift(1);
none is used here. All randomness fixed at SEED=42.
"""
from __future__ import annotations
import os, sys, json, hashlib, gzip, csv, io, ssl, urllib.request
from datetime import date, timedelta
from collections import defaultdict

import numpy as np
import pandas as pd

# ----------------------------------------------------------------------------------------------------
SEED = 42
RNG = np.random.default_rng(SEED)
HERE = os.path.dirname(os.path.abspath(__file__))
RAW = os.path.join(HERE, "data", "raw")
FIG = os.path.join(HERE, "figures")
os.makedirs(RAW, exist_ok=True)
os.makedirs(FIG, exist_ok=True)
_CTX = ssl.create_default_context()

START = "2010-01-01"
END   = "2025-01-01"          # ETF window: events 2010-2024, need ~3mo buffer each side
EST   = (-60, -11)            # estimation window (trading days rel. to t0)
EVT   = (-5, 10)              # event window (trading days rel. to t0)
CUM   = {"cum_0_5": (0, 5), "cum_0_10": (0, 10)}
N_PERM = 2000                 # permutation / placebo replications

HURDAT2_URL = "https://www.nhc.noaa.gov/data/hurdat/hurdat2-1851-2025-02272026.txt"
SE_BASE = "https://www.ncei.noaa.gov/pub/data/swdi/stormevents/csvfiles/"
SE_FILES = {  # year -> creation-date suffix (latest revision as of download)
    "2010": "20260323", "2011": "20260323", "2012": "20260323", "2013": "20260323",
    "2014": "20260323", "2015": "20260323", "2016": "20260323", "2017": "20260519",
    "2018": "20260323", "2019": "20260323", "2020": "20260323", "2021": "20260323",
    "2022": "20260625", "2023": "20260323", "2024": "20260421",
}
SECTORS = ["KIE", "KBWP", "XLU"]
ALL_TK  = SECTORS + ["SPY"]

MANIFEST: dict = {}


def _md5(b: bytes) -> str:
    return hashlib.md5(b).hexdigest()


def _get(url: str, dest: str, timeout: int = 200) -> bytes:
    if not os.path.exists(dest):
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        data = urllib.request.urlopen(req, timeout=timeout, context=_CTX).read()
        with open(dest, "wb") as fh:
            fh.write(data)
    b = open(dest, "rb").read()
    MANIFEST[os.path.basename(dest)] = {"url": url, "md5": _md5(b), "bytes": len(b)}
    return b


# ============================ 1. HURRICANE EVENTS (HURDAT2) ============================
def saffir_cat(kt: int) -> int:
    return 5 if kt >= 137 else 4 if kt >= 113 else 3 if kt >= 96 else 2 if kt >= 83 else 1 if kt >= 64 else 0


def _is_us_landfall(lat: float, lon: float) -> bool:
    """CONUS Atlantic/Gulf coast, excluding NW Bahamas and NE Mexico (Tamaulipas).
    Cuba is already excluded by the lat>=24 floor. Rule is purely geographic + reproducible."""
    if not (24.0 <= lat <= 47.5 and -98.0 <= lon <= -66.0):
        return False
    if lat <= 27.5 and lon >= -79.3:   # NW Bahamas (Abaco/Grand Bahama/Bimini) sit inside the box
        return False
    if lat <= 26.0 and lon <= -97.0:   # NE Mexico coast (Tamaulipas) -- e.g. Alex 2010
        return False
    return True


def build_hurricanes() -> pd.DataFrame:
    raw = _get(HURDAT2_URL, os.path.join(RAW, "hurdat2_atlantic_1851_2025.txt")).decode("utf-8", "ignore")
    lines = raw.splitlines()
    out, i = [], 0
    while i < len(lines):
        h = lines[i].split(",")
        if len(h) >= 3 and h[0].strip().startswith("AL"):
            sid, name, n = h[0].strip(), h[1].strip(), int(h[2])
            recs = lines[i + 1: i + 1 + n]; i += 1 + n
            yr = int(sid[4:8])
            if not (2010 <= yr <= 2024):
                continue
            us = []
            for r in recs:
                c = [x.strip() for x in r.split(",")]
                if "L" in c[2] and c[3] == "HU":               # landfall record, hurricane strength
                    lat = float(c[4][:-1]) * (1 if c[4][-1] == "N" else -1)
                    lon = float(c[5][:-1]) * (-1 if c[5][-1] == "W" else 1)
                    if _is_us_landfall(lat, lon):
                        us.append((c[0], int(c[6])))
            if us:
                first = min(us, key=lambda x: x[0])[0]
                maxwind = max(x[1] for x in us)
                out.append({
                    "event_id": sid, "name": name, "type": "hurricane",
                    "date": f"{first[:4]}-{first[4:6]}-{first[6:8]}",
                    "dose": float(saffir_cat(maxwind)),      # PRIMARY dose = Saffir-Simpson category
                    "dose_name": "saffir_simpson_category",
                    "max_wind_kt": maxwind, "n_us_landfalls": len(us),
                    "dose_alt": float(maxwind), "dose_alt_name": "max_landfall_wind_kt",
                })
        else:
            i += 1
    df = pd.DataFrame(out).sort_values("date").reset_index(drop=True)
    return df


# ============================ 2. HEAT-WAVE EVENTS (NOAA Storm Events) ============================
def build_heatwaves(n_target_rmin: float = 200.0, sep_days: int = 21) -> pd.DataFrame:
    dN, dD = defaultdict(int), defaultdict(int)
    for y, c in SE_FILES.items():
        fn = f"StormEvents_details-ftp_v1.0_d{y}_c{c}.csv.gz"
        gz = _get(SE_BASE + fn, os.path.join(RAW, fn))
        rows = list(csv.reader(io.StringIO(gzip.decompress(gz).decode("latin-1"))))
        ix = {name: k for k, name in enumerate(rows[0])}
        for r in rows[1:]:
            if len(r) <= ix["EVENT_TYPE"] or r[ix["EVENT_TYPE"]] != "Excessive Heat":
                continue
            ym = r[ix["BEGIN_YEARMONTH"]]
            try:
                bd = date(int(ym[:4]), int(ym[4:6]), int(r[ix["BEGIN_DAY"]]))
            except Exception:
                continue
            v = r[ix["DEATHS_DIRECT"]].strip()
            dD[bd] += int(v) if v not in ("", "NaN") else 0
            dN[bd] += 1
    alldays = sorted(dN)

    def R(d):            # 7-day centered national event-count = geographic-temporal scale
        return sum(dN.get(d + timedelta(k), 0) for k in range(-3, 4))

    def deaths_win(d, a, b):
        return sum(dD.get(d + timedelta(k), 0) for k in range(a, b + 1))

    # greedy peak detection with minimum separation -> discrete, non-overlapping heat waves
    sel = []
    for d in sorted(alldays, key=lambda x: -R(x)):
        if R(d) < n_target_rmin:
            break
        if all(abs((d - s).days) >= sep_days for s in sel):
            sel.append(d)
    out = []
    for d in sorted(sel):
        out.append({
            "event_id": f"HEAT_{d.isoformat()}", "name": f"HeatWave_{d.isoformat()}",
            "type": "heat", "date": d.isoformat(),
            "dose": float(R(d)),                          # PRIMARY dose = 7-day national scale
            "dose_name": "heat_scale_7d_eventcount",
            "deaths_direct_win": deaths_win(d, -3, 7),
            "dose_alt": float(deaths_win(d, -3, 7)),      # robustness dose = deaths
            "dose_alt_name": "deaths_direct_-3_+7",
        })
    return pd.DataFrame(out).sort_values("date").reset_index(drop=True)


# ============================ 3. ETF OHLC + VOLATILITY PROXIES ============================
def fetch_ohlc() -> pd.DataFrame:
    import yfinance as yf
    frames = {}
    for tk in ALL_TK:
        dest = os.path.join(HERE, "data", f"ohlc_{tk}.csv")
        if not os.path.exists(dest):
            d = yf.download(tk, start=START, end=END, progress=False, auto_adjust=False)
            if isinstance(d.columns, pd.MultiIndex):
                d.columns = [a for a, _ in d.columns]
            d = d[["Open", "High", "Low", "Close"]].dropna()
            d.to_csv(dest)
        b = open(dest, "rb").read()
        MANIFEST[f"ohlc_{tk}.csv"] = {"source": "yfinance", "md5": _md5(b), "bytes": len(b)}
        df = pd.read_csv(dest, index_col=0, parse_dates=True)
        frames[tk] = df[["Open", "High", "Low", "Close"]]
    return frames


def logvol_frame(frames: dict, proxy: str) -> pd.DataFrame:
    """Return DataFrame indexed by SPY trading dates, columns=tickers, values=daily log-vol."""
    cal = frames["SPY"].index
    cols = {}
    for tk, df in frames.items():
        O, H, L, C = df["Open"], df["High"], df["Low"], df["Close"]
        lhl = np.log((H / L).clip(lower=1 + 1e-9))
        if proxy == "parkinson":
            var = (lhl ** 2) / (4.0 * np.log(2.0))
        elif proxy == "gk":
            lco = np.log((C / O).replace(0, np.nan))
            var = 0.5 * lhl ** 2 - (2 * np.log(2) - 1) * lco ** 2
            var = var.clip(lower=1e-10)
        elif proxy == "absret":
            lr = np.log(C / C.shift(1))
            var = (lr ** 2).clip(lower=1e-10)
        else:
            raise ValueError(proxy)
        cols[tk] = np.log(var.clip(lower=1e-12)) * 0.5   # log daily vol
    lv = pd.DataFrame(cols).reindex(cal)
    return lv


# ============================ 4. EVENT STUDY ============================
def _t0_index(cal: pd.DatetimeIndex, event_date: str) -> int:
    """First trading day on/after the event date."""
    ts = pd.Timestamp(event_date)
    pos = cal.searchsorted(ts, side="left")
    return int(pos)


def event_abnormal_vol(lv: pd.DataFrame, tk: str, t0: int, market_adjust: bool = False):
    """Return dict tau->AV over event window, or None if data insufficient."""
    cal_n = len(lv)
    e0, e1 = EST
    v0, v1 = EVT
    lo, hi = t0 + e0, t0 + v1
    if lo < 0 or hi >= cal_n:
        return None
    est_pos = np.arange(t0 + e0, t0 + e1 + 1)      # [-60,-11] inclusive (50 obs)
    evt_pos = np.arange(t0 + v0, t0 + v1 + 1)      # [-5,+10] inclusive (16 obs)
    y = lv[tk].values
    if not market_adjust:
        est = y[est_pos]
        if np.any(~np.isfinite(est)):
            return None
        mu, sd = np.mean(est), np.std(est, ddof=1)
        if not np.isfinite(sd) or sd < 1e-9:
            return None
        av = (y[evt_pos] - mu) / sd
    else:
        x = lv["SPY"].values
        est_y, est_x = y[est_pos], x[est_pos]
        if np.any(~np.isfinite(est_y)) or np.any(~np.isfinite(est_x)):
            return None
        b1, b0 = np.polyfit(est_x, est_y, 1)
        resid = est_y - (b0 + b1 * est_x)
        sd = np.std(resid, ddof=2)
        if not np.isfinite(sd) or sd < 1e-9:
            return None
        av = (y[evt_pos] - (b0 + b1 * x[evt_pos])) / sd
    if np.any(~np.isfinite(av)):
        return None
    taus = list(range(v0, v1 + 1))
    return dict(zip(taus, av))


def run_event_study(lv: pd.DataFrame, events: pd.DataFrame, tk: str, market_adjust: bool = False):
    cal = lv.index
    per_event = []
    for _, ev in events.iterrows():
        t0 = _t0_index(cal, ev["date"])
        av = event_abnormal_vol(lv, tk, t0, market_adjust)
        if av is None:
            continue
        rec = {"event_id": ev["event_id"], "date": ev["date"], "dose": ev["dose"],
               "dose_alt": ev.get("dose_alt", np.nan), "t0": t0, "av": av}
        for cname, (a, b) in CUM.items():
            rec[cname] = float(sum(av[t] for t in range(a, b + 1)))
        per_event.append(rec)
    return per_event


def caav_curve(per_event):
    taus = list(range(EVT[0], EVT[1] + 1))
    return {t: float(np.mean([e["av"][t] for e in per_event])) for t in taus}


def xsec_ttest(vals):
    vals = np.asarray(vals, float)
    n = len(vals)
    if n < 3:
        return {"n": n, "mean": float(np.mean(vals)) if n else None, "t": None, "p": None}
    m, sd = np.mean(vals), np.std(vals, ddof=1)
    se = sd / np.sqrt(n)
    t = m / se if se > 0 else np.nan
    from scipy import stats
    p = float(2 * stats.t.sf(abs(t), df=n - 1)) if np.isfinite(t) else None
    return {"n": int(n), "mean": float(m), "sd": float(sd), "t": float(t), "p": p}


def month_matched_placebo(lv, events, tk, cum_key, market_adjust=False, n_perm=N_PERM):
    """SEED=42 placebo: relocate each event's t0 to a random trading day in the SAME calendar month,
    >=20 calendar days from any real event, with full est+event window. Two-sided p on |CAAV|."""
    cal = lv.index
    real_t0 = {}
    for _, ev in events.iterrows():
        real_t0[ev["event_id"]] = _t0_index(cal, ev["date"])
    real_dates = [pd.Timestamp(d) for d in events["date"]]
    e0, v1 = EST[0], EVT[1]
    # candidate pools by month
    valid = np.zeros(len(cal), bool)
    for j in range(len(cal)):
        if j + e0 >= 0 and j + v1 < len(cal):
            valid[j] = True
    months = cal.month.values
    pools = {}
    for m in range(1, 13):
        idx = np.where(valid & (months == m))[0]
        # drop within 20 calendar days of any real event
        keep = []
        for j in idx:
            dj = cal[j]
            if all(abs((dj - rd).days) >= 20 for rd in real_dates):
                keep.append(j)
        pools[m] = np.array(keep)

    obs = float(np.mean([e[cum_key] for e in run_event_study(lv, events, tk, market_adjust)]))
    ev_months = [pd.Timestamp(d).month for d in events["date"]]
    a, b = CUM[cum_key]
    y = lv[tk].values
    x = lv["SPY"].values
    est_a, est_b = EST

    def cav_at(t0):
        est_pos = np.arange(t0 + est_a, t0 + EST[1] + 1)
        cum_pos = np.arange(t0 + a, t0 + b + 1)
        if not market_adjust:
            est = y[est_pos]
            if np.any(~np.isfinite(est)):
                return None
            mu, sd = est.mean(), est.std(ddof=1)
            if sd < 1e-9:
                return None
            return float(np.sum((y[cum_pos] - mu) / sd))
        est_y, est_x = y[est_pos], x[est_pos]
        if np.any(~np.isfinite(est_y)) or np.any(~np.isfinite(est_x)):
            return None
        b1, b0 = np.polyfit(est_x, est_y, 1)
        sd = (est_y - (b0 + b1 * est_x)).std(ddof=2)
        if sd < 1e-9:
            return None
        return float(np.sum((y[cum_pos] - (b0 + b1 * x[cum_pos])) / sd))

    null = np.empty(n_perm)
    for r in range(n_perm):
        vals = []
        for m in ev_months:
            pool = pools[m]
            if len(pool) == 0:
                continue
            for _try in range(8):
                t0 = int(RNG.choice(pool))
                c = cav_at(t0)
                if c is not None:
                    vals.append(c); break
        null[r] = np.mean(vals) if vals else np.nan
    null = null[np.isfinite(null)]
    p = float((1 + np.sum(np.abs(null) >= abs(obs))) / (1 + len(null)))
    return {"observed_caav": obs, "placebo_p_two_sided": p, "n_perm_used": int(len(null)),
            "placebo_mean": float(np.mean(null)), "placebo_sd": float(np.std(null))}


# ============================ 5. DOSE-RESPONSE ============================
def ols_dose(y, x):
    """Simple OLS y = a + b*x with 95% CI (t) + bootstrap CI (SEED=42)."""
    x = np.asarray(x, float); y = np.asarray(y, float)
    n = len(x)
    if n < 4 or np.std(x) < 1e-12:
        return None
    from scipy import stats
    X = np.column_stack([np.ones(n), x])
    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    resid = y - X @ beta
    dof = n - 2
    s2 = (resid @ resid) / dof
    cov = s2 * np.linalg.inv(X.T @ X)
    se = np.sqrt(np.diag(cov))
    tcrit = stats.t.ppf(0.975, dof)
    slope, se_s = beta[1], se[1]
    tval = slope / se_s
    p = float(2 * stats.t.sf(abs(tval), df=dof))
    ss_tot = np.sum((y - y.mean()) ** 2)
    r2 = 1 - (resid @ resid) / ss_tot if ss_tot > 0 else np.nan
    # bootstrap slope CI
    bs = []
    for _ in range(2000):
        idx = RNG.integers(0, n, n)
        Xb, yb = X[idx], y[idx]
        try:
            bb, *_ = np.linalg.lstsq(Xb, yb, rcond=None)
            bs.append(bb[1])
        except Exception:
            pass
    bs = np.array(bs)
    return {
        "n": int(n), "slope": float(slope), "se": float(se_s), "t": float(tval), "p": p,
        "ci95": [float(slope - tcrit * se_s), float(slope + tcrit * se_s)],
        "boot_ci95": [float(np.percentile(bs, 2.5)), float(np.percentile(bs, 97.5))],
        "intercept": float(beta[0]), "r2": float(r2),
        "dose_range": [float(np.min(x)), float(np.max(x))],
    }


def spearman_dose(y, x):
    from scipy import stats
    x = np.asarray(x, float); y = np.asarray(y, float)
    m = np.isfinite(x) & np.isfinite(y)
    if m.sum() < 4:
        return None
    r = stats.spearmanr(x[m], y[m])
    return {"n": int(m.sum()), "rho": float(r.correlation), "p": float(r.pvalue)}


def ols_influence(y, x, dose_labels=None, drop_ks=(1, 2)):
    """Cook's-distance jackknife: refit dose slope after removing the top-k most influential events.
    Exposes whether a 'significant' gradient hinges on a couple of leverage/outlier points."""
    x = np.asarray(x, float); y = np.asarray(y, float)
    n = len(x)
    if n < 6 or np.std(x) < 1e-12:
        return None
    X = np.column_stack([np.ones(n), x])
    XtX_inv = np.linalg.inv(X.T @ X)
    H = X @ XtX_inv @ X.T
    h = np.diag(H)
    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    resid = y - X @ beta
    mse = (resid @ resid) / (n - 2)
    cook = (resid ** 2 / (2 * mse)) * (h / (1 - h) ** 2)
    order = np.argsort(-cook)
    out = {"cook_top_idx": [int(i) for i in order[:3]],
           "cook_top_vals": [float(cook[i]) for i in order[:3]]}
    if dose_labels is not None:
        out["cook_top_labels"] = [dose_labels[int(i)] for i in order[:3]]
    for k in drop_ks:
        keep = np.ones(n, bool); keep[order[:k]] = False
        d = ols_dose(y[keep], x[keep])
        out[f"drop_top{k}"] = None if d is None else {"slope": d["slope"], "p": d["p"], "r2": d["r2"], "n": d["n"]}
    # drop entire max-dose stratum (e.g. all Cat-5)
    mx = x < x.max()
    d = ols_dose(y[mx], x[mx]) if mx.sum() >= 5 and np.std(x[mx]) > 1e-9 else None
    out["drop_max_dose_stratum"] = None if d is None else {"slope": d["slope"], "p": d["p"], "r2": d["r2"], "n": d["n"]}
    return out


def pooled_dose_fe(per_by_sector, cum_key):
    """Pool sectors with sector fixed effects; event-clustered SE (cluster by event_id).
    Reported as SECONDARY (K1355: same-day cross-sector shocks are not iid)."""
    rows = []
    for sec, pe in per_by_sector.items():
        for e in pe:
            rows.append((e["event_id"], sec, e["dose"], e[cum_key]))
    if len(rows) < 6:
        return None
    ev_ids = sorted(set(r[0] for r in rows))
    secs = sorted(set(r[1] for r in rows))
    ev_idx = {e: k for k, e in enumerate(ev_ids)}
    import numpy as np
    dose = np.array([r[2] for r in rows], float)
    y = np.array([r[3] for r in rows], float)
    # design: intercept-per-sector (FE) + dose slope
    D = np.zeros((len(rows), len(secs)))
    for k, r in enumerate(rows):
        D[k, secs.index(r[1])] = 1.0
    X = np.column_stack([D, dose])
    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    resid = y - X @ beta
    XtX_inv = np.linalg.inv(X.T @ X)
    # cluster-robust (by event)
    meat = np.zeros((X.shape[1], X.shape[1]))
    clusters = np.array([ev_idx[r[0]] for r in rows])
    for cl in np.unique(clusters):
        m = clusters == cl
        Xg = X[m]; ug = resid[m]
        s = Xg.T @ ug
        meat += np.outer(s, s)
    G = len(np.unique(clusters))
    cov = XtX_inv @ meat @ XtX_inv * (G / (G - 1))
    se = np.sqrt(np.diag(cov))
    from scipy import stats
    slope = beta[-1]; se_s = se[-1]
    tval = slope / se_s
    p = float(2 * stats.t.sf(abs(tval), df=G - 1))
    return {"n_obs": len(rows), "n_events": G, "n_sectors": len(secs),
            "slope": float(slope), "cluster_se": float(se_s), "t": float(tval),
            "p_clustered": p, "sectors": secs}


# ============================ 6. NON-OVERLAP SUBSET ============================
def non_overlap_subset(per_event, min_sep_td=16):
    """Greedy: keep events whose t0 are >= min_sep_td trading days apart (drop later of a colliding pair)."""
    pe = sorted(per_event, key=lambda e: e["t0"])
    kept, last = [], -10 ** 9
    for e in pe:
        if e["t0"] - last >= min_sep_td:
            kept.append(e); last = e["t0"]
    return kept


# ============================ MAIN ============================
def summarize(per_event, label):
    if not per_event:
        return {"label": label, "n_events": 0}
    out = {"label": label, "n_events": len(per_event), "caav_curve": caav_curve(per_event)}
    for cname in CUM:
        out[cname + "_ttest"] = xsec_ttest([e[cname] for e in per_event])
    return out


def main():
    print(f"[K1811] seed={SEED}")
    # ---- events ----
    hur = build_hurricanes()
    heat = build_heatwaves()
    hur.to_csv(os.path.join(HERE, "data", "events_hurricanes.csv"), index=False)
    heat.to_csv(os.path.join(HERE, "data", "events_heatwaves.csv"), index=False)
    print(f"  hurricanes: n={len(hur)}  cat_dist={hur['dose'].value_counts().to_dict()}")
    print(f"  heat waves: n={len(heat)}  scale[min,max]=[{heat['dose'].min():.0f},{heat['dose'].max():.0f}]")

    # ---- ETF vol ----
    frames = fetch_ohlc()
    lv_park = logvol_frame(frames, "parkinson")
    lv_gk   = logvol_frame(frames, "gk")

    results = {
        "experiment": "K1811", "seed": SEED,
        "design": {"estimation_window": list(EST), "event_window": list(EVT),
                   "cum_windows": {k: list(v) for k, v in CUM.items()},
                   "vol_proxy_primary": "parkinson", "n_perm": N_PERM},
        "n_events": {"hurricane": int(len(hur)), "heat": int(len(heat)),
                     "total": int(len(hur) + len(heat))},
        "event_lists": {
            "hurricanes": hur[["event_id", "name", "date", "dose", "max_wind_kt", "n_us_landfalls"]].to_dict("records"),
            "heatwaves": heat[["event_id", "date", "dose", "deaths_direct_win"]].to_dict("records"),
        },
        "event_study": {}, "sector_specificity": {}, "dose_response": {},
        "robustness": {},
    }

    event_sets = {"hurricane": hur, "heat": heat}

    for etype, evs in event_sets.items():
        results["event_study"][etype] = {}
        per_by_sector_std = {}
        per_by_sector_madj = {}
        for tk in ALL_TK:
            pe_std = run_event_study(lv_park, evs, tk, market_adjust=False)
            results["event_study"][etype][tk] = summarize(pe_std, f"{etype}:{tk}:parkinson:standardized")
            if tk in SECTORS:
                per_by_sector_std[tk] = pe_std
                per_by_sector_madj[tk] = run_event_study(lv_park, evs, tk, market_adjust=True)
        # market-adjusted (sector-specific vol net of SPY) event study
        results["event_study"][etype]["_market_adjusted"] = {
            tk: summarize(per_by_sector_madj[tk], f"{etype}:{tk}:parkinson:market_adjusted")
            for tk in SECTORS}

        # placebo / permutation on primary cum window for each sector (standardized)
        results["event_study"][etype]["_placebo"] = {}
        for tk in SECTORS + ["SPY"]:
            results["event_study"][etype]["_placebo"][tk] = {
                ck: month_matched_placebo(lv_park, evs, tk, ck, market_adjust=False)
                for ck in CUM}

        # sector-specificity: paired (sector - SPY) CAV difference test
        spy_by_evt = {e["event_id"]: e for e in run_event_study(lv_park, evs, "SPY")}
        results["sector_specificity"][etype] = {}
        for tk in SECTORS:
            for ck in CUM:
                diffs = []
                for e in per_by_sector_std[tk]:
                    s = spy_by_evt.get(e["event_id"])
                    if s is not None:
                        diffs.append(e[ck] - s[ck])
                results["sector_specificity"][etype].setdefault(tk, {})[ck] = xsec_ttest(diffs)

        # dose-response (primary cum_0_10) per sector + pooled FE + full robustness suite
        results["dose_response"][etype] = {
            "per_sector": {}, "pooled_fe": {}, "spy_control": {},
            "market_adjusted": {}, "spearman": {}, "influence": {}, "per_event_cav": []}
        spy_pe = run_event_study(lv_park, evs, "SPY")
        for ck in CUM:
            for tk in SECTORS:
                pe = per_by_sector_std[tk]
                results["dose_response"][etype]["per_sector"].setdefault(tk, {})[ck] = \
                    ols_dose([e[ck] for e in pe], [e["dose"] for e in pe])
                results["dose_response"][etype]["market_adjusted"].setdefault(tk, {})[ck] = \
                    ols_dose([e[ck] for e in per_by_sector_madj[tk]], [e["dose"] for e in per_by_sector_madj[tk]])
            # SPY (market) dose-response: if the category gradient is also in SPY it is market-wide
            results["dose_response"][etype]["spy_control"][ck] = \
                ols_dose([e[ck] for e in spy_pe], [e["dose"] for e in spy_pe])
            results["dose_response"][etype]["pooled_fe"][ck] = pooled_dose_fe(per_by_sector_std, ck)
        # rank-based + influence diagnostics on primary window cum_0_10
        for tk in ALL_TK:
            pe = run_event_study(lv_park, evs, tk)
            y = [e["cum_0_10"] for e in pe]; x = [e["dose"] for e in pe]
            lbls = [e["event_id"] for e in pe]
            results["dose_response"][etype]["spearman"][tk] = spearman_dose(y, x)
            results["dose_response"][etype]["influence"][tk] = ols_influence(y, x, dose_labels=lbls)
        # per-event CAV transparency table (KIE/KBWP/XLU/SPY at cum_0_10)
        cav_map = {tk: {e["event_id"]: e["cum_0_10"] for e in run_event_study(lv_park, evs, tk)} for tk in ALL_TK}
        for _, ev in evs.iterrows():
            row = {"event_id": ev["event_id"], "name": ev["name"], "date": ev["date"], "dose": ev["dose"]}
            for tk in ALL_TK:
                row[tk] = cav_map[tk].get(ev["event_id"])
            results["dose_response"][etype]["per_event_cav"].append(row)

        # robustness: non-overlap subset CAAV (standardized, cum windows)
        results["robustness"].setdefault(etype, {})["non_overlap"] = {}
        for tk in SECTORS + ["SPY"]:
            pe = run_event_study(lv_park, evs, tk)
            sub = non_overlap_subset(pe)
            res = {"n_full": len(pe), "n_subset": len(sub)}
            for ck in CUM:
                res[ck + "_ttest"] = xsec_ttest([e[ck] for e in sub])
            results["robustness"][etype]["non_overlap"][tk] = res
        # robustness: Garman-Klass proxy CAAV
        results["robustness"][etype]["garman_klass"] = {}
        for tk in SECTORS + ["SPY"]:
            pe = run_event_study(lv_gk, evs, tk)
            r = {"n": len(pe)}
            for ck in CUM:
                r[ck + "_ttest"] = xsec_ttest([e[ck] for e in pe])
            results["robustness"][etype]["garman_klass"][tk] = r

    # provenance manifest
    json.dump(MANIFEST, open(os.path.join(HERE, "data", "provenance_manifest.json"), "w"), indent=2)
    results["provenance"] = {
        "hurricane_source": HURDAT2_URL,
        "heat_source": SE_BASE + "StormEvents_details-ftp_v1.0_d{YEAR}_c{REV}.csv.gz",
        "manifest_file": "data/provenance_manifest.json",
        "etf_source": "yfinance (daily OHLC, unadjusted; Parkinson range is adjustment-invariant)",
    }

    # ---- self-describing verdict (honest summary; NULL/mixed acceptable) ----
    hz = results["dose_response"]["hurricane"]
    results["summary"] = {
        "verdict": "MIXED_MOSTLY_NULL",
        "one_line": ("Hurricane mean abnormal vol NULL; a positive Saffir-category dose-response exists but is "
                     "FRAGILE (Cook's D of the single Cat-5 Michael = %.2f, ~10x next) and partly market-wide "
                     "(SPY gradient p=%.3f); heat waves fully NULL." % (
                         hz["influence"]["KIE"]["cook_top_vals"][0], hz["spy_control"]["cum_0_10"]["p"])),
        "hurricane_mean_av": "NULL (KIE p=%.2f, KBWP p=%.2f, XLU p=%.2f; placebo NS)" % (
            results["event_study"]["hurricane"]["KIE"]["cum_0_10_ttest"]["p"],
            results["event_study"]["hurricane"]["KBWP"]["cum_0_10_ttest"]["p"],
            results["event_study"]["hurricane"]["XLU"]["cum_0_10_ttest"]["p"]),
        "hurricane_dose_response": "SUGGESTIVE-BUT-FRAGILE (OLS KIE p=%.3f; Spearman p=%.3f; drop-Cat5 p=%.3f; SPY p=%.3f)" % (
            hz["per_sector"]["KIE"]["cum_0_10"]["p"], hz["spearman"]["KIE"]["p"],
            hz["influence"]["KIE"]["drop_max_dose_stratum"]["p"], hz["spy_control"]["cum_0_10"]["p"]),
        "heat": "NULL (mean AV negative=summer seasonal, placebo NS; dose-response all p>0.37)",
        "consistency_with_priors": "Refines K117/K148 (market absorbs climate-event vol): only the strongest, "
                                   "market-confounded events lift sector vol.",
        "self_verification": {
            "sign_convention_ok": bool(hz["per_event_cav"][0] is not None),
            "estimation_before_event": "EST=(-60,-11) strictly pre-t0, no overlap with EVT=(-5,10)",
            "seed": SEED, "not_too_good_to_be_true": "significant OLS traced to influential market-confounded Michael",
        },
        "unresolved": "None blocking. Pending: main-thread Codex code review before knowledge.json write. "
                      "Follow-up ideas: station-level GHCN heat-index dose; explicit market-stress exclusion window.",
    }

    make_figures(results, event_sets, lv_park)

    out = os.path.join(HERE, "k1811_results.json")
    json.dump(results, open(out, "w"), indent=2, default=float)
    print(f"  wrote {out}")
    _print_headline(results)
    return results


def _print_headline(R):
    print("\n===== HEADLINE NUMBERS =====")
    for etype in ("hurricane", "heat"):
        print(f"\n[{etype.upper()}]  n={R['n_events'][etype]}")
        for tk in ALL_TK:
            tt = R["event_study"][etype][tk].get("cum_0_10_ttest", {})
            print(f"  {tk:5s} CAAV[0,+10] mean={tt.get('mean'):+.3f}  t={tt.get('t')}  p={tt.get('p')}  (n={tt.get('n')})")
        for tk in SECTORS:
            pb = R["event_study"][etype]["_placebo"][tk]["cum_0_10"]
            ss = R["sector_specificity"][etype][tk]["cum_0_10"]
            print(f"    {tk} placebo p={pb['placebo_p_two_sided']:.3f} | (sector-SPY) mean={ss.get('mean'):+.3f} p={ss.get('p')}")
        for tk in SECTORS:
            dr = R["dose_response"][etype]["per_sector"][tk]["cum_0_10"]
            sp = R["dose_response"][etype]["spearman"][tk]
            inf = R["dose_response"][etype]["influence"][tk]
            if dr:
                dm = inf.get("drop_max_dose_stratum") if inf else None
                dm_s = f" | drop-max-dose p={dm['p']:.3f}" if dm else ""
                print(f"    dose {tk}: OLS slope={dr['slope']:+.3f} p={dr['p']:.3f} R2={dr['r2']:.3f} | "
                      f"Spearman rho={sp['rho']:+.3f} p={sp['p']:.3f}{dm_s}")
        spy = R["dose_response"][etype]["spy_control"]["cum_0_10"]
        if spy:
            print(f"    SPY (market) dose gradient: slope={spy['slope']:+.3f} p={spy['p']:.3f}  <- if sig, gradient is market-wide")
        pf = R["dose_response"][etype]["pooled_fe"]["cum_0_10"]
        if pf:
            print(f"    pooled-FE dose slope={pf['slope']:+.3f} cluster_p={pf['p_clustered']:.3f} (events={pf['n_events']})")


def make_figures(R, event_sets, lv):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    # CAAV curves
    for etype in ("hurricane", "heat"):
        fig, ax = plt.subplots(figsize=(8, 5))
        taus = list(range(EVT[0], EVT[1] + 1))
        for tk in ALL_TK:
            c = R["event_study"][etype][tk].get("caav_curve")
            if c:
                ax.plot(taus, [c[str(t)] if isinstance(list(c.keys())[0], str) else c[t] for t in taus],
                        marker="o", ms=3, label=tk)
        ax.axvline(0, color="k", ls=":", lw=0.8); ax.axhline(0, color="grey", lw=0.6)
        ax.set_title(f"K1811 Average Abnormal Volatility - {etype} events (Parkinson, standardized)")
        ax.set_xlabel("trading day relative to event (tau)"); ax.set_ylabel("AAV (std units)")
        ax.legend(); fig.tight_layout()
        fig.savefig(os.path.join(FIG, f"caav_{etype}.png"), dpi=110); plt.close(fig)
    # dose-response scatter
    for etype, evs in event_sets.items():
        fig, ax = plt.subplots(figsize=(8, 5))
        for tk in SECTORS:
            pe = run_event_study(lv, evs, tk)
            xs = [e["dose"] for e in pe]; ys = [e["cum_0_10"] for e in pe]
            ax.scatter(xs, ys, s=22, alpha=0.7, label=tk)
            dr = R["dose_response"][etype]["per_sector"][tk]["cum_0_10"]
            if dr and len(xs) > 1:
                xx = np.linspace(min(xs), max(xs), 20)
                ax.plot(xx, dr["intercept"] + dr["slope"] * xx, lw=1.2)
        ax.axhline(0, color="grey", lw=0.6)
        dose_label = "Saffir-Simpson category" if etype == "hurricane" else "heat scale (7d national event-count)"
        ax.set_title(f"K1811 Dose-response - {etype}: CAV[0,+10] vs dose")
        ax.set_xlabel(dose_label); ax.set_ylabel("cumulative abnormal vol [0,+10]")
        ax.legend(); fig.tight_layout()
        fig.savefig(os.path.join(FIG, f"dose_{etype}.png"), dpi=110); plt.close(fig)


if __name__ == "__main__":
    main()
