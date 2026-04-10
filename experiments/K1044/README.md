# K1044: Gamma-VT Causal Panel Test (Cross-Asset Causal Verification)

## 動機
K53 發現 GJR-GARCH gamma（leverage effect）與 VT alpha 的相關係數 r=0.564 (N=22, p<0.01)，暗示 gamma 高的資產做 VT 效果更好。但這只是相關，不是因果。N145 更發現 gamma 不預測 Sharpe improvement (rho=-0.264, p=0.34, N=15)。本實驗用 13 個跨資產類別的 panel 數據重新檢驗此關係，並透過機制分解（mechanism decomposition）試圖釐清因果路徑。

## 核心問題
1. K53 的 r=0.564 在擴大到 13 資產後是否穩定？
2. LOO stability：是否被某幾個極端資產驅動？
3. gamma -> autocorrelation -> VT alpha 的因果鏈是否成立？
4. Sizing channel (VIX) vs Momentum channel (gamma) 哪個更重要？

## 方法
- **資產**: SPY, QQQ, IWM, EFA, EEM, GLD, SLV, USO, TLT, HYG, BTC-USD, 0050.TW, XLF (N=13)
- **數據**: yfinance, 2007-01-01 ~ 2026-04-10
- **GJR-GARCH**: window=2000, refit=63, 估計每個資產的 gamma
- **VT**: 12/VIX, cap=1.5, **signal.shift(1)** 確保無 lookahead
- **OOS**: 2015-01-01 ~ 2026-04-10
- **統計**: Spearman/Pearson correlation, Bootstrap 5000 reps (seed=42), LOO stability
- **機制分解**: gamma->autocorrelation->VT alpha (momentum channel) vs gamma->VIX-return correlation->VT alpha (sizing channel)

## 結果

### 核心結果：Gamma 不預測 VT Alpha
| Relationship | Spearman rho | p-value | 95% Bootstrap CI |
|---|---|---|---|
| Gamma vs VT Alpha | -0.209 | 0.494 | [-0.782, 0.427] |
| Gamma vs Sharpe Diff | -0.033 | 0.915 | [-0.503, 0.553] |
| Gamma vs MDD Improvement | -0.253 | 0.405 | [-0.746, 0.377] |

K53 的 r=0.564 **不可重現**。在 13 資產 panel 中，gamma 與任何 VT 效果指標都無顯著相關。Bootstrap CI 全部跨零。

### 機制分解
| Path | Spearman rho | p-value | 顯著性 |
|---|---|---|---|
| Gamma -> Autocorr(1) | -0.538 | 0.058 | 邊際顯著 |
| Gamma -> VIX-Return Corr | **-0.879** | **0.0001** | 高度顯著 |
| Autocorr(1) -> VT Alpha | 0.456 | 0.117 | 不顯著 |
| VIX-Return Corr -> VT Alpha | 0.357 | 0.231 | 不顯著 |

- **Gamma 強烈預測 VIX-return correlation** (rho=-0.879, p=0.0001)：gamma 高的資產與 VIX 負相關更強
- **但 VIX-return correlation 不預測 VT alpha**：通道斷裂在第二段
- Sizing channel (0.314) > Momentum channel (0.246)，但兩者都很弱

### LOO Stability
- **TLT** 最具影響力 (delta_rho=+0.216)：移除 TLT 後 rho 從 -0.209 變為 +0.007
- **BTC-USD** 也有影響 (delta_rho=-0.190)：移除後 rho 變為 -0.399
- 結果對個別資產敏感，不穩定

### Asset Panel
| Asset | Gamma | VT Alpha | Sharpe Diff | MDD Improve | BH Sharpe | VT Sharpe |
|---|---|---|---|---|---|---|
| SPY | 0.258 | -0.057 | +0.092 | -0.194 | 0.785 | 0.877 |
| HYG | 0.200 | -0.020 | +0.056 | -0.112 | 0.568 | 0.624 |
| QQQ | 0.198 | -0.076 | +0.046 | -0.117 | 0.867 | 0.913 |
| XLF | 0.195 | -0.044 | +0.098 | -0.251 | 0.577 | 0.675 |
| IWM | 0.154 | -0.057 | -0.089 | -0.177 | 0.483 | 0.394 |
| EFA | 0.146 | -0.044 | -0.060 | -0.146 | 0.522 | 0.462 |
| EEM | 0.113 | -0.051 | -0.152 | -0.076 | 0.400 | 0.248 |
| 0050.TW | 0.109 | -0.020 | +0.385 | -0.136 | 0.952 | 1.336 |
| USO | 0.096 | +0.005 | +0.116 | -0.331 | 0.150 | 0.266 |
| BTC-USD | 0.061 | -0.146 | -0.040 | -0.029 | 0.931 | 0.892 |
| SLV | -0.006 | -0.067 | -0.035 | -0.115 | 0.596 | 0.561 |
| GLD | -0.012 | -0.045 | -0.022 | -0.060 | 0.836 | 0.814 |
| TLT | -0.026 | +0.010 | +0.114 | -0.184 | 0.028 | 0.143 |

## 結論

**K53 的 gamma-VT alpha 相關 r=0.564 不可重現。** 在 13 資產的 panel 中，gamma 與 VT alpha 的 Spearman rho = -0.209 (p=0.494)，方向甚至相反。

**Gamma 的真正作用**：
1. Gamma 強烈預測資產與 VIX 的連動程度（rho=-0.879, p=0.0001）——這是 mechanical result
2. 但 VIX 連動程度不預測 VT 的經濟效果——通道在此斷裂
3. VT 效果取決於其他因素（base volatility level、vol-of-vol、market microstructure），不是 gamma

**與先前研究的一致性**：
- 確認 N145 (gamma 不預測 Sharpe improvement, rho=-0.264)
- 確認 VT effectiveness time-stable despite gamma decline
- 確認 gamma determines VT mechanism (trend/contrarian), not VT value

## 局限性
- Cross-sectional N=13 仍然較小，統計檢定力有限
- VIX 是美國市場指標，用於非美資產的 VT sizing 有 proxy mismatch
- 0050.TW 使用 clean_tw50_data 處理分割問題
- BTC 歷史較短（2014 起）
- USO 有結構性 contango/roll 問題
- 因果關係無法僅從 cross-sectional correlation 確立

## 檔案
- `k1044.py` — 實驗腳本
- `k1044_results.json` — 完整結果
- `k1044_gamma_vt_scatter.png` — Gamma vs VT 散佈圖
- `k1044_mechanism_decomposition.png` — 機制分解圖

## 數據來源
- yfinance (daily adjusted close), 2007-2026
- ^VIX (CBOE via yfinance)

## 參考文獻
- Moreira & Muir (2017) "Volatility-Managed Portfolios" JF
- Engle & Ng (1993) "Measuring and Testing the Impact of News on Volatility" JF
- Glosten, Jagannathan & Runkle (1993) GJR-GARCH JF
- Hood & Raughtigan (2025) VT = trend following
