# I5 — Regime-Switching Hedge Ratio

## 問題

在期貨避險的語境下，常見直覺是：市場 regime 改變時，最佳避險比率也應該跟著改變。`I5` 檢驗的就是這個命題：

- 以 `SPY` 現貨與 `ES=F` 期貨為例，
- 若用 `VIX` 把市場切成低波動、正常、升高、危機四個 regime，
- regime-specific OHR 是否能比全樣本 static OHR 更有效降低風險？

## 資料

- 來源：`yfinance`
- 標的：`SPY`, `ES=F`, `^VIX`
- 期間：`2005-01-04` 到 `2026-03-25`
- 樣本數：`5337` 日

## 方法

1. 用日報酬計算 `SPY` 與 `ES=F` 的 hedge ratio。
2. 依 `VIX` 切四個 regime：
   - `Low (VIX < 15)`
   - `Normal (15 <= VIX < 20)`
   - `Elevated (20 <= VIX < 30)`
   - `Crisis (VIX >= 30)`
3. 各 regime 內分別估 OLS OHR。
4. 和全樣本 static OHR 比較：
   - variance reduction
   - 年化波動
   - MDD
   - DM-style loss comparison
5. 另用 rolling 60-day OHR 看 OHR 是否真的隨 VIX 系統性變動。

## 主要結果

### Regime-specific OHR

| Regime | n | OHR | Variance Reduction | Hedged Vol (ann.) |
|---|---:|---:|---:|---:|
| Low (`VIX<15`) | 1987 | 0.9592 | 0.9361 | 2.1% |
| Normal (`15-20`) | 1590 | 0.9521 | 0.9536 | 2.8% |
| Elevated (`20-30`) | 1313 | 0.9735 | 0.9693 | 3.5% |
| Crisis (`VIX>30`) | 447 | 0.9680 | 0.9542 | 10.0% |

OHR 雖然在統計上有差異，但範圍只在 `0.952` 到 `0.974`，經濟意義很小。

### Static vs Regime-aware

| Method | Sharpe | MDD | Variance Reduction | Ann. Vol |
|---|---:|---:|---:|---:|
| Static OHR | 0.533 | -0.0691 | 0.9575 | 3.9% |
| Regime-aware OHR | 0.593 | -0.0691 | 0.9575 | 3.9% |

### 統計檢定

- ANOVA: `F = 54.36`, `p << 0.001`
- Spearman(`VIX`, rolling OHR): `rho = -0.035`, `p = 0.0118`
- DM-style比較：`t = 0.62`，**不顯著**

## 結論

`I5` 的結論是 **NULL**：

1. `SPY/ES=F` 是近乎完美的高相關避險配對。
2. 雖然 OHR 在不同 VIX regime 間有可測得的差異，但幅度極小。
3. regime-aware hedging 並沒有比 static OHR 帶來可交易或可實務採用的增量改善。
4. 對 equity index futures 這種 `rho ≈ 0.98` 的配對，dynamic/regime-switching OHR 幾乎沒有價值。

## 方法論意義

- **統計顯著不等於經濟顯著**：本實驗是典型例子。
- **高相關避險配對下，簡單 static OHR 往往已足夠**。
- 若要讓 regime-switching correlation hedging 真正有機會成立，較合理的下一步應該是：
  - 較低相關的 cross-hedge
  - commodity / currency hedge
  - basis risk 更高的配對

## 檔案

- `i5_regime_hedge_ratio.py`
- `i5_regime_hedge_ratio_results.json`
