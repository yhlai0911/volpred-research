# K1660 代碼審查紀錄

## Reviewer source
- **Primary path（Codex CLI）不可用**：2026-07-08 送 `codex exec`（gpt-5.5, xhigh）審查時回
  `ERROR: You've hit your usage limit ... try again at Jul 11th, 2026`（ChatGPT auth 額度用盡，7/11 恢復）。
- **依 `.claude/rules/experiments.md` fallback**：改派 `feature-dev:code-reviewer` subagent 做 independent
  fresh-context review（K1259/K1261/K1262 已走過此 path）。**Reviewer source = code-reviewer subagent fallback**。
- Bar 不變：CONDITIONAL_PASS 以上才可寫 knowledge.json。**Codex 恢復後應以 primary-path 二次驗證**再立 closure
  （K1259 教訓：subagent PASS ≠ primary-path Codex PASS）。

## VERDICT: PASS
（feature-dev:code-reviewer, 2026-07-08, fresh context, read-only, 完整讀取 457 行）

reviewer 未發現任何 ≥80 信心的 lookahead bug 或會誇大/低估 gated vs always-VT 差異的錯誤。核心因果鏈
（signal 計算 → shift(1) → 賺 ret → 扣 cost）正確，HAC / block bootstrap 實作正確，**NULL 結論可信、非 bug 造成**。

## 逐項通過摘要
1. **LOOKAHEAD（通過）**：`pos = exposure.shift(1)`（decision 用 t-1、賺 ret_t）；`turnover = pos.diff().abs()`
   與 shift 後 pos 對齊；`high_regime()` 的 rolling-quantile threshold 與 `realized_vol`/`ewma_vol` 皆只用 up-to-t
   資料，整條 exposure 一併 shift；`valid` mask 同步套用 always_vt / gated 確保兩序列同期。
2. **公平比較（通過）**：always_vt 與 gated 共用同一 `vol_fc` / `cap` / `cost_bps` / shift；gated 只差
   `exp_vt.where(regime>0.5, 1.0)`。
3. **成本模型（通過）**：`net = gross - (bps/1e4)*turnover`，單邊 |Δpos|，標準。
4. **統計（通過）**：Newey-West Bartlett kernel HAC 變異數公式正確；circular block bootstrap 對 a、b **同一組
   rows** joint resample 保留 cross-correlation、seed=42 可重現；符號慣例 `diff = gated - always_vt` 無 sign-flip。
5. **資料清洗（通過）**：`clean_returns()` 僅對 0050.TW 用固定門檻 |ret|>0.11（台股漲跌幅限制經濟依據），
   非依樣本調整的 outlier-fishing，無 survivorship/lookahead。
6. **Metrics（通過）**：CAGR/MDD/Calmar/Sharpe/turnover 公式標準無偏誤。

## reviewer 次要觀察（信心<80，已於修訂處理 3/4）
- ✅ 已修：`buy_hold` 未套 valid mask → 現三策略共用同一 valid mask，完全同期比較（buy_hold 參考數字微調）。
- ✅ 已修：`regime_frac_high` 用未 shift 的 regime → 改 `.shift(1)` 對齊實際驅動 pos_t 的 regime_{t-1}（純報表欄位）。
- ✅ 已修：bootstrap `_sharpe()` ddof=0 vs `Perf.sharpe` ddof=1 → 統一 ddof=1。
- ⓘ 未改（無影響）：`net.dropna()` 因 pos.diff 首兩列 NaN 多丟一天，兩策略對稱受影響不偏頗。

以上修訂後重跑，核心 gated vs always-VT 檢定數字**完全不變**（該 idx 本已對齊），僅 buy_hold 參考行同期化。
