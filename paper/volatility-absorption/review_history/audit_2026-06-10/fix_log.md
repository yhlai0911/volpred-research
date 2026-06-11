# volatility-absorption 審查修正 log（2026-06-11，Codex）

## 本輪收尾

- active manuscript `main_v3.tex` 已降回可追溯 evidence set：保留 SAR、K897 null simulation、pinned-snapshot cross-asset、NFP、K903 baseline / threshold / subperiod / RV / controlled regressions。
- shock-type、VRP、hedging / portfolio-backtest 相關段落已從 active numerical evidence 移除或降級為 deferred extensions，避免再用無 JSON binding 的 Table 6--8 與「available upon request」內部數字支撐結論。
- 作者欄已移除 `VolPred Research System`，保留於致謝語境。
- README / results index / experiments index 已同步到 `MAJOR REVISION` 與 active-source 口徑。
- `reproduce.py` 已重寫成對齊 v3 活檔的 gate；不再驗證已經降級的 legacy sections。

## 仍保留的限制

- `main.tex` 不是 active source；本輪以 `main_v3.tex` 為主。
- shock-type / VRP / hedging 若要重新回到正文，必須先用 pinned snapshot 重建 JSON 與 table binding。
- K716--K722 原始估計腳本仍缺，完整歷史 provenance 仍不如新實驗標準。
