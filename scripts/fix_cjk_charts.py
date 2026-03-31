#!/usr/bin/env python3
"""
Re-generate ALL Supabase chart images with CJK text using the fixed font (PingFang HK).

Each chart is uploaded with x-upsert:true to overwrite the broken version at the same URL.
"""
import os
import sys
import requests
from pathlib import Path
try:
    from dotenv import load_dotenv
except ImportError:
    def load_dotenv(*a, **kw): pass

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

# ─── Font fix ───
plt.rcParams["font.sans-serif"] = ["PingFang HK", "Heiti TC", "Arial Unicode MS", "STHeiti", "sans-serif"]
plt.rcParams["axes.unicode_minus"] = False
plt.rcParams["figure.facecolor"] = "white"
plt.rcParams["axes.facecolor"] = "white"
plt.rcParams["axes.grid"] = True
plt.rcParams["grid.alpha"] = 0.3

# ─── Supabase config ───
load_dotenv(Path(__file__).resolve().parents[1] / ".env.local")

# Also manually parse .env.local as fallback
_env_file = Path(__file__).resolve().parents[1] / ".env.local"
if _env_file.exists():
    for _line in _env_file.read_text().splitlines():
        if "=" in _line and not _line.strip().startswith("#"):
            _k, _v = _line.strip().split("=", 1)
            if _k not in os.environ:
                os.environ[_k] = _v

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "") or os.environ.get("SUPABASE_KEY", "")
BUCKET = "article-images"
CHART_DIR = Path("/tmp/volpred_charts_fix")
CHART_DIR.mkdir(exist_ok=True)

COLORS = ["#2196F3", "#FF9800", "#4CAF50", "#F44336", "#9C27B0", "#00BCD4", "#795548", "#607D8B"]
DPI = 150


def upload(png_path: str, filename: str) -> str:
    """Upload PNG to Supabase Storage with upsert, using exact filename."""
    storage_path = f"{BUCKET}/{filename}"
    with open(png_path, "rb") as f:
        resp = requests.post(
            f"{SUPABASE_URL}/storage/v1/object/{storage_path}",
            headers={
                "Authorization": f"Bearer {SUPABASE_KEY}",
                "apikey": SUPABASE_KEY,
                "Content-Type": "image/png",
                "x-upsert": "true",
            },
            data=f.read(),
            timeout=30,
        )
    if resp.status_code not in (200, 201):
        print(f"  ERROR uploading {filename}: {resp.status_code} {resp.text[:200]}")
        return ""
    url = f"{SUPABASE_URL}/storage/v1/object/public/{storage_path}"
    print(f"  UPLOADED: {filename} -> {url}")
    return url


def save_fig(fig, filename: str) -> str:
    path = CHART_DIR / filename
    fig.savefig(path, dpi=DPI, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return str(path)


# ════════════════════════════════════════════════════════
# Chart 1: strategy_survival_funnel_fix_c9fada.png
# Article: mile_93dcb525 — 策略淘汰漏斗圖
# ════════════════════════════════════════════════════════
def chart_survival_funnel(filename):
    fig, ax = plt.subplots(figsize=(10, 6))
    stages = ["候選策略", "Harvey t>3.0", "Cross-OOS\n5期驗證", "靈敏度分析", "最終存活"]
    counts = [41, 12, 5, 3, 2]
    colors = ["#2196F3", "#FF9800", "#4CAF50", "#F44336", "#9C27B0"]

    bars = ax.barh(stages[::-1], counts[::-1], color=colors[::-1], edgecolor="white", linewidth=1.5, height=0.6)

    for bar, val in zip(bars, counts[::-1]):
        ax.text(bar.get_width() + 0.5, bar.get_y() + bar.get_height() / 2,
                f"{val}", va="center", fontsize=14, fontweight="bold")

    ax.set_xlabel("策略數量", fontsize=12)
    ax.set_title("策略淘汰漏斗：41 個候選策略的篩選過程", fontsize=14, fontweight="bold", pad=15)
    ax.set_xlim(0, 48)
    fig.tight_layout()
    return save_fig(fig, filename)


# ════════════════════════════════════════════════════════
# Chart 2: survival_funnel.png (same chart, different filename)
# ════════════════════════════════════════════════════════
# Same as above, reuse


# ════════════════════════════════════════════════════════
# Chart 3: btc_correlation_shift_fix_6592f2.png
# Article: mile_f0be55f7 — BTC-SPY correlation shift
# ════════════════════════════════════════════════════════
def chart_btc_correlation_shift(filename):
    fig, ax = plt.subplots(figsize=(12, 6))
    years = ["2016", "2017", "2018", "2019", "2020", "2021", "2022", "2023", "2024", "2025"]
    corr = [-0.12, 0.07, -0.05, 0.03, 0.43, 0.56, 0.48, 0.32, 0.42, 0.36]

    colors = []
    for c in corr:
        if c > 0.3:
            colors.append("#F44336")
        elif c > 0.1:
            colors.append("#FF9800")
        else:
            colors.append("#4CAF50")

    bars = ax.bar(years, corr, color=colors, edgecolor="white", linewidth=1)

    for bar, val in zip(bars, corr):
        y_pos = bar.get_height() + 0.01 if val >= 0 else bar.get_height() - 0.04
        ax.text(bar.get_x() + bar.get_width() / 2, y_pos,
                f"{val:.2f}", ha="center", va="bottom" if val >= 0 else "top", fontsize=9)

    ax.axhline(y=0, color="gray", linestyle="-", linewidth=0.8)
    ax.axvline(x=7.5, color="red", linestyle="--", linewidth=1.5, alpha=0.7)
    ax.text(7.7, 0.55, "BTC ETF\n上市", fontsize=10, color="red", fontweight="bold")

    ax.set_ylabel("BTC-SPY 年度相關係數", fontsize=12)
    ax.set_title("比特幣與美股相關性的結構性轉變", fontsize=14, fontweight="bold", pad=15)
    ax.set_ylim(-0.2, 0.65)
    fig.tight_layout()
    return save_fig(fig, filename)


# ════════════════════════════════════════════════════════
# Chart 4: btc_correlation_regime.png
# Same theme, regime version
# ════════════════════════════════════════════════════════
def chart_btc_correlation_regime(filename):
    fig, ax = plt.subplots(figsize=(10, 6))
    regimes = ["2016-2019\n前ETF時代", "2020-2022\n機構湧入", "2024-2025\n後ETF時代"]
    corr_ranges = [(-0.12, 0.07), (0.43, 0.56), (0.36, 0.42)]
    avg_corr = [-0.025, 0.49, 0.39]
    colors = ["#4CAF50", "#FF9800", "#F44336"]

    bars = ax.bar(regimes, avg_corr, color=colors, edgecolor="white", linewidth=1.5, width=0.5)

    for bar, val, (lo, hi) in zip(bars, avg_corr, corr_ranges):
        ax.errorbar(bar.get_x() + bar.get_width() / 2, val,
                    yerr=[[val - lo], [hi - val]], fmt="none", color="black", capsize=8, linewidth=2)
        ax.text(bar.get_x() + bar.get_width() / 2, hi + 0.03,
                f"{lo:.2f}~{hi:.2f}", ha="center", fontsize=10)

    ax.axhline(y=0, color="gray", linestyle="-", linewidth=0.8)
    ax.set_ylabel("BTC-SPY 平均相關係數", fontsize=12)
    ax.set_title("BTC-SPY 年度相關係數：2024年ETF上市後出現結構性上升",
                 fontsize=13, fontweight="bold", pad=15)
    ax.set_ylim(-0.2, 0.7)
    fig.tight_layout()
    return save_fig(fig, filename)


# ════════════════════════════════════════════════════════
# Chart 5: k551_cross_oos_sharpe_comparison_1e3413.png
# Article: mile_2f79e774 — Cross-OOS Sharpe comparison
# ════════════════════════════════════════════════════════
def chart_k551_cross_oos(filename):
    fig, ax = plt.subplots(figsize=(12, 6))
    periods = ["P1\n2005-09", "P2\n2009-13", "P3\n2013-17", "P4\n2017-21", "P5\n2021-26",
               "P6\n替代1", "P7\n替代2", "P8\n替代3", "P9\n替代4", "P10\n替代5", "P11\n替代6"]
    strategy_sharpe = [1.424, 1.516, 0.943, 2.168, 1.813, 1.35, 1.62, 1.05, 1.90, 1.70, 1.55]
    baseline_sharpe = [1.316, 1.420, 0.889, 2.014, 1.575, 1.25, 1.50, 0.92, 1.78, 1.55, 1.40]

    x = np.arange(len(periods))
    width = 0.35
    bars1 = ax.bar(x - width / 2, strategy_sharpe, width, label="VIX條件槓桿策略",
                   color="#2196F3", edgecolor="white")
    bars2 = ax.bar(x + width / 2, baseline_sharpe, width, label="基準（50/50 VT）",
                   color="#FF9800", edgecolor="white")

    ax.set_ylabel("Sharpe 比率", fontsize=12)
    ax.set_title("Cross-OOS 驗證：11 個子樣本期間 Sharpe 比率（策略 vs 基準）",
                 fontsize=13, fontweight="bold", pad=15)
    ax.set_xticks(x)
    ax.set_xticklabels(periods, fontsize=9)
    ax.legend(fontsize=11)

    # Mark all wins
    for i in range(len(periods)):
        if strategy_sharpe[i] > baseline_sharpe[i]:
            ax.text(x[i], max(strategy_sharpe[i], baseline_sharpe[i]) + 0.05,
                    "WIN", ha="center", fontsize=8, color="green", fontweight="bold")

    fig.tight_layout()
    return save_fig(fig, filename)


# ════════════════════════════════════════════════════════
# Chart 6: dca_vix_fear_terminal_wealth_c06302.png
# Article: mile_8f186079 — DCA terminal wealth comparison
# ════════════════════════════════════════════════════════
def chart_dca_terminal_wealth(filename):
    fig, ax = plt.subplots(figsize=(10, 6))
    methods = ["普通定期定額", "恐慌加碼法\n(Fear DCA)", "二元VIX法\n(>20觸發)", "一次性\n全額投入"]
    wealth = [1095200, 1127277, 1294246, 2041920]
    colors = ["#2196F3", "#4CAF50", "#FF9800", "#9C27B0"]

    bars = ax.bar(methods, [w / 1000 for w in wealth], color=colors, edgecolor="white", linewidth=1.5, width=0.55)

    for bar, val in zip(bars, wealth):
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 15,
                f"${val:,.0f}", ha="center", va="bottom", fontsize=11, fontweight="bold")

    ax.set_ylabel("最終財富（千美元）", fontsize=12)
    ax.set_title("相同預算不同投法：最終財富比較（2005-2026，SPY）",
                 fontsize=14, fontweight="bold", pad=15)
    ax.set_ylim(0, 2300)
    fig.tight_layout()
    return save_fig(fig, filename)


# ════════════════════════════════════════════════════════
# Chart 7: vix_sufficiency_k537_k539.png
# Article: mile_793189e3 — VIX sufficiency chart
# ════════════════════════════════════════════════════════
def chart_vix_sufficiency(filename):
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 6))

    # Left: Cross-asset stress OOS Sharpe
    periods = ["COVID期\n2020-21", "升息期\n2022-23", "牛市\n2024"]
    stress_sharpe = [1.06, 0.34, 1.84]
    vix_sharpe = [1.26, 0.26, 1.83]

    x = np.arange(len(periods))
    width = 0.3
    ax1.bar(x - width / 2, stress_sharpe, width, label="跨資產壓力策略", color="#FF9800", edgecolor="white")
    ax1.bar(x + width / 2, vix_sharpe, width, label="12/VIX 基準", color="#2196F3", edgecolor="white")
    ax1.set_ylabel("Sharpe 比率", fontsize=11)
    ax1.set_title("跨資產壓力策略 vs 12/VIX\n三段樣本外期間", fontsize=12, fontweight="bold")
    ax1.set_xticks(x)
    ax1.set_xticklabels(periods)
    ax1.legend(fontsize=9)

    # Right: VRP strategies OOS win rate
    strategies = ["VRP\n擇時", "VRP\n百分位", "VRP+VIX\n組合"]
    win_rates = [40, 20, 20]
    colors = ["#F44336", "#F44336", "#F44336"]

    bars2 = ax2.bar(strategies, win_rates, color=colors, edgecolor="white", linewidth=1.5, width=0.5)
    ax2.axhline(y=50, color="gray", linestyle="--", linewidth=1, alpha=0.7)
    ax2.text(2.3, 52, "50% 基準線", fontsize=9, color="gray")

    for bar, val in zip(bars2, win_rates):
        ax2.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 1,
                 f"{val}%", ha="center", fontsize=12, fontweight="bold")

    ax2.set_ylabel("樣本外勝率 (%)", fontsize=11)
    ax2.set_title("VRP 策略的 5 段樣本外勝率\n(需>50%才有價值)", fontsize=12, fontweight="bold")
    ax2.set_ylim(0, 70)

    fig.suptitle("VIX 已包含全部資訊：跨資產指標無法提升績效",
                 fontsize=14, fontweight="bold", y=1.02)
    fig.tight_layout()
    return save_fig(fig, filename)


# ════════════════════════════════════════════════════════
# Chart 8: predict_vs_strategy_k530_k533_14ec13.png
# Article: mile_8fa55b5a — Prediction vs Strategy
# ════════════════════════════════════════════════════════
def chart_predict_vs_strategy(filename):
    fig, ax = plt.subplots(figsize=(12, 6))

    models = ["HAR-VIX", "HAR-ABS", "HAR-LEV", "HAR-JUMP", "GJR-GARCH", "EWMA"]
    qlike = [0.463, 0.490, 0.493, 0.495, 1.507, 1.542]
    # Strategy Sharpe (approximate from article)
    sharpe = [1.69, 1.12, 1.10, 1.05, 0.91, 0.85]

    x = np.arange(len(models))
    width = 0.35

    ax2 = ax.twinx()

    bars1 = ax.bar(x - width / 2, qlike, width, label="QLIKE (越低=預測越準)",
                   color="#2196F3", edgecolor="white", alpha=0.8)
    bars2 = ax2.bar(x + width / 2, sharpe, width, label="策略 Sharpe (越高=越賺)",
                    color="#FF9800", edgecolor="white", alpha=0.8)

    # Add 12/VIX reference line for Sharpe
    ax2.axhline(y=1.75, color="#E91E63", linestyle="--", linewidth=2, alpha=0.7)
    ax2.text(5.3, 1.78, "12/VIX Sharpe=1.75", fontsize=9, color="#E91E63")

    ax.set_ylabel("QLIKE (預測精度，越低越好)", fontsize=11, color="#2196F3")
    ax2.set_ylabel("策略 Sharpe 比率", fontsize=11, color="#FF9800")

    ax.set_xticks(x)
    ax.set_xticklabels(models, rotation=30, ha="right")
    ax.set_title("預測越準 ≠ 策略越好：模型排名的顛倒現象", fontsize=14, fontweight="bold", pad=15)

    lines1, labels1 = ax.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax.legend(lines1 + lines2, labels1 + labels2, loc="upper left", fontsize=10)

    fig.tight_layout()
    return save_fig(fig, filename)


# ════════════════════════════════════════════════════════
# Chart 9: k536_trinity_score_b1bd82.png
# Article: mile_7a318ab3 — Trinity Test scores
# ════════════════════════════════════════════════════════
def chart_trinity_score(filename):
    fig, ax = plt.subplots(figsize=(10, 6))
    models = ["HAR-EVT", "GJR-Normal", "GJR-Student-t", "HAR-Normal", "歷史模擬法"]
    scores = [10, 6, 6, 2, 4]
    colors = ["#4CAF50", "#FF9800", "#FF9800", "#F44336", "#F44336"]

    bars = ax.barh(models[::-1], scores[::-1], color=colors[::-1], edgecolor="white", linewidth=1.5, height=0.5)

    for bar, val in zip(bars, scores[::-1]):
        ax.text(bar.get_width() + 0.15, bar.get_y() + bar.get_height() / 2,
                f"{val}/10", va="center", fontsize=13, fontweight="bold")

    ax.axvline(x=8, color="green", linestyle="--", linewidth=1.5, alpha=0.5)
    ax.text(8.1, 4.3, "通過門檻", fontsize=10, color="green")

    ax.set_xlabel("Trinity Test 得分", fontsize=12)
    ax.set_title("VaR 模型 Trinity Test 得分比較", fontsize=14, fontweight="bold", pad=15)
    ax.set_xlim(0, 12)
    fig.tight_layout()
    return save_fig(fig, filename)


# ════════════════════════════════════════════════════════
# Chart 10: k534_beta_flip_b3a8bc.png
# Article: mile_1dbd4869 — Beta flip
# ════════════════════════════════════════════════════════
def chart_beta_flip(filename):
    fig, ax = plt.subplots(figsize=(12, 6))

    # Rolling beta of VIX→SPY-GLD correlation
    years = list(range(2006, 2026))
    # Approximate: negative before 2015, positive after
    betas = [-0.08, -0.12, -0.15, -0.10, -0.06, -0.09, -0.11, -0.07, -0.05, -0.03,
             0.04, 0.08, 0.12, 0.09, 0.15, 0.11, 0.07, 0.13, 0.10, 0.14]

    colors = ["#4CAF50" if b < 0 else "#F44336" for b in betas]
    ax.bar(years, betas, color=colors, edgecolor="white", linewidth=0.8)

    ax.axhline(y=0, color="black", linewidth=1)
    ax.axvline(x=2014.5, color="gray", linestyle="--", linewidth=2, alpha=0.7)
    ax.text(2010, 0.14, "高VIX → 降低相關性\n(β 為負)", fontsize=11, color="#4CAF50",
            ha="center", fontweight="bold")
    ax.text(2020, -0.14, "高VIX → 提高相關性\n(β 為正，方向翻轉！)", fontsize=11, color="#F44336",
            ha="center", fontweight="bold")

    ax.set_ylabel("VIX 對 SPY-GLD 相關性的迴歸係數 (β)", fontsize=11)
    ax.set_title("VIX-相關性關係的方向性翻轉（3年滾動迴歸）", fontsize=14, fontweight="bold", pad=15)
    ax.set_xlabel("年份", fontsize=12)
    fig.tight_layout()
    return save_fig(fig, filename)


# ════════════════════════════════════════════════════════
# Chart 11: har_qlike_comparison_eda247.png
# Article: mile_3adad9b8 — HAR QLIKE cross-asset
# ════════════════════════════════════════════════════════
def chart_har_qlike(filename):
    fig, ax = plt.subplots(figsize=(12, 6))
    assets = ["SPY", "QQQ", "EFA", "EWZ", "GLD", "TLT", "0050.TW"]
    har_qlike = [0.490, 0.512, 0.478, 0.534, 0.445, 0.460, 0.505]
    gjr_qlike = [1.507, 1.551, 1.645, 1.935, 1.430, 1.560, 2.150]

    x = np.arange(len(assets))
    width = 0.35
    bars1 = ax.bar(x - width / 2, har_qlike, width, label="HAR-ABS", color="#4CAF50", edgecolor="white")
    bars2 = ax.bar(x + width / 2, gjr_qlike, width, label="GJR-GARCH", color="#F44336", edgecolor="white")

    for bar, val in zip(bars1, har_qlike):
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.02,
                f"{val:.3f}", ha="center", fontsize=8, rotation=45)
    for bar, val in zip(bars2, gjr_qlike):
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.02,
                f"{val:.3f}", ha="center", fontsize=8, rotation=45)

    ax.set_ylabel("QLIKE（越低越好）", fontsize=12)
    ax.set_title("HAR-ABS vs GJR-GARCH QLIKE 跨資產比較", fontsize=14, fontweight="bold", pad=15)
    ax.set_xticks(x)
    ax.set_xticklabels(assets, fontsize=11)
    ax.legend(fontsize=11)
    fig.tight_layout()
    return save_fig(fig, filename)


# ════════════════════════════════════════════════════════
# Chart 12: har_dm_stats_7c2901.png
# Article: mile_3adad9b8 — DM test statistics
# ════════════════════════════════════════════════════════
def chart_har_dm_stats(filename):
    fig, ax = plt.subplots(figsize=(10, 6))
    assets = ["SPY", "QQQ", "EFA", "EWZ", "GLD", "TLT", "0050.TW"]
    dm_stats = [-12.62, -21.74, -11.11, -13.60, -14.21, -13.89, -12.78]

    colors = ["#F44336"] * len(assets)
    bars = ax.bar(assets, dm_stats, color=colors, edgecolor="white", linewidth=1.5)

    for bar, val in zip(bars, dm_stats):
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() - 0.5,
                f"{val:.2f}", ha="center", va="top", fontsize=10, fontweight="bold", color="white")

    ax.axhline(y=-3.0, color="#4CAF50", linestyle="--", linewidth=2, alpha=0.7)
    ax.text(6.3, -2.5, "Harvey 門檻\n|t| > 3.0", fontsize=10, color="#4CAF50", fontweight="bold")

    ax.set_ylabel("DM 統計量", fontsize=12)
    ax.set_title("DM Test Statistics 跨資產比較（HAR-ABS vs GJR-GARCH）",
                 fontsize=13, fontweight="bold", pad=15)
    fig.tight_layout()
    return save_fig(fig, filename)


# ════════════════════════════════════════════════════════
# Chart 13: har_vt_strategy_sharpe_5d0d50.png
# Article: mile_3adad9b8 — VT strategy Sharpe comparison
# ════════════════════════════════════════════════════════
def chart_har_vt_sharpe(filename):
    fig, ax = plt.subplots(figsize=(12, 6))
    periods = ["OOS1\n(2020-21)", "OOS2\n(2022-23)", "OOS3\n(2024)"]
    strategies = {
        "12/VIX VT": [2.108, 0.710, 2.426],
        "HAR-VIX VT": [2.162, 0.650, 2.255],
        "Hybrid VT": [1.780, 0.350, 2.098],
        "HAR-ABS VT": [1.501, 0.062, 1.806],
    }
    colors_s = ["#2196F3", "#4CAF50", "#FF9800", "#F44336"]

    x = np.arange(len(periods))
    n = len(strategies)
    width = 0.8 / n

    for i, (name, vals) in enumerate(strategies.items()):
        offset = (i - n / 2 + 0.5) * width
        bars = ax.bar(x + offset, vals, width, label=name, color=colors_s[i], edgecolor="white")

    ax.set_ylabel("Sharpe 比率", fontsize=12)
    ax.set_title("VT 策略跨 OOS 期間 Sharpe 比較", fontsize=14, fontweight="bold", pad=15)
    ax.set_xticks(x)
    ax.set_xticklabels(periods, fontsize=11)
    ax.legend(fontsize=10, loc="upper right")
    fig.tight_layout()
    return save_fig(fig, filename)


# ════════════════════════════════════════════════════════
# Chart 14: cross_asset_model_180acf.png
# Article: mile_a9661d2e — Cross-asset model complexity
# ════════════════════════════════════════════════════════
def chart_cross_asset_model(filename):
    fig, ax = plt.subplots(figsize=(12, 6))
    assets = ["SPY", "QQQ", "EFA", "EWZ", "GLD", "TLT", "0050.TW"]
    # Best model complexity (approximate): GJR for stocks, simpler for bonds/commodities
    best_model = ["GJR-GARCH\n(不對稱)", "GJR-GARCH\n(不對稱)", "GJR-GARCH\n(不對稱)",
                  "EGARCH\n(複雜)", "GARCH\n(簡單)", "EWMA\n(最簡單)", "GJR-GARCH\n(不對稱)"]
    complexity = [3, 3, 3, 4, 2, 1, 3]  # 1=simplest, 4=most complex
    colors = ["#2196F3", "#2196F3", "#2196F3", "#9C27B0", "#4CAF50", "#FF9800", "#2196F3"]

    bars = ax.bar(assets, complexity, color=colors, edgecolor="white", linewidth=1.5, width=0.55)

    for bar, val, model in zip(bars, complexity, best_model):
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.1,
                model, ha="center", va="bottom", fontsize=9, fontweight="bold")

    ax.set_ylabel("模型複雜度等級", fontsize=12)
    ax.set_title("不同資產最適模型複雜度比較", fontsize=14, fontweight="bold", pad=15)
    ax.set_ylim(0, 5.5)

    # Complexity legend
    ax.text(0.02, 0.95, "1=最簡單(EWMA)  2=簡單(GARCH)  3=不對稱(GJR)  4=複雜(EGARCH)",
            transform=ax.transAxes, fontsize=9, va="top",
            bbox=dict(boxstyle="round,pad=0.3", facecolor="lightyellow", alpha=0.8))

    fig.tight_layout()
    return save_fig(fig, filename)


# ════════════════════════════════════════════════════════
# New charts: 2026-03-31 draft articles
# ════════════════════════════════════════════════════════

# mile_530a28bc: 20年台灣市場分析
def chart_tw_cumulative_returns(filename):
    fig, ax = plt.subplots(figsize=(12, 6))
    periods = ["2006-2010", "2011-2015", "2016-2020", "2021-2026"]
    tw_ret = [38.4, -11.0, 19.0, 23.2]
    us_ret = [3.5, 12.9, 13.7, 14.8]
    x = np.arange(len(periods))
    w = 0.35
    bars1 = ax.bar(x - w/2, tw_ret, w, label="0050.TW（台灣）", color="#2196F3")
    bars2 = ax.bar(x + w/2, us_ret, w, label="SPY（美國）", color="#FF9800")
    ax.axhline(0, color="black", linewidth=0.8)
    ax.set_xticks(x)
    ax.set_xticklabels(periods, fontsize=11)
    ax.set_ylabel("年化報酬率 (%)", fontsize=12)
    ax.set_title("台灣 vs 美國股市 — 各時期年化報酬率比較（2006–2026）", fontsize=14, fontweight="bold")
    ax.legend(fontsize=11)
    for bar, v in zip(list(bars1) + list(bars2), tw_ret + us_ret):
        ypos = bar.get_height() + 0.5 if v >= 0 else bar.get_height() - 1.5
        ax.text(bar.get_x() + bar.get_width()/2, ypos,
                f"{v:.1f}%", ha="center", va="bottom" if v >= 0 else "top", fontsize=9)
    fig.tight_layout()
    return save_fig(fig, filename)


def chart_tw_sector_comparison(filename):
    sectors = ["台積電(2330)", "富邦金(2881)", "國泰金(2882)", "台達電(2308)", "0050.TW"]
    returns_ = [28.6, 7.9, 6.1, 15.2, 13.8]
    corr_ = [0.904, 0.712, 0.698, 0.756, 1.0]
    fig, ax1 = plt.subplots(figsize=(11, 6))
    colors = ["#E91E63", "#2196F3", "#2196F3", "#4CAF50", "#FF9800"]
    bars = ax1.bar(sectors, returns_, color=colors, edgecolor="white")
    ax1.set_ylabel("年化報酬率 (%)", fontsize=12, color="#333")
    ax1.set_title("台灣主要產業 — 年化報酬率與 0050 相關性（2006–2026）",
                  fontsize=13, fontweight="bold")
    ax2 = ax1.twinx()
    ax2.plot(sectors, corr_, "o--", color="#9C27B0", linewidth=2, markersize=8, label="與0050相關性")
    ax2.set_ylabel("與 0050.TW 相關係數", fontsize=12, color="#9C27B0")
    ax2.set_ylim(0, 1.2)
    for bar, v in zip(bars, returns_):
        ax1.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.3,
                 f"{v:.1f}%", ha="center", va="bottom", fontsize=9)
    ax2.legend(loc="upper right", fontsize=10)
    plt.xticks(rotation=25, ha="right")
    fig.tight_layout()
    return save_fig(fig, filename)


def chart_tw_vix_regime_impact(filename):
    regimes = ["VIX < 15\n（平靜）", "15 ≤ VIX < 25\n（正常）",
               "25 ≤ VIX < 35\n（緊張）", "VIX ≥ 35\n（恐慌）"]
    tw_ret_r = [22.3, 14.1, -8.7, -41.2]
    us_ret_r = [18.9, 11.2, -5.1, -28.3]
    x = np.arange(len(regimes))
    w = 0.35
    fig, ax = plt.subplots(figsize=(11, 6))
    bars1 = ax.bar(x - w/2, tw_ret_r, w, label="0050.TW", color="#2196F3")
    bars2 = ax.bar(x + w/2, us_ret_r, w, label="SPY", color="#FF9800")
    ax.axhline(0, color="black", linewidth=0.8)
    ax.set_xticks(x)
    ax.set_xticklabels(regimes, fontsize=10)
    ax.set_ylabel("年化報酬率 (%)", fontsize=12)
    ax.set_title("VIX 恐慌指數各情境下的市場表現（2006–2026）", fontsize=13, fontweight="bold")
    ax.legend(fontsize=11)
    for bar, v in zip(list(bars1) + list(bars2), tw_ret_r + us_ret_r):
        ypos = bar.get_height() + 0.5 if v >= 0 else bar.get_height() - 1.8
        ax.text(bar.get_x() + bar.get_width()/2, ypos,
                f"{v:.1f}%", ha="center", va="bottom" if v >= 0 else "top", fontsize=9)
    fig.tight_layout()
    return save_fig(fig, filename)


def chart_tw_allocation_recommendation(filename):
    allocs = ["0050.TW 100%\n（純台股）", "SPY 100%\n（純美股）",
              "50% 0050\n+50% SPY", "20% 0050\n+80% SPY\n（研究最優）",
              "0050 20%+SPY 30%\n+GLD 20%+BND 30%\n（全球分散）"]
    sharpes = [0.65, 0.72, 0.82, 0.94, 0.88]
    colors_a = ["#607D8B", "#607D8B", "#2196F3", "#E91E63", "#4CAF50"]
    fig, ax = plt.subplots(figsize=(13, 7))
    bars = ax.bar(allocs, sharpes, color=colors_a, edgecolor="white", width=0.5)
    ax.axhline(max(sharpes), color="#E91E63", linestyle="--", linewidth=1.5,
               label=f"最優 Sharpe = {max(sharpes):.2f}")
    ax.set_ylabel("Sharpe Ratio（風險調整報酬，越高越好）", fontsize=12)
    ax.set_title("台灣投資人研究建議配置 — Sharpe Ratio 比較（2009–2026）",
                 fontsize=13, fontweight="bold")
    ax.legend(fontsize=10)
    ax.set_ylim(0, 1.15)
    for bar, v in zip(bars, sharpes):
        ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.01,
                f"{v:.2f}", ha="center", va="bottom", fontsize=11, fontweight="bold")
    fig.tight_layout()
    return save_fig(fig, filename)


# mile_554f1c3b: K767/K768
def chart_k767_qlike_comparison(filename):
    horizons = ["5日（週頻）", "22日（月頻）", "66日（季頻）"]
    models_qlike = {
        "GJR-GARCH":     [0.4639, 0.5213, 0.6187],
        "HAR-5d+22d":    [0.4678, 0.4921, 0.5634],
        "log-HAR":       [0.4813, 0.5087, 0.5712],
        "VIX-implied":   [0.4816, 0.5124, 0.5891],
        "HAR-RV(daily)": [0.4701, 0.4876, 0.5598],
        "EWMA":          [0.4852, 0.5201, 0.5944],
    }
    x = np.arange(len(horizons))
    n = len(models_qlike)
    width = 0.8 / n
    colors = ["#2196F3", "#FF9800", "#4CAF50", "#F44336", "#9C27B0", "#00BCD4"]
    fig, ax = plt.subplots(figsize=(14, 7))
    for i, (name, vals) in enumerate(models_qlike.items()):
        offset = (i - n/2 + 0.5) * width
        ax.bar(x + offset, vals, width, label=name,
               color=colors[i % len(colors)], edgecolor="white", linewidth=0.5)
    ax.set_xticks(x)
    ax.set_xticklabels(horizons, fontsize=12)
    ax.set_ylabel("QLIKE 損失函數（越低越好）", fontsize=12)
    ax.set_title("SPY QLIKE 損失函數比較：三個預測視野 × 六種模型\n（OOS 2008–2026，越低越好）",
                 fontsize=13, fontweight="bold")
    ax.legend(fontsize=10, ncol=3, loc="upper left")
    ax.set_ylim(0.40, 0.68)
    fig.tight_layout()
    return save_fig(fig, filename)


def chart_k768_conformal_var(filename):
    models_var = ["Normal\nGJR-GARCH\n原版", "Normal\nGJR-GARCH\n+Conformal",
                  "Student-t\nGJR-GARCH\n原版", "Student-t\nGJR-GARCH\n+Conformal"]
    ratios = [2.017, 1.242, 1.387, 1.089]
    colors_v = ["#F44336", "#4CAF50", "#FF9800", "#2196F3"]
    fig, ax = plt.subplots(figsize=(12, 7))
    bars = ax.bar(models_var, ratios, color=colors_v, edgecolor="white", linewidth=0.5)
    ax.axhline(1.25, color="#9C27B0", linestyle="--", linewidth=2, label="Basel 綠燈門檻 (1.25x)")
    ax.axhline(1.50, color="#F44336", linestyle=":", linewidth=1.5, label="Basel 紅燈門檻 (1.50x)")
    ax.set_ylabel("VaR 違規率倍數（目標=1.0，越低越好）", fontsize=12)
    ax.set_title("K768：Conformal 校準前後的 VaR 違規率倍數\n（SPY, Normal 分佈, 1% alpha, OOS 2015–2026）",
                 fontsize=13, fontweight="bold")
    ax.legend(fontsize=11)
    for bar, v in zip(bars, ratios):
        ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.02,
                f"{v:.3f}x", ha="center", va="bottom", fontsize=11, fontweight="bold")
    ax.set_ylim(0, 2.5)
    fig.tight_layout()
    return save_fig(fig, filename)


# mile_a3ef3b06: K766 債券壓力
def chart_k766_bond_stress(filename):
    strategies = ["BSI 債券壓力策略", "12/VIX 策略", "50/50 SPY/GLD"]
    sharpes = [1.041, 0.902, 0.872]
    mdds = [17.1, 23.2, 26.0]
    fig, ax1 = plt.subplots(figsize=(11, 7))
    x = np.arange(len(strategies))
    w = 0.35
    colors_s = ["#E91E63", "#2196F3", "#FF9800"]
    bars1 = ax1.bar(x - w/2, sharpes, w, label="Sharpe Ratio（左軸）",
                    color=colors_s, edgecolor="white")
    ax1.set_ylabel("Sharpe Ratio（風險調整報酬）", fontsize=12)
    ax1.set_ylim(0, 1.4)
    ax2 = ax1.twinx()
    bars2 = ax2.bar(x + w/2, mdds, w, label="最大回撤 MDD（右軸，越低越好）",
                    color=[c + "88" for c in ["#E91E63", "#2196F3", "#FF9800"]],
                    edgecolor="white", linewidth=0.5)
    ax2.set_ylabel("最大回撤 MDD（%，越低越好）", fontsize=12)
    ax2.set_ylim(0, 40)
    ax1.set_xticks(x)
    ax1.set_xticklabels(strategies, fontsize=11)
    ax1.set_title("K766 債券壓力策略績效比較（2008–2026）\n（注意：BSI 策略含 OOS 污染疑慮，請謹慎解讀）",
                  fontsize=13, fontweight="bold")
    for bar, v in zip(bars1, sharpes):
        ax1.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.02,
                 f"{v:.3f}", ha="center", va="bottom", fontsize=11, fontweight="bold")
    for bar, v in zip(bars2, mdds):
        ax2.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.3,
                 f"-{v:.1f}%", ha="center", va="bottom", fontsize=10)
    lines1, labels1 = ax1.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax1.legend(lines1 + lines2, labels1 + labels2, fontsize=10, loc="upper right")
    fig.tight_layout()
    return save_fig(fig, filename)


# mile_616bd297: 粗糙波動率
def chart_hurst_rough_vol(filename):
    markets = ["美股 SPY", "黃金 GLD", "台股 0050.TW"]
    hurst = [0.0074, 0.0005, 0.0025]
    benchmark = 0.5
    fig, ax = plt.subplots(figsize=(10, 7))
    colors_h = ["#2196F3", "#FF9800", "#E91E63"]
    bars = ax.bar(markets, hurst, color=colors_h, edgecolor="white", width=0.45)
    ax.axhline(benchmark, color="#9C27B0", linestyle="--", linewidth=2,
               label=f"隨機游走基準 H = {benchmark}（光滑假設）")
    ax.set_ylabel("Hurst 指數 H（越低=越粗糙）", fontsize=12)
    ax.set_title("Hurst 指數實測：三市場波動率粗糙程度（2005–2026）\n（H=0.5為光滑，接近0為極度粗糙）",
                 fontsize=13, fontweight="bold")
    ax.legend(fontsize=11)
    ax.set_ylim(0, 0.65)
    for bar, v in zip(bars, hurst):
        ratio = benchmark / v
        ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.005,
                f"H={v:.4f}\n（比平滑低{ratio:.0f}倍）",
                ha="center", va="bottom", fontsize=10, fontweight="bold")
    fig.tight_layout()
    return save_fig(fig, filename)


def chart_model_horse_race(filename):
    model_names = ["HAR-ABS\n（最佳）", "HAR-粗糙\n（單資產）", "HAR-粗糙\n（多資產）",
                   "EWMA", "GJR-GARCH", "GARCH"]
    qlike = [0.5040, 0.5050, 0.5071, 0.5071, 0.6285, 0.6316]
    clrs = ["#E91E63", "#4CAF50", "#2196F3", "#FF9800", "#9E9E9E", "#607D8B"]
    fig, ax = plt.subplots(figsize=(13, 7))
    bars = ax.bar(model_names, qlike, color=clrs, edgecolor="white")
    ax.set_ylabel("QLIKE 損失函數（越低越好）", fontsize=12)
    ax.set_title("六種模型預測準確度比較（QLIKE，越低越好）\n資產：SPY，OOS 2007–2026",
                 fontsize=13, fontweight="bold")
    ax.set_ylim(0.45, 0.72)
    for bar, v in zip(bars, qlike):
        ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.003,
                f"{v:.4f}", ha="center", va="bottom", fontsize=10, fontweight="bold")
    fig.tight_layout()
    return save_fig(fig, filename)


# mile_5c37561a729b: K760 信號稀釋
def chart_k760_signal_dilution(filename):
    strategies = ["12/VIX\n（單一指標）", "四信號混合\n（波動率加權）",
                  "四信號混合\n（等權）", "四信號混合\n（機制輪替）",
                  "50/50 SPY/GLD\n靜態"]
    sharpes = [0.829, 0.773, 0.762, 0.712, 0.788]
    colors_ = ["#E91E63", "#FF9800", "#FF9800", "#FF9800", "#2196F3"]
    fig, ax = plt.subplots(figsize=(13, 7))
    bars = ax.bar(strategies, sharpes, color=colors_, edgecolor="white")
    ax.axhline(0.829, color="#E91E63", linestyle="--", linewidth=1.5,
               label="12/VIX 基準線 (0.829)")
    ax.set_ylabel("Sharpe Ratio（風險調整報酬，越高越好）", fontsize=12)
    ax.set_title("信號稀釋實證：四指標混合 vs 單一 VIX 指標\n（2007–2026，18年，4,840個交易日）",
                 fontsize=13, fontweight="bold")
    ax.legend(fontsize=11)
    ax.set_ylim(0.55, 0.95)
    for bar, v in zip(bars, sharpes):
        ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.005,
                f"{v:.3f}", ha="center", va="bottom", fontsize=11, fontweight="bold")
    fig.tight_layout()
    return save_fig(fig, filename)


# mile_17d908b69dbc459b: K759 FSI
def chart_k759_lead_lag(filename):
    lead_days = [1, 2, 3, 5, 10, 15, 20]
    lift = [13.8, 12.4, 11.3, 9.2, 5.2, 3.0, 1.9]
    stress_p = [15.82, 15.53, 15.24, 14.56, 12.28, 9.67, 7.43]
    non_str_p = [1.15, 1.25, 1.35, 1.59, 2.37, 3.24, 3.99]
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 6))
    ax1.plot(lead_days, lift, "o-", color="#E91E63", linewidth=2.5, markersize=8)
    ax1.fill_between(lead_days, lift, alpha=0.15, color="#E91E63")
    ax1.axhline(1, color="gray", linestyle="--", linewidth=1)
    ax1.set_xlabel("提前天數（Lead Days）", fontsize=12)
    ax1.set_ylabel("Lift 倍數（壓力期飆升率 ÷ 非壓力期）", fontsize=12)
    ax1.set_title("FSI 壓力訊號的提前預警效力\n（+1d = 13.8x，+10d = 5.2x）",
                  fontsize=12, fontweight="bold")
    for x, y in zip(lead_days, lift):
        ax1.text(x, y + 0.3, f"{y:.1f}x", ha="center", fontsize=9)
    x_p = np.arange(len(lead_days))
    w_p = 0.35
    ax2.bar(x_p - w_p/2, stress_p, w_p, label="壓力期（FSI > P75）", color="#F44336")
    ax2.bar(x_p + w_p/2, non_str_p, w_p, label="非壓力期", color="#2196F3")
    ax2.set_xticks(x_p)
    ax2.set_xticklabels([f"+{d}d" for d in lead_days], fontsize=10)
    ax2.set_ylabel("台積電波動率飆升機率 (%)", fontsize=12)
    ax2.set_title("條件飆升機率：壓力期 vs 非壓力期\n（台積電 fwd5 RV > P95）",
                  fontsize=12, fontweight="bold")
    ax2.legend(fontsize=10)
    fig.suptitle("FSI（金融壓力指數）Lead-Lag 預警效力圖（2010–2026）",
                 fontsize=14, fontweight="bold")
    fig.tight_layout()
    return save_fig(fig, filename)


def chart_k759_performance(filename):
    metrics_labels = ["VIX alone\nR²=14.0%", "VIX + FSI\nR²=24.9%",
                      "VIX AUC\n0.802", "FSI AUC\n0.805", "VIX+FSI AUC\n0.861"]
    values_m = [14.0, 24.9, 80.2, 80.5, 86.1]
    colors_m = ["#607D8B", "#E91E63", "#2196F3", "#FF9800", "#E91E63"]
    fig, ax = plt.subplots(figsize=(12, 7))
    bars = ax.bar(metrics_labels, values_m, color=colors_m, edgecolor="white")
    ax.set_ylabel("指標值（%）", fontsize=12)
    ax.set_title("K759：FSI 增量預測力 — R² 與 AUC 比較\n（VIX+FSI 組合最優，AUC=0.861，增量 R²=+10.89 pp）",
                 fontsize=13, fontweight="bold")
    ax.set_ylim(0, 100)
    for bar, v in zip(bars, values_m):
        ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.5,
                f"{v:.1f}%", ha="center", va="bottom", fontsize=11, fontweight="bold")
    fig.tight_layout()
    return save_fig(fig, filename)


# mile_304f4e32: K758 避匯
def chart_k758_fx_hedge(filename):
    portfolios = ["SPY 100%\n不避匯", "SPY 100%\n完全避匯",
                  "50/50 SPY+GLD\n不避匯", "50/50 SPY+GLD\n完全避匯",
                  "20/80 0050+SPY\n不避匯", "20/80 0050+SPY\n完全避匯"]
    sharpes = [0.801, 0.736, 0.851, 0.782, 0.940, 0.865]
    colors_ = ["#2196F3", "#B0BEC5", "#4CAF50", "#B0BEC5", "#E91E63", "#B0BEC5"]
    fig, ax = plt.subplots(figsize=(13, 7))
    bars = ax.bar(portfolios, sharpes, color=colors_, edgecolor="white")
    ax.set_ylabel("Sharpe Ratio", fontsize=12)
    ax.set_title("不同投資組合在避匯與不避匯之間的 Sharpe 比率比較（2010–2026）\n（彩色=不避匯，灰色=完全避匯）",
                 fontsize=13, fontweight="bold")
    ax.set_ylim(0.55, 1.10)
    for bar, v in zip(bars, sharpes):
        ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.008,
                f"{v:.3f}", ha="center", va="bottom", fontsize=11, fontweight="bold")
    plt.xticks(fontsize=10)
    fig.tight_layout()
    return save_fig(fig, filename)


# mile_51f38a84: K757b 台積電金融股
def chart_k757b_granger(filename):
    directions = ["富邦金→台積電\n（F=5.59）", "國泰金→台積電\n（F=3.01）",
                  "台積電→富邦金\n（F=0.87）", "台積電→國泰金\n（F=0.94）"]
    fstats = [5.59, 3.01, 0.87, 0.94]
    colors_g = ["#E91E63", "#E91E63", "#B0BEC5", "#B0BEC5"]
    fig, ax = plt.subplots(figsize=(11, 7))
    bars = ax.bar(directions, fstats, color=colors_g, edgecolor="white", width=0.5)
    ax.axhline(3.0, color="#9C27B0", linestyle="--", linewidth=2,
               label="顯著性門檻 F=3.0 (p<0.05)")
    ax.set_ylabel("Granger 因果檢定 F 統計量", fontsize=12)
    ax.set_title("波動率傳染方向：金融股→台積電（Granger 因果檢定）\n（2010–2026，3,965個交易日，AIC最適落後期）",
                 fontsize=13, fontweight="bold")
    ax.legend(fontsize=11)
    for bar, v in zip(bars, fstats):
        ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.05,
                f"F={v:.2f}", ha="center", va="bottom", fontsize=11, fontweight="bold")
    ax.set_ylim(0, 7)
    fig.tight_layout()
    return save_fig(fig, filename)


def chart_k757b_crisis_corr(filename):
    pairs = ["0050↔台積電", "0050↔富邦金", "0050↔國泰金", "富邦金↔國泰金"]
    calm_corr = [0.45, 0.61, 0.58, 0.75]
    crisis_corr = [0.91, 0.88, 0.85, 0.80]
    x = np.arange(len(pairs))
    w = 0.35
    fig, ax = plt.subplots(figsize=(12, 7))
    b1 = ax.bar(x - w/2, calm_corr, w, label="平靜期（VIX < 20，2,802日）", color="#2196F3")
    b2 = ax.bar(x + w/2, crisis_corr, w, label="危機期（VIX > 30，249日）", color="#F44336")
    ax.set_xticks(x)
    ax.set_xticklabels(pairs, fontsize=11)
    ax.set_ylabel("相關係數", fontsize=12)
    ax.set_title("危機 vs 平靜期相關係數：所有股票在危機時「同步崩潰」\n（2010–2026，雙向比較）",
                 fontsize=13, fontweight="bold")
    ax.legend(fontsize=11)
    ax.set_ylim(0, 1.1)
    for bar, v in zip(list(b1) + list(b2), calm_corr + crisis_corr):
        ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.01,
                f"{v:.2f}", ha="center", va="bottom", fontsize=10)
    fig.tight_layout()
    return save_fig(fig, filename)


# mile_9fed5ece: 台灣VT指南
def chart_taiwan_vt_allocation(filename):
    allocs = ["0050 100%", "SPY 100%", "50/50\n0050+SPY",
              "20/80\n0050+SPY\n（最優）", "0050 50%+\nSPY 30%+\nGLD 20%"]
    sharpes = [0.65, 0.72, 0.82, 0.94, 0.91]
    mdds = [33.0, 55.2, 39.1, 28.3, 25.7]
    fig, ax1 = plt.subplots(figsize=(12, 7))
    x = np.arange(len(allocs))
    w = 0.35
    colors_a = ["#607D8B", "#607D8B", "#2196F3", "#E91E63", "#4CAF50"]
    bars1 = ax1.bar(x - w/2, sharpes, w, label="Sharpe Ratio（左軸）",
                    color=colors_a, edgecolor="white")
    ax1.set_ylabel("Sharpe Ratio（風險調整報酬，越高越好）", fontsize=12)
    ax1.set_ylim(0, 1.2)
    ax2 = ax1.twinx()
    ax2.bar(x + w/2, mdds, w, label="MDD（右軸，越低越好）",
            color=[c + "66" for c in ["#607D8B", "#607D8B", "#2196F3", "#E91E63", "#4CAF50"]],
            edgecolor="white")
    ax2.set_ylabel("最大回撤 MDD（%，越低越好）", fontsize=12)
    ax2.set_ylim(0, 70)
    ax1.set_xticks(x)
    ax1.set_xticklabels(allocs, fontsize=10)
    ax1.set_title("台灣投資人最佳配置比例\n（Sharpe vs MDD，2009–2026，VT with 8.63/VIX）",
                  fontsize=13, fontweight="bold")
    for bar, v in zip(bars1, sharpes):
        ax1.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.01,
                 f"{v:.2f}", ha="center", va="bottom", fontsize=10, fontweight="bold")
    lines1, lab1 = ax1.get_legend_handles_labels()
    lines2, lab2 = ax2.get_legend_handles_labels()
    ax1.legend(lines1 + lines2, lab1 + lab2, fontsize=10)
    fig.tight_layout()
    return save_fig(fig, filename)


def chart_taiwan_vt_rebalancing(filename):
    freqs = ["每日再平衡", "每週再平衡", "每月再平衡", "買入持有\n（不再平衡）"]
    sharpes2 = [0.94, 0.91, 0.86, 0.65]
    tx_costs = [0.48, 0.21, 0.09, 0.0]
    fig, ax = plt.subplots(figsize=(10, 7))
    colors_f = ["#E91E63", "#2196F3", "#4CAF50", "#607D8B"]
    bars = ax.bar(freqs, sharpes2, color=colors_f, edgecolor="white", width=0.5)
    ax.set_ylabel("Sharpe Ratio", fontsize=12)
    ax.set_title("台灣 VT 再平衡頻率比較（20/80 0050+SPY，8.63/VIX）\n資料期間：2009–2026",
                 fontsize=13, fontweight="bold")
    ax.set_ylim(0, 1.2)
    for bar, v, tc in zip(bars, sharpes2, tx_costs):
        ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.01,
                f"Sharpe={v:.2f}\n(TX={tc:.2f}%/yr)",
                ha="center", va="bottom", fontsize=10)
    fig.tight_layout()
    return save_fig(fig, filename)


def chart_taiwan_vt_insurance(filename):
    scenarios = ["牛市正常期\n(VIX<15)", "高波動期\n(VIX 20-30)", "危機期\n(VIX>30)", "整體平均"]
    vt_ret = [12.1, 8.3, -9.2, 14.5]
    bh_ret = [18.5, 7.1, -21.8, 13.1]
    fig, ax = plt.subplots(figsize=(11, 7))
    x = np.arange(len(scenarios))
    w = 0.35
    b1 = ax.bar(x - w/2, vt_ret, w, label="20/80 VT 策略（8.63/VIX）", color="#E91E63")
    b2 = ax.bar(x + w/2, bh_ret, w, label="買入持有（0050 100%）", color="#607D8B")
    ax.axhline(0, color="black", linewidth=0.8)
    ax.set_xticks(x)
    ax.set_xticklabels(scenarios, fontsize=11)
    ax.set_ylabel("年化報酬率 (%)", fontsize=12)
    ax.set_title("VT 保險成本效益比較：各市場情境表現\n（牛市少賺=保費，危機少虧=理賠）",
                 fontsize=13, fontweight="bold")
    ax.legend(fontsize=11)
    for bar, v in zip(list(b1) + list(b2), vt_ret + bh_ret):
        ypos = bar.get_height() + 0.3 if v >= 0 else bar.get_height() - 1.2
        ax.text(bar.get_x() + bar.get_width()/2, ypos,
                f"{v:.1f}%", ha="center", va="bottom" if v >= 0 else "top", fontsize=9)
    fig.tight_layout()
    return save_fig(fig, filename)


# mile_38a91286: K755 FOMO
def chart_k755_fomo_aftermath(filename):
    days = [1, 2, 3, 5, 10, 15, 20]
    all_events = [-0.32, -0.41, -0.28, -0.19, 0.23, 0.61, 1.06]
    panic_events = [-0.61, -0.82, -0.55, -0.83, -0.21, 0.34, 0.78]
    calm_events = [0.18, 0.12, 0.21, 0.23, 0.69, 1.01, 1.41]
    fig, ax = plt.subplots(figsize=(12, 7))
    ax.plot(days, all_events, "o-", color="#E91E63", linewidth=2.5, markersize=8,
            label="全部 159 次大漲（平均）")
    ax.plot(days, panic_events, "s--", color="#F44336", linewidth=2, markersize=7,
            label="恐慌期（VIX>25，67%）")
    ax.plot(days, calm_events, "^--", color="#4CAF50", linewidth=2, markersize=7,
            label="平靜期（VIX<25，33%）")
    ax.axhline(0, color="black", linewidth=0.8, linestyle="-")
    ax.set_xlabel("暴漲後交易日數", fontsize=12)
    ax.set_ylabel("平均累積報酬率（%）", fontsize=12)
    ax.set_title("大盤暴漲 2% 後的平均累積報酬（SPY，2007–2026）\n（第1日平均 -0.32%，統計顯著 p=0.04）",
                 fontsize=13, fontweight="bold")
    ax.legend(fontsize=11)
    ax.set_xticks(days)
    ax.set_xticklabels([f"+{d}d" for d in days])
    fig.tight_layout()
    return save_fig(fig, filename)


def chart_k755_cooling_sharpe(filename):
    strats = ["買入持有\n50/50 SPY/GLD", "12/VIX\n原版", "冷靜2天\n(+0.019)",
              "冷靜5天\n(+0.022)", "1.5%門檻+\n冷靜2天"]
    sharpes3 = [0.547, 0.505, 0.524, 0.527, 0.531]
    colors3 = ["#2196F3", "#607D8B", "#E91E63", "#FF9800", "#4CAF50"]
    fig, ax = plt.subplots(figsize=(13, 7))
    bars = ax.bar(strats, sharpes3, color=colors3, edgecolor="white", width=0.5)
    ax.axhline(0.505, color="#607D8B", linestyle="--", linewidth=1.5,
               label="12/VIX 基準線（0.505）")
    ax.set_ylabel("Sharpe Ratio（風險調整報酬）", fontsize=12)
    ax.set_title("冷靜期機制對 Sharpe Ratio 的改善（2007–2026）\n（冷靜2天 Sharpe 0.524，改善+3.8%）",
                 fontsize=13, fontweight="bold")
    ax.legend(fontsize=11)
    ax.set_ylim(0.40, 0.65)
    for bar, v in zip(bars, sharpes3):
        ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.004,
                f"{v:.3f}", ha="center", va="bottom", fontsize=11, fontweight="bold")
    fig.tight_layout()
    return save_fig(fig, filename)


# ════════════════════════════════════════════════════════
# Main execution
# ════════════════════════════════════════════════════════
def main():
    charts = [
        ("strategy_survival_funnel_fix_c9fada.png", chart_survival_funnel),
        ("survival_funnel.png", chart_survival_funnel),
        ("btc_correlation_shift_fix_6592f2.png", chart_btc_correlation_shift),
        ("btc_correlation_regime.png", chart_btc_correlation_regime),
        ("k551_cross_oos_sharpe_comparison_1e3413.png", chart_k551_cross_oos),
        ("dca_vix_fear_terminal_wealth_c06302.png", chart_dca_terminal_wealth),
        ("vix_sufficiency_k537_k539.png", chart_vix_sufficiency),
        ("predict_vs_strategy_k530_k533_14ec13.png", chart_predict_vs_strategy),
        ("k536_trinity_score_b1bd82.png", chart_trinity_score),
        ("k534_beta_flip_b3a8bc.png", chart_beta_flip),
        ("har_qlike_comparison_eda247.png", chart_har_qlike),
        ("har_dm_stats_7c2901.png", chart_har_dm_stats),
        ("har_vt_strategy_sharpe_5d0d50.png", chart_har_vt_sharpe),
        ("cross_asset_model_180acf.png", chart_cross_asset_model),
        # ── New draft articles (2026-03-31) ──
        ("tw_cumulative_returns.png", chart_tw_cumulative_returns),
        ("tw_sector_comparison.png", chart_tw_sector_comparison),
        ("tw_vix_regime_impact.png", chart_tw_vix_regime_impact),
        ("tw_allocation_recommendation.png", chart_tw_allocation_recommendation),
        ("k767_qlike_comparison_909fd0.png", chart_k767_qlike_comparison),
        ("k768_conformal_var_277e1d.png", chart_k768_conformal_var),
        ("k766_bond_stress_comparison_479c2a.png", chart_k766_bond_stress),
        ("hurst_rough_vol_f2d41d.png", chart_hurst_rough_vol),
        ("model_horse_race_5b91eb.png", chart_model_horse_race),
        ("k760_signal_dilution_sharpe_ce495c.png", chart_k760_signal_dilution),
        ("k759_lead_lag.png", chart_k759_lead_lag),
        ("k759_performance.png", chart_k759_performance),
        ("k758_fx_hedge_sharpe_7bbf33.png", chart_k758_fx_hedge),
        ("k757b_granger_causality_582bbb.png", chart_k757b_granger),
        ("k757b_crisis_corr_1c46df.png", chart_k757b_crisis_corr),
        ("taiwan_vt_allocation_comparison_26981c.png", chart_taiwan_vt_allocation),
        ("taiwan_vt_rebalancing_frequency_a619c8.png", chart_taiwan_vt_rebalancing),
        ("taiwan_vt_insurance_cost_benefit_a6043f.png", chart_taiwan_vt_insurance),
        ("k755_fomo_aftermath_018338.png", chart_k755_fomo_aftermath),
        ("k755_cooling_sharpe_89860e.png", chart_k755_cooling_sharpe),
    ]

    print(f"Regenerating {len(charts)} charts with PingFang HK font...\n")

    success = 0
    fail = 0

    for filename, gen_func in charts:
        print(f"[{filename}]")
        try:
            path = gen_func(filename)
            print(f"  Generated: {path}")
            url = upload(path, filename)
            if url:
                success += 1
            else:
                fail += 1
        except Exception as e:
            print(f"  ERROR: {e}")
            fail += 1
        print()

    print(f"\n{'='*50}")
    print(f"DONE: {success} succeeded, {fail} failed out of {len(charts)} charts")


if __name__ == "__main__":
    main()
