"""股票波動率 vs 信用市場：這次科技股回檔，信用市場有沒有跟著定價風險？

問題：2026 年 6-7 月 QQQ 出現逾 10% 回檔、台版 VIX 站上 37，但美國高收益債
(HYG) / 投資級債 (LQD) 的波動率與 OAS 利差看起來沒有同步反應。這是真的背離，
還是只是「還沒輪到信用市場」？

作法（描述 + 歷史對照，不宣稱因果）：
  1. 抓 QQQ / HYG / LQD / ^VIX 日資料（yfinance）與 FRED 的 HY / IG OAS。
  2. 算 20 日已實現波動率（年化，close-to-close）。
  3. 找出歷史上 QQQ 由近 252 日高點回檔 >= 10% 的「事件日」，取每段回檔的
     最深日當代表（避免同一段回檔被重複計入）。
  4. 對每個歷史事件，量測事件當日 HY OAS 相對事件前 60 個交易日均值的變化
     (bp)，以及 HYG 20d RV 的同期變化。
  5. 把「當前」放進這個歷史分佈裡看百分位 —— 回答「信用市場的沉默有多罕見」。

研究誠實：
  - 全部數字來自實際下載，無臆造；random 程序無（純描述統計 + 經驗百分位）。
  - 這是 descriptive / cross-asset 比較，不做預測宣稱、不做因果宣稱。
  - 事件日以「回檔谷底」定義，是 ex-post 標註，僅用於歷史分佈對照，
    不構成可交易訊號（不涉及 lookahead 的策略回測）。
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf
from urllib.request import urlopen

HERE = Path(__file__).resolve().parent
START = "2010-01-01"
TRADING_DAYS = 252
DRAWDOWN_THRESHOLD = -0.10
PRE_WINDOW = 60  # trading days of baseline before an event


def _fred_key() -> str:
    key = os.environ.get("FRED_API_KEY")
    if key:
        return key
    env = Path(__file__).resolve().parents[2] / ".env.local"
    for line in env.read_text(encoding="utf-8").splitlines():
        if line.startswith("FRED_API_KEY="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise RuntimeError("FRED_API_KEY not found")


def fetch_fred(series_id: str) -> pd.Series:
    url = (
        f"https://api.stlouisfed.org/fred/series/observations?series_id={series_id}"
        f"&api_key={_fred_key()}&file_type=json&observation_start={START}"
    )
    with urlopen(url, timeout=60) as resp:
        payload = json.loads(resp.read())
    obs = payload["observations"]
    idx = pd.to_datetime([o["date"] for o in obs])
    vals = pd.to_numeric([o["value"] for o in obs], errors="coerce")
    return pd.Series(vals, index=idx, name=series_id).dropna()


def realized_vol(close: pd.Series, window: int = 20) -> pd.Series:
    """Annualised close-to-close realised volatility, in percent."""
    ret = np.log(close).diff()
    return ret.rolling(window).std() * np.sqrt(TRADING_DAYS) * 100.0


def drawdown_events(close: pd.Series) -> list[pd.Timestamp]:
    """One representative date per distinct >=10% drawdown episode.

    Episode = a maximal run of days where drawdown-from-252d-high <= -10%.
    Representative day = the trough (most negative) inside that run.
    """
    peak = close.rolling(TRADING_DAYS, min_periods=TRADING_DAYS // 2).max()
    dd = close / peak - 1.0
    in_ep = dd <= DRAWDOWN_THRESHOLD

    events: list[pd.Timestamp] = []
    start: pd.Timestamp | None = None
    for date, flag in in_ep.items():
        if flag and start is None:
            start = date
        elif not flag and start is not None:
            seg = dd.loc[start:date].iloc[:-1]
            if len(seg):
                events.append(seg.idxmin())
            start = None
    if start is not None:  # episode still open at the end of the sample
        seg = dd.loc[start:]
        if len(seg):
            events.append(seg.idxmin())
    return events, dd


def main() -> None:
    tickers = ["QQQ", "HYG", "LQD", "^VIX"]
    raw = yf.download(
        tickers, start=START, auto_adjust=True, progress=False, group_by="column"
    )["Close"]
    raw = raw.dropna(how="all")

    hy_oas = fetch_fred("BAMLH0A0HYM2")  # ICE BofA US High Yield OAS (%)
    ig_oas = fetch_fred("BAMLC0A0CM")  # ICE BofA US Corporate OAS (%)

    df = pd.DataFrame(
        {
            "qqq": raw["QQQ"],
            "hyg": raw["HYG"],
            "lqd": raw["LQD"],
            "vix": raw["^VIX"],
        }
    ).dropna()
    df["hy_oas"] = hy_oas.reindex(df.index).ffill()
    df["ig_oas"] = ig_oas.reindex(df.index).ffill()
    df = df.dropna()

    df["qqq_rv"] = realized_vol(df["qqq"])
    df["hyg_rv"] = realized_vol(df["hyg"])
    df["lqd_rv"] = realized_vol(df["lqd"])
    df = df.dropna()

    events, dd = drawdown_events(df["qqq"])
    dd = dd.reindex(df.index)

    rows = []
    for ev in events:
        loc = df.index.get_loc(ev)
        if loc < PRE_WINDOW:
            continue
        pre = df.iloc[loc - PRE_WINDOW : loc]
        cur = df.loc[ev]
        rows.append(
            {
                "event_date": ev.strftime("%Y-%m-%d"),
                "qqq_drawdown_pct": round(float(dd.loc[ev]) * 100, 2),
                "qqq_rv": round(float(cur["qqq_rv"]), 2),
                "qqq_rv_change": round(float(cur["qqq_rv"] - pre["qqq_rv"].mean()), 2),
                "hyg_rv": round(float(cur["hyg_rv"]), 2),
                "hyg_rv_change": round(float(cur["hyg_rv"] - pre["hyg_rv"].mean()), 2),
                "hy_oas_bp_change": round(
                    float(cur["hy_oas"] - pre["hy_oas"].mean()) * 100, 1
                ),
                "ig_oas_bp_change": round(
                    float(cur["ig_oas"] - pre["ig_oas"].mean()) * 100, 1
                ),
                "vix": round(float(cur["vix"]), 2),
            }
        )

    # ---- current reading (last available day) ----
    last = df.iloc[-1]
    loc = len(df) - 1
    pre = df.iloc[loc - PRE_WINDOW : loc]
    current = {
        "as_of": df.index[-1].strftime("%Y-%m-%d"),
        "qqq_drawdown_pct": round(float(dd.iloc[-1]) * 100, 2),
        "qqq_rv": round(float(last["qqq_rv"]), 2),
        "qqq_rv_change": round(float(last["qqq_rv"] - pre["qqq_rv"].mean()), 2),
        "hyg_rv": round(float(last["hyg_rv"]), 2),
        "hyg_rv_change": round(float(last["hyg_rv"] - pre["hyg_rv"].mean()), 2),
        "lqd_rv": round(float(last["lqd_rv"]), 2),
        "hy_oas": round(float(last["hy_oas"]), 2),
        "hy_oas_bp_change": round(float(last["hy_oas"] - pre["hy_oas"].mean()) * 100, 1),
        "ig_oas": round(float(last["ig_oas"]), 2),
        "ig_oas_bp_change": round(float(last["ig_oas"] - pre["ig_oas"].mean()) * 100, 1),
        "vix": round(float(last["vix"]), 2),
    }

    hist = pd.DataFrame(rows)

    def pct_rank(series: pd.Series, value: float) -> float:
        return round(float((series < value).mean()) * 100, 1)

    # ---- conditional comparison: days where equity vol rose as much as today ----
    # The drawdown-trough sample (n=6) is small AND today is not a trough (QQQ is
    # only ~3% off its high). The apples-to-apples question is: on days when QQQ's
    # 20d RV ran this far above its own 60d baseline, what was credit doing?
    qqq_rv_base = df["qqq_rv"].rolling(PRE_WINDOW).mean().shift(1)
    hy_base = df["hy_oas"].rolling(PRE_WINDOW).mean().shift(1)
    hyg_rv_base = df["hyg_rv"].rolling(PRE_WINDOW).mean().shift(1)
    panel = pd.DataFrame(
        {
            "qqq_rv_change": df["qqq_rv"] - qqq_rv_base,
            "hy_oas_bp_change": (df["hy_oas"] - hy_base) * 100,
            "hyg_rv_change": df["hyg_rv"] - hyg_rv_base,
        }
    ).dropna()

    cur_spike = current["qqq_rv_change"]
    cond = panel[panel["qqq_rv_change"] >= cur_spike]
    cond_hist = cond.iloc[:-1] if len(cond) else cond  # exclude today itself

    conditional = {
        "condition": f"QQQ 20d RV at least {cur_spike:.1f} pp above its own trailing {PRE_WINDOW}d mean",
        "n_days": int(len(cond_hist)),
        "hy_oas_bp_change": {
            "median": round(float(cond_hist["hy_oas_bp_change"].median()), 1),
            "q25": round(float(cond_hist["hy_oas_bp_change"].quantile(0.25)), 1),
            "q75": round(float(cond_hist["hy_oas_bp_change"].quantile(0.75)), 1),
            "share_negative": round(
                float((cond_hist["hy_oas_bp_change"] < 0).mean()) * 100, 1
            ),
            "current": current["hy_oas_bp_change"],
            "current_percentile": round(
                float(
                    (cond_hist["hy_oas_bp_change"] < current["hy_oas_bp_change"]).mean()
                )
                * 100,
                1,
            ),
        },
        "hyg_rv_change": {
            "median": round(float(cond_hist["hyg_rv_change"].median()), 2),
            "share_negative": round(
                float((cond_hist["hyg_rv_change"] < 0).mean()) * 100, 1
            ),
            "current": current["hyg_rv_change"],
            "current_percentile": round(
                float((cond_hist["hyg_rv_change"] < current["hyg_rv_change"]).mean())
                * 100,
                1,
            ),
        },
    }

    summary = {
        "sample": {
            "start": df.index[0].strftime("%Y-%m-%d"),
            "end": df.index[-1].strftime("%Y-%m-%d"),
            "n_days": int(len(df)),
            "n_drawdown_episodes": int(len(hist)),
        },
        "current": current,
        "conditional_on_equity_vol_spike": conditional,
        "historical_events": rows,
        "historical_median": {
            "qqq_rv_change": round(float(hist["qqq_rv_change"].median()), 2),
            "hyg_rv_change": round(float(hist["hyg_rv_change"].median()), 2),
            "hy_oas_bp_change": round(float(hist["hy_oas_bp_change"].median()), 1),
            "ig_oas_bp_change": round(float(hist["ig_oas_bp_change"].median()), 1),
        },
        "current_percentile_vs_history": {
            "hy_oas_bp_change": pct_rank(
                hist["hy_oas_bp_change"], current["hy_oas_bp_change"]
            ),
            "hyg_rv_change": pct_rank(hist["hyg_rv_change"], current["hyg_rv_change"]),
            "qqq_rv_change": pct_rank(hist["qqq_rv_change"], current["qqq_rv_change"]),
        },
        "full_sample_correlation": {
            "qqq_rv_vs_hyg_rv": round(float(df["qqq_rv"].corr(df["hyg_rv"])), 3),
            "qqq_rv_vs_hy_oas": round(float(df["qqq_rv"].corr(df["hy_oas"])), 3),
            "vix_vs_hy_oas": round(float(df["vix"].corr(df["hy_oas"])), 3),
        },
        "provenance": {
            "equity_source": "yfinance (auto_adjust=True)",
            "oas_source": "FRED BAMLH0A0HYM2 / BAMLC0A0CM (ICE BofA OAS, percent)",
            "rv_definition": "20d close-to-close log-return stdev, annualised x sqrt(252), in %",
            "event_definition": f"trough day of each maximal run with QQQ drawdown from trailing {TRADING_DAYS}d high <= {DRAWDOWN_THRESHOLD:.0%}",
            "baseline": f"{PRE_WINDOW} trading days immediately before the event day",
        },
    }

    out = HERE / "credit_silence_results.json"
    out.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    df.to_csv(HERE / "panel.csv")
    print(json.dumps(summary["current"], indent=2, ensure_ascii=False))
    print("\nepisodes:", len(rows))
    print(hist.to_string(index=False) if len(hist) else "(none)")
    print("\npercentiles:", summary["current_percentile_vs_history"])
    print("corr:", summary["full_sample_correlation"])
    print("\nconditional:", json.dumps(conditional, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
