# Leverage-Direction (JBF) Reframing Decision — 2026-07-01

## Trigger

Codex contribution-gate (gpt-5.5 xhigh, 2026-07-01) verdict: **BORDERLINE — needs reframing**.
Multi-round latex_academic review (3 passes): all FAIL_MAJOR_REVISION (8 HIGH / 7 MEDIUM).

Reports:
- `paper/leverage-direction/review_history/codex_contribution_gate_20260701.md`
- `paper/leverage-direction/review_history/multi_round_20260701/`

## Decision: Option A (pragmatic, 階段化)

**深度 reframe 重投 JBF**，分三階段執行；不 split、不 lower-tier、不 shelve。

### 為什麼不選 B/C/D

| Option | 反對理由 |
|---|---|
| B (lower-tier FRL/IJF) | Codex 點明有 JBF-grade idea；下放等於放棄 Mission #3 top-tier target，不可逆 signal |
| C (split 2 papers) | Reframe 本來就要做；split 後兩篇都要過 contribution gate，乘以 2 工作量 |
| D (shelve, 改推 vt-trend-following) | vt-trend body_v3 才剛 PASS、還有 10 個 K-id tags 待清，雙線退場 → portfolio 全卡 |

### Option A 三階段

**Stage 1 — Quick wins（≤2 週）**

| Sub-task | 對應 Codex item | 緊急度 |
|---|---|---|
| Cover letter scrub: 拿掉 `t=-5.79`、12 DM 改 11、刪 third time-zone contribution | item 4 | P1 immediate |
| Abstract + intro + conclusion 重寫：「two contributions」→ 「one central contribution: 經濟內涵」；刪 time-zone | item 1 | P1 |
| 把 VaR/ES、VIX、HAR、crowding、behavioral 移到 `online_appendix.tex`；主文只留服務 leverage direction mechanism 的內容 | item 1 | P1 |
| Sample split unification：1 套明確 train/test boundary，data section/descriptive/OOS table/cover letter 一致 | item 4 | P1 |

Stage 1 目標：移除 desk-reject 風險點。完成後 paper 從「過載」變成「聚焦」，但核心 claim 仍 fragile。

**Stage 2 — Core rebuild（≤4 週，stage 1 done 才開始）**

| Sub-task | 對應 Codex item |
|---|---|
| Pre-specified regime design for gold：放棄 unconditional inverted leverage claim；regime 用 safe-haven / liquidation 外生定義（VIX threshold / DXY / Treasury basis），holdout period validate | item 2 |
| Genuine OOS model-selection horse race：pre-specify gamma rule on 1 universe/period → test on disjoint universe + future period；DM/MCS + 多重檢定校正；提供 forecast-origin decision log；刪「never significantly beaten」headline | item 3 |
| Replication freeze：data vintage 凍結；移除 table notes 暗示主表無法 reconstruct | item 4 |

Stage 2 目標：把「borderline 有 idea」變成「genuine JBF contribution」。

**Stage 3 — Defer（不在本 round）**

| Sub-task | 對應 Codex item | 理由 |
|---|---|---|
| VT channel identification independent of GJR | item 5 | partly mechanical 是 valid critique；但獨立 identification 需新方法（exogenous leverage proxies），規模等同新 paper；先 caveat 改寫不 over-claim，獨立 identification 留下一篇 |

## ETA

- Stage 1：~10-14 天（mostly editorial + restructuring，無新實驗）
- Stage 2：~21-28 天（含 regime design 新實驗 + OOS horse race 重跑）
- Stage 3：另一篇 paper 主題（leverage direction 投出後啟動）

## 已建 sub-tasks（next_tasks.json）

Stage 1：
- `paper_leverage_direction_stage1_cover_letter_scrub` (P1, paper_body)
- `paper_leverage_direction_stage1_intro_abstract_rewrite` (P1, paper_body)
- `paper_leverage_direction_stage1_appendix_offload` (P1, paper_body)
- `paper_leverage_direction_stage1_sample_split_unify` (P1, paper_body)

Stage 2（stage 1 全 succeeded 後 unblock）：
- `paper_leverage_direction_stage2_gold_regime_design` (P2, blocked)
- `paper_leverage_direction_stage2_oos_horse_race` (P2, blocked)
- `paper_leverage_direction_stage2_replication_freeze` (P2, blocked)

## Pipeline tracker 更新

`storage/paper_pipeline_status.json`：
- stage: `revision`（保持）
- blocker: `contribution_gate_BORDERLINE` → `stage1_reframing_in_progress`
- next_review: stage 1 done 後跑 codex latex_academic + contribution gate v2

## Boss reporting

Email summary 發出 — 描述 decision rationale + 三階段 + ETA。**如老闆否決或要求改方向，停手等回信**；未否決前 stage 1 sub-task 由 hourly dispatch 推進。

## 如何 close 此 task

- Decision 文件落地 ✓
- Sub-tasks enqueued ✓
- Pipeline tracker 更新 ✓
- Boss email 寄出 ✓
- task status → succeeded

下次 review converge gate：stage 1 完成後跑 codex latex_academic + contribution gate v2。
