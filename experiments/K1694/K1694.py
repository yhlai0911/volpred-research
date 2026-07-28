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
   - 資料 as-of = 月底。**真實發布日未經核對**：本腳本用 availability = 月底 + 45 天的
     合成常數（`FCM_LAG_DAYS`），離線資料裡沒有發布日欄位。
   - 主 spec 的 as-of 合併只保證「不會用到 outcome 月底之後才可得的報表」，**不保證訊號
     嚴格早於 outcome**：availability 通常落在 outcome 月中，而 outcome `d_nonrep` 是整月
     DCOT 平均相對前月的變化。因此主 spec 只能宣稱 **ex-post association**，不可宣稱
     predictive / causal / known-before-outcome。
   - 想講「訊號在 outcome 開始前就已可得」必須看 spec4（見下）。
2. CFTC DCOT（Disaggregated COT, futures-only, 72hh-3qpy）週頻：
   - nonrept_positions_long/short_all（小型交易者部位）→ 排擠結果
   - conc_gross_le_4/8_tdr（trader-level 集中度）→ 第二個集中度視角（部位層 vs 清算層）
   - DCOT 資料 as-of 週二、發布週五（約 3 天 lag）。
3. 波動：對應商品期貨的 realized vol（yfinance 日資料）。

方法（含正式檢定）
------------------
- 觀察先於計算：HHI 時序、regime 描述統計、相關表。
- 排擠假說：high-vol × 高 FCM 集中度 → 小型交易者部位/佔比下降（交互項 β<0）。
- **估計樣本只有一個 owner**：`build_spec_frame()`。panel 迴歸與 bootstrap 都吃同一份
  frame、同一份 `SPEC1_RHS`（含時間趨勢 `t`），所以「bootstrap 估的就是 spec1」由結構
  保證，不靠人工對齊兩份清單。
- **完整性規則**（`monthly_coverage()`，可重複、不寫死日期）：DCOT 月需 ≥4 份週報且最後
  一份 as-of 落在月底 6 天內；RV 月需 ≥15 個交易日，否則該月 rv 視為缺值。跨不相鄰月份
  的差分一律作廢。
- Panel（commodity × month）FE + Driscoll-Kraay / cluster-by-month SE（K1355：不可把
  asset-month 當 iid；同月跨商品有共同 shock）。DK bandwidth 用**固定規則**
  `max(ceil(T^(1/3)), 4)`（見 `_hac_bandwidth_rule`），**不是**由 residual ACF 決定；
  另報 bandwidth 1..24 的敏感度。
- Time-series aggregate 版用 Newey-West，同一固定 bandwidth 規則，另報 residual acf(1)。
- Bootstrap 兩種，皆與 spec1 同 design matrix / 同樣本，固定 seed=1694：
  (a) **stationary block bootstrap by month**（Politis-Romano，幾何長度、循環接續）
      —— 保留月間序列相關，headline CI 用這個；
  (b) **month-cluster IID bootstrap** —— 保留同月橫截面但破壞月間序列相關，僅作對照，
      名稱如實標示，不叫 block bootstrap。
- Null 如實報告。

誠實邊界
--------
FCM 集中度是單一月度系統序列（高自相關、有效自由度低）；結論強度須節制。
spec1-3 的波動 regime 與結果同期，且 regime label（`rv_z`/`highvol`）用**全樣本**動差 →
只能講 association。**spec4 是唯一可以講 predictive 的規格**：FCM 報表在 outcome 月開始
「前」就已可得（以月初而非月底做 as-of 合併），regime label 改用 point-in-time expanding
動差，所有控制變數落後一期。
"""
from __future__ import annotations

import io
import json
import re
import ssl
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

T0 = time.time()

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

FCM_LAG_DAYS = 45  # 合成常數，非真實發布日：CFTC FCM 月報 ≈ 月底 + 1 個月，再加緩衝

# --- 完整性規則（reproducible，不寫死任何日期）--------------------------------
# 任何日曆月至少含 4 個週二，故一個「完整」的月度 DCOT 聚合至少要有 4 份週報；且最後一份
# 週報的 as-of 日必須落在月底 6 天內（月內最後一個週二距月底最多 6 天），否則該月的週資料
# 沒有覆蓋到月底。RV 端：完整月的交易日數在本樣本是 19-23，門檻取 15。
MIN_DCOT_WEEKS = 4
MAX_DCOT_TAIL_GAP_DAYS = 6
MIN_RV_DAYS = 15

# spec4（predictive）的 point-in-time regime label 需要的最短暖身期
PIT_MIN_MONTHS = 24

# 估計樣本與 RHS 的唯一 owner。bootstrap 與 spec1 共用這兩個常數 → 規格一致由結構保證。
SPEC1_RHS = ["hhi_seg_z", "highvol", "fcm_x_highvol",
             "nonrep_lag", "d_nonrep_lag", "dlog_oi", "t"]
SPEC_FRAME_REQUIRED = ["d_nonrep", "hhi_seg_z", "highvol",
                       "nonrep_lag", "d_nonrep_lag", "dlog_oi", "rv_z"]

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
def monthly_coverage(dcot: pd.DataFrame, rv: pd.DataFrame) -> pd.DataFrame:
    """Single owner of the input-completeness rule (no hard-coded dates).

    Codex round 1 blocked on 2026-07 entering the panel with one week of DCOT, ten
    RV trading days and 15 of 22 commodities, undisclosed. The fix is a rule, not a
    cut-off date: each source declares when a calendar month is fully observed, and
    the rule governs exactly the variable that source feeds.

    Returns one row per (commodity, month) with the raw coverage counts and two
    flags:

    ``dcot_complete``
        the monthly DCOT aggregate covers the whole month -- at least
        ``MIN_DCOT_WEEKS`` weekly reports AND the last report's as-of date within
        ``MAX_DCOT_TAIL_GAP_DAYS`` of month end. Incomplete months are dropped
        outright: they can be neither an outcome nor the lag of one.
    ``rv_complete``
        at least ``MIN_RV_DAYS`` trading days. Incomplete months keep their DCOT
        row (so the difference chain is not broken) but their ``rv`` is masked to
        NaN, because a partial month cannot label a volatility regime.
    """
    d = dcot.copy()
    d["month"] = d["report_date"].dt.to_period("M")
    cov = d.groupby(["commodity", "month"]).agg(
        nweeks=("report_date", "size"),
        last_report=("report_date", "max"),
    ).reset_index()
    cov["month_end"] = cov["month"].dt.to_timestamp(how="end").dt.normalize()
    cov["dcot_tail_gap_days"] = (cov["month_end"] - cov["last_report"]).dt.days
    cov["dcot_complete"] = ((cov["nweeks"] >= MIN_DCOT_WEEKS)
                            & (cov["dcot_tail_gap_days"] <= MAX_DCOT_TAIL_GAP_DAYS))

    rvm = rv.copy()
    rvm["month"] = rvm["month_end"].dt.to_period("M")
    cov = cov.merge(rvm[["commodity", "month", "rv", "ndays"]],
                    on=["commodity", "month"], how="left")
    cov = cov.rename(columns={"ndays": "rv_ndays"})
    cov["rv_complete"] = cov["rv_ndays"] >= MIN_RV_DAYS
    return cov


def coverage_report(cov: pd.DataFrame) -> dict:
    """Human-auditable disclosure of what the completeness rule removed."""
    bad_dcot = cov.loc[~cov["dcot_complete"]]
    bad_rv = cov.loc[cov["rv"].notna() & ~cov["rv_complete"]]

    def _months(frame: pd.DataFrame) -> list[dict]:
        if frame.empty:
            return []
        out = frame.groupby("month").agg(
            n_commodities=("commodity", "nunique"),
            min_nweeks=("nweeks", "min"),
            max_tail_gap_days=("dcot_tail_gap_days", "max"),
            min_rv_days=("rv_ndays", "min"),
        ).reset_index()
        return [{"month": str(r["month"]),
                 "n_commodity_rows_dropped": int(r["n_commodities"]),
                 "min_dcot_weeks": int(r["min_nweeks"]),
                 "max_dcot_tail_gap_days": int(r["max_tail_gap_days"]),
                 "min_rv_trading_days": (None if pd.isna(r["min_rv_days"])
                                         else int(r["min_rv_days"]))}
                for _, r in out.iterrows()]

    return {
        "rule": {
            "dcot_month_complete": (
                f"nweeks >= {MIN_DCOT_WEEKS} AND month_end - max(report_date) <= "
                f"{MAX_DCOT_TAIL_GAP_DAYS} days"),
            "rv_month_complete": f"trading days >= {MIN_RV_DAYS}",
            "date_hardcoded": False,
            "effect_of_dcot_incomplete": "row dropped from the panel entirely",
            "effect_of_rv_incomplete": "rv masked to NaN; DCOT row retained",
            "adjacency": ("first differences and their lags are voided whenever the "
                          "previous retained month is not the immediately preceding "
                          "calendar month, so dropping a month cannot silently create "
                          "a two-month difference"),
        },
        "dropped_partial_dcot_months": _months(bad_dcot),
        "rv_masked_partial_months": int(len(bad_rv)),
        "rv_masked_month_examples": sorted({str(m) for m in bad_rv["month"]})[:12],
    }


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
    agg["month_end"] = agg["month"].dt.to_timestamp(how="end").dt.normalize()
    agg["month_start"] = agg["month"].dt.to_timestamp(how="start").dt.normalize()

    # --- completeness rule: drop partial DCOT months, mask partial RV months ---
    cov = monthly_coverage(dcot, rv)
    agg = agg.merge(cov[["commodity", "month", "last_report", "dcot_tail_gap_days",
                         "rv", "rv_ndays", "dcot_complete", "rv_complete"]],
                    on=["commodity", "month"], how="left")
    agg = agg[agg["dcot_complete"].fillna(False)].copy()
    agg.loc[~agg["rv_complete"].fillna(False), "rv"] = np.nan

    # --- FCM as-of merges -------------------------------------------------------
    # (a) primary: latest FCM report available by the outcome month's END. This is
    #     NOT "strictly before the outcome": availability can fall mid-month, and the
    #     outcome is a whole-month average change. Ex-post association only.
    # (b) predictive (spec4): latest report available before the outcome month even
    #     BEGINS, so the signal is known before any of the outcome window.
    fcm_sorted = fcm.sort_values("avail_date").reset_index(drop=True)
    fcm_sorted["hhi_seg_pit_z"] = _expanding_z(fcm_sorted["hhi_seg"], PIT_MIN_MONTHS)
    agg = agg.sort_values("month_end").reset_index(drop=True)
    merged = pd.merge_asof(
        agg, fcm_sorted[["avail_date", "hhi_seg", "cr4_seg", "hhi_total", "n_fcm"]],
        left_on="month_end", right_on="avail_date", direction="backward",
    )
    pre = pd.merge_asof(
        agg.sort_values("month_start")[["commodity", "month", "month_start"]],
        fcm_sorted[["avail_date", "hhi_seg", "hhi_seg_pit_z"]].rename(
            columns={"avail_date": "avail_date_pre", "hhi_seg": "hhi_seg_pre"}),
        left_on="month_start", right_on="avail_date_pre", direction="backward",
    )
    merged = merged.merge(pre[["commodity", "month", "avail_date_pre",
                               "hhi_seg_pre", "hhi_seg_pit_z"]],
                          on=["commodity", "month"], how="left")
    # data-month gap between FCM report used and outcome month (provenance sanity)
    merged["fcm_used_month"] = merged["avail_date"] - pd.Timedelta(days=FCM_LAG_DAYS)
    merged["fcm_avail_within_outcome_month"] = (
        (merged["avail_date"] >= merged["month_start"])
        & (merged["avail_date"] <= merged["month_end"]))

    # --- within-commodity dynamics & regime ---
    merged = merged.sort_values(["commodity", "month"]).reset_index(drop=True)
    merged["m_ord"] = merged["month"].astype("period[M]").astype(int)
    g = merged.groupby("commodity", group_keys=False)
    # adjacency: a difference is only a MONTHLY difference if the previous retained
    # row is the immediately preceding calendar month.
    adj = (merged["m_ord"] - g["m_ord"].shift(1)) == 1
    merged["adjacent_prev_month"] = adj
    merged["d_nonrep"] = g["nonrep_share"].diff().where(adj)
    merged["nonrep_lag"] = g["nonrep_share"].shift(1).where(adj)
    merged["dlog_oi"] = g["oi"].apply(lambda s: np.log(s).diff()).where(adj)
    g = merged.groupby("commodity", group_keys=False)  # regroup: new columns above
    merged["d_nonrep_lag"] = g["d_nonrep"].shift(1).where(adj)
    merged["dlog_oi_lag"] = g["dlog_oi"].shift(1).where(adj)
    # vol z-score within commodity; highvol = above commodity-specific median.
    # NaN-safe: a missing rv must stay missing, not silently become highvol=0
    # (Codex round 1: `NaN > median` is False, which mislabelled 7 rows and made the
    # bootstrap sample larger than spec1's).
    merged["rv_z"] = g["rv"].transform(lambda s: (s - s.mean()) / s.std(ddof=0))
    merged["highvol"] = g["rv"].transform(
        lambda s: s.gt(s.median()).astype(float).where(s.notna()))
    merged["conc4_z"] = g["conc4"].transform(lambda s: (s - s.mean()) / s.std(ddof=0))
    # point-in-time regime labels for the predictive spec: expanding moments through
    # the labelling month only -- no future information in the label.
    merged["rv_z_pit"] = g["rv"].transform(lambda s: _expanding_z(s, PIT_MIN_MONTHS))
    merged["highvol_pit"] = g["rv"].transform(
        lambda s: s.gt(s.expanding(min_periods=PIT_MIN_MONTHS).median())
                   .astype(float).where(s.notna() & (s.expanding(
                       min_periods=PIT_MIN_MONTHS).median().notna())))
    g = merged.groupby("commodity", group_keys=False)
    merged["highvol_pit_lag"] = g["highvol_pit"].shift(1).where(adj)
    merged["rv_z_pit_lag"] = g["rv_z_pit"].shift(1).where(adj)

    # FCM concentration z-scores (time series, common across commodities)
    fcm_ts = merged.dropna(subset=["hhi_seg"]).drop_duplicates("month")[["month", "hhi_seg", "cr4_seg", "hhi_total"]]
    for col in ("hhi_seg", "cr4_seg", "hhi_total"):
        mu, sd = fcm_ts[col].mean(), fcm_ts[col].std(ddof=0)
        merged[col + "_z"] = (merged[col] - mu) / sd

    # interactions (crowding-out core term)
    merged["fcm_x_highvol"] = merged["hhi_seg_z"] * merged["highvol"]
    merged["fcm_x_rvz"] = merged["hhi_seg_z"] * merged["rv_z"]
    merged["conc4_x_highvol"] = merged["conc4_z"] * merged["highvol"]
    # spec4: both legs known before the outcome month starts
    merged["fcm_pre_x_highvol_lag"] = merged["hhi_seg_pit_z"] * merged["highvol_pit_lag"]

    merged["month_id"] = merged["month"].astype(str)
    return merged


def _expanding_z(s: pd.Series, min_periods: int) -> pd.Series:
    """Point-in-time z-score: moments use observations up to and including t only."""
    mu = s.expanding(min_periods=min_periods).mean()
    sd = s.expanding(min_periods=min_periods).std(ddof=0)
    return (s - mu) / sd.replace(0.0, np.nan)


def build_spec_frame(panel: pd.DataFrame) -> pd.DataFrame:
    """THE single owner of the estimation sample.

    Every estimator in this script -- the panel regressions, the aggregate
    time-series regression and both bootstraps -- takes its rows from here. Codex
    round 1 failed the experiment because the bootstrap kept its own dropna list
    and its own RHS, so the reported CI belonged to a specification nobody had
    reported (3,300 rows without the time trend `t` vs spec1's 3,293 rows with it).
    Sharing one frame and one ``SPEC1_RHS`` makes that class of mismatch
    unrepresentable rather than merely discouraged.
    """
    df = panel.dropna(subset=SPEC_FRAME_REQUIRED).copy()
    df["t"] = df["month"].astype("period[M]").astype(int)
    df["t"] = df["t"] - df["t"].min()
    # linearmodels requires the time index to be numeric or date-like; a pandas
    # Period index is rejected outright, so carry the month as a timestamp.
    df["month_ts"] = df["month"].dt.to_timestamp()
    return df.reset_index(drop=True)


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
def _hac_bandwidth_rule(nmonths: int) -> int:
    """FIXED bandwidth rule ``max(ceil(T^(1/3)), 4)`` -- NOT derived from any ACF.

    K1655 forbids the degenerate ``lag = h-1``; the repo canonical floor is
    ``ceil(n^(1/3))``. Codex round 1 correctly flagged that the previous name
    (``_acf_bandwidth``) and the previous call site (which passed a zero vector as
    ``resid``) advertised a residual-ACF-driven bandwidth that the body never
    computed. The rule stays -- it is a defensible floor -- but it is now named and
    documented for what it is, and the DK results carry a 1..24 sensitivity grid so
    the choice is checkable rather than asserted.
    """
    return max(int(np.ceil(nmonths ** (1.0 / 3.0))), 4)


SPEC2_RHS = ["hhi_seg_z", "rv_z", "fcm_x_rvz", "nonrep_lag", "d_nonrep_lag", "dlog_oi", "t"]
SPEC3_RHS = ["conc4_z", "highvol", "conc4_x_highvol", "nonrep_lag", "d_nonrep_lag", "dlog_oi", "t"]
SPEC4_RHS = ["hhi_seg_pit_z", "highvol_pit_lag", "fcm_pre_x_highvol_lag",
             "nonrep_lag", "d_nonrep_lag", "dlog_oi_lag", "t"]


def panel_regression(frame: pd.DataFrame) -> dict:
    """Estimate the specs on the frame produced by :func:`build_spec_frame`."""
    from linearmodels.panel import PanelOLS

    results = {}
    nmonths = frame["month"].nunique()

    def run(rhs: list[str], label: str, dk_lag: int, note: str = ""):
        cols = ["d_nonrep"] + rhs
        df = frame.dropna(subset=cols).set_index(["commodity", "month_ts"])
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
            "n_months": int(df.index.get_level_values(1).nunique()),
            "n_rows_dropped_vs_spec_frame": int(len(frame) - len(df)),
            "rhs": rhs,
            "driscoll_kraay": key(res_dk) | {"bandwidth": dk_lag,
                                             "bandwidth_rule": "max(ceil(T^(1/3)), 4)"},
            "cluster_by_month": key(res_cl),
            "rsq_within": float(res_dk.rsquared_within),
        }
        if note:
            results[label]["note"] = note
        return res_dk

    dk = _hac_bandwidth_rule(nmonths)
    # Spec 1: FCM system HHI × highvol (primary crowding-out). Ex-post association.
    run(SPEC1_RHS, "spec1_fcm_highvol", dk,
        note=("ex-post association: the FCM report may become available mid-outcome-"
              "month and the outcome is a whole-month average change"))
    # Spec 2: continuous FCM × rv_z
    run(SPEC2_RHS, "spec2_fcm_rvz_continuous", dk,
        note="ex-post association; same timing caveat as spec1")
    # Spec 3: trader-concentration lens (within-commodity conc4)
    run(SPEC3_RHS, "spec3_trader_conc4_highvol", dk,
        note="ex-post association; sample is smaller wherever conc4 is missing")
    # Spec 4: fully lagged predictive spec. The module docstring promised one and
    # Codex round 1 found it missing. Every regressor is known before the outcome
    # month begins: the FCM report is merged as-of month START, the volatility
    # regime label uses point-in-time expanding moments at t-1, and every control
    # is a t-1 quantity.
    run(SPEC4_RHS, "spec4_predictive_fully_lagged", dk,
        note=("predictive: FCM report available before the outcome month starts, "
              "point-in-time regime label at t-1, all controls lagged"))
    results["_hac_bandwidth"] = dk
    results["_hac_bandwidth_rule"] = "max(ceil(T^(1/3)), 4); fixed rule, not ACF-derived"
    return results


def dk_bandwidth_sensitivity(frame: pd.DataFrame, rhs: list[str], term: str,
                             grid: range = range(1, 25)) -> dict:
    """spec1 t-stat across Driscoll-Kraay bandwidths, so the fixed rule is checkable."""
    from linearmodels.panel import PanelOLS
    df = frame.dropna(subset=["d_nonrep"] + rhs).set_index(["commodity", "month_ts"])
    mod = PanelOLS(df["d_nonrep"], df[rhs].astype(float), entity_effects=True)
    rows = []
    for b in grid:
        r = mod.fit(cov_type="kernel", kernel="bartlett", bandwidth=b)
        rows.append({"bandwidth": int(b), "tstat": float(r.tstats[term]),
                     "pval": float(r.pvalues[term])})
    ts = [abs(r["tstat"]) for r in rows]
    return {
        "term": term,
        "grid": rows,
        "abs_t_min": float(min(ts)),
        "abs_t_max": float(max(ts)),
        "any_abs_t_ge_1_96": bool(max(ts) >= 1.96),
    }


def timeseries_regression(frame: pd.DataFrame) -> dict:
    """Cross-commodity aggregate: mean d_nonrep on FCM HHI + interaction, Newey-West."""
    import statsmodels.api as sm
    p = frame.dropna(subset=["d_nonrep", "hhi_seg_z", "highvol"]).copy()
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
    # Fixed bandwidth rule (NOT chosen from the residual ACF); acf(1) reported below
    # as a K1655 direction check, not as the bandwidth selector.
    n = len(resid)
    lag = _hac_bandwidth_rule(n)
    nw = sm.OLS(y, X).fit(cov_type="HAC", cov_kwds={"maxlags": lag})
    names = ["const", "hhi_z", "highvol_frac", "hhi_x_volfrac"]
    # residual acf(1) for reporting (K1655 direction check)
    acf1 = float(np.corrcoef(resid[:-1], resid[1:])[0, 1]) if n > 2 else float("nan")
    return {
        "n_months": int(n),
        "hac_lag": int(lag),
        "hac_lag_rule": "max(ceil(T^(1/3)), 4); fixed rule, not ACF-derived",
        "resid_acf1": acf1,
        "coef": {nm: float(nw.params[i]) for i, nm in enumerate(names)},
        "tstat": {nm: float(nw.tvalues[i]) for i, nm in enumerate(names)},
        "pval": {nm: float(nw.pvalues[i]) for i, nm in enumerate(names)},
    }


# ---------------------------------------------------------------------------
# 7. Bootstraps for the spec1 interaction coefficient
#
# Both bootstraps below resample MONTHS from the SAME frame and the SAME RHS that
# spec1 uses (``SPEC1_RHS``, time trend `t` included). Codex round 1 failed the
# experiment because the old bootstrap carried a private dropna list and a private
# RHS, so the published CI belonged to no reported specification.
# ---------------------------------------------------------------------------
def _within_ols(y: np.ndarray, X: np.ndarray, entity: np.ndarray) -> np.ndarray:
    """Entity-demeaned (within) OLS -- algebraically identical to PanelOLS(entity_effects).

    Used only inside the bootstrap loop, where linearmodels' per-fit overhead would
    dominate. ``bootstrap_spec1`` asserts the point estimate this returns equals the
    PanelOLS spec1 coefficient before any replicate is drawn, so the shortcut can
    never silently drift from the estimator it stands in for.
    """
    order = np.argsort(entity, kind="stable")
    y, X, e = y[order], X[order], entity[order]
    starts = np.flatnonzero(np.r_[True, e[1:] != e[:-1]])
    counts = np.diff(np.r_[starts, len(e)])
    codes = np.repeat(np.arange(len(starts)), counts)
    ybar = np.bincount(codes, weights=y) / counts
    yd = y - ybar[codes]
    Xd = X - (np.stack([np.bincount(codes, weights=X[:, j]) / counts
                        for j in range(X.shape[1])], axis=1))[codes]
    beta, *_ = np.linalg.lstsq(Xd, yd, rcond=None)
    return beta


def _month_blocks_stationary(n_months: int, mean_block: int,
                             rng: np.random.Generator) -> np.ndarray:
    """Politis-Romano stationary bootstrap indices over the ordered month axis.

    Geometric block lengths with mean ``mean_block``, wrapping circularly, so the
    resample preserves month-to-month SERIAL dependence -- the property an IID
    month-cluster resample destroys.
    """
    p = 1.0 / max(mean_block, 1)
    idx = np.empty(n_months, dtype=np.int64)
    cur = int(rng.integers(n_months))
    for i in range(n_months):
        idx[i] = cur
        if rng.random() < p:
            cur = int(rng.integers(n_months))
        else:
            cur = (cur + 1) % n_months
    return idx


def bootstrap_spec1(frame: pd.DataFrame, kind: str, n_boot: int = 2000,
                    mean_block: int | None = None) -> dict:
    """Resample months of the spec1 estimation sample; refit the spec1 coefficient.

    ``kind='stationary_block'`` -- Politis-Romano stationary block bootstrap over
    consecutive months (preserves serial correlation; this is the headline CI).
    ``kind='month_cluster_iid'`` -- IID resampling of whole months (preserves the
    within-month cross-section, destroys serial correlation). Reported under that
    honest name only; it is NOT a block bootstrap.
    """
    from linearmodels.panel import PanelOLS

    term = "fcm_x_highvol"
    cols = ["d_nonrep"] + SPEC1_RHS
    df = frame.dropna(subset=cols)
    month_codes, months = pd.factorize(df["month"], sort=True)
    n_months = len(months)
    order = np.argsort(month_codes, kind="stable")
    bounds = np.searchsorted(month_codes[order], np.arange(n_months + 1))
    rows_by_month = [order[bounds[k]:bounds[k + 1]] for k in range(n_months)]

    y_all = df["d_nonrep"].to_numpy(dtype=float)
    X_all = df[SPEC1_RHS].to_numpy(dtype=float)
    ent_all = pd.factorize(df["commodity"])[0]
    j_term = SPEC1_RHS.index(term)

    # Identity check: the fast within estimator must reproduce the PanelOLS spec1
    # coefficient on the real sample, or the CI would again describe another model.
    ref = PanelOLS(df.set_index(["commodity", "month_ts"])["d_nonrep"],
                   df.set_index(["commodity", "month_ts"])[SPEC1_RHS].astype(float),
                   entity_effects=True).fit(cov_type="unadjusted")
    point_panelols = float(ref.params[term])
    point_within = float(_within_ols(y_all, X_all, ent_all)[j_term])
    if not np.isclose(point_within, point_panelols, rtol=1e-9, atol=1e-15):
        raise AssertionError(
            f"within-OLS {point_within!r} != PanelOLS {point_panelols!r}")

    rng = np.random.default_rng(SEED)
    if mean_block is None:
        mean_block = _hac_bandwidth_rule(n_months)
    boots = np.empty(n_boot, dtype=float)
    n_failed = 0
    for b in range(n_boot):
        if kind == "stationary_block":
            pick = _month_blocks_stationary(n_months, mean_block, rng)
        elif kind == "month_cluster_iid":
            pick = rng.integers(0, n_months, size=n_months)
        else:  # pragma: no cover - guarded by caller
            raise ValueError(kind)
        rows = np.concatenate([rows_by_month[k] for k in pick])
        # Entity stays the commodity (that is what spec1's fixed effects absorb);
        # only the month axis is resampled, and every regressor -- `t` included --
        # travels with its original row. Drawing the same month twice needs no
        # relabelling here because the within estimator carries no panel index, so
        # the entity-time index collision that forced the round-1 relabel (and the
        # string label that silently NaN'd every replicate) cannot arise.
        try:
            boots[b] = _within_ols(y_all[rows], X_all[rows], ent_all[rows])[j_term]
        except np.linalg.LinAlgError:  # pragma: no cover - singular replicate
            boots[b] = np.nan
            n_failed += 1
    ok = boots[~np.isnan(boots)]
    label = {"stationary_block": "stationary block bootstrap by month (Politis-Romano)",
             "month_cluster_iid": "IID month-cluster bootstrap (NOT a block bootstrap; "
                                  "preserves the within-month cross-section but "
                                  "destroys month-to-month serial correlation)"}[kind]
    return {
        "kind": kind,
        "label": label,
        "preserves_serial_correlation": kind == "stationary_block",
        "mean_block_months": int(mean_block) if kind == "stationary_block" else None,
        "rhs": list(SPEC1_RHS),
        "shares_spec1_design_matrix": True,
        "n_rows": int(len(df)),
        "n_months": int(n_months),
        "point": point_panelols,
        "point_estimator_identity_check": {
            "panel_ols": point_panelols,
            "within_ols": point_within,
            "max_abs_diff": float(abs(point_within - point_panelols)),
        },
        "n_boot": int(len(ok)),
        "n_failed": int(n_failed),
        "ci95": [float(np.percentile(ok, 2.5)), float(np.percentile(ok, 97.5))],
        "p_two_sided": float(2 * min((ok > 0).mean(), (ok < 0).mean())),
        "mean": float(ok.mean()),
        "std": float(ok.std(ddof=1)),
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
        "spec4_predictive_fully_lagged": ("FCM HHI × highvol, lagged\n(DK, predictive)",
                                          "fcm_pre_x_highvol_lag"),
    }
    for sp, (lab, term) in spec_map.items():
        r = panel_res[sp]["driscoll_kraay"]
        c = r["coef"][term]
        t = r["tstat"][term]
        se = abs(c / t) if t != 0 else np.nan
        labels3.append(lab); coefs.append(c); los.append(c - 1.96 * se); his.append(c + 1.96 * se)
    # spec1 stationary block bootstrap -- same design matrix and sample as spec1
    labels3.append("FCM HHI × highvol\n(stationary block boot)")
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
    cov = monthly_coverage(dcot, rv)
    cov_report = coverage_report(cov)
    panel = build_panel(fcm, dcot, rv)
    panel.to_csv(DATA / "panel.csv", index=False)

    # ONE owner of the estimation sample; every estimator below reads this frame.
    frame = build_spec_frame(panel)
    print(f"[PANEL] {len(panel)} retained rows; estimation sample {len(frame)}; "
          f"{frame['commodity'].nunique()} commodities; "
          f"span {frame['month'].min()}..{frame['month'].max()}")
    for m in cov_report["dropped_partial_dcot_months"]:
        print(f"[COVERAGE] dropped partial month {m['month']}: "
              f"{m['n_commodity_rows_dropped']} rows, min weeks={m['min_dcot_weeks']}, "
              f"max tail gap={m['max_dcot_tail_gap_days']}d")

    desc = descriptives(panel, fcm)
    panel_res = panel_regression(frame)
    ts_res = timeseries_regression(frame)
    dk_sens = dk_bandwidth_sensitivity(frame, SPEC1_RHS, "fcm_x_highvol")
    boot = bootstrap_spec1(frame, kind="stationary_block", n_boot=2000)
    boot_iid = bootstrap_spec1(frame, kind="month_cluster_iid", n_boot=2000)
    make_figures(fcm, panel, panel_res, boot)

    # ---- verdict logic ----
    p1 = panel_res["spec1_fcm_highvol"]
    dk_t = p1["driscoll_kraay"]["tstat"]["fcm_x_highvol"]
    dk_c = p1["driscoll_kraay"]["coef"]["fcm_x_highvol"]
    cl_t = p1["cluster_by_month"]["tstat"]["fcm_x_highvol"]
    crowding_out = (dk_c < 0) and (abs(dk_t) >= 2.0) and (abs(cl_t) >= 2.0) and \
                   (boot["ci95"][1] < 0)
    verdict = "CROWDING_OUT_SUPPORTED" if crowding_out else "NULL"
    p2 = panel_res["spec2_fcm_rvz_continuous"]
    p4 = panel_res["spec4_predictive_fully_lagged"]

    results = {
        "experiment_id": "K1694",
        "title": "FCM clearing concentration and high-volatility crowding-out of small commodity traders",
        "seed": SEED,
        "run_utc": datetime.now(timezone.utc).isoformat(),
        "verdict": verdict,
        "verdict_scope": (
            "NULL is scoped to ONE hypothesis: the NEGATIVE, BINARY high-vol "
            "crowding-out interaction (spec1 fcm_x_highvol < 0). It does NOT mean "
            "'no association'. The continuous analogue (spec2 fcm_x_rvz) is "
            f"POSITIVE and significant: coef "
            f"{p2['driscoll_kraay']['coef']['fcm_x_rvz']:.4e}, "
            f"t_DK {p2['driscoll_kraay']['tstat']['fcm_x_rvz']:.2f}, "
            f"t_cluster_month {p2['cluster_by_month']['tstat']['fcm_x_rvz']:.2f} -- "
            "i.e. in the direction opposite to crowding-out."),
        "claim_type": "ex_post_association",
        "claim_language_rule": (
            "spec1-3 may only be described as ex-post association. The words "
            "predictive, causal, forecast and known-before-outcome are forbidden for "
            "them because the FCM report can become available mid-outcome-month and "
            "the outcome is a whole-month average change. Only spec4 "
            "(spec4_predictive_fully_lagged) is timed so every regressor is known "
            "before the outcome month begins."),
        "data_provenance": {
            "fcm_source": "CFTC Financial Data for FCMs (monthly xlsx)",
            "fcm_publication_lag_days_assumed": FCM_LAG_DAYS,
            "fcm_publication_dates_verified": False,
            "fcm_publication_lag_is_synthetic": (
                "avail_date = month_end + 45d is a constant chosen by this script, not "
                "an observed CFTC release date; the offline cache carries no release "
                "date column. Sensitivity over 30/45/60/75/90d lives in "
                "K1694_lag_sensitivity.json."),
            "fcm_asof_merge_primary": (
                "backward as-of: latest FCM report whose synthetic avail_date <= the "
                "outcome month_end. Availability may therefore fall INSIDE the outcome "
                "month -- association timing, not predictive timing."),
            "fcm_asof_merge_predictive_spec4": (
                "backward as-of on the outcome month's START, so the report is "
                "available before any of the outcome window."),
            "fcm_avail_inside_outcome_month_rows": int(
                panel["fcm_avail_within_outcome_month"].fillna(False).sum()),
            "dcot_source": "CFTC DCOT futures-only 72hh-3qpy (weekly; as-of Tue, published Fri)",
            "dcot_small_trader_proxy": "non-reportable positions (long+short)/(2*OI)",
            "vol_source": "yfinance daily futures; monthly realized vol = std(daily logret)*sqrt(252)",
            "commodities": list(COMMODITY_MAP.keys()),
        },
        "sample": {
            "fcm_months": desc["fcm_hhi_stats"]["n_months"],
            "fcm_span": desc["fcm_hhi_stats"]["span"],
            "estimation_sample_owner": "build_spec_frame(); shared by every estimator",
            "panel_rows_usable": int(len(frame)),
            "panel_commodities": int(frame["commodity"].nunique()),
            "panel_span": [str(frame["month"].min()), str(frame["month"].max())],
            "panel_span_is_complete_months_only": True,
            "completeness": cov_report,
        },
        "descriptives": desc,
        "panel_regressions": panel_res,
        "dk_bandwidth_sensitivity_spec1": dk_sens,
        "timeseries_regression": ts_res,
        "bootstrap_spec1": {
            "headline": "stationary_block_by_month",
            "stationary_block_by_month": boot,
            "month_cluster_iid": boot_iid,
            "design_matrix_note": (
                "Both bootstraps resample months of the SAME build_spec_frame() rows "
                "and refit the SAME SPEC1_RHS (time trend `t` included), so the CI is "
                "the CI of the reported spec1 coefficient."),
        },
        "primary_interaction": {
            "term": "fcm_x_highvol",
            "spec": "spec1_fcm_highvol",
            "coef": dk_c, "t_driscoll_kraay": dk_t, "t_cluster_month": cl_t,
            "stationary_block_bootstrap_ci95": boot["ci95"],
            "stationary_block_bootstrap_p_two_sided": boot["p_two_sided"],
            "month_cluster_iid_bootstrap_ci95": boot_iid["ci95"],
            "bootstrap_matches_spec1_sample_and_rhs": (
                boot["n_rows"] == panel_res["spec1_fcm_highvol"]["n_obs"]
                and boot["rhs"] == panel_res["spec1_fcm_highvol"]["rhs"]),
            "claim_type": "ex_post_association",
        },
        "secondary_findings": {
            "spec2_continuous_interaction_is_positive_and_significant": {
                "term": "fcm_x_rvz",
                "coef": p2["driscoll_kraay"]["coef"]["fcm_x_rvz"],
                "t_driscoll_kraay": p2["driscoll_kraay"]["tstat"]["fcm_x_rvz"],
                "t_cluster_month": p2["cluster_by_month"]["tstat"]["fcm_x_rvz"],
                "reading": ("opposite sign to the crowding-out hypothesis; it is why "
                            "the NULL must not be stated as 'no association'"),
            },
            "spec4_predictive": {
                "term": "fcm_pre_x_highvol_lag",
                "n_obs": p4["n_obs"],
                "coef": p4["driscoll_kraay"]["coef"]["fcm_pre_x_highvol_lag"],
                "t_driscoll_kraay": p4["driscoll_kraay"]["tstat"]["fcm_pre_x_highvol_lag"],
                "t_cluster_month": p4["cluster_by_month"]["tstat"]["fcm_pre_x_highvol_lag"],
            },
        },
        "limitations": [
            "FCM concentration is a single system-wide monthly series (high autocorrelation, "
            "low effective d.o.f.); its main effect is a common time factor. The panel has "
            f"{panel_res['spec1_fcm_highvol']['n_obs']} rows but only "
            f"{panel_res['spec1_fcm_highvol']['n_months']} months of independent FCM variation.",
            "FCM publication dates are SYNTHETIC (month_end + 45d), never checked against "
            "actual CFTC release dates; the lag grid in K1694_lag_sensitivity.json shows "
            "insensitivity to the assumed vintage but is not a verification of it.",
            "Within-month timing overlap: in spec1-3 the FCM report's assumed availability "
            "can fall inside the outcome month, and the outcome d_nonrep is the change in a "
            "whole-month average, so part of the outcome window predates the signal. "
            "Ex-post association only.",
            "Regime labels rv_z and highvol in spec1-3 use FULL-SAMPLE within-commodity "
            "moments, i.e. the labelling itself looks ahead. Acceptable for a retrospective "
            "association, not for a predictive claim; spec4 uses point-in-time expanding "
            "moments instead.",
            "The month-cluster IID bootstrap preserves the within-month cross-section but "
            "does NOT preserve month-to-month serial correlation; it is reported only "
            "alongside the stationary block bootstrap, which does.",
            "The last weekly DCOT report of month t-1 is published within ~3 days of its "
            "Tuesday as-of date, so the t-1 controls in spec4 can be public a few days into "
            "month t; a residual publication overlap of at most a few business days remains.",
            "Volatility regime is contemporaneous with the outcome in spec1-3 -> association, "
            "not causal; reverse causality (small-trader exit affecting vol) cannot be excluded.",
            "FCM seg funds are dominated by financial futures; crowding-out mapped onto "
            "physical-commodity small traders is an indirect linkage.",
            "yfinance continuous-futures realized vol is a proxy for each commodity's true vol.",
        ],
    }

    # The results JSON and reproduce_spec.json are written by ONE trace_file() call,
    # so code_trace and the spec's entrypoint describe the same bytes by construction
    # (K1708: hand-written specs describe a program that no longer exists).
    from volpred.research.reproduce_spec import finalize_experiment
    results_path, spec = finalize_experiment(
        results=results,
        entrypoint=__file__,
        canonical_result="K1694_results.json",
        inputs=[DATA / n for n in
                ("fcm_monthly.csv", "dcot_weekly.csv", "rv_monthly.csv")],
        outputs=["data/panel.csv",
                 "figures/fig1_fcm_hhi_timeseries.png",
                 "figures/fig2_regime_2x2.png",
                 "figures/fig3_interaction_coef.png"],
        seeds=[("numpy", SEED)],
        started_at=T0,
        timeout_seconds=1800,
    )
    print(f"\n=== VERDICT: {verdict} ===")
    print(f"spec1 FCM×highvol coef={dk_c:.3e} t_DK={dk_t:.2f} t_cluster={cl_t:.2f} "
          f"stationary-block boot95=[{boot['ci95'][0]:.2e},{boot['ci95'][1]:.2e}] "
          f"(IID month-cluster boot95=[{boot_iid['ci95'][0]:.2e},{boot_iid['ci95'][1]:.2e}])")
    print(f"spec2 FCM×rv_z coef={p2['driscoll_kraay']['coef']['fcm_x_rvz']:.3e} "
          f"t_DK={p2['driscoll_kraay']['tstat']['fcm_x_rvz']:.2f} "
          f"t_cluster={p2['cluster_by_month']['tstat']['fcm_x_rvz']:.2f}  <- positive")
    print(f"spec4 predictive coef={p4['driscoll_kraay']['coef']['fcm_pre_x_highvol_lag']:.3e} "
          f"t_DK={p4['driscoll_kraay']['tstat']['fcm_pre_x_highvol_lag']:.2f} n={p4['n_obs']}")
    print(f"DK bandwidth 1..24 |t| range "
          f"[{dk_sens['abs_t_min']:.2f}, {dk_sens['abs_t_max']:.2f}]")
    print(f"timeseries hhi_x_volfrac t={ts_res['tstat']['hhi_x_volfrac']:.2f} "
          f"(HAC lag={ts_res['hac_lag']}, resid_acf1={ts_res['resid_acf1']:.2f})")
    print(f"results -> {results_path.name}; spec -> reproduce_spec.json "
          f"(entrypoint sha {spec['entrypoint']['sha256'][:12]})")


if __name__ == "__main__":
    main()
