"""
K1381 研究文章發布腳本：台灣科技股波動率格蘭傑因果性 OOS 預測研究
"""
import sys
sys.path.insert(0, '/Users/yhlai0911/Desktop/volpred-research')

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
import os

from volpred.charts import upload_chart, embed_chart
from volpred.publisher.publisher import Publisher

# ─── 第二張圖：DM t 統計量比較 ─────────────────────────────────────────
def make_dm_chart():
    models = ['HAR-X\nTSMC', 'HAR-X\nMTK', 'HAR-X\nTECH', 'HAR-X\nVIX', 'HAR-X\nALL']
    dm_t = [0.4215, -1.2225, -0.807, -8.8181, -8.4686]
    colors = ['#4CAF50' if t > 0 else '#F44336' for t in dm_t]

    fig, ax = plt.subplots(figsize=(9, 5))
    bars = ax.barh(models, dm_t, color=colors, alpha=0.85)
    ax.axvline(0, color='black', linewidth=0.8)
    ax.axvline(3.0, color='#4CAF50', linewidth=1.5, linestyle='--', label='Harvey 門檻 (+3.0)')
    ax.axvline(-3.0, color='#F44336', linewidth=1.5, linestyle='--', label='Harvey 門檻 (−3.0)')

    for bar, t in zip(bars, dm_t):
        ax.text(t + (0.2 if t >= 0 else -0.2), bar.get_y() + bar.get_height() / 2,
                f'{t:.3f}', va='center', ha='left' if t >= 0 else 'right', fontsize=10)

    ax.set_xlabel('DM t 統計量（正 = HAR-X 更優，負 = HAR 基準更優）', fontsize=10)
    ax.set_title('K1381：HAR-X 各模型 vs HAR 基準的 Diebold-Mariano t 統計量\n（OOS n=1,181，Harvey 門檻 |t|>3.0）', fontsize=11, pad=12)
    ax.legend(loc='lower left', fontsize=9)
    ax.set_xlim(-11, 3.5)
    fig.tight_layout()

    path = '/tmp/k1381_dm_comparison.png'
    fig.savefig(path, dpi=150, bbox_inches='tight')
    plt.close(fig)
    return path

dm_chart_path = make_dm_chart()

# ─── 上傳圖表 ─────────────────────────────────────────────────────────
print("上傳圖表 1/2：預測比較圖...")
url1 = upload_chart(
    '/Users/yhlai0911/Desktop/volpred-research/experiments/k1381/k1381_forecast_comparison.png',
    bucket='article-images'
)
print(f"  chart1: {url1}")

print("上傳圖表 2/2：DM t 統計量比較圖...")
url2 = upload_chart(dm_chart_path, bucket='article-images')
print(f"  chart2: {url2}")

# ─── 文章內文 ─────────────────────────────────────────────────────────
content = f"""## 摘要

本研究以 HAR-X 模型框架，在 2009–2026 年 0050.TW 日頻波動率預測中，實驗台積電（TSMC）、聯發科（MTK）波動率作為外生預測變數的邊際增益。格蘭傑因果檢定（5 lags，α=0.05）顯示 TSMC→0050 顯著（F=4.016，p=0.0012）、MTK→0050 顯著（F=4.708，p=0.0003），統計上科技股波動率確實領先大盤 ETF。然而，OOS QLIKE（1,181 天）下 HAR-X_TSMC 僅比基準 HAR 改善 0.06%（9.329 vs 9.335），DM 檢定 t=0.42（p=0.67）遠未觸及 Harvey 門檻（|t|>3.0）。最反常的是 VIX 加入後顯著惡化（DM t=−8.82，Harvey PASS 但方向相反），提示 VIX 在日頻線性 HAR-X 框架中對 0050 波動率有系統性干擾效果。整體判定：MIXED — 格蘭傑領先是真實統計現象，但未能轉化為 OOS 預測力。

---

## 研究背景

「台積電打噴嚏，大盤就感冒」是台股市場的常識判斷。0050.TW 持股中台積電長期佔比超過 30%，直覺上 TSMC 的波動率應當領先 0050 波動率。問題是：這種統計關係能否轉化為日頻 HAR 模型可用的預測力？

關聯性（或格蘭傑因果性）與 OOS 可預測性是兩個不同的問題。格蘭傑因果是基於全樣本 OLS 的 F 統計量，而 OOS 預測需要外生變數在每一個滾動窗口都貢獻邊際準確度。本實驗刻意分開這兩個問題：先做格蘭傑因果，再做 OOS DM 比較，確認兩者是否一致。

本研究承接 K1374 系列（0050 HAR 基準）與 K1373（VIX 充分性），在已知 VIX 加入台股 HAR 模型通常不帶來顯著改善的脈絡下，進一步測試「同市場科技股板塊波動率」是否能帶出不同結論。

---

## 方法與數據

| 項目 | 設定 |
|------|------|
| 標的 | 0050.TW（被解釋變數） |
| 預測變數 | 2330.TW（TSMC）、2454.TW（聯發科 MTK）、科技板塊複合波動率、VIX |
| 期間 | 2009-02-18 至 2026-04-17 |
| 樣本 | n=3,935；訓練期 n=2,754；OOS n=1,181 |
| RV proxy | 日對數報酬平方（Patton 2011 代理穩健損失設定） |
| 模型 | HAR（基準）、HAR-X_TSMC、HAR-X_MTK、HAR-X_TECH、HAR-X_VIX、HAR-X_ALL |
| OOS 設定 | 擴展窗口（expanding window） |
| 預測損失 | QLIKE（Patton 2011 代理穩健損失函數） |
| 統計門檻 | Harvey (1997) DM 修正，\|t\| > 3.0 才視為顯著 |
| Granger 設定 | 5 lags，F 檢定，α = 0.05 |
| 異常值過濾 | \|log-return\| > 0.5 遮蔽為 NaN（排除公司事件假信號） |
| 隨機 seed | 42 |

HAR-X 模型：預測 t+1 的 0050 波動率，外生變數 $X_t$ 均以 t 日已知值輸入，不存在前視偏誤（no lookahead）。

---

## 核心發現

### 4.1 格蘭傑因果：台積電與聯發科波動率確實統計領先

| 配對 | F 統計量 | p 值 | lags | 顯著（α=0.05） |
|------|---------|------|------|--------------|
| TSMC → 0050 | 4.016 | 0.0012 | 5 | ✓ |
| MTK → 0050 | 4.708 | 0.0003 | 5 | ✓ |

兩項格蘭傑因果在 5 滯後下均顯著，p 值遠低於 0.05。這與 TSMC 在 0050 的高持股占比相符：成分股波動率在下一個交易日部分反映於 ETF 的波動率路徑是合理的機制。

---

### 4.2 OOS 預測增益：格蘭傑顯著不代表預測改善

下圖為各模型 OOS 預測損失（QLIKE）比較：

![K1381 OOS 預測比較]({url1})

| 模型 | OOS QLIKE | vs HAR | DM t | p 值 | Harvey PASS |
|------|-----------|--------|------|------|------------|
| HAR（基準） | 9.3346 | — | — | — | — |
| HAR-X_TSMC | 9.3292 | −0.06% | +0.422 | 0.673 | ✗ |
| HAR-X_MTK | 9.3586 | +0.26% | −1.223 | 0.222 | ✗ |
| HAR-X_TECH | 9.3518 | +0.18% | −0.807 | 0.420 | ✗ |
| HAR-X_VIX | 9.6915 | +3.83% | −8.818 | <0.001 | ✓（反向） |
| HAR-X_ALL | 9.6948 | +3.87% | −8.469 | <0.001 | ✓（反向） |

Harvey PASS 欄中「反向」指 DM t 統計量通過 \|t\|>3.0 門檻，但方向指向 HAR 基準更優，而非 HAR-X。

HAR-X_TSMC 的 OOS QLIKE 從 9.3346 降至 9.3292，改善幅度 0.06%，DM t=0.422、p=0.673——完全不顯著，離 Harvey 門檻有七倍之遠。HAR-X_MTK 甚至略微惡化（+0.26%）。5 個 HAR-X 變體中，沒有任何一個達到 Harvey (1997) 顯著性標準的「勝過基準」。

---

### 4.3 DM t 統計量全貌：VIX 的系統性破壞

下圖直接呈現各模型 DM t 統計量，正值代表 HAR-X 優於 HAR，負值代表 HAR 基準更優：

![K1381 DM t 統計量比較]({url2})

HAR-X_VIX（加入美國 VIX 作為外生預測變數）的 OOS QLIKE 反升至 9.6915，比基準 HAR 惡化 3.83%，DM t=−8.818，Harvey 門檻成立但方向為 HAR 勝。HAR-X_ALL（同時加入 TSMC、MTK、VIX）結果幾乎相同（QLIKE=9.6948，DM t=−8.469）。

VIX 是主導 HAR-X_ALL 惡化的主因而非 TSMC/MTK。這個解讀可從以下三個角度考量：

1. **尺度錯配**：VIX 是隱含波動率（年化 30 天前向），0050 的 RV proxy 是日頻已實現波動率。兩者單位和信息集不對稱，直接加入 HAR-X 引入系統性偏誤。
2. **多共線性放大**：VIX 與 0050 自身的日、週、月頻 RV 之間存在相關，但 VIX 是跨市場代理，在 OLS 估計下係數不穩定，OOS 滾動窗口中惡化累積。
3. **VIX 充分性的逆向含義**：若 VIX 已充分描述系統性風險環境，線性 HAR-X 加入 VIX 反而多了噪音。HAR 本身的自相關結構已隱含市場記憶，VIX 的前向信息在日頻 OLS 框架下無法乾淨分離。

---

## 實務意義

對採用 HAR 系列模型做 0050.TW 波動率預測的研究者，本結果給出兩點警示：

**格蘭傑因果不能替代 OOS DM 測試。** 格蘭傑 F 統計量是全樣本描述工具；在時間嚴格前向的 OOS 評估下，台積電波動率雖然格蘭傑引導 0050，這個信號在 1,181 個 OOS 窗口的平均邊際貢獻接近零。直接從格蘭傑顯著推論「可以加入 HAR-X 提升預測」是一個邏輯跳躍。

**VIX 在日頻 HAR-X 框架中是系統性干擾。** 若要利用美國市場的波動率信息，應考慮非線性轉換（VIX 分位數 regime dummy、VIX 一階差分、或 VIX 閾值條件模型）而非直接加入水準值。

---

## 限制與穩健性

- **RV proxy 為日報酬平方**：Patton (2011) 代理穩健損失對 proxy 噪音有容忍度，但日報酬平方相比高頻 5 分鐘 RV 含有更多微結構噪音。
- **單標的**：以 0050.TW 為唯一被解釋變數，結果是否推廣到 0056、006208 或個股未作驗證。
- **Granger 為雙變量 F 檢定**：非 VAR 多元框架，解讀需限於此定義。
- **子期間穩定性未檢驗**：2009–2026 包含 COVID 崩潰（2020）、升息週期（2022）、AI 行情（2023–2024），各 regime 下 TSMC 與 0050 關係可能有差異。
- **Look-ahead 確認**：所有外生變數以 t 日已知值預測 t+1，無前視偏誤。

---

## 結論

K1381 問的是：科技股波動率的格蘭傑領先性，能否轉化為 0050.TW 的 OOS 波動率預測增益？

格蘭傑因果在全樣本下確實顯著（TSMC F=4.016，MTK F=4.708，均 p<0.01），但 OOS 框架下最佳 HAR-X（HAR-X_TSMC）的改善幅度只有 0.06%，DM t=0.422。VIX 加入更是反向顯著惡化（DM t=−8.818，Harvey PASS，方向為 HAR 勝）。

格蘭傑因果與 OOS 可預測性測量的不是同一個東西。混用兩者概念會導致「統計說有效但預測說沒用」的研究誤判，這個案例是台灣市場 HAR-X 研究的具體提醒。

後續研究方向：非線性 HAR-X（TSMC 波動率分位數 regime dummy）、高頻 RV proxy 替換、或台積電法說前後 HAR-X 係數的 subsample 穩定性檢驗。

---

*[提出: Claude] 本文基於實驗 K1381（腳本：`experiments/k1381/k1381.py`，結果：`experiments/k1381/k1381_results.json`）。數據來源：paper/taiwan-vt 資料集（yfinance），期間：2009–2026，n=3,935 觀測值（訓練 n=2,754；OOS n=1,181）。*
"""

# ─── 發布 ─────────────────────────────────────────────────────────────
pub = Publisher()
result = pub.publish_milestone(
    title='K1381：台灣科技股波動率格蘭傑領先 0050——統計顯著，OOS 預測增益趨近於零',
    description=content,
    phase='research',
    category='milestone',
    audience='research',
    tags=['K1381', '0050.TW', 'TSMC', '聯發科', 'HAR-X', '格蘭傑因果', '波動率預測', 'Diebold-Mariano'],
    proposer='Claude',
    status='draft',
)
print(f"\n發布結果: {result}")
