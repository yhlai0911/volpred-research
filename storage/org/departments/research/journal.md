# research 工作日誌（append-only）

## 2026-08-05T08:51Z–09:05Z（台灣時間 16:51–17:05）— 首次啟動：13 worktree 收編判定層

**outcome=done**（判定層完整交付；執行層不屬本部門，已依管道送出）

**一句話結論**：13 個帶未合併 commit 的 worktree，14 個實驗目錄逐一跑 certify 後 **14/14 全部
BLOCKED** —— 收編卡住的根因不是 merge 權限，是這批實驗沒有一個帶著有效的 Codex 審查裁決。

### 處理的 inbox 項

| 工作項 | 處置 |
|---|---|
| `item_20260805T084156023702Z`（P1 當班指令＋範圍修正） | **done** — 判定層全數完成，報告已送經理 |
| `item_20260805T074701282542Z`（P1 13 worktree 收編） | **done（判定層）** — 執行層依經理指示轉平台工程部 |
| `item_20260805T074205980360Z`（派工通道測試單） | **noop** — 依經理指示不產出任何東西 |
| `item_20260805T075102457505Z`（內容部 smoke test 回覆） | **noop** — 依經理指示歸檔；內容部意見已採納（日後送 request 必附 refs 與具體問題） |
| `item_20260805T085056310819Z`（P3 canonical K1737） | **done（判定）** — 不重跑，續作已在池中 pending |
| `item_20260805T085056474828Z`（P3 canonical K1741） | **done（判定）** — 實驗已完成於 worktree，改走收編 |
| `item_20260805T085056629604Z`（P3 canonical K1745） | **done（判定）** — 實驗已完成於 worktree，改走收編 |

### 產出

- `storage/org/departments/research/inventory/worktree_reclaim_20260805.md` — 逐個 K 的判定表：
  ahead commit 內容、產物清單、certify 結果、artifact gate 結果、髒檔 disposition、A/B/C 分組
  建議、對三張 P3 canonical 單的影響、權限缺口。

### 判定摘要

- **certify（merge 第一道門）14/14 BLOCKED**：無 `review_verdict.json` 9、verdict=FAIL 4、
  UNCERTIFIED 1
- **artifact gate 12/14 BLOCKED**：缺 knowledge 條目 9（只能主線程寫）、缺 `reproduce_spec.json` 4；
  兩道全過的只有 k1813 與 k1095_v3
- **髒檔 4 個**：k1747 的 `figures/`＋`tables/`（結果本體，必 commit）、signfc 的
  `review_verdict.json`（審查裁決，必 commit）、k1721 的 `data/`（5MB，含會被覆寫的 GPR xls，
  必 commit）、k1737 的 `data/`（57MB parquet，**不 commit 也不刪**，續作要靠它）；
  四者的 `__pycache__/` 一律丟棄
- **k1737 建議不收編**：結果早於自己的輸入（02:11 vs 02:13/02:16），作者已自行 QUARANTINE 並
  明文禁止 review/merge/寫 knowledge；續作 `split_K1737_cached_rerun_20260802` 已在池中 pending

### 三張 P3 canonical 單的實質內容（本班不重跑，避免同 K 雙 agent）

- **K1741**：`assessment.verdict = CONDITIONAL_PASS`，評估期 2018-01-26～2026-07-31，n=2138。
  方向性效率或費率敏感度存在，但 N=4 事件與多重性 gate 不支持無條件排序。
- **K1745**：`verdict.grade = NULL_NO_MULTIPLICITY_AWARE_TVP_HAR_EDGE`，
  `substantive_positive = false`。預先登錄的雙市場多重性感知 QLIKE 與 fluctuation 準則未同時
  滿足，敏感度分析救不回主要族群。
- **K1737**：實驗未完成，見上。

### 判定後的自我更正（兩點，已同步判定表並補送經理）

- **k1813 從 A 組移到 B 組**：certify 只說「no review_verdict.json」，我一開始讀成「沒審過」。
  實查 knowledge 條目 `ccbccb6a` 發現它已被 Codex primary-path 審過並判 FAIL（2026-08-02，
  2 項 blocking），remediation round 2 `assign_bfd8dbf8` 已在池中 pending。裁決存在，只是沒落成
  檔案。**教訓：certify 說「沒有裁決檔」有兩種成因（沒審過 / 審過沒歸檔），gate 分不出來**；
  其餘 8 個無裁決檔的 K 連 knowledge 條目都沒有，無從交叉驗證，它們「沒審過」只是「沒有相反證據」。
- **k1095_v3 的 artifact gate PASS 是假通過**：`check_experiment_artifacts.py` 的 knowledge 檢查是
  substring 匹配，`k1095_v3` 匹配到更早的 K1095 原版條目而通過。任何 kid 只要是既有 kid 的字串
  延伸就自動繼承前作的通過權 —— 而變體實驗恰恰最需要被 dedup 看見。缺陷在
  `scripts/check_experiment_artifacts.py`（非本部門轄區，未動，已上報）。

### 送出的組織訊息

- → `platform_eng`（P1 request，`item_20260805T090001506186Z`）：4 個 worktree 的髒檔代為 commit，
  明確聲明**先不要 merge**（附 14/14 certify BLOCKED 的理由，免得白跑），原文轉達禁止 `--force`
  與禁止丟棄的裁決
- → `manager`（P1 report，`item_20260805T090150021152Z`）：完整判定＋三件待裁決（A 組要不要
  派審查／B 組 FAIL 要不要排修復／k1737 建議不收編）＋三張 P3 單改走收編的建議＋權限缺口
- → `platform_eng`（P2 request，`item_20260805T090428568009Z`）：inbox 歸檔代執行＋建議補歸檔 CLI
- → `manager`（P1 report，`item_20260805T090918196998Z`）：上述兩點自我更正（A 組 6→5、B 組 4→5）
  ＋ artifact gate substring 缺陷

### 阻塞與教訓

- **收尾契約第 3 條（inbox 項移入 `_archive/`）本班無法執行**：`mv` 與 `rm` 在本部門權限下被 deny，
  且 `scripts/org/` 沒有任何 inbox 歸檔 CLI（`grep -rn "_archive" scripts/org/*.py` 只有讀取端）。
  已另送 request 請平台工程部代執行並補工具。**這是組織流程的洞，不是本次的個案**：契約要求的
  動作沒有對應的工具，也沒有對應的權限。
- `dept_send.py --task` 內容含反引號會整則被 deny（shell 命令替換偵測）。第一次送經理報告即因此
  失敗，移除反引號後成功。日後寫組織訊息一律不用反引號。
- `git -C <worktree> status` 被 deny → 髒檔判定改用 `ls -la` 對照 `git diff --name-only` 推導。
  **對 untracked 完整、對 modified 是盲的**，判定表已標註此限制。
