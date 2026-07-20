# K528 round-5 remediation — 獨立收件驗證（不是重做，是查證）

**Model**: claude-opus-4-8 / xhigh (per model_router)
**Worktree (cwd)**: `.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp`（HEAD `17f12d16c`）
**輸出**: `experiments/k528/k528_round5_collection_verdict.json`

## 你的角色

上一個 agent 宣稱修好了 Codex round-5 verdict 的四個 blocking defect，產出
`experiments/k528/k528_round5_remediation.json`。**你的工作是查證那份宣稱，不是相信它。**
（K1016 教訓：agent 曾聲稱 QLIKE 改善 +13.7%，JSON 打開是惡化。）逐條自己看檔案、自己跑測試，
證據一律寫成 `file:line` 或實際指令輸出，禁止把 remediation JSON 的敘述抄進你的 verdict 當證據。

先讀 `storage/ops/codex_reviews/k528_round5_verdict.md`（Codex 原始裁決）與
`experiments/k528/k528_round5_remediation.json`（被查證的宣稱），再開始。

## 四條查證項（全部要有 PASS/FAIL + 證據）

- **B1 — Friday estimand 措辭一致性**：agent 選了 route (i)（Friday trading-session estimand，
  六個 Good Friday 具名揭露）。全文 grep README + 生成器 + JSON 的 claim surface，
  確認**不存在兩種口徑並存**（舊的「release weekday」說法一處都不能殘留）。
  同時確認那六個 Good Friday 案例真的被具名列出，不是只在散文裡提一句。

- **B2 — 對抗測試必須示範「在未修版本會 fail」**：這是最容易造假的一條。
  一個永遠會過的測試等於沒修。做法：把受測邏輯 revert 成 pre-fix 版本（用
  `git show 73dca01d0:<path>` 取舊檔到暫存路徑，或在測試內注入舊行為），跑該測試，
  **確認它 FAIL**；再跑現行版本確認 PASS。兩次輸出都要進 verdict。
  無法示範 fail = 這條判 FAIL，不要給善意解讀。

- **B3 — 覆蓋率 / freshness gate 要有實測**：不是看 code 有寫 gate 就算，
  要有實際餵入不足覆蓋 / 過期資料時 gate 真的擋下來的輸出。特別確認沒有 fail-open
  （例外被吞掉、預設值放行）——round 5 的原始 blocker 就是三處 fail-open。

- **B4 — confirmatory family 是 rerun 前指定**：確認 family 的定義在 commit 歷史上
  **早於**該次 rerun（用 git log/blame 給時序證據，不是看註解說「pre-specified」），
  且 Holm 調整後的 p 值有完整列表（不是只報通過的那幾個）。

## 通過之後（依序，有依賴）

1. 四條全 PASS → enqueue Codex round 6 primary-path review。
2. round 6 PASS 才可重生 `review_verdict.json`（用 verdict template）——
   **必須在所有 claim-surface 檔 landed 之後**，否則 sha pin 會漂移。
3. 然後才 `experiment_gates.py certify` → 正式 `merge_worktree.sh`。
4. **禁自簽 PASS**：verdict template 的裁決欄留 `FILL:` 佔位給 Codex。
   你的 collection verdict 是「查證結果」，不是「審查通過」。

任一條 FAIL → 不 enqueue round 6，在 verdict 的 `unresolved` 寫清楚哪條、為什麼、
要補什麼才能過，並**不要**自己動手改 K528 的實驗碼（那是下一輪 remediation 的範圍，
你這輪的職責是查證邊界，混進來會讓「誰修的、誰驗的」再也分不開）。

## 輸出格式（`k528_round5_collection_verdict.json`）

```json
{
  "experiment_id": "K528",
  "artifact": "k528_round5_collection_verdict",
  "reviewed_commit": "17f12d16c",
  "verified_at": "<ISO8601+08:00>",
  "blockers": [
    {"id": "K528-R5-B1", "verdict": "PASS|FAIL",
     "evidence": ["<file:line 或指令輸出>"], "notes": "..."}
  ],
  "b2_adversarial_demonstration": {
    "pre_fix_run": "<指令 + 輸出摘要，必須是 FAIL>",
    "post_fix_run": "<指令 + 輸出摘要，必須是 PASS>"
  },
  "round6_enqueued": true,
  "round6_job_id": "<若有>",
  "unresolved": []
}
```

`merge_status` 一律維持 NOT MERGED / NOT CERTIFIED — 本輪不合併。
knowledge.json 由主線程寫，你不要碰。
