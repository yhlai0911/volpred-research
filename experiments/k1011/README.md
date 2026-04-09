# K1011: Financial Stock Early Warning System for Taiwan Market Volatility

## 動機
K757 發現富邦金（2881.TW）波動 Granger-cause 台積電（2330.TW）波動（F=6.11）。延伸問題：金融股波動是否也領先整體台股（0050.TW）？能否建構金融壓力指標作為台股 VT 信號？

## 方法
- **數據**：yfinance 2012-2026（~3,448 obs）
- **金融股**：2881.TW（富邦金）、2882.TW（國泰金）、2886.TW（兆豐金）、2891.TW（中信金）
- **目標**：0050.TW、^TWII、2330.TW
- **波動指標**：20 日滾動標準差（年化）
- **Granger 因果檢定**：lag 1, 5, 10, 22
- **金融壓力指數**：等權 z-score（EQ）+ PCA 第一主成分（PC1 解釋 77.9%）
- **波動預測**：HAR-style OLS（RV lag 1,5,22 + stress），2 年 OOS
- **VT 策略**：stress > 1σ 減碼至 50%，> 2σ 完全避險。signal.shift(1)
- seed=42

## 核心發現

### 1. Granger Causality（部分顯著）
- 全樣本 48 組測試中 20 組 p<0.01（42%）
- **金融股 → 0050.TW**：6/16 顯著（主要在 lag 5-22）
- **最強預測者：兆豐金（2886.TW）** — 全部 lag 5/10/22 對 0050.TW、^TWII、2330.TW 均顯著
- **中信金（2891.TW）** — 對 0050.TW lag 5/10/22 顯著，且跨三個子期間均一致
- **富邦金、國泰金**：主要預測 TSMC，對 0050.TW 預測力較弱
- lag=1 幾乎全不顯著 → 金融股領先效應需 1 週以上才顯現

### 2. 金融壓力指數
- EQ 和 PCA 相關性 1.000（因 PC1 解釋 77.9%，四檔金融股高度同步）
- 與 0050.TW RV 無條件相關 0.689
- Granger 因果：stress → 0050.TW 在 lag 5/10/22 顯著（p<0.001）

### 3. 波動預測（PARTIALLY NULL）
- IS R² baseline = 0.9598，加 stress 仍為 0.9598（幾乎無提升）
- OOS QLIKE/MSE/R² 幾乎一致
- **DM test |t| = 2.51 < 3.0 → 不滿足 Harvey (2016) 門檻**
- stress 係數 t=1.79，p=0.074 → 邊際不顯著

### 4. VT 策略（NULL）
- BH 0050.TW Sharpe = 0.979
- FIN_STRESS EQ VT Sharpe = 0.797（更差）
- FIN_STRESS PCA VT Sharpe = 0.814（更差）
- 減碼期間約 11-22%，但錯過了正常漲幅

### 5. 子期間穩健性
- **兆豐金**：2017-2020 和 2021-2026 顯著，2012-2016 不顯著（新興效應？）
- **中信金**：跨三個期間均顯著（最穩健）
- **富邦金、國泰金**：全部期間均不顯著對 0050.TW

## 結論
1. **金融股波動確實 Granger-cause 台股波動**，但效應以週-月頻為主（lag 5-22），非日頻
2. **兆豐金和中信金**是最有資訊量的金融股（不是富邦金）
3. **但預測改善幅度極小**，加入 stress 後 R² 幾乎不變，DM test 不過 3.0 門檻
4. **VT 策略無效** — stress 信號太慢（需 1 週以上才領先），且高 stress 不等於市場下跌
5. 金融股波動更像是 coincident indicator 而非 leading indicator

## 局限性
- 只用 20d 滾動 RV，未用 GARCH 或 5-min RV
- 壓力指數只用 4 檔金融股，可擴展至全部金融類股
- HAR-style OLS 可能不如 GJR-X 等非線性模型捕捉 stress 效應
- 台灣金融股受政策影響大（升息/降息、金融監理），可能有 regime-dependent 效應

## 後續方向
- 測試 GJR-GARCH with exogenous stress（τ = exp(θ₁ × stress_{t-1})）
- 金融 credit spread（金融債-公債利差）vs 股票波動
- 高頻數據版本（5-min RV 的 Granger）
- 結合 VIX + FIN_STRESS 的複合信號

## 檔案
- `k1011.py` — 實驗腳本
- `k1011_results.json` — 完整結果
- `k1011_charts.png` — 時間序列圖 + 策略累積報酬
- `k1011_granger_heatmap.png` — Granger F 值熱力圖
