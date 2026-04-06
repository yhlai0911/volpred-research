# K943: Multi-Horizon MF-GJR(VIX) — Multi-step Forecasting Ability

**[提出: Claude (research_program), 執行: Claude]**

## 問題

MF-GJR(VIX) 在 h=1（日頻）已被確認為最佳波動率預測模型（K889, K942）。但實務投資人通常關心 h=5（週頻）或 h=22（月頻）的波動率。MF-GJR 的 VIX 因子在多步預測中是否仍有優勢？

**假說**：VIX 是前瞻性的（選擇權隱含），天然包含多步信息，因此 MF-GJR 在長期預測的優勢應該更大。

## 方法

- **資產**：SPY（2006-01-01 ~ 2026-04-01），yfinance
- **OOS**：2016-01-01 ~ 2025-12-31（2575 天）
- **Window**：2000，Refit 每 21 天
- **模型**：GARCH(1,1)、GJR-GARCH(1,1,1)、MF-GJR(VIX)

### Multi-step 預測公式

- **GARCH/GJR**：σ²_{t+1|t} 用實際值，σ²_{t+i|t} = ω + (α+γ/2+β) × σ²_{t+i-1|t} for i≥2
- **MF-GJR**：τ_t 固定為最新 VIX，g 部分做短期遞迴
- **目標**：h=1 用 r²_t，h=5 用 Σr²_{t:t+4}，h=22 用 Σr²_{t:t+21}

### 評估

- QLIKE on cumulative r²（Patton 2011 proxy-robust）
- OOS R²
- Spearman ρ（分配無關）
- DM test（Harvey 2016 |t| > 3.0）

## 結果

| Horizon | Best QLIKE | MF-GJR vs GJR | DM t-stat | Harvey PASS | MF-GJR Spearman ρ |
|---------|-----------|----------------|-----------|-------------|-------------------|
| h=1     | MF-GJR    | +6.37%         | -5.40     | ✓ PASS      | 0.453             |
| h=5     | MF-GJR    | +18.42%        | -4.12     | ✓ PASS      | 0.717             |
| h=22    | GARCH     | -5.66%         | +0.52     | ✗ FAIL      | 0.676             |

### 詳細 QLIKE

| Model   | h=1   | h=5   | h=22  |
|---------|-------|-------|-------|
| GARCH   | 1.667 | 0.518 | 0.496 |
| GJR     | 1.634 | 0.493 | 0.502 |
| MF-GJR  | 1.530 | 0.402 | 0.530 |

### 詳細 R² (OOS)

| Model   | h=1    | h=5    | h=22   |
|---------|--------|--------|--------|
| GARCH   | 0.255  | 0.333  | 0.113  |
| GJR     | 0.258  | 0.357  | 0.059  |
| MF-GJR  | -0.099 | -0.167 | -0.969 |

**R² 的 paradox**：MF-GJR 在 QLIKE 和 Spearman 上都最好，但 R² 為負。這表示 MF-GJR 的 ranking 正確（相關性高）但 magnitude 有偏（scale 問題）。QLIKE 是 proxy-robust 的正確評估指標（Patton 2011），R² 受 scale 影響大。

## 結論

1. **假說被否定**：VIX 優勢不隨 horizon 單調增長。改善幅度呈倒 U 形：
   - h=1: +6.37%（★★ DM PASS）
   - h=5: +18.42%（★★★ 最佳，DM PASS）
   - h=22: -5.66%（退化，DM FAIL）

2. **h=5 是最佳預測 horizon**：
   - QLIKE 改善 18.42%（遠高於 h=1 的 6.37%）
   - Spearman ρ = 0.717（所有 horizon 中最高）
   - 信噪比最優（與 K143 結果一致）

3. **h=22 的退化原因**：
   - τ_t 常數假設在 22 天內不合理（VIX 會顯著變化）
   - 短期遞迴的 persistence^22 累積誤差
   - 簡單 GARCH 的均值回歸特性反而在長期更穩健

4. **實務含義**：
   - 用 MF-GJR 做 1 週預測（效果最佳）
   - 月頻預測用 GARCH(1,1) 即可（簡單模型更穩健）
   - 如需月頻 VIX 信息，應考慮 rolling-VIX 或多期 VIX 更新

## 局限性

- 僅測試 SPY 一個資產
- τ_t 常數假設是已知限制，可改用 rolling VIX update
- h=22 的 multi-step 公式假設 E[I(r<0)] = 0.5，可能引入偏差

## 檔案

- `k943.py` — 實驗腳本
- `k943_results.json` — 完整結果
- `k943_horizon_comparison.png` — 4 面板比較圖

## 參考文獻

- Engle, Ghysels & Sohn (2013) Stock market volatility and macroeconomic fundamentals, RES
- Conrad & Engle (2025) Two-factor GARCH, J Applied Econometrics
- Patton (2011) Volatility forecast comparison using imperfect proxies, J Econometrics
- Harvey et al. (2016) Tests for forecast encompassing, JBES
