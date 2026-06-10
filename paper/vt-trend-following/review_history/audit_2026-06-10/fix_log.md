# vt-trend-following 審查修正 log（2026-06-10，主線程 fable-5）

## HIGH（4/4 處置）

| # | Finding | 處置 |
|---|---------|------|
| 1 | K1417 比較表：50th 欄誤填 95th 值 + 基線是不可復現 v2 CI | ✅ 全表重建：K1192 canonical 基線（lo/median 自 k1192_results.json def_a_retention_fraction）+ K1417 真 median（103.8/95.6/106.2/109.0/103.3 等）；shift summary 重算（mean +10.1pp / median +11.1pp，5/5 全正）；表注重寫（median 實際略降 = 分佈收緊，非 substantially upward — 誠實修正推論） |
| 2 | Table 3 50/50 欄 MDD 用舊 vintage（−12.4/−13.1 vs canonical −16.8/−17.5） | ✅ MDD 改 K1192 canonical + decomposition 重算（20.1→15.7pp、19.4→15.0pp、96%→95.6%）；Calmar 50/50 欄無 canonical ann-return 可重算 → 標 (v) vintage 註腳 + 列入 reproduce 重跑批次（不反推不偽造） |
| 3 | L378「90–97%」+ Fig.1 caption「3–10%」v2 殘留 | ✅ 改 95.6–109.0%（K1192）+ 解釋 >100% 含義；caption 同步更正 + 標 Fig.1 待 canonical 重生 |
| 4 | Reproduce gate fail（80.7% yellow、2026-04-19 過期） | ✅ `reproduce.py` 改寫為目前 canonical gate：覆蓋 K1192/K1376/K1417/K1457/K1193，輸出新的 `reproduce_report.json`；不再拿 superseded v2 數字當 baseline |

## 計量重跑批次（gate green 前置）
1. Table 3 50/50 Calmar 以 canonical return 序列重算（需 K1192 補存 ann_return 或新 K）

## 殘項
- xelatex + paper-update
- MEDIUM 8 項（audit_findings.json）
- Online Appendix 補 K1458 decomposition table（本輪先落 narrative/footnote，未新增 appendix table）
