# snapshot-dup 污染事件 — 三份平行 audit 的裁決對帳

**產出**：2026-07-22 00:2x 台灣時間，hourly dispatch slot-1（job 457427c2）
**觸發**：`assign_3df3d4c6`（snapaudit remediation：補齊遺漏 consumers 後重審），已餓死 57.3h
**結論**：**audit A 作廢，audit C 為權威裁決集，audit B 為 rerun 證據來源。**

---

## 0. 為什麼會有三份

同一起事件（2026-05-18 快照重複列污染，9 個 canonical CSV 各含 10 個重複交易日）被**三個獨立
agent 各審一次**，彼此不知情，分母與結論都不同：

| | branch | 日期 | 分母 | affected | 結論 |
|---|---|---|---|---|---|
| **A** | `wt/dispatch-slot-1-858545f9-snapaudit` | 07-19 | 44 consumers | 8 | `conclusions_changed_by_the_contamination: 0` |
| **B** | `snapaudit-dcc222db` | 07-20 | 64 consumers | 16（10 已重跑） | 10 個產出數字改變 |
| **C** | `wt/dispatch-slot-1-20b291d5-snapdup` | 07-21 | 70 篩 / 51 裁決 | 9 確認 + 4 未定 | **2 個顯著性判定被翻轉** |

三個 worktree 中只有 C 的還在（A、B 的 worktree 已移除，**但 branch 都在、成果沒丟** —— 已逐一
`git log main..<branch>` 確認）。

## 1. 裁決：A 的頭條結論是錯的

A 宣稱 `conclusions_changed_by_the_contamination: 0`、`paper_numbers_changed: 0`。這個結論建立在
**不完整的 consumer 集合**上：

- Codex primary-path review 早已判 A **FAIL（MAJOR-1）**
  （`storage/ops/codex_reviews/audit_dup_snapshot_20260719_verdict.md`），理由是 A 自己的
  `needs_compute_queue` 列出的 snapshot readers 沒進 `consumers_scanned`。
- 本次逐一比對確認：A 的 44 個 path 中**沒有 k1319**。而 k1319 正是後來被證實會翻轉判定的那一個。
- B 與 C **各自獨立重跑**，對 k1319 得到**完全相同**的數字：
  DM `har_vs_ewma` t 從 **−2.9319 → −3.1085**，p 從 0.0034 → 0.0019。
  兩份獨立 rerun 吻合到小數第四位 —— 這不是單一 agent 的自說自話。
- −3.1085 跨過 Harvey |t| > 3.0 門檻 → **顯著性判定本身改變，不只是小數位**。

因此 A 的頭條不是「保守但安全」，而是**分母錯了導致的偽陰性**。修補 A（原任務要求的
「補齊遺漏 consumers 後重審」）已無意義：C 用更大的篩選面（70 檔）重做了整件事，且對所有 9 個
確認案例達成 exact reconstruction。**A 作廢，不再投入。**

## 2. 權威裁決集 = C，證據補強 = B

C（`experiments/audit_snapshot_dup_20260721/`）的裁決分類：

| verdict | n |
|---|---|
| CONTAMINATED_VERIFIED | 8 |
| CONTAMINATED_VALUES_ONLY | 1 |
| AT_RISK_UNVERIFIED | 4 |
| UNVERIFIABLE_MISSING_INPUT | 1 |
| PROTECTED_DEDUP | 18 |
| PROTECTED_DATE_WINDOW | 11 |
| NOT_A_CONSUMER | 8 |

確認污染 9 個：`k1319, k1391, k1396, k1398, k1399, k1591, k1592, k1705,
paper2_table1_summary_stats_provenance`。

B 的價值在**成對重跑的機制乾淨**：A/B 兩臂取自同一 git vintage（`00b07f07f^` vs `00b07f07f`），
並先驗證 `dedup(A) == B` byte-identical，因此任何 delta 只能歸因於那 10 個重複列。B 也誠實記下
**vintage caveat**：重跑落在 2026-07-19 vintage，與原始執行 vintage 不同 → **方向與量級可信，
精確更正值仍須在原 vintage 重跑**。這個 caveat 要帶進所有下游更正，不可省略。

### 一處 C 的內部標籤張力（已記，不自行改對方文件）

C 把 k1592 標成 `CONTAMINATED_VALUES_ONLY`，但 C 自己的 `verdict_flips_found` 又把 k1592 列為翻轉
（`dm_GammaRule_minus_GJR_p` 0.038 → 0.137 跨 5%）。B 的重跑支持後者（85 個欄位改變）。
以 `verdict_flips_found` 為準：**k1592 是判定翻轉，不是純數值變動**。標籤待 C 的 owner 修。

## 3. 待更正產出（依 C 的 `artifacts_needing_correction`，嚴重度排序）

| consumer | 嚴重度 | 為什麼 |
|---|---|---|
| **k1319** | HIGH | DM t −2.9319 → −3.1085 跨 Harvey \|t\|>3.0，**判定錯誤**非小數位 |
| **k1592** | HIGH | 10 筆偽造零報酬使 panel mean_losses 膨脹 ~25-30%；p 0.038 → 0.137 跨 5%；**列數是乾淨的，count-only 稽核看不見** |
| k1705 | MEDIUM | 143 欄位改變；mean_dcc_rho 0.00215 → 0.00109（~96%）。KS/Ljung-Box 判定未翻 |
| k1399 | MEDIUM | 全部 OOS QLIKE 與 DM-HLN 位移；H1..H5 判定未翻，敘事成立但數字錯 |
| paper2_table1_summary_stats_provenance | MEDIUM | SPY row：n_obs 4668 → 4658, kurt 14.1197 → 14.0832。**這是論文 Table 1 的 provenance 產物** |
| k1391 | MEDIUM_UNQUANTIFIED | stored `n_full_oos=1866` 證明吃進重複列，但未重跑，量級未知 |
| k1591 | MEDIUM_UNQUANTIFIED | stored `data.n_obs=4091` 證明污染；因需連網抓 macro 未重跑 |
| k1398 | LOW | 三資產皆污染但效果 ≤1.7%，DM t 在 9-35 遠離門檻，無翻轉 |
| k1396 | LOW | 僅 legacy-rerun 產物受影響；frozen 產物未動，且 K1379 已取代公開詮釋 |

## 3b. 觸及面：audit B 的 downstream 盤點推翻了 A 的「只有一篇文章」

A 記 `reached_a_reader = 一篇已發佈文章 (mile_02c71e74) + 一個 knowledge 條目`。B 對 10 個
`numbers_changed` 的 consumer 逐一追下游，實際觸及面大得多：

| consumer | 欄位變動 | 下游 |
|---|---|---|
| **k1592** | 85 | **`paper/leverage-direction/body_v_ijf.tex:332`** 表註 + **頭條結論**「no asset and no panel meets this criterion」+ SPY Holm p=0.104；L22/L124/L130 亦有註 |
| **k1591** | 95 | **`paper/leverage-direction/body_v_ijf.tex:358`** gamma_diff=−0.087、HAC t=−0.66、bootstrap CI [−0.71,+0.39]、69.8% negative draws |
| k1391 | 161 | `paper/garch-x-vix/errata_pending.md` §SF1-K1391（已標記 n=1866）、EXECUTION.md、review_history、feed |
| k1396 | 13 | feed ×4（2 篇已發佈 + 1 篇未發佈 + 1 篇「K1396 更正」）、index.json、garch-x-vix review_history v5/v7 |
| k1399 | 36 | 已發佈 `mile_34157161` |
| k1308 | 21 | 已發佈 `mile_02c71e74` |
| k1319 | 13 | feed.json 有 K1319（**判定翻轉案例**） |
| paper2_table1_summary_stats_provenance | 23 | `paper/taiwan-vt body_v3.tex` `tab:summary_stats` 的 provenance check |
| k1585 | 125 | 僅 knowledge.json ×2 |
| k1498 | 162 | paper/ 與 storage/reports/ 皆無引用 |

**最嚴重的一項**：`leverage-direction` 是目前唯一接近 ready-for-submission 的論文，而它 body 裡的
兩處數字（含一個頭條結論）源自受污染面板。已建 P1 任務
`snapaudit_paper_leverage_direction_k1591_k1592_contaminated`（機器來源被 admission clamp 降為 P2，
但性質是投稿完整性）。**在它關閉前，leverage-direction 不得推進 arXiv 或投稿。**

### B 與 C 對 k1308 的分歧，以 B 為準

C 把 k1308 標 `UNVERIFIABLE_MISSING_INPUT`（VIXTWN CSV 在 C 的環境不存在）。但 **B 有 fixture 且
重跑成功**（21 欄位改變）。C 的 unverifiable 是**環境限制，不是結論** —— 這正是 B 保留為證據來源
的價值所在。

## 4. 仍未關閉（C 自陳，本次未擴權處理）

1. `k1497 / k1498 / k1585 / k1380` 讀 canonical CSV、無 dedup、窗口開放，但**沒有 stored count
   可釘 vintage**，也未重跑（k1380 的 SPA bootstrap 昂貴）。暴露已從源頭確立，量級未測。
2. `k1308` 無法關閉：其 n=119 來自對 VIXTWN CSV 的 inner merge，該路徑
   （`~/Desktop/volpred-research/data/vixtwn/vixtwn_daily.csv`）在本機不存在 → 既無法 count 證明也無法重跑。
3. 執行時間歸因用「實驗目錄的 git commit 日期」當 proxy；在污染窗口內執行但較晚 commit（或修好後
   重跑未再 commit）者會被誤判。**有 stored count 的案例不依賴此 proxy，且以 count 為主證。**
4. 三份 audit 都**沒有**寫 `storage/memory/knowledge.json` / `feed.json`（K1259 gate 正確遵守）；
   受影響 K-id 的 knowledge 條目待主線程寫。

## 5. 本次的處置

- `assign_3df3d4c6`（修補 A）→ **完成為 superseded**：A 已作廢，修補它是白工。
- 新建 `snapaudit_correct_k1319_k1592_original_vintage`（P2）：兩個 HIGH 案例在**原 vintage** 重跑
  取得精確更正值 → 更正 results.json + knowledge 條目。
- 新建 `snapaudit_quantify_unmeasured_exposure`（P3）：k1391 / k1591 / k1497 / k1498 / k1585 / k1380
  的量級測定 + k1308 的資料可得性裁決。
- Branch 處置：A（`wt/dispatch-slot-1-858545f9-snapaudit`）與 B（`snapaudit-dcc222db`）的 worktree
  已不存在、branch 保留為證據，**不合併**（A 已作廢；B 的 rerun 證據由本文件與 C 引用即可）。
  C 的 worktree 仍在，合併走它自己的 review gate，不在本次範圍。

## 6. 教訓（給流程，不是給某個 agent）

同一起事件被派了三次，三次都從零開始篩 consumer，得到三個不同分母、其中一個結論是錯的。成本是
三份 agent 工時，風險是「先完成的那份（A）差點以 `conclusions_changed: 0` 定案」。派工端在建
audit 類任務前應先查同 incident 是否已有進行中的 audit —— 這與 K-article 的 dedup gate 是同一類
問題，只是發生在 ops 側而非內容側。
