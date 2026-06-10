# taiwan-vt 審查修正 log（2026-06-10，主線程 fable-5）

## HIGH（5/5 處置）

| # | Finding | 處置 |
|---|---------|------|
| 1 | Abstract 5.0×/CI[2.8,8.1]（CI 全 repo 無來源） | ✅ main_v3.tex L35 改 canonical 4.3× + CI[2.28,6.58]（K1370），rolling 5.0× 降為括註 |
| 2 | Intro「Student-t VaR 0.5%」錯置（0.51% 屬 Cornish-Fisher；窗口錯） | ✅ body L16 改 K896 canonical：GJR+Student-t/HistSim 1.03%（唯二過 VaR trinity+ES）、C-F 0.51% over-conservative、窗口 2019–2026 |
| 3 | SSVS 表 PIP 0.312/0.087 無來源 + footnote 歸屬錯誤 | ✅ 表全重建（K461 真值：SPY ret 1.000、AR(1) 0.9994 t=−10.29、SPY momentum 0.937、VIX change 0.881、VIX level 0.801）；SPY 對照欄移除 + Notes 誠實揭露無來源；正文改寫（not sparse、broad U.S.-info block，刪無來源的 U.S. empty-model 對比） |
| 4 | §8.2 insurance cost 用已撤回 pre-2009 vendor 數字（−77.3/−48.6/7.59/3.71） | ✅ 以 K1175 重算整段：MDD 改善 12.6pp、CAGR 成本 7.06pp → 56bp/pp（非 13.5bp）；U.S. 對比改「order of magnitude lower」+ 結論誠實重評（高保費、適合高風險趨避者） |
| 5 | §8.1 用已撤回 Sharpe 0.69 比較 FX | ✅ 改質性論述 + canonical 1.137 引註 + 揭露 FX-converted 重算未跑 |

## 計量重跑需求
- FX-converted 12/VIX-on-SPY 比較：**需新 K 實驗**才能恢復量化比較（已揭露，質性論述不依賴它）
- U.S.-side SSVS 對照欄：**需 dedicated 實驗**（表注已標 pending）
- 其餘修正均對齊既有 canonical 實驗（K1370/K896/K461/K1175），無新增未溯源數字

## 殘項
- xelatex + paper-update 上傳（分類器中斷，恢復即跑）
- MEDIUM 5 項（見 audit_findings.json）
