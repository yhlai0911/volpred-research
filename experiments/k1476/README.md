# K1476: TAIFEX OFI → RV across horizon and regime

## 研究問題

用 TAIFEX TX 5 分鐘 tick/5-min bar cache 建出的 OFI，對未來波動率的增量預測力，
到底是：

1. 只存在於極短 horizon？
2. 只存在於高波動 regime？
3. 還是會延伸到次日 daily RV？

這個 task 明確要求看 **5min / 30min / 1day** 三個 horizon，且 regime 必須避免
K1128 那種固定 IS cutoffs 在 COVID 期間退化的老問題。

## 與既有研究的差異

- `K1124` 已測過 5-min OFI 對下一 bar RV 的增量，但主角是 HAR+OFI 規格比較
- `K1128 / K1131 / K1199` 主題是 **OFI→jump** 的 regime/interaction，最後被 error log
  明確記錄：固定 regime cutoffs 會崩
- `K1142` 改看 vol-normalized OFI → jump，得到 partial OOS positive

**K1476 的新點**：

- target 從 `jump` 改成 **RV**
- 一次對照 `5min / 30min / next-day daily RV`
- regime 改用 **前一日 daily RV 的 expanding tertile**，不再用固定 IS 門檻

## 文獻動機

1. Cont, Kukanov, Stoikov (2014), *The Price Impact of Order Book Events*  
2. Lee, Mykland (2008), *Jumps in Financial Markets*  
3. Hansen, Lunde (2005), *Does Anything Beat a GARCH(1,1)?*  

第一篇給 OFI 微結構動機，後兩篇分別提供 jump / vol proxy 與 forecast comparison 的方法背景。

## 資料

- **來源**：`experiments/k1124/_cache_bars_2017-01-01_2021-12-31.parquet`
- **市場**：TAIFEX TX，日盤 08:45-13:45，5 分鐘 bar
- **期間**：2017-01-03 至 2021-12-30
- **總 bar 數**：73,203
- **交易日數**：1,223
- **IS / OOS**：
  - IS：2017-01-03 至 2019-12-31
  - OOS：2020-01-01 至 2021-12-30
- **Seed**：42

## Regime 定義

每一天先算該日總 daily RV，然後用：

- `regime_t = expanding tertile of daily_RV_{t-1}`

也就是：

- 只用 **前一日** daily RV 決定今天屬於 low / mid / high vol regime
- 至少先累積 60 個交易日歷史後才開始標 regime

這樣可以避免：

- 用未來波動定義當期 regime
- 用固定 IS cutoffs 讓 OOS 極端事件把 regime 全擠到同一格

## 方法

### 5min horizon

target:

- `RV_{t+1}` = 下一個 5 分鐘 bar 的 RV

baseline:

- `rv_lag1`
- `rv_mean6`
- `rv_mean12`

OFI model:

- baseline + `abs_ofi_t` + `signed_ofi_t`

### 30min horizon

target:

- 未來 6 個 bar 的 RV 總和

features 同 5min horizon。

### 1day horizon

先把每一天的 5-min OFI 聚合成日特徵：

- `abs_ofi_mean`
- `signed_ofi_mean`
- `abs_ofi_last12`
- `signed_ofi_last12`

target:

- `daily_RV_{t+1}`

baseline:

- `rv_lag1`
- `rv_mean5`
- `rv_mean22`

OFI model:

- baseline + 四個日聚合 OFI 特徵

### 預測與評估

- baseline 與 OFI model 都用 IS fit，OOS 固定參數預測
- 5min / 30min 用 level-RV OLS
- 1day 用 `log(RV)` OLS，再 exponentiate 回 variance scale，避免 level-RV OLS 出現病態近零預測
- 指標：
  - OOS QLIKE
  - DM-HLN vs baseline
  - 各 regime 的平均 QLIKE gain

## 主要結果

### Horizon 摘要

| Horizon | QLIKE Baseline | QLIKE + OFI | Gain | DM t | p-value |
|---|---:|---:|---:|---:|---:|
| 5min | 0.282031 | 0.280784 | +0.44% | +1.646 | 0.0997 |
| 30min | 0.225259 | 0.222647 | +1.16% | +4.904 | 0.0000 |
| 1day | 0.950397 | 0.452609 | +52.38% | +5.826 | 0.0000 |

先講最重要的：

- **5min 有改善，但不夠顯著**
- **30min 有小但穩的顯著改善**
- **1day 改善最大，但幾乎全部集中在 high-vol regime**

### Regime gain（OOS average QLIKE gain of OFI model）

#### 5min

- low: `+0.004658`
- mid: `+0.001013`
- high: `+0.000403`

這代表最短 horizon 的 OFI 增量**沒有**特別集中在 high-vol regime，反而 low-vol 天數上的平均 gain 最大，但整體統計力不足。

#### 30min

- low: `+0.001250`
- mid: `+0.002153`
- high: `+0.003255`

這個 pattern 最乾淨：**horizon 拉到 30 分鐘後，OFI 增量隨 regime 升高而變強。**

#### 1day

- low: `-0.022367`
- mid: `+0.075947`
- high: `+0.879003`

次日 daily RV 的結果最極端：

- low regime 其實是負貢獻
- high regime 則非常強

換句話說，**日頻 OFI 訊號不是普適有效，而是非常 regime-dependent。**

## 解讀

### 1. 「OFI 只對超短線有用」不成立

如果只看 5min，結論會太保守。真正最穩的是 **30min**，不是 5min。

### 2. 「OFI 對未來 daily RV 完全無用」也不成立

至少在這份 TAIFEX cache 上，當你把日內 OFI 做適當聚合後，對次日 daily RV 有很強的 OOS 增量。

### 3. regime dependence 主要出現在較長 horizon

- 5min：regime pattern 不明顯
- 30min：high > mid > low，很合理
- 1day：幾乎只在 high regime 才有值

這比較像一個「累積型壓力訊號」：

> OFI 不是立刻把下一根 5min bar 的 RV 打穿，而是會在更高波動環境下，
> 經過一段時間累積成更明顯的未來波動壓力。

## 結論

K1476 的最誠實結論是：

1. **OFI 對 TAIFEX RV 的預測力確實有 horizon dependence**
2. **最穩的 bar-level horizon 是 30min，不是 5min**
3. **對 next-day daily RV 的訊號最強，但高度集中在 high-vol regime**
4. **所以「OFI regime dependence」不是假議題，但要看的是 adaptive prior-day RV regime，不是 K1128 那種固定 IS VIX tertile**

## 與 error log / 舊結論的關係

這個結果**沒有推翻** `docs/error_log.md` 對 K1128 的警告，反而支持它：

- 錯的是「固定 regime cutoffs + jump target 的敘事」
- 不是「所有 OFI regime dependence 都不存在」

K1476 比較像是把題目改成一個更可存活的版本：

- adaptive regime
- RV target
- 多 horizon 比較

## 限制

1. 單一市場（TAIFEX TX）
2. 只用 2017-2021 cache，OOS 含 COVID 但不含更長近年樣本
3. 1day horizon 的強結果來自日內 OFI 聚合，需後續 cross-market replication 才能提高可信度
4. 尚未做更完整的 DM / bootstrap 多重比較調整

## 檔案

- `k1476.py`
- `k1476_results.json`
- `k1476_horizon_qlike.png`
- `k1476_regime_gain.png`
