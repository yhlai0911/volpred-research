# Paper 9 (garch-x-vix) — v8 Plan

**Date**: 2026-06-08
**Author**: hourly-20 dispatch
**Stage**: submitted under review / amber / body frozen
**Source**: codex v7 review (2026-06-05) + decision memo (2026-06-06)

## 一句話結論

**v8 不是 body rewrite，是 R1-prep packet hardening**。Body frozen 直到 reviewer 回覆；本輪只處理 replication metadata、shelf errata、R1 response wording queue。

## v7 verdict 計數

| Severity   | Count | Findings                                                                 |
|------------|-------|--------------------------------------------------------------------------|
| **HIGH**     | 1     | (1) Replication metadata (README/reproduce_report) stale，與 body 不一致 |
| **MED-HIGH** | 2     | (2) "Statistically non-inferior" terminology too strong<br>(3) `g_t` 與 `g`-proxy 概念混淆 (abstract/intro/conclusion vs §6) |
| **MED**      | 1     | (4) Conclusion 跨資產推論未對齊 Bonferroni caveat                       |
| **MIN**      | 0     | (無)                                                                     |
| **TOTAL**    | **4** | 全部屬於 claim discipline / packet consistency，無 fresh empirical invalidation |

## v8 工作項（do-now, packet-cleanup queue only）

### A1. Replication metadata sync (high)

- **檔案**：`paper/garch-x-vix/README.md`, `paper/garch-x-vix/reproduce_report.json`
- **動作**：
  - README headline `DM t=4.03 ... outperforming all GARCH-MIDAS variants` → 改成「paper-frozen point estimate；B1 變體在統計上 indistinguishable」
  - README cross-asset GLD source 從 K1085 改成 K997（paper-period `t=3.17`）
  - reproduce_report.json 區分三層：`paper_frozen` / `pinned_snapshot` / `live_rerun`，並標註 `4.03 vs 4.148384` 為 controlled shelf erratum（非 mismatch）
- **預估 effort**：30 min（純 metadata edit + JSON schema 加 layer field + reproduce.py 跑 verify）
- **驗證**：`reproduce_report.json` `match_rate ≥ 95%` 不退；alert_level 從 amber 維持或上修到 green
- **Gate**：仍走 `.claude/rules/paper-workflow.md` 四大硬規則第 2 條（reproduce gate 是 review 先決條件）

### A2. R1 wording patch queue (med-high × 2 + med × 1)

寫到 `paper/garch-x-vix/r1_response_queue.md`，**不**直接改 main.tex。內容：

| Patch | 原句（line ref）| 改成 | Why |
|-------|----------------|------|-----|
| P1 | `statistically non-inferior` (main.tex:806, 813) | `not statistically distinguishable under these comparisons` | DM 非拒絕 ≠ non-inferiority margin |
| P2 | `g_t tracks VRP at rho≈0.80` (main.tex:52, 82, 893, 909) | `g-proxy (derived from multiplicative decomposition) tracks VRP at rho≈0.80; latent g_t itself is approximately orthogonal to VRP (rho≈0.06)` | §6 已揭露 — 全文需 explicit 區分 |
| P3 | `five of seven tested markets ... global fear factor` (main.tex:911) | `five of seven under baseline Harvey screen; four of seven under conservative Bonferroni adjustment (GLD t=3.17 marginally below |t|>3.22)` | 對齊 v6 已加的 Bonferroni caveat |

- **觸發條件**：R1 reviewer response 到達後 → 把 queue 應用到 main.tex → editor cover letter 直接 cite 此 queue 作為「我們已主動識別並準備修正」
- **預估 effort**：20 min 寫 queue + reviewer-response 草稿 1 段；R1 真到時 30 min apply 到 main.tex
- **不做**：本輪 **不** 改 main.tex（per 2026-06-06 decision memo `Disallowed work before R1: unsolicited body rewrite`）

### A3. Errata pending 文件 consolidation (med)

- **檔案**：`paper/garch-x-vix/errata_pending.md` (已存在，最後動 2026-06-05)
- **動作**：
  - 把 v7 4 個 findings 全部 append 為 `Section: v7 reviewer-anticipated issues`
  - 每條對齊到 A1/A2 對應 patch 編號
  - 強調 Harvey qualitative conclusion invariant，pinned snapshot 在
- **預估 effort**：15 min

## v8 預估總 effort

- A1 + A2 queue + A3：~65 min
- 不含 main.tex 改動（pre-R1）
- 不含 reproduce.py 重跑（只 schema 加 layer，非重算）

## Promotion path

**本輪不 promote**。維持 `submitted under review / amber`。

**Promotion 觸發**（三選一）：
1. R1 reviewer response 到達 → 套 A2 wording queue → 重投 → `revision_submitted`
2. 用戶明確 push「先變 R1 revision 不等 reviewer」→ 套 wording queue + body rewrite → `revision_ready`
3. 新 empirical contradiction 推翻 qualitative conclusion → 走 retraction / 重新研究 → 退回 `draft`

否則維持 amber 直到 reviewer 接觸。

## 不做的事（明確列出避免 drift）

- ❌ 不改 main.tex（pre-R1 unsolicited body rewrite）
- ❌ 不重跑 OOS 數字（drift 已知 + qualitatively invariant + snapshot pinned）
- ❌ 不改 paper status / narrative_state
- ❌ 不寄 retraction / withdrawal
- ❌ 不 promote 到 ready_for_submission（已 submitted，不適用此 state machine）

## 下一輪 review 觸發

- **時機**：R1 reviewer response 到達當天，或 30 天無回覆時主動 ping editor 後
- **Reviewer**：Codex adversarial mode（v8）+ latex-academic-reviewer skill
- **入口**：建立 `task_type=paper_review`, `id=paper_review_garch_x_vix_r1_response`

## 一句話 follow-up

V8 = R1-prep packet hardening（metadata sync + wording queue + errata consolidation），**不動 main.tex**，總 effort ~65 min；等 R1 reviewer response 觸發 body apply。
