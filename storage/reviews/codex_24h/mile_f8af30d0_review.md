# Codex 24h Review — mile_f8af30d0 (K1090)

- **Article**: 看到一個新資產，能不能先猜這套波動率方法值不值得跑？
- **Draft source**: `storage/reports/feed.json` (`mile_f8af30d0`)
- **Task**: `paper_review_mile_f8af30d0`
- **Reviewed**: 2026-06-08 台灣時間
- **Reviewer**: Codex CLI (codex-cli 0.137.0, ChatGPT auth, gpt-5.4 medium)
- **Verdict**: **CONDITIONAL_PASS**

## 結論摘要

文章的核心訊息成立，主要數字也與 `k1090_results.json` 對得上（54% R² / 0.26 LOOCV R² / 1.94 LOOCV RMSE 等與 `ols_compact` 一致）。但方法論的包裝過度：把 leave-one-asset-out 橫截面 LOOCV 稱作「out-of-sample R²」，且 LOOCV 之前的 LASSO 特徵選擇與 preprocessing (fillna + StandardScaler) 都在全 12 資產上做，是典型的 post-selection 與 preprocessing leakage，使 LOOCV 數字偏樂觀。對 general audience 而言，這層含糊容易讓讀者高估「先猜哪個資產該跑」的可靠度。

不需要整體退稿，但建議在文章中段補一段「方法局限」短註，明說：(1) 這是 12 資產內輪流留一的橫截面 CV，不是時間 OOS；(2) 12 樣本下的單一非 USD 資產（0050.TW）幾乎決定 currency_usd 係數；(3) n=12 + 多重比較，邊際 p≈0.056 不可稱顯著。

## Numeric verification

| Claim | Source | Match |
|---|---|---|
| R² ≈ 54%（ols_compact） | `ols_compact.r2=0.5410` | ✓ |
| LOOCV R² ≈ 0.26 | `ols_compact.loocv_r2=0.2576` | ✓ |
| LOOCV RMSE ≈ 1.94 | `ols_compact.loocv_rmse=1.9415` | ✓ |
| Currency USD 為正向特徵、邊際顯著 | coef `currency_usd>0`, p≈0.056 | ✓ (邊際) |
| corr_ret_vix 係數方向 | `coef<0` | ✓ |
| 6 個 ranked 新資產建議 | `new_asset_predictions` (`SLV/HG/EWG/...`) | ✓ |

## Findings

1. **Post-selection LOOCV leakage（高優）** — `experiments/k1090/k1090.py:255,258`
   - LASSO 在全 12 資產 fit 後選 compact features，再用相同 12 資產做 OLS LOOCV。
   - 影響：LOOCV R²/RMSE 是「post-selection」指標，本質偏樂觀。
   - 建議：(a) 文章補一句「post-selection LOOCV，數字偏樂觀」；(b) 後續實驗做 nested LOOCV（每 fold 自行做 LASSO + OLS）。

2. **Preprocessing leakage（中優）** — `experiments/k1090/k1090.py:208,215,225`
   - `fillna(col_means)` 與 `StandardScaler.fit_transform` 在 LOOCV 切分前用全 12 資產 fit，held-out asset 資訊已滲入。
   - 影響：與 finding 1 同方向，但量級較小。
   - 建議：後續實驗 nested LOOCV fold 內各自 fit preprocessing。

3. **"Out-of-sample R²" overclaim（高優）** — article line ~52
   - 「out-of-sample R²」對 general audience 暗示「未見資產」的外推能力，但實際只是「12 資產內輪流留一」。
   - 建議：改寫成「12 資產內輪流留一的橫截面 LOOCV R²」或「leave-one-asset-out 樣本內驗證」，避免「OOS」字眼。

4. **邊際顯著 + multiple comparisons（中優）** — article line ~27-44
   - currency_usd p≈0.056 屬邊際，且單一非 USD 資產（0050.TW）幾乎獨佔識別。
   - n=12 下做多特徵迴歸 + 多重比較，不可宣稱「統計顯著」。
   - 建議：補一句「n=12、單一 TWD case，多重比較下不可稱顯著」。

5. **方法論透明度（中優）** — 整體
   - General audience 文章在 IS/OOS 區分上應更明確；補一個「方法局限」小段（3-5 行）就能消化 finding 1+3+4。

## Recommendation

CONDITIONAL_PASS — 數字無造假，問題是 framing/包裝過度。修法：

1. **本次（最小修）**：在文章中段 / 結尾補「方法局限」段（3-5 行），明寫 (i) LOOCV 是 12 資產內輪流留一、不是時間 OOS；(ii) 特徵選擇與 preprocessing 用全樣本 fit、屬 post-selection 偏樂觀；(iii) n=12 + 邊際 p、不可稱顯著。
2. **後續實驗（K1090b）**：跑 nested LOOCV + 擴大資產池（≥20）+ bootstrap CI 重估，看 LOOCV R² 是否仍在 0.26 同量級。

## 任務歸檔

- knowledge.json: `paper_review_mile_f8af30d0_codex_2026_06_08` (CONDITIONAL_PASS / reviewer=Codex)
- task: `paper_review_mile_f8af30d0` (succeeded)
- followup task suggested: `research_k1090b_nested_loocv` (P3, experiment)
