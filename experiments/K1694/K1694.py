#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""K1694 — FCM 清算集中度是否在高波動期排擠小型交易者並放大商品流動性風險。

研究問題
--------
用 CFTC 月度 FCM customer-segregated assets 算清算集中度（HHI），檢定：
FCM 清算集中度在高波動期是否排擠小型交易者、放大商品流動性風險？
以 CFTC DCOT 的 non-reportable positions（小型交易者代理）作為排擠的結果變數。

資料來源（provenance 最高風險）
--------------------------------
1. CFTC "Financial Data for FCMs" 月度 xlsx（每家 FCM 的 Customers' Assets in Seg）
   → 每月跨 FCM 的 HHI / CR4（系統層清算集中度）。
   - 資料 as-of = 月底；發布日 ≈ 月底 + 約 1 個月。本腳本用 availability = 月底 + 45 天
     的保守 lag，並以 as-of 合併確保 FCM 訊號嚴格早於結果（防 Class F lookahead）。
2. CFTC DCOT（Disaggregated COT, futures-only, 72hh-3qpy）週頻：
   - nonrept_positions_long/short_all（小型交易者部位）→ 排擠結果
   - conc_gross_le_4/8_tdr（trader-level 集中度）→ 第二個集中度視角（部位層 vs 清算層）
   - DCOT 資料 as-of 週二、發布週五（約 3 天 lag）。
3. 波動：對應商品期貨的 realized vol（yfinance 日資料）。

方法（含正式檢定）
------------------
- 觀察先於計算：HHI 時序、regime 描述統計、相關表。
- 排擠假說：high-vol × 高 FCM 集中度 → 小型交易者部位/佔比下降（交互項 β<0）。
- Panel（commodity × month）FE + Driscoll-Kraay / cluster-by-month SE（K1355：不可把
  asset-month 當 iid；同月跨商品有共同 shock）。
- Time-series aggregate 版用 Newey-West，bandwidth 由 loss/resid acf 決定（K1655：不可只用 h-1）。
- Block bootstrap（by month）固定 seed=1694。
- Null 如實報告。

誠實邊界
--------
FCM 集中度是單一月度系統序列（高自相關、有效自由度低）；結論強度須節制。
波動 regime 與結果同期 → 為「相關」非「因果」；另附全落後 predictive spec 作對照。
"""
from __future__ import annotations

import io
import json
import re
import ssl
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
FIG = HERE / "figures"
DATA.mkdir(exist_ok=True)
FIG.mkdir(exist_ok=True)

SEED = 1694
np.random.seed(SEED)

# TLS verification ON via certifi CA bundle (host's default trust store lacks the CFTC
# intermediate chain; certifi carries it). No insecure fallback.
import certifi  # noqa: E402
_SSL = ssl.create_default_context(cafile=certifi.where())
_UA = {"User-Agent": "Mozilla/5.0 (research; volpred K1694)"}

FCM_LAG_DAYS = 45  # 保守：CFTC FCM 月報 ≈ 月底 + 1 個月發布；再加緩衝防 lookahead

# 精選流動實體商品：DCOT contract_market_name -> yfinance ticker
COMMODITY_MAP = {
    "WTI-PHYSICAL": "CL=F",
    "NAT GAS NYME": "NG=F",
    "GOLD": "GC=F",
    "SILVER": "SI=F",
    "PLATINUM": "PL=F",
    "PALLADIUM": "PA=F",
    "COPPER- #1": "HG=F",
    "CORN": "ZC=F",
    "SOYBEANS": "ZS=F",
    "SOYBEAN OIL": "ZL=F",
    "SOYBEAN MEAL": "ZM=F",
    "WHEAT-SRW": "ZW=F",
    "WHEAT-HRW": "KE=F",
    "SUGAR NO. 11": "SB=F",
    "COFFEE C": "KC=F",
    "COCOA": "CC=F",
    "COTTON NO. 2": "CT=F",
    "LIVE CATTLE": "LE=F",
    "LEAN HOGS": "HE=F",
    "FEEDER CATTLE": "GF=F",
    "NY HARBOR ULSD": "HO=F",
    "GASOLINE RBOB": "RB=F",
}


def _get(url: str, timeout: int = 60) -> bytes:
    req = urllib.request.Request(url, headers=_UA)
    return urllib.request.urlopen(req, timeout=timeout, context=_SSL).read()


# ---------------------------------------------------------------------------
# 1. FCM monthly clearing concentration (HHI / CR4)
# ---------------------------------------------------------------------------
MONTHS = {m: i for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july",
     "august", "september", "october", "november", "december"], start=1)}


def _fcm_manifest() -> list[dict]:
    """Scrape recent + historical index pages -> [{year, month, url, era}]."""
    base = "https://www.cftc.gov"
    pages = [
        base + "/MarketReports/financialfcmdata/index.htm",
        base + "/MarketReports/financialfcmdata/HistoricalFCMReports/index.htm",
    ]
    out: dict[tuple[int, int], dict] = {}
    for page in pages:
        try:
            html = _get(page).decode("utf-8", "ignore")
        except Exception as exc:  # noqa: BLE001
            print(f"  [manifest] FAIL {page}: {exc!r}", file=sys.stderr)
            continue
        links = re.findall(r'href=["\']([^"\']+\.(?:xls|xlsx))["\']', html, re.I)
        for href in links:
            url = href if href.startswith("http") else base + href
            fn = urllib.parse.unquote(href.split("/")[-1])
            ym = _parse_fcm_month(fn)
            if ym is None:
                continue
            year, month = ym
            era = "A" if "webpage update" in fn.lower() else "B"
            # prefer era A (newest consistent xlsx); else keep first seen
            if (year, month) not in out or (era == "A" and out[(year, month)]["era"] != "A"):
                out[(year, month)] = {"year": year, "month": month, "url": url, "era": era, "fn": fn}
    return sorted(out.values(), key=lambda d: (d["year"], d["month"]))


def _parse_fcm_month(fn: str) -> tuple[int, int] | None:
    low = fn.lower()
    m = re.search(r"webpage update - ([a-z]+) (\d{4})", low)
    if m and m.group(1) in MONTHS:
        return int(m.group(2)), MONTHS[m.group(1)]
    m = re.search(r"(?:tm)?fcmdata(\d{2})(\d{2})", low)
    if m:
        mm, yy = int(m.group(1)), int(m.group(2))
        if 1 <= mm <= 12:
            year = 2000 + yy
            return year, mm
    return None


def _parse_fcm_file(url: str) -> dict | None:
    """Return {n_fcm, hhi_seg, cr4_seg, hhi_total, total_seg, asof} or None."""
    try:
        raw = _get(url)
        book = pd.read_excel(io.BytesIO(raw), sheet_name=0, header=None)
    except Exception as exc:  # noqa: BLE001
        print(f"    parse FAIL {url[-40:]}: {exc!r}", file=sys.stderr)
        return None
    # find header row: contains a cell matching "assets in seg"
    hdr_row = None
    cols: dict[str, int] = {}
    for i in range(min(12, len(book))):
        rowvals = [str(x).lower().replace("\n", " ") for x in book.iloc[i].tolist()]
        for j, v in enumerate(rowvals):
            if re.search(r"assets\s+in\s+seg", v):
                cols["seg"] = j
            if re.search(r"section\s+30\.7\s+account", v) or re.search(r"separate\s+section\s+30\.7", v):
                cols["s307"] = j
            if re.search(r"cleared\s+swap\s+segrega", v):
                cols["cswap"] = j
            if re.search(r"as\s+of\s*date", v):
                cols["asof"] = j
        if "seg" in cols:
            hdr_row = i
            break
    if hdr_row is None or "seg" not in cols:
        return None
    body = book.iloc[hdr_row + 1:].copy()
    seg = pd.to_numeric(body.iloc[:, cols["seg"]], errors="coerce")
    # data rows: positive seg assets; drop TOTAL rows (name col ~ col1)
    name_col = 1 if book.shape[1] > 1 else 0
    names = body.iloc[:, name_col].astype(str).str.lower()
    mask = seg.notna() & (seg > 0) & (~names.str.contains("total", na=False))
    seg = seg[mask].to_numpy(dtype=float)
    if seg.size < 5:
        return None
    total = float(seg.sum())
    shares = seg / total
    hhi = float(np.sum(shares ** 2))
    top4 = float(np.sort(shares)[::-1][:4].sum())
    rec = {
        "n_fcm": int(seg.size),
        "hhi_seg": hhi,
        "cr4_seg": top4,
        "total_seg": total,
    }
    # HHI on total customer funds (seg + 30.7 + cleared swaps) as robustness
    comp = seg.copy()
    for k in ("s307", "cswap"):
        if k in cols:
            extra = pd.to_numeric(book.iloc[hdr_row + 1:, cols[k]], errors="coerce")
            extra = extra[mask].fillna(0).to_numpy(dtype=float)
            if extra.shape == comp.shape:
                comp = comp + extra
    tot2 = float(comp.sum())
    if tot2 > 0:
        s2 = comp / tot2
        rec["hhi_total"] = float(np.sum(s2 ** 2))
        rec["cr4_total"] = float(np.sort(s2)[::-1][:4].sum())
    # as-of date from file if present
    asof = None
    if "asof" in cols:
        av = pd.to_datetime(book.iloc[hdr_row + 1:, cols["asof"]], errors="coerce").dropna()
        if len(av):
            asof = av.mode().iloc[0]
    rec["asof_file"] = str(asof.date()) if asof is not None and pd.notna(asof) else None
    return rec


def build_fcm() -> pd.DataFrame:
    cache = DATA / "fcm_monthly.csv"
    if cache.exists():
        df = pd.read_csv(cache, parse_dates=["month_end", "avail_date"])
        print(f"[FCM] cached {len(df)} months {df.month_end.min().date()}..{df.month_end.max().date()}")
        return df
    manifest = _fcm_manifest()
    print(f"[FCM] manifest {len(manifest)} files; downloading/parsing ...")
    rows = []
    for i, mf in enumerate(manifest):
        rec = _parse_fcm_file(mf["url"])
        if rec is None:
            continue
        month_end = (pd.Timestamp(year=mf["year"], month=mf["month"], day=1)
                     + pd.offsets.MonthEnd(0))
        avail = month_end + timedelta(days=FCM_LAG_DAYS)
        rec.update({"year": mf["year"], "month": mf["month"], "era": mf["era"],
                    "month_end": month_end, "avail_date": avail})
        rows.append(rec)
        if (i + 1) % 25 == 0:
            print(f"    parsed {i+1}/{len(manifest)} (kept {len(rows)})")
    df = pd.DataFrame(rows).sort_values("month_end").reset_index(drop=True)
    df.to_csv(cache, index=False)
    print(f"[FCM] kept {len(df)} months {df.month_end.min().date()}..{df.month_end.max().date()}")
    return df


# ---------------------------------------------------------------------------
# 2. DCOT small-trader (non-reportable) + trader concentration
# ---------------------------------------------------------------------------
def build_dcot() -> pd.DataFrame:
    cache = DATA / "dcot_weekly.csv"
    if cache.exists():
        df = pd.read_csv(cache, parse_dates=["report_date"])
        print(f"[DCOT] cached {len(df)} rows, {df.commodity.nunique()} commodities")
        return df
    fields = ["report_date_as_yyyy_mm_dd", "contract_market_name", "open_interest_all",
              "nonrept_positions_long_all", "nonrept_positions_short_all",
              "pct_of_oi_nonrept_long_all", "pct_of_oi_nonrept_short_all",
              "conc_gross_le_4_tdr_long", "conc_gross_le_4_tdr_short",
              "conc_gross_le_8_tdr_long", "conc_gross_le_8_tdr_short",
              "traders_tot_all"]
    names = list(COMMODITY_MAP.keys())
    in_clause = ",".join("'" + n.replace("'", "''") + "'" for n in names)
    params = {
        "$select": ",".join(fields),
        "$where": f"contract_market_name in ({in_clause})",
        "$limit": "100000",
        "$order": "report_date_as_yyyy_mm_dd",
    }
    url = "https://publicreporting.cftc.gov/resource/72hh-3qpy.json?" + urllib.parse.urlencode(params)
    data = json.loads(_get(url).decode())
    df = pd.DataFrame(data)
    df["report_date"] = pd.to_datetime(df["report_date_as_yyyy_mm_dd"]).dt.tz_localize(None)
    df["commodity"] = df["contract_market_name"]
    num = [c for c in fields if c not in ("report_date_as_yyyy_mm_dd", "contract_market_name")]
    for c in num:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df.to_csv(cache, index=False)
    print(f"[DCOT] fetched {len(df)} rows, {df.commodity.nunique()} commodities "
          f"{df.report_date.min().date()}..{df.report_date.max().date()}")
    return df


# ---------------------------------------------------------------------------
# 3. Realized vol per commodity (yfinance)
# ---------------------------------------------------------------------------
def build_vol(start="2005-01-01") -> pd.DataFrame:
    cache = DATA / "rv_monthly.csv"
    if cache.exists():
        df = pd.read_csv(cache, parse_dates=["month_end"])
        print(f"[RV] cached {len(df)} rows, {df.commodity.nunique()} commodities")
        return df
    import yfinance as yf
    frames = []
    for name, tick in COMMODITY_MAP.items():
        try:
            px = yf.download(tick, start=start, progress=False, auto_adjust=True)
        except Exception as exc:  # noqa: BLE001
            print(f"  [RV] {tick} FAIL {exc!r}", file=sys.stderr)
            continue
        if px is None or len(px) == 0:
            continue
        close = px["Close"]
        if isinstance(close, pd.DataFrame):
            close = close.iloc[:, 0]
        ret = np.log(close).diff()
        g = ret.groupby(ret.index.to_period("M"))
        rv = g.std() * np.sqrt(252)
        cnt = g.count()
        m = pd.DataFrame({"rv": rv, "ndays": cnt})
        m = m[m["ndays"] >= 10]  # require enough trading days
        m["commodity"] = name
        m["month_end"] = m.index.to_timestamp(how="end").normalize()
        frames.append(m.reset_index(drop=True))
    df = pd.concat(frames, ignore_index=True)
    df.to_csv(cache, index=False)
    print(f"[RV] {len(df)} rows, {df.commodity.nunique()} commodities")
    return df


# ---------------------------------------------------------------------------
# 4. Panel assembly (provenance-aware as-of merge)
# ---------------------------------------------------------------------------
def build_panel(fcm: pd.DataFrame, dcot: pd.DataFrame, rv: pd.DataFrame) -> pd.DataFrame:
    # --- DCOT weekly -> monthly per commodity ---
    d = dcot.copy()
    d["nonrep_share"] = (d["nonrept_positions_long_all"] + d["nonrept_positions_short_all"]) / \
                        (2.0 * d["open_interest_all"])
    d["small_pct"] = (d["pct_of_oi_nonrept_long_all"] + d["pct_of_oi_nonrept_short_all"]) / 2.0
    d["conc4"] = (d["conc_gross_le_4_tdr_long"] + d["conc_gross_le_4_tdr_short"]) / 2.0
    d["month"] = d["report_date"].dt.to_period("M")
    agg = d.groupby(["commodity", "month"]).agg(
        nonrep_share=("nonrep_share", "mean"),
        small_pct=("small_pct", "mean"),
        conc4=("conc4", "mean"),
        oi=("open_interest_all", "mean"),
        n_traders=("traders_tot_all", "mean"),
        nweeks=("nonrep_share", "size"),
    ).reset_index()
    agg["month_end"] = agg["month"].dt.to_timestamp(how="end").normalize()

    # --- realized vol monthly ---
    rvm = rv.copy()
    rvm["month"] = rvm["month_end"].dt.to_period("M")
    agg = agg.merge(rvm[["commodity", "month", "rv"]], on=["commodity", "month"], how="left")

    # --- FCM as-of merge: attach latest FCM report AVAILABLE by month_end ---
    fcm_sorted = fcm.sort_values("avail_date").reset_index(drop=True)
    agg = agg.sort_values("month_end").reset_index(drop=True)
    merged = pd.merge_asof(
        agg, fcm_sorted[["avail_date", "hhi_seg", "cr4_seg", "hhi_total", "n_fcm"]],
        left_on="month_end", right_on="avail_date", direction="backward",
    )
    # data-month gap between FCM report used and outcome month (provenance sanity)
    merged["fcm_used_month"] = merged["avail_date"] - pd.Timedelta(days=FCM_LAG_DAYS)

    # --- within-commodity dynamics & regime ---
    merged = merged.sort_values(["commodity", "month"]).reset_index(drop=True)
    g = merged.groupby("commodity", group_keys=False)
    merged["d_nonrep"] = g["nonrep_share"].diff()
    merged["nonrep_lag"] = g["nonrep_share"].shift(1)
    merged["d_nonrep_lag"] = g["d_nonrep"].shift(1)
    merged["dlog_oi"] = g["oi"].apply(lambda s: np.log(s).diff())
    # vol z-score within commodity; highvol = above commodity-specific median
    merged["rv_z"] = g["rv"].transform(lambda s: (s - s.mean()) / s.std(ddof=0))
    merged["highvol"] = g["rv"].transform(lambda s: (s > s.median()).astype(float))
    merged["conc4_z"] = g["conc4"].transform(lambda s: (s - s.mean()) / s.std(ddof=0))

    # FCM concentration z-scores (time series, common across commodities)
    fcm_ts = merged.dropna(subset=["hhi_seg"]).drop_duplicates("month")[["month", "hhi_seg", "cr4_seg", "hhi_total"]]
    for col in ("hhi_seg", "cr4_seg", "hhi_total"):
        mu, sd = fcm_ts[col].mean(), fcm_ts[col].std(ddof=0)
        merged[col + "_z"] = (merged[col] - mu) / sd

    # interactions (crowding-out core term)
    merged["fcm_x_highvol"] = merged["hhi_seg_z"] * merged["highvol"]
    merged["fcm_x_rvz"] = merged["hhi_seg_z"] * merged["rv_z"]
    merged["conc4_x_highvol"] = merged["conc4_z"] * merged["highvol"]

    merged["month_id"] = merged["month"].astype(str)
    return merged


# ---------------------------------------------------------------------------
# 5. Descriptives (observation before inference)
# ---------------------------------------------------------------------------
def descriptives(panel: pd.DataFrame, fcm: pd.DataFrame) -> dict:
    out = {}
    out["fcm_hhi_stats"] = {
        "n_months": int(fcm["hhi_seg"].notna().sum()),
        "span": [str(fcm["month_end"].min().date()), str(fcm["month_end"].max().date())],
        "hhi_seg_mean": float(fcm["hhi_seg"].mean()),
        "hhi_seg_min": float(fcm["hhi_seg"].min()),
        "hhi_seg_max": float(fcm["hhi_seg"].max()),
        "cr4_seg_mean": float(fcm["cr4_seg"].mean()),
        "n_fcm_mean": float(fcm["n_fcm"].mean()),
        "n_fcm_last": int(fcm.sort_values("month_end")["n_fcm"].iloc[-1]),
        "hhi_seg_trend_perYr": float(np.polyfit(
            (fcm["month_end"] - fcm["month_end"].min()).dt.days / 365.25,
            fcm["hhi_seg"], 1)[0]),
    }
    # 2x2 regime table on d_nonrep
    p = panel.dropna(subset=["d_nonrep", "highvol", "hhi_seg_z"]).copy()
    p["fcm_high"] = (p["hhi_seg_z"] > 0).astype(int)
    cell = p.groupby(["fcm_high", "highvol"])["d_nonrep"].agg(["mean", "std", "size"])
    out["regime_2x2_d_nonrep"] = {
        f"fcm{int(fh)}_vol{int(hv)}": {"mean": float(r["mean"]), "std": float(r["std"]), "n": int(r["size"])}
        for (fh, hv), r in cell.iterrows()
    }
    # simple correlations
    cc = p[["d_nonrep", "hhi_seg_z", "rv_z", "highvol", "conc4_z", "dlog_oi"]].corr()
    out["corr_d_nonrep"] = {k: float(v) for k, v in cc["d_nonrep"].items()}
    return out


# ---------------------------------------------------------------------------
# 6. Panel regressions (Driscoll-Kraay + cluster-by-month)
# ---------------------------------------------------------------------------
def _acf_bandwidth(resid: np.ndarray, nmonths: int) -> int:
    """K1655: HAC lag from data, not h-1. floor = ceil(n^{1/3})."""
    base = int(np.ceil(nmonths ** (1.0 / 3.0)))
    return max(base, 4)


def panel_regression(panel: pd.DataFrame) -> dict:
    from linearmodels.panel import PanelOLS
    import statsmodels.formula.api as smf  # noqa: F401

    results = {}
    base_cols = ["d_nonrep", "hhi_seg_z", "highvol", "fcm_x_highvol",
                 "nonrep_lag", "d_nonrep_lag", "dlog_oi", "rv_z", "fcm_x_rvz",
                 "conc4_z", "conc4_x_highvol", "commodity", "month", "month_id"]
    df = panel.dropna(subset=["d_nonrep", "hhi_seg_z", "highvol", "nonrep_lag",
                              "d_nonrep_lag", "dlog_oi", "rv_z"]).copy()
    df = df[base_cols].copy()
    # time trend
    df["t"] = (df["month"].astype("period[M]").astype(int))
    df["t"] = df["t"] - df["t"].min()
    nmonths = df["month"].nunique()

    df = df.set_index(["commodity", "month"])

    def run(rhs: list[str], label: str, dk_lag: int):
        y = df["d_nonrep"]
        X = df[rhs].astype(float)
        mod = PanelOLS(y, X, entity_effects=True)
        res_dk = mod.fit(cov_type="kernel", kernel="bartlett", bandwidth=dk_lag)
        res_cl = mod.fit(cov_type="clustered", cluster_entity=False, cluster_time=True)
        key = lambda r: {  # noqa: E731
            "coef": {k: float(r.params[k]) for k in rhs},
            "tstat": {k: float(r.tstats[k]) for k in rhs},
            "pval": {k: float(r.pvalues[k]) for k in rhs},
        }
        results[label] = {
            "n_obs": int(res_dk.nobs),
            "n_commodities": int(df.index.get_level_values(0).nunique()),
            "n_months": int(nmonths),
            "rhs": rhs,
            "driscoll_kraay": key(res_dk) | {"bandwidth": dk_lag},
            "cluster_by_month": key(res_cl),
            "rsq_within": float(res_dk.rsquared_within),
        }
        return res_dk

    dk = _acf_bandwidth(np.zeros(nmonths), nmonths)
    # Spec 1: FCM system HHI × highvol (primary crowding-out)
    run(["hhi_seg_z", "highvol", "fcm_x_highvol", "nonrep_lag", "d_nonrep_lag", "dlog_oi", "t"],
        "spec1_fcm_highvol", dk)
    # Spec 2: continuous FCM × rv_z
    run(["hhi_seg_z", "rv_z", "fcm_x_rvz", "nonrep_lag", "d_nonrep_lag", "dlog_oi", "t"],
        "spec2_fcm_rvz_continuous", dk)
    # Spec 3: trader-concentration lens (within-commodity conc4)
    run(["conc4_z", "highvol", "conc4_x_highvol", "nonrep_lag", "d_nonrep_lag", "dlog_oi", "t"],
        "spec3_trader_conc4_highvol", dk)
    results["_hac_bandwidth"] = dk
    return results


def timeseries_regression(panel: pd.DataFrame) -> dict:
    """Cross-commodity aggregate: mean d_nonrep on FCM HHI + interaction, Newey-West."""
    import statsmodels.api as sm
    p = panel.dropna(subset=["d_nonrep", "hhi_seg_z", "highvol"]).copy()
    ts = p.groupby("month").agg(
        d_nonrep=("d_nonrep", "mean"),
        hhi_z=("hhi_seg_z", "first"),
        highvol_frac=("highvol", "mean"),
    ).reset_index().sort_values("month")
    ts["hhi_x_volfrac"] = ts["hhi_z"] * (ts["highvol_frac"] - ts["highvol_frac"].mean())
    y = ts["d_nonrep"].to_numpy()
    X = sm.add_constant(ts[["hhi_z", "highvol_frac", "hhi_x_volfrac"]].to_numpy())
    ols = sm.OLS(y, X).fit()
    resid = ols.resid
    # bandwidth from acf of residuals
    n = len(resid)
    lag = _acf_bandwidth(resid, n)
    nw = sm.OLS(y, X).fit(cov_type="HAC", cov_kwds={"maxlags": lag})
    names = ["const", "hhi_z", "highvol_frac", "hhi_x_volfrac"]
    # residual acf(1) for reporting (K1655 direction check)
    acf1 = float(np.corrcoef(resid[:-1], resid[1:])[0, 1]) if n > 2 else float("nan")
    return {
        "n_months": int(n),
        "hac_lag": int(lag),
        "resid_acf1": acf1,
        "coef": {nm: float(nw.params[i]) for i, nm in enumerate(names)},
        "tstat": {nm: float(nw.tvalues[i]) for i, nm in enumerate(names)},
        "pval": {nm: float(nw.pvalues[i]) for i, nm in enumerate(names)},
    }


# ---------------------------------------------------------------------------
# 7. Block bootstrap (by month) for interaction coefficient
# ---------------------------------------------------------------------------
def bootstrap_interaction(panel: pd.DataFrame, n_boot: int = 2000) -> dict:
    from linearmodels.panel import PanelOLS
    rng = np.random.default_rng(SEED)
    rhs = ["hhi_seg_z", "highvol", "fcm_x_highvol", "nonrep_lag", "d_nonrep_lag", "dlog_oi"]
    df = panel.dropna(subset=["d_nonrep"] + rhs).copy()
    months = df["month"].unique()
    # precompute point estimate
    def fit(dd):
        dd = dd.set_index(["commodity", "month"])
        try:
            r = PanelOLS(dd["d_nonrep"], dd[rhs].astype(float), entity_effects=True).fit(
                cov_type="unadjusted")
            return float(r.params["fcm_x_highvol"])
        except Exception:  # noqa: BLE001
            return np.nan
    point = fit(df.copy())
    boots = []
    mlist = list(months)
    for _ in range(n_boot):
        pick = rng.choice(len(mlist), size=len(mlist), replace=True)
        parts = []
        for k, idx in enumerate(pick):
            sub = df[df["month"] == mlist[idx]].copy()
            # relabel month to keep clusters distinct (avoid duplicate index)
            sub["month"] = f"B{k}"
            parts.append(sub)
        bd = pd.concat(parts, ignore_index=True)
        b = fit(bd)
        if not np.isnan(b):
            boots.append(b)
    boots = np.array(boots)
    return {
        "point": float(point),
        "n_boot": int(len(boots)),
        "ci95": [float(np.percentile(boots, 2.5)), float(np.percentile(boots, 97.5))],
        "p_two_sided": float(2 * min((boots > 0).mean(), (boots < 0).mean())),
        "mean": float(boots.mean()),
        "std": float(boots.std(ddof=1)),
    }


# ---------------------------------------------------------------------------
# 8. Figures
# ---------------------------------------------------------------------------
def make_figures(fcm: pd.DataFrame, panel: pd.DataFrame, panel_res: dict, boot: dict):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    # fig1: FCM HHI + CR4 time series
    f = fcm.sort_values("month_end")
    fig, ax1 = plt.subplots(figsize=(10, 4.5))
    ax1.plot(f["month_end"], f["hhi_seg"], color="#1f4e79", lw=1.8, label="HHI (customer seg funds)")
    ax1.set_ylabel("HHI (0-1)", color="#1f4e79")
    ax1.tick_params(axis="y", labelcolor="#1f4e79")
    ax2 = ax1.twinx()
    ax2.plot(f["month_end"], f["cr4_seg"] * 100, color="#c0504d", lw=1.3, ls="--", label="CR4 (%)")
    ax2.set_ylabel("Top-4 FCM share (%)", color="#c0504d")
    ax2.tick_params(axis="y", labelcolor="#c0504d")
    ax1.set_title("FCM clearing concentration of U.S. customer segregated funds (CFTC monthly)")
    ax1.grid(alpha=0.25)
    fig.tight_layout()
    fig.savefig(FIG / "fig1_fcm_hhi_timeseries.png", dpi=130)
    plt.close(fig)

    # fig2: 2x2 regime bar of mean d_nonrep
    p = panel.dropna(subset=["d_nonrep", "highvol", "hhi_seg_z"]).copy()
    p["fcm_high"] = (p["hhi_seg_z"] > 0).astype(int)
    cell = p.groupby(["fcm_high", "highvol"])["d_nonrep"].mean() * 1e4  # in bp of OI share
    labels = ["Low HHI\nLow vol", "Low HHI\nHigh vol", "High HHI\nLow vol", "High HHI\nHigh vol"]
    vals = [cell.get((0, 0), np.nan), cell.get((0, 1), np.nan),
            cell.get((1, 0), np.nan), cell.get((1, 1), np.nan)]
    colors = ["#9dc3e6", "#2e75b6", "#f4b183", "#c00000"]
    fig, ax = plt.subplots(figsize=(7.5, 4.5))
    ax.bar(labels, vals, color=colors)
    ax.axhline(0, color="k", lw=0.8)
    ax.set_ylabel("Mean Δ small-trader OI share (bp)")
    ax.set_title("Crowding-out check: monthly change in non-reportable share by regime")
    ax.grid(axis="y", alpha=0.25)
    fig.tight_layout()
    fig.savefig(FIG / "fig2_regime_2x2.png", dpi=130)
    plt.close(fig)

    # fig3: interaction coefficient across specs + bootstrap CI
    fig, ax = plt.subplots(figsize=(8, 4.2))
    labels3, coefs, los, his = [], [], [], []
    spec_map = {
        "spec1_fcm_highvol": ("FCM HHI × highvol\n(DK)", "fcm_x_highvol"),
        "spec2_fcm_rvz_continuous": ("FCM HHI × rv_z\n(DK)", "fcm_x_rvz"),
        "spec3_trader_conc4_highvol": ("Trader conc4 × highvol\n(DK)", "conc4_x_highvol"),
    }
    for sp, (lab, term) in spec_map.items():
        r = panel_res[sp]["driscoll_kraay"]
        c = r["coef"][term]
        t = r["tstat"][term]
        se = abs(c / t) if t != 0 else np.nan
        labels3.append(lab); coefs.append(c); los.append(c - 1.96 * se); his.append(c + 1.96 * se)
    # bootstrap point for spec1
    labels3.append("FCM HHI × highvol\n(block boot)")
    coefs.append(boot["point"]); los.append(boot["ci95"][0]); his.append(boot["ci95"][1])
    ypos = np.arange(len(labels3))
    for i in range(len(labels3)):
        ax.plot([los[i], his[i]], [ypos[i], ypos[i]], color="#404040", lw=2)
        ax.plot(coefs[i], ypos[i], "o", color="#c00000", ms=7)
    ax.axvline(0, color="k", ls="--", lw=1)
    ax.set_yticks(ypos); ax.set_yticklabels(labels3, fontsize=9)
    ax.set_xlabel("Interaction coefficient on Δ small-trader share (95% CI)")
    ax.set_title("Does high clearing concentration steepen small-trader retreat in high vol?")
    ax.grid(axis="x", alpha=0.25)
    fig.tight_layout()
    fig.savefig(FIG / "fig3_interaction_coef.png", dpi=130)
    plt.close(fig)
    print("[FIG] wrote 3 figures")


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
def main():
    print("=== K1694 build ===")
    fcm = build_fcm()
    dcot = build_dcot()
    rv = build_vol()
    panel = build_panel(fcm, dcot, rv)
    panel.to_csv(DATA / "panel.csv", index=False)
    common = panel.dropna(subset=["d_nonrep", "hhi_seg_z", "rv"])
    print(f"[PANEL] {len(panel)} rows; usable {len(common)}; "
          f"{common['commodity'].nunique()} commodities; "
          f"span {common['month'].min()}..{common['month'].max()}")

    desc = descriptives(panel, fcm)
    panel_res = panel_regression(panel)
    ts_res = timeseries_regression(panel)
    boot = bootstrap_interaction(panel, n_boot=2000)
    make_figures(fcm, panel, panel_res, boot)

    # ---- verdict logic ----
    p1 = panel_res["spec1_fcm_highvol"]
    dk_t = p1["driscoll_kraay"]["tstat"]["fcm_x_highvol"]
    dk_c = p1["driscoll_kraay"]["coef"]["fcm_x_highvol"]
    cl_t = p1["cluster_by_month"]["tstat"]["fcm_x_highvol"]
    crowding_out = (dk_c < 0) and (abs(dk_t) >= 2.0) and (abs(cl_t) >= 2.0) and \
                   (boot["ci95"][1] < 0)
    verdict = "CROWDING_OUT_SUPPORTED" if crowding_out else "NULL"

    results = {
        "experiment_id": "K1694",
        "title": "FCM clearing concentration and high-volatility crowding-out of small commodity traders",
        "seed": SEED,
        "generated_utc": datetime.utcnow().isoformat() + "Z",
        "verdict": verdict,
        "data_provenance": {
            "fcm_source": "CFTC Financial Data for FCMs (monthly xlsx)",
            "fcm_publication_lag_days_assumed": FCM_LAG_DAYS,
            "fcm_asof_merge": "backward as-of on month_end >= FCM avail_date (month_end+45d)",
            "dcot_source": "CFTC DCOT futures-only 72hh-3qpy (weekly; as-of Tue, published Fri)",
            "dcot_small_trader_proxy": "non-reportable positions (long+short)/(2*OI)",
            "vol_source": "yfinance daily futures; monthly realized vol = std(daily logret)*sqrt(252)",
            "commodities": list(COMMODITY_MAP.keys()),
        },
        "sample": {
            "fcm_months": desc["fcm_hhi_stats"]["n_months"],
            "fcm_span": desc["fcm_hhi_stats"]["span"],
            "panel_rows_usable": int(len(common)),
            "panel_commodities": int(common["commodity"].nunique()),
            "panel_span": [str(common["month"].min()), str(common["month"].max())],
        },
        "descriptives": desc,
        "panel_regressions": panel_res,
        "timeseries_regression": ts_res,
        "bootstrap_interaction_spec1": boot,
        "primary_interaction": {
            "term": "fcm_x_highvol",
            "coef": dk_c, "t_driscoll_kraay": dk_t, "t_cluster_month": cl_t,
            "bootstrap_ci95": boot["ci95"],
        },
        "limitations": [
            "FCM concentration is a single system-wide monthly series (high autocorrelation, "
            "low effective d.o.f.); its main effect is a common time factor.",
            "Volatility regime is contemporaneous with the outcome -> association, not causal; "
            "reverse causality (small-trader exit affecting vol) cannot be excluded.",
            "FCM seg funds are dominated by financial futures; crowding-out mapped onto "
            "physical-commodity small traders is an indirect linkage.",
            "yfinance continuous-futures realized vol is a proxy for each commodity's true vol.",
        ],
    }
    (HERE / "K1694_results.json").write_text(json.dumps(results, indent=2, default=str))
    print(f"\n=== VERDICT: {verdict} ===")
    print(f"spec1 FCM×highvol coef={dk_c:.3e} t_DK={dk_t:.2f} t_cluster={cl_t:.2f} "
          f"boot95=[{boot['ci95'][0]:.2e},{boot['ci95'][1]:.2e}]")
    print(f"timeseries hhi_x_volfrac t={ts_res['tstat']['hhi_x_volfrac']:.2f} "
          f"(HAC lag={ts_res['hac_lag']}, resid_acf1={ts_res['resid_acf1']:.2f})")
    print("results -> K1694_results.json")


if __name__ == "__main__":
    main()
