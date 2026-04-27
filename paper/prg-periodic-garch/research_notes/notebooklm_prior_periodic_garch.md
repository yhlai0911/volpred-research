# P6 PRG — NotebookLM Prior Periodic GARCH Audit

**Date**: 2026-04-27 02:08 CST
**Notebook ID**: `5d8707e3-fb41-4fc8-a444-f7ee647a86d5`
**Notebook Title**: "P6 PRG Prior Literature RAG"
**Conversation ID**: `9454ea19-3056-498b-8a00-298865afe729`

## Sources（8 ready + 3 paywall errors）

由 `notebooklm source add-research "Bollerslev Ghysels periodic GARCH" --mode fast` 主動 discover + auto-import：

1. On Periodic Autoregressive Conditional Heteroskedasticity (EconPapers)
2. On The Accuracy of GARCH Estimation in R Packages
3. On some probabilistic properties of periodic GARCH processes (arXiv)
4. **Periodic Autoregressive Conditional Heteroscedasticity** (Duke Economics) ← 應為 Bollerslev-Ghysels 1996
5. Real Estate Investment Trusts and Seasonal Volatility
6. Seasonal asymmetric persistence in volatility (ORBilu)
7. Temporal Aggregation of a Strong PGARCH(1,1) Process
8. **P6 PRG main.pdf** (我們的 paper) ← `notebooklm source add` 加入

3 個 tandfonline web sources 因 paywall return error（不影響 query）

## Query

> Compared to the periodic GARCH literature in this notebook (Bollerslev-Ghysels Duke 1996, periodic ARCH variants, seasonal asymmetric persistence, periodic long-memory GARCH, etc.), what is the unique contribution of the PRG paper (the supabase main.pdf source)? Specifically: (1) is the session-based simplification (6-8 params vs prior 12+ params) genuinely novel, or already covered? (2) what concrete differentiation argument should §1 make to defend FRL submission? Quote relevant sources where possible.

## Answer — 3 個具體 differentiation argument（直接給 P6 v3 M2 §1 rewrite 用）

### Argument A: Session-Boundary Information Bridge（**核心 ablation 論證**）

PRG 強迫 conditional variance $h_n$ 從一個 session 收盤 **carry 到下個 session 開盤** → cross-session **"information bridge"**。這是區分 PRG vs prior periodic GARCH 的關鍵 mechanism — prior 多數把 sessions 當 separate 或 blend 成 close-to-close。

**Concrete evidence（必引）**：
- Ablation 實驗 sever cross-session link → DM $t$ 從 **6.00 → -0.57**（outperformance collapse entirely）
- Mincer-Zarnowitz $R^2$ 從 **0.464 → 0.264**（cut nearly in half）
- PRG vs Separate GARCH benchmark: DM $t$ ranging $-4.07$ to $-6.69$（cross all markets）

**Take-away**: PRG 的貢獻是 linkage（cross-session bridge）不是「不同 phase 用不同參數」這個老把戲。

### Argument B: Ultra-Parsimony and Implementability

對 FRL audience（practitioner-facing）emphasize PRG 比 existing overnight/intraday models **顯著更簡單**：

| Prior approach | Complexity |
|---|---|
| Kim et al. 2023 | Continuous-time diffusions |
| Linton-Wu 2020 | Massive coupled EGARCH systems |
| Lai et al. 2024 | Regime-switching unobserved variables |
| **PRG** | **Standard MLE + 6-8 params** |

→ Risk manager friendly + robust to overfitting in moderate samples + effortlessly implementable

### Argument C: Exposing "Target-Mismatch" Illusion in Prior Literature

Prior literature 普遍認為 **HAR > GJR** in volatility forecasting — 但這是 **"target mismatch" artifact**（Patton 2011 警告）。

**Concrete evidence（必引）**：
- 強迫 common fair target $\sigma^2_{\text{full}} = r^2_{\text{overnight}} + r^2_{\text{intraday}}$
- → GJR vs HAR **statistically indistinguishable**（DM $t = 0.57$ on TAIFEX）
- PRG dominate **both** because two-phase timing convention 允許 forecast 在 market open 用 fully realized overnight return

→ **PRG 不只是 better model，是 expose 整個 prior literature 的 evaluation methodology bias**。這是 FRL-worthy 的 "punch"。

## How to apply（P6 v3 M2 §1 rewrite）

1. 重寫 §1 contribution claim 從「first to model session-based periodic GARCH」改為這 3 個 specific argument
2. 把 `positioning.md` L21-22 的 calendar→session differentiation 搬進 intro，**加上 cross-session information bridge mechanism**
3. 確保 ablation evidence (DM 6.00→-0.57, MZ R² 0.464→0.264) **明確進 §1 而非只在 §5**
4. Cite Bollerslev-Ghysels 1996 + Linton-Wu 2020 + Kim 2023 並用 differentiation table 對比 parsimony

## Cross-link

- `paper/prg-periodic-garch/review_history/v2/README.md` — v2 round verdict 提 M2 §1 rewrite
- `paper/prg-periodic-garch/positioning.md` L21-22 — calendar→session differentiation 既有素材
- `paper/prg-periodic-garch/main.tex` — 待修檔
- Memory `reference_notebooklm_rag_workflow.md` — workflow reference
