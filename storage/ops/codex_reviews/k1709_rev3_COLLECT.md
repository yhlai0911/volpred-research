# 收 K1709 rev3 裁決時看這裡（job `k1709-rev3-codex-review`）

**為什麼有這張紙**：這個 job 的 `claude_followup.brief` 寫著「把 verdict JSON block 逐字轉寫進
`review_verdict.json`」—— 那是舊的輸出契約。我在 enqueue 後才修正 prompt（改成「Codex 只出裁決與理由，
schema 由 gate 產生」，per `.claude/rules/experiments.md` §審查認證），但 job 已經 `running`，而
`compute_queue.py amend` **正確地拒絕修改正在跑的 job**。所以修正寫在這裡，不去動一份正在被履行的承諾。

## Codex 的實際輸出格式（`k1709_rev3_verdict.md`）

```
REVIEWED_COMMIT: f3f9d3034b1a5cc4c42cacae1528178e798d08d1
VERDICT: PASS | FAIL
## BLOCKING DEFECTS
## REVIEW      ← 五問的逐條裁決；Q4 ratchet 裁決、非阻斷項都在這裡（不進 JSON）
## SHA256
```

## 收件步驟

1. **裁決檔不可手寫 schema**。worktree 裡的 `experiments/k1709/review_verdict.json` 已由
   `experiment_gates.py verdict-template` 產生、5 個 claim-surface 檔的 sha256 已 pin 好。
   只從 Codex 的輸出填：`verdict` / `reviewer` / `reviewed_at` / `reviewed_commit` /
   `review_artifact` / `blocking_defects`。**其他欄位不要加**（rev2 就是栽在 brief 手寫 schema）。
2. **核 SHA**：Codex 的 `## SHA256` 必須等於 template pin 的那 5 個。不等 = 它審的不是這份 bytes，裁決作廢。
3. **特別核 Q5**（本輪新增的考題）：`render_readme.py` 的 `else:` 分支把 README「Does say」第一條寫成
   寫死散文「No robust incremental predictive evidence was found」，**少了 JSON 版有的 UNCONDITIONAL
   限定詞**，而且因為是 renderer 散文，`--relabel` 的 byte-identity 不變量掃不到它。
   → Codex 判它 blocking 就開 fix task（實驗留 worktree）；判它被 README:38 的全域聲明治好，
   仍要問「宣稱句有兩個作者、其中一個在不變量之外」是不是設計缺陷。
4. **PASS** → 從 main checkout 跑 `experiment_gates.py certify` → path-scoped 抽 `experiments/k1709/`
   進 main → 主線程寫 knowledge.json（`verdict=INCONCLUSIVE_NO_EXACT_NULL_CLAIM`；誠實記錄
   0/10 gate pass、只有 5/10 排除 1% margin；**不美化**）→ `k1709-redo` 標 succeeded。
5. **FAIL** → 每個 blocking defect 開一條 fix task；**實驗不得進 main**。FAIL 是好答案。
6. **Q4 的 ratchet 裁決** → 餵給池內既有 P2 task `nested_dm_auditor_cannot_express_fixed_window_gw`。

## 歷史（不要再走一次）

- rev2：brief 手寫 verdict schema → 欄位對不上 merge gate，30 分鐘 xhigh 審查險些認證不到任何東西。
- rev3 第一次重審：Codex 被塞進 Claude agent 當子程序，父 turn 一結束就把它殺在寫裁決前一秒
  （844KB transcript、20 分鐘、零產出）。現在改由 `codex_review_job.sh` 讓 Codex 自己就是 job。
