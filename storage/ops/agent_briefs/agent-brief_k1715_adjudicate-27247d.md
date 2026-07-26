# K1715 split child stage: codex-adjudicate （ONLY 最終裁決，禁止重跑實驗）

**Model**: claude-opus-4-8 / max (per model_router)
**Parent timed-out job**: agent-brief_k1715_fix_attempt1-ba80b2 (budget 2880s，於 Codex re-review 途中被 wall-clock kill)
**Split stage**: codex-adjudicate
**Worktree (cwd)**: .claude/worktrees/k1715-204d556b

## 背景（已核實，勿重做）

K1715 實驗**已完整跑完且產物有效**（`artifact_ok=True`）：
- `experiments/K1715/K1715_results.json`（450KB，完整 per_model / head_to_head / backtests）
- `experiments/K1715/K1715.py`、`README.md`、3 張圖、`build_readme.py`
- 結果 = **defensible NULL**：score-driven（GAS-t / GAS-t-lev）與 GARCH-family（GARCH-t / GJR-t）在 joint VaR+ES 上統計打平（Harvey |t|>3 準則下 sig better 0/3、worse 0/3、tied 3/3；四族在遠左尾同樣 under-coverage）。

**前一個 job 唯一沒做完的事**：Codex 獨立 re-review 跑到一半（`codex_rereview.md` 有 4446 行分析），wall-clock timeout 在 21:33 把它 kill，**沒有輸出最終結構化裁決**，導致 `review_verdict.json` 仍是未填的 `FILL:` 模板。

Codex 被 kill 前正在查的關鍵疑點（你必須回答它）：**GJR-t multistart 收斂品質** — 38% 的 GJR-t refit 起點落在非最佳 basin（`(3,1)`/`(3,2)` 佔多數，vs GAS/GARCH 幾乎全 `(3,3)`）；README §188 已誠實記載 min-NLL 選擇丟棄這些 straggler、`param_dispersion_near_best`≈0。判斷這是否構成 blocking defect，還是「誠實揭露、min-NLL 選擇下不影響結論」。

## 你的唯一任務（bounded，禁止 scope creep）

1. **禁止重跑實驗**：`K1715_results.json` 是 frozen 事實。不要重新 fit、不要改 `K1715.py` 的計算邏輯。
2. 跑一次**收斂的** Codex 獨立裁決（`codex exec`，你在 detached worker 內、允許）。prompt 要**緊**：讀 `K1715.py`、`K1715_results.json`（summary / head_to_head / per_model 收斂欄位）、`README.md`、既有 `codex_rereview.md` 的分析，聚焦上述 GJR-t 收斂疑點 + NULL 是否 defensibly earned + reporting 誠實性。**給 Codex 明確 bar**：CONDITIONAL_PASS 以上 = mergeable；乾淨、無 leakage、誠實報告的 NULL 應為 PASS；只有真實 defect（leakage / 數字不符 / 造假或過度宣稱 / 收斂造假）才 FAIL。要求 Codex 輸出指定格式：`VERDICT: <PASS|CONDITIONAL_PASS|FAIL>` + blocking_defects 逐條。
3. 把這次裁決全文 append 到 `experiments/K1715/codex_adjudication_final.md`。
4. **填 `experiments/K1715/review_verdict.json`**（成功後置條件）：
   - `verdict` = Codex 給的 PASS / CONDITIONAL_PASS / FAIL（不可再有 `FILL:`）
   - `reviewer` = 實際 Codex model / effort
   - `reviewed_at` = ISO8601
   - `reviewed_commit` = 你讀的 frozen SHA（worktree HEAD）
   - `review_artifact` = `experiments/K1715/codex_adjudication_final.md`
   - `blocking_defects` = FAIL 時逐條，PASS/CONDITIONAL 時 `[]`
   - `reviewed_sha256` = **重新計算** 當前檔案雜湊（勿沿用舊值，要與 disk 一致）
5. worktree 內 commit（worktree agent commit 合法）：把 `codex_adjudication_final.md` + 填好的 `review_verdict.json` 一起 commit，message ASCII，例：`K1715 codex-adjudicate: fill final verdict from bounded re-review`。

## 成功標準（success criterion）

`experiments/K1715/review_verdict.json` 不再含任何 `FILL:` 字串，`verdict` ∈ {PASS, CONDITIONAL_PASS, FAIL}，`reviewed_sha256` 與 disk 檔案一致，且 worktree 已 commit。

## 防錯

- 研究誠實最高：不得為了讓它 merge 而把 FAIL 寫成 PASS。若 Codex 判 FAIL，就如實填 FAIL + blocking_defects。
- 不要碰共享狀態（feed.json / knowledge.json / Supabase）—— knowledge 由主線程寫（K1259）。
- timeout 內若 Codex 仍無法收斂到裁決，把已得結論誠實填入（標 CONDITIONAL_PASS 或 FAIL 並說明未竟部分），不要留白模板。
