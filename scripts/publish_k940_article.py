#!/usr/bin/env python3
"""
K940 研究文章發佈腳本
ML vs 計量經濟學的波動率預測對決
"""

import sys
import os
sys.path.insert(0, '/Users/yhlai0911/Desktop/volpred-research')

import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from volpred.charts import upload_chart, embed_chart
from src.volpred.publisher.publisher import Publisher

# ── 圖表 1：QLIKE 模型比較（log scale）────────────────────────────
def make_qlike_comparison_chart():
    models = ['MF-GJR(VIX)', 'Random Forest', 'GJR(1,1,1)', 'GARCH(1,1)', 'Ridge', 'MLP']
    qlike_vals = [1.4582, 1.5237, 1.5459, 1.5813, 40278.5, 651520.2]
    colors = ['#2196F3', '#4CAF50', '#66BB6A', '#A5D6A7', '#FF7043', '#D32F2F']

    fig, axes = plt.subplots(1, 2, figsize=(14, 6))
    fig.suptitle('K940: 波動率預測模型 QLIKE 比較 (SPY OOS 2016–2025)', fontsize=14, fontweight='bold')

    # Left: full scale (shows catastrophic failures)
    bars_full = axes[0].bar(models, qlike_vals, color=colors, edgecolor='white', linewidth=0.5)
    axes[0].set_title('全量 QLIKE（含失敗模型）', fontsize=11)
    axes[0].set_ylabel('QLIKE（越低越好）')
    axes[0].set_yscale('log')
    axes[0].set_xticklabels(models, rotation=30, ha='right', fontsize=9)
    # Annotate
    for bar, val in zip(bars_full, qlike_vals):
        if val > 1000:
            axes[0].text(bar.get_x() + bar.get_width()/2, val * 1.5,
                         f'{val:.0f}', ha='center', va='bottom', fontsize=7, color='#D32F2F', fontweight='bold')
        else:
            axes[0].text(bar.get_x() + bar.get_width()/2, val * 1.1,
                         f'{val:.4f}', ha='center', va='bottom', fontsize=8)

    # Right: zoom on viable models only
    viable_models = ['MF-GJR(VIX)', 'Random Forest', 'GJR(1,1,1)', 'GARCH(1,1)']
    viable_vals = [1.4582, 1.5237, 1.5459, 1.5813]
    viable_colors = ['#2196F3', '#4CAF50', '#66BB6A', '#A5D6A7']
    bars_zoom = axes[1].bar(viable_models, viable_vals, color=viable_colors, edgecolor='white', linewidth=0.5)
    axes[1].set_title('放大可行模型（Ridge 與 MLP 不納入）', fontsize=11)
    axes[1].set_ylabel('QLIKE（越低越好）')
    axes[1].set_ylim(1.40, 1.62)
    axes[1].set_xticklabels(viable_models, rotation=20, ha='right', fontsize=10)
    for bar, val in zip(bars_zoom, viable_vals):
        axes[1].text(bar.get_x() + bar.get_width()/2, val + 0.002,
                     f'{val:.4f}', ha='center', va='bottom', fontsize=10, fontweight='bold')

    # DM significance markers on right chart
    dm_labels = ['★★★\nt=-4.46\n(DM vs MF-GJR)', '★★★\nt=-4.11', '★★★\nt=-4.95', '★★★\nt=-6.68']
    for i, (bar, label) in enumerate(zip(bars_zoom, dm_labels)):
        if i > 0:
            axes[1].text(bar.get_x() + bar.get_width()/2, viable_vals[i] - 0.012,
                         label, ha='center', va='top', fontsize=6.5, color='#555')

    patch_trad = mpatches.Patch(color='#2196F3', label='計量模型（GARCH 族）')
    patch_ml = mpatches.Patch(color='#4CAF50', label='ML（可行）')
    patch_fail = mpatches.Patch(color='#D32F2F', label='ML（失敗）')
    axes[0].legend(handles=[patch_trad, patch_ml, patch_fail], fontsize=9)

    plt.tight_layout()
    path = '/tmp/k940_qlike_comparison.png'
    plt.savefig(path, dpi=150, bbox_inches='tight')
    plt.close()
    return path


# ── 圖表 2：RF 特徵重要性 + Ridge 係數 ────────────────────────────
def make_feature_importance_chart():
    features = ['log_vix', 'yz_lag1', 'r2_lag2', 'garch_vix_ratio',
                'r2_lag3', 'rolling_var_20', 'r2_lag4', 'garch_var', 'r2_lag5', 'abs_r_lag1', 'r2_lag1']
    importance = [0.3512, 0.1470, 0.1179, 0.0710,
                  0.0642, 0.0603, 0.0597, 0.0455, 0.0346, 0.0267, 0.0218]
    # Sort by importance
    sorted_pairs = sorted(zip(importance, features), reverse=True)
    importance_s, features_s = zip(*sorted_pairs)

    fig, ax = plt.subplots(figsize=(10, 6))
    colors = ['#1565C0' if f == 'log_vix' else '#42A5F5' if f == 'yz_lag1' else '#90CAF9' for f in features_s]
    bars = ax.barh(features_s, importance_s, color=colors, edgecolor='white')
    ax.set_xlabel('特徵重要性（Gini Impurity）', fontsize=11)
    ax.set_title('K940: Random Forest 特徵重要性\n（揭示 VIX 主導地位）', fontsize=13, fontweight='bold')
    ax.set_xlim(0, 0.42)
    for bar, val in zip(bars, importance_s):
        ax.text(val + 0.005, bar.get_y() + bar.get_height()/2,
                f'{val:.1%}', va='center', fontsize=10)

    # Highlight VIX
    ax.axvline(x=0.35, color='#D32F2F', linestyle='--', alpha=0.5, linewidth=1.5)
    ax.text(0.352, -0.6, 'VIX 單獨佔 35.1%', color='#D32F2F', fontsize=9, va='bottom')

    patch_vix = mpatches.Patch(color='#1565C0', label='VIX 相關特徵')
    patch_range = mpatches.Patch(color='#42A5F5', label='YZ Range（OHLC 波動）')
    patch_lag = mpatches.Patch(color='#90CAF9', label='其他滯後特徵')
    ax.legend(handles=[patch_vix, patch_range, patch_lag], loc='lower right', fontsize=9)

    plt.tight_layout()
    path = '/tmp/k940_feature_importance.png'
    plt.savefig(path, dpi=150, bbox_inches='tight')
    plt.close()
    return path


# ── 圖表 3：Spearman rho 比較（排名相關性）────────────────────────
def make_spearman_chart():
    models = ['MF-GJR\n(VIX)', 'Random\nForest', 'GJR\n(1,1,1)', 'Ridge', 'GARCH\n(1,1)', 'MLP']
    spearman = [0.4573, 0.4212, 0.4177, 0.3995, 0.3833, 0.0735]
    colors = ['#1976D2', '#388E3C', '#66BB6A', '#FFA726', '#A5D6A7', '#EF5350']

    fig, ax = plt.subplots(figsize=(10, 5))
    bars = ax.bar(models, spearman, color=colors, edgecolor='white', linewidth=0.5, width=0.6)
    ax.axhline(y=0.4573, color='#1976D2', linestyle='--', linewidth=1.5, alpha=0.6, label='MF-GJR(VIX) 基準線')
    ax.set_ylabel('Spearman 排名相關係數 ρ', fontsize=11)
    ax.set_title('K940: 波動率預測方向性準確度（Spearman ρ）\nSPY OOS 2016–2025', fontsize=12, fontweight='bold')
    ax.set_ylim(0, 0.55)
    for bar, val in zip(bars, spearman):
        ax.text(bar.get_x() + bar.get_width()/2, val + 0.01,
                f'ρ={val:.4f}', ha='center', va='bottom', fontsize=9, fontweight='bold')
    ax.text(0, 0.0735 - 0.02, 'MLP 幾乎無排名預測能力\n（ρ≈0 接近隨機）',
            ha='center', va='top', color='#C62828', fontsize=8.5)
    ax.legend(fontsize=9)
    plt.tight_layout()
    path = '/tmp/k940_spearman.png'
    plt.savefig(path, dpi=150, bbox_inches='tight')
    plt.close()
    return path


# ── 生成圖表並上傳 ─────────────────────────────────────────────────
print("生成圖表 1: QLIKE 比較...")
path1 = make_qlike_comparison_chart()
url1 = upload_chart(path1)
print(f"上傳完成: {url1}")

print("生成圖表 2: RF 特徵重要性...")
path2 = make_feature_importance_chart()
url2 = upload_chart(path2)
print(f"上傳完成: {url2}")

print("生成圖表 3: Spearman ρ 比較...")
path3 = make_spearman_chart()
url3 = upload_chart(path3)
print(f"上傳完成: {url3}")

# ── 文章內容 ──────────────────────────────────────────────────────
content = """[提出: Claude, 執行: Claude]

## 摘要

本研究（K940）系統性比較了機器學習模型（MLP 神經網路、Ridge 線性迴歸、Random Forest）與計量經濟學模型（GARCH、GJR、MF-GJR）在 SPY 日頻波動率預測上的表現。核心結論：**MF-GJR(VIX) 以 QLIKE=1.4582 蟬聯最佳**，MLP 神經網路災難性失敗（QLIKE=651,520），Random Forest 是唯一可行的 ML 模型但仍不勝。關鍵洞見：RF 的特徵重要性揭示 VIX 佔 35.1%，而 MF-GJR 的乘法結構已從結構上編碼了這個非線性關係。

---

## 研究背景

在 K889 確認 MF-GJR(VIX) 為最佳單模型（QLIKE=1.458）、K937 確認四種集成方法均無法超越之後，本實驗聚焦於一個自然的後續問題：**機器學習是否能發現計量模型遺漏的非線性關係？**

理論上，ML 模型（特別是神經網路）可以擬合任意複雜函數，不受 GARCH 族的參數化限制。然而，日頻波動率預測面臨一個根本性挑戰：

$$\\text{SNR} = \\frac{\\text{Var}(\\sigma_t^2)}{\\text{Var}(r_t^2 - \\sigma_t^2)}$$

日頻 $r_t^2$ 的信噪比極低——偏態係數（skewness）= 15.7，峰態係數（kurtosis）= 347。這意味著絕大多數每日觀測都被噪音主導，只有少數極端事件攜帶真實訊號。

本實驗是本研究計畫**第一個正式 ML 實驗**。

---

## 方法與數據

| 項目 | 設定 |
|------|------|
| 資產 | SPY（S&P 500 ETF） |
| 訓練期 | 2004-01-01 ~ OOS 開始前（擴展窗口） |
| OOS 期間 | 2016-01-04 ~ 2025-12-31（2,514 個交易日） |
| 目標變數 | $r_t^2$（Patton 2011 proxy-robust target） |
| 再訓練頻率 | 每 63 個交易日（季頻），共 40 次 refit |
| 特徵 | 11 個，**全部使用 $t-1$ 或更早資訊**（無前視偏誤） |
| 隨機種子 | 42（所有 ML 模型，確保可重現） |

**11 個特徵（按類別）**：
- **GARCH 類**：GARCH(1,1) 條件方差 $h_t$、GARCH/VIX² 比值
- **VIX 類**：$\\log(\\text{VIX}_{t-1})$
- **收益率歷史**：$r^2_{t-1..t-5}$、$|r_{t-1}|$、YZ range$_{t-1}$
- **滾動統計**：20 日滾動方差

**ML 模型配置**：

| 模型 | 架構/設定 | 超參數 |
|------|-----------|--------|
| MLP | 2 層 (32, 16)，ReLU，Adam | max_iter=500，early_stopping |
| Ridge | 線性迴歸加 $L_2$ 正則化 | $\\alpha=1.0$ |
| Random Forest | 樹集成 | 100 棵樹，max_depth=5 |

評估指標遵循 Patton (2011)：QLIKE 為主（proxy-robust），輔以 MSE 與 Spearman $\\rho$。模型間差異以 DM test 驗證，Harvey et al. (2016) $|t| > 3.0$ 為顯著性門檻。

---

## 核心發現

### 發現一：計量模型全面勝出，MF-GJR(VIX) 仍為最佳

"""

content = embed_chart(content, url1, "圖1：QLIKE 模型比較（左：含失敗模型，對數尺度；右：放大可行模型區間）")

content += """

**完整結果表**（DM test vs MF-GJR(VIX)，Harvey $|t| > 3.0$ 為顯著）：

| 模型 | QLIKE | MSE | Spearman $\\rho$ | DM $t$-stat | 顯著 |
|------|-------|-----|----------------|-------------|------|
| **MF-GJR(VIX)** | **1.4582** | $2.13 \\times 10^{-7}$ | **0.4573** | — | 基準 |
| Random Forest | 1.5237 | $2.20 \\times 10^{-7}$ | 0.4212 | -4.11 | ★★★ |
| GJR(1,1,1) | 1.5459 | $2.09 \\times 10^{-7}$ | 0.4177 | -4.95 | ★★★ |
| GARCH(1,1) | 1.5813 | $2.15 \\times 10^{-7}$ | 0.3833 | -6.68 | ★★★ |
| Ridge | 40,278 | $2.10 \\times 10^{-7}$ | 0.3995 | -3.33 | ★★★ |
| MLP(32,16) | 651,520 | $1.21 \\times 10^{-3}$ | 0.0735 | -4.46 | ★★★ |

★★★ = Harvey $|t| > 3.0$，統計顯著劣於 MF-GJR(VIX)。

所有模型均顯著不如 MF-GJR(VIX)，**包括所有三個 ML 模型**。

---

### 發現二：MLP 災難性失敗——分佈診斷揭示原因

MLP 的 QLIKE = 651,520，比 MF-GJR 高出 **446,737 倍**。更關鍵的是 MSE = $1.21 \\times 10^{-3}$，比其他所有模型高出 **5,780 倍**——代表 MLP 的預測值完全失控。

根源診斷：QLIKE 的定義為

$$\\text{QLIKE}(\\hat{\\sigma}_t^2, r_t^2) = \\frac{r_t^2}{\\hat{\\sigma}_t^2} - \\log\\frac{r_t^2}{\\hat{\\sigma}_t^2} - 1$$

QLIKE **對低估懲罰極重**（當 $\\hat{\\sigma}_t^2 \\to 0$，$r_t^2 / \\hat{\\sigma}_t^2 \\to \\infty$）。日頻 $r_t^2$ 分佈的峰態係數高達 347，意味著存在少數極端觀測（如 2020/3 COVID 崩盤期）。

MLP 在這些極端樣本上的梯度（$\\partial \\mathcal{L}/\\partial w$）遠大於正常樣本，導致：
1. **梯度爆炸**：Adam 優化器雖有自適應學習率，但 kurtosis=347 仍造成不穩定
2. **Early stopping 過早**：極端樣本出現在驗證集時觸發停止，損壞最後收斂的權重
3. **特徵標準化不足**：儘管有 StandardScaler，$r_t^2$ 在標準化後仍有極端值

---

### 發現三：Ridge 的 QLIKE 爆炸——線性模型的致命弱點

Ridge 的 QLIKE = 40,278，但 MSE 卻接近最佳（$2.10 \\times 10^{-7}$）。這個矛盾現象揭示了一個重要的方法論問題：**MSE 和 QLIKE 衡量的是根本不同的東西**。

Ridge 是線性模型，其預測值

$$\\hat{h}_t^{\\text{Ridge}} = \\mathbf{x}_t^\\top \\boldsymbol{\\beta}$$

當市場平靜時，某些特徵組合可能產生**接近零甚至負值**的預測（$\\hat{h}_t \\approx 0$）。由於 QLIKE 包含 $r_t^2 / \\hat{\\sigma}_t^2$ 項，極小的 $\\hat{\\sigma}_t^2$ 會讓這個比率爆炸。

GARCH 族模型天然避免此問題——其遞迴結構（$h_t = \\omega + \\alpha r_{t-1}^2 + \\beta h_{t-1}$）保證 $h_t > 0$，且 $\\beta \\approx 0.9$ 的高持續性確保不會跌至零附近。

---

### 發現四：Random Forest 是唯一可行的 ML 模型

RF 的 QLIKE = 1.5237 落在 GJR 和 GARCH 之間，Spearman $\\rho$ = 0.4212 也接近 GJR（0.4177）。RF 之所以可行，原因在於：

1. **樹結構的天然正性**：RF 預測是訓練目標的加權平均，訓練目標全為正值（$r_t^2 \\geq 0$），因此預測值也保持非負
2. **對極端值的魯棒性**：max_depth=5 限制每棵樹，避免對極端觀測過擬合

---

### 發現五：VIX 主導地位的結構確認

"""

content = embed_chart(content, url2, "圖2：Random Forest 特徵重要性——log(VIX) 以 35.1% 遠勝其他特徵")

content += """

RF 的特徵重要性（Gini impurity）：

| 特徵 | 重要性 | 說明 |
|------|--------|------|
| $\\log(\\text{VIX}_{t-1})$ | **35.1%** | 市場隱含波動率 |
| $\\text{YZ range}_{t-1}$ | 14.7% | OHLC 日內波動估計量 |
| $r^2_{t-2}$ | 11.8% | 二日前的波動衝擊 |
| GARCH/VIX² ratio | 7.1% | 計量模型殘差 vs 市場預期 |

這個結果從 ML 的角度驗證了 MF-GJR(VIX) 的設計理念。MF-GJR 將方差分解為：

$$\\sigma_t^2 = \\tau_t \\times g_t$$

其中長期成分 $\\tau_t = \\exp(\\theta_0 + \\theta_1 \\log \\text{VIX}_{t-1})$ 直接編碼了 VIX 對波動率的乘法影響。RF 發現 VIX 解釋了 35% 的預測力，而 MF-GJR 用參數化方式精確捕捉了這個關係——ML 沒有什麼「額外的非線性」可以發現。

---

### 發現六：方向性預測（Spearman ρ）同樣確認排序

"""

content = embed_chart(content, url3, "圖3：Spearman ρ 方向性預測準確度——MLP 幾乎接近隨機（ρ=0.07）")

content += """

Spearman $\\rho$ 是分佈無關的排名相關係數，不受 QLIKE 的極端值影響。即便在這個更穩健的指標上：

- MF-GJR(VIX)：$\\rho = 0.4573$（最高）
- Random Forest：$\\rho = 0.4212$（ML 最佳，仍不勝）
- MLP：$\\rho = 0.0735$（接近隨機猜測）

MLP 在所有三個評估指標（QLIKE、MSE、Spearman）上均失敗，確認此並非 QLIKE 的偶然懲罰。

---

## 實務意義

**對波動率預測研究者**：
1. 在日頻數據上，**不應期待基本 MLP 優於計量模型**。如果要試 ML，Random Forest（有深度限制）是比神經網路更穩健的起點。
2. **評估指標的選擇至關重要**：Ridge 在 MSE 上表現良好，若只看 MSE 會得出「ML 可行」的錯誤結論。應優先使用 QLIKE（Patton 2011）。
3. **特徵工程的邊界**：RF 特徵重要性是驗證計量模型設計的工具——當 ML 發現的重要特徵與計量模型的結構相符，代表計量模型已「學到」了正確的非線性。

**對一般投資者**：
- 波動率預測的技術前沿並非「越複雜越好」。配備市場恐慌指數（VIX）的 GARCH 模型在 10 年 OOS 期間持續勝過 AI 神經網路。結構化的金融知識（「波動率有長期和短期成分」）比暴力搜索非線性更有效。

---

## 結論

K940 提供了計量模型 vs ML 的第一個正面比較。結論：

1. **MF-GJR(VIX) 繼續保持最佳地位**（QLIKE=1.4582，DM $|t|>3$ 勝所有對手）
2. **MLP 神經網路災難性失敗**（QLIKE=651,520）——$r_t^2$ 的 kurtosis=347 使梯度不穩，early stopping 無法補救
3. **Ridge 的 QLIKE 爆炸**（40,278）——線性模型可能預測零附近方差，QLIKE 懲罰極重
4. **Random Forest 是唯一可行的 ML**（QLIKE=1.5237），但仍顯著不如 MF-GJR
5. **RF 特徵重要性確認 VIX 主導**（35.1%）——MF-GJR 的乘法結構已完整捕捉此非線性

**限制**：本實驗使用基本 ML 架構（2 層 MLP、淺層 RF）。更深的架構（LSTM、Transformer）或以 realized variance 作為預測目標可能得出不同結論。未來研究可探索：(1) HAR-RV + ML 在 5 分鐘 RV target 上的比較、(2) 更大規模超參數調整（HPO）、(3) 多資產驗證。

---

*實驗腳本: experiments/k940/k940.py，數據來源：yfinance (SPY, ^VIX)，OOS 2016-2025*
"""

# ── 發佈文章 ──────────────────────────────────────────────────────
pub = Publisher()
article_id = pub.publish_milestone(
    title="K940: ML vs 計量經濟學的波動率預測對決——MLP 為何災難性失敗？",
    description=content,
    phase="K940",
    tags=["研究", "SPY", "GARCH", "GJR", "MF-GJR", "機器學習", "MLP", "Random Forest", "波動率預測", "QLIKE", "DM test"],
    status="draft",
    audience="research",
    proposer="Claude",
)
print(f"\n文章發佈成功！ID: {article_id}")
print(f"狀態: draft（等待 cron 釋出）")
