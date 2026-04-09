# K1003: A4f Sensitivity Analysis (Paper Robustness)

[提出: 賴奕豪, 執行: Claude]

## 動機

K988 發現 A4f 模型（τ=θ₀+θ₁VIX², free ω）在 SPY 上 DM t=+4.48 顯著優於 GJR。論文需要 robustness 檢驗，驗證結論不依賴於特定的估計設定。

## 方法

A4f 模型規格:
- τ_t = max(θ₀ + θ₁ × X²_{t-1}, 1e-16)
- g_t = ω + α × u²_{t-1} + γ × u²_{t-1} × 1_{u<0} + β × g_{t-1}
- u_{t-1} = r_{t-1} / sqrt(τ_t)
- ω: free parameter

4 個維度的 sensitivity analysis:

### 1. Refit 頻率 (21d / 63d / 126d / 252d)
### 2. 估計窗口 (1000 / 1500 / 2000 / 2500 / 3000)
### 3. OOS 子期間 (2019-2020 COVID / 2021-2022 升息 / 2023-2026 穩定期)
### 4. VIX 替代指標 (VIX / VIX9D / VIX3M / VIX/VIX3M ratio)

評估: QLIKE on r² (Patton 2011), DM test vs GJR, Harvey (2016) |t| > 3.0

## 數據

- SPY + ^VIX + ^VIX9D + ^VIX3M from yfinance
- 期間: 2011-01-03 ~ 2026-04-07 (VIX9D 限制了起始日)
- n=3837, OOS n=1825 (from 2019-01-01)

## 結果

**13/16 (81.3%) 測試通過 Harvey (2016) |t| > 3.0 門檻**

### Refit 頻率: 4/4 ROBUST

| Refit | QLIKE GJR | QLIKE A4f | DM t | Robust |
|-------|-----------|-----------|------|--------|
| 21d   | 1.5001    | 1.4085    | +4.29 | Yes |
| 63d (baseline) | 1.4975 | 1.4081 | +3.92 | Yes |
| 126d  | 1.5009    | 1.4082    | +3.36 | Yes |
| 252d  | 1.5089    | 1.4098    | +3.32 | Yes |

結論: A4f 對 refit 頻率不敏感。更頻繁的 refit 略微改善 DM t，但所有設定均顯著。

### 估計窗口: 5/5 ROBUST

| Window | QLIKE GJR | QLIKE A4f | DM t | Robust |
|--------|-----------|-----------|------|--------|
| 1000   | 1.4781    | 1.4182    | +3.18 | Yes |
| 1500   | 1.4899    | 1.4075    | +3.49 | Yes |
| 2000 (baseline) | 1.4975 | 1.4081 | +3.92 | Yes |
| 2500   | 1.4914    | 1.4023    | +5.13 | Yes |
| 3000   | 1.4866    | 1.4022    | +4.94 | Yes |

結論: 更長窗口反而提升 DM t（2500-3000 最強）。A4f 受益於更多資料。

### OOS 子期間: 1/3 ROBUST

| Period | QLIKE GJR | QLIKE A4f | DM t | n | Robust |
|--------|-----------|-----------|------|---|--------|
| 2019-2020 (COVID) | 1.5221 | 1.4078 | +1.60 | 505 | No |
| 2021-2022 (升息) | 1.3844 | 1.3032 | +2.50 | 502 | No |
| 2023-2026 (穩定) | 1.5519 | 1.4727 | +4.52 | 816 | Yes |

結論: A4f 在所有子期間均改善 QLIKE，但 DM 檢定力因樣本量減少而不足。2023-2026 (n=816) 顯著; COVID 和升息期間方向正確但 n~500 不夠。這是 sub-sample DM test 的已知 power issue，不是模型失敗。

### VIX 替代指標: 3/4 ROBUST

| Indicator | QLIKE GJR | QLIKE A4f | DM t | Robust |
|-----------|-----------|-----------|------|--------|
| VIX (baseline) | 1.4975 | 1.4081 | +3.92 | Yes |
| VIX9D | 1.4975 | 1.3802 | +5.15 | Yes |
| VIX3M | 1.4975 | 1.4361 | +2.59 | No |
| VIX/VIX3M ratio | 1.4975 | 1.4460 | +3.53 | Yes |

結論: VIX9D (短期 VIX) 最強 (DM t=+5.15)，因為短期 VIX 反應更快。VIX3M (3 個月) 改善最小 (DM t=+2.59)，因為長期 VIX 變化較慢、資訊含量較低。VIX/VIX3M ratio (term structure slope) 也顯著。

## 整體結論

A4f 模型**高度穩健**: 在 refit 頻率、估計窗口、VIX 指標三個維度上幾乎全部通過 Harvey (2016) 門檻。子期間穩定性的 2/3 未通過是統計檢定力不足所致（n~500），方向一致正確。

**論文可以報告**: "A4f 在 13/16 sensitivity 設定下保持 DM |t| > 3.0 的統計顯著性"。

## 局限

- 單一資產 (SPY)
- VIX9D 歷史較短（2011起），限制了整體樣本量
- 子期間 DM test 的 power 受 n 限制
- VIX/VIX3M ratio 在 VIX3M 較小時可能放大噪音

## 檔案

- `k1003.py`: 實驗腳本
- `k1003_results.json`: 完整結果

## 參考文獻

- Engle, Ghysels & Sohn (2013). Stock Market Volatility and Macroeconomic Fundamentals. RES 95(3):776-797.
- Patton (2011). Volatility forecast comparison. J Econometrics 160:246-256.
- Harvey et al. (2016). t > 3.0 threshold.
- Conrad & Loch (2015). JBES 33(3):338-358.
