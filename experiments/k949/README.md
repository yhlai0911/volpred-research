# K949: Cross-Market MF-GJR — Is VIX a Global Risk Factor?

## 問題
MF-GJR(VIX) 在 SPY 上穩定勝出（K889, K942）。但 VIX 是美國市場的隱含波動率。它對歐洲和日本市場的波動率預測是否也有效？如果有效，說明 VIX 是全球風險的 sufficient statistic。

## 動機
- K889: MF-GJR(VIX) 在 SPY 上 DM t=-4.42
- K942: 13/13 子樣本全勝
- K916: 跨資產測試 equity OK, crypto 失敗
- 本實驗擴展到跨國市場

## 方法
- **資產**: SPY (US), FEZ (Eurozone STOXX 50), EWG (Germany), EWJ (Japan), EWU (UK)
- **VIX**: ^VIX (CBOE), forward-filled for non-US holidays
- **模型**: GARCH(1,1), GJR(1,1,1), MF-GJR(VIX)
- **Window**: 2000, Refit every 21 days
- **OOS**: 2016-01-01 ~ 2025-12-31 (2513 days)
- **評估**: QLIKE on r², Spearman ρ, DM test (Harvey |t|>3.0)
- **數據來源**: yfinance

## 結果

| Market | QLIKE GARCH | QLIKE GJR | QLIKE MF-GJR | Improve vs GJR | Spearman ρ | DM t (Harvey) | Sig |
|--------|------------|-----------|--------------|----------------|------------|---------------|-----|
| SPY    | 0.761      | 0.737     | 0.655        | 11.1%          | 0.456      | 3.44          | ✓   |
| FEZ    | 1.251      | 1.245     | 1.190        | 4.4%           | 0.335      | 3.84          | ✓   |
| EWG    | 1.249      | 1.237     | 1.186        | 4.1%           | 0.328      | 3.48          | ✓   |
| EWJ    | 0.981      | 0.974     | 0.929        | 4.6%           | 0.303      | 4.22          | ✓   |
| EWU    | 0.965      | 0.958     | 0.884        | 7.7%           | 0.342      | 2.40          | ✗   |

**Significant at Harvey |t|>3.0: 4/5 markets**

### VIX Elasticity (θ₁) across markets
| Market | θ₁    |
|--------|-------|
| SPY    | 1.794 |
| FEZ    | 2.278 |
| EWG    | 2.143 |
| EWJ    | 1.977 |
| EWU    | 2.285 |
| **Mean** | **2.096** |
| **Std**  | **0.188** |

## 結論

**VIX 是全球風險因子。** MF-GJR(VIX) 在 4/5 個國際市場顯著改善波動率預測（Harvey |t|>3.0）。

關鍵發現：
1. **跨市場一致性**: θ₁ 在所有市場都是正值且量級相近（mean=2.10, std=0.19），表示 VIX 對全球波動率有穩定的正向預測力
2. **美國最強**: SPY 的 QLIKE 改善最大（11.1%），Spearman ρ 最高（0.456）
3. **日本最顯著**: EWJ 的 DM t=4.22 是最高的，可能反映日本市場對美國風險情緒的高敏感度
4. **英國例外**: EWU 的 DM t=2.40 未達 Harvey 門檻，但 QLIKE 改善仍有 7.7%，方向正確
5. **θ₁ 跨市場穩定**: 非美市場的 θ₁ 反而比美國更高（~2.1-2.3 vs 1.8），暗示 VIX 對這些市場的 long-run vol 驅動力甚至更強

## 局限
- 所有 ETF 在美國交易所上市，可能已內建美國因子暴露
- 更嚴格的測試應使用各國本地指數和本地 VIX 等價物（VSTOXX, JNIV 等）
- OOS 期間包含 COVID（2020），可能放大全球相關性
- 未控制 USD 匯率效應

## 檔案
- `k949.py` — 實驗腳本
- `k949_results.json` — 完整結果
- `k949_cross_market.png` — 四面板視覺化
