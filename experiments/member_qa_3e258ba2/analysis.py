# -*- coding: utf-8 -*-
"""member_qa_3e258ba2 — 「30 年穩定每年 7%」的歷史可達成性分析

會員 yaoxk1431 問：接下來 30 年資金穩定每年成長 7%，該掌握哪些問題。
本腳本用實際歷史資料檢定「30 年年化 7%」在歷史上可不可達成、變異多大。

三個實證組件：
  (1) Volatility drag：CAGR ≈ μ − σ²/2。算要拿到 7% 幾何報酬需多高算術報酬。
  (2) 30 年滾動視窗：S&P 500 rolling 30 年年化幾何報酬分佈，達標(≥7%)比例、最差/最好。
  (3) Sequence-of-returns：block bootstrap（seed=42, B=2000）量化「平均相近、路徑不同」
      造成的終值分佈寬度；permutation 隔離「同一組報酬換順序」的純序列效果。

資料：
  主  — Shiller 月頻 S&P 500（含股息 D + CPI），1871-2023，可算含息名目 + 含息實質報酬。
  cross-check — ^GSPC 價格指數（yfinance），1928-2026，純價格報酬（不含股息）。
Shiller 含息是回答「資金成長」的正確口徑；^GSPC 純價格會低估真實投資人報酬約一個股息殖利率。

seed=42 固定。results.json 原子寫入。
"""
from __future__ import annotations

import io
import json
import os
import sys
from datetime import datetime

import numpy as np
import pandas as pd

SEED = 42
np.random.seed(SEED)

HERE = os.path.dirname(os.path.abspath(__file__))
SHILLER_CACHE = os.path.join(HERE, "shiller_monthly.csv")
GSPC_CACHE = os.path.join(HERE, "gspc_monthly.csv")

TARGET = 0.07  # 會員的目標：每年 7%
WINDOW_M = 360  # 30 年 = 360 月

# Okabe-Ito 色盤（色盲友善）
OKABE = {
    "black": "#000000", "orange": "#E69F00", "skyblue": "#56B4E9",
    "green": "#009E73", "yellow": "#F0E442", "blue": "#0072B2",
    "vermillion": "#D55E00", "purple": "#CC79A7",
}


# ---------------------------------------------------------------------------
# 資料載入
# ---------------------------------------------------------------------------
def load_shiller() -> pd.DataFrame:
    """Shiller 月頻資料 → 含息名目/實質月報酬。回傳 df: date, P, D, CPI, r_nom, r_real."""
    if os.path.exists(SHILLER_CACHE):
        df = pd.read_csv(SHILLER_CACHE, parse_dates=["date"])
    else:
        url = "http://www.econ.yale.edu/~shiller/data/ie_data.xls"
        raw = pd.read_excel(url, sheet_name="Data", skiprows=7)
        sub = raw[["Date", "P", "D", "CPI"]].copy()
        sub = sub[pd.to_numeric(sub["Date"], errors="coerce").notna()]
        sub["Date"] = sub["Date"].astype(float)
        sub = sub[pd.to_numeric(sub["P"], errors="coerce").notna()]
        # Shiller 慣例：1871.01=1月, 1871.10=10月, 1871.12=12月（小數兩位即月份）
        def to_date(x: float) -> pd.Timestamp:
            year, mm = f"{x:.2f}".split(".")
            month = int(mm) or 10
            return pd.Timestamp(year=int(year), month=month, day=1)
        sub["date"] = sub["Date"].apply(to_date)
        sub["P"] = pd.to_numeric(sub["P"], errors="coerce")
        sub["D"] = pd.to_numeric(sub["D"], errors="coerce")
        sub["CPI"] = pd.to_numeric(sub["CPI"], errors="coerce")
        df = sub[["date", "P", "D", "CPI"]].reset_index(drop=True)
        df.to_csv(SHILLER_CACHE, index=False)

    df = df.sort_values("date").reset_index(drop=True)
    # 只保留 D、CPI 都有的列（含息報酬需要 D）
    df = df[df["D"].notna() & df["CPI"].notna() & df["P"].notna()].reset_index(drop=True)
    # 含息名目月報酬：(P_t + D_t/12) / P_{t-1} - 1，D 為年化股息 → 月配 D/12
    p = df["P"].values
    d = df["D"].values
    cpi = df["CPI"].values
    r_nom = np.full(len(df), np.nan)
    r_nom[1:] = (p[1:] + d[1:] / 12.0) / p[:-1] - 1.0
    # 含息實質月報酬：名目 × 通膨折算
    infl = np.full(len(df), np.nan)
    infl[1:] = cpi[1:] / cpi[:-1]
    r_real = (1.0 + r_nom) / infl - 1.0
    df["r_nom"] = r_nom
    df["r_real"] = r_real
    return df.dropna(subset=["r_nom", "r_real"]).reset_index(drop=True)


def load_gspc() -> pd.DataFrame:
    """^GSPC 月頻價格報酬（不含股息），cross-check 用。"""
    if os.path.exists(GSPC_CACHE):
        df = pd.read_csv(GSPC_CACHE, parse_dates=["date"])
    else:
        import yfinance as yf
        raw = yf.download("^GSPC", start="1927-01-01", progress=False, auto_adjust=True)
        close = raw["Close"]
        if hasattr(close, "columns"):
            close = close.iloc[:, 0]
        m = close.resample("ME").last()
        df = pd.DataFrame({"date": m.index, "price": m.values})
        df["date"] = pd.to_datetime(df["date"]).dt.to_period("M").dt.to_timestamp()
        df.to_csv(GSPC_CACHE, index=False)
    df = df.sort_values("date").reset_index(drop=True)
    df["r_nom"] = df["price"].pct_change()
    return df.dropna(subset=["r_nom"]).reset_index(drop=True)


# ---------------------------------------------------------------------------
# 組件 1：Volatility drag
# ---------------------------------------------------------------------------
def volatility_drag(monthly_returns: np.ndarray) -> dict:
    """算術 vs 幾何年化報酬，並回推要達 7% 幾何所需算術報酬。

    口徑統一在「年報酬序列」上：把月報酬複利成不重疊的 12 月年報酬，
    對這組年報酬算算術均值、幾何均值(CAGR)與標準差，
    如此 drag = 算術 − 幾何 才與理論 σ²/2 同口徑（避免單利 vs 複利年化混用）。
    """
    r = monthly_returns
    n = len(r)
    # 不重疊 12 月年報酬
    n_years = n // 12
    annual = np.array([np.prod(1 + r[y * 12:(y + 1) * 12]) - 1 for y in range(n_years)])
    a_ann = float(np.mean(annual))                       # 年化算術報酬
    g_ann = float(np.prod(1 + annual) ** (1 / n_years) - 1)  # 年化幾何報酬 = CAGR
    sigma_ann = float(np.std(annual, ddof=1))            # 年報酬標準差
    drag_empirical = a_ann - g_ann                       # 實測 drag
    drag_theory = sigma_ann ** 2 / 2                     # 理論 drag ≈ σ²/2
    # 要達 7% 幾何所需算術（μ ≈ g + σ²/2）
    required_arith = {}
    for s in [0.10, 0.15, 0.18, 0.20, 0.25]:
        required_arith[f"sigma_{s:.2f}"] = TARGET + s ** 2 / 2
    required_arith[f"sigma_empirical_{sigma_ann:.3f}"] = TARGET + sigma_ann ** 2 / 2
    return {
        "n_months": int(n),
        "n_annual_obs": int(n_years),
        "arith_annual": a_ann,
        "geo_annual_cagr": g_ann,
        "sigma_annual": sigma_ann,
        "drag_empirical_pctpt": float(drag_empirical),
        "drag_theory_sigma2_over_2_pctpt": float(drag_theory),
        "required_arithmetic_for_7pct_geo": {k: float(v) for k, v in required_arith.items()},
    }


# ---------------------------------------------------------------------------
# 組件 2：30 年滾動視窗
# ---------------------------------------------------------------------------
def rolling_30yr(monthly_returns: np.ndarray, dates: np.ndarray) -> dict:
    """360 月滾動年化幾何報酬分佈。"""
    r = monthly_returns
    n = len(r)
    if n < WINDOW_M:
        return {"error": "insufficient data", "n_months": int(n)}
    ann_geo = []
    starts = []
    ends = []
    for i in range(0, n - WINDOW_M + 1):
        win = r[i:i + WINDOW_M]
        cagr_m = np.prod(1 + win) ** (1 / WINDOW_M) - 1
        cagr_ann = (1 + cagr_m) ** 12 - 1
        ann_geo.append(cagr_ann)
        starts.append(str(pd.Timestamp(dates[i]).date()))
        ends.append(str(pd.Timestamp(dates[i + WINDOW_M - 1]).date()))
    ann_geo = np.array(ann_geo)
    frac_hit = float(np.mean(ann_geo >= TARGET))
    worst_i = int(np.argmin(ann_geo))
    best_i = int(np.argmax(ann_geo))
    return {
        "n_windows": int(len(ann_geo)),
        "window_years": 30,
        "fraction_ge_7pct": frac_hit,
        "fraction_ge_5pct": float(np.mean(ann_geo >= 0.05)),
        "fraction_ge_4pct": float(np.mean(ann_geo >= 0.04)),
        "fraction_ge_10pct": float(np.mean(ann_geo >= 0.10)),
        "mean": float(np.mean(ann_geo)),
        "median": float(np.median(ann_geo)),
        "std": float(np.std(ann_geo, ddof=1)),
        "min": float(ann_geo.min()),
        "min_window": f"{starts[worst_i]} → {ends[worst_i]}",
        "max": float(ann_geo.max()),
        "max_window": f"{starts[best_i]} → {ends[best_i]}",
        "p10": float(np.percentile(ann_geo, 10)),
        "p25": float(np.percentile(ann_geo, 25)),
        "p75": float(np.percentile(ann_geo, 75)),
        "p90": float(np.percentile(ann_geo, 90)),
        "_dist": ann_geo.tolist(),  # 供繪圖，發佈前不入 draft
    }


# ---------------------------------------------------------------------------
# 組件 3：Sequence-of-returns（block bootstrap + permutation）
# ---------------------------------------------------------------------------
def block_bootstrap_paths(monthly_returns: np.ndarray, n_paths: int, horizon: int,
                          block: int, rng: np.random.Generator) -> np.ndarray:
    """回傳 shape (n_paths, horizon) 的重抽月報酬矩陣（circular block bootstrap）。"""
    r = monthly_returns
    n = len(r)
    out = np.empty((n_paths, horizon))
    n_blocks = int(np.ceil(horizon / block))
    for p in range(n_paths):
        seq = []
        for _ in range(n_blocks):
            start = rng.integers(0, n)
            idx = (start + np.arange(block)) % n
            seq.append(r[idx])
        out[p] = np.concatenate(seq)[:horizon]
    return out


def sequence_of_returns(monthly_returns: np.ndarray, dates: np.ndarray) -> dict:
    rng = np.random.default_rng(SEED)
    B = 2000
    block = 24  # 2 年 block，保留波動叢聚
    paths = block_bootstrap_paths(monthly_returns, B, WINDOW_M, block, rng)

    # (a) 一次投入 lump sum 10,000，30 年不動
    lump0 = 10_000.0
    gross = np.prod(1 + paths, axis=1)
    lump_terminal = lump0 * gross
    lump_cagr = gross ** (1 / WINDOW_M) - 1
    lump_cagr_ann = (1 + lump_cagr) ** 12 - 1

    # (b) 定期定額 DCA 500/月
    contrib = 500.0
    # 每筆 contrib 在第 t 月投入，複利到第 360 月：contrib * prod(1+r[t:])
    dca_terminal = np.empty(B)
    for p in range(B):
        rp = paths[p]
        # 反向累積 gross：future_factor[t] = prod(1+r[t..end])
        rev = np.cumprod((1 + rp)[::-1])[::-1]
        dca_terminal[p] = contrib * np.sum(rev)
    dca_invested = contrib * WINDOW_M

    boot = {
        "n_paths": B, "block_months": block, "horizon_months": WINDOW_M,
        "lump_sum_initial": lump0,
        "lump_terminal_p10": float(np.percentile(lump_terminal, 10)),
        "lump_terminal_p50": float(np.percentile(lump_terminal, 50)),
        "lump_terminal_p90": float(np.percentile(lump_terminal, 90)),
        "lump_cagr_p10": float(np.percentile(lump_cagr_ann, 10)),
        "lump_cagr_p50": float(np.percentile(lump_cagr_ann, 50)),
        "lump_cagr_p90": float(np.percentile(lump_cagr_ann, 90)),
        "lump_frac_beat_7pct": float(np.mean(lump_cagr_ann >= TARGET)),
        "dca_monthly_contrib": contrib,
        "dca_total_invested": dca_invested,
        "dca_terminal_p10": float(np.percentile(dca_terminal, 10)),
        "dca_terminal_p50": float(np.percentile(dca_terminal, 50)),
        "dca_terminal_p90": float(np.percentile(dca_terminal, 90)),
        "_lump_terminal": lump_terminal.tolist(),
        "_dca_terminal": dca_terminal.tolist(),
    }

    # (c) permutation：固定「同一組 30 年報酬」的 multiset，只換順序
    #     用最近 360 個月的真實報酬做示範
    fixed = monthly_returns[-WINDOW_M:].copy()
    perm_rng = np.random.default_rng(SEED)
    Bp = 2000
    lump_perm = np.empty(Bp)
    dca_perm = np.empty(Bp)

    def run_withdraw(rp: np.ndarray, start: float, monthly_wd: float):
        """回傳 (是否耗盡, 存活月數, 期末餘額)。"""
        bal = start
        for t in range(WINDOW_M):
            bal = bal * (1 + rp[t]) - monthly_wd
            if bal <= 0:
                return True, t + 1, 0.0
        return False, WINDOW_M, bal

    wd_start = 1_000_000.0
    # 確定性極端：同一組報酬「最差月份排前面(bad-early)」vs「最好月份排前面(good-early)」
    # 這是 sequence-of-returns risk 的教科書示範 — 平均報酬完全相同，只有順序不同
    def extreme_withdraw(rate: float):
        asc = np.sort(fixed)            # 差的在前（退休後馬上遇空頭）
        desc = np.sort(fixed)[::-1]     # 好的在前
        mwd = wd_start * rate / 12
        d_bad, s_bad, e_bad = run_withdraw(asc, wd_start, mwd)
        d_good, s_good, e_good = run_withdraw(desc, wd_start, mwd)
        return {
            "rate": rate,
            "bad_early_depleted": bool(d_bad), "bad_early_survive_months": int(s_bad),
            "bad_early_end_balance": float(e_bad),
            "good_early_depleted": bool(d_good), "good_early_survive_months": int(s_good),
            "good_early_end_balance": float(e_good),
        }

    wd4_end = np.empty(Bp)   # 4% 提領期末餘額
    wd4_depleted = np.zeros(Bp, dtype=bool)
    wd5_depleted = np.zeros(Bp, dtype=bool)
    wd5_survive = np.empty(Bp)
    for b in range(Bp):
        order = perm_rng.permutation(WINDOW_M)
        rp = fixed[order]
        lump_perm[b] = 10_000.0 * np.prod(1 + rp)              # 順序無關 → 應常數
        rev = np.cumprod((1 + rp)[::-1])[::-1]
        dca_perm[b] = 500.0 * np.sum(rev)                     # DCA：順序有關
        d4, _, end4 = run_withdraw(rp, wd_start, wd_start * 0.04 / 12)
        wd4_depleted[b] = d4
        wd4_end[b] = end4
        d5, s5, _ = run_withdraw(rp, wd_start, wd_start * 0.05 / 12)
        wd5_depleted[b] = d5
        wd5_survive[b] = s5

    perm = {
        "n_perms": Bp,
        "fixed_window": f"{str(pd.Timestamp(dates[-WINDOW_M]).date())} → {str(pd.Timestamp(dates[-1]).date())}",
        "note": "固定同一組 30 年月報酬，只隨機打亂順序；lump-sum 應不變，有現金流者隨順序變動",
        "lump_terminal_min": float(lump_perm.min()),
        "lump_terminal_max": float(lump_perm.max()),
        "lump_terminal_cv": float(np.std(lump_perm) / np.mean(lump_perm)),  # ≈0 → 順序無關
        "dca_terminal_p10": float(np.percentile(dca_perm, 10)),
        "dca_terminal_p50": float(np.percentile(dca_perm, 50)),
        "dca_terminal_p90": float(np.percentile(dca_perm, 90)),
        "dca_spread_p90_over_p10": float(np.percentile(dca_perm, 90) / np.percentile(dca_perm, 10)),
        "withdrawal_start": wd_start,
        "withdrawal_4pct": {
            "monthly": wd_start * 0.04 / 12,
            "frac_depleted": float(np.mean(wd4_depleted)),
            "end_balance_p10": float(np.percentile(wd4_end, 10)),
            "end_balance_p50": float(np.percentile(wd4_end, 50)),
            "end_balance_p90": float(np.percentile(wd4_end, 90)),
            "end_balance_spread_p90_over_p10": float(
                np.percentile(wd4_end, 90) / max(np.percentile(wd4_end, 10), 1.0)),
        },
        "withdrawal_5pct": {
            "monthly": wd_start * 0.05 / 12,
            "frac_depleted": float(np.mean(wd5_depleted)),
            "survive_p10_months": float(np.percentile(wd5_survive, 10)),
            "survive_p50_months": float(np.percentile(wd5_survive, 50)),
        },
        "withdrawal_extremes": {
            "note": "同一組 30 年報酬，最差月份排前(bad-early) vs 最好月份排前(good-early)",
            "rate_4pct": extreme_withdraw(0.04),
            "rate_5pct": extreme_withdraw(0.05),
            "rate_6pct": extreme_withdraw(0.06),
        },
    }
    return {"block_bootstrap": boot, "permutation": perm}


# ---------------------------------------------------------------------------
# 繪圖
# ---------------------------------------------------------------------------
def make_figures(shiller_nom_roll, shiller_real_roll, gspc_roll, drag, seq):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib import font_manager

    # 中文字體 PingFang TC
    for cand in ["PingFang TC", "PingFang SC", "Heiti TC", "Arial Unicode MS"]:
        try:
            font_manager.findfont(cand, fallback_to_default=False)
            plt.rcParams["font.sans-serif"] = [cand]
            break
        except Exception:
            continue  # silent-ok: font-candidate probing, next candidate is the handler
    plt.rcParams["axes.unicode_minus"] = False

    # --- Fig 1：30 年滾動報酬分佈（含息名目 vs 含息實質）---
    fig, ax = plt.subplots(figsize=(9, 5.2))
    nom = np.array(shiller_nom_roll["_dist"]) * 100
    real = np.array(shiller_real_roll["_dist"]) * 100
    bins = np.linspace(min(real.min(), nom.min()) - 1, max(real.max(), nom.max()) + 1, 40)
    ax.hist(nom, bins=bins, alpha=0.6, color=OKABE["blue"], label="含息名目報酬")
    ax.hist(real, bins=bins, alpha=0.6, color=OKABE["vermillion"], label="含息實質報酬（扣通膨）")
    ax.axvline(7, color=OKABE["black"], lw=2, ls="--", label="目標 7%")
    ax.set_xlabel("30 年年化幾何報酬 (%)")
    ax.set_ylabel("30 年滾動視窗數")
    ax.set_title("S&P 500 歷史 30 年滾動報酬分佈（1871–2023，月頻滾動）")
    ax.legend(frameon=False)
    fig.text(0.5, -0.02,
             f"名目達標(≥7%)比例 {shiller_nom_roll['fraction_ge_7pct']*100:.0f}%；"
             f"實質達標比例 {shiller_real_roll['fraction_ge_7pct']*100:.0f}%",
             ha="center", fontsize=10, color="#555")
    fig.tight_layout()
    fig.savefig(os.path.join(HERE, "fig1_rolling_30yr.png"), dpi=150, bbox_inches="tight")
    plt.close(fig)

    # --- Fig 2：Volatility drag（要達 7% 幾何所需算術報酬 vs 波動）---
    fig, ax = plt.subplots(figsize=(9, 5.2))
    sig = np.linspace(0.02, 0.30, 100)
    req = (TARGET + sig ** 2 / 2) * 100
    ax.plot(sig * 100, req, color=OKABE["green"], lw=2.5, label="達 7% 幾何所需算術報酬")
    ax.axhline(7, color=OKABE["black"], ls=":", lw=1.5, label="7%（若無波動，算術=幾何）")
    s_emp = drag["sigma_annual"]
    ax.scatter([s_emp * 100], [(TARGET + s_emp ** 2 / 2) * 100], s=90, color=OKABE["vermillion"],
               zorder=5, label=f"S&P 實測 σ={s_emp*100:.0f}%")
    ax.annotate(f"σ={s_emp*100:.0f}% → 需算術 {(TARGET + s_emp**2/2)*100:.1f}%",
                xy=(s_emp * 100, (TARGET + s_emp ** 2 / 2) * 100),
                xytext=(s_emp * 100 - 11, (TARGET + s_emp ** 2 / 2) * 100 + 1.2),
                fontsize=10, color=OKABE["vermillion"])
    ax.set_xlabel("年化波動率 σ (%)")
    ax.set_ylabel("所需年化算術報酬 (%)")
    ax.set_title("波動拖累：波動越大，同樣 7% 幾何目標要更高的算術報酬")
    ax.legend(frameon=False, loc="upper left")
    fig.tight_layout()
    fig.savefig(os.path.join(HERE, "fig2_volatility_drag.png"), dpi=150, bbox_inches="tight")
    plt.close(fig)

    # --- Fig 3：Block bootstrap 終值分佈（一次投入 10,000）---
    fig, ax = plt.subplots(figsize=(9, 5.2))
    lump = np.array(seq["block_bootstrap"]["_lump_terminal"])
    ax.hist(lump / 1000, bins=45, color=OKABE["skyblue"], alpha=0.85, edgecolor="white")
    p10 = seq["block_bootstrap"]["lump_terminal_p10"] / 1000
    p50 = seq["block_bootstrap"]["lump_terminal_p50"] / 1000
    p90 = seq["block_bootstrap"]["lump_terminal_p90"] / 1000
    ratio = p90 / p10
    ymax = ax.get_ylim()[1]
    for val, lab, col, yfrac in [(p10, "P10", OKABE["vermillion"], 0.78),
                                 (p50, "中位數", OKABE["black"], 0.92),
                                 (p90, "P90", OKABE["green"], 0.92)]:
        ax.axvline(val, color=col, lw=2, ls="--")
        ax.text(val + 20, ymax * yfrac, f"{lab} {val:.0f}k", ha="left", fontsize=9.5, color=col)
    ax.set_xlabel("30 年後終值（千美元，起始投入 10k）")
    ax.set_ylabel("模擬路徑數（共 2000）")
    ax.set_title(f"同樣一次投入 1 萬、30 年後終值：路徑不同，P90 是 P10 的 {ratio:.0f} 倍")
    fig.text(0.5, -0.02, "Block bootstrap（block=24 月, B=2000, seed=42），S&P 含息名目月報酬重抽",
             ha="center", fontsize=10, color="#555")
    fig.tight_layout()
    fig.savefig(os.path.join(HERE, "fig3_bootstrap_terminal.png"), dpi=150, bbox_inches="tight")
    plt.close(fig)


# ---------------------------------------------------------------------------
# 原子寫入
# ---------------------------------------------------------------------------
def atomic_write_json(path: str, obj: dict) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
    with open(tmp, "r", encoding="utf-8") as f:
        json.load(f)  # 驗證可解析
    os.replace(tmp, path)


def strip_private(obj):
    """遞迴移除 _ 開頭的大陣列鍵，供 results.json 精簡版。"""
    if isinstance(obj, dict):
        return {k: strip_private(v) for k, v in obj.items() if not k.startswith("_")}
    if isinstance(obj, list):
        return obj
    return obj


def main():
    print("[1/5] 載入 Shiller 含息資料 ...")
    sh = load_shiller()
    print(f"      Shiller: {len(sh)} 月, {sh['date'].min().date()} → {sh['date'].max().date()}")

    print("[2/5] 載入 ^GSPC 價格 cross-check ...")
    try:
        gs = load_gspc()
        print(f"      GSPC: {len(gs)} 月, {gs['date'].min().date()} → {gs['date'].max().date()}")
    except Exception as e:
        print(f"      GSPC 載入失敗（cross-check 略過）: {e}")
        gs = None

    print("[3/5] 組件 1：volatility drag ...")
    drag_nom = volatility_drag(sh["r_nom"].values)
    drag_real = volatility_drag(sh["r_real"].values)

    print("[4/5] 組件 2：30 年滾動視窗 ...")
    roll_nom = rolling_30yr(sh["r_nom"].values, sh["date"].values)
    roll_real = rolling_30yr(sh["r_real"].values, sh["date"].values)
    roll_gspc = rolling_30yr(gs["r_nom"].values, gs["date"].values) if gs is not None else {"error": "no gspc"}

    print("[5/5] 組件 3：sequence-of-returns block bootstrap ...")
    seq = sequence_of_returns(sh["r_nom"].values, sh["date"].values)

    make_figures(roll_nom, roll_real, roll_gspc, drag_nom, seq)

    results = {
        "experiment_id": "member_qa_3e258ba2",
        "question": "接下來 30 年資金穩定每年成長 7%，該掌握哪些投資問題",
        "generated_at": datetime.now().isoformat(),
        "seed": SEED,
        "data": {
            "shiller": {
                "source": "Robert Shiller ie_data.xls (含股息 D + CPI)",
                "n_months": int(len(sh)),
                "period": f"{sh['date'].min().date()} → {sh['date'].max().date()}",
                "return_type": "含息 total return（名目與扣 CPI 實質兩版）",
            },
            "gspc": {
                "source": "yfinance ^GSPC (價格指數，不含股息)",
                "n_months": int(len(gs)) if gs is not None else 0,
                "period": (f"{gs['date'].min().date()} → {gs['date'].max().date()}" if gs is not None else "NA"),
                "return_type": "純價格報酬（低估真實含息報酬約一個股息殖利率）",
                "caveat": "價格指數不含股息，故 30 年達標比例系統性低於含息口徑；僅作 cross-check",
            },
        },
        "component1_volatility_drag": {
            "nominal_total_return": drag_nom,
            "real_total_return": drag_real,
            "note": "drag = 算術年化 − 幾何年化 ≈ σ²/2；波動越大，同一幾何目標需更高算術報酬",
        },
        "component2_rolling_30yr": {
            "shiller_nominal": strip_private(roll_nom),
            "shiller_real": strip_private(roll_real),
            "gspc_price_nominal": strip_private(roll_gspc),
        },
        "component3_sequence_of_returns": strip_private(seq),
    }

    # 文章引用的顯示值（四捨五入後的衍生數字）必須是 results 的明確欄位，
    # 發佈端 content-vs-source gate 才能逐字對上（gate 建議的正規做法）。
    bb = seq["block_bootstrap"]
    req = drag_nom["required_arithmetic_for_7pct_geo"]
    results["display_values_for_article"] = {
        "rolling_ge7_nominal_pct": round(roll_nom["fraction_ge_7pct"] * 100, 1),
        "rolling_ge7_real_pct": round(roll_real["fraction_ge_7pct"] * 100, 1),
        "rolling_ge4_real_pct": round(roll_real["fraction_ge_4pct"] * 100, 1),
        "rolling_ge5_real_pct": round(roll_real["fraction_ge_5pct"] * 100, 1),
        "worst_30yr_nominal_pct": round(roll_nom["min"] * 100, 2),
        "best_30yr_nominal_pct": round(roll_nom["max"] * 100, 2),
        "n_windows": roll_nom["n_windows"],
        "real_geo_annual_pct": round(drag_real["geo_annual_cagr"] * 100, 2),
        "nominal_arith_annual_pct": round(drag_nom["arith_annual"] * 100, 2),
        "nominal_geo_annual_pct": round(drag_nom["geo_annual_cagr"] * 100, 2),
        "req_arith_for_7geo_sigma10_pct": round(req["sigma_0.10"] * 100, 1),
        "req_arith_for_7geo_sigma18_pct": round(req["sigma_empirical_0.180"] * 100, 2),
        "req_arith_for_7geo_sigma25_pct": round(req["sigma_0.25"] * 100, 1),
        "sigma_levels_pct": [10, 18, 25],
        "target_geo_pct": 7,
        "bootstrap_p10_wan": round(bb["lump_terminal_p10"] / 10000, 2),
        "bootstrap_p50_wan": round(bb["lump_terminal_p50"] / 10000, 2),
        "bootstrap_p90_wan": round(bb["lump_terminal_p90"] / 10000, 2),
        "bootstrap_p10_cagr_pct": round(bb["lump_cagr_p10"] * 100, 2),
        "bootstrap_p50_cagr_pct": round(bb["lump_cagr_p50"] * 100, 2),
        "bootstrap_p90_cagr_pct": round(bb["lump_cagr_p90"] * 100, 2),
        "bootstrap_ge7_pct": round(bb["lump_frac_beat_7pct"] * 100, 1),
        "lumpsum_terminal_cv": seq["permutation"]["lump_terminal_cv"],
        "withdrawal_rate_pct": 4,
        "percentile_90": 90,
    }

    atomic_write_json(os.path.join(HERE, "member_qa_3e258ba2_results.json"), results)
    print("\n=== 關鍵數字 ===")
    print(f"[C1] 含息名目：算術 {drag_nom['arith_annual']*100:.2f}% / 幾何 {drag_nom['geo_annual_cagr']*100:.2f}% "
          f"/ σ {drag_nom['sigma_annual']*100:.1f}% / drag 實測 {drag_nom['drag_empirical_pctpt']*100:.2f}pp "
          f"/ 理論σ²/2 {drag_nom['drag_theory_sigma2_over_2_pctpt']*100:.2f}pp")
    print(f"[C1] 達 7% 幾何：σ={drag_nom['sigma_annual']*100:.0f}% 需算術 "
          f"{(TARGET + drag_nom['sigma_annual']**2/2)*100:.2f}%")
    print(f"[C2] 名目 30 年達標(≥7%)比例 {roll_nom['fraction_ge_7pct']*100:.1f}%；"
          f"最差 {roll_nom['min']*100:.2f}%（{roll_nom['min_window']}）；最好 {roll_nom['max']*100:.2f}%")
    print(f"[C2] 實質 30 年達標(≥7%)比例 {roll_real['fraction_ge_7pct']*100:.1f}%；"
          f"達 4% 實質比例 {roll_real['fraction_ge_4pct']*100:.1f}%")
    if gs is not None:
        print(f"[C2] ^GSPC 純價格 30 年達標(≥7%)比例 {roll_gspc['fraction_ge_7pct']*100:.1f}%（不含股息，偏低）")
    bb = seq["block_bootstrap"]
    print(f"[C3] Bootstrap 一次投入 10k 終值 P10 {bb['lump_terminal_p10']:.0f} / "
          f"P50 {bb['lump_terminal_p50']:.0f} / P90 {bb['lump_terminal_p90']:.0f}")
    pm = seq["permutation"]
    print(f"[C3] 同組報酬換順序：lump-sum CV {pm['lump_terminal_cv']:.2e}（≈0，順序無關）；"
          f"DCA P90/P10 {pm['dca_spread_p90_over_p10']:.2f}x；"
          f"4% 提領期末餘額 P90/P10 {pm['withdrawal_4pct']['end_balance_spread_p90_over_p10']:.2f}x（耗盡 {pm['withdrawal_4pct']['frac_depleted']*100:.0f}%）")
    ex6 = pm["withdrawal_extremes"]["rate_6pct"]
    print(f"[C3] 6% 提領極端（同組報酬）：差月排前 期末 {ex6['bad_early_end_balance']:,.0f}（存活 {ex6['bad_early_survive_months']} 月）"
          f" vs 好月排前 期末 {ex6['good_early_end_balance']:,.0f}")


if __name__ == "__main__":
    main()
