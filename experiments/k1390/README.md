# K1390: Regime-Weighted Conformal VaR

## 動機

本實驗檢驗一個最小可解釋的 regime-structured conformal VaR 校準：若市場處於高波動狀態，單一固定的 unconditional tail quantile 可能會低估尾部風險；若以 `VIX_{t-1} > 20` 將校準樣本拆成高波動與低波動兩個 bucket，再做 regime-specific conformal quantile，是否能改善 VaR 覆蓋率。

## 方法摘要

- 標的：SPY 日對數報酬 `r_t = log(SPY_t / SPY_{t-1})`
- Regime 定義：`high_vol = VIX_{t-1} > 20`，嚴格使用 `t-1` lag，避免 lookahead
- IS：2004-01-01 至 2014-12-31
- OOS：2015-01-01 至 2026-12-31
- VaR 方法：
  - `HS-252`：前 252 日 rolling historical simulation quantile
  - `CU`：以 IS 全樣本尾部分位數固定校準的 conformal-unconditional VaR
  - `CR`：以 IS 高/低波動 bucket 分開校準的 conformal-regime VaR
- 評估：
  - 95% VaR (`alpha=0.05`) 與 99% VaR (`alpha=0.01`)
  - exceedance 定義：`r_t < -VaR_t`
  - **Kupiec LR**（unconditional coverage，df=1）
  - **Christoffersen LR_ind**（first-order Markov independence of hits，df=1）
  - **Christoffersen CC = Kupiec + Ind**（conditional coverage joint test，df=2）
- Data dedup：`load_data` 對 CSV duplicate dates 保留第一筆（防 upstream pipeline 暫時 dup；2026-05 期間 CSV 有 10 個 dup dates，pipeline 修正另案追蹤）

## 資料來源與期間

- 資料檔：`paper/leverage-direction/data/spy_vix_2004-2026.csv`
- 欄位：`spy_adj_close`、`vix_close`
- OOS regime 次數：高波動 859 日，低波動 2005 日（dedup 後 n_obs=2864）

## 結果

### VaR coverage tests

| Method | α | Actual rate | Kupiec p | Christoffersen Ind p | CC p (df=2) |
|---|---:|---:|---:|---:|---:|
| HS-252 | 0.05 | 0.0524 | 0.563 | 1.21e-07 | 7.02e-07 |
| CU     | 0.05 | 0.0419 | 0.041 | 3.19e-05 | 2.17e-05 |
| **CR** | 0.05 | 0.0496 | **0.918** | **0.267** | **0.538** |
| HS-252 | 0.01 | 0.0164 | 0.0016 | 7.01e-06 | 2.84e-07 |
| CU     | 0.01 | 0.0063 | 0.032 | 0.0044 | 0.0017 |
| **CR** | 0.01 | 0.0108 | **0.662** | 0.046 | **0.123** |

### Per-regime VaR magnitudes（IS calibration，% of return）

| α | CU (single bucket) | CR high-vol | CR low-vol | high/low ratio |
|---:|---:|---:|---:|---:|
| 0.05 | 1.80% | 2.997% | 1.224% | 2.45× |
| 0.01 | 3.79% | 5.40% | 1.95% | 2.77× |

CR 在高波動 bucket 內部 VaR 校準幅度顯著大於低波動 bucket，方向 economically consistent。

## 結論

`CR` 在 95% 與 99% VaR 兩個水準上：
1. Kupiec unconditional coverage 兩個 α 都顯著優於 CU（0.918>0.041、0.662>0.032），且接近 nominal rate；
2. Christoffersen CC（conditional coverage 聯合檢定）也顯著優於 CU 與 HS-252（CR 0.538 / 0.123 vs CU 2e-05 / 0.0017 vs HS-252 7e-07 / 3e-07）；
3. Per-regime VaR magnitude 與 economic intuition 一致（high-vol bucket VaR 為 low-vol 的 2.45-2.77×）。

**HS-252** 雖在 95% Kupiec 達標但 Christoffersen Ind p 極小（1e-07）— exceedance hits 高度群聚，coverage 對但 hits clustering 是真風險。**CU** 在兩個 α 都 under-cover（actual<nominal）且 CC FAIL — 固定 unconditional quantile 對 vol regime 校準不足。**CR** 是唯一同時通過 Kupiec + CC 的方法。

Verdict = `REGIME_EFFECT`（stricter rule：CR Kupiec p > CU on both α AND CR CC p not significantly worse than CU on either α）。

## Caveats（已記入 results.json `caveats` 欄位）

- IS/OOS cutoff 2014-12-31 為 canonical，未做 cutoff sensitivity (±1y)
- VIX>20 regime threshold 為 ex-ante per literature，threshold sensitivity 未掃描
- Conformal calibration 為 single-shot 全 IS 樣本，未做 rolling re-calibration

## Reviewer

- 2026-05-25 by codex-rescue subagent (gpt-5.4) — initial pass：lookahead/seed/IS-OOS split/Kupiec impl/HS-252 rolling = PASS；data reproducibility (n_obs mismatch from CSV dup dates), weak verdict rule, missing Christoffersen, missing per-regime magnitude = CAVEAT/FAIL
- 2026-05-25 hourly-13 fix：dedup defensive logic、Christoffersen Ind + CC、per-regime magnitude payload、stricter verdict (Kupiec both + CC not worse) — 全部 review 點已處理
