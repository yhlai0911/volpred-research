# K994: Cross-Asset Validation of Multiplicative GJR-X (A4f Specification)

**[提出: 賴奕豪, 執行: Claude]**

## 動機

K988/K988b 在 SPY 上發現 A4f（τ=θ₀+θ₁VIX², free ω, GJR g_t, τ_t 分母）為冠軍規格（QLIKE=-8.3608, DM t=+4.48 vs GJR）。但僅測 SPY，需跨資產驗證確認泛化性。

## 方法

在 4 個資產上測試 A4f vs A4 (constrained) vs GJR benchmark：

| 資產 | 類型 | VIX 處理 |
|------|------|---------|
| QQQ | 高 beta 科技 | 同日 VIX |
| EEM | 新興市場 | 同日 VIX |
| GLD | 黃金（低 VIX 相關性） | 同日 VIX |
| 0050.TW | 台股 ETF | VIX lag+1（時區差異） |

- OOS: 2019-2026, window=2000, refit/63d
- 評估: QLIKE on r² (Patton 2011), DM test (Harvey t>3.0), Spearman ρ
- 0050.TW 用 `clean_tw50_data` 處理分割問題

## A4f 模型規格

```
σ²_t = τ_t × g_t
τ_t = max(θ₀ + θ₁ × VIX²_{t-1}, 1e-16)
g_t = ω + α × u²_{t-1} + γ × u²_{t-1} × 1_{u<0} + β × g_{t-1}
u_{t-1} = r_{t-1} / sqrt(τ_t)    ← 分母用當期 τ_t
ω: 自由估計（A4f），或 ω = 1-α-γ/2-β（A4 約束版）
```

## 結果

| Asset | GJR QLIKE | A4 QLIKE | A4f QLIKE | DM t(A4f vs GJR) | Harvey sig |
|-------|-----------|----------|-----------|-------------------|------------|
| QQQ | 1.4806 | 1.4233 | 1.4195 | -3.71 | **YES** |
| EEM | 1.3375 | 1.3055 | 1.3069 | -2.47 | NO |
| GLD | 1.5291 | 1.5134 | 1.5126 | -1.08 | NO |
| 0050.TW | 1.4581 | 1.4465 | 1.4318 | -1.44 | NO |

- A4f Harvey 顯著: **1/4** (僅 QQQ)
- A4 Harvey 顯著: **1/4** (僅 QQQ)
- A4f vs A4 在所有資產上無顯著差異

### VIX-r² 相關性與模型改進的關係

| Asset | VIX-r² corr (OOS) | A4f QLIKE improvement |
|-------|-------------------|----------------------|
| QQQ | 0.494 | -0.061 (sig) |
| EEM | 0.499 | -0.031 (not sig) |
| GLD | 0.126 | -0.017 (not sig) |
| 0050.TW | 0.275 | -0.026 (not sig) |

## 結論

1. **A4f 泛化性有限**：僅在 QQQ 達到 Harvey 顯著（DM t=-3.96），其餘三個資產改進方向正確但不顯著
2. **VIX 相關性是關鍵**：QQQ 與 SPY 同屬美國股市，VIX 直接反映其波動。EEM/GLD/0050.TW 的波動受各自因素驅動
3. **A4f vs A4 無顯著差異**：free omega 的額外彈性在跨資產上未帶來統計顯著改進
4. **方向一致**：所有 4 個資產 A4f 的 QLIKE 都優於 GJR（方向正確），只是效果量不夠大
5. **GLD 最弱**（VIX-r² corr 僅 0.126），符合預期

### 實務意義
- A4f 適用於與 VIX 高相關的美國股市資產（SPY, QQQ）
- 跨市場使用需替換為**當地市場的恐慌指數**（如 TVIX 對台股、VXEEM 對新興市場）
- VIX² 作為 τ 的外生變數在非美國資產上解釋力不足

## 數據來源
- yfinance: QQQ, EEM, GLD, 0050.TW, ^VIX
- 期間: 2005-01-01 ~ 2026-04-08
- OOS: 2019-01-01 ~ 2026-04-07

## 參考文獻
- Engle, Ghysels & Sohn (2013). Stock Market Volatility and Macroeconomic Fundamentals. RES 95(3):776-797.
- Patton (2011). Volatility forecast comparison. J Econometrics 160:246-256.
- Harvey et al. (2016). t > 3.0 threshold.
- Conrad & Loch (2015). Anticipating Long-Term Stock Market Volatility. JBES 33(3):338-358.

## 檔案
- `k994.py` — 實驗腳本
- `k994_results.json` — 完整結果（每個資產×模型的 QLIKE, DM t, Spearman, params）
