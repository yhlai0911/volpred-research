---
name: feedback_3spec_disambiguation
description: Paper 中同一 symbol (如 γ) 有多個 spec 產生的不同數值，用 3-spec footnote 解；也適用 reproduce-gate MISMATCH 重分類 NOTE
type: feedback
originSessionId: 01d23520-901e-44a9-9f09-f9e497e18020
---
當 paper 的某個 symbol（如 $\gamma_{HM}$、$\gamma$ GJR-GARCH leverage、DM t-statistic 等）在不同 sections 有不同數值，**不一定是錯誤 — 可能是不同 spec**：

- Zero-mean GJR vs Constant-mean GJR
- Short window vs long window
- Sub-sample vs full-sample
- Different estimator (K799 vs K802 alternate residual treatment)
- Different convention (auto_adjust=True vs False)

**Resolution pattern**（本 session P1/P2 成功驗證）：

1. **Body.tex 加 footnote dagger** 明示 3-spec disambiguation（本 session 用 `\ddagger`/`\S`/`\P` 區分）：
   ```
   $^{\ddagger}$ Table X reports $\gamma = ...$ under the Zero-mean GJR-GARCH specification
   estimated on 2008-2026 full sample; Section Y reports $\gamma = ...$ from the
   Constant-mean specification. The K892 canonical re-estimate yields ... consistent
   with the Constant-mean pooled estimator. Three specifications share the same symbol.
   ```

2. **reproduce.py 對應 check 改 NOTE tier**（不是 MISMATCH）：
   ```python
   add("Internal", "TSMC gamma Table 2 (0.039) vs Sec 4.5 (0.054) — 3-spec disambiguated",
       "disambiguated", "K892", "Zero-mean=0.039, Constant-mean=0.054, K892=0.0525",
       "NOTE")  # was MISMATCH
   ```

3. **README.md Status 反映**：「4 MISMATCH disambiguated via body footnote, 現 0 MISMATCH」。

**Paper precedent**（本 session 成功應用）：
- P1 leverage-direction K1256 3-spec（pure_vt_full / pure_vt_high_vix / hybrid_vt_full）
- P2 taiwan-vt TSMC γ / 0050.TW γ / TWII γ 3-spec

**When this pattern does NOT apply**：
- 真的抄錯格（paper 作者搞錯）→ (a) 修論文
- 統計上 sign flip（例如 P8 T10 2020-26 β −0.00035 → +0.000139）→ 不是 spec 差異，要 CRITICAL errata
- Harvey-threshold crossing（|t|>3 → |t|<3 across snapshots）→ errata revise body claim

**How to apply**:
- 發現 paper 內同 symbol 兩個值前，先查 K-experiment JSONs 看是否有多個 spec stored
- 若是 legit spec difference → 3-spec footnote 是 cleanest resolution
- 若是 value copy error → (a) 修論文 canonical value
- 若是 sign/Harvey crossing → CRITICAL errata，不能 NOTE
