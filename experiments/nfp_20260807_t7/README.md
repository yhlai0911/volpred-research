# nfp_20260807_t7 — 非農前 T-7→T-1 的 VIX 路徑

狀態：**正式收編／canonical rerun 完成；結論為 `NULL_FAILURE_TO_DETECT`**。

這個 evidence package 支援事件文章 `mile_84e3be0a`（`NFP_US_2026_08_07`,
slot `T-7`）。原 producer 在 2026-07-31 留下三個未追蹤檔案後結束，沒有 README、
canonical entrypoint、raw input snapshot 或 runtime `reproduce_spec.json`，因此 orphan
reaper 連續 45 班只能把整個 atomic unit 標成 `atomic_unit_incomplete`。本次不刪除或
覆寫舊證據，而是把它收編成可離線重跑、可審查的正式實驗。

## 問題與差異化

問題是：從官方 NFP 公布日前第七個交易日收盤（T-7）到前一交易日收盤（T-1），
VIX 的六個交易日變化是否不同於沒有與 NFP 前置視窗重疊的同長度控制視窗？

這不是 NFP 當日反應研究，也不是交易策略。條件變數只使用 T-7 已知的 VIX 水位；
歷史事件日來自 FRED/ALFRED release id 50，而不是「每月第一個週五」proxy。這個
日期來源選擇直接承接 knowledge `390d9784`：該 proxy 曾在 13 筆中錯 7 筆並翻轉
兩個方向性結論。

## 資料與 information set

- VIX：Yahoo Finance `^VIX` 日收盤，2010-01-04 至 2026-07-30，原始 cache 中
  2026-06-19、2026-07-03 兩個無有效 close 的假日列被明列後移除；有效 4,169 列。
- NFP 日曆：FRED/ALFRED release dates API，release id 50（Employment Situation），
  query 2010-01-01 至 2026-07-31；每月若有 off-cycle entries，依 canonical helper
  取最早一筆並通過 13–110 天 cadence gate。
- 歷史事件：191 次可對上交易日的官方公布日，2010-02-05 至 2026-07-02。
- target event：2026-08-07。發布排程的 `T-7` 是七個日曆日前的內容槽；研究條件
  的 `T-7` 是第七個交易日前收盤，因此固定使用 2026-07-29 的 VIX 20.66。
  snapshot 另保留 2026-07-30（交易日 T-6）供完整歷史樣本重跑，但不會以最後一列
  覆蓋 target 的 T-7 information set。
- 無估計器 seed、bootstrap、Monte Carlo 或抽樣；`randomness=not_applicable`。

兩個 input snapshot 位於 `data/` 且由 `reproduce_spec.json` 逐檔綁 sha256；正常重跑
`network=deny`，不再受到 Yahoo/FRED 後續回補或修訂影響。

## 方法修正

### 1. exact interval overlap

事件窗從 index `i-7` close 到 `i-1` close，實際使用的六段 return interval 是
`i-6..i-1`。控制窗從 `k` close 到 `k+6` close，使用 `k+1..k+6`。兩者相交的充要
條件是 `i-12 <= k <= i-2`。

封存版實作排除 `i-13..i`，多排除三個實際不相交的起點；canonical 版依上述
interval 定義逐段驗證，留下 2,062 個控制窗。`nfp_20260807_t7_controls.csv` 保存完整
claim surface，測試會逐一證明其六段 return interval 與所有事件窗不相交。

### 2. overlapping outcomes 不可視為 iid

2,062 個控制窗是 daily rolling 六日變化，彼此大量重疊。封存版用 iid Welch 與
Mann–Whitney 當正式推論，會把重疊窗誤當獨立樣本。canonical primary test 改為按
start date 排序的 `chg_pct ~ const + event` OLS，使用 Newey–West HAC covariance；
primary lag=22，另完整報 lag 6/22/60 sensitivity。封存 iid 統計只保留為 reconciliation
diagnostic，不再承載結論。

這個處理依循 overlapping-horizon 與 HAC 文獻：

1. Hansen, L. P. & Hodrick, R. J. (1980), “Forward Exchange Rates as Optimal
   Predictors of Future Spot Rates,” *Journal of Political Economy* 88(5),
   829–853, DOI `10.1086/260910`。
2. Newey, W. K. & West, K. D. (1987), “A Simple, Positive Semi-Definite,
   Heteroskedasticity and Autocorrelation Consistent Covariance Matrix,”
   *Econometrica* 55(3), 703–708, DOI `10.2307/1913610`。
3. Andrews, D. W. K. (1991), “Heteroskedasticity and Autocorrelation Consistent
   Covariance Matrix Estimation,” *Econometrica* 59(3), 817–858,
   DOI `10.2307/2938229`。

## Canonical 結果

| 指標 | NFP 前置窗 | exact-overlap 控制窗 |
|---|---:|---:|
| n | 191 | 2,062 |
| 平均六日 VIX 變化 | +1.631% | +0.800% |
| 中位數 | -1.802% | -1.363% |
| 標準差 | 17.307% | 18.161% |
| 上漲比例 | 44.50% | 45.88% |

Primary mean difference = **+0.830 percentage points**；Newey–West HAC(22)
SE=1.514、t=0.548、two-sided p=0.583，95% CI **[-2.137, +3.798]**。

Lag sensitivity 均為 failure to detect：

| HAC lag | t | p |
|---:|---:|---:|
| 6 | 0.561 | 0.575 |
| 22 | 0.548 | 0.583 |
| 60 | 0.583 | 0.560 |

四個 T-7 VIX regime 的 event-vs-control HAC p 分別為 0.964、0.683、0.165、0.250；
Holm 校正後最小 p=0.659。原本看似單調的梯度仍主要由 VIX 起點水位解釋，沒有任一
regime 提供可通過 multiple-testing gate 的 NFP-specific evidence。

**結論強度**：在這份 pinned daily-close sample 與 HAC specification 下，未偵測到
NFP 前 T-7→T-1 對 VIX 六日變化的增量效果。這不是等效性檢定；信賴區間仍容許約
-2.14 到 +3.80 個百分點的效果，所以不能說「效果等於零」。

## Legacy bytes 與更正義務

以下三個檔案是 2026-07-31 producer 留下的原始 bytes，完整保留，不作 canonical source：

- `nfp_t7_results.json`
- `nfp_t7_events.csv`
- `nfp_t7_regime.png`

原版沒有保存 raw VIX snapshot；Yahoo cache 後續回補後，原本控制組 n=1,485 已無法從
現行資料逐位重建。原文章引用的 iid Welch p=0.342 也不適合 rolling-overlap controls。
線上文章 `mile_84e3be0a` 已於 2026-08-02 經 `publish_draft.py --update` 正式更正：
改引用 `nfp_20260807_t7_results.json`、canonical figure 與 HAC p=0.583，並在
`errata.update_action=nfp_t7_hac_provenance_correction` 留下 audit trail。
結果檔的 `published_article_correction.required=true` 記錄的是本次正式化當下發現的義務；
是否已履行由 canonical feed 的 errata 與 live reader read-back 證明，不把 mutable 發布狀態
反寫進可離線重跑的研究結果。

舊 producer 腳本當時也是未追蹤檔；在加入退役 wrapper 前沒有保存 byte-exact pre-image，
因此不能宣稱原始 producer source 有可驗證 hash。`scripts/gen_nfp_20260807_t7_analysis.py`
只保留明確標為 `LEGACY_SOURCE_UNVERIFIED` 的 inert forensic text；可驗證且必須保持不變的
原件是上述三個 `nfp_t7_*` artifacts，測試逐檔鎖定它們在任何 wrapper call 前後的 sha256。

## 檔案

- `nfp_20260807_t7.py`：canonical network-free entrypoint。
- `nfp_20260807_t7_results.json`：canonical result + runtime code trace。
- `reproduce_spec.json`：runtime-generated spec、input/result identity。
- `nfp_20260807_t7_events.csv`：191 個事件窗完整列。
- `nfp_20260807_t7_controls.csv`：2,062 個 exact-overlap 控制窗完整列。
- `nfp_20260807_t7_regime.png`：canonical chart。
- `data/`：兩個 pinned raw inputs。
- `nfp_t7_*`：preserved legacy artifacts。

## 重跑與 gate

```bash
uv run python experiments/nfp_20260807_t7/nfp_20260807_t7.py
uv run python scripts/experiment_gates.py run \
  --path experiments/nfp_20260807_t7
uv run python scripts/check_experiment_artifacts.py check \
  --path experiments/nfp_20260807_t7
uv run pytest tests/test_nfp_20260807_t7_artifacts.py -q
```

`--bootstrap-snapshots` 只供全新 experiment identity 的一次性 acquisition，不是 reproduce
path。只要 `data/` 已存在就會在任何 network call 前 fail closed；首次 acquisition 也先寫入
staging directory，再以 directory rename 一次安裝，不能覆蓋已 pin 的 inputs。
