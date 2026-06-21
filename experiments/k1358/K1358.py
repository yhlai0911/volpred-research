"""K1358: AI labor exposure x sector ETF volatility.

Question
--------
Do sectors with higher AI labor-income exposure show larger volatility,
downside semivariance, or correlation responses after AI-labor news / labor
market shocks, and does that exposure improve next-week sector ETF RV
forecasts?

This is a free-data proxy experiment:
* AI exposure comes from Felten/Raj/Seamans AIIE industry scores.
* Sector ETF exposure is a hand-mapped NAICS-prefix average, not holdings-level
  constituent labor exposure.
* AI-labor shock is GDELT article-count attention plus BLS/FRED macro labor
  residuals, not firm-level layoff/adoption data.
"""

from __future__ import annotations

import io
import json
import math
import re
import time
import urllib.request
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from xml.etree import ElementTree as ET

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import requests
import yfinance as yf

from volpred.stats.model_evaluation import dm_test, qlike_pointwise


SEED = 42
EXP_ID = "K1358"
EXP_DIR = Path(__file__).resolve().parent
DATA_DIR = EXP_DIR / "data"
RESULTS_PATH = EXP_DIR / "K1358_results.json"
FIG_PATH = EXP_DIR / "K1358_ai_labor_sector_vol.png"

START = "2017-01-01"
END = datetime.now(timezone.utc).strftime("%Y-%m-%d")
OOS_START = pd.Timestamp("2020-01-01")
INIT_TRAIN_MIN = 504
REFIT_EVERY = 252
N_BOOT = 2000

AIOE_XLSX = "https://github.com/AIOE-Data/AIOE/raw/main/AIOE_DataAppendix.xlsx"
GDELT_URL = "https://api.gdeltproject.org/api/v2/doc/doc"
GDELT_QUERY = '("artificial intelligence" OR "generative AI" OR ChatGPT OR automation) (jobs OR layoffs OR workforce OR employment OR labor OR workers)'

SECTORS = {
    "XLB": {"name": "Materials", "prefixes": ["2122", "2123", "321", "322", "325", "326", "327", "331", "332"]},
    "XLE": {"name": "Energy", "prefixes": ["211", "213"]},
    "XLF": {"name": "Financials", "prefixes": ["52"]},
    "XLI": {"name": "Industrials", "prefixes": ["23", "333", "336", "48", "49", "5413", "561"]},
    "XLK": {"name": "Technology", "prefixes": ["334", "5112", "518", "519", "5415"]},
    "XLP": {"name": "Consumer Staples", "prefixes": ["311", "312", "445", "446"]},
    "XLU": {"name": "Utilities", "prefixes": ["221"]},
    "XLV": {"name": "Health Care", "prefixes": ["3254", "621", "622", "623"]},
    "XLY": {"name": "Consumer Discretionary", "prefixes": ["441", "442", "448", "451", "452", "453", "454", "71", "72"]},
    "XLRE": {"name": "Real Estate", "prefixes": ["531"]},
    "XLC": {"name": "Communication Services", "prefixes": ["512", "515", "517", "519", "711"]},
}
ASSETS = list(SECTORS.keys())
TICKERS = ASSETS + ["SPY", "^VIX"]


@dataclass(frozen=True)
class ModelSpec:
    name: str
    features: list[str]


MODELS = [
    ModelSpec("HAR_VIX", ["log_rv_1_lag1", "log_rv_5_lag1", "log_rv_22_lag1", "vix_z_lag1", "spy_rv_5_lag1"]),
    ModelSpec(
        "HAR_VIX_AI_LABOR",
        [
            "log_rv_1_lag1",
            "log_rv_5_lag1",
            "log_rv_22_lag1",
            "vix_z_lag1",
            "spy_rv_5_lag1",
            "ai_news_x_exposure_lag1",
            "labor_x_exposure_lag1",
            "joint_shock_x_exposure_lag1",
        ],
    ),
]


def save_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def rolling_z_past(x: pd.Series, window: int = 252, min_periods: int = 60) -> pd.Series:
    past = x.shift(1)
    mean = past.rolling(window, min_periods=min_periods).mean()
    std = past.rolling(window, min_periods=min_periods).std(ddof=0)
    return ((x - mean) / std.replace(0.0, np.nan)).replace([np.inf, -np.inf], np.nan)


def rolling_z_monthly_past(x: pd.Series, window: int = 60, min_periods: int = 24) -> pd.Series:
    past = x.shift(1)
    mean = past.rolling(window, min_periods=min_periods).mean()
    std = past.rolling(window, min_periods=min_periods).std(ddof=0)
    return ((x - mean) / std.replace(0.0, np.nan)).replace([np.inf, -np.inf], np.nan)


def xlsx_sheet_to_frame(raw: bytes, sheet_name: str) -> pd.DataFrame:
    """Small xlsx reader for this workbook so openpyxl is not required."""
    ns = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
    with zipfile.ZipFile(io.BytesIO(raw)) as zf:
        shared = []
        root = ET.fromstring(zf.read("xl/sharedStrings.xml"))
        for si in root.findall(f"{ns}si"):
            shared.append("".join(t.text or "" for t in si.iter(f"{ns}t")))

        wb = ET.fromstring(zf.read("xl/workbook.xml"))
        rels = ET.fromstring(zf.read("xl/_rels/workbook.xml.rels"))
        relmap = {r.attrib["Id"]: r.attrib["Target"] for r in rels}
        sheet_path = None
        for sheet in wb.find(f"{ns}sheets"):
            if sheet.attrib["name"] == sheet_name:
                rid = sheet.attrib["{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"]
                sheet_path = "xl/" + relmap[rid]
                break
        if sheet_path is None:
            raise ValueError(f"sheet not found: {sheet_name}")

        def col_index(ref: str) -> int:
            letters = re.sub(r"[^A-Z]", "", ref)
            out = 0
            for ch in letters:
                out = out * 26 + ord(ch) - ord("A") + 1
            return out - 1

        def cell_value(cell: ET.Element):
            value = cell.find(f"{ns}v")
            if value is None:
                return None
            text = value.text
            if cell.attrib.get("t") == "s":
                return shared[int(text)]
            return text

        rows = []
        sheet_root = ET.fromstring(zf.read(sheet_path))
        for row in sheet_root.iter(f"{ns}row"):
            vals = {}
            max_col = -1
            for cell in row.findall(f"{ns}c"):
                idx = col_index(cell.attrib["r"])
                vals[idx] = cell_value(cell)
                max_col = max(max_col, idx)
            if max_col >= 0:
                rows.append([vals.get(i) for i in range(max_col + 1)])
    header = rows[0]
    return pd.DataFrame(rows[1:], columns=header)


def load_ai_industry_exposure() -> pd.DataFrame:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    cache = DATA_DIR / "aiie_industry_exposure.csv"
    if cache.exists():
        return pd.read_csv(cache, dtype={"NAICS": str})
    raw_path = DATA_DIR / "AIOE_DataAppendix.xlsx"
    if raw_path.exists():
        raw = raw_path.read_bytes()
    else:
        raw = urllib.request.urlopen(AIOE_XLSX, timeout=90).read()
        raw_path.write_bytes(raw)
    df = xlsx_sheet_to_frame(raw, "Appendix B")
    df = df.rename(columns={"Industry Title": "industry_title"})
    df["NAICS"] = df["NAICS"].astype(str).str.replace(r"\.0$", "", regex=True)
    df["AIIE"] = pd.to_numeric(df["AIIE"], errors="coerce")
    df = df[["NAICS", "industry_title", "AIIE"]].dropna()
    df.to_csv(cache, index=False)
    return df


def sector_exposure() -> pd.DataFrame:
    aiie = load_ai_industry_exposure()
    rows = []
    for ticker, meta in SECTORS.items():
        prefixes = tuple(meta["prefixes"])
        mask = aiie["NAICS"].apply(lambda x: any(str(x).startswith(prefix) for prefix in prefixes))
        sub = aiie[mask].copy()
        rows.append(
            {
                "ticker": ticker,
                "sector_name": meta["name"],
                "ai_labor_exposure": float(sub["AIIE"].mean()),
                "ai_labor_exposure_median": float(sub["AIIE"].median()),
                "n_aiie_industries": int(len(sub)),
                "naics_prefixes": ",".join(meta["prefixes"]),
            }
        )
    out = pd.DataFrame(rows)
    mean = out["ai_labor_exposure"].mean()
    std = out["ai_labor_exposure"].std(ddof=0)
    out["ai_exposure_z"] = (out["ai_labor_exposure"] - mean) / std
    out["exposure_group"] = pd.qcut(out["ai_labor_exposure"], 3, labels=["low", "mid", "high"])
    out.to_csv(DATA_DIR / "sector_ai_exposure.csv", index=False)
    return out


def gdelt_params(start: str, end: str) -> dict[str, str]:
    return {
        "query": GDELT_QUERY,
        "mode": "timelinevolraw",
        "format": "json",
        "STARTDATETIME": start,
        "ENDDATETIME": end,
        "TIMELINESMOOTH": "0",
    }


def fetch_gdelt_ai_labor() -> pd.DataFrame:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    raw_cache = DATA_DIR / "gdelt_ai_labor_timeline_raw.json"
    daily_cache = DATA_DIR / "gdelt_ai_labor_daily.csv"
    if daily_cache.exists():
        return pd.read_csv(daily_cache, parse_dates=["date"]).set_index("date")
    if raw_cache.exists():
        payload = json.loads(raw_cache.read_text(encoding="utf-8"))
    else:
        params = gdelt_params(START.replace("-", "") + "000000", END.replace("-", "") + "000000")
        last_text = ""
        for attempt in range(4):
            if attempt:
                time.sleep(6 * attempt)
            response = requests.get(GDELT_URL, params=params, timeout=90)
            last_text = response.text[:500]
            if response.status_code == 429:
                continue
            response.raise_for_status()
            payload = response.json()
            raw_cache.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            break
        else:
            raise RuntimeError(f"GDELT request failed; last response={last_text}")
    timeline = payload.get("timeline") or payload.get("timelinevolraw")
    if not timeline:
        raise ValueError("GDELT payload has no timeline")
    rows = timeline[0].get("data") or []
    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"], utc=True).dt.tz_localize(None).dt.normalize()
    df["ai_labor_news_count"] = pd.to_numeric(df["value"], errors="coerce")
    df["gdelt_total"] = pd.to_numeric(df["norm"], errors="coerce")
    df["ai_labor_news_share"] = df["ai_labor_news_count"] / df["gdelt_total"].replace(0.0, np.nan)
    df["log_ai_labor_news_share"] = np.log(df["ai_labor_news_share"].clip(lower=1e-12))
    df["ai_labor_news_z"] = rolling_z_past(df["log_ai_labor_news_share"], 252, 60).clip(-8, 8)
    out = df[["date", "ai_labor_news_count", "gdelt_total", "ai_labor_news_share", "ai_labor_news_z"]].dropna()
    out.to_csv(daily_cache, index=False)
    return out.set_index("date")


def fred_series(series_id: str) -> pd.Series:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    cache = DATA_DIR / f"fred_{series_id}.csv"
    url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"
    if cache.exists():
        df = pd.read_csv(cache)
    else:
        df = pd.read_csv(url)
        df.to_csv(cache, index=False)
    df["observation_date"] = pd.to_datetime(df["observation_date"])
    return pd.to_numeric(df[series_id], errors="coerce").set_axis(df["observation_date"]).dropna()


def bls_labor_shock(daily_index: pd.DatetimeIndex) -> pd.DataFrame:
    payems = fred_series("PAYEMS")
    wage = fred_series("CES0500000003")
    emp_change = payems.diff()
    wage_change = np.log(wage / wage.shift(1))
    emp_z = rolling_z_monthly_past(emp_change)
    wage_z = rolling_z_monthly_past(wage_change)
    monthly = pd.DataFrame({"emp_surprise_z": emp_z, "wage_surprise_z": wage_z}).dropna()
    # Approximate public availability: next month plus four business days.
    monthly.index = monthly.index + pd.offsets.MonthBegin(1) + pd.offsets.BDay(4)
    daily = monthly.reindex(monthly.index.union(daily_index)).sort_index().ffill().reindex(daily_index)
    daily["labor_macro_shock"] = daily[["emp_surprise_z", "wage_surprise_z"]].abs().max(axis=1)
    daily.to_csv(DATA_DIR / "bls_fred_labor_shock_daily.csv", index_label="date")
    return daily


def field(raw: pd.DataFrame, name: str, tickers: list[str]) -> pd.DataFrame:
    if isinstance(raw.columns, pd.MultiIndex):
        out = raw[name]
    else:
        out = raw[[name]]
    cols = [ticker for ticker in tickers if ticker in out.columns]
    return out[cols].astype(float)


def load_yfinance() -> dict[str, pd.DataFrame]:
    cache = DATA_DIR / "yfinance_ohlcv.csv"
    if cache.exists():
        raw = pd.read_csv(cache, header=[0, 1], index_col=0, parse_dates=True)
        raw.index = pd.to_datetime(raw.index).tz_localize(None).normalize()
    else:
        raw = yf.download(TICKERS, start=START, end=END, auto_adjust=False, progress=False, threads=True)
        if raw.empty:
            raise RuntimeError("yfinance returned empty data")
        raw.index = pd.to_datetime(raw.index).tz_localize(None).normalize()
        raw.to_csv(cache)
    return {
        "adj_close": field(raw, "Adj Close", TICKERS),
        "close": field(raw, "Close", TICKERS),
        "volume": field(raw, "Volume", TICKERS),
    }


def build_panel() -> tuple[pd.DataFrame, pd.DataFrame]:
    exposure = sector_exposure()
    data = load_yfinance()
    news = fetch_gdelt_ai_labor()
    daily_index = data["adj_close"].index
    labor = bls_labor_shock(daily_index)
    vix = data["close"]["^VIX"]
    vix_z = rolling_z_past(vix)
    spy_ret = np.log(data["adj_close"]["SPY"] / data["adj_close"]["SPY"].shift(1)).replace([np.inf, -np.inf], np.nan)
    spy_rv = spy_ret.pow(2).clip(lower=1e-10)
    spy_rv_5 = spy_rv.rolling(5).mean()

    news_daily = news.reindex(daily_index).ffill()
    shock = pd.DataFrame(index=daily_index)
    shock["ai_labor_news_z"] = news_daily["ai_labor_news_z"]
    shock["labor_macro_shock"] = labor["labor_macro_shock"]
    shock["joint_ai_labor_shock"] = shock["ai_labor_news_z"].clip(lower=0.0) + shock["labor_macro_shock"].fillna(0.0)
    shock["event_shock"] = ((shock["ai_labor_news_z"] >= 2.0) | (shock["labor_macro_shock"] >= 1.5)).astype(float)

    frames = []
    exp_map = exposure.set_index("ticker").to_dict(orient="index")
    for asset in ASSETS:
        if asset not in data["adj_close"]:
            continue
        adj = data["adj_close"][asset]
        ret = np.log(adj / adj.shift(1)).replace([np.inf, -np.inf], np.nan)
        rv = ret.pow(2).clip(lower=1e-10)
        downside = ret.clip(upper=0.0).pow(2)
        fwd5_rv = sum(rv.shift(-i) for i in range(1, 6)).clip(lower=1e-10)
        fwd5_downside = sum(downside.shift(-i) for i in range(1, 6)).clip(lower=0.0)
        fwd21_corr = ret.shift(-1).rolling(21).corr(spy_ret.shift(-1)).shift(-20)
        meta = exp_map[asset]
        e_z = float(meta["ai_exposure_z"])
        frame = pd.DataFrame(
            {
                "asset": asset,
                "sector_name": meta["sector_name"],
                "ai_labor_exposure": float(meta["ai_labor_exposure"]),
                "ai_exposure_z": e_z,
                "exposure_group": str(meta["exposure_group"]),
                "ret": ret,
                "rv": rv,
                "target_rv5": fwd5_rv,
                "target_log_rv5": np.log(fwd5_rv),
                "fwd5_downside": fwd5_downside,
                "fwd21_corr_to_spy": fwd21_corr,
                "vix_z": vix_z.reindex(adj.index),
                "spy_rv_5": spy_rv_5.reindex(adj.index),
                "ai_labor_news_z": shock["ai_labor_news_z"].reindex(adj.index),
                "labor_macro_shock": shock["labor_macro_shock"].reindex(adj.index),
                "joint_ai_labor_shock": shock["joint_ai_labor_shock"].reindex(adj.index),
                "event_shock": shock["event_shock"].reindex(adj.index),
            },
            index=adj.index,
        )
        frame["log_rv_1_lag1"] = np.log(rv).shift(1)
        frame["log_rv_5_lag1"] = np.log(rv.rolling(5).mean().clip(lower=1e-10)).shift(1)
        frame["log_rv_22_lag1"] = np.log(rv.rolling(22).mean().clip(lower=1e-10)).shift(1)
        frame["vix_z_lag1"] = frame["vix_z"].shift(1)
        frame["spy_rv_5_lag1"] = np.log(spy_rv_5.clip(lower=1e-10)).shift(1)
        frame["ai_news_x_exposure_lag1"] = (frame["ai_labor_news_z"].clip(lower=0.0) * e_z).shift(1)
        frame["labor_x_exposure_lag1"] = (frame["labor_macro_shock"] * e_z).shift(1)
        frame["joint_shock_x_exposure_lag1"] = (frame["joint_ai_labor_shock"] * e_z).shift(1)
        frames.append(frame.reset_index(names="date"))

    panel = pd.concat(frames, ignore_index=True).replace([np.inf, -np.inf], np.nan)
    panel.to_csv(DATA_DIR / "model_panel.csv", index=False)
    return panel, exposure


def fit_ols(train: pd.DataFrame, features: list[str]) -> np.ndarray:
    x = train[features].to_numpy(dtype=float)
    y = train["target_log_rv5"].to_numpy(dtype=float)
    x = np.column_stack([np.ones(len(x)), x])
    beta, *_ = np.linalg.lstsq(x, y, rcond=None)
    return beta


def expanding_predictions(asset_df: pd.DataFrame, spec: ModelSpec) -> pd.Series:
    df = asset_df.sort_values("date").reset_index(drop=True)
    preds = pd.Series(np.nan, index=df.index, dtype=float)
    oos_idx = np.flatnonzero(df["date"].to_numpy() >= np.datetime64(OOS_START))
    if len(oos_idx) == 0:
        preds.index = df["date"]
        return preds
    first_oos = int(oos_idx[0])
    beta = None
    last_fit = -10**9
    for i in range(first_oos, len(df)):
        if i < INIT_TRAIN_MIN:
            continue
        if beta is None or i - last_fit >= REFIT_EVERY:
            train = df.iloc[:i].dropna(subset=spec.features + ["target_log_rv5"])
            if len(train) < INIT_TRAIN_MIN:
                continue
            beta = fit_ols(train, spec.features)
            last_fit = i
        row = df.iloc[i]
        if row[spec.features].isna().any() or pd.isna(row["target_log_rv5"]):
            continue
        x = np.array([1.0] + [float(row[col]) for col in spec.features])
        preds.iloc[i] = float(x @ beta)
    preds.index = df["date"]
    return preds


def evaluate_asset(asset_df: pd.DataFrame) -> dict:
    asset = str(asset_df["asset"].iloc[0])
    df = asset_df.sort_values("date").reset_index(drop=True)
    pred = {spec.name: expanding_predictions(df, spec) for spec in MODELS}
    pred_df = pd.DataFrame(pred)
    actual = df.set_index("date")[["target_rv5", "target_log_rv5"]].join(pred_df)
    actual = actual.dropna(subset=["target_rv5", "HAR_VIX", "HAR_VIX_AI_LABOR"])
    metrics = {}
    losses = {}
    for spec in MODELS:
        valid = actual.dropna(subset=[spec.name])
        obs = valid["target_rv5"].to_numpy(dtype=float).clip(1e-10, 10.0)
        pred_var = np.exp(valid[spec.name].to_numpy(dtype=float)).clip(1e-10, 10.0)
        qloss = qlike_pointwise(obs, pred_var)
        mse_log = (valid["target_log_rv5"].to_numpy(dtype=float) - valid[spec.name].to_numpy(dtype=float)) ** 2
        metrics[spec.name] = {"n_oos": int(len(valid)), "qlike": float(np.mean(qloss)), "mse_log": float(np.mean(mse_log))}
        losses[spec.name] = pd.DataFrame({"date": valid.index, "qlike": qloss, "mse_log": mse_log})
    common = losses["HAR_VIX_AI_LABOR"].merge(losses["HAR_VIX"], on="date", suffixes=("_challenger", "_base"))
    q_t, q_p = dm_test(common["qlike_challenger"].to_numpy(), common["qlike_base"].to_numpy(), h=5)
    base_q = metrics["HAR_VIX"]["qlike"]
    ch_q = metrics["HAR_VIX_AI_LABOR"]["qlike"]
    return {
        "asset": asset,
        "metrics": metrics,
        "comparison": {
            "qlike_improvement_pct": float((base_q - ch_q) / abs(base_q) * 100.0),
            "dm_qlike_t": float(q_t),
            "dm_qlike_p": float(q_p),
        },
        "losses": losses,
    }


def pooled_dm(asset_results: list[dict]) -> dict:
    pieces = []
    for res in asset_results:
        ch = res["losses"]["HAR_VIX_AI_LABOR"][["date", "qlike"]].rename(columns={"qlike": "ch"})
        ba = res["losses"]["HAR_VIX"][["date", "qlike"]].rename(columns={"qlike": "base"})
        merged = ch.merge(ba, on="date")
        merged["diff"] = merged["ch"] - merged["base"]
        pieces.append(merged)
    panel = pd.concat(pieces, ignore_index=True)
    by_date = panel.groupby("date")["diff"].mean().dropna()
    t_stat, p_val = dm_test(by_date.to_numpy(), np.zeros(len(by_date)), h=5)
    return {
        "n_dates": int(len(by_date)),
        "mean_loss_diff": float(by_date.mean()),
        "dm_t": float(t_stat),
        "dm_p": float(p_val),
        "method": "date-clustered cross-sector mean QLIKE loss differential, h=5",
    }


def bootstrap_mean_diff(a: np.ndarray, b: np.ndarray) -> dict:
    rng = np.random.default_rng(SEED)
    a = a[np.isfinite(a)]
    b = b[np.isfinite(b)]
    if len(a) < 20 or len(b) < 20:
        return {"point": None, "ci_lo": None, "ci_hi": None, "n_a": int(len(a)), "n_b": int(len(b))}
    diffs = np.empty(N_BOOT)
    for i in range(N_BOOT):
        aa = rng.choice(a, size=len(a), replace=True)
        bb = rng.choice(b, size=len(b), replace=True)
        diffs[i] = np.mean(aa) - np.mean(bb)
    return {
        "point": float(np.mean(a) - np.mean(b)),
        "ci_lo": float(np.percentile(diffs, 2.5)),
        "ci_hi": float(np.percentile(diffs, 97.5)),
        "n_a": int(len(a)),
        "n_b": int(len(b)),
    }


def event_did(panel: pd.DataFrame) -> dict:
    date_rows = []
    for date, g in panel.dropna(subset=["target_rv5", "fwd5_downside", "fwd21_corr_to_spy"]).groupby("date"):
        high = g[g["exposure_group"] == "high"]
        low = g[g["exposure_group"] == "low"]
        if len(high) < 2 or len(low) < 2:
            continue
        date_rows.append(
            {
                "date": date,
                "event_shock": float(g["event_shock"].max()),
                "rv_high_low": float(high["target_rv5"].mean() - low["target_rv5"].mean()),
                "downside_high_low": float(high["fwd5_downside"].mean() - low["fwd5_downside"].mean()),
                "corr_high_low": float(high["fwd21_corr_to_spy"].mean() - low["fwd21_corr_to_spy"].mean()),
            }
        )
    d = pd.DataFrame(date_rows)
    shock = d[d["event_shock"] == 1.0]
    base = d[d["event_shock"] == 0.0]
    out = {}
    for col in ["rv_high_low", "downside_high_low", "corr_high_low"]:
        out[col] = bootstrap_mean_diff(shock[col].to_numpy(dtype=float), base[col].to_numpy(dtype=float))
    out["n_event_dates"] = int(len(shock))
    out["n_non_event_dates"] = int(len(base))
    return out


def verdict(results: dict) -> dict:
    event = results["event_did"]
    pooled = results["forecast"]["pooled"]
    positive_assets = sum(1 for row in results["forecast"]["per_asset"] if row["comparison"]["qlike_improvement_pct"] > 0)
    event_pass = (
        event["rv_high_low"]["ci_lo"] is not None
        and event["rv_high_low"]["ci_lo"] > 0
        and event["downside_high_low"]["ci_lo"] is not None
        and event["downside_high_low"]["ci_lo"] > 0
    )
    forecast_pass = pooled["dm_t"] < -3.0 and positive_assets >= 7
    if event_pass and forecast_pass:
        label = "CONDITIONAL_PASS_PROXY"
        summary = "AI-labor exposed sectors show shock-window risk response and OOS RV forecast improvement"
    elif event_pass:
        label = "EVENT_ONLY_WEAK"
        summary = "AI-labor exposed sectors show event-window risk response, but OOS RV forecast gate fails"
    elif pooled["dm_t"] < 0 and positive_assets >= 7 and pooled["dm_p"] < 0.10:
        label = "MIXED_WEAK"
        summary = "forecast direction is favorable but below Harvey strength and event DID is not robust"
    else:
        label = "NULL_PROXY"
        summary = "free-data AI labor exposure proxy does not robustly explain sector ETF volatility"
    return {
        "verdict": label,
        "summary": summary,
        "event_pass": bool(event_pass),
        "forecast_pass": bool(forecast_pass),
        "positive_asset_count": int(positive_assets),
        "asset_count": int(len(results["forecast"]["per_asset"])),
        "claim_ceiling": "NAICS-prefix sector proxy, GDELT/BLS macro shocks; not holdings-level labor-income exposure or firm-level AI adoption/layoff data",
    }


def make_figure(results: dict, exposure: pd.DataFrame) -> None:
    per_asset = results["forecast"]["per_asset"]
    imp = {row["asset"]: row["comparison"]["qlike_improvement_pct"] for row in per_asset}
    exp = exposure.sort_values("ai_labor_exposure")
    fig, axes = plt.subplots(2, 1, figsize=(12, 8), constrained_layout=True)
    axes[0].bar(exp["ticker"], exp["ai_labor_exposure"], color="#457b9d")
    axes[0].set_title("Sector AI labor exposure proxy from Felten/Raj/Seamans AIIE")
    axes[0].set_ylabel("Mean AIIE across mapped NAICS industries")
    vals = [imp.get(t, np.nan) for t in exp["ticker"]]
    colors = ["#2a9d8f" if v > 0 else "#d1495b" for v in vals]
    axes[1].bar(exp["ticker"], vals, color=colors)
    axes[1].axhline(0, color="#333333", lw=0.8)
    axes[1].set_title("OOS QLIKE improvement: HAR+VIX+AI-labor shocks vs HAR+VIX")
    axes[1].set_ylabel("Improvement (%)")
    fig.savefig(FIG_PATH, dpi=140)
    plt.close(fig)


def main() -> dict:
    np.random.seed(SEED)
    panel, exposure = build_panel()
    usable = panel.dropna(
        subset=[
            "target_rv5",
            "target_log_rv5",
            "log_rv_1_lag1",
            "log_rv_5_lag1",
            "log_rv_22_lag1",
            "vix_z_lag1",
            "spy_rv_5_lag1",
            "ai_news_x_exposure_lag1",
            "labor_x_exposure_lag1",
            "joint_shock_x_exposure_lag1",
        ]
    )
    raw_results = []
    for _, asset_df in usable.groupby("asset"):
        if len(asset_df) < INIT_TRAIN_MIN + 252:
            continue
        raw_results.append(evaluate_asset(asset_df.copy()))
    per_asset = [
        {"asset": row["asset"], "metrics": row["metrics"], "comparison": row["comparison"]}
        for row in raw_results
    ]
    results = {
        "experiment_id": EXP_ID,
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "seed": SEED,
        "data": {
            "sources": [
                "yfinance daily OHLCV auto_adjust=False",
                "Felten/Raj/Seamans AIOE GitHub AIIE industry scores",
                "GDELT DOC 2.0 TimelineVolRaw AI-labor query",
                "FRED/BLS PAYEMS and CES0500000003 monthly labor series",
            ],
            "start": START,
            "end_requested": END,
            "oos_start": OOS_START.strftime("%Y-%m-%d"),
            "assets": ASSETS,
            "n_panel_rows": int(len(panel)),
            "n_usable_rows": int(len(usable)),
        },
        "lookahead_policy": {
            "event_response": "shock at t, responses are sector RV/downside/correlation over t+1 forward windows",
            "forecast_target": "row t target is sector close-to-close RV over t+1..t+5",
            "forecast_signals": "HAR, VIX, SPY RV, AI-news, BLS labor, and joint shock interactions are all shifted by 1",
            "bls_availability": "monthly BLS/FRED values are approximated as available next month plus four business days, then forward-filled and shifted",
            "pooled_dm": "same-date cross-sector QLIKE loss differentials averaged before DM; h=5 overlapping horizon",
        },
        "sector_ai_exposure": exposure.to_dict(orient="records"),
        "event_did": event_did(panel),
        "forecast": {
            "baseline": "HAR_VIX",
            "challenger": "HAR_VIX_AI_LABOR",
            "per_asset": per_asset,
            "pooled": pooled_dm(raw_results),
        },
    }
    results["verdict"] = verdict(results)
    make_figure(results, exposure)
    save_json(RESULTS_PATH, results)
    print(json.dumps({"verdict": results["verdict"], "pooled": results["forecast"]["pooled"]}, indent=2))
    return results


if __name__ == "__main__":
    main()
