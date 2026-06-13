# K_repo_basis_funding_stress_gate_duration_2026_06_14 — Repo-basis funding stress gate 預測 duration 資產波動

**Status**: NULL  
**Date**: 2026-06-14  
**Task source**: `research_repo_basis_funding_stress_gate_duration`

## 動機

這題來自 `research_program.md` 的研究 backlog：檢查 repo funding 壓力與
basis-trade proxy 是否能領先長天期利率資產波動。和現有 `I8` 不同，這裡不
再看單純的現貨/期貨價差，而是改用更接近機制本身的兩類訊號：

1. **Funding 壓力**：SOFR、EFFR、TGCR 的利差
2. **Basis-trade proxy**：CFTC Traders in Financial Futures 中，UST 10Y / UST Bond 的 leveraged funds 空單占 open interest 比例

目標資產是 `TLT`、`IEF`、`ZN=F`，看這些 stress proxy 是否能預測**下週**
realized variance。

## 與既有知識的差異

- `I8` 測的是 `TLT-ZN` 的價差 basis 對未來 RV 的解釋力；本題改測
  **funding + 槓桿部位**。
- `k_treasury_signed_vol_imbalance_2026_06_14` 測的是 Treasury 方向性流量代理；
  本題改成**repo / basis-trade 機制**。

## 文獻 / 背景來源

至少三個外部來源，供設計與解釋使用：

1. New York Fed, *Recent Developments in Treasury Market Liquidity and Funding* (2025)  
   basis trade 規模與 funding liquidity 對 Treasury market stability 的關聯。
2. Dallas Fed, *How sensitive is the Treasury cash-futures basis trade to funding conditions?* (2025)  
   討論 basis position 對 funding stress / 市場波動的敏感度。
3. Federal Reserve FEDS Notes, *Quantifying Treasury Cash-Futures Basis Trades* (2024-03-08)  
   用 CFTC / futures positioning 衡量 basis trade。

## 設計摘要

- **樣本**：2018-04-03 到 2026-06-13
- **頻率**：週頻（訊號日為週五）
- **Lookahead 防護**：
  - CFTC `Report_Date_as_YYYY-MM-DD` 是週二持倉，不可直接當週二可交易資訊。
  - 腳本一律把 CFTC 訊號可用日設為 `report_date + 3 天`，也就是**週五 release 日**。
  - 目標 `future_rv` 僅使用 release 日之後的下 5 個交易日。
- **Target**：下 5 個交易日 annualized RV
- **Stress index**：SOFR-EFFR、SOFR-TGCR、basis-short proxy 的 expanding z-score 平均，避免用全樣本標準化把未來分布帶進訊號
- **Baseline**：`log(RV_{t+1}) ~ const + log(RV_t)`
- **Full**：`log(RV_{t+1}) ~ const + log(RV_t) + stress_index`
- **檢定**：
  - Full-sample Newey-West HAC(4)
  - Block bootstrap（block=8, B=2000, seed=42）
  - Expanding-window OOS QLIKE + Diebold-Mariano

## 核心結果

- 初版用 full-sample z-score 標準化 stress index，Codex review 視為 OOS lookahead contamination；已改成 expanding z-score 後重跑。
- 修正後三個資產都沒有穩健訊號：
  - `TLT`：beta `+0.0403`，HAC t `0.35`，bootstrap p `0.948`，`QLIKE Δ=-0.0054`，`OOS R²=-0.0240`
  - `IEF`：beta `-0.0351`，HAC t `-0.37`，bootstrap p `0.524`，`QLIKE Δ=-0.0011`，`OOS R²=-0.0216`
  - `ZN=F`：beta `-0.0567`，HAC t `-0.57`，bootstrap p `0.497`，`QLIKE Δ=-0.0018`，`OOS R²=-0.0168`

因此本題不能支持「repo-basis funding stress 會推高下週長債波動」這個正向機制敘事；
在 lookahead-safe scaling 後，也不能支持原本的 reverse-sign 解讀。結論應收斂為 NULL。

## 檔案

- `k_repo_basis_funding_stress_gate_duration_2026_06_14.py`
- `k_repo_basis_funding_stress_gate_duration_2026_06_14_results.json`
- `fig_stress_index_timeseries.png`
- `fig_tlt_scatter.png`
- `codex_review.md`

## 重現

```bash
uv run python experiments/k_repo_basis_funding_stress_gate_duration_2026_06_14/k_repo_basis_funding_stress_gate_duration_2026_06_14.py
```
