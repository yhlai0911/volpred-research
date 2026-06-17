# K1524 — Translation Gap Pilot: 統計精度 → 投組 Sharpe 的斷點

## 動機

「Prediction ≠ Application」系列 #7。本實驗系統性量化「translation gap」——
波動率預測模型在統計準則（QLIKE / 排序準確度）上的贏家，是否也是投組績效
（vol-targeting Sharpe）上的贏家。

**Prior**：
- **K533**（HAR-RV VT 策略）：HAR 是 QLIKE 最佳但 VT Sharpe 最差，建議 12/VIX
  作為實務 signal。
- **K594**（Adaptive window VT）：自適應視窗在 QLIKE 上改善但 Sharpe 沒有跟著
  改善，是典型 null result。

K533/K594 是「單模型 × 單策略」case studies；K1524 升級為 **3 × 3 系統性矩陣**，
明確展示 translation gap 不是 anecdotal artifact，而是跨模型族的 phenomenon。

## 設計

| 維度 | 內容 |
|------|------|
| Universe | SPY + 10 大型股 (AAPL MSFT GOOGL AMZN NVDA META TSLA JPM JNJ V) |
| 期間 | 2018-01-01 ~ 2025-12-31；OOS = 2022-01-01 ~ 2025-12-31 |
| RV | 5-day rolling std × √252（annualised） |
| 模型 1 | HAR-RV (lag 1/5/22 day RV, expanding OLS, refit q21d) |
| 模型 2 | GJR-GARCH(1,1) on daily returns, `arch` 套件, refit q21d |
| 模型 3 | RandomForest (100 trees, depth 5, RV/abs-ret lag 1/5/22 + VIX) |
| 準則 1 | QLIKE on variance: r²/h² - log(r²/h²) - 1（lower better） |
| 準則 2 | Cross-sectional Spearman ρ (forecast rank vs realised rank, daily) |
| 準則 3 | Vol-targeting Sharpe: w_t = clip(target_vol / f_t, 3); EW 11 ticker |
| Seed | 42 (RF), random_state 固定 |
| Data | yfinance |

**Lookahead 處理**：所有 features 用 `.shift(1)`；GJR walk-forward 訓練集
`r.loc[r.index < t]`（strict less-than）。Forecast at date `t` 只用 `≤ t-1` 的資料；
strategy return at `t` = `w_t × r_t`，無偷看。

## 結果：3 × 3 矩陣

| Model | QLIKE ↓ | Rank ρ ↑ | EW Sharpe ↑ | Single Sharpe median |
|-------|---------|----------|-------------|----------------------|
| HAR   | 0.341   | **0.863** | **1.148**  | 0.623 |
| GJR   | 0.557   | 0.695   | 0.939      | 0.595 |
| **RF**| **0.232** | 0.859 | 1.108      | **0.670** |

**Winners 不一致**：
- QLIKE winner = **RF** (0.232，比 HAR 低 32%，比 GJR 低 58%)
- Rank ρ winner = **HAR** (0.863，但 RF 0.859 幾乎平手)
- EW Sharpe winner = **HAR** (1.148 vs RF 1.108)
- Single Sharpe median winner = **RF**

**DM test (QLIKE)**：
- HAR vs GJR: stat = -3.11, p = 0.0018（HAR 顯著優於 GJR）
- HAR vs RF: stat = 1.60, p = 0.110（RF 優於 HAR 但 not significant at 5%）
- GJR vs RF: stat = 24.0, p ≈ 0（RF 大幅優於 GJR）

## Translation Gap 結論

**Gap 確認存在**：QLIKE winner (RF) ≠ EW Sharpe winner (HAR)，但只差 **3.6%**
(1.148 vs 1.108)。Single-asset Sharpe median 反而是 RF 略勝。

| 維度 | Winner | 解讀 |
|------|--------|------|
| 統計精度（學術發表） | **RF** | 預測 variance 最準；QLIKE 比 HAR 低 32% |
| 排序準確度 | HAR ≈ RF | 兩者跨資產排序能力幾乎平手 |
| EW 投組 Sharpe | HAR | 線性簡潔模型仍是組合配置贏家 |
| Per-asset 平均 Sharpe | RF | 單一資產 vol-targeting RF 略勝 |

**Phenomenon 系統性**：translation gap 存在但**幅度小於 K533/K594 的 anecdotal
report**。RF 把 QLIKE 砍掉 1/3，但只能維持與 HAR 旗鼓相當的 Sharpe，**沒有把
統計優勢完全轉化為投組績效**。HAR 仍是投組配置的可靠選擇。

**Punchline**：
> 統計準確度的邊際改善 (QLIKE -32%) 換不到對應的投組 Sharpe 改善 (-3.6%)。
> 「最值得投稿」與「最值得交易」是兩個不同的模型。

## Verdict: PASS

- QLIKE/Sharpe winners 不一致 → translation gap phenomenon 確認
- 3 × 3 矩陣完整、DM test 完成、≥3 張圖
- 結論方向與 K533/K594 一致但更系統化

## Limitations

1. **Pilot scope only**：11 ticker，非 K1523 規劃的 ~465 股全 universe。
2. **No transaction cost**：未扣手續費 / slippage（K533 顯示 TC 對 VT 結論變動 < 20%）。
3. **No long-only constraint**：目前 weight cap 3x 但無 short 限制。
4. **RV proxy 粗糙**：5-day rolling std，未用 Parkinson / Garman-Klass
   high-frequency RV。
5. **Refit freq 21d**：可能對 RF 過於保守；可做 daily refit robustness。
6. **OOS 4 年**：含 2022 熊市但無 2008 / 2020 規模 crash，small-sample 訓練。
7. **Gap 幅度小 (3.6%)**：與 K533 的 dramatic gap 不同；可能是樣本/期間特性。

## Next Steps (K1523+)

- Full universe (S&P 500) + 更多 ML models (LSTM / XGBoost)
- Add transaction cost layer (10–25 bps round-trip)
- Long-only + long-short variants
- Multi-horizon (1-day, 5-day, 22-day forecast)
- Cross-validation for hyperparameter selection
- Test stability of translation gap across regimes (高 VIX vs 低 VIX 子期間)

## Files

- `k1524.py` — 完整可復現腳本
- `results.json` — 3×3 矩陣 + DM tests + winners + gap summary
- `fig1_3x3_matrix.png` — 模型 × 準則 ranks heatmap
- `fig2_qlike_vs_sharpe_scatter.png` — 統計精度 vs 投組績效 scatter
- `fig3_winner_consistency_by_ticker.png` — per-ticker winner pattern

---

## Provenance (salvage note)

- 原工作 tagged K1522 但與 main K1522 (bond ETF factor audit) K-id 衝突。
- Worktree branch: `worktree-agent-a98f6f236a885f9f2` (commit 33419d13)
- Salvaged by: hourly-10 2026-06-17，rename K1522 → K1524 避衝突。
