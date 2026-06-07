# k1419

- Experiment ID: `k1419`
- Status: pilot_offline_first_pass
- Last updated: 2026-06-08

## 問題描述

原 brief 想做的是「HAR-RV / GJR-GARCH 點預測，升級成條件分位數預測」，並用 long-horizon 5-min realized variance 做正式 cross-asset OOS 檢定。

本機資料檢查後，這個 full-spec 在本輪不誠實：

- `data/intraday/SPY_daily_rv.csv` 只有 2026 年 `99` 筆
- `data/intraday/0050_TW_daily_rv.csv` 只有 `72` 筆 non-null
- `QQQ` 沒有對應 daily 5-min RV 檔

所以本輪把 K1419 落成一個 **offline first-pass pilot**：

1. 共用 target 改成 `Parkinson range-based variance` 的 `log` 版本
2. 比較三種 quantile forecast：
   - HAR point forecast + Gaussian residual quantile
   - HAR point forecast + empirical residual quantile
   - Direct quantile HAR
3. 評估用：
   - pinball loss
   - nominal coverage
   - pointwise pinball loss 的 DM test（Harvey gate `|t| > 3.0`）

## 方法

- 資產：`SPY`, `QQQ`, `0050.TW`
- 樣本：`2023-01-03` 起
- OOS：`2025-01-02` 起
- Refit：每 `21` 個交易日
- HAR feature：
  - `lag1`
  - `avg5`
  - `avg22`
  - `|r_{t-1}|`
  - `r^2_{t-1}`
- Quantiles：`τ ∈ {0.05, 0.25, 0.50, 0.75, 0.95}`

## 結果口徑

- 這不是 full HAR-RV / FZ / VaR-ES paper-spec 的完成版。
- 它回答的是更窄的工程問題：
  - **在本機可用資料下，direct quantile HAR 有沒有在 pinball loss 上穩定打贏 Gaussian residual baseline？**
- 若答案有訊號，再排 compute-queue follow-up 做正式長樣本 HAR-RV / GJR / VaR-ES 版本。

## 本輪結果

- `SPY`：五個 quantiles 全部是 `Gaussian residual baseline` 最佳，沒有 augmentation 訊號。
- `QQQ`：`qHAR` 在 `τ=0.50/0.75` pinball loss 較低，但所有 DM 都未過 Harvey `|t|>3`。
- `0050.TW`：`qHAR` 在五個 quantiles 全部最低，且在 `τ=0.05` 對 Gaussian baseline 的 DM `t=-4.84`，過 Harvey gate；`τ=0.25` 的 empirical / qHAR 也都過關。
- 總結：**quantile augmentation 的訊號集中在台股 proxy-vol，不是美股。**

## 下一步

- 若要升級成正式 K1419：
  - 補齊 `QQQ` 與更長歷史的 daily 5-min RV
  - 把 target 從 `Parkinson proxy` 升回真正 `HAR-RV`
  - 補 `VaR/ES + Fissler-Ziegel` 模組

## 產物

- `k1419_probabilistic_rv_quantile.py`
- `k1419_probabilistic_rv_quantile_results.json`
