# Codex 24h Review — mile_85502a95 (K1113)

- **Article**: 31 家公司、6 個指標、5 個假設：為什麼「看得到的特徵」無法預測財報當天的波動反應
- **Task**: `paper_review_mile_85502a95`
- **Reviewed**: 2026-06-09 台灣時間
- **Reviewer**: Codex CLI
- **Verdict**: **CONDITIONAL_PASS**

## Summary

這篇文章的主體數字和 `K1113` source 大致對齊：`N=31`、`6` 個 covariates、`5` 個 preregistered hypotheses、主回歸 `R²=0.116`、leakage-free `CV R²=-0.661`、`Tier A=0 / Tier B=31 / Tier C=0` 都和結果檔一致，核心 null result 方向沒有問題。但有兩個方法論聲明超出現有證據：第一，文中把設計寫成可在「財報季前」事先挑公司的規則，然而 `price_volatility`、`log_avg_volume`、`ind_momentum` 是用 **sample end date** 的最後 252 交易日算的，不是對每家 firm 在同一 ex ante 日期凍結的特徵；第二，文中把 `script_sha256_short` 講成 prereg 鎖定證明，但這個 hash 是程式在執行當下對「目前腳本內容」現算再寫進 results，不是獨立時間戳記的凍結證據。

## Numeric verification

下列主張與 source 對齊：

| Draft claim | Source | Match |
|---|---|---|
| 樣本 N = 31 | `primary_regression.n` | ✓ |
| 6 個 covariates、5 個假設 | `pre_registration` | ✓ |
| 樣本內 R² = 0.116 | `primary_regression.r2` | ✓ |
| 5-fold leakage-free CV R² = -0.661 | `primary_regression.cv.cv_r2` | ✓ |
| BH 校正後無存活者 | `hypothesis_verdict.H1_any_bh_survives` | ✓ |
| Tier A = 0 / B = 31 / C = 0 | `tier_classification_summary` | ✓ |
| K1109 ANOVA p = 0.297 | `k1109_benchmark.anova_p` | ✓ |

## Findings

1. **Ex ante selection-rule framing is too strong for the implemented covariates** — [k1113.py](/Users/yhlai0911/Desktop/volpred-research/experiments/k1113/k1113.py:127), [README.md](/Users/yhlai0911/Desktop/volpred-research/experiments/k1113/README.md:244)
   文章把問題寫成「能否在財報季前挑出哪些公司值得特別處理」，但 `price_volatility`、`log_avg_volume`、`ind_momentum` 的實作是 `df.iloc[-252:]`，也就是直接取每檔 cached price 的最後 252 個交易日，而不是為每家 firm 對齊同一個事前決策時點。README 自己也承認這兩個變數是「windows ending at the sample end date」。因此，K1113 支撐的是「在這個 N=31 panel 上，這些樣本末端 market covariates 對 θ₂ 的 cross-sectional 解釋力為 null」，而不是乾淨的「財報季前可部署選股規則失敗」。

2. **The pre-registration evidence chain is overstated** — [k1113.py](/Users/yhlai0911/Desktop/volpred-research/experiments/k1113/k1113.py:776), [README.md](/Users/yhlai0911/Desktop/volpred-research/experiments/k1113/README.md:39)
   文中說「研究設計、變數清單、成功判定標準全部在跑資料之前鎖定」，並把 results JSON 內的 SHA256 當成證據。但 source 實際做的是在 `main()` 執行時讀取 `Path(__file__)`、對當下腳本內容算 hash，再把它寫到 output。這只能證明「results 對應哪個腳本版本」，不能獨立證明「該腳本在執行前已被外部凍結且不可改」。如果要保留 prereg 敘事，建議降級成「研究團隊事前定義了 covariates / hypotheses，results 保存了對應腳本 hash 以利追溯」，不要寫成已完成嚴格審計意義上的 prereg lockbox。

3. **“方法論符合規範” should be narrowed, not generalized** — [README.md](/Users/yhlai0911/Desktop/volpred-research/experiments/k1113/README.md:69), [README.md](/Users/yhlai0911/Desktop/volpred-research/experiments/k1113/README.md:176)
   文章把 K1113 描述成「方法論符合規範、程式碼通過獨立審查的確認性實驗」。後半句基本成立，因為 README 明確記錄了 CV leakage 與 prediction-SE bug 修正；但前半句若被讀成「整個 prereg/ex ante pipeline 完全 audit-clean」就太強。更準確的寫法是：`HC1 OLS`、`BH-FDR`、`bootstrap`、以及修正後的 `leakage-free CV / full prediction interval` 這些統計步驟是合格的；然而 covariate timestamp discipline 與 prereg audit trail 仍有限。

4. **Core null-result narrative itself is appropriately conservative** — [README.md](/Users/yhlai0911/Desktop/volpred-research/experiments/k1113/README.md:90), [README.md](/Users/yhlai0911/Desktop/volpred-research/experiments/k1113/README.md:142)
   值得保留的是，文章沒有把 null result 說成「永遠不存在可預測性」，而是限定在這 31 家公司、這 6 個公開市場指標、這個 panel 設計下看不到穩定信號。`CV R² < 0` 與 `Tier A = 0` 的解讀也沒有 overclaim，這部分敘事邊界是守住的。

## Lookahead audit

- PASS — K1113 不是交易回測，不存在 `signal at t` 乘 `return at t` 的典型 same-day lookahead 形態。
- CAUTION — 雖然沒有同日交易 leakage，但 covariates 的時間戳 discipline 不夠嚴格：`_compute_vol_momentum_volume()` 直接取每檔資料最後 252 日，而非對齊共同 decision date，見 [k1113.py](/Users/yhlai0911/Desktop/volpred-research/experiments/k1113/k1113.py:127)。

## Recommended tweaks

1. 把「在財報季前就挑出哪些公司值得特別處理」改成較弱版本，例如「在這個 N=31 firm panel 上，樣本末端可觀測市場特徵無法解釋 θ₂ 的 cross-sectional 差異」。
2. 把 prereg 段落改成可審計的真實強度：說明 `results.json` 記錄了對應 script hash 以利追溯，但這不是外部時間戳的嚴格 prereg lock evidence。
3. 若未來要把這條線升級成真正的 firm-selection rule，需為每家公司明確定義共同 ex ante feature date，重算 `price_volatility` / `volume` / `momentum` / `analyst_count`，避免 sample-end snapshot 混入。
