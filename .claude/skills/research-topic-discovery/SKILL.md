---
name: research-topic-discovery
description: >
  Discover and rank new VolPred research directions from current primary
  academic literature. Use when the research backlog needs new, non-duplicate
  experimentable questions.
---

# Research Topic Discovery

本 skill 產生有來源、可跑、可區分的研究 proposals；不直接執行實驗，也不自己取得
排程或 task-pool ownership。

## Preflight

先讀：

- `.claude/skills/autonomous-research/references/operations-core-contract.md`
- `storage/ops/task_pool_mode.json`（透過下列 status command 每次重新 read-back）
- `scripts/agent_prompts/journal_topic_scan.md`

```bash
uv run python scripts/task_pool_control.py status
```

同一 session 的早期 mode 不可重用。

## 1. 決定 discovery scope

先從 `research_program.md`、近期 verified/null experiments 與 knowledge index整理：

- 現有 research arcs
- 已反覆 null 的方法
- 尚未解決的大問題
- 市場、資料與方法的 coverage gaps

用 bounded search，不整檔載入大型 memory。建立 semantic dedup baseline；同一機制只換
ticker或包裝，不算新方向。

## 2. 搜尋 primary literature

至少覆蓋與問題相關的三類來源：

- Finance / asset pricing / market microstructure
- Forecasting / econometrics / statistics
- Applied or market-specific literature

每個候選保留可核實的 title、authors、year、journal/repository與 DOI/official URL。
搜尋摘要只能做 discovery；最終方法 claim回到 paper或official abstract。不能捏造 citation。

## 3. 轉成 VolPred proposal

每個方向必須有：

| Field | Requirement |
|---|---|
| `academic_finding` | 文獻真正研究了什麼 |
| `volpred_question` | 可推翻的 forecasting/risk/strategy 問題 |
| `differentiation` | 與現有 K/arcs 的實質差異 |
| `data_contract` | 免費/可取得 source、period、availability、proxy bias |
| `method` | baseline、target、OOS、formal test |
| `failure_value` | null/failed 仍能學到什麼 |
| `sources` | 至少三個 primary references |

一個 batch 目標 8–12 個 proposals，至少兩個非美股市場方向；市場多樣性不能犧牲資料
可用性或方法正當性。

## 4. Rank and verify

依下列維度排序：

- novelty relative to current K
- decision/research value
- data availability與timing safety
- identification/inference quality
- bounded runtime與artifact feasibility

Top proposals再次查 knowledge/experiments/task identities，移除重複或已在執行者。

## 5. Handoff and task mode

輸出先交給主線程 review。只有主線程接受後才：

- 更新 `research_program.md` 的 discovery batch
- queued execution：經 canonical research producer/refill writer materialize tasks
- direct execution：保留 proposal或在已授權時建立 GitHub Issue；不新增 legacy task id
- restore/unreadable：fail closed

每次 materialize 前都重新讀 `storage/ops/task_pool_mode.json`；不是 batch 開頭讀一次後
整批沿用。

## Schedule read-back

若這次是在診斷「為何 discovery 沒自然執行」：

1. 從 `config/runtime_schedules.json` 查目前承接 research backlog/discovery 的 job。
2. 從 `.schedule_materialization.receipt_path` 回讀 Operations Core terminal receipt。
3. 回讀最新 accepted discovery batch或 task receipt。

本 skill 不保存 cadence，也不建立另一個clock。

## Completion

- [ ] 8–12 個可推翻 proposals
- [ ] 每個至少三個primary sources且可核實
- [ ] 與既有K/arcs/task做semantic dedup
- [ ] data availability、timing與proxy bias明確
- [ ] 至少兩個非美股方向
- [ ] ranking與排除理由可重建
- [ ] 主線程acceptance有read-back
- [ ] Task materialization符合當次mode並有canonical receipt
