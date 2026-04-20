# K1259 — MCS/SPA Meta-Analysis (Phase 1: DM Pair Ledger)

**Phase 1 只做一件事**：掃描 `experiments/k400` 到 `experiments/k1258` 範圍內的
`*_results.json` / `results.json`，把所有可辨識的 Diebold-Mariano (DM) 成對比較統計
抽成**平坦 JSON ledger**，供 Phase 2 的 MCS（Hansen-Lunde-Nason 2011）/ SPA
（Hansen 2005）演算法使用。

> 本資料夾**不**含 MCS / SPA 主算法 — 那是 Phase 2。Phase 1 的產出是
> meta-analysis 的**資料基底**，必須先 self-contained、schema-consistent、
> 能被 Phase 2 的 loader 直接吃下去。

## 目錄內容

| 檔名 | 用途 |
|---|---|
| `README.md` | 本檔，解釋資料抽取邏輯、覆蓋範圍、限制 |
| `build_dm_ledger.py` | Phase 1 產生器；idempotent，重跑會覆寫兩個 output |
| `dm_ledger.json` | 結構化 DM ledger（rows array，strict schema） |
| `dm_ledger_summary.md` | 人類可讀摘要（coverage、distribution、gaps） |

## Row schema（strict）

每 row 必含以下 12 key（缺值以 `null` 表示，**不得**插補 / 偽造）：

```json
{
  "k_id": "K530",
  "model_a": "GJR-t",
  "model_b": "EWMA",
  "loss_fn": "QLIKE",
  "asset": "SPY",
  "sample_n": 1580,
  "period": "2020-01-02 to 2026-04-06",
  "dm_stat": -3.59,
  "p_value": 0.0003,
  "harvey_adjusted": true,
  "source_file": "experiments/k530/k530_results.json",
  "source_field_path": "dm_tests.GJR-t_vs_EWMA"
}
```

欄位語意：

- `k_id` — 從 folder name 抽（`experiments/k530/` → `K530`）
- `model_a` / `model_b` — pair 的兩個 model 名稱；依以下順序解析：
  1. 明確欄位 `model_1/model_2`、`model_a/model_b`、`baseline/candidate`、`m1/m2`
  2. `comparison` 或 `pair` 字串（parse `" vs "` / `"_vs_"` / `"-vs-"`）
  3. 包含 pair dict 的 key name（e.g. `"HAR-PD vs HAR"`）
- `loss_fn` — 明確 `loss` / `loss_fn` 欄位優先；否則從 context path 推斷
  （`qlike` → `QLIKE`、`fz1` → `FZ1%`、`mse` → `MSE`、`parkinson` → `Parkinson` 等）；
  若無線索但在 DM context 下，預設 `QLIKE`（本 codebase 慣例）
- `asset` — 明確 `asset` / `ticker` / `symbol` 欄位優先；否則從 ancestor context keys
  尋找已知 ticker（SPY, QQQ, GLD, 0050.TW 等）；若皆無則留空 `""`
- `sample_n` — pair 內 `n_valid` / `n` 優先；否則 root 的 `n_oos` / `n_total` / `sample_size`
- `period` — pair 的 `period` / `subperiod` 優先；否則從 context 抓 subperiod 標籤
  （`Bear_2022`, `GFC`, `vix_buckets.Extreme` 等）；否則 root `data_period` / `period`
- `dm_stat` — 從 `dm_stat` / `dm_t` / `DM` / `t_stat` / `harvey_t` / `DM_HLN_t` 任一抽取
- `p_value` — 從 `p_value` / `p_val` / `p` / `dm_p` / `DM_HLN_p` 抽取；**不**做兩側 z 估計
  （研究誠實原則 — 估計值會污染 Phase 2 MCS p-bootstrap；留 `null` 由 Phase 2 決定處理）
- `harvey_adjusted` — 來自 `harvey_adjusted` / `harvey_pass` / `harvey_significant` / `significant_harvey`；
  若 key 名稱含 `DM_HLN_t` / `harvey_t` / `harvey_p` 則推斷為 `True`（做了 Harvey 校正）；
  其他情況留 `null`（未知，不推斷）
- `source_file` — repo-relative path，從 `experiments/` 開始
- `source_field_path` — dot-notation JSON pointer，用於 Phase 2 回溯稽核

## 抽取邏輯

`build_dm_ledger.py` 對每個 JSON 做遞迴 walk：

1. 探測「pair container」：dict 本身有 `dm_stat`-like + `p_value`-like 欄位，
   或 dict 的子 key 是 `"A_vs_B"` 形式且值是 pair dict
2. 探測「pair list」：`dm_tests: [...]` 的 list 元素各自是 pair dict
3. 支援的 nested 結構（實測觀察到的）：
   - `root.dm_tests.{pair_key}` — 最常見（K1000, K1014, K1015）
   - `root.dm_tests[i]` — list 形式（K869, K890, K910）
   - `root.assets.{TICKER}.dm_tests.{pair_key}` — 多資產實驗（K1004）
   - `root.results.{TICKER}.periods[i].dm_tests` — 多期間（K1253 等）
   - `root.vix_buckets.{bucket}.dm_t/dm_p` — 單 pair，bucket-specific
   - `root.crisis_subperiods.{name}.dm_t/dm_p` — 單 pair，subperiod-specific
   - `root.rolling_dm.samples[i].dm_t/dm_p` — rolling window
   - `root.pass_cells_BH/harvey[i].DM_HLN_t/p` — K1241 系列（already HLN-adjusted）
4. Context key stack 紀錄 ancestor，供 asset / period / loss 推斷

**Dedup policy**：同一 `(k_id, source_field_path, model_a, model_b, loss_fn, asset, period)`
組合在同一檔內只保留一 row。跨檔不去重（不同 K 的相同 pair 是合法獨立 DM test）。

## 當前覆蓋範圍（見 `dm_ledger_summary.md` 最新數字）

- **Rows**: 2,741
- **K experiments 有貢獻 DM rows**: 236 / 749 folder in range
- **Unique model names**: 811（含 case variants，Phase 2 建議正規化）
- **Assets with ≥20 rows**: SPY (465), QQQ (140), GLD (112), 0050.TW (73),
  USO (70), EWT (62), IWM (29), TLT (26), EWJ (20)
- **Loss functions**: QLIKE (2263), MSE (321), Parkinson (86), FZ (64), ES (6), FZ1% (1)
- **|dm_stat| > 3 (Harvey-significant 粗略門檻)**: 30.3%
- **p-value available**: 2480/2741 (90.5%)

## 已知限制（Phase 2 必處理）

1. **1,695 rows 缺 asset tag**（約 62%）— 多為單資產 K 未在 pair dict 或 context
   明示 ticker。Phase 2 需回讀 source JSON 的 `data_source` / `references`
   或從檔名推斷（禁用 blind default "SPY"）
2. **Model name 大小寫不一**（`GJR` vs `gjr`, `HAR` vs `har`）— 811 是過度計數；
   Phase 2 MCS 前必跑 canonical 名稱 mapping（建議 lowercase + 底線正規化 + alias table）
3. **Loss fn 有些仍被推為 QLIKE 預設**（DM-family 慣例）— Phase 2 對 VaR/ES 比較
   （FZ loss）需特別檢查 context 是否匹配
4. **Harvey adjustment 狀態**大多數 row 是 `null`（既非 True 也非 False）— Phase 2
   做 HLN bootstrap 時需保守假設 un-adjusted 並自行套 Harvey-Leybourne-Newbold (1997) 校正
5. **Period 欄位格式不統一** — 有 `YYYY-MM-DD to YYYY-MM-DD`、`OOS_YYYY-MM-DD`、
   `Bear_2022`、`vix_buckets:Extreme` 等；Phase 2 MCS 需分兩層 partition：
   (a) full-sample vs subperiod；(b) calendar period
6. **重複性 pair**：同一 `(model_a, model_b, asset)` 在不同 K 之間可能代表
   不同 OOS / 不同 rolling window；Phase 2 MCS 要分組處理，不可視為獨立觀察
7. **K 編號 419 之前有 31 個 folder 未掃**（`experiments/kXX`、`experiments/kXXX`
   三位數以下）— 依任務要求 K400-K1200 範圍；若 Phase 2 需更廣可擴 `build_dm_ledger.py`
   的 range filter

## 重跑方式

```bash
cd /Users/yhlai0911/Desktop/volpred-research
python3 experiments/k1259/build_dm_ledger.py
```

約 10-15 秒完成。Idempotent — 重跑會覆寫 `dm_ledger.json` 與
`dm_ledger_summary.md`；不動 source JSON，不動共享狀態。

## 與 research_program.md 的連結

此 ledger 是 K1259 主實驗（MCS/SPA meta-analysis — 用統計嚴格方式總結
「哪個 model 在哪個 asset / 哪個 loss 上最不可拒絕」）的 Phase 1。Phase 2
預計輸出：

- 每個 `(asset, loss_fn)` cell 的 MCS 集合 M^*_{90%}（內含之 models 在統計上
  不可拒絕為 best）
- SPA test p-values（Hansen 2005）以檢驗 superior predictive ability
- Bootstrap 變異度分析（stationary bootstrap，block length via 實證最佳化）

Phase 2 設計稿見 `research_program.md`（待 Phase 1 簽收後補）。

## 防錯合規

- ✅ 不偽造數字 — 缺值留 `null`，source_field_path 可回溯稽核
- ✅ 不插補 dm_stat 或 p_value — 缺 p 就缺，Phase 2 自行處理
- ✅ 不修共享狀態（`storage/memory/knowledge.json`, `feed.json` 等）
- ✅ 只寫 `experiments/k1259/` 目錄下 4 檔（README, script, ledger, summary）
- ✅ Source file 均為 repo-relative path
