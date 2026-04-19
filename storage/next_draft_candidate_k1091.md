# Next Draft Candidate: K1091 Meta-Prediction OOS Asset-Class Asymmetry

**Prepared 2026-04-19** as preemptive brief for future `draft_pool_low` remediation. Alternative to K957 memo; pick whichever fits pool gap + user direction.

## K1091 Overview

**Score**: 5
**Title**: K1091: Meta Prediction Out-of-Sample Test — Equities VGK/EWJ PASS Clean, Commodities CPER/SLV FAIL (No Matched IV)
**Coverage**: uncovered any audience

## Why this topic works

- **Asset-class asymmetry** 是鮮明 general-audience hook：「為什麼股指 meta-prediction 準，但銅/銀預測不準？」
- **方法論橋接**：K1090 meta-regression → K1091 OOS validation — 讀者看得到 paper / research workflow 實際操作
- **具體數字**:
  - VGK (European): predicted +4.71, realized +4.46, |err|=0.25, **Harvey PASS** ⭐
  - EWJ (Japan): predicted +4.34, realized +4.81, |err|=0.47, **Harvey PASS** ⭐
  - CPER (Copper): predicted +3.58, realized +0.4x（預測差 3x）**FAIL**
  - SLV (Silver): similar commodity FAIL
- **解釋核心**：「No Matched IV」 — commodities 缺適當 implied volatility benchmark，predictive regression 失真

## Article Skeleton Proposal (general audience 2000-2500 chars)

1. **Intro**: 研究者如何用 K1090 meta-regression 預測哪些資產 VIX sufficiency 會通過 Harvey
2. **Out-of-sample test**: 用 4 個未訓練樣本外資產驗證（K1091）
3. **Equities 符合預期**: VGK/EWJ |err|<0.5 — 預測方法 works
4. **Commodities FAIL**: CPER/SLV |err|>3 — 為什麼？
5. **"No Matched IV" 機制**: stocks 有 VIX（匹配 S&P 500），commodities 沒有對應 IV index — predictive base 失去可比性
6. **Implication**: 方法論 meta-prediction 只在 structurally similar 資產類別有效
7. **Cross-link to K957 / K672** (if published): evidence from 1421 entries 的層級

## Charts needed (2 real)

1. Predicted vs Realized scatter plot 4 assets + 45° line + Harvey threshold boundary
2. Error magnitude bar chart by asset-class（equities vs commodities）

## Data sources

- `experiments/k1091/k1091_results.json`
- `experiments/k1090/k1090_results.json` (meta-regression training)
- `experiments/k1092/k1092_results.json` (related DCC-A4f asymmetric)

## Dispatch when

- Pool drops below 4 again after K957 used OR
- User requests methodology-explainer angle article

## Differentiation vs other memos

- **vs K957**（methodology lessons from experiments process）— K1091 是 **single OOS validation case study**，more focused
- **vs K672**（cumulative findings from 1421 entries）— K1091 是 **asset-class limitation mechanism discovery**

## Hard rules (agent briefing template)

- proposer="Claude" / audience="general" or "research" (methodology explainer 可 dual-audience) / category="milestone" / status="draft"
- 2000+ chars CJK
- 2 real matplotlib charts
- 不 touch shared memory
- 圖 1 scatter with Harvey threshold line is critical visual
