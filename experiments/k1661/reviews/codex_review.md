# K1661 代碼審查

- **Reviewer source**: `feature-dev:code-reviewer` subagent（**Codex fallback** — Codex CLI 額度用盡，2026-07-11 恢復）
- **審查日期**: 2026-07-08
- **VERDICT**: **PASS**（本專案 bar：CONDITIONAL_PASS 以上才可寫 knowledge）
- **建議 knowledge provenance**: 依 `.claude/rules/experiments.md` **K1259 教訓**「Subagent fallback PASS ≠ primary-path Codex PASS」，主線程寫 `knowledge.json` 時建議先以 `CONDITIONAL_PASS`-等級記錄、`reviewer_source=code-reviewer subagent fallback`，待 2026-07-11 Codex 額度恢復後以 **primary-path Codex** 二審通過再升級為完整 PASS closure。

## 四類 hard-fail 逐項核實（皆未發現）

### 1. Lookahead — 未發現 ✅
- `build_design()`：`RV_d/RV_w/RV_m/sqrtRQ/sqrtRQ_sm` 全部 `.shift(1)` / `rolling().shift(1)`，只用 t-1 之前資訊；`y=rv`（未 shift）為 target。
- `rolling_oos()`：`tr = d.iloc[i-window:i]`、`te = d.iloc[i:i+1]`，`d` 依日期升冪，訓練窗所有列 target date 嚴格早於預測日，滿足 `target_end < forecast_origin`（h=1）。
- `stats_z`（standardize 統計）用訓練窗 `tr[c]` 算出，未用測試窗/未來資訊。
- `n_design`（SPY 4129 = 4151−22）、`n_oos`（3129 = 4129−1000）與 script 邏輯精確吻合，佐證非手改結果。

### 2. QLIKE 方向 — 正確 ✅
`qlike_pointwise()`：`r = a/f; return r - log(r) - 1`，canonical actual-over-predicted，未反向。

### 3. DM-HLN 實作 — 正確（代數驗證通過）✅
`dm_hln()`：`V=gamma0`（h=1 迴圈不執行）、`dm=dbar/sqrt(V/T)`、HLN 因子 `sqrt((T+1-2h+h(h-1)/T)/T)`、Student-t(df=T-1)，與 Harvey-Leybourne-Newbold (1997) 一致。代數驗證：h=1 時 `DM_HLN = DM(code) × sqrt((T-1)/T) = t_std`（population γ0 × HLN 因子精確等價標準配對 t 檢定）。方向約定 `d = loss_HARQ - loss_HAR`（`dm_hln(HARQ, HAR)`），`< -3.0`→HARQ 顯著優、`> 3.0`→顯著劣，與 README 一致無誤植。

### 4. Baseline 動手腳 — 未發現 ✅
`insanity_filter()` 對**所有模型**（含 HAR）無差別套用，bounds 取自同一 `ytr`。四模型共用同一 `d`/`window`/迴圈，test set（`dates`/`yt`）完全相同，僅 `yp` 因模型不同 — 公平比較。

## 其他重點確認
- **HARQ spec**：`make_X()` HARQ = HAR + `z(sqrtRQ)*RV_d`，等價 `(β_d+β_dQ√RQ)·RV_d`；HARQ-F 交互到 weekly/monthly，與 BPQ(2016) HARQ-F 用同一 lag-1 √RQ 交互三項的定義一致。
- **standardize forecast-neutrality**：代數驗證 `z*RV_d = c/s − (m/s)*RV_d`，因 `RV_d` 已在設計矩陣，為既有欄位空間內可逆線性變換，OLS fitted/forecast 值不變 — README 宣稱屬實。
- **結論效力**：Harvey `|t|>3` 為 canonical gate，三資產 t（0.49/0.71/0.54）遠低 → 正確判 `NULL`；README 明標「3/3 同向僅 suggestive（binomial p=0.125）」「不可誇大為顯著傷害」，未過度宣稱。跨資產未做 iid pooling（K1355 遵守）。HARQ-F TWII t=2.615(p=0.009) 正確標注「未達 Harvey 3」，未混淆顯著性層級。

## Caveats（可接受，供記錄）
1. **HARQ-F 命名**：同一 √RQ_{t-1} 交互三項為 BPQ HARQ-F 標準做法，非 bug。
2. **Dead-code hygiene**（reviewer 標出，已於審查後清理）：`MIN_TRAIN` 未使用 → 已移除；`insanity_filter` 第二 return 不可達 → 已簡化為 `return pred`。**清理後重跑數值完全不變**（HAR/HARQ/HARQ-F/HARQ-smooth QLIKE、DM-HLN t 逐位一致）。
3. **primary-path Codex 二審**：待 2026-07-11 額度恢復後補（K1259 規則）。

## 結論
方法論嚴謹：lookahead 防護到位、QLIKE 方向正確、DM-HLN 數學驗證通過、HAR/HARQ 家族公平比較、standardize forecast-neutral 屬實、NULL 結論誠實。無任何 lookahead / QLIKE 反向 / DM-HLN 錯誤 / baseline 動手腳。**VERDICT: PASS**（作為最終 closure 寫 knowledge.json 前，建議 7/11 Codex primary-path 複驗）。
