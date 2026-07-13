#!/usr/bin/env python3
"""台灣無人載具產業 EP1 — 上游環節（晶片/飛控/感測/通訊/射頻）證據包。

資料源：yfinance（真抓真算）。上游名冊來自 EP0 已驗證名冊
（storage/pending_series/taiwan_drone_series_ep0_research.md，代碼板別逐檔 live 驗證）。

本腳本回答三件 EP0 沒回答的事：
  1. 上游各檔的「真財報」長什麼樣：FY2023-2025 營收、營收成長、毛利率、營益率、研發密度
  2. 市場付多少錢買一元營收（市值/營收倍數）—— 描述性倍數，非估值建議
  3. 「題材含量」能不能量化：財報拆不出無人機營收佔比 → 改用市場資料做雙因子迴歸
     r_i = a + b·TWII + c·DroneResid + e
     其中 DroneResid = 純度較高的無人載具整機/軍工籃（雷虎/漢翔/亞航/中光電/碳基/龍德）
     等權日報酬對 ^TWII 迴歸後的殘差（正交化，避免與大盤共線）。
     c = 「題材載荷」。HAC (Newey-West) 標準誤，lag = ceil(n^(1/3))。
     ⚠ 同期描述性迴歸，非預測模型；不可用於擇時。

輸出：
  storage/drafts/assets/drone_ep1_theme_vs_fundamental.png  — 題材熱度 vs 基本面（股價報酬 vs 營收成長）
  storage/drafts/assets/drone_ep1_theme_loading.png         — 題材載荷（drone factor beta）+ 95% CI
  storage/drafts/assets/drone_ep1_margin_multiple.png       — 毛利率 vs 市值/營收倍數
  storage/drafts/drone_ep1_upstream_evidence.json           — 所有引用數字（可複現）

用法：
  uv run python scripts/drone_ep1_upstream_evidence.py
"""
from __future__ import annotations

import json
import math
from datetime import datetime, timezone, timedelta
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import statsmodels.api as sm
import yfinance as yf
from matplotlib import font_manager

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "storage" / "drafts" / "assets"
ASSETS.mkdir(parents=True, exist_ok=True)
OUT_JSON = ROOT / "storage" / "drafts" / "drone_ep1_upstream_evidence.json"

for cand in ["Heiti TC", "PingFang TC", "Arial Unicode MS", "Songti TC"]:
    if any(cand == f.name for f in font_manager.fontManager.ttflist):
        plt.rcParams["font.family"] = cand
        break
plt.rcParams["axes.unicode_minus"] = False

# 與 EP0 相同的價格窗口，維持系列可比性
START = "2025-06-30"
END = "2026-07-11"  # yfinance end 為開區間；EP0 實際末日 2026-07-10
TRADING_DAYS = 252

# 上游 13 檔（EP0 名冊 tier=上游）。segment = EP1 的五個環節切法。
UPSTREAM: list[tuple[str, str, str, str]] = [
    # (name, ticker, segment, confidence)
    ("新唐", "4919.TW", "飛控/MCU", "中"),
    ("聯發科", "2454.TW", "晶片(題材)", "低"),
    ("聯詠", "3034.TW", "晶片(題材)", "低"),
    ("全訊", "5222.TW", "射頻/微波", "高"),
    ("立積", "4968.TW", "射頻/微波", "中"),
    ("昇達科", "3491.TWO", "射頻/微波", "中"),
    ("合勤控", "3704.TW", "通訊", "中"),
    ("亞光", "3019.TW", "光學/感測", "中高"),
    ("邑錡", "7402.TWO", "光學/感測", "中"),
    ("義隆", "2458.TW", "光學/感測", "中"),
    ("千附精密", "6829.TWO", "精密結構件", "高"),
    ("寶一", "8222.TW", "精密結構件", "高"),
    ("晟田", "4541.TWO", "精密結構件", "高"),
]

# 純度較高的無人載具整機/軍工籃 —— 用來建「題材因子」。
# 全部取自 EP0 名冊中游/下游、關聯信心「高」的整機或軍工主體，
# 刻意不含任何上游股，避免上游對自己的因子產生機械式自我載荷。
PURE_PLAY: list[tuple[str, str]] = [
    ("雷虎", "8033.TW"),
    ("漢翔", "2634.TW"),
    ("亞航", "2630.TW"),
    ("中光電", "5371.TWO"),
    ("碳基", "7719.TWO"),
    ("龍德造船", "6753.TW"),
]

BENCH = "^TWII"
# 小型股對照因子：富邦臺灣中小 ETF。用來檢驗「題材載荷」是不是只是小型股共同波動。
SMALLCAP = "00733.TW"

SEGMENT_COLOR = {
    "飛控/MCU": "#d62728",
    "晶片(題材)": "#9467bd",
    "射頻/微波": "#1f77b4",
    "通訊": "#17becf",
    "光學/感測": "#2ca02c",
    "精密結構件": "#ff7f0e",
}


def fetch_prices(tickers: list[str]) -> pd.DataFrame:
    raw = yf.download(
        tickers, start=START, end=END, auto_adjust=True, progress=False, group_by="ticker"
    )
    cols = {}
    for t in tickers:
        try:
            cols[t] = raw[t]["Close"]
        except Exception:
            cols[t] = raw["Close"][t]
    return pd.DataFrame(cols).dropna(how="all")


def hac_lag(n: int) -> int:
    return max(1, int(math.ceil(n ** (1.0 / 3.0))))


def fin_row(fin: pd.DataFrame, key: str, col) -> float | None:
    if fin is None or fin.empty or key not in fin.index or col not in fin.columns:
        return None
    v = fin.loc[key, col]
    if pd.isna(v):
        return None
    return float(v)


def main() -> None:
    now_tw = datetime.now(timezone(timedelta(hours=8)))
    tickers = [t for _, t, _, _ in UPSTREAM] + [t for _, t in PURE_PLAY] + [BENCH, SMALLCAP]
    px = fetch_prices(tickers)
    rets = np.log(px).diff().dropna(how="all")

    mkt = rets[BENCH]

    # ---- 序貫正交化 ----
    # 1) 小型股因子 = 中小型 ETF 報酬對大盤的殘差
    sz = pd.concat({"sc": rets[SMALLCAP], "mkt": mkt}, axis=1).dropna()
    m0 = sm.OLS(sz["sc"], sm.add_constant(sz["mkt"])).fit(
        cov_type="HAC", cov_kwds={"maxlags": hac_lag(len(sz))}
    )
    size_resid = pd.Series(m0.resid, index=sz.index, name="size")

    # 2) 題材因子 = 純整機籃等權報酬對「大盤 + 小型股因子」的殘差
    #    → 載荷讀成「扣掉大盤與小型股共同波動後，仍與軍工整機題材同步的部分」
    pp_cols = [t for _, t in PURE_PLAY]
    pp_ret = rets[pp_cols].mean(axis=1)
    joint = pd.concat({"pp": pp_ret, "mkt": mkt, "size": size_resid}, axis=1).dropna()
    m1 = sm.OLS(joint["pp"], sm.add_constant(joint[["mkt", "size"]])).fit(
        cov_type="HAC", cov_kwds={"maxlags": hac_lag(len(joint))}
    )
    drone_resid = pd.Series(m1.resid, index=joint.index, name="drone")

    # 天真版（只對大盤正交化）—— 用來對照「不控制規模會高估多少」
    j_naive = pd.concat({"pp": pp_ret, "mkt": mkt}, axis=1).dropna()
    m1n = sm.OLS(j_naive["pp"], sm.add_constant(j_naive["mkt"])).fit(
        cov_type="HAC", cov_kwds={"maxlags": hac_lag(len(j_naive))}
    )
    drone_resid_naive = pd.Series(m1n.resid, index=j_naive.index, name="drone_naive")

    factor_desc = {
        "members": [f"{n}({t})" for n, t in PURE_PLAY],
        "smallcap_proxy": SMALLCAP,
        "pureplay_beta_on_twii": float(m1.params["mkt"]),
        "pureplay_beta_on_size": float(m1.params["size"]),
        "pureplay_r2": float(m1.rsquared),
        "smallcap_beta_on_twii": float(m0.params["mkt"]),
        "smallcap_r2_on_twii": float(m0.rsquared),
        "obs": int(len(joint)),
        "note": "題材因子 = 純整機籃等權日對數報酬對 ^TWII + 小型股因子迴歸後的殘差（序貫正交化）",
        "contamination_caveat": "中小型 ETF 成分可能已含部分名冊股 → 真實題材效應有一部分被吸進小型股因子，故本文的題材載荷是保守（偏低）估計",
    }

    # ---- 逐檔：財報 + 價格 + 雙因子迴歸 ----
    rows = []
    for name, tkr, seg, conf in UPSTREAM:
        tk = yf.Ticker(tkr)
        info = tk.info or {}
        fin = tk.financials
        cols = list(fin.columns)[:3] if fin is not None and not fin.empty else []
        # yfinance 欄位為期末日，降序
        by_year: dict[int, dict] = {}
        for c in cols:
            y = pd.Timestamp(c).year
            rev = fin_row(fin, "Total Revenue", c)
            gp = fin_row(fin, "Gross Profit", c)
            op = fin_row(fin, "Operating Income", c)
            rd = fin_row(fin, "Research And Development", c)
            ni = fin_row(fin, "Net Income", c)
            by_year[y] = {
                "revenue": rev,
                "gross_profit": gp,
                "operating_income": op,
                "rnd": rd,
                "net_income": ni,
                "gross_margin": (gp / rev) if (gp is not None and rev) else None,
                "operating_margin": (op / rev) if (op is not None and rev) else None,
                "rnd_intensity": (rd / rev) if (rd is not None and rev) else None,
            }
        years = sorted(by_year)
        latest = years[-1] if years else None
        prev = years[-2] if len(years) >= 2 else None
        rev_yoy = None
        if latest and prev and by_year[latest]["revenue"] and by_year[prev]["revenue"]:
            rev_yoy = by_year[latest]["revenue"] / by_year[prev]["revenue"] - 1.0

        s = px[tkr].dropna()
        r = rets[tkr].dropna()
        ret_1y = float(s.iloc[-1] / s.iloc[0] - 1.0)
        vol = float(r.std() * np.sqrt(TRADING_DAYS))

        # 3 因子（控制規模）
        d = pd.concat(
            {"y": rets[tkr], "mkt": mkt, "size": size_resid, "drone": drone_resid}, axis=1
        ).dropna()
        m2 = sm.OLS(d["y"], sm.add_constant(d[["mkt", "size", "drone"]])).fit(
            cov_type="HAC", cov_kwds={"maxlags": hac_lag(len(d))}
        )
        beta_mkt = float(m2.params["mkt"])
        beta_size = float(m2.params["size"])
        beta_drone = float(m2.params["drone"])
        t_drone = float(m2.tvalues["drone"])
        p_drone = float(m2.pvalues["drone"])
        ci = m2.conf_int().loc["drone"]

        # 2 因子（不控制規模）—— 對照組
        dn = pd.concat({"y": rets[tkr], "mkt": mkt, "drone": drone_resid_naive}, axis=1).dropna()
        m2n = sm.OLS(dn["y"], sm.add_constant(dn[["mkt", "drone"]])).fit(
            cov_type="HAC", cov_kwds={"maxlags": hac_lag(len(dn))}
        )
        beta_drone_naive = float(m2n.params["drone"])
        p_drone_naive = float(m2n.pvalues["drone"])
        mcap = info.get("marketCap")
        rev_latest = by_year[latest]["revenue"] if latest else None
        ps = (mcap / rev_latest) if (mcap and rev_latest) else None

        rows.append(
            {
                "name": name,
                "ticker": tkr,
                "segment": seg,
                "ep0_confidence": conf,
                "market_cap": float(mcap) if mcap else None,
                "fy_latest": latest,
                "revenue_latest": rev_latest,
                "revenue_yoy": rev_yoy,
                "gross_margin": by_year[latest]["gross_margin"] if latest else None,
                "operating_margin": by_year[latest]["operating_margin"] if latest else None,
                "rnd_intensity": by_year[latest]["rnd_intensity"] if latest else None,
                "net_income_latest": by_year[latest]["net_income"] if latest else None,
                "price_to_sales": ps,
                "ret_1y": ret_1y,
                "ann_vol": vol,
                "beta_mkt": beta_mkt,
                "beta_size": beta_size,
                "theme_loading": beta_drone,
                "theme_t": t_drone,
                "theme_p": p_drone,
                "theme_ci_low": float(ci[0]),
                "theme_ci_high": float(ci[1]),
                "theme_loading_naive_no_size_control": beta_drone_naive,
                "theme_p_naive_no_size_control": p_drone_naive,
                "r2": float(m2.rsquared),
                "financials_by_year": by_year,
            }
        )

    df = pd.DataFrame(rows)

    # ---- 對照組：大盤與 EP0 等權籃基準 ----
    bench_s = px[BENCH].dropna()
    bench_ret = float(bench_s.iloc[-1] / bench_s.iloc[0] - 1.0)
    bench_vol = float(rets[BENCH].std() * np.sqrt(TRADING_DAYS))

    # 上游等權籃
    up_cols = [t for _, t, _, _ in UPSTREAM]
    up_basket = rets[up_cols].mean(axis=1)
    up_basket_ret = float(np.expm1(up_basket.sum()))
    up_basket_vol = float(up_basket.std() * np.sqrt(TRADING_DAYS))

    # ---- 截面關聯：題材載荷 vs 毛利率 / 規模（誠實 robustness：載荷會不會只是小型股效應？）----
    from scipy import stats as _st

    cs = df.dropna(subset=["theme_loading", "gross_margin", "market_cap"]).copy()
    cs["log_mcap"] = np.log(cs["market_cap"])
    rho_gm, p_gm = _st.spearmanr(cs["theme_loading"], cs["gross_margin"])
    rho_sz, p_sz = _st.spearmanr(cs["theme_loading"], cs["log_mcap"])
    rho_rev, p_rev = _st.spearmanr(cs["theme_loading"], cs["revenue_yoy"])
    cross_section = {
        "n": int(len(cs)),
        "spearman_loading_vs_gross_margin": {"rho": float(rho_gm), "p": float(p_gm)},
        "spearman_loading_vs_log_marketcap": {"rho": float(rho_sz), "p": float(p_sz)},
        "spearman_loading_vs_revenue_yoy": {"rho": float(rho_rev), "p": float(p_rev)},
        "caveat": "n=13，截面關聯只作描述，不足以支撐因果或可交易結論；小型股共同波動是題材載荷的競爭解釋，故一併報告與規模的關聯",
    }

    sig = df[df["theme_p"] < 0.05]
    sig_naive = df[df["theme_p_naive_no_size_control"] < 0.05]
    summary = {
        "cross_section": cross_section,
        "n_theme_significant_naive_no_size_control": int(len(sig_naive)),
        "theme_significant_naive_names": sig_naive["name"].tolist(),
        "n_upstream": len(df),
        "n_theme_significant_5pct": int(len(sig)),
        "theme_significant_names": sig["name"].tolist(),
        "median_theme_loading": float(df["theme_loading"].median()),
        "median_gross_margin": float(df["gross_margin"].dropna().median()),
        "median_revenue_yoy": float(df["revenue_yoy"].dropna().median()),
        "n_revenue_declining": int((df["revenue_yoy"] < 0).sum()),
        "n_operating_loss": int((df["operating_margin"] < 0).sum()),
        "upstream_basket_ret_1y": up_basket_ret,
        "upstream_basket_vol": up_basket_vol,
        "twii_ret_1y": bench_ret,
        "twii_vol": bench_vol,
    }

    payload = {
        "generated_at_tw": now_tw.strftime("%Y-%m-%d %H:%M:%S"),
        "price_window": {"start": START, "end_exclusive": END, "obs": int(len(rets))},
        "data_source": "yfinance (auto_adjust=True); financials = annual income statement",
        "method": {
            "returns": "daily log returns",
            "vol": "std * sqrt(252)",
            "regression_main": "r_i = a + b*TWII + s*SizeResid + c*DroneResid + e, HAC(Newey-West) SE, lag=ceil(n^(1/3))",
            "regression_naive": "r_i = a + b*TWII + c*DroneResidNaive + e（不控制規模，僅作對照）",
            "caveat": "同期描述性迴歸，非預測模型，不可用於擇時；題材因子成分股本身含非無人機業務（航太/造船），載荷應讀成『與軍工整機題材共同波動的程度』，不等於無人機營收佔比",
        },
        "theme_factor": factor_desc,
        "summary": summary,
        "upstream": rows,
    }
    OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
    print(f"wrote {OUT_JSON}")

    # ================= 圖 1：題材熱度 vs 基本面 =================
    fig, ax = plt.subplots(figsize=(11, 7))
    plot = df.dropna(subset=["revenue_yoy"])
    for seg, g in plot.groupby("segment"):
        ax.scatter(
            g["revenue_yoy"] * 100,
            g["ret_1y"] * 100,
            s=140,
            color=SEGMENT_COLOR.get(seg, "#777"),
            label=seg,
            alpha=0.85,
            edgecolors="white",
            linewidths=1.2,
        )
    for _, r in plot.iterrows():
        ax.annotate(
            f"{r['name']}",
            (r["revenue_yoy"] * 100, r["ret_1y"] * 100),
            textcoords="offset points",
            xytext=(7, 5),
            fontsize=10,
        )
    ax.axhline(bench_ret * 100, color="crimson", ls="--", lw=1.4,
               label=f"加權指數近一年 {bench_ret*100:+.1f}%")
    ax.axvline(0, color="#999", lw=1)
    ax.set_xlabel(f"FY2025 營收年增率（%）—— 基本面")
    ax.set_ylabel("近一年股價報酬（%）—— 題材熱度")
    ax.set_title("無人載具上游 13 檔：股價漲幅與營收成長的落差\n（yfinance 年度損益表 + 還原收盤價，2025-06-30～2026-07-10）")
    ax.legend(fontsize=9, loc="upper left")
    ax.grid(alpha=0.25)
    ax.margins(x=0.12, y=0.08)
    fig.tight_layout()
    p1 = ASSETS / "drone_ep1_theme_vs_fundamental.png"
    fig.savefig(p1, dpi=150)
    plt.close(fig)
    print(f"wrote {p1}")

    # ================= 圖 2：題材載荷 =================
    d2 = df.sort_values("theme_loading")
    fig, ax = plt.subplots(figsize=(11.5, 7.5))
    y = np.arange(len(d2))
    ax.barh(
        y + 0.19, d2["theme_loading_naive_no_size_control"], height=0.36,
        color="#c9c9c9", alpha=0.95, label="不控制規模（天真版）",
    )
    colors = ["#d62728" if p < 0.05 else "#8fb8d8" for p in d2["theme_p"]]
    ax.barh(y - 0.19, d2["theme_loading"], height=0.36, color=colors, alpha=0.95,
            label="控制大盤 + 小型股後（紅=5% 顯著）")
    ax.errorbar(
        d2["theme_loading"], y - 0.19,
        xerr=[d2["theme_loading"] - d2["theme_ci_low"], d2["theme_ci_high"] - d2["theme_loading"]],
        fmt="none", ecolor="#333", elinewidth=1.0, capsize=2.5,
    )
    ax.set_yticks(y)
    ax.set_yticklabels([f"{n}（{s}）" for n, s in zip(d2["name"], d2["segment"])], fontsize=10)
    ax.axvline(0, color="black", lw=1)
    ax.set_xlabel("題材載荷（對無人載具整機因子的迴歸係數，HAC 標準誤 95% 信賴區間）")
    ax.set_title("誰真的跟著無人載具題材走？\n把「小型股一起漲」的部分扣掉後，剩下多少是題材本身")
    ax.legend(fontsize=9, loc="lower right")
    ax.grid(axis="x", alpha=0.25)
    fig.tight_layout()
    p2 = ASSETS / "drone_ep1_theme_loading.png"
    fig.savefig(p2, dpi=150)
    plt.close(fig)
    print(f"wrote {p2}")

    # ================= 圖 3：毛利率 vs 市值/營收 =================
    d3 = df.dropna(subset=["gross_margin", "price_to_sales"])
    fig, ax = plt.subplots(figsize=(11, 7))
    for seg, g in d3.groupby("segment"):
        ax.scatter(
            g["gross_margin"] * 100,
            g["price_to_sales"],
            s=140,
            color=SEGMENT_COLOR.get(seg, "#777"),
            label=seg,
            alpha=0.85,
            edgecolors="white",
            linewidths=1.2,
        )
    for _, r in d3.iterrows():
        ax.annotate(
            r["name"],
            (r["gross_margin"] * 100, r["price_to_sales"]),
            textcoords="offset points",
            xytext=(7, 5),
            fontsize=10,
        )
    ax.set_xlabel("FY2025 毛利率（%）—— 技術議價力的一個代理指標")
    ax.set_ylabel("市值 ÷ FY2025 營收（倍）")
    ax.set_title("市場付多少錢買一元營收\n（描述性倍數，非估值判斷；市值取自 yfinance 查詢當日）")
    ax.legend(fontsize=9)
    ax.grid(alpha=0.25)
    fig.tight_layout()
    p3 = ASSETS / "drone_ep1_margin_multiple.png"
    fig.savefig(p3, dpi=150)
    plt.close(fig)
    print(f"wrote {p3}")

    # ---- console summary ----
    show = df[
        ["name", "ticker", "segment", "revenue_latest", "revenue_yoy", "gross_margin",
         "operating_margin", "rnd_intensity", "price_to_sales", "ret_1y", "ann_vol",
         "beta_size", "theme_loading_naive_no_size_control", "theme_loading", "theme_t",
         "theme_p", "r2"]
    ].copy()
    pd.set_option("display.width", 240)
    print(show.to_string(index=False))
    print("\nSUMMARY", json.dumps(summary, ensure_ascii=False, indent=2))
    print("\nFACTOR", json.dumps(factor_desc, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
