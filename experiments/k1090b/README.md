# K1090b: Nested LOOCV + Expanded Asset Pool for Cross-Asset A4f Meta-Regression

**Question**: K1090 的 cross-asset meta-regression 在修掉 preprocessing / feature-selection leakage、並把 labeled asset pool 從 12 擴到 20 之後，LOOCV 表現還站得住嗎？

**Short answer**: 站得住，但比 K1090 保守很多。  
在 `N=20`、真正 nested 的設定下：

- **Nested Ridge LOOCV R² = 0.151**, RMSE = **2.00**
- **Nested compact OLS LOOCV R² = -0.146**, RMSE = **2.32**
- 對照 K1090 的 post-selection 指標：R² = **0.257**, RMSE = **1.94**

結論是：**K1090 的 0.26 並非純假訊號，但確實被 leakage 與小樣本放大。**
一旦把 feature selection、standardisation、fillna 全搬進 fold 內，最穩的模型變成 **ridge**，而不是原本那條兩變數 compact OLS。

## 1. Why K1090b exists

Codex 對 mile_f8af30d0 / K1090 的 source-level review 指出兩個高優先方法論問題：

1. **Preprocessing leakage**  
   `fillna(col_means)` 與 `StandardScaler.fit_transform()` 在 LOOCV 前先對全樣本 fit。
2. **Post-selection leakage**  
   先用全樣本 LASSO 選特徵，再回頭算 compact OLS 的 LOOCV。

這會讓 `LOOCV R² ≈ 0.26` 偏樂觀。K1090b 的任務就是把這兩個 leakage 拔掉，並且加入更多真實 A4f labels，避免結果只被 `N=12` 支撐。

## 2. Asset pool

### 2.1 Reused from K1090 (12)

SPY, QQQ, EEM, IWM, GLD, USO, FXI, EWZ, EWT, TLT, BTC-USD, 0050.TW

### 2.2 Reused from K1091 (4)

VGK, EWJ, CPER, SLV

### 2.3 New labels run inside K1090b (4)

Recent-OOS A4f-VIX vs GJR labels:

| Ticker | Class | OOS start | n_OOS | DM t | Harvey |
|---|---|---:|---:|---:|---|
| IEF | bonds medium duration | 2022-01-03 | 1110 | **+1.79** | FAIL |
| ETH-USD | crypto | 2022-01-03 | 1617 | **+1.84** | FAIL |
| AAPL | US single stock | 2022-01-03 | 1005 | **+1.44** | FAIL |
| NVDA | US single stock | 2022-01-03 | 1005 | **+1.55** | FAIL |

所以最終 labeled pool = **20 assets**。

## 3. Leakage-safe methodology

### 3.1 Feature window

- Features still use **2018-01-01 .. 2024-12-31** daily data
- 與 K1090 保持同口徑，避免把改善/惡化混進 feature-definition drift

### 3.2 Outer evaluation = leave-one-asset-out

每次拿 1 檔資產當 held-out，其餘 19 檔當 outer-train。

### 3.3 What is nested now

在每個 outer fold 內：

1. 用 **outer-train only** 算缺值平均
2. 用 **outer-train only** fit `StandardScaler`
3. 用 **inner LOOCV on outer-train** 選 ridge / lasso 的 alpha
4. 用 **outer-train only** 做 LASSO feature selection
5. 再用該 fold 選出的特徵 fit compact OLS，預測 held-out asset

這樣 `fillna / scaler / feature selection / alpha tuning` 都不會看到被留出的資產。

## 4. Results

### 4.1 Primary performance

| Model | LOOCV R² | LOOCV RMSE | Comment |
|---|---:|---:|---|
| **Nested Ridge** | **0.151** | **2.00** | 最穩、仍有一些 cross-asset signal |
| Nested Compact OLS | **-0.146** | **2.32** | honest 評估下已不可靠 |
| K1090 compact OLS | 0.257 | 1.94 | 舊版、含 leakage / post-selection optimism |

### 4.2 Interpretation

- **Ridge 還保有正的 LOOCV R²**，表示跨資產 scope signal 並沒有完全消失。
- 但 **0.15 明顯低於 0.26**，代表 K1090 的 headline 應下修。
- **Compact OLS 變負 R²**，表示「少數可解釋特徵 + 小樣本線性式」在 honest nested 評估下不夠穩。

### 4.3 Modal feature set

Outer folds 最常選到的 feature set（20 folds 中 9 次）是：

`currency_usd + log_n_constituents + corr_ret_vix + corr_r2_vix2`

以這組 modal feature 在 full sample 上重估 descriptive OLS：

```text
DM_t ≈ -2.54 + 3.34·currency_usd + 0.31·log_n_constituents
       -1.74·corr_ret_vix + 1.67·corr_r2_vix2
```

但注意：**這組 full-sample OLS 只用來描述方向，不可拿來當 honest OOS 表現。**

### 4.4 Bootstrap CI (modal full-sample OLS)

| Feature | Coef | 95% bootstrap CI |
|---|---:|---:|
| currency_usd | +3.34 | [-0.68, +4.77] |
| log_n_constituents | +0.31 | [-0.30, +0.70] |
| corr_ret_vix | -1.74 | [-4.84, +4.24] |
| corr_r2_vix2 | +1.67 | [-4.81, +14.29] |

所有區間都很寬，顯示 **N=20 仍不足以做強係數推論**。

## 5. Main findings

1. **K1090 的 positive result 沒有完全消失，但明顯被修正。**  
   Honest nested ridge 仍有 `R² ≈ 0.15`，不是零；但比原本 `0.26` 弱很多。

2. **最受傷的是 compact OLS 敘事。**  
   K1090 原本可講成「兩變數公式有 modest OOS explanatory power」；K1090b 後只能講「簡式公式在 honest nested 評估下不穩，ridge 較可信」。

3. **新增 4 檔 recent-OOS labels 全部未過 Harvey。**  
   IEF / ETH-USD / AAPL / NVDA 都落在 `DM t ≈ 1.4~1.8`，支持「A4f signal 並非對所有新資產都強」。

4. **Currency / scope signal 仍在，但樣本異質性上升很快。**  
   一旦把單股、次長債、第二個 crypto 納進來，線性公式的穩定度明顯下降。

## 6. Implication for article / paper framing

K1090 的 general-audience framing 應更新為：

- 可以說「**有一點 scope-prediction 訊號**」
- 不應再說「LOOCV R² 約 0.26 的 OOS 公式」
- 更精確的說法是：
  - `N=20` nested ridge 的 leave-one-asset-out R² 約 **0.15**
  - simple compact formula 在 honest nested 下 **不穩**
  - 這更像 **粗排序工具**，不是可宣稱的穩定預測器

## 7. Limitations

1. 新增 4 檔 labels 的 OOS 採 recent window（2022+）以控制計算量，與 K1091 的長 OOS 不完全同口徑。
2. `IEF` 的 constituent count / HHI 仍是 ETF-level metadata approximation。
3. 單股（AAPL/NVDA）加入後提高了 pool heterogeneity，這對外推是好事，但也讓小樣本線性模型更難穩定。
4. bootstrap CI 仍寬；**K1090b 解的是 leakage，不是小樣本根本問題。**

## 8. Files

```text
experiments/k1090b/
├── README.md
├── k1090b.py
├── k1090b_results.json
├── k1090b_nested_loocv.png
├── k1090b_feature_selection.png
└── k1090b_training_dm_t.png
```

## 9. References

- Engle, Ghysels, and Sohn (2013), *Review of Economics and Statistics*
- Patton (2011), *Journal of Econometrics*
- Varma and Simon (2006), *BMC Bioinformatics*
- Cawley and Talbot (2010), *JMLR*
- Upstream internal experiments: K1090, K1091
