# Orphan Reap 無主產物處置報告（2026-07-19）

- 產出時間：2026-07-19 13:17（台灣時間）
- 任務：`assign_d8b55d37`（+ `assign_6e8ece3f` 的 k1731-rev5 一筆）
- 權威來源：`storage/ops/orphan_held_state.json`（held 時間軸，非 `orphan_reap_report.json`——後者 live `held:[]`，只有 `held_escalated_paths` 這份持久 escalation 清單）
- held 筆數：**23 筆**（任務標題寫 22；差 1 是 k1380 有 3 筆已改名的舊路徑仍掛在 held state，見下）
- 每筆判定皆已「打開檔案／查對線上產物／查 git 與 knowledge 狀態」，非僅看檔名

## 三類統計

| 類別 | 數量 | 說明 |
|---|---|---|
| **可刪** | 14 | 內容已上線／deliverable 已安全落地／job 失敗或被取代，無殘餘研究價值 |
| **已收編** | 0 | 有價值的無主產物（k1730、k1380）皆為 worktree 未合併或 git 未 commit，**依規則屬主線程操作**（worktree merge 只能走 `merge_worktree.sh`；scope 禁 git commit），不可由本 agent cp/mv 收編（會繞過 certification gate）→ 全歸「需裁決」 |
| **需裁決** | 9 | k1380（8 筆，未 commit 的 active WIP）+ k1730 job（1 筆，未合併的完整實驗） |

**根因共通點**：這 23 筆幾乎全是 reaper 的 **false-positive / stale bookkeeping**，不是真的垃圾——
(a) draft namespace 用 `no_title` 判準，把「已發佈文章的 FB 複本／errata 更正稿」誤當無主草稿；
(b) compute_queue job 的 `output_paths` 指向已合併並移除的 worktree 路徑，檔案不在原位 → 誤判 `no_existing_declared_files`；
(c) k1380 是 working-tree 有未 commit 的改名（→INVALID）+ 修改，reaper 看到 git `D` 狀態就想刪。
**真正該修的是流程**（見文末），不是刪資料。

---

## 類別 A：可刪（14 筆，主線程確認後刪；本 agent 不刪）

### A-1 drafts（6 筆，reason=no_title）— 內容全部已上線
| # | 路徑 | 一行理由 |
|---|---|---|
| 1 | `storage/drafts/digest_20260714.md` | 「避風港出勤表」整篇已以 **mile_5dd7c135**（published）發佈；此為草稿母本 |
| 2 | `storage/drafts/fb_mile_5a20a332.md` | 台積電法說會前夕 FB 雙發佈稿；對應 feed **mile_5a20a332** 已 published，事件（7/15）已過時效 |
| 3 | `storage/drafts/fb_mile_f78be848.md` | 台積電 ADR 跌 FB 稿；對應 feed **mile_f78be848** 已 published，事件（7/16）已過時效 |
| 4 | `storage/drafts/k1410_source_provenance_update.md` | K1410 provenance errata（2026-07-16 撤回「近似含息」）**已套用到線上 mile_c2020d8c** |
| 5 | `storage/drafts/k841_mile_179df5f5_correction.md` | K841 errata（2026-07-15）**已套用到線上 mile_179df5f5** |
| 6 | `storage/drafts/k841_mile_b4304948_correction.md` | K841 errata（2026-07-15）**已套用到線上 mile_b4304948** |

> 註：兩則 fb_mile 未在本機找到 FB 發佈 log；但事件已過時效 3 天、feed 正文與圖皆已上線，FB 稿無論是否已發都無殘餘價值。

### A-2 compute_queue jobs（8 筆）— deliverable 已落地／失敗／被取代
| # | job | reason | 一行理由 |
|---|---|---|---|
| 7 | `job:k1704-formal-cache-rerun-20260716` | no_existing_declared_files | deliverable 已在 `experiments/k1704/K1704_results.json`，K1704 已 **certified PASS**（`review_verdict.json` + knowledge `k1704_certified_20260716`）；held 指向已移除的 worktree 路徑 |
| 8 | `job:k1704-formal-rerun-20260716` | no_existing_declared_files | job **failed**(exit 1)，已被 #7 cache-rerun 取代 |
| 9 | `job:k1704-input-ledger-delta-review-20260716` | no_existing_declared_files | review md 已合併到 `experiments/k1704/pre_run_input_delta_review.md` |
| 10 | `job:k1704-origin-ledger-delta-review-20260716` | no_existing_declared_files | review md 已合併到 `experiments/k1704/pre_run_origin_delta_review.md` |
| 11 | `job:k1704-post-run-review-20260716` | no_existing_declared_files | review md 已合併到 `experiments/k1704/post_run_review.md` |
| 12 | `job:k1731-armB-corrected-rev5` | no_existing_declared_files | rev5 為中間版，已被**同 worktree 內 active 的 rev6/rev7**（最新 2026-07-19 10:35）取代 |
| 13 | `job:lazypack-mile_a8d79d6a-r2` | declared_outputs_not_yet_deliverable | 3 張 panel PNG + render script 已 `partial_delivered`，對應文章 **mile_a8d79d6a 已 published 且含 lazypack 圖**；未交付的只有 `.pyc` / `article.md` 暫存物 |
| 14 | `job:K1694-script-rerun-1211` | no_existing_declared_files | job **failed**(exit 1)，worktree 內只有 `K1694.py`、無 results.json，無有效 deliverable。⚠️ 殘留 worktree 需 reclaim（見文末） |

---

## 類別 B：已收編（0 筆）

無。有研究價值的無主產物（k1730 完整實驗、k1380 active WIP）都不是「散落待 cp 的孤兒檔」，而是
**worktree 未合併 / git 未 commit 的狀態**，依 `.claude/rules/worktree.md` 與本任務 scope（禁 git commit、
worktree merge 屬主線程），本 agent 收編會繞過 certification gate（k1730 無 `review_verdict.json`），
故一律改列「需裁決」，不強行搬移。

---

## 類別 C：需主線程裁決（9 筆）

### C-1 experiments/k1380（8 筆）— 未 commit 的 active Paper 9 WIP，reaper false-positive
**判定：保留，不可刪。** k1380 是 Paper 9「17-spec 多重檢定（White RC / Hansen SPA）」的活躍實驗：
- README 明載 2026-07-16 run 因 QLIKE loss 反向（`σ²/r²`）作廢，re-run 已排；`k1380.py:647` 已修
- compute_queue 有 **4 個 k1380 job**（含 v3 numba / v4 3-strike refactor / spa-test），最新 commit `fa1a2cfab`（今日 13:16）仍在收 Paper 9 C3 followup
- knowledge.json 尚無 K1380 條目（實驗未定案，故 reaper 視為無主）

**held 的真因 = working-tree 有未 commit 的變更**（`git status` 實測）：
```
 M experiments/k1380/README.md          M experiments/k1380/k1380.py
 D experiments/k1380/k1380_losses_all.npy      (→ 改名為 *_INVALID_20260716.npy)
 D experiments/k1380/k1380_results.json        (→ *_INVALID_20260716.json)
 D experiments/k1380/k1380_spa_from_cache.py   (→ *_INVALID_20260716.py)
?? 三個 *_INVALID_20260716.* 為 untracked 新檔
```
| # | 路徑 | held reason | 現況 |
|---|---|---|---|
| 15 | `experiments/k1380/k1380_losses_all.npy` | deletion_not_owned | 檔已不存在，git `D`（改名為 INVALID，未 commit） |
| 16 | `experiments/k1380/k1380_results.json` | deletion_not_owned | 同上，git `D` |
| 17 | `experiments/k1380/k1380_spa_from_cache.py` | deletion_not_owned | 同上，git `D` |
| 18 | `experiments/k1380/README.md` | paired_deletion_pending | 現行檔（modified，記錄作廢與 re-run） |
| 19 | `experiments/k1380/k1380.py` | paired_deletion_pending | 現行修正腳本（modified，line 647 已修） |
| 20 | `experiments/k1380/k1380_losses_all_INVALID_20260716.npy` | paired_deletion_pending | 刻意封存的錯誤 loss cache（README 明言 archived not deleted） |
| 21 | `experiments/k1380/k1380_results_INVALID_20260716.json` | paired_deletion_pending | 刻意封存的作廢結果 |
| 22 | `experiments/k1380/k1380_spa_from_cache_INVALID_20260716.py` | paired_deletion_pending | 依賴錯誤 cache 的死腳本，隨 archive 保留 |

**建議處置（主線程）**：`git add -A experiments/k1380/ && git commit`（把 INVALID 改名 + README/py 修改一次 commit 掉），held 8 筆會自動消失（held state note：「一筆記錄消失＝那個路徑已經有出口了」）。**切勿刪 k1380**——刪掉會毀掉 Paper 9 的 multiple-testing subsection。

### C-2 job:compute-k1730-arm-a-...（1 筆）— 未合併的完整實驗，有研究價值
| # | job | reason | 現況 |
|---|---|---|---|
| 23 | `job:compute-k1730-arm-a-production-quick-mode-1784358686` | no_existing_declared_files | job **completed**(exit 0, 2026-07-18)，deliverable 完整躺在 worktree `dispatch-slot-1-558d7893-k1730/experiments/k1730/`（results 129KB + 4 圖 + `K1730_ARM_A_FULL_RUN_COLLECTION.md` + scripts）；但 **main `experiments/k1730/` 為空、knowledge 無 K1730、無 `review_verdict.json`**（未 certified） |

**建議處置（主線程）**：K1730 已 dispatch followup（job record 有 `followup_next_task_id`），屬 active pipeline。走正規流程：Codex 審 → `experiment_gates.py verdict-template` 產認證 → `bash scripts/merge_worktree.sh dispatch-slot-1-558d7893-k1730`。**有價值，不可刪。**

---

## 附帶發現：殘留 worktree（本報告範圍外，但同源，建議主線程一併處理）

三個 dispatch-slot worktree 仍在（皆 unlocked、不 prunable）：
- `dispatch-slot-1-558d7893-k1730` — **active**（k1730 完整實驗待 certify+merge，見 C-2）
- `dispatch-slot-1-bd00f90a-k1731` — **active**（K1731 rev5/6/7 今日仍在改，最新 10:35）
- `dispatch-slot-1-f53bca44-k1694` — **stale**（K1694 job failed，worktree 內僅 `K1694.py` 無 results）→ 建議 `scripts/reclaim_stale_worktrees.py`

## 流程層建議（PDCA — 讓 reaper 少誤報）
1. **compute_queue job 的 held 判準**：job `status=completed` 且 result 已 merge 進 `experiments/<k>/` 時，held 應改看「experiments/ 內是否有對應 result」，而非死盯已移除的 worktree `output_paths` → 消除 A-2 這類 stale bookkeeping 誤報。
2. **draft intake 的 `no_title`**：對 `fb_mile_*` / `*_correction` / `digest_*` 這類「已發佈文章的衍生複本」應比對 feed 是否已有對應 mile_id/內容，命中即自動回收，不進 held escalation。
3. **experiments/ 的 held**：working-tree 有未 commit 變更（git `M`/`D`/`??`）時不應判 `deletion_not_owned` / `paired_deletion_pending`——那是「待 commit」不是「無主」。

---
### 回傳摘要
- **可刪 14 / 已收編 0 / 需裁決 9**（合計 23）
- 已收編 0 的原因：有價值者（k1730、k1380）皆屬 worktree 未合併 / git 未 commit，依規則歸主線程，不由本 agent 搬移
- 需裁決清單：k1380 全 8 筆（未 commit 的 active Paper 9 WIP → 主線程 git commit）、job:compute-k1730（未合併完整實驗 → 主線程 certify+merge）
- 本 agent 未刪任何檔、未動 feed/knowledge/config、未 git commit（遵守 scope）
