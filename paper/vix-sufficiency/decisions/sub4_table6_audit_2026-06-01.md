# Sub4 Table 6 era-Harvey audit (2026-06-01)

**Task**: `Paper4_DIV4_Table6_era_Harvey_passes` (P4 / paper_review / pending_main_thread)
**Trigger**: next_tasks 描述「Table 6 顯示 0/5 Harvey pass, 數字小 10-186×」
**Decision**: 已 RESOLVED in main_v3.tex (Sub4, 2026-04-19) + main_v4.tex (current canonical)

## Verification

對照 main_v4.tex L591-593 vs K752 `part_d_competing_signals_by_era`:

| Signal | Era | paper v4 incr_R² | K752 incr_R² | t-stat | harvey_pass |
|---|---|---|---|---|---|
| Overnight VIX abs | Era3 GFC | 0.0039† | 0.0039 | -3.15 | true |
| VRP proxy | Era3 GFC | 0.0160† | 0.0160 | -6.51 | true |
| Vol momentum 20/60 | Era3 GFC | 0.0216† | 0.0216 | +7.60 | true |
| Vol momentum 20/60 | Era5 COVID | 0.0372† | 0.0372 | +9.30 | true |
| Overnight VIX abs | Era5 | 0.0032 | 0.0032 | +2.65 | false |
| VRP proxy | Era5 | 0.0005 | 0.0005 | -1.04 | false |

100% numeric match。4 個 † 標記 + footnote (L598) 明確說明 "four such crossings occur—three in Era 3 (GFC: all three signals) and one in Era 5 (COVID/Inflation: Vol momentum 20/60)"。主文段落 (L603) 也已 nuanced rewrite。

## v1 vs v4 對比（task description 來源）

main.tex (v1) Table 6 全是 0.0001–0.0008 量級 + Harvey Pass = 0/5,0/5,0/5 — 與 K752 偏差 10-186×（task description 的數字正確描述 v1 狀態）。Sub4 fix 已在 main_v3 + v4 修正，task 描述未隨之 update 因此 stale。

## Conclusion

- **無 paper-side 動作需要做**: main_v4 Table 6 數字 ✓ 標記 ✓ footnote ✓ narrative ✓
- **無 errata 需要發**: 修正落在 v1→v3 過程，v3/v4 從未公開投稿
- 標 task succeeded，下班。
- Universal-null 命題保留為「on-average / OOS DM-HB-corrected 後」— v4 已正確 framing。
