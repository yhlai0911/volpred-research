# K1421 — HAR-Quantile Cross-Asset Robustness on Commodities (GLD / USO / UNG)

## 動機
K1403 已驗證 HAR-Quantile pipeline 在 equity proxy (QQQ) + bond (TLT) + 黃金 (GLD) 上的表現（DM NULL / tail usable）。K1421 把同樣 pipeline 推到 commodity ETF 三檔，**檢驗能源類 (USO 油 / UNG 天然氣) 與貴金屬 (GLD) 是否表現出更強的 quantile asymmetry**，從而支持「asset-class-conditional quantile model selection」這個 design claim。

假說（不可造假）：
- USO/UNG 的 upper-tail/lower-tail pinball ratio asymmetry > GLD > SPY baseline
- ≥1/3 commodity 出現 DM(q05) sig POS — 代表 tail forecasting 在能源類有 incremental value

Null 結果可接受（K1403 已是 NULL，K1421 找的是 cross-class differentiation 的證據）。

## 方法

1. **資料**：yfinance OHLC daily，2012-01-03 起，IS 至 2020-12-31，OOS 2021-01-04 起。Garman-Klass (1980) 已實現波動率 proxy。
2. **模型**：HAR-RV (Corsi 2009) lag-{d, w, m} OLS baseline + Koenker-Bassett 1978 QuantReg at τ ∈ {0.05, 0.50, 0.95}。fixed-origin（單次 IS fit）。
3. **指標**：per-asset Pinball loss、Kupiec UC（單尾 q05/q95）、Diebold-Mariano with Harvey HLN 小樣本校正 vs OLS。
4. **跨資產 joint test**：Politis-Romano 1994 stationary bootstrap, mean block L = ⌈n^{1/3}⌉, n_boot=1000, seed=42。檢驗 mean(OLS - QR pinball) 在 3 個 commodity 跨資產池中 > 0（QR 改善 OLS）。
5. **Asymmetry metric**：`(p95 / p50) - (p05 / p50)`，越偏離 0 越不對稱；正號代表上尾更難預測（vol explosions）。

## 成功 / verdict 邏輯（pre-registered）

- **PASS**：≥1/3 assets DM(q05) p<0.10 + 正向 stat **且** joint bootstrap p_one_sided<0.10
- **CONDITIONAL_PASS**：≥1/3 assets DM 任一 quantile sig POS，但 joint NS
- **DESCRIPTIVE_ASYMMETRY**：無 DM 改善，但 ≥2/3 commodities |asymmetry| > 0.75
- **NULL**：以上皆無

## 防錯 / 研究誠實 checklist

- `signal.shift(1)` 已內建於 `build_har_panel`（rv_d / rv_w / rv_m 全 lag-shifted）。
- seed=42 固定（np.random.seed + np.random.default_rng(SEED) for bootstrap）。
- Bootstrap 1000 iterations × 3 asset × 3 quantile = heavy compute → 走 `scripts/compute_queue.py`。
- IS/OOS hard split 2020-12-31 / 2021-01-04（無 look-ahead 進 OOS）。
- 套件限制（statsmodels QuantReg 收斂）已 `max_iter=5000`，若任何 asset/quantile fail 會在 `run_asset` raise 中斷。
- Codex review mandatory before knowledge.json write（per `.claude/rules/experiments.md`）。

## 預期輸出

- `experiments/k1421/k1421_results.json` — 完整結果 + per-asset verdicts + joint bootstrap + aggregate verdict
- 由下個 hourly tick 派 Claude interpretation agent 解讀 + 是否寫 knowledge.json

## 參考

- K1402（SPY HAR-Quantile DM NULL）
- K1403（QQQ/GLD/TLT cross-asset robustness）
- Corsi (2009) HAR
- Koenker & Bassett (1978) Quantile Regression
- Garman & Klass (1980) RV proxy
- Politis & Romano (1994) Stationary bootstrap
- Patton (2011) volatility loss function review
- Harvey, Leybourne, Newbold (1997) DM small-sample correction
