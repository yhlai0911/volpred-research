# K970: MF2-GARCH — Mixed-Frequency Squared GARCH

## 動機
Conrad & Engle (2025, J. Applied Econometrics) 提出 MF2-GARCH，將波動率分解為長期（τ）和短期（g）成分：σ² = τ × g。長期成分由外部低頻變數驅動，短期成分由 GJR-GARCH 捕捉日頻動態。本實驗測試此分解是否能改善標準 GJR-GARCH 的 OOS 預測。

## 方法
- **分解**：σ²_t = τ_t × g_t
  - τ_t：長期成分（3 種 proxy）
  - g_t：對標準化 return r̃ = r/√τ 做 GJR-GARCH(1,1)
- **MF2-RV**：τ = 22 天 rolling realized variance
- **MF2-VIX**：τ = (VIX/√252)²（日頻隱含波動率）
- **MF2-EMA**：τ = EMA of r²（halflife=22）
- **Baseline**：標準 GJR-GARCH(1,1)，Student-t errors
- **數據**：SPY 2006-2026（yfinance），IS: 2006-2018, OOS: 2019-2026
- **評估**：QLIKE on r²（Patton 2011 proxy-robust）、MSE、Mincer-Zarnowitz、DM test、VaR backtesting

## 核心結果（與 `k970_mf2_garch_results.json` 一致；2026-06-18 對齊舊版 README stale 估計）

### QLIKE 改善 vs GJR
| Model   | QLIKE 改善 | 方向         |
|---------|-----------|-------------|
| MF2-VIX | **+9.55%** | 改善（最佳） |
| MF2-EMA |  +1.24%   | 邊際改善     |
| MF2-RV  |  −4.49%   | **惡化**     |

### DM Test（Harvey 2016 |t|>3.0 門檻）
| Pair             | DM t-stat | p-value  | Harvey 門檻通過？ |
|------------------|-----------|----------|--------------|
| GJR vs MF2-VIX   |  +2.939   | 0.0033   | **NO**（borderline） |
| GJR vs MF2-RV    |  −1.585   | 0.1129   | NO           |
| GJR vs MF2-EMA   |  +0.334   | 0.7380   | NO           |
| MF2-RV vs MF2-VIX|  +5.355   | <0.0001  | YES (內部對照) |
| MF2-VIX vs MF2-EMA| −4.792   | <0.0001  | YES (內部對照) |

### VaR Backtesting（caveat：所有模型共用 baseline GJR 的 Student-t df，比較不純）
- MF2-VIX 在表上通過 Kupiec / Christoffersen；但檢定函式在 `p_hat = 0/1` 與 `pi11 = 0` 邊界直接回 `p=1`（Codex 2026-06-18 K970 review 指出），極端值會被誤判通過 — 結論需保留。

## 結論
1. **VIX 作為長期成分有方向性優勢**：MF2-VIX QLIKE 改善 9.55%，DM t=2.94 接近但**未通過** Harvey |t|>3 門檻。
2. **歷史 proxy 反而傷模型**：MF2-RV（22 天歷史 RV）QLIKE 比 GJR **惡化** 4.49%；MF2-EMA 僅 +1.24%。
3. **內部對照清楚**：MF2-VIX 顯著優於 MF2-RV / MF2-EMA（|t|>4），代表 VIX 內含的 forward-looking 資訊不是歷史 RV 平均能取代。
4. **發表強度**：不足以宣稱新基準；視為 candidate signal，需擴 OOS 與 cross-asset 才能升等（reviewer note：不可寫成「MF2 分解優於 GJR」— 只有 VIX 變體有方向性優勢）。
5. **短期成分 persistence 降低**：MF2 的短期 GJR persistence 從 0.995 降到 0.80-0.95，說明長期動態被 τ 吸收。

## 局限性
- 簡化實作：τ 用 proxy 而非完整 MEM 估計
- 單一資產（SPY）、單一 OOS 期間
- GJR 用固定 IS 參數（未 rolling refit）
- VaR backtesting 共用 baseline `nu`、boundary p-value 處理寬鬆（需用各模型自身 Student-t df + 修 boundary）
- DM 函式只實作 lag=0 NW；h>1 需補 Bartlett kernel 與 Harvey-Leybourne-Newbold small-sample correction

## 檔案
- `k970_mf2_garch.py` — 實驗腳本
- `k970_mf2_garch_results.json` — 完整結果
- `k970_volatility_components.png` — 三種長期成分比較
- `k970_oos_comparison.png` — OOS 預測 + 累積 QLIKE 優勢

## 參考文獻
- Conrad, C. & Engle, R. (2025). Two-component GARCH models with exogenous long-run dynamics. *J. Applied Econometrics*.
- Engle, R., Ghysels, E., & Sohn, B. (2013). Stock market volatility and macroeconomic fundamentals. *Review of Economics and Statistics*.
- Patton, A.J. (2011). Volatility forecast comparison using imperfect volatility proxies. *J. Econometrics*, 160(1), 246-256.
