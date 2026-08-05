# 裸 NaN / Infinity 全庫掃描結果 ＋ 常設 gate 規格

**執行**：研究部，2026-08-05（經理 D40 第 5 項）
**機器可讀清單**：`bare_nan_inventory.json`（同目錄，可用下方掃描法重生）

---

## 一、為什麼這件事沒有任何 gate 抓得到

Python 的 `json` 模組**預設就發出也接受** `NaN` / `Infinity` / `-Infinity`，所以全平台的
自家工具（讀寫 results、跑 gate、算 metrics）都能順利 round-trip 這些檔案，一路綠燈。

但這三個字面值**不是合法 JSON**（RFC 8259 沒有它們）。嚴格 reader —— 瀏覽器的
`JSON.parse`、Go `encoding/json`、Rust `serde_json`、`jq` —— **拒絕整份檔案，不是拒絕那一個欄位**。

所以失效形態是：**在我們這邊完全靜默，在下游是整份消失。** 這正是經理指出的
「不會讓任何 gate 變紅，只會讓下游嚴格讀者安靜地拒收整份檔案」。

## 二、掃描結果（口徑寫清楚，不含糊）

| 項目 | 數字 |
|---|---|
| 掃描的 `*_results.json` | **1527** |
| regex 命中裸 token 的檔案 | 70 |
| **嚴格 parser 實際拒絕的檔案** | **52** |
| regex 命中但嚴格 parser 接受 | 18 |
| regex 計得的 token 總數 | 960（**上界**） |
| 含 `Infinity`（非只有 NaN）的檔案 | 5 |
| 前 5 大檔案佔 token 總數 | **69.6%** |

**兩個口徑必須分開講**：
- **52** 是真的壞掉的（`json.loads(..., parse_constant=拋錯)` 實測拒絕）
- 另外 18 份是 **regex 假陽性**——token 出現在字串值裡（例如敘述文字寫了 "NaN"），
  那是合法 JSON，不該修。

**以 parser 為準，不以 grep 為準。** 若只報 70，會有 18 份被無謂地改動；
若只報 960 token，會讓人以為工作量是逐 token 的，實際上是逐檔案的。

集中度極高，可先修最痛的幾份拿到大部分收益：

```
  474 × NaN         experiments/k1530/k1530_results.json
   64 × NaN         experiments/k1490/k1490_results.json
   57 × Inf,NaN     experiments/k1261/k1261_results.json
   41 × Inf,NaN     experiments/k1090/k1090_results.json
   32 × NaN         experiments/k1660_mz_calibration_audit/..._results.json
```

## 三、重生方式（掃描邏輯，非結果）

```python
BARE = re.compile(r'(?<![\w"])(-?\bInfinity\b|\bNaN\b)(?![\w"])')   # 粗篩
json.loads(text, parse_constant=lambda n: (_ for _ in ()).throw(ValueError(n)))  # 判準
```

粗篩只用來省下對 1500 份檔案全跑 parser 的成本；**判準永遠是 parser**。

## 四、常設 gate 規格（送 platform_eng；掃描在研究部轄區，gate 不在）

**建議的 enforcement owner**：既有的 `scripts/check_experiment_artifacts.py`
**加一條檢查**，不要新開一支 gate 或 watchdog——這條 concern 屬於「實驗產物是否可用」，
和它已經在管的 knowledge 條目／reproduce_spec／entrypoint 漂移同一類（anti-stacking）。

**規格**：

1. **判準**：對 `experiments/<kid>/*_results.json` 跑
   `json.loads(text, parse_constant=<拋錯>)`；拋錯即 FAIL。**不要用 regex 當判準**
   （本次實測 regex 有 18/70 假陽性）。
2. **scope**：與該 gate 現有 scope 一致（帶 archived `*_results.json` 的目錄），
   不要擴及全 repo。
3. **ratchet 而非一次清乾淨**：52 份既有違規凍結成 baseline
   （形態比照 `storage/ops/dm_hac_lag_baseline.json` 與 `mdd_scale_artifact_baseline.json`），
   **只准變少**。新寫的實驗一律 FAIL——這是把 class 關起來，不是把存量清掉。
4. **修法要修產生端不是修檔案**：正確做法是實驗腳本輸出前把非有限值轉成 `null`
   （或明確的字串標記），**不是事後用 sed 改 JSON**。
   平台已有 `finalize_experiment`（`src/volpred/research/reproduce_spec.py`）作為推薦收尾點，
   在那裡加一道非有限值處理，能一次涵蓋所有走它的新實驗。
5. **修既有檔案會動到 result identity**：52 份裡若有已被 `reproduce_commit.json` /
   `review_verdict.json` pin 住 sha256 的，改檔會讓認證漂移、需重審。
   **所以存量清理必須逐份評估，不可批次 sed**——這也是建議走 ratchet 的理由。

## 五、研究部沒有做的事

- **沒有修任何一份檔案。** 經理 D40 只指派掃描；且修法屬產生端，
  而多數產生端在 worktree 內（研究部目前寫不進去，見 `item_20260805T111505681611Z`）。
- **沒有自建 gate。** gate 屬 platform_eng 轄區，本文件即規格。
