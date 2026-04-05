# Codex Adversarial Review — Paper 2 Section 5 (TAIFEX HF)

**Verdict: needs-attention (3 HIGH + 1 MEDIUM)**

## H1: Proxy ceiling not causally identified
- Changed target + window + sample simultaneously
- Need ablation: same sample/window, only change evaluation proxy
- Status: NEEDS EXPERIMENT (re-run GJR on same expanding window with both r² and RV targets)

## H2: Prediction-VaR paradox may be sample truncation artifact
- HAR 450 days vs GJR 481 days (not like-for-like)
- Need common sample + skewed Student-t alternative
- Status: NEEDS EXPERIMENT

## H3: Overgeneralization from Taiwan-specific structure
- Night session overlap is TAIFEX-specific
- Fix: narrow claims to "Taiwan/TAIFEX" throughout
- Status: TEXT FIX (can do now)

## M1: RealGARCH bridge claim fragile
- Same 3/481 violations as GJR, no significance test
- Fix: add DM test for Spearman gap, tone down "only model"
- Status: TEXT FIX (can do now)
