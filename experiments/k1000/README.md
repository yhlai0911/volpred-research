# K1000: MF-GJR-X(A4f) + Student-t Joint MLE — 5-Model OOS Comparison

## 動機
驗證 MF-GJR-X(A4f) 模型（VIX² 作為低頻成分外生變數，free ω）加上 Student-t 分佈聯合 MLE 估計，在 OOS VaR/ES 風險預測的表現。比較 5 種模型：單頻 GJR（Normal/t）vs 多頻 A4f（Normal/t-2step/t-joint）。

## 方法
- **數據**: SPY 2004-2026（yfinance），OOS: 2019-2026
- **窗口**: 2000 天滾動估計，每 63 天重估
- **模型**:
  1. GJR_N: GJR-GARCH(1,1) + Normal
  2. GJR_t: GJR-GARCH(1,1) + Student-t joint MLE
  3. A4f_N: MF-GJR-X(VIX², free ω) + Normal
  4. A4f_t_2step: A4f Normal → 殘差 MLE df（兩步估計）
  5. A4f_t_joint: A4f + Student-t 聯合估計（7 參數）
- **評估**: QLIKE on r²（Patton 2011）、DM test（Harvey t>3.0）、VaR（1%/2.5%/5%）UC/CC/DQ 檢定、ES 2.5% Acerbi-Szekely Z1/Z2

## 核心結果

### QLIKE（越低越好）
| 模型 | QLIKE |
|------|-------|
| GJR_N | -8.260 |
| GJR_t | -8.275 |
| A4f_N | -8.362 |
| A4f_t_2step | -8.362 |
| A4f_t_joint | -8.361 |

### DM Tests
- **A4f 全面顯著勝 GJR**：所有 A4f vs GJR 的 DM |t| > 4.2（遠超 Harvey 3.0 門檻）
- A4f 三個變體之間**無顯著差異**（t ≈ 0）
- GJR_N vs GJR_t 也無顯著差異（t = 1.23）

### VaR/ES 2.5% Scorecard（6 = UC+CC+DQ+Basel+ES_Z1+ES_Z2 全 PASS）
| 模型 | 違約率 | Scorecard |
|------|--------|-----------|
| GJR_N | 4.00% | 3/6 |
| GJR_t | 3.29% | 5/6 |
| A4f_N | 2.96% | 6/6 |
| A4f_t_2step | 2.80% | 6/6 |
| A4f_t_joint | 2.80% | 6/6 |

### 參數估計（IS final）
- A4f_t_joint: θ₀≈-6e-5, θ₁≈0.010, ω≈0.049, α≈0, γ≈0.146, β≈0.793, df≈8.0
- Persistence(g): ~0.87（比 GJR 的 0.97 低，因為 τ 吸收了長期趨勢）

## 結論
1. **MF-GJR-X(A4f) 顯著優於 GJR**（DM |t| > 4.2，QLIKE 改善 ~0.10）—— VIX² 作為外生低頻成分有效改善波動率預測
2. **Student-t 改善 VaR 校準但不改善 QLIKE**：t 分佈改善尾部風險覆蓋（1% VaR 違約率從 1.75% 降到 1.21%），但 QLIKE 幾乎不變
3. **A4f_t_joint 和 A4f_t_2step 表現幾乎相同**：兩步和聯合估計的 df 很接近（~8），實際差異可忽略
4. **3 個 A4f 模型都達到 VaR/ES 2.5% 的 6/6 完美 scorecard**
5. df ≈ 8 表示 SPY 日報酬率尾部明顯偏厚（遠離 Normal）

## 局限性
- 僅測試 SPY 單一資產
- VIX² 作為 τ 的外生變數可能有同步性問題（lagged 1 day）
- 未測試其他外生變數（如 realized variance、credit spreads）
- OOS 期間 2019-2026 包含 COVID，可能影響結果代表性

## 參考文獻
- Engle & Rangel (2008) Spline-GARCH
- Patton (2011) QLIKE loss
- Kupiec (1995), Christoffersen (1998), Engle & Manganelli (2004) VaR tests
- Acerbi & Szekely (2014) ES backtesting
- Harvey (2016) t>3.0 threshold
