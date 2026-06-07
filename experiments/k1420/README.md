# K1420: Regime-Weighted Conformal VaR (RWC)

## 動機

K1390 證明「單一 volatility regime 切 bucket」對 SPY 的 conformal VaR 有幫助，但那版 regime 是固定二分法（`VIX_{t-1} > 20`），不是這次 brief 要求的 3-state regime-weighted 設計。K1420 的目標是做一個更接近文獻 `Regime-Weighted Conformal VaR` 的本地 first-pass replication：用 3-state HMM 在 `|returns|` 上估 regime，再把 conformal tail threshold 做成 regime-weighted forecast。

## 方法

- 標的：`SPY`、`0050.TW`
- 資料：
  - `experiments/k1206/data/SPY.csv`
  - `experiments/k1411/data/T0050.csv`
- 樣本：`2012-01-01` 到 `2025-12-31`
- OOS：`2023-01-01` 之後
- 預測目標：next-day `5% VaR / ES`
- Rolling 規格：
  - refit window = `2000`
  - conformal calibration window = `500`
  - refit every `63` days
  - HMM multistart = `20`
- 比較方法：
  - `GJR-Normal`
  - `GJR-Student-t`
  - `Plain conformal`（用 GJR-N sigma 標準化）
  - `RWC`（3-state HMM regime-weighted conformal）

## Lookahead 防線

所有 forecast 都是 `signal from t-1, return at t`：

1. GJR variance forecast 用 `return_{t-1}` 和 `h_{t-1}` 推 `sigma_t`
2. HMM 用歷史 `|return|` 到 `t-1` 的 filtered posterior 推 `state_t` 機率
3. conformal calibration window 只用到 `t-1` 為止的 standardized loss score
4. `VaR_t` / `ES_t` 算完後才對照 `return_t`

## 主要結果

### SPY

| Method | Violation | Kupiec p | CC p | DQ p | Mean FZ |
|---|---:|---:|---:|---:|---:|
| GJR-Normal | 5.05% | 0.947 | 0.444 | 0.720 | **-5.500** |
| GJR-t | 5.72% | 0.377 | 0.268 | 0.327 | -5.349 |
| Plain conformal | 4.39% | 0.432 | **0.680** | 0.717 | -5.400 |
| RWC | 6.12% | 0.174 | 0.190 | 0.083 | -5.314 |

- Plain conformal 的 CC 最好，但 FZ 仍輸給 GJR-Normal。
- RWC 在 SPY 上沒有改善 coverage；FZ 也明顯較差。
- DM(FZ, base=`GJR-Normal`)：
  - `GJR-t`: `t=-14.43`
  - `Plain conformal`: `t=-7.21`
  - `RWC`: `t=-7.77`
- 上述 t 都是負的，代表 **GJR-Normal loss 較低**，RWC 並沒有贏 baseline。

### 0050.TW

| Method | Violation | Kupiec p | CC p | DQ p | Mean FZ |
|---|---:|---:|---:|---:|---:|
| GJR-Normal | 4.83% | 0.837 | 0.547 | 0.941 | -5.150 |
| GJR-t | 4.97% | 0.973 | 0.500 | 0.920 | -4.969 |
| Plain conformal | 4.70% | 0.705 | **0.596** | 0.937 | -4.955 |
| RWC | 6.22% | 0.148 | 0.469 | 0.230 | **-5.183** |

- 0050 上 RWC 的 FZ 平均分數最低，但 coverage 變差，違約率升到 `6.22%`。
- 因為 success rule 要求「CC 不差於 plain conformal 且 violation 接近 nominal」，0050 也不算 pass。
- DM(FZ, base=`GJR-Normal`)：
  - `GJR-t`: `t=-15.47`
  - `Plain conformal`: `t=-11.01`
  - `RWC`: `t=+0.70`，未達 Harvey 顯著

## 結論

本地 first-pass replication 結果是 **NULL_RESULT**：

- `pass_count = 0 / 2`
- RWC 在 `SPY`、`0050.TW` 都沒有同時滿足：
  - conditional coverage 不差於 plain conformal
  - violation rate 與 nominal 5% 距離在 `±1.5%` 內

更具體地說：

- `SPY`：plain conformal 已經把 CC 做得比 RWC 更好，RWC 反而 over-breach。
- `0050.TW`：RWC 雖然 FZ 平均值略優於 GJR-Normal，但 coverage 退步，不能 overclaim 成成功。

## 與前作關係

- `K1390`：簡單二分 regime conformal 在 SPY 上有效
- `K1005` / `K1026`：plain conformal 對某些 VaR backbone 有效，但不保證 regime-weighted 一定更好
- `K1420`：把 regime 從 exogenous VIX threshold 換成 endogenous HMM state 之後，本地 first-pass **沒有複製出增量優勢**

## Caveats

1. 這版用的是 repo 內既有 daily close 資料，沒有重新抓 live data。
2. Regime 來源是 `|returns|` 的 Gaussian HMM，不是 paper 其他可能的 state feature set。
3. 只測 `alpha=5%`；沒有掃 1% / 2.5%。
4. Conformal overlay 綁在 `GJR-Normal` sigma backbone；沒有再做 A4f 或其他 proxy-robust backbone。
