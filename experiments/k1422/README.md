# K1422 — HAR-Quantile commodity rerun with fair baselines

## 動機
K1421 在 GLD / USO / UNG 上跑出 aggregate `PASS`，但 Codex source review 判定 formal conclusion 不可採信，原因有二：

1. `q05/q95` 的 DM test 把 **OLS conditional mean** 直接套進 pinball@τ，去跟 **直接最小化 pinball@τ 的 QR** 比，屬於設計性 advantage。
2. `joint_bootstrap()` 的 one-sided p-value 公式錯誤，會把檢定寫成近似 `boot_T >= 2*T_obs`。

K1422 的目的不是「修飾 K1421 結論」，而是重新做一個**公平且可推翻舊結論**的 rerun。

## 方法

資料與 OOS 切分沿用 K1421：
- 資料：GLD / USO / UNG OHLC，Garman-Klass 日內波動率 proxy
- IS：2012-01-03 至 2020-12-31
- OOS：2021-01-04 起
- HAR 特徵：`rv_d`, `rv_w`, `rv_m`，全部 `shift(1)`，避免 lookahead

模型：
1. **QR target model**：HAR + QuantReg at `τ ∈ {0.05, 0.50, 0.95}`
2. **Fair baseline A**：HAR Gaussian constant sigma
3. **Fair baseline B**：HAR empirical residual quantile
4. **Fair baseline C**：HAR location-scale Gaussian（先用 HAR 預測 mean，再用 HAR on `|resid|` 預測 scale）

評估：
1. 每個 baseline 對每個 `τ` 都算 pinball loss
2. QR vs baseline 跑 DM test with Harvey-HLN correction
3. 跨資產 joint test 改成 **centered-null stationary bootstrap**

## 成功標準

- **單一 baseline formal PASS**：某個 tail（`q05` 或 `q95`）達成
  - `>=1/3` assets DM sig positive (`p < 0.10`, `dm_stat > 0`)
  - 且 joint bootstrap one-sided `p < 0.10`
- **整體 PASS**：至少 `2/3` fair baselines 都 formal PASS
- **整體 CONDITIONAL_PASS**：只有 `1/3` baseline formal PASS，或只有 per-asset positive 但 joint 不過
- **整體 NULL**：三個 fair baselines 都沒有 formal tail improvement

這個判準比 K1421 更保守，因為這輪的重點是**robustness under fair comparison**。

## 預期輸出

- `experiments/k1422/k1422.py`
- `experiments/k1422/k1422_results.json`
- 若結果為 `NULL`，需回溯更正 K1402 → K1403 → K1421 commodity tail claim 的 formal 敘述

## 參考

- K1421 review knowledge entry: `ac45417a`
- Corsi (2009) HAR
- Koenker & Bassett (1978) Quantile Regression
- Politis & Romano (1994) Stationary bootstrap
