# Codex primary-path review — K1257 / K1258 BMA remediation (round 3)

Repo root: `/Users/yhlai0911/volpred-research`

## 你要裁決什麼

K1257（standard BMA）與 K1258（forgetting-factor BMA）在 2026-07-19 做了 remediation 全期重跑，
修的是你（Codex v2）先前提的兩個 MAJOR：

- **MAJOR-1** invalid-model posterior contamination（forecast 無效的日子，該模型的 stale prior 仍留在後驗裡）
- **MAJOR-2** 未收斂的 fit 仍被拿去產生預測

2026-07-20 的內部收件驗證判 **CONDITIONAL PASS**：兩個 MAJOR 在程式碼層面確實修好，但修法**新引入一個報告層
的樣本錯配**，已於 2026-07-20 修正並重跑（本次送審的就是修正後版本）。

## 待審檔案（primary path，逐行看，不要只讀 README）

- `experiments/k1257/k1257_bma_volatility.py`（重點：forecast loop 的 valid mask、posterior 更新、
  `common_mask` / `_mean_common` 的 headline 聚合、`dm_harvey`）
- `experiments/k1257/k1257_results.json`、`experiments/k1257/README.md`
- `experiments/k1258/k1258_forgetting_factor_bma.py`（重點：`ffbma_posterior` 的 `log_floor=-700`、
  cache 的 `posterior_semantics_version` 判讀、`verdict_h4`）
- `experiments/k1258/k1258_results.json`、`experiments/k1258/README.md`
- 舊審查意見：`experiments/k1257/codex_review.md`、`experiments/k1258/codex_review.md`、
  `experiments/k1258/codex_review_v2.md`

## 五個必答重點（每條給檔案:行號證據，禁憑印象）

1. **樣本對齊是否真的修好。** 舊版 headline 用 `np.nanmean` 逐序列各算各的：SPY 的 GJR-t 因為一次
   non-converged refit 掉了 63 天（2024-04-05 → 2024-07-05），分母 1518，而 BMA/Equal 是 1581，
   於是 BMA−GJR-t 被灌水 81%（報 -0.09165，對齊後 -0.05060），而同一句 `conclusions` 引用的
   Harvey t=-3.17 對應的 d_bar 其實是 -0.0506 —— 一句話裡兩個樣本。新版改用
   `common_mask`（BMA∩Equal∩GJR-t 共同有效日）算 headline，並保留 `qlike_own_sample`。
   **請獨立從 `experiments/k1258/forecasts_SPY.parquet` 重算共同 1518 日的 BMA QLIKE**，
   驗證新 artifact 的 `bma_qlike ≈ -8.186393` 與 `n_common_sample == 1518`，並確認
   `regime_qlike` 也已對齊。

2. **確認 DM 檢定本身從未被污染。** `dm_harvey` 用 `valid = np.isfinite(d)`，逐日 loss 差自動落在共同
   有效日，所以 H1/H2/H3 的 verdict 不受樣本錯配影響。請明確裁決「錯配只影響 headline 數字、不影響
   verdict」，避免把嚴重度誤判成翻案級 —— 但如果你不同意這個判斷，請直接說並給證據。

3. **-inf 吸收態是否為可接受的 BMA 語意。** MAJOR-1 的修法把 invalid 模型設 `-inf`，下一日
   `-inf + lp` 仍是 -inf → 該模型**永不復活**，即使後續 refit 收斂。SPY GJR_t 的
   `final_weights` 因此是精確 `0.0`（K1258 因 `log_floor=-700` 則是 8.47e-305 — 兩支實驗語意不一致）。
   本例影響 negligible（drop 前該模型權重已 ~3.4e-06），已在 JSON 的 `posterior_semantics` 與 README
   Limitations 揭露。請裁決：揭露是否足夠，還是必須改成「當日排除、隔日沿用上次有效後驗」？
   這是修法的副作用，你前一輪沒看過。

4. **README ↔ JSON 每個數字交叉檢查。** 已知既有 debt（04-29 你提過、本輪才處理或仍未處理的）：
   K1257 README 的 7 models / HAR-RV / Realized GARCH 描述與實作（6 models、`HAR_ABS`、`A4f_IV2`、
   GLD 用 `^GVZ`）不符；README「~500 days」不是計算出來的指標（effective n_models 仍未計算）；
   K1258 README「BMA-family ensemble is structurally limited」超出 3 資產 × 5 λ × 單一 OOS 窗的證據。
   請標記「已修 / 未修」而非重新發現。

5. **「結論沒變」是否可信。** H1 PARTIAL / H2 FAIL / H3 FAIL（K1257）與 H1 FAIL / H2 PASS / H3 PASS
   （K1258）在 remediation 前後皆未改變。支持「污染影響本來就小、但修法確實生效」的反證是：
   GLD 與 0050.TW 所有指標 Δ=0；SPY GJR-t baseline Δ=+0.039、DM t Δ=+0.22、
   `final_weights.GJR_t` 1.8e-09 → 0.0。請獨立判斷這是否足以排除「修法根本沒跑到新分支」，
   不要接受口頭聲明。

## 額外請一併看

- 多重比較：K1257 H1 = 3 資產同時檢定；K1258 H1 = 3 資產 × 4 個 λ = 12 cells，無 Bonferroni/BH。
  Harvey |t|>3（≈ p<0.003）是否足以當 de-facto 保護？README 是否該明講？
- `invalid_forecast_days` 與 `dropped_model_days` 依構造恆等（同一 if 分支內同時 +1），是否應合併或
  改成真正獨立的兩個訊號。
- `final_weights` 中 `0.0`（被 drop 而永久出局）與 `1e-30`（likelihood 輸掉）語意不同但無欄位區分。
- 兩個實驗目錄都缺 `review_verdict.json`（`scripts/experiment_gates.py` certification gate 會判 uncertified）。

## 輸出格式（verdict 檔第一行必須是這個 token）

```
VERDICT: PASS | CONDITIONAL PASS | FAIL
```

之後依序給：每個必答重點的裁決 + 證據、blocking issues（SEVERE/MAJOR/MINOR + 最小修復動作）、
以及「若 CONDITIONAL PASS，放行需要滿足的最小條件清單」。
