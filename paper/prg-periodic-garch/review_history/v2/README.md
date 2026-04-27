# Review Round v2 — prg-periodic-garch (Paper 6)

**Date**: 2026-04-27
**Triggered by**: 用戶 2026-04-27 授權「所有學術論文的優化全部由你決定」+ NotebookLM + 獨立 Opus 評估揭露 P5 v2 我之前 single-paper agent 4.4★ 過度樂觀（ABM 設計性問題沒抓到）。memory `feedback_paper_cross_paper_meta_eval.md` 規範 review round 必加 cross-paper meta-eval。
**Manuscript**: `paper/prg-periodic-garch/main.tex` (post v1 fix; reproduce GREEN 100% 15/15)
**Target journal**: Finance Research Letters (FRL)
**Reviewers**:
- `latex-academic-reviewer` proxy via Claude general-purpose subagent `ae2b1ac246eb66bbb`
- `citation-verifier` proxy via Claude general-purpose subagent `aa7a513a9459ba3be`
- `cross-paper-meta-evaluator` 主線程（按 NotebookLM 評估 + portfolio decision memory）

---

## Overall Assessment

| Reviewer | Verdict | Rating |
|----------|---------|--------|
| Citation | 0 MAJOR / 1 MED / 3 MINOR; 15 cites verified, v1 ERR-C1 (Lai DOI) RESOLVED | ✅ acceptable (MED-C1 Todorova2014 DOI 30 秒 fix) |
| Academic | 0 CRITICAL / 0 SEVERE / **3 MAJOR** / 5 MED / 4 MINOR; **anti-樂觀 portfolio-level lens** applied | ★★★½ (**3.6/5**, v1 4.2★ → -0.6 after honesty correction) |
| Cross-paper meta | 同 portfolio (P1-P10) 共用 SPY/GLD/TLT/VIX dataset 風險 + 新穎性中等偏低 | ⚠️ portfolio risk significant |

**Joint verdict**: **Major revise → v3 round 後再評估**。**Predicted FRL outcome**: as-is **desk-reject 30% / R&R 60% / accept 10%**；M1+M2+M3 修完後 R&R 60% / accept 25% / desk-reject 15%。**Hold in review stage**，不升 ready_for_submission。

---

## NotebookLM-identified Critical Issues — BOTH CONFIRMED ✓

### Issue 1: 不公平基準（PRG 讀兩次資訊 vs GJR 一次） → MAJOR (M1)

- ✅ Paper 有清楚揭露 fairness concern（L113-127）+ Fix B literature defense（Todorova/Opschoor §5 L311）
- ❌ **沒做 Fix A**：GJR-X controlling experiment（GJR 也讀兩次資訊的對照組）deferred to future work
- ⚠️ PRG-vs-Separate ablation **無法 close 這個 gap**（Separate 也用 both sessions；只有 bridge 差異）
- **Fix**: 4-6 小時 SPY 上跑 GJR-X experiment；預測 GJR-X DM t ∈ [2, 4]
- **Why MAJOR**: 這是 NotebookLM 抓到的 critical structural fairness — reviewer 一定打

### Issue 2: 新穎性偏低（Bollerslev-Ghysels / Linton-Wu 已有週期 GARCH） → MAJOR (M2)

- ✅ Paper citations 誠實（L58-59 引 Bollerslev-Ghysels + Linton-Wu）
- ❌ §1 L63 contribution language **at risk of over-claiming**
- ❌ Bollerslev-Ghysels **calendar→session extension** differentiation（在 `positioning.md` L21-22 有寫但**沒進 manuscript**）
- **Fix**: 30 分鐘 §1 L63 語言修 + 把 positioning.md 內 calendar→session differentiation 搬進 introduction
- **Why MAJOR**: contribution claim 不誠實標明既有 prior work limitation = referee 立刻打

---

## Issues Summary

### CRITICAL (0) — none
### SEVERE (0) — none

### MAJOR (3 latex + 0 citation = 3 total)
- **M1**. GJR-X controlling experiment 缺（不公平基準 fairness fix A）— 4-6 小時 SPY 重跑
- **M2**. §1 L63 contribution language over-claim risk — 30 min rewrite + positioning.md differentiation 搬進 intro
- **M3**. VT cross-market carry-over from v1 不完全 closed

### MEDIUM (5 latex + 1 citation = 6 total)
- 5 latex MEDs: calendar→session insert / ablation visibility / bibliography ordering / dense paragraph / GJR-X future-work language
- 1 citation MED: Todorova2014 缺 DOI `10.1016/j.frl.2014.07.001`（30 秒 fix）

### MINOR (4 latex + 3 citation = 7 total)
- 4 latex: mathptmx / abstract trim / MDD sign convention / Hansen-Huang-Shek 2012 attribution gap
- 3 citation: alphabetical reorder + cosmetic

---

## v1 Progress Verification

| v1 Issue | v2 status |
|---|---|
| v1 4 MAJOR | 2 closed, 2 partial carry-over (M1, M3) |
| v1 ERR-C1 (Lai DOI) | ✅ RESOLVED |
| v1 15 verified citations | ✅ all content-accurate in v2 |
| v1 canonical doc 3 DOIs (Blanc2014/Kim2023/Opschoor2021) | 標 typo — main.tex DOIs 對 但 v1 doc 該 housekeeping |
| 6 v1 MED + 10 MINOR + 17 DOIs | 多數 closed |
| PRS continuity §6 | ✅ added |

**No regressions**. Most v1 fixes successfully applied; M1+M3 是 v1 deferred 過大不好處理的 → v3 必修。

---

## Cross-Paper Meta-Evaluation (主線程做，按 memory `feedback_paper_cross_paper_meta_eval.md`)

### Portfolio overlap risk
- P6 PRG 用 SPY/GLD/TLT/VIX dataset — 與 P1/P3/P4ins/P5/P7/P8/P9 同一 dataset 高度重疊
- 9 篇 paper 結論都收斂「12/VIX 法則夠用 / 複雜化無益」 — P6 PRG「更簡單就贏」也走同方向
- Reviewer 可能懷疑「一篇切九份」portfolio risk

### 真實新穎性評估
- **PRG vs prior periodic GARCH**：Bollerslev-Ghysels (1996) calendar-based 已 30 年，Linton-Wu (2020) intraday periodic 12 params。PRG 賣點是「session-based + 6-8 params 更簡單」
- **這算是有 differentiation 但不是 fundamental new** — 現版 §1 contribution claim 沒充分突顯這個 narrow gap，反而看起來像 over-claim

### Portfolio-level recommendation
- **不要與 P9 GARCH-X 同時投稿**（兩篇 paper 都用 multiplicative decomposition + VIX，reviewer 可能看到自我引用 working paper 重疊）
- 若投稿，先選**單篇代表**（P6 或 P9）試水溫，等 reviewer feedback 再評估第二篇

---

## Stage Decision

**Current stage**: review (留 review stage 不升)
**Reasoning**:
- Latex 3.6★ < 4★ ✗ → 不滿足升 ready 條件
- Citation 0 MAJOR + 1 MED ≤3 ✓
- Cross-paper meta-eval ⚠️ portfolio risk + 新穎性 narrow → 不滿足
- 3 MAJOR (M1/M2/M3) blocking promote

**Decision**: **Hold in review**，跑 v3 round 含 GJR-X experiment + §1 rewrite + M3 close。

---

## Action Plan for v3

**主線程必修（v3 開始前）**:

| 優先 | Item | Effort |
|---|---|---|
| **P0** | M1 GJR-X controlling experiment on SPY（fair-info baseline） | 4-6 hr coding + 1 hr DM test + 1 hr §3 rewrite |
| **P0** | M2 §1 L63 contribution language rewrite + 搬 positioning.md calendar→session differentiation 進 intro | 30 min |
| **P1** | M3 VT cross-market carry-over close（v1 deferred） | 1-2 hr |
| **P1** | MED-C1 Todorova2014 DOI 加 `10.1016/j.frl.2014.07.001` | 30 sec |
| **P2** | 5 latex MEDs（calendar→session insert / ablation / bibliography / dense paragraph / GJR-X future-work） | 1-2 hr combined |
| **P3** | 7 MINORs + 1 citation MIN-C2 (Engle-Sokalska 2012 pre-empt) | 1 hr batch |

**Total estimate**: ~10-14 小時 main-thread effort to converge v3.

**可 deferred 到 v4**:
- 7 academic MINORs final-pass
- 1 citation MIN-C1 alphabetical reorder

**Predicted v3 → ready**: M1+M2+M3 + Meds + cross-paper meta-eval re-run → 若 GJR-X DM t ∈ [2, 4] confirm（P6 仍勝出 fair baseline）→ 4.0-4.2★ + FRL R&R 60% + accept 25%。

---

## Files in this round

- `academic_review_report.md` — full latex review (255 lines, 26KB)
- `citation_check_report.md` — full citation verification (197 lines, 14.9KB)
- `README.md` — this round summary

## Cross-link refs

- `paper/prg-periodic-garch/review_history/v1/` — v1 round
- `paper/prg-periodic-garch/review_history/pre_submission_audit_v1/` — pre-submission audit
- `paper/prg-periodic-garch/positioning.md` — PRS continuity reference (calendar→session differentiation 在 L21-22)
- `paper/prg-periodic-garch/citation_check.md` — main canonical citation trail
- `paper/prg-periodic-garch/reproduce_report.json` — GREEN 100% 15/15
- Memory: `project_paper_portfolio_decisions_2026_04_27.md` (Tier A 排序)
- Memory: `feedback_paper_cross_paper_meta_eval.md` (3 維度 review 規範)
