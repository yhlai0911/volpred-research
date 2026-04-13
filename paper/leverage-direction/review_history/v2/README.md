# Review Round v2 — leverage-direction

**Date**: 2026-04-13
**Triggered by**: User directive to evaluate paper readiness (priority sort by quality+completion)
**Reviewers**:
- `citation-verifier` skill (agent a990382e8119702c9)
- `latex-academic-reviewer` skill (agent acfb6a6c76db4abd2)

---

## Overall Assessment

| Reviewer | Verdict | Rating |
|----------|---------|--------|
| Citation | 0 MAJOR / 5 minor / 3 MED content / 2 NEEDS_CHECK | ✅ |
| Academic | **NOT ready_for_submission**, predicted JBF major revision | ★★★☆☆ (3/5) |

**Stage decision**: leverage-direction stays at **review** (not promoted to ready_for_submission).

---

## Issues Summary

### HIGH severity (7) — blocking submission

1. **Internal contradiction #1**: bear-market gold γ reported as +0.20 vs +0.048 in same line (body_v2.tex line 208)
2. **Internal contradiction #2**: Henriksson-Merton γ_HM cross-section (§4.8 line 373: -0.035 n.s.) vs (§5.4.4 line 433: -0.043 t=-4.06 ***)
3. **Proposition 1 statistically fragile**: N=6 ρ=0.886 → N=12 ρ=-0.448 (n.s.). Should rebrand "Empirical Regularity" or do OOS extension
4. **Table 3 "9/9 perfect"** is in-sample but abstract lacks qualifier
5. **Missing ES backtest**: FRTB 2019 mandates this for VaR work
6. **BTC allocation logic conflict**: γ>0.10 rule assigns GJR but Table 3 prefers GARCH for BTC
7. **Citation issues**: 2 missing critical (Engle-Ghysels-Sohn 2013 GARCH-MIDAS, Patton-Sheppard 2015 good vol) + 3 orphans残留 (bollerslev1994, corsi2009, engle2002)

### MEDIUM (3 from citation review)

1. `hou2020` content claim mismatch (line 61) — Yahoo-vs-CRSP attribution wrong
2. `demiguel2024` framing inaccurate (line 46) — "13% Sharpe" not from this paper
3. `xu2024` author initial wrong (Y. → X.)

### Minor (~10)

- Format/typo issues in bibliography
- Length: 62p vs JBF ideal 45p (compress TZ momentum appendix)
- Table 5 missing sample-period column
- VaR Student-t formula needs σ_t clarification

---

## Action Plan for v3

**主線程必修**（全 7 HIGH + 3 MED）：
1. 修 internal contradictions：統一 gamma 數字（pick one calculation, update consistently）
2. 移 H-M γ 跨節到單一節，標 final value
3. Rebrand Proposition 1 為 Empirical Regularity 或加 OOS 驗證
4. Abstract 加 in-sample qualifier
5. 加 ES backtest section（K1041/K1092 已有 ES infrastructure 可重用）
6. 修 BTC rule 或排除 BTC
7. 加 Engle-Ghysels-Sohn 2013 + Patton-Sheppard 2015 引用，刪 3 orphans
8-10. 修 hou2020 / demiguel2024 / xu2024 (citation issues)

**可 deferred 到 v4**：
- 長度 compress（先看 v3 修完還剩多少頁）
- Format minor

**Prediction for v3**：if all 7 HIGH fixed → likely ★★★★/5, ready for JBF submission.

---

## Files in this round

- `citation_check_report.md` — citation-verifier 完整輸出
- `academic_review_report.md` — latex-academic-reviewer 完整輸出
- `README.md` — 本檔（摘要 + 行動清單）

## Next round trigger

- After 主線程完成 v3 修正
- 跑新一輪 citation-verifier + latex-academic-reviewer → 寫入 `review_history/v3/`
- 比較 v3 vs v2：HIGH 從 7 降到 ?，目標 0
