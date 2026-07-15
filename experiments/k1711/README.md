# K1711 — TSFM × HAR forecast pool under Model Confidence Sets

## 結果摘要

K1711 問的不是「foundation model 是否打敗 HAR」，而是：把 TimesFM、Tiny Time
Mixer（TTM）及其與 HAR 的組合加入候選池後，TSFM-bearing model 是否進入 Hansen–Lunde–Nason
Model Confidence Set（MCS），以及原本 HAR family 的 superior set 是否改變。

預先指定的 primary cell 是 retrospective pseudo-OOS、RV proxy、QLIKE、h=1、
α=0.10，逐資產評估。三個資產的 full-pool MCS 都保留至少一個 TSFM-bearing model；
跨資產按日期平均 QLIKE 的 pooled MCS（2,344 個共同日期）為 `{HAR-A, COMB-MZ}`。
這代表 TSFM-bearing forecast **未被 MCS 排除**，不是「TSFM 勝出」，也不是「加入 TSFM
有顯著增量」。原始 TimesFM 與 TTM 在三個 primary superior sets 都未存活；存活的是
MZ 校準或含 HAR 的組合。

將 full-pool MCS 投影回 base models 後，0050.TW、TX 與 pooled base set 不變；SPY 的
standalone base set 是 `{HAR-A}`，full-pool 投影則是 `{HAR, HAR-A}`。因此 base-set change
只出現在 SPY，而且方向是較弱的 HAR 重新進入集合，不是 TSFM 淘汰 HAR。

正式 verdict：

`TSFM_BEARING_MODELS_SURVIVE_MCS_NO_WINNER_OR_INCREMENTAL_CLAIM`

## 動機與差異化

- 原始問題：TSFM × HAR 組合是否穩定進 superior set，而不是再做一次「誰贏」賽馬。
- K1259 建立 repo 的 MCS 基礎；K1535 等既有 ML ceiling 結果顯示，公平資訊集下的複雜模型
  通常難以顯著勝過 HAR family。
- K1711 的差異化是 forecast-pool composition：比較 base-pool MCS 與 augmented-pool MCS，
  而非把單一 point estimate 包裝成架構勝利。

## 資料與期間

| 資產 | 原始 panel 期間 | Primary scoring 期間 | Primary N | RV proxy |
|---|---:|---:|---:|---|
| SPY | 1999-01-04–2026-07-13 | 2016-07-01–2026-07-10 | 2,519 | yfinance 日 OHLC 的 Garman–Klass variance |
| 0050.TW | 2009-01-05–2026-07-13 | 2016-07-01–2026-07-09 | 2,426 | yfinance 日 OHLC 的 Garman–Klass variance |
| TX | 2012-01-02–2026-07-13 | 2016-07-01–2026-07-09 | 2,438 | 本機 TAIFEX 5-min、按成交量選 active contract 的日 RV |

第二個評估 proxy 是 `log(close/open)^2`。0050.TW 的 target 直接使用 raw within-day OHLC
ratios；`clean_tw50_data()` 只套在 close series 作 split diagnostic/proof，刻意不逐欄重寫 target
OHLC，因為逐欄修復會破壞 H/L 的跨欄關係。GK 與 open-to-close squared return 都是日內比率，
跨日等比例 split rescaling 會抵消。Squared open-to-close return 只有在 zero conditional intraday
mean 等理想化假設下才是 conditionally unbiased proxy；本實驗又對 exact zero 使用 pre-window
floor，所以 `r2` 僅是 approximate robustness。完整來源、hash、樣本診斷在
`data/panel_meta.json`。

TSFM 預測由以下公開 checkpoint 產生，context=512、forecast horizon=32：

- `google/timesfm-2.5-200m-pytorch`（TimesFM 2.5, 200M）
- `ibm-granite/granite-timeseries-ttm-r2`，official selector `512-96-ft-r2.1`

逐資產 forecast 數、panel SHA-256、package version 與 model-card corpus 聲明在
`data/tsfm_timesfm_meta.json`、`data/tsfm_ttm_meta.json`。每個 forecast CSV 同時記錄
`target_date` 與 `origin_date`，測試強制 context 結束於 origin，不可包含 target。

TAIFEX collector 會隨日後資料 append；`panel_meta.json` 的 raw SHA-256 記錄 experiment-time
snapshot，commit 內的 derived `panel_TX.csv` 才是本實驗實際評估列的凍結證據。後續 raw common
rows 對帳不代表應以新尾端覆寫已完成實驗。

## Retrospective pseudo-OOS 限定

2016-07+ 主窗口不是 real-time OOS：兩個 checkpoint 都是後來才發布的 artefact，且 TimesFM 的
公開 pretraining corpus cutoff 晚於部分評估期。輸入 context 沒有 forward peek，但 model weights
是否接觸過等價歷史模式無法完全稽核。因此主窗口只能稱 **retrospective pseudo-OOS**。

`vintage_clean` 是沿用的 window key，實際語義只是 2024-01-01 起的 later/cleaner robustness：
它位於 TimesFM 已公開 corpus cutoff 之後，但 TTM 的 training-data cutoff 未 stated。TTM model
card 列舉的金融序列只有 Bitcoin，未列 equity/index volatility；這降低直接 target contamination
疑慮，卻不能把這個窗口稱為 fully model-vintage-clean 或 true real-time forecast evaluation。

## 方法

模型池：

- Base：RW、AR1、HAR、HAR-A。
- TSFM-bearing：TimesFM、TTM、TimesFM-MZ、TTM-MZ、COMB-EW、COMB-MZ、COMB-GR。

HAR、MZ 與 GR 都用 expanding estimation。對 origin `t`，訓練 row `j` 必須滿足
`j + h < t`；target 是 `mean(proxy[t+1:t+h])`。這個 embargo 在 h=1 與 h=5 都有 regression
test。所有模型在同一個 ex-ante calendar 上計分；window 內任何 missing/non-positive forecast
直接報錯，不可靜默縮樣本。

主要評估：

- Loss：Patton QLIKE；MSE 為 robustness。
- MCS：Hansen, Lunde & Nason（2011）的 `max_i t_i` / `e_max`（常稱 T_max/e_max）
  elimination variant，5,000 bootstrap，seed=20260714，α grid
  `{0.01, 0.05, 0.10, 0.25, 0.50}`。`src/volpred/stats/mcs.py` docstring 的 T_R 名稱不精確；
  pairwise `max |t_ij|` 才通常稱 T_R，本實驗沒有把兩者混稱。
- Pairwise nonnested diagnostics：canonical `dm_test` + HLN finite-sample factor，HAC bandwidth
  `ceil(h^(1/3) n^(1/3))`，再於 cell 內做 Holm；primary cells 的 bandwidth 均為 14。
- Cross-asset pooled MCS：先按共同日期平均三資產 QLIKE，再 bootstrap；不把三個同日 shock
  當成三個獨立樣本。

## Nested inference contract

`AR1 ⊂ HAR`、`HAR ⊂ HAR-A`，COMB-GR 的 estimated weights 也可在 null 下 collapse 回 HAR。
這些 pair 的 raw DM/HLN 在 nested null 下不是合法的一般等準確度推論。

- 所有 nested raw DM/HLN 都只存在 `diagnostic_dm_hln`，固定
  `feeds_verdict=false`（`nested-dm: diagnostic-only`）。
- Nested MSE 使用 canonical Clark–West（2007），cell 內 Holm；它只承載 secondary MSE verdict。
  每筆結果顯式記 `small`、`large`、`candidate_role` 與 alternative direction。例如 AR1 row
  檢定的是 larger HAR 是否勝 smaller AR1；reject 不能寫成「候選 AR1 勝 HAR」。HAR-A 與
  COMB-GR rows 的 candidate 才是 larger model。
- Clark–West 是 MSPE correction，不能貼到 QLIKE。Nested QLIKE 沒有本實驗已實作的合法
  general-loss test，因此 verdict 一律
  `INCONCLUSIVE_NO_VALID_GENERAL_LOSS_NESTED_TEST`。
- 未拒絕不等於證明 NULL。Primary headline 只讀 MCS membership，不讀 raw DM/HLN 或 CW。

MCS 自身也有限制：候選 forecast 是 estimated，部分 pair nested；standard MCS bootstrap 沒有另外
校正 nested pairwise QLIKE 的 non-standard null。因此 MCS 只回答「哪些模型未被集合程序排除」，
不能回答「某個 survivor 顯著優於 HAR」或「TSFM 有因果增量」。

## Primary results

### QLIKE 與 full-pool MCS

| 資產 | HAR | HAR-A | TimesFM-MZ | TTM-MZ | COMB-MZ | Full-pool MCS α=.10 |
|---|---:|---:|---:|---:|---:|---|
| SPY | 0.3840 | 0.3693 | 0.3837 | 0.3853 | 0.3784 | HAR, HAR-A, TimesFM-MZ, TTM-MZ, COMB-MZ, COMB-GR |
| 0050.TW | 0.3672 | 0.3581 | 0.3625 | 0.3658 | 0.3587 | HAR, HAR-A, TimesFM-MZ, TTM-MZ, COMB-MZ, COMB-GR |
| TX | 0.1702 | 0.1600 | 0.1654 | 0.1733 | 0.1667 | HAR, HAR-A, TimesFM-MZ, COMB-EW, COMB-MZ, COMB-GR |

Pooled mean QLIKE 的 minimum 是 HAR-A（0.2955）；COMB-MZ 為 0.3003。Pooled MCS 仍同時
保留 `{HAR-A, COMB-MZ}`。因此最精確的描述是「校準/組合後的 TSFM-bearing model 穩定存活」，
不是「TSFM point forecast 最佳」。

### Base-set projection

| 資產 | Standalone base MCS | Base models in full-pool MCS | 改變？ |
|---|---|---|---|
| SPY | HAR-A | HAR, HAR-A | 是 |
| 0050.TW | HAR, HAR-A | HAR, HAR-A | 否 |
| TX | HAR, HAR-A | HAR, HAR-A | 否 |
| Pooled | HAR-A | HAR-A | 否 |

## Robustness 與診斷

- MCS block length 使用 auto、half-auto、double-auto 時，三個 primary superior sets 完全不變。
- Results 中的 elimination trace 只記 α=.01 的 stopping path；較大的 α 才可能淘汰更深，
  因此這個 trace 不標成 complete/deepest path，也不把 survivor lower bound 當 exact p-value。
- `r2` floor 使用 2016-07 primary window 前正值的 0.5%、1%、5% percentile 時，各資產 MCS
  set 不變。
- 換成 noisy `r2` proxy 後，HAR、HAR-A、TimesFM-MZ、COMB-MZ、COMB-GR 仍在三資產 h=1
  MCS；TTM-MZ 在 TX 不存活，COMB-EW membership 依資產/proxy 改變。
- 24 cells × 11 models 的 264 條 QLIKE series mean 與 results JSON 逐項相等；由 series 重算的
  DM-HLN t-stat 與 JSON 最大誤差為 0。compute stdout 的 24 個 MCS@.10 set 與 JSON 相等。
- 沒有策略回測或 Sharpe，故不存在 same-day signal×return 或 Sharpe>2× baseline 問題。

## 圖表

- `figures/fig1_primary_mcs_membership.png` — primary mean QLIKE excess；黑框是 MCS survivor。
- `figures/fig2_cumulative_loss_diff.png` — TSFM-bearing models 相對 HAR 的累積 QLIKE 差。
- `figures/fig3_proxy_robustness.png` — RV 與 `r2` 下的 MCS membership。
- `figures/fig4_calibration.png` — zero-shot 與 MZ recalibration 的 mean QLIKE。

圖表只讀 JSON/series，不重算或改寫統計量；label 全為 ASCII，避免 CJK tofu glyph。

## 重現與驗證

昂貴的 TSFM inference 已快取在 `data/tsfm_*.csv`；目前 results 由 2026-07-14 的完整 evaluation
compute 產生，seed 固定為 20260714。不要為了文件或 nested verdict wiring 重跑 TSFM。

```bash
# Wording/provenance-only refresh（不重算 panel、forecast、loss 或 MCS）
uv run python experiments/k1711/k1711_data.py --refresh-metadata-only
uv run python experiments/k1711/k1711.py --finalize-existing

# 完整 evaluation（讀 cached TSFM forecasts；仍會重估 HAR/combination 與重跑 MCS）
uv run python experiments/k1711/k1711.py

# 單元/回歸測試
uv run --extra dev pytest experiments/k1711/test_k1711.py -q

# 圖表
uv run python experiments/k1711/k1711_charts.py

# 從 main repo 執行 worktree-aware methodology gate
uv run python scripts/experiment_gates.py run --path \
  /absolute/path/to/worktree/experiments/k1711
```

獨立 Codex review 由主線程在 commit 後執行；本目錄不自行產生 `review_verdict=PASS`。

## 產出

- `k1711.py` — forecasting、MCS、DM/HLN、CW 與 verdict wiring。
- `k1711_results.json` — 24 cells、8 pooled cells、sensitivity、adjudication。
- `k1711_series.json` — date-indexed pointwise QLIKE series。
- `k1711_charts.py`、`figures/*.png` — 真實結果圖。
- `test_k1711.py` — lookahead、alignment、HAC、nested verdict wiring regression tests。
- `data/` — derived panels、TSFM forecast cache、metadata/provenance。

## 限制

1. 這是 retrospective pseudo-OOS，不是 model-vintage-respecting real-time contest。
2. SPY/0050.TW 使用 daily OHLC GK proxy，只有 TX 使用本機 5-min RV；跨市場 measurement quality
   不同。
3. 免費 model-card corpus disclosure 不能證明訓練資料完全無污染。
4. MCS membership 是 non-rejection set；集合大小取決於 loss、proxy、block bootstrap 與 pool composition。
5. Nested QLIKE pair 沒有合法 general-loss inference，因此必須保持 inconclusive。

## 參考文獻

- Clark, T. E., & West, K. D. (2007). Approximately normal tests for equal predictive
  accuracy in nested models. *Journal of Econometrics*, 138(1), 291–311.
- Giacomini, R., & White, H. (2006). Tests of conditional predictive ability.
  *Econometrica*, 74(6), 1545–1578. https://doi.org/10.1111/j.1468-0262.2006.00718.x
- Hansen, P. R., Lunde, A., & Nason, J. M. (2011). The Model Confidence Set.
  *Econometrica*, 79(2), 453–497. https://doi.org/10.3982/ECTA5771
- Patton, A. J. (2011). Volatility forecast comparison using imperfect volatility proxies.
  *Journal of Econometrics*, 160(1), 246–256. https://doi.org/10.1016/j.jeconom.2010.03.034
