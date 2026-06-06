# Codex 24h-rule review — mile_bcdd203c (K1056)

- **Article**: 五個市場時代、從沒輸過：A4f 波動率預測的跨時間穩健性驗證
- **Published**: 2026-06-06T01:01:06Z
- **Reviewed**: 2026-06-06T02:11Z（hourly-10 fire）
- **Reviewer**: Codex CLI 0.135.0（ChatGPT auth）
- **Scope**: source-code-level audit per `.claude/rules/agent-delegation.md` K1018 24h-rule
- **Sources read**: `experiments/k1056/k1056.py` (847 lines), `experiments/k1056/k1056_results.json`, article content via `storage/reports/feed.json`

## Verdict: **CONDITIONAL_PASS**

主結論成立、數字皆可在 results.json 找到對應，但有 3 個 source-code-level 問題阻止直接 PASS。文章 5/5 directional 結果在這些問題下仍 robust，但精確 magnitudes 與口徑表達需收緊。

## 面向逐項 finding

| 面向 | 狀態 | 摘要 |
|------|------|------|
| [A] Lookahead | ⚠️ partial | `τ_t` 用 `VIX_{t-1}²` 正確。但 A4f 遞推 `u_prev = r_{t-1} / sqrt(τ_t)` 與檔頭定義 `u_t = r_t / sqrt(τ_t)` 不一致 — 應使用 `τ_{t-1}`（state alignment bug）。 |
| [B] DM test | ⚠️ nomenclature | `dm_test()` 實作 plain DM + Newey-West HAC，非 Harvey-Leybourne-Newbold small-sample correction。文章用「DM 檢驗 t 統計量達 -6.59，遠超過學術界公認的嚴格門檻」帶入 Harvey 隱喻 — 數字成立但口徑需明示。 |
| [C] OOS refit hygiene | ✅ clean | refit window 嚴格只取 `[train_start:abs_idx]`，window=2000, refit_every=63 分隔乾淨。 |
| [D] QLIKE 計算 | ✅ correct | `QLIKE = mean(a/f − log(a/f) − 1)`，用 `actual=r², predicted=σ²` 與 Patton 2011 proxy-robust 一致。 |
| [E] Subperiod split | ✅ correct | 5 段不重疊（P1–P5），各 `n_obs` 加總=2828 = `full_oos.n_valid`。但 `n_oos=2834`（raw）vs `n_valid=2828`（effective）需文章釐清。 |
| [F] VIX bucket | ⚠️ contemp | bucket 用 `VIX_t` 而非 `VIX_{t-1}` — 屬於 ex post conditional stratification，不能解讀為「事前知道 VIX 高就能切換」。 |
| [G] Statistical overclaim | ⚠️ mild | P3 在文中標「弱顯著」(`dm_t=-2.66, p=0.0081, harvey_significant=false`)，與「Harvey |t|>3」全文口徑形成混用。 |
| [H] Article numerical accuracy | ✅ verified | 5/5 win, binomial p=0.03125, full OOS n=2828 / t=-6.59 / 6.27%, VIX bucket 9.0/1.0/13.7/25.9, θ₁ 45 次全正 — 全部對得上 results.json。 |

## Specific bugs

### Bug 1 — A4f residual standardization misalignment（最關鍵）
- **位置**: `experiments/k1056/k1056.py` lines 237, 353, 377
- **問題**: `u_prev = r_prev / sqrt(τ_t)` 應該是 `r_prev / sqrt(τ_{t-1})`。`tau_prev` 在 line 358 有寫但未在 forecast block 使用。
- **影響**: A4f 量化值會略有偏移，但 5/5 directional 結果幾乎不會翻盤（GJR 同樣遞推、相對排名不變）。
- **建議**: 顯式 two-step state update — 先用 `tau_prev` 標準化得到 `u_{t-1}`，更新 `g_t`，再以 `tau_t` 合成 `σ²_t = tau_t * g_t`，最後 `tau_prev = tau_t`。

### Bug 2 — DM nomenclature
- **位置**: `src/volpred/stats/model_evaluation.py:83`, `k1056.py:411`
- **問題**: 程式只做 plain DM + HAC，但 script print 與文章口徑暗示 Harvey-corrected。
- **建議**: 二選一 — (a) 補 Harvey-Leybourne-Newbold small-sample correction；(b) 全文改為「plain DM HAC，另採 Harvey et al. (2016) `|t|>3` 多重比較**經驗門檻**」。

### Bug 3 — VIX regime ex post
- **位置**: `k1056.py:291, 492`
- **問題**: bucket 用 contemporaneous `VIX_t` → 屬 ex post stratification。
- **建議**: 改用 `vix[abs_idx - 1]`；若保留現寫法，文章需明示「ex post conditional split，非可預測 regime switch」。

## 對文章的影響評估

- **不需立即下架**：所有數字可從 results.json 對得上，directional 結論 robust。
- **建議補一條 footnote / methodology 補述**：
  > 「DM 檢驗為 plain Diebold-Mariano + Newey-West HAC；`|t|>3` 為 Harvey et al. (2016) 提出的多重比較經驗門檻。VIX 分組為 ex post conditional stratification（用 contemporaneous VIX 分桶後比較 QLIKE），非可預測 regime switch。」
- **建議排 followup task**：重跑 K1056b 使用修正後 `u_prev` 對齊，比對 magnitudes 是否變動 >5%。若變動小（預期 <2%），原文章標 verified；若變動大，需更新數字。

## Cross-paper 影響

`u_prev` τ-alignment 模式可能在 Paper 9 的其他 A4f 實驗（K988, K988b, K994, K1024, K1033）重複出現。建議：
- 排 audit task：grep `u_prev` / `tau_prev` 在 experiments/k* 各 A4f 腳本，確認對齊一致。
- 若全 series 都有此 misalignment，影響是 systematic 而非 K1056-only，需 Paper 9 narrative 同步補述。

## Endorsement

- 5 段時間切分合理，2024-07~2026-04 第 5 段把樣本延伸到最近期是很好的 stress test。
- Subperiod split + VIX regime split 雙視角（時間 vs 環境）讓 robustness 論述完整。
- 5/5 binomial p=0.03125 是 honest 的小樣本檢定，比硬上 Harvey 在 5 個檢定上更嚴謹。

## 結論

CONDITIONAL_PASS — 文章可繼續展示，但 24h 內補上 methodology footnote；同時排 K1056b refit 驗證 magnitudes 是否 robust to τ-alignment fix。
