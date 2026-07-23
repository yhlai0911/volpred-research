# K528 — split child stage 1／2：關閉 v6 completeness-gate 繞道，並用對抗性測試證明它關上了

**Model**: claude-opus-4-8 / xhigh (per model_router)
**Parent (timed-out) job**: `agent-brief_k528_rerun_v3-6e4286`（budget 5400s，exit 1）
**Split stage**: `completeness_gate_bypass_fix`（本階段）→ 下一階段 `codex_round5_and_merge_decision`
**Worktree（唯一可寫處）**: `.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp`

## 為什麼有這張單（先讀，別急著動手）

父 job 在 08:00 起跑後即刻 `Execution error`，之後由別的行為者接手把第三輪 review 推到 **round 4（v6）**，
於 17:26 收到 **FAIL**，然後就停在那裡沒人接。你不是從零開始，你是接一個**已知失敗點很明確**的殘局。

`experiments/k528/review_verdict_v6.json`（reviewer: Codex gpt-5.6-sol / high，reviewed_commit `3098ad5b5`）
唯一的 blocking defect，逐字：

> completeness could be bypassed by putting a tail month into `KNOWN_MISSING_MONTHS` (which made the
> raw→selected check skip it) while the counter-check that would expose the false claim only scanned
> the selected span; adding the month to `REVIEWED_MULTI_ENTRY_MONTHS` as well kept it accepted

白話：**完整性閘門可以被繞過** —— 把一個尾端月份塞進 `KNOWN_MISSING_MONTHS`，raw→selected 檢查就跳過它；
而唯一能揭穿「這個月真的什麼都沒發布」這個假宣稱的反向檢查，只掃 selected span（那個月已經不在裡面了）。
再把它同時放進 `REVIEWED_MULTI_ENTRY_MONTHS` 就照樣過關。後果是**樣本可以被靜默截短而閘門全綠**。

## 第一件事：先確認它是否已經被修掉了（不要假設，也不要靠讀碼下結論）

`k528_nfp_event_study.py` 在 17:24 被改過（v6 裁決是 17:26 寫的，時序含糊），而現在 296-300 行看起來已有
「同一月份不得同時出現在兩個清單」的檢查、339 行有「`KNOWN_MISSING_MONTHS` 宣稱沒發布但 raw feed 有」的檢查。

**但讀碼看起來有擋 ≠ 真的擋得住。** 這正是本 repo 反覆踩的坑。所以：

寫一個**對抗性測試**，逐字重演 v6 描述的攻擊路徑：取一個真實有資料的尾端月份 → 同時加進
`KNOWN_MISSING_MONTHS` 與 `REVIEWED_MULTI_ENTRY_MONTHS` → 跑完整性閘門 → **必須 raise/fail**。
- 若測試在**未修改的現況**下就紅 → 繞道還在，修它。
- 若測試在現況下就綠 → 繞道已被 296-300/339 關上；**你的工作是把這個測試留下來當迴歸釘子**，
  並在 summary 裡誠實寫「defect 已於 commit X 關閉，本階段補的是缺失的迴歸證據」，不要謊稱是你修的。

**兩個方向都要再做一次反向驗證**：把你依賴的那道檢查暫時癱瘓，確認測試會變紅。一個永遠不會紅的
測試不是 gate。

## 邊界（硬規則）

- **只在上述 worktree 內寫檔**。禁碰 main checkout、禁碰 `feed.json`、禁碰 `storage/next_tasks.json`。
- **不要重跑整份 event study**（那正是父 job 逾時的原因）。本階段只碰完整性閘門與其測試；
  除非閘門修正本身改變了選樣，才需要重算，而那要在 summary 裡明講並附前後對照。
- **不要自己寫 `knowledge.json`**（K1259）。
- **不要合併 worktree、不要下裁決**。round 5 review 與 merge 決定是下一階段的事。
- 禁 `--no-verify`、禁 force push、禁假數字。

## 單一交付物

`experiments/k528/k528_completeness_gate_fix.json`，必含：

| 欄位 | 內容 |
|---|---|
| `stage` | `"completeness_gate_bypass_fix"` |
| `parent_job_id` | `"agent-brief_k528_rerun_v3-6e4286"` |
| `defect_state` | `"was_open_now_fixed"` 或 `"already_closed_before_this_stage"` |
| `adversarial_test` | 測試檔路徑 + 測試名 + 它模擬的攻擊逐字描述 |
| `test_result_before` / `test_result_after` | 修前／修後的 pass-fail |
| `mutation_check` | 癱瘓哪一道檢查、測試是否因此翻紅（證明 gate 會咬人） |
| `files_changed` | 逐檔 |
| `sample_span_changed` | true/false；true 就附前後月份數與 headline 影響 |
| `remaining_blockers` | 你自己發現但**沒有**在本階段解決的問題（誠實列，不要清空湊漂亮） |

## 成功判準

1. 對抗性測試存在、命名清楚、且經 mutation check 證明會紅；
2. 現況下該測試綠；
3. `k528_completeness_gate_fix.json` 齊全且與實際檔案狀態一致（不得有宣稱與檔案不符）；
4. worktree 內既有測試沒有因你的改動變紅。
