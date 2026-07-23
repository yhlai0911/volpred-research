# K528 round-5 remediation — NFP event study 四條 blocking defect

**Model**: opus / xhigh (per model_router)
**Task id**: `k528_round5_remediation`（VolPred task pool，已 claim）
**Worktree cwd**: `.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp`（branch `k528-nfp-official-dates`）

## 開工前必讀

1. 完整任務規格：`storage/next_tasks.json` 裡 id=`k528_round5_remediation` 的 `description`（含 B1–B4 逐條證據行號與最小修法）
2. Codex 裁決全文：`storage/ops/codex_reviews/k528_round5_verdict.md`
3. `experiments/k528/README.md` + `k528_nfp_event_study.py`

## 四條 blocker（逐條修，逐條留可重現證據）

- **B1 — Friday estimand 錯置**：程式用**映射後的交易 session weekday** 篩 237 筆，不是官方**發布日** weekday（253 個有效發布日中 243 個在週五；6 個 Good Friday 被映射到下週一而排除）。→ 同時保存 `release_date` 與 `session_date`；若沿用現分析，全文改稱 **Friday trading-session estimand** 並揭露那 6 個 Good Friday 案例。若要真的回答「發布日在週五」，須改用 release weekday 篩 243 筆 + 重設計 weekday-matched controls + 重跑。**先做裁決並寫下理由，再執行。**
- **B2 — raw 與 selected 同步截短仍通過**：70 天容忍容得下整個首/尾月消失。→ 對這個固定歷史樣本**釘住預期首尾月份或預期發布數**（或用獨立 release-schedule 判斷應已發布月份），並**新增同時刪 raw+selected 首/尾月的對抗測試**（測試必須真的能 fail）。
- **B3 — 價格資料尾端截短不 fail closed**：`yf.download` 後無 SPY/^VIX 覆蓋或 freshness gate；VIX `ffill()` 會沿用陳舊值。→ 要求覆蓋至預期端點、`n_outside_price_sample == 0`、限制 VIX forward-fill 最大資料年齡。
- **B4 — 未定義多重比較 family 卻宣稱 5% 顯著**：週五 p=0.0209 目前只能稱 **nominal significance**。→ 指定 rerun 前既有的 confirmatory endpoints、報 Holm／Romano-Wolf 調整值、其餘明標 exploratory。（README 六個主要檢定 → Holm ≈ 0.0417 結論可保留；全部 22 個 inferential outputs → Holm ≈ 0.375。）**family 未定義前不得無限定地寫「顯著」。**

殘留 gap `single-month upstream truncation` 的裁決 = **blocking**，必須真的關掉，不能只揭露。

## 硬性禁令

- ❌ 禁止 merge worktree、禁止 certify（round 5 未 PASS 前）
- ❌ 禁止寫 `knowledge.json`
- ❌ 不得推翻既有 archived 數字去湊結論；若修完數字變了，照實記錄變化
- ❌ 禁止 force push / `--no-verify` / 假數字

## Heavy compute 走 queue

若 B1 裁決導向「改用 release weekday 重跑」，該重跑屬 heavy compute → 腳本寫完並自審後用
`uv run python scripts/compute_queue.py enqueue --script <path> --result-artifact <path> --output-path <file> --followup-brief '...' --followup-task-type experiment`，**不要**在本 job 內硬跑到超時。

## 交付物（**必須存在**）

`experiments/k528/k528_round5_remediation.json`：

```json
{
  "task_id": "k528_round5_remediation",
  "blockers": {
    "B1": {"decision": "session-estimand | release-weekday-rerun", "rationale": "...", "changes": ["..."], "good_friday_cases": 6},
    "B2": {"fix": "...", "adversarial_test": "path::test_name", "test_fails_when_month_deleted": true},
    "B3": {"fix": "...", "gates_added": ["..."]},
    "B4": {"confirmatory_endpoints": ["..."], "holm_adjusted": {"friday": 0.0}, "exploratory": ["..."]}
  },
  "readme_claims_updated": ["..."],
  "tests": {"added": ["..."], "all_pass": true},
  "commits": ["<sha>"],
  "residual_limitations": ["..."]
}
```

## 送審

修完跑 `codex exec` 做 round-6 獨立審查，裁決存 `storage/ops/codex_reviews/k528_round6_verdict.md`，摘要寫進交付 JSON。
