# Next Draft Candidate: K957 Session Synthesis (E019-E023 Meta-Lessons)

**Prepared 2026-04-19** as preemptive brief for next `draft_pool_low` remediation. Use when Claude agent is dispatched to补 pool from uncovered K candidates.

## K957 Overview

**Score**: 6 (★★★★)
**Title**: K957: K526-K566 Session Synthesis — 37 Experiments, 5 Meta-Lessons (E019-E023)
**Coverage**: uncovered any audience

## Why this topic works

- **Meta-synthesis level** 適合 research audience：把 37 個 experiments 的結論蒸餾為 5 條 learning lessons
- **硬核發現** 對 paper 寫作有直接價值：
  - 2 個 Harvey-pass 策略（K548/K551 leverage t=7.90、K553/K558 台灣 t=4.79）
  - 7/7 HAR universal breakthrough
  - 37+ VIX sufficiency 確認
  - 3 個 daily-artifact 案例
- 5 experience records **E019-E023** 直接可當五個 section 骨架

## Article Skeleton Proposal

1. **Intro**: 什麼是 session synthesis + 為何 K526-K566 段值得蒸餾
2. **E019 Daily Artifact**: daily-scale 3 案例
3. **E020 Harvey-pass strategies**: K548/K551 leverage + K553/K558 台灣
4. **E021 HAR universal breakthrough**: 7/7 asset
5. **E022 VIX sufficiency 37+ confirmations**
6. **E023 [從 JSON 補細節]**
7. **Summary + Cross-link to K672** (evidence hierarchy)

## Charts needed (2 real)

1. Experiments timeline K526-K566 + verdict distribution（37 exp + 4 missing K-IDs 標）
2. Meta-lesson triangle / Sankey 連接 experiments → E019-E023

## Data sources

- `experiments/k957/k957_results.json` — main JSON
- `storage/memory/experiment_experiences.json` — E019-E023 entries
- `experiments/k548/` ~ `experiments/k566/` — 37 supporting experiments
- `storage/memory/knowledge.json` — HAR universal + VIX sufficiency 相關 entries

## Dispatch when

- Pool drops below 4 (`draft_pool_low` breach)
- **AND** Codex quota not yet needed for this topic（Claude agent 足夠）
- **OR** 用戶 explicitly requests K957 topic

## Hard rules (agent briefing template)

- proposer="Claude" / audience="research" / category="milestone" / status="draft"
- 2000+ chars (CJK 繁中)
- 2 real matplotlib charts (no ASCII)
- Differentiate from `mile_c15c7b98` (K672 evidence hierarchy) — K957 focuses on **methodology lessons from experiments process**, K672 focuses on **cumulative findings from 1421 entries**
- Cross-link both in 'Related articles' footer
