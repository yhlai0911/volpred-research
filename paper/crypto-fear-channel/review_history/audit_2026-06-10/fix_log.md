# crypto-fear-channel 審查修正 log（2026-06-10/11，主線程 fable-5）

## HIGH（4/7 字面處置 + 3 重跑排程）
1. Table 1 v1/v2 混 vintage → 全表 + 敘事段改 k1025_v2 真值（kurt 11.83 / skew −0.74 / mean 0.16% / RV max 1.96 / ADF −5.10）✅
2. subperiod 口徑矛盾（2015-17 p=0.014）→ abstract / 摘要 / §5.3 三處統一 Bonferroni 口徑 ✅
3. Granger HAC 不實宣稱 → 改 OLS F + lag augmentation 如實描述 ✅
5. regime 切點 22/30 → 25/35（對齊 code）+ 自家「DCC」字樣 → EWMA（RiskMetrics, λ=0.94）；文獻泛指 DCC 保留 ✅

## 重跑批次（殘項）
4. FEVD：方法描述已部分如實化；殘 — 變數排序 robustness 重算或改 KPPS generalized FEVD
6. K1025b 以 v2 spec 重跑（lagged QR + bootstrap + AIC subperiod + rolling OOS）→ 重填 Table 5
7. data pinning：snapshot CSV + auto_adjust=False + SPY log return 統一後重跑

編譯 exit 0 + paper-update 上傳 ✅（中途修復一處底線跳脫 LaTeX 錯誤）。
