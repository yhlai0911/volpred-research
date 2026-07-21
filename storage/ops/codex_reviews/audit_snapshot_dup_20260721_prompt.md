# Codex 審查 — audit_snapshot_dup_20260721（snapshot 重複列污染稽核）

你是 READ-ONLY 審查者。**不要修改任何檔案**，只輸出審查報告。

## 待審物件（凍結 bytes）

Worktree（不是 canonical repo）：
`/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-1-20b291d5-snapdup`

claim surface：
- `experiments/audit_snapshot_dup_20260721/audit_snapshot_dup_20260721.py`（799 行，稽核腳本本體）
- `experiments/audit_snapshot_dup_20260721/README.md`
- `experiments/audit_snapshot_dup_20260721/audit_snapshot_dup_20260721_results.json`
- `experiments/audit_snapshot_dup_20260721/reproduce_spec.json`
- `experiments/audit_snapshot_dup_20260721/rerun_cache.json`

## 背景

`scripts/refresh_paper_snapshots.py` 的並行 double-append 造成 6 篇 paper 共 9 個 live snapshot CSV 在
2026-05-04..05-15 被重複 append 10 個交易日（byte-identical）。污染窗 2026-05-15 ~ 2026-07-17。
本稽核要回答：**哪些 consumer 真的吃進了這 10 列重複，影響多大**。

稽核自述結論：篩 70 個 py 檔、裁決 51 個 consumer、9 個確認污染、4 個 at-risk 無法釘死、
重跑 7 個且 7 個全部有數字變動、其中 2 個**顯著性判定翻轉**：
- k1319：DM har_vs_ewma |t| 2.9319 → 3.1085（跨過 Harvey |t|>3.0）
- k1592：dm_GammaRule_minus_GJR_p 0.038 → 0.137（跨過 5%）

## 審查重點（依重要性排序）

1. **證據 vs 推測**：`consumers[]` 每一條的 `evidence` 欄是否真的落在可查證的行號 / 存檔計數 /
   重跑差異上？有沒有哪一條的裁決其實是「看起來應該沒事」式推測？特別檢查
   `PROTECTED_DEDUP`(18) / `PROTECTED_DATE_WINDOW`(11) / `NOT_A_CONSUMER`(8) 這 37 個「無罪」裁決 ——
   放過一個真污染者比誤報一個更貴。逐條去原始碼確認 dedup 呼叫真的在讀檔之後、
   date window 真的結束在 2026-05-04 之前。

2. **k1592 的 diff-before-dedup 論證**：稽核宣稱 `k1592.py:80` 先 `.diff()` 再於 `:82`
   `drop_duplicates(keep='last')`，導致 10 個 dup 日期以**捏造的 0.0 報酬**存活、且列數不變所以
   count audit 抓不到。請直接讀 k1592.py 驗證這條因果鏈是否成立 —— 這是整份稽核最強也最容易錯的一條。

3. **重跑的可比性**：`reran[]` 的 before/after 是否真的只有「資料去重」一個變因？
   有沒有混入不同 random seed、不同 yfinance 抓取時點、不同套件版本？
   `rerun_cache.json` 是否足以讓第三方重現這些 before/after？

4. **未解事項是否誠實**：`unresolved[]` 列了 5 條（k1497/k1498/k1585/k1380 未重跑、k1308 缺檔、
   k1391/k1591 已證污染但未重跑、run-time attribution 用 git commit date 當 proxy）。
   這些坦承是否覆蓋了實際的知識缺口，還是有更大的缺口沒講？

5. **`generated_from_revision` 與 `reproduce_spec.json`**：spec 是否 hash 了所有輸入？
   稽核聲稱的「乾淨版計數」是怎麼算出來的，可驗證嗎？

## 輸出格式

先寫一段 3-5 句的整體判斷，然後：

```
VERDICT: PASS | CONDITIONAL_PASS | FAIL
```

若非 PASS，逐條列 blocking defect：`[BLOCKING] <檔:行> <問題> <為什麼這會讓結論站不住>`。
非阻斷但值得記的用 `[NOTE]`。

判準：這份稽核的結論會被拿去建立 P1 修正任務、並可能撤回已發表的數字。
**PASS 的意思是「這些數字與裁決可以直接拿去行動」**，不是「大致合理」。
