# snapdup 稽核（audit_snapshot_dup_20260721）— bounded remediation（逐項修 Codex FAIL 5 blocking）

**Model**: opus / max (per model_router)。禁止原樣重派、禁止 force-merge、禁止手改 verdict 繞 gate。

## 背景
worktree `dispatch-slot-1-20b291d5-snapdup`，實驗 `experiments/audit_snapshot_dup_20260721/`。
Codex re-review（非額度鎖、非空檔）判 **FAIL**，全文：
`storage/ops/codex_reviews/audit_snapshot_dup_20260721_verdict_rerun20260727.md`。
此稽核的用途是判定哪些 K 因 snapshot 重複交易日污染需撤回/P1 修正 —— 數字不可信就不能拿去撤回，故必須修到可查證。
**只准在此 worktree 內 `experiments/` 寫**。禁碰 feed.json / knowledge.json / 主線其他檔。

## 開工先讀
- verdict 全文（上路徑）
- `audit_snapshot_dup_20260721.py` / `README.md` / `..._results.json` / `reproduce_spec.json` / `rerun_cache.json`
- 相關 consumer：k1583.py（:124/:148）、k1592.py（:75/:80/:82/:303/:353）、K1380_v4 dedup commit `4eadfae10`(2026-07-05)

## 5 個 BLOCKING defect —— 逐項修，每項要有可驗證產出

### B1（py:444，最關鍵）：k1583 被錯判 PROTECTED_DEDUP，實為真污染者
- 事實：k1583.py:124 載入 K1380_v4 loss matrix；:148 才配日期並丟重複 index —— 只刪日期標籤、清不掉 .npy 內已污染的 loss。K1380_v4 的 dedup 是 2026-07-05 `4eadfae10` 才加，k1583 結果產於 2026-06-30，當時在污染 frame 上算 return。
- 修法：重新分類 k1583 為 CONTAMINATED（非 PROTECTED_DEDUP），修正 classification 邏輯使「dedup 發生在下游 loss 已污染之後」不算保護；重算「確認污染數」下限（不再是 9）與 dedup「無罪」清單（原 18 至少錯一項，重查全部）。
- 驗收：results.json 的 contaminated set 含 k1583；每個 PROTECTED_DEDUP 裁決附「dedup 時點早於污染 loss 生成」的 git-commit 證據。

### B2（py:757）：「2 個顯著性翻轉」過度宣稱
- 事實：k1592 raw p 0.038→0.137、t 2.075→1.487，但正式 interpretation 兩邊都 `equal_accuracy_not_rejected`（k1592.py:303）、Harvey+Holm gate 未翻轉（:353，Holm p=0.841）。只有 k1319 是正式 Harvey verdict 翻轉。
- 修法：改為「1 個正式 verdict 翻轉（k1319 DM |t| 2.9319→3.1085 跨 Harvey 3.0）＋ 1 個未調整 nominal p 跨線但正式判定不變（k1592）」。results.json 與 README 都要區分「nominal p 跨線」與「formal gate 翻轉」，不可並列。
- 驗收：無「2 個顯著性翻轉」字眼；k1592 標為 formal 不變。

### B3（py:742）：「70 個 py 檔」硬編碼、無實際 repo scan、無候選全集
- 修法：實際執行 repo scan 產生 consumer 候選全集（保存完整清單 + 每檔納入/排除理由）；51 條 CONSUMERS 之外的排除檔要逐檔 evidence（grep 到的 import/讀取路徑），不可概括「明顯無關」。
- 驗收：results.json/artifact 存候選全集 + 排除清單 + 逐檔理由；掃描可由第三方重跑重建。

### B4（results.json:4）：generated_from_revision 指不到生成 bytes
- 事實：revision 77c6eef 中 audit entrypoint 與 rerun cache 都不存在，整套 audit 是 `1c30466ae` 才加。
- 修法：把 provenance 欄改指向實際生成本結果的 commit（1c30466ae 或之後），不可列為「可忽略差異」。
- 驗收：generated_from_revision 指向的 commit 內 audit entrypoint 存在且能對上結果。

### B5（reproduce_spec.json:3）：reproduce spec 與 rerun_cache 不完整、無法第三方重現
- 修法：spec 補齊 hash —— audit entrypoint、7 支 rerun consumer 程式、`src/volpred` 統計 helper、額外輸入（如 k1705 讀 parent results、paper2 讀 1997–2007 snapshot）、Python/套件版本。rerun_cache 保存完整 polluted/clean outputs、執行命令、stdout/stderr、各輸入 hash（非只 top-30 diff 摘要）。
- 驗收：第三方能從凍結 artifacts 重現 7 組 before/after 數字。
- 順帶修 NOTE：results.json:513 k1705 evidence「143 fields」與 cache/README 的 141/255 不一致 → 由 cache 程式化生成 evidence 文字，消除手抄。

## 收尾（agent 內做到可交付；merge/knowledge 由收件 fire 決定）
1. 重跑 audit 產生修正後 `audit_snapshot_dup_20260721_results.json`（固定 seed；保留 B1–B5 的新 provenance/scan artifacts）為 result-artifact。
2. README 補 `## Remediation 修訂紀錄`：逐條 B1–B5 說明改法 + 驗收證據路徑；更新「確認污染數」新下限。
3. 更新 `review_verdict.json`（reviewed_sha256 用 `shasum -a 256` 實算、禁手抄；verdict 先留 `PENDING_RECERT`）。
4. **不要自己 merge、不要寫 knowledge.json、不要手改 verdict 成 PASS**。
