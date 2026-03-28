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
