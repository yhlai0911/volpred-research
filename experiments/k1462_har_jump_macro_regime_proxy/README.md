# K1462 — Macro Regime Does Not Absorb SPY Jump-Proxy Signal

## 問題

research backlog 的原命題是：`regime-switching HAR` 中，商業循環 state 會不會把 jump 成分「吸收掉」，讓 jump 係數變得不重要？

理想版需要：

- 長樣本 intraday RV
- BNS bipower jump decomposition
- state-aware HAR-CJ / Markov regime design

但本 repo 目前沒有長樣本 pinned intraday SPY 資料；只有 2026 局部 5-min 檔，因此**不能誠實地假裝完成正式 HAR-CJ**。本實驗改做一個可重現的 proxy feasibility test：

- target：SPY 日頻 Parkinson variance
- jump proxy：隔夜 gap squared，`log(Open_t / Close_{t-1})^2`
- macro states：PIT 對齊的 `CFNAI<0`、`NFCI>0`、`INDPRO<0`

重點不是證明正式理論，而是先回答一個窄問題：

> 即使只用最保守的 gap-jump proxy，macro state conditioning 有沒有把 jump 訊號吸收掉？

## 文獻先行

1. **Corsi (2009)**：HAR-RV 的多尺度持續性基礎。
2. **Barndorff-Nielsen & Shephard (2004)**：bipower variation / jump 識別的正式基礎。  
   本實驗因資料限制**未**直接實作該正式 jump 分解。
3. **Hamilton (1989)**：regime-switching / business-cycle state 的經典出發點。
4. **Chicago Fed CFNAI / NFCI technical docs**：macro state 指標的經濟意涵與發布節奏。

## 資料

- SPY OHLC：`experiments/k1206/data/SPY.csv`
- CFNAI / NFCI / INDPRO（PIT 月頻）：`experiments/k1117b/data/*_monthly_pit.csv`
- 樣本：`2006-02-03` 到 `2026-04-16`
- OOS：`2016-01-04` 到 `2026-04-16`
- OOS observations：`2586`
- train window：`1000` 日
- refit：每 `63` 日
- seed：`42`

## 模型

1. `HAR`
   `log(Park_t) ~ log(Park_{t-1}) + log(Park_{t-5:t-1}) + log(Park_{t-22:t-1})`

2. `HAR+Jump`
   上式加上 `log(1 + 1e6 * gap_sq_{t-1})`

3. `HAR+Jump+State`
   上式再加上 `state_{t-1}` 與 `jump_{t-1} × state_{t-1}`

所有 predictor 都明確 lagged，沒有 same-day leakage。

## 主要結果

### Full-sample HAC

- `log_gap_proxy` 在三個 state 規格都顯著：
  - CFNAI state：p = `1.39e-21`
  - NFCI state：p = `6.92e-44`
  - INDPRO state：p = `2.92e-37`
- `jump × state` interaction **三個都不顯著**：
  - CFNAI：p = `0.340`
  - NFCI：p = `0.758`
  - INDPRO：p = `0.945`

這表示至少在這個 proxy 規格下，macro state **沒有把 jump 訊號吸收掉**。

### OOS QLIKE（Parkinson target；越低越好）

- `HAR` = `0.5241`
- `HAR+Jump` = `0.4922`
- `HAR+Jump+CFNAI` = `0.4973`
- `HAR+Jump+NFCI` = `0.4928`
- `HAR+Jump+INDPRO` = `0.4927`

### DM / Harvey 口徑

- `HAR` vs `HAR+Jump`：DM t = `2.82`, p = `0.0048`
  - 改善方向正確
  - **但未達本專案 Harvey |t| > 3 gate**
- `HAR+Jump` vs `HAR+Jump+NFCI`：DM t = `-4.00`, p < `1e-4`
  - 表示加上 `NFCI` state 後反而更差
- `HAR+Jump` vs `HAR+Jump+CFNAI`：DM t = `-1.82`, p = `0.068`
  - 邊際變差，不可宣稱顯著
- `HAR+Jump` vs `HAR+Jump+INDPRO`：DM t = `-0.15`, p = `0.882`
  - 無差異

## 結論

`NULL_FOR_ABSORPTION`

在這個可重現的 proxy 設計裡：

- jump proxy 本身有增量資訊
- macro regime interaction 沒有顯著吸收 jump 係數
- state-aware 版本沒有比 jump-only HAR 更好，甚至 `NFCI` 版本顯著更差

因此，原始 backlog 假說目前**沒有被支持**。更合理的下一步不是繼續堆 state，而是先補齊：

1. 長樣本 intraday RV cache
2. 正式 BNS jump decomposition
3. 真正的 HAR-CJ / regime-switching 規格

## 限制

1. **這不是正式 HAR-CJ。** 沒有 BNS jump，因此不能把本結果外推成「jump 文獻已被推翻」。
2. state 是 PIT macro threshold，不是 latent Markov state。
3. Parkinson variance 與 overnight gap proxy 都是日頻 proxy，無法分解日內 jump / continuous variation。

## 檔案

- `k1462.py`：實驗主腳本
- `k1462_results.json`：結果 artifact
- `k1462_oos_qlike.png`：OOS QLIKE + interaction p-value 圖
