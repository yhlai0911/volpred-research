"""K1700 — 「未來 30 年每年穩定成長 15%」的可行性拆解.

Member question e79a7097 (yaoxk1431):
  「如果我要接下來 30 年我的資金穩定每年成長 15%, 我該問什麼問題,
    我必須掌握投資的 15 個問題」

本實驗不做預測，只做歷史事實的量化拆解：

  A. 美股 30 年滾動總報酬 CAGR 的歷史分布 —— 15% 出現過幾次？
  B. 「穩定」與高 CAGR 能否共存 —— 高 CAGR 視窗內的最大回撤
  C. 槓桿能不能補上缺口 —— 每日再平衡 2x/3x（用 FRED 實際短率當借貸成本）
  D. 台股 ^TWII 的同口徑對照（樣本 < 30 年，只作參考）

**含息序列的建法（v2，2026-07-12 code review C1/C2/C3 修正）**：
早期股息率遠高於近期（1950 年代 ~7% vs 2020 年代 ~1.3%），因此**不可**用單一
常數平移 price-only 分布（v1 的作法會低估 1927-1960 起點視窗的含息報酬 2-3pp）。
v2 改為：
  - 1927 ~ 1988：Shiller 逐月 D/P 股息率 → 日化 → r_tr = r_price + y/252
  - 1988 ~ 2026：直接用 ^SP500TR 的實際日報酬
  - 兩段在 1988-01 銜接；並在 1988-2023 重疊區把「Shiller 建法」與「^SP500TR
    實際值」對照，報告建法誤差（見 results 的 `tr_construction_validation`）

無預測訊號、無 train/test split、無隨機程序，因此不涉及 lookahead，亦無 seed
需求；所有數字皆為已實現歷史路徑的描述統計。

Data: yfinance ^GSPC / ^SP500TR / ^TWII；Shiller ie_data（股息）；FRED TB3MS（短率）。
"""

from __future__ import annotations

import io
import json
import re
import urllib.request
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import requests
import yfinance as yf

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
DATA.mkdir(exist_ok=True)

TARGET_CAGR = 0.15
WINDOW_YEARS = 30
TR_SPLICE = pd.Timestamp("1988-01-04")  # ^SP500TR 起點
BROKER_SPREAD = 0.01  # 槓桿借貸利差（短率之上），1pp

plt.rcParams["font.sans-serif"] = ["Heiti TC", "Arial Unicode MS", "PingFang TC"]
plt.rcParams["axes.unicode_minus"] = False


# --------------------------------------------------------------------------
# data
# --------------------------------------------------------------------------
def fetch_px(ticker: str, start: str) -> pd.Series:
    df = yf.download(ticker, start=start, auto_adjust=False, progress=False)
    px = df["Close"]
    if isinstance(px, pd.DataFrame):
        px = px.iloc[:, 0]
    return px.dropna()


def shiller_dividend_yield() -> pd.Series:
    """Shiller ie_data 的逐月股息率（年化 D / P）。快取到 experiments/k1700/data/."""
    cache = DATA / "shiller_ie_data.xls"
    if not cache.exists():
        url = "http://www.econ.yale.edu/~shiller/data/ie_data.xls"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        cache.write_bytes(urllib.request.urlopen(req, timeout=120).read())
    df = pd.ExcelFile(io.BytesIO(cache.read_bytes())).parse("Data", skiprows=7)
    df = df[["Date", "P", "D"]].dropna()
    # Date 形如 1871.01 / 1871.1 (=十月)；用字串補位解析
    def _to_ts(v: float) -> pd.Timestamp:
        y, m = str(v).split(".")
        return pd.Timestamp(int(y), int(m.ljust(2, "0")), 1)

    df["ts"] = df["Date"].map(_to_ts)
    y = (df["D"].astype(float) / df["P"].astype(float)).values
    return pd.Series(y, index=pd.DatetimeIndex(df["ts"]), name="div_yield")


def fred_tb3ms() -> pd.Series:
    key = re.search(r"FRED_API_KEY=(\S+)", Path(".env.local").read_text()).group(1)
    r = requests.get(
        "https://api.stlouisfed.org/fred/series/observations",
        params={"series_id": "TB3MS", "api_key": key, "file_type": "json"},
        timeout=60,
    )
    obs = r.json()["observations"]
    s = pd.Series(
        {pd.Timestamp(o["date"]): float(o["value"]) / 100.0
         for o in obs if o["value"] not in ("", ".")}
    )
    return s.sort_index()


# --------------------------------------------------------------------------
# analytics
# --------------------------------------------------------------------------
def rolling_cagr_and_mdd(px: pd.Series, years: int) -> pd.DataFrame:
    """對每個交易日起點，算 `years` 年後的 CAGR 與該視窗內的最大回撤."""
    idx = px.index
    end_targets = idx + pd.DateOffset(years=years)
    pos = np.searchsorted(idx.values, end_targets.values, side="left")
    vals = px.values
    rows = []
    for i, j in enumerate(pos):
        if j >= len(idx):
            continue
        realised_years = (idx[j] - idx[i]).days / 365.25
        cagr = (vals[j] / vals[i]) ** (1.0 / realised_years) - 1.0
        seg = vals[i : j + 1]
        mdd = float((seg / np.maximum.accumulate(seg) - 1.0).min())
        rows.append(
            {
                "start": idx[i],
                "end": idx[j],
                "cagr": float(cagr),
                "mdd": mdd,
                "multiple": float(vals[j] / vals[i]),
            }
        )
    return pd.DataFrame(rows)


def summarize(df: pd.DataFrame, label: str) -> dict:
    return {
        "label": label,
        "n_windows": int(len(df)),
        "n_independent_windows": round(
            (df["end"].iloc[-1] - df["start"].iloc[0]).days / 365.25 / WINDOW_YEARS, 2
        ),
        "first_start": str(df["start"].iloc[0].date()),
        "last_end": str(df["end"].iloc[-1].date()),
        "cagr_median": float(df["cagr"].median()),
        "cagr_p5": float(df["cagr"].quantile(0.05)),
        "cagr_p95": float(df["cagr"].quantile(0.95)),
        "cagr_max": float(df["cagr"].max()),
        "cagr_max_start": str(df.loc[df["cagr"].idxmax(), "start"].date()),
        "cagr_min": float(df["cagr"].min()),
        "cagr_min_start": str(df.loc[df["cagr"].idxmin(), "start"].date()),
        "share_ge_target": float((df["cagr"] >= TARGET_CAGR).mean()),
        "n_ge_target": int((df["cagr"] >= TARGET_CAGR).sum()),
        "mdd_median": float(df["mdd"].median()),
        "mdd_worst": float(df["mdd"].min()),
        "mdd_shallowest": float(df["mdd"].max()),
    }


def main() -> None:
    out: dict = {
        "experiment_id": "K1700",
        "question_id": "e79a7097-714f-4be4-b115-402f02f2d748",
        "target_cagr": TARGET_CAGR,
        "window_years": WINDOW_YEARS,
        "target_multiple_30y": float((1 + TARGET_CAGR) ** WINDOW_YEARS),
        "data_sources": {
            "prices": "yfinance ^GSPC / ^SP500TR / ^TWII",
            "dividends": "Shiller ie_data (monthly D/P), econ.yale.edu",
            "financing": "FRED TB3MS (3-month T-bill) + 1pp broker spread",
        },
        "random_process": "none (無抽樣 / MC / bootstrap，故無 seed)",
    }

    gspc = fetch_px("^GSPC", "1927-01-01")
    sptr = fetch_px("^SP500TR", "1988-01-01")
    dy = shiller_dividend_yield()

    # ---- 建含息（total return）日序列 ----
    r_px = gspc.pct_change().dropna()
    dy_daily = dy.reindex(r_px.index, method="ffill")  # 月頻 → 日頻
    dy_daily = dy_daily.ffill().bfill()
    r_tr_shiller = r_px + dy_daily / 252.0

    r_sptr = sptr.pct_change().dropna()
    r_tr = r_tr_shiller.copy()
    overlap = r_tr.index.intersection(r_sptr.index)
    r_tr.loc[overlap] = r_sptr.loc[overlap]  # 1988 起改用實際 ^SP500TR
    tr_index = (1.0 + r_tr).cumprod()
    tr_index.iloc[0] = 1.0

    # ---- 建法驗證：1988-2023 重疊區，Shiller 建法 vs 實際 ^SP500TR ----
    val_end = min(dy.index[-1], r_sptr.index[-1])
    vmask = (overlap >= TR_SPLICE) & (overlap <= val_end)
    ov = overlap[vmask]
    yrs = (ov[-1] - ov[0]).days / 365.25
    cagr_built = float((1 + r_tr_shiller.loc[ov]).prod() ** (1 / yrs) - 1)
    cagr_actual = float((1 + r_sptr.loc[ov]).prod() ** (1 / yrs) - 1)
    out["tr_construction_validation"] = {
        "overlap": [str(ov[0].date()), str(ov[-1].date())],
        "years": float(yrs),
        "shiller_built_cagr": cagr_built,
        "actual_sp500tr_cagr": cagr_actual,
        "error_pp": float((cagr_built - cagr_actual) * 100),
        "note": "此誤差即 1927-1988 那段（無 ^SP500TR 可用）建法的預期精度。",
    }
    out["dividend_yield_history"] = {
        "1930s_mean": float(dy["1930":"1939"].mean()),
        "1950s_mean": float(dy["1950":"1959"].mean()),
        "1980s_mean": float(dy["1980":"1989"].mean()),
        "2010s_mean": float(dy["2010":"2019"].mean()),
        "note": "股息率長期由 ~6% 降到 ~2%，故不可用單一常數平移（v1 的錯誤）。",
    }

    # ---- A/B. 30 年滾動（含息）----
    roll_tr = rolling_cagr_and_mdd(tr_index, WINDOW_YEARS)
    out["spx_total_return_30y"] = summarize(roll_tr, "S&P500 total return, 30y rolling")
    out["spx_total_return_30y"]["share_ge_target_multiple"] = float(
        (roll_tr["multiple"] >= out["target_multiple_30y"]).mean()
    )
    roll_px = rolling_cagr_and_mdd(gspc, WINDOW_YEARS)
    out["spx_price_only_30y"] = summarize(roll_px, "S&P500 price-only, 30y rolling")

    top = roll_tr.nlargest(max(1, len(roll_tr) // 10), "cagr")
    out["best_decile_windows"] = {
        "n": int(len(top)),
        "cagr_min": float(top["cagr"].min()),
        "cagr_max": float(top["cagr"].max()),
        "mdd_median": float(top["mdd"].median()),
        "mdd_shallowest": float(top["mdd"].max()),
        "share_with_mdd_worse_than_30pct": float((top["mdd"] <= -0.30).mean()),
        "share_with_mdd_worse_than_40pct": float((top["mdd"] <= -0.40).mean()),
    }

    # ---- C. 槓桿（含息 + 實際短率借貸成本）----
    tb3 = fred_tb3ms()
    fin_daily = tb3.reindex(r_tr.index, method="ffill")
    lev_rows = []
    for k in (1.0, 1.5, 2.0, 3.0):
        for spread, tag in ((None, "免費借貸（理論上界）"), (BROKER_SPREAD, "實際短率+1pp")):
            if k == 1.0 and spread is not None:
                continue
            if spread is None:
                cost = 0.0
                r_lev = k * r_tr
            else:
                cost = (fin_daily + spread) / 252.0
                r_lev = k * r_tr - (k - 1.0) * cost
            r_lev = r_lev.dropna().clip(lower=-0.99)
            path = (1.0 + r_lev).cumprod()
            rr = rolling_cagr_and_mdd(path, WINDOW_YEARS)
            s = summarize(rr, f"{k:g}x {tag}")
            s["leverage"] = k
            s["financing"] = tag
            lev_rows.append(s)
    out["leverage_30y"] = lev_rows
    out["financing_rate_context"] = {
        "tb3ms_range": [str(tb3.index[0].date()), str(tb3.index[-1].date())],
        "tb3ms_mean": float(tb3.mean()),
        "tb3ms_mean_1970s_1990s": float(tb3["1970":"1999"].mean()),
        "note": "槓桿最好的 30 年（1970 起）恰逢短率 6-15%，固定 4% 假設會嚴重美化槓桿。",
    }

    # ---- D. 台股 ^TWII ----
    # 註：原欲用 0050.TW，但 yfinance 該序列 2014-02-05 收 13.95（實際約 57），
    # 會生出 -77.9% 的假回撤 → 棄用，改 ^TWII。
    tw = fetch_px("^TWII", "1997-01-01")
    tw_years = (tw.index[-1] - tw.index[0]).days / 365.25
    tw_roll20 = rolling_cagr_and_mdd(tw, 20)
    out["taiwan_twii"] = {
        "ticker": "^TWII",
        "period": [str(tw.index[0].date()), str(tw.index[-1].date())],
        "years": float(tw_years),
        "cagr_price_only_full": float((tw.iloc[-1] / tw.iloc[0]) ** (1 / tw_years) - 1),
        "mdd_full": float((tw / tw.cummax() - 1.0).min()),
        "rolling20y_price_only": summarize(tw_roll20, "^TWII price-only, 20y rolling"),
        "note": (
            "加權指數為價格指數（未含息；台股現金殖利率長期約 3-4%，故含息 CAGR "
            "約再加 3-4pp）。樣本自 1997 起 < 30 年，改看 20 年視窗，僅作對照。"
        ),
        "data_quality_note": (
            "0050.TW 在 yfinance 的序列有明顯錯價（2014-02-05 收 13.95，實際約 57），"
            "會產生 -77.9% 的假最大回撤 → 本實驗棄用該序列。"
        ),
    }

    out["caveats"] = [
        "1927-1988 的含息報酬由 Shiller 逐月股息率合成（非逐日實配），"
        f"其精度見 tr_construction_validation（重疊區誤差 "
        f"{out['tr_construction_validation']['error_pp']:.2f}pp/年）。",
        "滾動視窗為重疊樣本（每交易日一個起點），視窗間高度相關；"
        "98 年資料只含約 3.3 個獨立的 30 年區間 —— 分位數是描述統計，不是統計檢定。",
        "槓桿路徑為每日再平衡、無交易成本與內扣費用，真實槓桿 ETF 更差；"
        "故此處數字對槓桿有利，是上界。",
        "槓桿單日報酬 clip 在 -99%；3x 的極端回撤應理解為「實務上已爆倉」。",
        "MDD 以日收盤計，未計盤中極值。",
    ]

    # ---- 圖 1 ----
    fig, ax = plt.subplots(figsize=(11, 5.5))
    ax.plot(roll_px["start"], roll_px["cagr"] * 100, lw=1.2, color="#a0aec0",
            label="只算價格（不含股息）")
    ax.plot(roll_tr["start"], roll_tr["cagr"] * 100, lw=1.6, color="#2b6cb0",
            label="含股息再投入（真實股息率）")
    ax.axhline(TARGET_CAGR * 100, color="#c53030", lw=2, label="目標 15%")
    best = out["spx_total_return_30y"]
    ax.annotate(
        f"史上最佳：{best['cagr_max_start'][:7]} 起的 30 年\n"
        f"年化 {best['cagr_max']*100:.1f}%（仍未到 15%）",
        xy=(pd.Timestamp(best["cagr_max_start"]), best["cagr_max"] * 100),
        xytext=(pd.Timestamp("1940-01-01"), 15.5),
        arrowprops=dict(arrowstyle="->", color="#2d3748"), fontsize=11,
    )
    ax.set_title("S&P 500 每一個 30 年區間的年化報酬（1927 年至今，含息）")
    ax.set_xlabel("這 30 年是從哪一天開始投的")
    ax.set_ylabel("這 30 年的年化報酬 (%)")
    ax.legend(loc="lower right")
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(HERE / "fig1_rolling_30y_cagr.png", dpi=130)
    plt.close(fig)

    # ---- 圖 2 ----
    fig, ax = plt.subplots(figsize=(9.5, 5.5))
    for s in lev_rows:
        if s["leverage"] != 1.0 and s["financing"] != "實際短率+1pp":
            continue
        x, y = -s["mdd_median"] * 100, s["cagr_median"] * 100
        ax.scatter(x, y, s=170, zorder=3)
        ax.annotate(f"{s['leverage']:g}x", (x, y), textcoords="offset points",
                    xytext=(10, 4), fontsize=13)
    ax.axhline(TARGET_CAGR * 100, color="#c53030", lw=1.8, ls="--", label="目標 15%")
    ax.set_xlabel("這 30 年裡最深的一次虧損（中位數，%）")
    ax.set_ylabel("30 年年化報酬（中位數，%，含息）")
    ax.set_title("借錢加碼買美股：報酬多一點，虧損多很多（借貸成本用歷史實際短率）")
    ax.set_ylim(0, 17)
    ax.legend(loc="lower left")
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(HERE / "fig2_leverage_tradeoff.png", dpi=130)
    plt.close(fig)

    with open(HERE / "k1700_results.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(json.dumps(
        {k: out[k] for k in
         ("tr_construction_validation", "spx_total_return_30y", "best_decile_windows")},
        ensure_ascii=False, indent=2))
    for s in lev_rows:
        print(f"{s['label']:28s} CAGR中位 {s['cagr_median']*100:6.2f}%  "
              f"≥15% 比例 {s['share_ge_target']*100:5.1f}%  MDD中位 {s['mdd_median']*100:6.1f}%")


if __name__ == "__main__":
    main()
