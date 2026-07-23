# K1731 arm B rev8 — 獨立 gate 驗證（主線程，非採信 JSON 自述）

- **驗證者**：hourly-slot-1-0a4f97f4eafa4ee8a65686a0f0adbfde
- **時間**：2026-07-21 04:10–04:20 CST
- **對象**：`.claude/worktrees/dispatch-slot-1-bd00f90a-k1731`（compute job `agent-brief_k1731_rev8-52736d`，exit=0）
- **方法**：主線程親自執行三個 gate，不讀 `k1731_armB_rev8_remediation.json` 的自述結論作為證據。

## 1. 三個 gate 的實際輸出

| Gate | 執行指令 | 實測結果 | JSON 自述 | 一致 |
|---|---|---|---|---|
| nested-DM ratchet | `pytest scripts/tests/test_nested_dm_misuse_ratchet.py` | **108 passed** (81.98s)，exit 0 | PASS 108/108 | ✅ |
| arm B verification | `python experiments/k1731/k1731_armB_verification.py` | `problems = 0`，107 個 check 行，README claim scan **0 violation**，exit **0** | PASS 107/107 checks | ✅ |
| regression（leaf drift） | `k1731_regression_check.py --baseline regression_baseline/..._corrected.json --candidate ..._corrected_rev5.json` | compared 3826 / accounted **3834** / by_design 63 / nondeterministic 19 / renamed_value_preserved 8 / **UNEXPECTED 0**，exit 0 | 3834 leaves、0 out-of-allowlist | ✅ |

**numeric leaf drift = 0** 已確認（`n_unexpected: 0`，且 8 個 rename 是「跟隨改名並要求新舊 leaf 同值」而非整列 allow-list）。

## 2. Negative control — gate 真的會失敗嗎

rev8 的 fallback 審查抓到的最致命問題是「`k1731_armB_verification.py` 永遠 exit 0，round-8 新增的 invariant 其實一條都沒被 gate 住」。這條修好沒有，不能靠 JSON 自述判斷，必須看它失敗。

實測：把 `The macro null rests on the PIP evidence plus the DM diagnostic.` 注入 `experiments/k1731/README.md` 末尾 →

```
NEGCTRL_EXIT=1
README claim scan: 1 violation(s)
```

移除後 README 與備份 byte-identical，重跑 exit 0。**gate 可失敗性成立**，且 concept-level scan（非固定字串 grep）確實抓得到未見過的改寫。

## 3. 為什麼這輪仍然不能結案

`upstream_verdict = FAIL`。原因不在 gate，在審查路徑：

- **Codex round-8 未完成**：CLI 回 `You've hit your usage limit`，quota 重置時間 **2026-07-25 13:30**。`storage/ops/codex_reviews/k1731_armB_rev8_verdict.md` 是空 verdict，**不存在對 round-8b bytes 的 Codex 判決**。
- **Fallback 不能替代**：`.claude/rules/experiments.md:36` —「Subagent fallback PASS ≠ primary-path Codex PASS」（K1259 教訓：subagent 標 provenance-clean，Codex 隔天在同份 code 找到 12 個 residual rows）。何況這次 fallback 本身回的是 **FAIL**（五個 blocking issue，已全數修掉並從 rev7 bytes 重跑 gate）。

因此：**gate 層 PASS，claim 層待 Codex**。不合併 worktree、不寫 knowledge.json、不排文章。

## 4. 處置

`assign_67f56b79` → `status=blocked`、`blocked_reason=codex_quota_reset_pending`、`blocked_until=2026-07-25T13:30:00+08:00`。quota 一恢復，PRE-PHASE-0 的 `unblock_expired_blocked_tasks.py` 會自動 flip 回 pending，接手者只需對 **round-8b frozen bytes**（`storage/ops/codex_reviews/k1731_armB_rev8_freeze.txt`）跑 Codex round 8，prompt 已備妥於 `storage/ops/codex_reviews/k1731_armB_rev8_prompt.md`。

## 5. 本次驗證未涵蓋

- 未重跑 GEV-HAR 估計本身（rev5 artifact 視為 frozen input；regression gate 的職責就是確認它沒動）。
- 未複驗 rev8 對 README 論述的**內容**是否正確，只驗了 scan 抓得到既知違規型態 —— 那是 Codex round 8 要判的事。
