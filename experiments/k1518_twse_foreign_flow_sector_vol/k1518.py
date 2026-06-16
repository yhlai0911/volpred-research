"""K1518 - TWSE foreign institutional flow as Taiwan sector-vol predictor.

Question
--------
Do lagged foreign institutional net-selling shocks from the official TWSE T86
feed improve next-week realized-variance forecasts for Taiwan sector baskets?

Design
------
- Weekly PoC to keep the official daily T86 endpoint reproducible inside the
  hourly budget: use each week's actual last trading day.
- Baskets:
  * semiconductor: 2330, 2454, 2303
  * financial: 2881, 2882, 2891
  * traditional: 1301, 1303, 2002, 2603
- Target: next 5 trading days equal-weight sector realized variance.
- Baseline: log RV_{t+1:t+5} ~ log RV_{t-4:t} + log RV_{t-19:t}
- Augmented: baseline + lagged foreign net-selling z-score.

Lookahead defense
-----------------
- The TWSE T86 signal is observed on week-ending date t but the primary feature
  is explicitly shifted one additional week: flow_sell_z_lag1 = flow_sell_z.shift(1).
- Targets use returns from t+1 through t+5.
- Rolling flow z-scores use trailing 52-week windows only.
- Train/OOS split is temporal: train < 2022-01-01, OOS >= 2022-01-01.

Run
---
uv run python experiments/k1518_twse_foreign_flow_sector_vol/k1518.py
"""

from __future__ import annotations

import json
import math
import sys
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd
import requests
import yfinance as yf
from sklearn.linear_model import LinearRegression

from volpred.stats.model_evaluation import dm_test, qlike_pointwise


SEED = 42
HERE = Path(__file__).resolve().parent

START = "2018-01-01"
END = "2026-06-17"
OOS_START = pd.Timestamp("2022-01-01")
HORIZON = 5
FLOW_Z_WINDOW = 52
T86_CACHE = HERE / "k1518_weekly_t86_flows.csv"

SECTORS: dict[str, list[str]] = {
    "semiconductor": ["2330", "2454", "2303"],
    "financial": ["2881", "2882", "2891"],
    "traditional": ["1301", "1303", "2002", "2603"],
}
ALL_CODES = sorted({code for codes in SECTORS.values() for code in codes})
YF_TICKERS = [f"{code}.TW" for code in ALL_CODES]


@dataclass(frozen=True)
class ModelResult:
    sector: str
    n_train: int
    n_oos: int
    qlike_base: float
    qlike_aug: float
    qlike_improvement_pct: float
    dm_t_aug_vs_base: float
    dm_p_aug_vs_base: float
    flow_coef: float
    flow_sell_z_oos_mean: float
    flow_sell_z_oos_std: float


def parse_int(text: object) -> float:
    if text is None:
        return np.nan
    s = str(text).strip().replace(",", "")
    if s in {"", "--", "nan", "NaN"}:
        return np.nan
    return float(s)


def fetch_prices() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    raw = yf.download(
        YF_TICKERS,
        start=START,
        end=END,
        progress=False,
        auto_adjust=True,
        group_by="ticker",
        threads=True,
        timeout=45,
    )
    if raw is None or raw.empty or not isinstance(raw.columns, pd.MultiIndex):
        raise RuntimeError("yfinance returned unusable Taiwan equity data")

    def xs(field: str) -> pd.DataFrame:
        out = raw.xs(field, axis=1, level=1).copy()
        out.columns = [str(c).replace(".TW", "") for c in out.columns]
        out.index = pd.to_datetime(out.index).tz_localize(None)
        return out[ALL_CODES].sort_index()

    close = xs("Close").dropna(how="all")
    high = xs("High").reindex(close.index)
    low = xs("Low").reindex(close.index)
    return close, high, low


def actual_week_ends(index: pd.DatetimeIndex) -> pd.DatetimeIndex:
    dates = pd.Series(index, index=index)
    week_ends = dates.groupby(pd.Grouper(freq="W-FRI")).max().dropna()
    return pd.DatetimeIndex(week_ends.values)


def fetch_t86_date(date: pd.Timestamp) -> list[dict]:
    url = (
        "https://www.twse.com.tw/rwd/zh/fund/T86"
        f"?date={date:%Y%m%d}&selectType=ALLBUT0999&response=json"
    )
    payload = None
    for attempt in range(1, 9):
        try:
            resp = requests.get(url, timeout=60, headers={"User-Agent": "Mozilla/5.0"})
            resp.raise_for_status()
            payload = resp.json()
            break
        except (requests.RequestException, ValueError):
            if attempt == 8:
                raise RuntimeError(
                    f"T86 request failed or returned non-JSON for {date:%Y%m%d}"
                )
            time.sleep(5.0 * attempt)
    if payload is None:
        raise RuntimeError(f"T86 returned no payload for {date:%Y%m%d}")
    if payload.get("stat") != "OK":
        return []

    fields = payload.get("fields", [])
    data = payload.get("data", [])
    if not fields or not data:
        return []
    idx = {name: i for i, name in enumerate(fields)}

    def field_idx(candidates: list[str]) -> int:
        for name in candidates:
            if name in idx:
                return idx[name]
        raise RuntimeError(
            f"T86 schema changed for {date:%Y%m%d}; none of {candidates} "
            f"in fields={fields}"
        )

    code_i = field_idx(["證券代號"])
    foreign_i = field_idx(
        [
            "外陸資買賣超股數(不含外資自營商)",
            "外資及陸資買賣超股數(不含外資自營商)",
            "外資買賣超股數",
        ]
    )
    trust_i = field_idx(["投信買賣超股數"])
    dealer_i = field_idx(["自營商買賣超股數"])

    rows: list[dict] = []
    for row in data:
        code = str(row[code_i]).strip()
        if code not in ALL_CODES:
            continue
        foreign = parse_int(row[foreign_i])
        trust = parse_int(row[trust_i])
        dealer = parse_int(row[dealer_i])
        rows.append(
            {
                "date": date.date().isoformat(),
                "code": code,
                "foreign_net_shares": foreign,
                "trust_net_shares": trust,
                "dealer_net_shares": dealer,
                "total_inst_net_shares": foreign + trust + dealer,
            }
        )
    return rows


def load_or_fetch_t86(week_dates: Iterable[pd.Timestamp]) -> pd.DataFrame:
    week_dates = pd.DatetimeIndex(sorted(pd.Timestamp(d) for d in week_dates))
    cached = pd.DataFrame()
    if T86_CACHE.exists():
        cached = pd.read_csv(T86_CACHE)
        cached["date"] = pd.to_datetime(cached["date"], format="mixed")
        cached["code"] = cached["code"].astype(str).str.strip()

    cached_dates = set(pd.to_datetime(cached["date"], format="mixed").dt.normalize()) if not cached.empty else set()
    needed = [d for d in week_dates if d.normalize() not in cached_dates]

    rows: list[dict] = []

    def flush_rows() -> None:
        nonlocal cached, rows
        if not rows:
            return
        new = pd.DataFrame(rows)
        cached = pd.concat([cached, new], ignore_index=True)
        cached = cached.drop_duplicates(["date", "code"], keep="last")
        cached = cached.sort_values(["date", "code"])
        cached.to_csv(T86_CACHE, index=False)
        rows = []

    for i, d in enumerate(needed, start=1):
        got = fetch_t86_date(d)
        rows.extend(got)
        if i == 1 or i % 25 == 0 or i == len(needed):
            print(f"[t86] fetched {i}/{len(needed)} missing week dates", flush=True)
            flush_rows()
        time.sleep(1.0)
    flush_rows()

    if cached.empty:
        raise RuntimeError("No T86 rows fetched")

    cached["date"] = pd.to_datetime(cached["date"], format="mixed")
    keep = cached["date"].isin(week_dates.normalize())
    out = cached.loc[keep].copy()
    if out.empty:
        raise RuntimeError("T86 cache has no rows for requested week dates")
    return out


def sector_return(close: pd.DataFrame, sector: str) -> pd.Series:
    codes = SECTORS[sector]
    ret = np.log(close[codes] / close[codes].shift(1))
    return ret.mean(axis=1, skipna=True).rename(f"{sector}_ret")


def future_rv(ret: pd.Series, dates: pd.DatetimeIndex, horizon: int) -> pd.Series:
    vals: list[float] = []
    out_idx: list[pd.Timestamp] = []
    r = ret.dropna()
    for d in dates:
        if d not in r.index:
            continue
        pos = r.index.get_loc(d)
        if isinstance(pos, slice) or isinstance(pos, np.ndarray):
            continue
        window = r.iloc[pos + 1 : pos + horizon + 1]
        if len(window) == horizon and np.isfinite(window).all():
            vals.append(float((window**2).mean() * 252.0))
            out_idx.append(d)
    return pd.Series(vals, index=pd.DatetimeIndex(out_idx), name="target_rv5")


def lag_rv(ret: pd.Series, dates: pd.DatetimeIndex, window: int) -> pd.Series:
    rv = (ret**2).rolling(window, min_periods=window).mean() * 252.0
    return rv.reindex(dates).rename(f"rv{window}_t")


def build_flow_features(t86: pd.DataFrame, close: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict] = []
    close_week = close.reindex(pd.DatetimeIndex(sorted(t86["date"].unique())), method=None)
    for sector, codes in SECTORS.items():
        sub = t86[t86["code"].isin(codes)].copy()
        for date, g in sub.groupby("date"):
            date = pd.Timestamp(date)
            net_value = 0.0
            total_value = 0.0
            n_codes = 0
            for _, row in g.iterrows():
                code = row["code"]
                if date not in close_week.index or code not in close_week.columns:
                    continue
                px = close_week.loc[date, code]
                if not np.isfinite(px):
                    continue
                net_value += float(row["foreign_net_shares"]) * float(px)
                total_value += float(row["total_inst_net_shares"]) * float(px)
                n_codes += 1
            if n_codes:
                rows.append(
                    {
                        "date": date,
                        "sector": sector,
                        "foreign_net_value_twd": net_value,
                        "total_inst_net_value_twd": total_value,
                        "n_flow_codes": n_codes,
                    }
                )

    flow = pd.DataFrame(rows).sort_values(["sector", "date"])
    if flow.empty:
        raise RuntimeError("Sector flow feature frame is empty")
    frames = []
    for sector, g in flow.groupby("sector"):
        g = g.set_index("date").sort_index()
        mu = g["foreign_net_value_twd"].rolling(FLOW_Z_WINDOW, min_periods=26).mean()
        sd = g["foreign_net_value_twd"].rolling(FLOW_Z_WINDOW, min_periods=26).std()
        flow_z = (g["foreign_net_value_twd"] - mu) / sd
        g["foreign_sell_z"] = -flow_z
        # Conservative one-week lag: feature for week t uses week t-1 flow.
        g["foreign_sell_z_lag1"] = g["foreign_sell_z"].shift(1)
        g["sector"] = sector
        frames.append(g.reset_index())
    return pd.concat(frames, ignore_index=True)


def build_panel() -> pd.DataFrame:
    close, _high, _low = fetch_prices()
    week_dates = actual_week_ends(close.index)
    t86 = load_or_fetch_t86(week_dates)
    flow = build_flow_features(t86, close)

    panels: list[pd.DataFrame] = []
    for sector in SECTORS:
        ret = sector_return(close, sector)
        target = future_rv(ret, week_dates, HORIZON)
        rv5 = lag_rv(ret, week_dates, 5)
        rv20 = lag_rv(ret, week_dates, 20)
        d = pd.concat([target, rv5, rv20], axis=1).dropna()
        d["sector"] = sector
        panels.append(d.reset_index(names="date"))
    panel = pd.concat(panels, ignore_index=True)
    panel = panel.merge(flow, on=["date", "sector"], how="left")
    panel = panel.dropna(
        subset=["target_rv5", "rv5_t", "rv20_t", "foreign_sell_z_lag1"]
    ).copy()
    eps = 1e-10
    panel["log_target_rv5"] = np.log(panel["target_rv5"].clip(lower=eps))
    panel["log_rv5_t"] = np.log(panel["rv5_t"].clip(lower=eps))
    panel["log_rv20_t"] = np.log(panel["rv20_t"].clip(lower=eps))
    return panel.sort_values(["sector", "date"]).reset_index(drop=True)


def design_matrix(df: pd.DataFrame, cols: list[str], add_sector_fe: bool) -> pd.DataFrame:
    x = df[cols].copy()
    if add_sector_fe:
        dummies = pd.get_dummies(df["sector"], prefix="sector", drop_first=True, dtype=float)
        x = pd.concat([x.reset_index(drop=True), dummies.reset_index(drop=True)], axis=1)
    return x.astype(float)


def fit_one(train: pd.DataFrame, oos: pd.DataFrame, sector: str) -> ModelResult:
    base_cols = ["log_rv5_t", "log_rv20_t"]
    aug_cols = base_cols + ["foreign_sell_z_lag1"]

    y_train = train["log_target_rv5"].to_numpy()
    y_oos_log = oos["log_target_rv5"].to_numpy()
    y_oos = oos["target_rv5"].to_numpy()

    base = LinearRegression()
    aug = LinearRegression()
    base.fit(design_matrix(train, base_cols, sector == "pooled"), y_train)
    aug.fit(design_matrix(train, aug_cols, sector == "pooled"), y_train)

    base_log = base.predict(design_matrix(oos, base_cols, sector == "pooled"))
    aug_log = aug.predict(design_matrix(oos, aug_cols, sector == "pooled"))
    base_var = np.exp(np.clip(base_log, -30, 5))
    aug_var = np.exp(np.clip(aug_log, -30, 5))

    loss_base = qlike_pointwise(y_oos, base_var)
    loss_aug = qlike_pointwise(y_oos, aug_var)
    dm_t, dm_p = dm_test(loss_aug, loss_base, h=1)

    q_base = float(np.mean(loss_base))
    q_aug = float(np.mean(loss_aug))
    coef_idx = aug_cols.index("foreign_sell_z_lag1")
    return ModelResult(
        sector=sector,
        n_train=int(len(train)),
        n_oos=int(len(oos)),
        qlike_base=q_base,
        qlike_aug=q_aug,
        qlike_improvement_pct=float((q_base - q_aug) / abs(q_base) * 100.0),
        dm_t_aug_vs_base=float(dm_t),
        dm_p_aug_vs_base=float(dm_p),
        flow_coef=float(aug.coef_[coef_idx]),
        flow_sell_z_oos_mean=float(oos["foreign_sell_z_lag1"].mean()),
        flow_sell_z_oos_std=float(oos["foreign_sell_z_lag1"].std(ddof=1)),
    )


def evaluate(panel: pd.DataFrame) -> dict:
    results: list[ModelResult] = []
    for sector in sorted(SECTORS):
        sub = panel[panel["sector"] == sector].copy()
        train = sub[sub["date"] < OOS_START]
        oos = sub[sub["date"] >= OOS_START]
        if len(train) >= 100 and len(oos) >= 52:
            results.append(fit_one(train, oos, sector))

    train_p = panel[panel["date"] < OOS_START]
    oos_p = panel[panel["date"] >= OOS_START]
    results.append(fit_one(train_p, oos_p, "pooled"))

    out = {r.sector: r.__dict__ for r in results}
    pooled = out["pooled"]
    sector_passes = sum(
        1
        for k, v in out.items()
        if k != "pooled" and v["qlike_improvement_pct"] > 0 and v["dm_t_aug_vs_base"] < 0
    )
    if (
        pooled["qlike_improvement_pct"] > 0
        and pooled["dm_t_aug_vs_base"] < -3.0
        and sector_passes >= 2
    ):
        verdict = "PASS"
    elif pooled["qlike_improvement_pct"] > 0 and pooled["dm_t_aug_vs_base"] < -2.0:
        verdict = "CONDITIONAL_PASS"
    else:
        verdict = "NULL"
    return {"models": out, "sector_directional_passes": sector_passes, "verdict": verdict}


def make_plot(panel: pd.DataFrame, results: dict) -> None:
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception as exc:  # pragma: no cover
        print(f"[plot] matplotlib unavailable: {exc}")
        return

    fig, axes = plt.subplots(2, 1, figsize=(11, 7), sharex=False)
    for sector in sorted(SECTORS):
        sub = panel[panel["sector"] == sector]
        axes[0].plot(sub["date"], sub["foreign_sell_z_lag1"], lw=0.8, label=sector)
    axes[0].axhline(0, color="gray", lw=0.8)
    axes[0].set_title("K1518 lagged foreign net-selling z-score by sector")
    axes[0].legend(fontsize=8)
    axes[0].grid(alpha=0.3)

    sectors = [k for k in results["models"] if k != "pooled"]
    vals = [results["models"][k]["qlike_improvement_pct"] for k in sectors]
    axes[1].bar(sectors, vals, color=["tab:blue" if v >= 0 else "tab:red" for v in vals])
    axes[1].axhline(0, color="black", lw=0.8)
    axes[1].set_ylabel("QLIKE improvement vs HAR (%)")
    axes[1].set_title("Augmented flow model OOS improvement")
    axes[1].grid(alpha=0.3, axis="y")

    fig.tight_layout()
    fig.savefig(HERE / "k1518_plots.png", dpi=140)
    plt.close(fig)


def main() -> int:
    print(f"[k1518] start {datetime.now().isoformat(timespec='seconds')}")
    panel = build_panel()
    print(
        f"[k1518] panel rows={len(panel)} dates={panel['date'].min().date()} -> "
        f"{panel['date'].max().date()}"
    )
    results = evaluate(panel)
    make_plot(panel, results)

    payload = {
        "experiment_id": "K1518",
        "title": "TWSE foreign institutional flow as Taiwan sector-vol leading indicator",
        "verdict": results["verdict"],
        "seed": SEED,
        "data": {
            "price_source": "yfinance adjusted close",
            "flow_source": "TWSE official T86 three-institution daily report, sampled at each week's actual last trading day",
            "period": {
                "start": START,
                "end": END,
                "oos_start": OOS_START.date().isoformat(),
            },
            "sectors": SECTORS,
            "n_panel_rows": int(len(panel)),
            "n_weeks": int(panel["date"].nunique()),
            "flow_cache": str(T86_CACHE.relative_to(HERE)),
        },
        "lookahead_defenses": [
            "Weekly target uses returns from t+1 through t+5 only.",
            "Foreign net-selling z-score uses trailing 52-week rolling mean/std only.",
            "Primary flow signal is explicitly shifted one additional week via foreign_sell_z.shift(1).",
            "Train/OOS split is strictly temporal: train < 2022-01-01, OOS >= 2022-01-01.",
            "Models fit on train only; OOS predictions use fixed train coefficients.",
        ],
        "results": results,
        "references": [
            {
                "citation": "TWSE T86 三大法人買賣超日報 official data page.",
                "url": "https://www.twse.com.tw/zh/trading/foreign/t86.html",
            },
            {
                "citation": "Wei (2009), Taiwan institutional trading volume volatility spillover on stock market index return.",
                "url": "https://ideas.repec.org/a/ebl/ecbull/eb-08c30093.html",
            },
            {
                "citation": "Lin, Lee, and Chiu (2009), foreign investors' trading behavior and Taiwan stock market impact.",
                "url": "https://ideas.repec.org/a/eee/riibaf/v23y2009i1p78-89.html",
            },
            {
                "citation": "Structural changes in foreign investors' trading behavior and impact on Taiwan stock market (PMC full text).",
                "url": "https://pmc.ncbi.nlm.nih.gov/articles/PMC7148904/",
            },
        ],
        "timestamp_utc": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
    }
    out_path = HERE / "k1518_results.json"
    out_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"[k1518] wrote {out_path}")
    print(f"[k1518] verdict={payload['verdict']}")
    pooled = results["models"]["pooled"]
    print(
        "[k1518] pooled QLIKE base={:.4f} aug={:.4f} improvement={:.2f}% DM t={:.3f} p={:.4f}".format(
            pooled["qlike_base"],
            pooled["qlike_aug"],
            pooled["qlike_improvement_pct"],
            pooled["dm_t_aug_vs_base"],
            pooled["dm_p_aug_vs_base"],
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
