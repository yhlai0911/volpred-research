# 2026-06-10 Codex Fix Log

Task: `paper_body_audit_fix_prg_periodic_garch_2026_06_10`

> **主線程獨立驗證（2026-06-11 00:15, fable-5）**：4 項 HIGH 修正逐項以 grep/讀檔驗證屬實
> （Table 2 正值+note L195-205、GJR-X 資訊集 L313、Basel exact-binomial L259-272、six-markets 句 0 hits）。
> 編譯 exit 0 + paper-update 重新上傳完成。

Completed:
- Unified Table 2 DM sign convention to `benchmark loss - PRG loss`, so positive values favor PRG in every column.
- Softened Harvey 2016 wording from "standard volatility-forecasting threshold" to a conservative paper-specific adoption motivated by multiple-testing logic.
- Corrected GJR-X discussion: removed the unsupported "identical information / structural not informational" claim and reframed it as a stricter lagged-overnight exogenous-regressor benchmark.
- Corrected Table 4 Basel zones for TAIFEX GJR and SPY GJR using exact-binomial thresholds at each market's realized OOS sample size.
- Softened VaR/ES generalization from an unsupported six-market universal ordering to the reported-market/SPY-supported scope.
- Fixed Hansen proxy-ranking citation from `Hansen2005` to `Hansen2006`.
- Fixed Table 5 mapping in `experiments.md` to `K874e layer6_economic`.
- Synced reproducibility target in `reproduce.py` with the new positive-sign Table 2 convention.
- Synced Basel traffic-light logic in `k874e_full_comparison.py`, `k880_prg_spy_validation.py`, `k881_prg_multi_asset.py`, and `src/volpred/stats/model_evaluation.py`.

Not changed:
- No new parameter-estimate appendix was added in this pass.
- No new Sharpe-difference/bootstrap test was added in this pass.
