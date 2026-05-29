# k903_extension_gld_2025_2026_subwindow

- Experiment ID: `k903_extension_gld_2025_2026_subwindow`
- Status: completed
- Created At: 2026-05-30T00:00:00+08:00

## 問題描述

- 驗證 `paper/leverage-direction/body.tex:198` 的子樣本 claim：GLD 在 `2025-01-01` 到 `2026-04-16` 的 rolling GJR-GARCH `gamma` 是否為平均 `-0.089` 且 `100% negative`。

## 動機

- `paper/leverage-direction/errata_gld_rolling_gamma_forensic.md` 已確認 GLD 全樣本 `-0.067` 無可追來源，且要求獨立驗證 2025--2026 子樣本敘述是否仍站得住。

## 方法

- 資料來源：`paper/leverage-direction/data/spy_qqq_gld_tlt_eem_iwm_slv_btc_usd_vix_2010-2026.csv`
- 標的：`GLD`
- 報酬：`gld_adj_close.pct_change()`
- Rolling spec：window=`504`、step=`63`
- 模型：沿用 `experiments/k903/k903.py` 的 `fit_gjr_unconstrained()`，允許負 `gamma`
- 子樣本定義：保留 **window end date** 落在 `2025-01-01` 到 `2026-04-16` 的 rolling estimates
- HAC：目標 lags=`8`；有限樣本下沿用 K903 規則 `min(8, n_windows // 4)` 做有效 lag cap

## 預期

- 若可重現，paper L198 子句可保留。
- 若不可重現，需將「100% negative, mean -0.089」改為 errata。

## 結論

- 見 `k903_extension_gld_2025_2026_subwindow_results.json`。
