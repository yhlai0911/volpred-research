# k_taiex_60k_scenario_20260619 / path_sim

台股加權指數 (^TWII)「3 個月內觸及 60,000 點」的 model-conditional 機率與路徑風險模擬。

## 動機

2026-06-18 ^TWII 收盤 ≈ 46,465 點。市場常見討論「會不會三個月內上 6 萬點」。
6 萬點相對現價需 **+29.1%**。本實驗用 GARCH(1,1) 條件波動率 + Monte Carlo 路徑模擬，
誠實估計此事件的 **model-conditional 機率**（非預測一定發生），並量化「觸及路徑」沿途的回撤風險。
另以真實歷史 rolling window 計算 empirical benchmark 作對照。

## 方法

1. **資料**：yfinance `^TWII` 日收盤（auto_adjust），2012-01-03 至 2026-06-18，3,520 個交易日 / 3,519 筆日報酬。本地 CSV snapshot (`data/twii_close_snapshot.csv`) 已 pin，腳本「local snapshot first, yfinance fallback」確保離線可重跑（依 error_log 2026-05-27 教訓）。
2. **報酬**：日對數報酬，以 ×100 (pct) 餵入 arch。
3. **模型**：`arch` 套件 GARCH(1,1)，Constant mean。同時 fit Student-t 與 Normal 兩個 innovation，依 **AIC 選擇**。結果選 **Student-t**（AIC 9364.8 < Normal 9601.0），dof ν ≈ 5.68 → 有顯著肥尾。α+β 持續性 = 0.9796（高，volatility clustering 明顯）。
4. **Monte Carlo**：`seed=42`，**20,000 條** 63 交易日（≈3 個月）路徑。用擬合後 GARCH 變異數遞迴（起始條件變異數 = 樣本末端 conditional variance；起始 ε² = 末端 residual²）逐日模擬，shock 用標準化 Student-t（已 scale 至單位變異數）。
5. **兩種 drift 情境**（誠實核心）：
   - **零 drift**：日 drift = 0（保守、無方向假設）。
   - **歷史平均 drift**：日 drift = 樣本平均日對數報酬（年化 ≈ +13.5%，外推 2012–2026 的長期上行 — **未必延續**）。
6. **報告指標**：P(期間內最高點 ≥ 60,000)、63 日後指數中位數與 5/25/75/95 百分位、路徑期間最大回撤 (max drawdown) 分佈、以及「觸及路徑」子集的回撤分佈。
7. **Empirical benchmark**：真實 ^TWII 2012–2026 所有 rolling 63 日前向窗口，計算「窗內最高點達到同等 +29.1% 漲幅」的實際發生頻率（無模擬、無 lookahead — 用 t 時點往後看 63 日窗，純描述歷史頻率）。

## 假設與限制 (caveats)

- **機率是 model-conditional，不是預測**：在「報酬服從此 GARCH(1,1) 過程」的假設下成立；不代表事件一定（或一定不）發生。
- **drift 假設影響極大**：零 drift → 3.36%；歷史平均 drift → 4.89%。歷史 drift 把過去 14 年平均上行外推，並非未來保證。
- **起始波動率偏高**：樣本末端 conditional vol（日 1.85%，年化 ≈ 29%）高於 GARCH 無條件 vol（日 1.08%，年化 ≈ 17%）。當前處於相對高波動 regime，這推高了近端觸及機率；GARCH 均值回歸會在 63 日內把 vol 拉回。
- **對稱模型低估下行群聚**：GARCH(1,1) 對稱；TWII 有記錄在案的槓桿效應（GJR γ=0.272，K-series 知識庫），對稱模型可能略低估下行尾端的波動群聚。
- **value-trap / 方向性警示**：高觸及機率 ≠ 必漲；模型同時顯示大量路徑下行（零 drift 下 p05 = 38,554，約 −17%）。觸及 6 萬與沿途深度回撤可並存。
- **model vs empirical 落差**：模型 3.4–4.9% 高於歷史實際頻率 1.10%（38/3457 窗）。落差來源：(a) 起始高波動 regime；(b) Student-t 肥尾在模擬中放大極端上行；(c) 歷史 63 日 +29% 本就罕見（史上最大 63 日漲幅 +44.7%）。兩個數字都據實呈現，讀者應視 1.1% 為「歷史經驗錨」、3–5% 為「當前高波動條件下的模型上限」。

## 資料來源

- `^TWII` via yfinance，期間 2012-01-03 → 2026-06-18，n=3,520 交易日。
- snapshot：`data/twii_close_snapshot.csv`（pinned，供離線重跑）。

## 主要結果

| 指標 | 零 drift | 歷史平均 drift |
|---|---|---|
| **P(63 日內觸及 ≥60,000)** | **3.36%** | **4.89%** |
| P(第 63 日收在 ≥60,000) | 1.96% | 3.12% |
| 63 日後指數中位數 | 46,474 | 48,069 |
| 5 / 95 百分位 | 38,554 / 56,015 | 39,877 / 57,938 |
| 路徑最大回撤 中位數 | 10.0% | 8.8% |
| 路徑最大回撤 p95 | 23.1% | 21.5% |
| 觸及路徑的最大回撤 中位數 | 9.2% | 8.1% |

**Empirical benchmark**：2012–2026 真實 ^TWII，3,457 個 rolling 63 日窗中僅 **38 個（1.10%）** 曾達到 +29.1% 漲幅；史上最大 63 日漲幅 +44.7%。閾值頻率：+10% → 23.6%、+15% → 11.9%、+20% → 4.9%、+25% → 2.5%、+29.1% → 1.1%。

## 檔案

- `path_sim.py` — 可獨立重跑（`uv run python path_sim.py`），seed=42。
- `path_sim_results.json` — 所有數字。
- `chart_final_distribution.png` — 兩 drift 情境的 63 日後指數分佈。
- `chart_drawdown_and_paths.png` — 最大回撤分佈 + 40 條 sample paths（橘=觸及 6 萬）。
- `data/twii_close_snapshot.csv` — pinned 原始收盤資料。

## 重跑

```bash
cd experiments/k_taiex_60k_scenario_20260619/path_sim
uv run python path_sim.py
```
