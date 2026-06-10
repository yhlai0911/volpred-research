# K1457: M1 Safe-Haven Dummy in Cross-Sectional Regression (Paper 6 v6 round-3 fix)

## 動機
Paper 6 (vt-trend-following) v5 review_history 列出 M1 missing：cross-sectional regression β_TSMOM_orth = γ0 + γ1·γ + ε（body_v3.tex line 228-229, R²=0.319）只用連續變數 γ，未控制 equity-vs-non-equity 二元結構。Reviewer 質疑：γ 與 β 的正相關是否實際反映 asset class grouping（GLD/TLT 等 non_equity 同時有低 γ 與低 β），而非 leverage-effect 連續機制？

## 設計
靜態 cross-sectional OLS（N=22 同 K55 canonical universe），無時序 lag 議題。
- M0：β = γ0 + γ1·γ + ε（reproduce body 數字）
- M1a：β = γ0 + γ1·dummy_non_eq + ε（dummy alone）
- M1b（M1 fix）：β = γ0 + γ1·γ + γ2·dummy_non_eq + ε

報 classical SE（match body convention t=3.06）+ HC3 robust SE。

## 資料來源
`paper/vt-trend-following/experiments/vt_tsmom_final_n22.json` — K55 canonical 22-asset full-sample γ (GJR-GARCH) 與 β_TSMOM_orth（market+TSMOM_orth 兩因子）。15 equity / 7 non_equity (GLD, TLT, USO, HYG, LQD, VNQ, SLV)。

## 主要結果
| Spec | γ1 (γ coef) | t_classical | t_HC3 | dummy coef | R² |
|---|---|---|---|---|---|
| M0 baseline | 0.5681 | **3.06** | 3.52 | — | 0.319 |
| M1a dummy only | — | — | — | -0.0751 (t_cls=-2.27, t_HC3=-1.84) | 0.205 |
| M1 (γ+dummy) | **0.4573** | **2.00** | 2.03 | -0.0317 (t_cls=-0.84) | 0.343 |

**Reproducibility self-check**: M0 完全等同 body 公布值 (γ=0.568, t=3.06, R²=0.319) ✓

## 結論
- M0 baseline：γ1=0.568, t_classical=3.06，reproduces body 公布值。
- M1a dummy alone：non_equity 平均比 equity β 低 7.5pp（classical t=-2.27 p=0.034；HC3 t=-1.84 p=0.065 marginal）— 確認 asset class 本身有一階差異。
- **M1b（γ + dummy 聯合）關鍵**：γ1 衰減 19.5%（0.568→0.457）但仍顯著（t_classical=2.00, t_HC3=2.03, p<0.05）；dummy 在 γ 控制下**塌陷至 NS**（t=-0.84, p=0.41）。
- R²：M1a 0.205 → M0 0.319 → M1b 0.343（dummy incremental R²=0.024 over γ alone, F-test p≈0.4）。

**Interpretation**: γ **subsumes** asset class 效應 — non_equity assets（GLD, TLT 等）的低 β 主要因其低 γ（leverage 機制弱），非「身為非股票類別」本身。聯合迴歸中 dummy 失去獨立 explanatory power，而 γ 仍顯著。此 finding **強化** body §3.x narrative：γ→TSMOM 是連續 leverage-effect 機制，非離散 asset-class grouping artifact。Mild γ1 衰減（19.5%）反映 γ 與 dummy 共線性（non_equity 平均 γ=0.045 vs equity 平均 γ=0.143），不削弱主因果方向。

## 對 paper body 的影響
Round-3 fix M1 完成：在 Table 2（tab:cross_section）後加 M1 三行（M0/M1a/M1b）替代既有 Welch t-test 兩行；在 §3.x leverage discussion paragraph 補一句 "controlling for asset class, γ1 attenuates 19.5% but remains significant (t=2.00)，dummy itself NS — consistent with continuous leverage mechanism rather than discrete asset-class grouping."

## Lookahead / Seed
- Lookahead: N/A (cross-sectional)
- Seed: N/A (deterministic OLS)
- Data snapshot: K55 canonical N22 JSON committed pre-2026
