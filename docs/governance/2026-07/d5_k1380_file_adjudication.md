# D5 — K1380 逐檔裁決

**任務**：`assign_0e6a740b`（parent `assign_a006f8ed`）
**外部第二意見全文**：`docs/governance/2026-07/phase_z_ownership_external_review.md`
**裁決時間**：2026-07-22 02:30 台灣時間
**裁決者**：hourly dispatch slot-1（`hourly-slot-1-3ab34f370c9e4c4ca748cc83ca45a2af`）

---

## 1. 為什麼這件事不能交給 cleanup layer

外部意見點名的是 semantics-as-provenance 反例：「檔案在 `experiments/` 裡」不能證明作者、
完整性或 readiness，而 `*_INVALID_20260716.*` 這個命名本身就說明有人做過裁決但沒收尾。
本裁決不猜檔案，而是先把 K1380 的完整時序還原出來，再逐檔判。

## 2. 時序還原（本次裁決的核心發現）

| 日期 | 事件 | 依據 |
|---|---|---|
| 2026-05-19/20 | `experiments/k1380/` v1–v3，三次都 `n_valid=0`（joint mask 塌成空集） | `452c400c5`、`a7c80e124`、`K1380_v4/README.md` |
| 2026-05-22 | **3-strike 重構產出 `experiments/K1380_v4/`** — per-model masks、MIDAS `np.roll` lag 修正、正確 Patton QLIKE | `30c03cb75` |
| 2026-07-05 | **K1380_v4 atomic 重跑，產出 canonical 結果** | `4eadfae10`，`k1380_v4_results.json` metadata timestamp |
| 2026-07-16 | 有人回頭重跑**已被取代的** `experiments/k1380/k1380.py`「從快取 loss matrix 收尾」，得到反向 QLIKE 的垃圾結論 | `fa1a2cfab` |
| 2026-07-17 | 診斷出 loss 反向、改名 `*_INVALID_20260716.*`、寫 erratum README，聲稱「re-run queued」 | README |
| 2026-07-20 | 5 個檔連同其他 50 個 foreign path 被收養進 git | `86d564690` |

**關鍵發現：2026-07-16 那次不是 v4 之後的下一步，而是一次回歸。** 正確答案在 07-16 之前
六週就已經存在於 `K1380_v4/`。README 寫的「re-run is in the compute queue」從來不是真的 ——
`storage/ops/compute_queue/` 裡 8 個 K1380 job 全是 `failed` 或 `cancelled`，沒有任何 pending。
這正是這 8 個檔「卡 78 班」的真正原因：沒有人在等的東西，當然永遠等不到。

**Canonical 結果**（`K1380_v4/k1380_v4_results.json`，已有 knowledge 條目 `K1583`）：

- mean QLIKE ≈ 1.40（A4f rank 1）— 與 paper 自己 K1379 run 的 ≈1.4 尺度一致，正是被作廢那次
  沒通過的 sanity check
- Hansen SPA：`stat=4.205, p=0.289` → 無法拒絕 H0
- White RC on A4f：`t=4.133, p=0.000` → 拒絕 H0，A4f 顯著勝 GJR
- `c3_verdict`: `"C3 MIXED: SPA/RC results require nuanced discussion of data snooping in paper body"`

SPA 與 RC 方向不一致是 v4 自己標記的 MIXED，不是本裁決要處理的問題，但寫 Paper 9 C3 的人
必須據此討論，不可只引其中一個。

## 3. 逐檔裁決

全部 5 檔目前皆為 tracked 且 clean（`86d564690` 之後工作區無殘留）。

| 檔案 | 裁決 | 理由 |
|---|---|---|
| `experiments/k1380/README.md` | **留 main，本次已修訂** | 這是 erratum 記錄本身，是 provenance 的核心。但原文的 STATUS 有兩處失真（宣稱 re-run queued、未指出被 v4 取代），本次已改為 SUPERSEDED 並補上 canonical 指標 |
| `experiments/k1380/k1380.py` | **留 main，標記 superseded** | 有效的歷史來源碼，`:647` 的 loss 修正真實存在。但整條 lineage 已被 `K1380_v4/k1380_v4.py` 取代（後者另修 joint-mask 與 `np.roll` 兩個 v1–v3 致命 bug），不得再拿來跑 |
| `k1380_losses_all_INVALID_20260716.npy` | **留 main 存檔，不刪** | 248KB。它 cache 的是可證明錯誤的 loss，且 `x - log x - 1` 非單射、無法反算修復。保留理由不是可重用，而是它是 erratum 的物證：沒有它，「07-16 那次算了什麼」只剩下敘述 |
| `k1380_results_INVALID_20260716.json` | **留 main 存檔，不刪** | 4.9KB、人類可讀，erratum 引用的 SPA $p=1.000$ / $t=-0.272$ / QLIKE 623.7 全在此。刪掉等於讓 README 的指控失去佐證 |
| `k1380_spa_from_cache_INVALID_20260716.py` | **留 main 存檔，不刪** | README 已正確判定它 dead（唯一輸入是上面那個壞 cache）。保留成本 10KB，且它記錄了「當時是怎麼從快取收尾的」這個流程事實 |
| `storage/work_log.json.bak_graphify_verdict_20260717` | **已不存在，結案** | 檔案在本次裁決時已不在工作區，git 亦無追蹤。無需動作 |
| `config/experiment_artifact_exclusions.json` | **不為 K1380 加任何 entry** | 見下節 |

**「archived, not deleted」是原作者已寫下的決定，本裁決維持。** 三個 INVALID 檔合計約 263KB，
換到的是一份完整可查的錯誤史；相對於 repo 已收養的 50 個 foreign path，這個成本不值得用
「省空間」去推翻一個有論證的決定。真正缺的從來不是刪檔，是那個指向 v4 的箭頭。

## 4. artifact exclusion 裁決：不加 entry

`config/experiment_artifact_exclusions.json` 目前是 tracked、`exclusions: []`、附有一份明確的
`_readme`。它不是半成品，是刻意留空的。本次確認兩件事：

1. **`experiments/k1380/` 根本不在 gate 範圍內。** `check_experiment_artifacts.py sweep` 把它列入
   `not_gated_no_results`，理由 `no archived *_results.json`。因為改名後檔名結尾是
   `_20260716.json`，不符 `*_results.json` glob。這個副作用語義上是對的 —— 被作廢的結果本來就
   不該被當成一筆待記錄的 finding。**不需要、也不應該**為它加 exclusion。
2. **`experiments/K1380_v4/` 有被 gate 到，唯一 violation 是 `missing reproduce_spec.json`。**
   它已有 knowledge 條目（`has_knowledge_entry: true`）。而全 repo sweep 顯示：1266 個 gated
   目錄中有 **1256 個**同樣缺 reproduce_spec（spec-only 1256、knowledge-only 0）。這是 99.2% 的
   系統性缺口，不是 K1380 的個案。

exclusions 檔自己的 `_readme` 寫得很清楚：「An exclusion is an admission that a finding will stay
unrecorded or unreproducible. It is NEVER the cheap way out.」為一個 1256 分之 1 的系統性缺口加
豁免，正是它禁止的用法。**裁決：不加。** reproduce_spec 覆蓋率是獨立議題，應由專門任務處理。

## 5. 對其他任務的影響（已 annotate，未代為結案）

以下兩張 pending 任務的前提被本次時序發現推翻，已在 task pool 加註，但不由本裁決代為關閉
（它們有各自的 owner 與範圍）：

- `dreaming_missing_retry_strategy_paper9_c3_multiple_testing_subsection`（P3，aged 92.7h）——
  「等 retry」的前提不成立，C3 的答案已在 v4
- `k1380_stage_refactor_collect`（P3）—— 標題寫「compute 尚未跑，禁寫 Paper 9」，此前提已可證偽

## 6. 未做的事（明確界線）

- 沒有重跑任何 K1380 計算，也沒有修改 `K1380_v4/` 的任何結果
- 沒有寫 Paper 9 C3 subsection（那是 paper 線的工作，本裁決只提供 canonical 指標）
- 沒有處理 SPA/RC 方向不一致的實質統計爭議
- 沒有清理 stale worktree `dispatch-slot-1-375ba0e3-k1380`（走 `reclaim_stale_worktrees.py`，非本任務）
