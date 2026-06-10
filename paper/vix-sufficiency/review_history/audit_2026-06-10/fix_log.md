# vix-sufficiency 審查修正 log（2026-06-10，主線程 fable-5）

## HIGH（6/6 處置）

| # | Finding | 處置 |
|---|---------|------|
| 1 | 2026-05-30 errata 未落地（BH Sharpe 0.947→0.827 + narrative 翻轉） | ✅ Table 3 L528-529：BH 改 0.827（K731 canonical, % source 註）、12/VIX 改 reference row（MDD −32.2）、ΔSharpe −0.043；L551 narrative 重寫（12/VIX 略勝 BH + erratum 揭露 + 「margin 不顯著」誠實表述） |
| 2 | 標題 Eleven vs 全文 thirteen | ✅ 標題改 Thirteen Signal Families |
| 3 | L504「all eight … well above 0.05」v3 殘文 | ✅ 重寫：10 testable；families 1-4,8-11 raw p≥0.147 null；12-13 兩側顯著但方向 harmful（signed t<0），one-sided null 不拒絕 |
| 4 | Intro +0.010 vs Table 3 +0.030 | ✅ L89 改 +0.030（behavioral sentiment, DM 0.72）；L554 重寫（behavioral 最大 +0.030，contango +0.010 次之） |
| 5 | luo2019 作者錯置 | ✅ bibitem 改 Huang, Tong & Wang (2019)（cite key 保留避免動 in-text；display 名已正確） |
| 6 | 「pre-registered」與 L165 自承 12-13 後加矛盾 | ✅ L74 改 pre-specified + 揭露（1-11 原設計、12-13 revision 加入同 pipeline 評估）；L80 safeguard 同步改 |

## MEDIUM（8 項 — 殘項待補）
詳 audit_findings.json — 主要為 §7.1 殘留文字、表注措辭等，下一輪補。

## 殘項 next steps
1. xelatex 編譯 + paper-update 上傳（分類器中斷中，恢復即跑）
2. MEDIUM 8 項逐條
3. errata 檔標記「已落地 2026-06-10」
