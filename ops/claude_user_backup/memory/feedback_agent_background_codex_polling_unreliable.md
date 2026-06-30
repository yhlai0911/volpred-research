---
name: agent background Codex + polling loop pattern unreliable
description: paper_review / multi-reviewer agents 用 "spawn Codex background + polling loop" pattern 常失敗，應改 foreground 同步執行
type: feedback
originSessionId: be30a269-dcc9-40ba-933b-815ea459b710
---
派 agent 跑 paper_review / multi-reviewer 任務時，agent 若採「spawn 兩個 Codex background reviewer + 設 polling loop 等檔出現 + 自己 exit」pattern，很容易留下孤兒 process 且實際 reviewer 沒跑（`ps` 無 `codex exec`）。

**Why**: 2026-05-12 hourly dispatch 派的 leverage-direction v3 review agent (id `a0c2291b96a5deb91`) 就是這 pattern。Agent 回報 "Both jobs still running" 後 exit，但 `paper/leverage-direction/review_history/v3/` 空，PID 26141 polling loop 變孤兒永遠等不到的檔，需手動 `pkill -f "academic_review_report.md.*ready"` 清除。Sub-agent 的 codex background spawn 並沒有可靠的 lifecycle 保證。

**How to apply**:
- 派 paper_review / latex-academic-reviewer / citation-verifier 類任務時，prompt 明確要求 agent **foreground 同步執行 reviewer**（不 spawn background）— 即使是同時跑兩個 reviewer，也要 wait both → write reports → exit。
- 若 agent 一定要 background，prompt 必要求 agent 在 exit 前 verify spawned process 真在 ps 裡 + 用 `wait` 或 monitor loop 確認完成，不可只設 file-existence polling。
- 主線程派 dispatch 前用 `ls paper/<id>/review_history/v(n)/` 看出檔，沒檔就確認 agent 是真完成還是 abandon。Agent 回 "still running" 等於 abandon。
- 看到 abandon 立即 pkill 孤兒 + 寫 error_log + 直接 foreground re-do 或 dispatch 新 agent（不要等 polling loop 自然死）。
