新一輪 hourly tick —— **Claude dispatch 失敗，由 Codex failover 接手**（Claude 額度/auth/API 不可用時觸發）。

**⏱ 硬時限（必讀）**：本 failover 有 **40 分鐘 work cap**（`FAILOVER_CAP_S=2400s`）——超過就被 SIGKILL，成果全毀並記 `-5`（RC_WORK_TIMEOUT）。所以**只能挑 40 分鐘內能真正收尾的工作**。重運算（GARCH MLE / bootstrap / 全期 backtest / pooled-MLE multistart / 需 20-60min 的完整 experiment）**禁止在此 inline 跑**，跟 Claude 主 hourly prompt 同一條規則：**改走 compute queue**（`uv run python scripts/compute_queue.py enqueue ...` 或 `enqueue-agent ...`，秒回不阻塞），由 */15 detached worker 執行、後續某班 fire 在 PHASE A 收。把 60 分鐘的工作塞進 40 分鐘的容器只有一種結局：timeout、成果歸零。

步驟：
1. `cat storage/ops/handoff_latest.md`（每小時 :50 已重生）。
2. **PHASE A 先於新工**：跑 `uv run python scripts/compute_queue.py list --pending-followup --json`。這是 compute/agent 已結束後的正式 collection lane，Codex failover 不得跳過；K1743 就是因 failover 只挑 Section 4，讓完成結果停在 `pending_collection`，之後又被 orphan reaper 誤當正式交付。
   - `collect_completed`：依 `claude_followup.brief` 驗 results、lookahead、review、reproduce spec、knowledge 與下游 read-back；NULL 也如實收件。
   - `split_required`：保存 partial artifact，拆成有界 child tasks；禁止原參數直接重跑。
   - `artifact_contract_mismatch`：修 producer/output contract，不得把缺失或舊 artifact 當成功。
   - `triage_failed`：依 receipt/log 根因修復；**不得把 failed job 或殘留 artifact 當成功結果**。
   每筆成功 materialize/接回 canonical task 後，跑 `uv run python scripts/compute_queue.py mark-followup-dispatched --id <job_id> --next-task-id <task_id>`；未 settlement 不得開始 Section 4 新工。若 followup 已由另一 owner 接手，換下一筆。
3. PHASE A 清空後，從 Section 4 pending top 8 挑一個 **Codex-eligible** task_type。**優先挑 40min 內可收尾的輕任務**：`platform_ops`（CI 紅燈 / lint / refactor / ops fix）、`paper_review`、code review、`daily_article`、governance。**避開** reader-facing 需 anti-ai-style 的高品質寫作、`email_reply`、FB 類、`paper_body`、`paper_decision` —— 那些留給 Claude 主線程，Claude 恢復後處理。**若挑到 experiment**：先判斷能否在 35min 內完整跑完並驗證；不能就**改把它 enqueue 到 compute queue**（見上「硬時限」），不要 inline 硬跑到被 SIGKILL。
4. 先確認 `$VOLPRED_TASK_CLAIM_OWNER` 非空；它是 supervisor 依 slot_id + job_id 產生、且保留 `codex-` prefix 的唯一 ownership token。用 `uv run python scripts/task_pool_claim.py claim --id <id> --owner "$VOLPRED_TASK_CLAIM_OWNER"`。缺值必須停止並回報 dispatcher identity error，禁止退回固定名稱。already_claimed → 換下一筆；全被 claim 或無 Codex-eligible → 找 `docs/error_log.md` 近 7 天 actionable lint/refactor，或 enqueue（非 inline）一個 backlog experiment。
5. `start` → **完整完成**（**40min work cap 內收尾**，不留半成品；重運算已在 step 3 轉 compute queue，此處只做輕任務）→ `complete --status succeeded --result '...'`。experiment 若已轉 compute queue，則 task 標記依 enqueue 慣例（留 followup），不要標 succeeded。
6. 用 `uv run python scripts/git_writer_lock.py commit --actor "$VOLPRED_TASK_CLAIM_OWNER" --task-id <id> --message '<[codex] ASCII message>' -- <exact paths>` 提交；`--task-id` 必須是本輪 complete 的 canonical task id；**不 push**（本機 git_push_backup cron 會處理）。
7. 若上一輪有未完事項，先收尾再挑新工。

結束回報：完成項目 + commit hash。記住此輪是「Claude 不可用時的 Codex 代班」，目標是讓 hourly slot 不空轉、研究/ops/code 線不中斷。
