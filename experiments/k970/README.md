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

## 核心結果

### QLIKE（越小越好）
| Model   | QLIKE  | vs GJR    | MZ-R²  |
|---------|--------|-----------|--------|
| GJR     | 0.9386 | baseline  | 0.2892 |
| MF2-RV  | 0.8051 | -14.23%   | 0.3773 |
| MF2-VIX | 0.7722 | **-17.73%** | 0.4250 |
| MF2-EMA | 0.8342 | -11.13%   | 0.4049 |

### DM Test（Harvey 2016 |t|>3.0 門檻）
| Pair            | DM-stat | p-value | Significant |
|-----------------|---------|---------|-------------|
| GJR vs MF2-RV   | 3.912   | 0.0001  | **YES**     |
| GJR vs MF2-VIX  | 4.171   | 0.0000  | **YES**     |
| GJR vs MF2-EMA  | 2.901   | 0.0037  | no          |
| MF2-RV vs MF2-VIX | 1.962 | 0.0498  | no          |

### VaR Backtesting
- MF2-VIX 在 1% 和 5% VaR 都通過 Kupiec 和 Christoffersen 檢定
- GJR 在 5% VaR 拒絕 Kupiec（p=0.031），顯示覆蓋不足

## 結論
1. **MF2 分解顯著優於標準 GJR**：三種 MF2 變體全部改善 QLIKE（11-18%），其中 MF2-RV 和 MF2-VIX 通過 Harvey |t|>3.0 門檻
2. **MF2-VIX 最佳**：VIX 作為長期成分提供 17.73% QLIKE 改善（DM t=4.171），MZ-R² 從 0.29 提升到 0.43
3. **VIX 是「免費提升」**：無需額外估計，直接用市場隱含波動率作為長期成分即可大幅改善
4. **短期成分 persistence 降低**：MF2 的短期 GJR persistence 從 0.995 降到 0.80-0.95，說明長期動態被 τ 吸收
5. **VaR 表現改善**：MF2-VIX 的 VaR violation rate 最接近理論值

## 局限性
- 簡化實作：τ 用 proxy 而非完整 MEM 估計
- 單一資產（SPY）、單一 OOS 期間
- GJR 用固定 IS 參數（未 rolling refit）

## 檔案
- `k970_mf2_garch.py` — 實驗腳本
- `k970_mf2_garch_results.json` — 完整結果
- `k970_volatility_components.png` — 三種長期成分比較
- `k970_oos_comparison.png` — OOS 預測 + 累積 QLIKE 優勢

## 參考文獻
- Conrad, C. & Engle, R. (2025). Two-component GARCH models with exogenous long-run dynamics. *J. Applied Econometrics*.
- Engle, R., Ghysels, E., & Sohn, B. (2013). Stock market volatility and macroeconomic fundamentals. *Review of Economics and Statistics*.
- Patton, A.J. (2011). Volatility forecast comparison using imperfect volatility proxies. *J. Econometrics*, 160(1), 246-256.
