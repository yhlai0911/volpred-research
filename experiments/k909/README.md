# K909: MF-GJR Extended Long-Run Factors

## 問題
MF-GJR 的長期因子目前只用 VIX：τ_t = exp(θ₀ + θ₁ × log(VIX_{t-1}))。加入第二個因子 θ₂ × X 是否能進一步改善？

## 動機
- K889: MF-GJR(VIX) 已 Harvey PASS
- K862: Corwin-Schultz spread 是唯一突破 VIX sufficiency 的指標（SPY t=3.01）
- VIX sufficiency 已確認 25 次，但乘法框架中的第二因子尚未測試

## 方法
- 3 候選因子：
  1. **VIX term structure slope**：log(VIX3M/VIX)——期限結構斜率
  2. **Corwin-Schultz spread**：OHLC bid-ask spread 估計（流動性/微結構）
  3. **Parkinson range**：log(H/L)——日內價格範圍
- τ_t = exp(θ₀ + θ₁ × logVIX + θ₂ × X)
- 3 資產：SPY, QQQ, 0050.TW
- OOS: 2019-2026，window=2000, refit=63d
- DM test vs MF-GJR(VIX) baseline

## 結果（VIX Sufficiency #26）
- **無第二因子通過 Harvey |t| > 3.0**
- VIX slope 最強但不足：SPY t=-2.88（接近 3.0）
- Corwin-Schultz: SPY t=-2.11, theta_2 撞上界（scaling issue）
- Parkinson range: t=-0.36, 無效
- MCS: SPY 只有 VIX+Slope 存活（但 DM 未過 Harvey）
- Slope 負係數 = backwardation 預測更高 vol（經濟直覺合理但統計不足）

## 結論
VIX sufficiency 再次確認。MF-GJR(VIX) 維持推薦——加入第二因子不可靠地改善。

## 數據來源
yfinance（SPY, QQQ, 0050.TW, ^VIX, ^VIX3M），2005-2026
