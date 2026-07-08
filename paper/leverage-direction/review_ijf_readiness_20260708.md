# Leverage-direction IJF submission-readiness review — 2026-07-08 (hourly-13, main thread)

**Reviewer source**: main thread (Codex CLI 額度用盡至 7/11 → 論文 methodology review 依 CLAUDE.md 由主線程執行，合規 fallback).
**Scope**: `body_v_ijf.tex` (354 lines) post Option-A honest-null reframe (A-tick-1/2, 2026-07-03).

## Verdict: MINOR_FIXES
Honest-null reframe 大體徹底、claim-evidence 綁定良好（多數數字帶 `% source:` k903 tables）。僅 1 處殘留 narrative 不一致已修；投稿前 2 個結構性 blocker 待驗。

## 4 項檢查

1. **Narrative 一致性 — PASS (after 1 fix)**：title(中性問句)/abstract("largely no")/intro("it does not")/§5.2 header("No Robust OOS Superiority")/§6.1("Views of the Null") 全一致為 null。「complexity ceiling」為刻意保留的 interpretive metaphor（A-tick-2 決定），非 headline claim，一致。
   - **FIXED**：§5.4 (L314) 原「the sign of γ also **predicts** whether VT re-weighting behaves as trend-following or contrarian」→「is also **associated with**」。原文與 intro (L176 已用 "is associated with") 矛盾，且 N=6、domain-restricted 的 regularity 用「predicts」過強。

2. **殘留 over-claim — PASS**：L291 SPY DM edge 明標「does not survive multiple-testing correction」；L293 selection rule 明標 defensive/risk-controlled + 逆轉舊 same-window draft 敘事；L299 ρ=0.944(N=5) 已用 14-asset extended (ρ=0.83, p=0.0002) 作 primary basis 對沖小 N。無過強句子殘留。

3. **Claim-evidence match — PASS (minor)**：主要數字有 `% source:` 綁定（k903 tables，符合 paper-workflow rule 3）。輕微 gap：L301 gold anti-VT Sharpe (1.71/1.51/1.56) 無 inline source note；建議補綁定。

4. **IJF honest-null fit — PASS，但 2 blocker**：contribution framing（可復現 measurement→allocation 框架 + honest null）適配 IJF methods-track。

## 投稿前 top blocker（未在本 fire 解，屬 A-tick-2/3 TODO，需驗證非改寫）
1. **Online Supplement 必須實存並入 replication package**：HAR paradox (L337)、14-asset extended sample (L299)、EWMA/window robustness、VaR orthogonality decomposition (L320) 均指向 "Online Supplement"。若未打包 → desk-reject 風險（paper-workflow self-contained hard requirement）。
2. **reproduce.py match_rate ≥ 95% gate**：A-tick-2 tracker 標「every retained number reproduce-gated」但狀態未驗；per paper-workflow rule 2，未 pass 不得標 ready/submit。
3. （非 blocker）L301 gold anti-VT 數字補 `% source:` 綁定。

## 下一步建議
A-tick-3 收斂：驗 Online Supplement 存在 + 跑 reproduce gate → 通過才進 journal-review skill 的 IJF format/compliance gate。
