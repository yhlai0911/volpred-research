# Paper Review (Codex 24h-rule): mile_28e6123e — K860 Prospect Theory VT 文章

**Article**: 同一筆數據，兩種評估框架，排名就對調了
**Published**: 2026-06-14 11:00 (~9h ago)
**Verdict**: **FAIL — 3 處數字錯誤需修正**

## Issue 1 (CRITICAL) — CE 排名表 BH_5050 / VT_12VIX 互換

文章表格（line 46-52 of article）：

| 策略 | PT-CE 月均排名 | 文章 CE | JSON 真值 |
|---|---|---|---|
| 風險平價 | #1 | -0.029% | -0.0293% ✓ |
| VT Robust | #2 | -0.031% | -0.0307% ✓ |
| **BH 50/50** | **#3** ❌ | -0.045% | -0.0452% (應為 **#4**) |
| **VT 12/VIX** | **#4** ❌ | -0.040% | -0.0401% (應為 **#3**) |
| BH SPY | #5 | -0.176% | -0.176% ✓ |

數字本身對，但 less negative = better 邏輯下 -0.0401% > -0.0452% → VT_12VIX 應排 #3、BH_5050 應排 #4。表格內部不一致（數字與排名互打架）。

## Issue 2 (CRITICAL) — "0.17 個百分點" 倍數錯誤 ×2 處

文章 line 54：「換算成月均 CE 差距：VT Robust 比 BH 50/50 多出 **0.17 個百分點**」
文章 line 76：「λ=2.25，VT Robust 的月均 CE 已高出 BH 50/50 達 **0.17 個百分點**」

實際計算：-0.0307% - (-0.0452%) = **0.0145 pp**（≈ 1.45 bps/月）
文章兩處皆高估 **11.7x**。正確應為「0.014 個百分點」或「1.4 bps」。

## Issue 3 (MEDIUM) — Opening narrative 連帶誤導

文章首段（line 5）：「VT Robust 升到第二，而 BH 50/50 滑到第三」
實際 BH_5050 從 Sharpe #2 滑到 PT-CE **#4**（不是 #3）— 2 階位跌幅，narrative 反而**低估**了排名翻轉的戲劇性。

## ✓ 通過驗證項

- `shift(1)` lookahead protection — 4 個 VT 策略全 lag（script line 171/181/191/203）
- Sharpe 排名數值 — RP 0.6025 / BH50 0.5872 / VTR 0.5789 / VT12 0.5658 / BHS 0.4106 ✓
- 損失頻率 / 幅度：VTR 44.2%/-0.615%, BH50 43.8%/-0.622% ✓
- λ breakeven = 1.5159 ≈ 1.52 ✓（VT_Robust）
- PT 參數 α=β=0.88, λ=2.25, reference=zero ✓
- 樣本期 2006-2026, n=5094 ✓
- 數據源 yfinance (SPY/GLD/^VIX) ✓
- λ 區間 1.5-2.5 文獻 cite 合理

## Required corrections (順序固定)

1. 改表格：BH 50/50 排名改 #4、VT 12/VIX 排名改 #3
2. 改 line 5 開頭：「BH 50/50 滑到第四」（或更精確：「跌兩階到第四」）
3. 改 line 54：「VT Robust 比 BH 50/50 多出約 0.014 個百分點（1.4 bps/月）」
4. 改 line 76：「λ=2.25 時 VT Robust 的月均 CE 已高出 BH 50/50 達 0.014 個百分點」
5. 補一句澄清：「VT 12/VIX 從 Sharpe #4 上升到 PT-CE #3，但仍未在任何 λ 下超越 BH 50/50（breakeven λ 不存在）」可在 line 80 附近加上，與既有 `never_preferred` 敘述對齊
