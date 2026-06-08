# K1430 — Autoencoder Enhanced Realised GARCH PoC

## 動機

`research_program.md` backlog 有一條新文獻方向：

- **Autoencoder Enhanced Realised GARCH** — arXiv:2411.17136

它的核心主張不是「任何 deep model 都會贏」，而是更窄的一件事：
**把多個 realized measures 壓成一個 synthetic measure，可能比單一 measure 更適合做 volatility forecasting。**

在 VolPred 現況下，先驗證這個 upstream claim，比硬拿 99 天樣本做 full Realized GARCH superiority claim 更誠實。

## 與既有脈絡的關係

- **K198**：daily proxy 版 Realized GARCH 是 NULL，提醒 measurement noise 是主問題。
- **K852**：5-min RV + Realized GARCH 在另一條研究線證明這個方向值得追，但場景與資料不同。
- **K1428**：2025 RV forecasting review 已明確建議，先鎖 realised-measure / baseline discipline，再談更炫的模型。

## 研究問題

在本地可用的 SPY 5-min 資料上：

1. 1 維 autoencoder synthetic measure，是否比單一 realised measure 更貼近當日 5-min RV？
2. 用 `signal_t -> RV_{t+1}` 的最小 forecasting PoC 時，它是否比 raw `RV_t` 更好？
3. 若有改善，是否強到能勝過現成單一 proxy，例如 BPV？

## 資料

- 資產：SPY
- 來源：`data/intraday/SPY_5min_*.csv`
- 原始 5 分鐘日數：99 天
- 期間：2026-01-14 至 2026-06-05
- 因 close-to-close return 對齊，最終 usable sample：98 天
- train / test：69 / 29（train end = 2026-04-24；test start = 2026-04-27）

## 方法

### Realized measures

每天從 5 分鐘 OHLC 生成：

- `RV_5min`
- `BPV`
- `RV+`
- `RV-`
- `Parkinson`
- `Garman-Klass`
- `OC2 = log(C/O)^2`

### Synthetic measure

- 對上列 7 個 log-measures 做標準化
- 訓練 1 維 bottleneck autoencoder：`7 -> 3 -> 1 -> 3 -> 7`
- `random_state = 42`
- 再用 train sample 線性校準，把 latent 轉回 `log(RV)` 尺度

### 對照組

- raw `RV_5min`
- `BPV`
- `Parkinson`
- `Garman-Klass`
- `OC2`
- 1 維 `PCA` synthetic measure

### Forecast test

不是 full HHS(2012) joint likelihood。
這裡只測一個 upstream PoC：

- `log(RV_{t+1}) ~ signal_t`

這樣可以清楚檢查 synthetic measure 本身有沒有帶來增量資訊。

### Lookahead / seed

- **無 lookahead**：所有 signal 都是 `t` 日已知 realised measure，預測的是 `t+1` 的 `RV_5min`
- **seed 固定**：`np.random.seed(42)`，`MLPRegressor(random_state=42)`

## 核心結果

### 1. AE 沒有打出強 superiority

OOS QLIKE 排名：

1. `BPV`
2. `RV_5min`
3. `PCA_1D`
4. `AE_1D`
5. `GarmanKlass`
6. `Parkinson`
7. `OC2`

重點不是 AE 完全沒用，而是：

- AE **沒有比 raw RV-only 更好**
- 但 **BPV 仍然更好**
- 連 `PCA_1D` 也排在 AE 前面
- `DM` 比較都 **不顯著**

所以這輪不能宣稱「autoencoder synthetic measure 已經勝出」。

### 2. 同日貼近度上，BPV 也比 AE 更強

在 test window，同日 `RV_5min` 對照裡：

- `BPV` 的 correlation 高於 `AE_1D`
- `PCA_1D` 反而高於 `AE_1D`

這意味著在這個短樣本下，**非線性壓縮的額外價值尚未顯現**。

### 3. 這更像「可繼續追，但不能先下結論」

合理讀法是：

- **feasible**：流程可以實作、沒有資料或工程上的 blocking issue
- **not yet superior**：小樣本下沒有足夠證據說 AE synthetic measure 勝過 best single measure

## 結論

`K1430` 的判定是 **`PARTIAL_NULL`**：

- Autoencoder synthetic measure 在這個 short sample 上 **沒有贏過 raw RV-only**
- 也 **勝不過 BPV**
- 而且 **連 PCA 壓縮都沒有超過**
- 而且 **沒有統計顯著性**

因此，這條文獻方向 **可以保留**，但下一步不該直接寫成「AE-Realised-GARCH 是下一個王者」。
更正確的下一步是：

1. 等 252+ 天 5-min depth
2. 把 synthetic measure 放進 full Realized GARCH / HAR-RV 正式 horse race
3. 做 SPY + 0050.TW 多市場重跑

## 限制

1. 只有 99 個 intraday days，樣本太短，不能做強結論。
2. 這裡驗證的是 synthetic measure upstream claim，不是完整 HHS(2012) joint estimation。
3. 只有 SPY，未做跨資產或長 regime 驗證。

## 文獻

1. **Autoencoder Enhanced Realised GARCH on Volatility Forecasting** — arXiv:2411.17136
2. **Hansen, Huang & Shek (2012)** — *Realized GARCH: a joint model for returns and realized measures of volatility*
3. **Bollerslev, Patton & Quaedvlieg (2016)** — realized-volatility measurement-error forecasting paper
4. **Skintzi & Fameliti (2025)** — realized-volatility estimator combination

## 三件套

- `README.md`
- `k1430.py`
- `k1430_results.json`

## 復現

```bash
PYTHONPATH=src python experiments/k1430/k1430.py
```
