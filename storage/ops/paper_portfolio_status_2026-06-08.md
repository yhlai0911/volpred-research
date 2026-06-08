# Paper Portfolio Status — 2026-06-08 18:11 台灣時間

**Triggered by**: hourly dispatch 18:07 fire — pool 100% experiment fallback, paper_review/paper_body pool empty。本 audit 補齊論文 pipeline visibility 並 seed concrete next tasks。

## 12-paper portfolio overview

| # | Paper | Latest body | Last review | Stage | Last commit (本 repo) | Next action |
|---|---|---|---|---|---|---|
| 1 | leverage-direction | `body.tex` | v10 (06-05) | **ready_for_submission** | 06-08 06:24 | Submission package prep + page reduction |
| 2 | crypto-fear-channel | `body_v5.tex` | v5_independent | **ready_for_submission** (PROMOTED v4.1) | 06-08 06:24 | Final cosmetic + submit |
| 3 | vt-crowding-abm | `main.tex` (v4 final, 26 pages) | v5_independent | **GREEN PASS** (0 SEVERE/0 MAJOR, 4.7★) | 05-21 09:34 | Submission package prep |
| 4 | prg-periodic-garch | `main.tex` (Paper 2) | v5_independent | **HOLD for v4.1 hotfix** (1 MAJOR + 1 MED + 3 MIN) | 06-02 20:16 | v4.1 hotfix 主線程 ~30 min |
| 5 | vt-trend-following | `body_v3.tex` | v4 | Active review | 06-06 06:14 | Next review round |
| 6 | garch-x-vix | `main.tex` | v7 | Active review | 06-08 06:24 | Read v7 verdict + plan |
| 7 | vix-sufficiency | `main_v4.tex` | v1 (06-06 Paper4 fig A update) | Early-draft / active fig refinement | 06-06 23:15 | Continue figure work |
| 8 | volatility-absorption | `main_v3.tex` | (none) | Draft revision v3 | 06-08 06:24 | First formal review round |
| 9 | taiwan-vt | `body_v3.tex` | v2 | Active review | 06-08 06:24 | Next review round |
| 10 | eav-universal-magnitude | `body.tex` | v1 | Single-round review | 05-22 06:18 | v2 review |
| 11 | vt-insurance-cost | `main.tex` | (none) | Draft, no review | 05-25 09:13 | First review round |
| 12 | btc-gas-negative | (none — drafts only) | v1 R0 MAJOR_REV | Pre-draft (review on drafts) | 06-07 16:15 | Compile draft to body.tex |

## Tier classification

**Tier A — Ready for submission（3 篇）**:
- leverage-direction v10
- crypto-fear-channel v4.1+
- vt-crowding-abm v4 final

→ 共同剩餘工作：page reduction、journal-specific formatting、cover letter、bibliography style normalization、submission-package zip。

**Tier B — 1 hotfix from ready_for_submission（1 篇）**:
- **prg-periodic-garch v4.1**：1 MAJOR (§4 vs §4.5 DM stat numerical inconsistency) + 1 MED (Bollerslev1996 cite) + 3 MIN (caption phrasing + 2 diacritic/spelling fixes)。預估 ~30 min 主線程編輯 + compile + paper-update sync。完成後升 ready_for_submission，FRL desk-accept 預期 35-45%。

**Tier C — Active review cycle（5 篇）**: vt-trend-following, garch-x-vix, vix-sufficiency, taiwan-vt, eav-universal-magnitude

**Tier D — Early draft / pre-review（3 篇）**: volatility-absorption, vt-insurance-cost, btc-gas-negative

## Seeded next tasks (3 concrete)

詳見 `storage/next_tasks.json` 對應 id：

1. **`paper_body_prg_v4_1_hotfix`** (P2, paper_body): prg-periodic-garch v4.1 — 5 items 修正細節 list-form 全部在本 audit doc + v4 README.md `§MAJOR/MED/MINOR` sections。完成標準：xelatex 0 warning + `uv run volpred ops paper-update --paper-id paper2` + NotebookLM refresh + commit。
2. **`paper_review_garch_x_vix_v7_verdict`** (P3, paper_review): 讀 garch-x-vix v7 review README + 寫 v8 plan（v7 verdict 未掃描出明確結論，需主線程 read-and-decide）。
3. **`paper_body_leverage_direction_submission_package`** (P3, paper_body): leverage-direction ready_for_submission → 製備投稿包（cover letter + page count check + JF/JFE specific formatting check）。

## Monetization 對應

- Mission #3 paper top-tier journal → Tier A 3 篇 + Tier B 1 篇 共 4 篇近期可投稿，accept 後 → academic 權威 → institutional 信任 → premium tier 變現
- Tier B (prg-periodic-garch v4.1 hotfix) 是**最近期最具體**的「升級到 ready_for_submission」槓桿點，~30 min 投入

## Audit methodology note

- 本 audit 用 `git log` 看每篇 paper 最後 touched commit、`ls review_history/v*/` 數 round count、`grep -A 1 -E "MAJOR|SEVERE|ready_for_submission|Stage Assessment"` 抽 latest verdict
- Full population scan（12 papers 全掃描，無 sample bias）— 符合 K1259 audit methodology hard rule
- 未對 `.paper_stage` marker file 全表掃（全部缺 — paper-stage-classifier skill 應補；列入 governance backlog）
