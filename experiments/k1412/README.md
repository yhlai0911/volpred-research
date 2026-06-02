# K1412 — TW0050-N225 OOS Sensitivity (rule out type-I)

## Motivation

Paper3_E2 (paper3_E2_cross_market_copula, 2026-05-29) 跑 5 markets × 10 pairs cross-market copula，**唯一** Harvey-sig 結果是 TW0050-N225 (Clayton DM_t=3.92, oos_start=2015-06-01). Aggregate Spearman ρ(λ_L_clayton, dm_clayton)=0.903 p=0.0003 highly sig，但**個別 pair Harvey 只過一個**。

`research_program.md` 明列 Open Question:

> TW0050-N225 唯一 Harvey sig — λ_L_clayton=0.444 + full_sample_corr=0.586 + Asian trading-hour overlap 三因子哪個是 driver? 需 sensitivity (different OOS start / refit_every / window) 排除 type-I error

K1412 = 該 Open Question 第一步：**OOS start sensitivity**。後續 K1413/K1414 可補 window/refit_every sensitivity 與 三因子 decomposition。

## Design

- **Pair**: TW0050-N225 (single pair，複用 paper3_E2 邏輯)
- **OOS starts**: 5 個 — `2014-01-02`, `2015-06-01` (baseline), `2016-01-04`, `2017-01-03`, `2018-01-02`
- **固定 config**: window=1250, refit_every=63, mc_paths=5000, seed=42
- **Models**: DCC-A4f-ASYM (benchmark) vs Copula-t-A4f-ASYM, Copula-Clayton-A4f-ASYM
- **Loss**: QLIKE（同 paper3_E2）
- **DM test**: HLN small-sample correction (Harvey 1997)

## Hypothesis

- **H1 (robust)**: ≥4/5 OOS starts 仍 Harvey-sig (best-copula best_dm_t > Harvey critical value) → 結論 robust，非 type-I error
- **H0 (type-I)**: ≤2/5 OOS starts Harvey-sig → original 2015-06-01 result 大概率 type-I error
- **PARTIAL**: 3/5 Harvey-sig → 弱證據，需追加 window/refit_every sensitivity

## Lookahead Guards

- 全 forecast 用 t-1 已知資訊 (paper3_E2 `oos_forecast_pair` 既有 lag 邏輯)
- Seed=42 固定（MC paths, copula sampling）
- DM test 用 OOS sample only

## Data

`yfinance`: `0050.TW`, `^N225`，2010-01-01 to 2026-05-28 (paper3_E2 cached)
Regressor: `^VIX` squared (vix2)

## Expected Runtime

~50s/run × 5 runs ≈ 250s（paper3_E2 全 10 pair 跑 471s 推算）

## Output

`k1412_results.json`:
- `per_oos`: 5 OOS 各自 DM_t / Harvey pass / λ_L / corr / mean QLIKE
- `summary`: n_harvey_sig, robust_ratio, verdict, λ_L_clayton range, corr range
- `verdict`: ROBUST / PARTIAL / TYPE-I_SUSPECT

## Codex Review Checklist

- [ ] OOS_START patching 不污染下一輪 (each call re-fits)
- [ ] paper3_E2 module reuse 沒造成 state leak
- [ ] HLN DM correction 正確套用
- [ ] Lookahead guards 維持 (paper3_E2 既有 lag 沒被覆寫)
- [ ] λ_L / corr per-OOS stability 一致 (factor identification)

## Parent / Refs

- Paper3_E2 (paper3_E2_cross_market_copula)
- `research_program.md` Open Question (Paper 3 reframe E2)
- Harvey/Liu/Newman (1997) HLN small-sample DM
- Patton (2006) IER 47(2) tail dependence
- Christoffersen et al. (2012) RFS international copula
