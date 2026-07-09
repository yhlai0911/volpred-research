# paper2_taiwan_vt_provenance_batch2b

**類型**: governance / provenance reproduction（非新研究發現）  
**日期**: 2026-07-10  
**來源任務**: `provenance-sweep-taiwan-vt-untraceable-batch2b`

## 目標

承接 `paper/PROVENANCE_SWEEP_20260710.md` 的 taiwan-vt Batch2b：把 Table 4/5、Table 2 gamma、Sec 3/4.5/6、Appendix TZ 等剩餘 untraceable 數字，盡可能綁到現有實驗 JSON；無法重現的項目明確標 `still_no_source` 或 `requires_signoff`。

## 方法

- 只讀現有 JSON artefacts：K1175、K1176、K1180、K1182、K892、K896、K515、K516、K900、`paper2_sec45_*`、`paper2_sec3_twd_usd_test`、`paper2_taiwan_indiv_rolling_gamma`、`paper2_twii_fullsample_gamma_provenance`。
- 不 live-fetch，不重新估計，不修改 manuscript。
- 逐項檢查 `paper/taiwan-vt/body_v3.tex` 的現行數字是否已由 JSON 支撐；舊 manuscript 已修過的 legacy gap 不再當成目前正文主張。

## 主要結論

`paper2_taiwan_vt_provenance_batch2b_results.json` 給出完整逐項清單。

- Table 3 / common-period Table 5 / Table 4 多數現行數字已可由 K1175 / K900 / K1176 追溯。
- Sec 6 BCI null 與 OOS Sharpe 可由 K1180 追溯；leading indicator 的精確 `t=3.74` / `R²=7.1%` 仍屬 period-sensitive drift。
- TWII `gamma=0.272, t=3.18` 與個股 rolling gamma legacy rows 仍不可重現，body 已標 sign-off，不可 silent rewrite。
- Appendix TZ 的 `-8.91bp` 與 bootstrap CI `[0.65, 2.24]` 仍沒有正式 JSON。
- TWD/USD `p=0.08` 重跑為約 `0.87`，屬 large drift；VIX Granger `F=58.8` 則可由 K1182 重現。
- TSMC VT Sharpe / 52.5% variance share 多數可追溯，但 ex-TSMC Sharpe range `0.193-0.637` 仍缺來源。

## 研究誠實聲明

本 artefact 不更改任何論文數字，只把來源狀態透明化。所有需要正文改寫的項目都必須走主線程 paper revision 與 owner sign-off。
