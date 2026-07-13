# K1025b: BTC Vol Spillover to NASDAQ-100 Equity (VXN target)

> ## ⛔ SUPERSEDED (2026-07-13) — Diebold-Yilmaz 方向性結論已撤回
>
> **`k1025b_v2.py` → `k1025b_v2_results.json` 是 canonical。**
> `k1025b_results.json` 的 `spillover_index` 與 `conclusions.spillover_direction`
> **全數撤回**（該檔依「永遠修流程，不修資料」原地保留，未手改，作為已發表內容的歷史紀錄）。
>
> | 指標 | 已撤回的發表值 | 更正值（KPPS，order-invariant） |
> |---|---|---|
> | `mean_net_btc` | **−76.64pp**（「BTC 是淨接收者」） | **+2.70pp**（全樣本，**翻號**，量級縮 ~28×） |
> | rolling 252d 均值 | — | **−0.11pp**，65% 視窗為負 → **無穩定方向** |
> | `mean_total` (TCI) | **90.09%** | **20.3%** |
>
> **三個缺陷，排序其實是最小的一個**：
> 1. **FEVD 誤切【主因】** — `fevd.decomp` 實為 `(n_vars, horizon, n_vars)`，
>    `decomp[-1]` 取到最後一個**變數**的 (horizon, n) 表。`n_vars` 被讀成 10 →
>    TCI 被機械性推到 ~90%（**在純雜訊上也是 ~90%**）。單這條就足以生出 −76.64pp。
> 2. **欄位命名反了** — `mean_from_btc` 是 BTC **傳出**量，但 DY 的 `FROM_i` 指 i **收到**的。
>    （已實測：NET 公式本身結構正確，這是標籤缺陷不是符號錯誤。）
> 3. **Cholesky 排序相依** — 即使切對，NET 跨 6 種排序仍跨 11.6pp 且**變號**。
>
> **⚠️ 「5/5 複製 K1025」的宣稱要降為 4/5**：第 (4) 項（DY net −76.64 vs K1025 −76.89，
> 「near identical」）是**兩支腳本共用同一個 bug 的一致，不是效應的複製**。
> Order-invariant 下兩個 panel 連正負號都不同（K1025 v3: −0.95pp；K1025b v2: **+2.70pp**）。
>
> Granger / 非對稱 / quantile / DCC / forecasting **未經過 FEVD，不受影響**。
> 完整稽核與下游污染清單：**[`ordering_audit.md`](./ordering_audit.md)**

**Date**: 2026-04-28（v2 correction: 2026-07-13）
**Author**: VolPred Research System (main thread)
**Status**: ⛔ spillover 段 SUPERSEDED by `k1025b_v2.py`；其餘方法有效
**Parent experiment**: K1025 (BTC vol → VIX)
**Purpose**: Multi-asset OOS robustness check for P10 (paper/crypto-fear-channel) per cross-paper meta-evaluation 2026-04-28 mandatory IJFMIM/JEF blocker fix.

---

## Motivation

P10 cross-paper meta-evaluation (2026-04-28, agent `a4c82fc4`) identified single-asset OOS as a top-tier blocker for IJFMIM/JEF submission: P6 PRG and P9 GARCH-X-VIX both run multi-asset OOS (5-6 markets), while P10 originally tested only the BTC→VIX (S&P 500 fear gauge) channel. Reviewers comparing same-author submissions would notice the asymmetry.

K1025b runs the identical 6-method analysis on the NASDAQ-100 fear gauge (^VXN) paired with QQQ as the equity ETF. If the asymmetric Granger / QR sign-reversal / regime-watershed / DY-net-receiver findings replicate, the family-level spillover claim is supported across two equity-fear gauges rather than a single asset.

## Variant from K1025

Three lines changed (mechanical ticker swap):

| Component | K1025 | K1025b |
|---|---|---|
| Equity ETF | SPY | QQQ |
| Fear gauge | ^VIX | ^VXN |
| Tracking | S&P 500 | NASDAQ-100 |

All 6 methods (symmetric Granger / asymmetric Hatemi-J / quantile regression / Diebold-Yilmaz / DCC / DM forecast) and all parameters (sample window 2015-02 to 2026-04-09, lag windows, quantiles, regime cutoffs, OOS window 2019-01-01 to 2026-04-08) are byte-identical to K1025.

Variable naming: `vix` is preserved as the internal Python variable name (for code-reuse simplicity); all output JSON keys rename `vix` → `vxn` and `experiment_id` is set to `K1025b`.

## Lookahead Audit

Inherited from K1025 framework:
- **Granger causality**: `statsmodels.tsa.stattools.grangercausalitytests(maxlag=L)` is internally lag-aware; tests whether *past* $X$ predicts *current* $Y$, not contemporaneous association.
- **Quantile regression**: explicit `t-1` lag in $Q_\tau(\text{VIX}_t | \text{RV}^{(20)}_{\text{btc}, t-1})$ specification.
- **DM forecast**: explicit `t-1` lag in `VIX_t = α₀ + Σ α_j VIX_{t-j} + γ * RV_btc_{t-1} + u_t`.
- **ADF tests**: stationarity check only; no forecast produced.
- **DCC / DY spillover**: contemporaneous correlation / variance decomposition; descriptive not predictive.

K1025 passed prior code review (per `research_program.md` 2026-04 history); K1025b mechanical ticker swap inherits the same protections.

## Results Summary

| Finding | K1025 (BTC→VIX) | K1025b (BTC→VXN) | Pattern preserved? |
|---|---|---|---|
| Asymmetric Granger (BTC-) lag 3 F | 10.18 | 11.46 | ✅ same direction |
| Asymmetric Granger (BTC+) lag 1-5 p | 0.16-0.95 (all NS) | 0.14+ (NS) | ✅ |
| QR sign reversal $\beta_{0.05}$ | $-2.86$ | $-1.46$ | ✅ |
| QR upper-tail $\beta_{0.95}$ | $+22.31$ | $+16.29$ | ✅ |
| QR amplification ratio ($\tau=0.95/0.5$) | 8.54$\times$ | $\sim$11$\times$ (similar order) | ✅ |
| 2020 subperiod Granger F | 11.05 | 13.41 | ✅ same regime watershed |
| ~~DY total spillover mean~~ | ~~90.11%~~ | ~~90.09%~~ | ⛔ **RETRACTED 2026-07-13** — 兩者皆為 FEVD 誤切假象（純雜訊上也 ~90%）。更正值：K1025 v3 **19.5%** / K1025b v2 **20.3%** |
| ~~DY net BTC (receiver)~~ | ~~$-76.89$pp~~ | ~~$-76.64$pp~~ | ⛔ **RETRACTED 2026-07-13** — 「near-identical」是**兩支腳本共用同一個 bug** 的一致，不是效應的複製。Order-invariant 下連正負號都不同：K1025 v3 **−0.95pp** / K1025b v2 **+2.70pp** |
| DCC Crisis-regime mean | 0.41 | 0.51 (Crisis VIX>30 def doesn't apply to VXN; using existing K1025 thresholds) | ✅ rises with stress |
| OOS DM stat (Harvey) | $-0.98$ (NS) | $-0.43$ (NS) | ✅ both fail Harvey |
| OOS DM full-sample improvement | $-0.24\%$ MSE | $-0.11\%$ MSE | ✅ both deteriorate marginally |

~~**Verdict**: All 6 P10 stylized facts replicate qualitatively in the BTC→VXN channel.~~

> ⛔ **VERDICT 更正 (2026-07-13)**：**降為 5/6**（原表 6 項中的 DY 兩列已撤回，見上）。
> DY 那一項的「複製」是**兩支腳本共用同一個 FEVD 誤切**所致 —— 相同的 bug 當然給出相同的數字。
> 兩支腳本跑同一個 bug 得到一致的結果，**不構成佐證**。
> Order-invariant 重估後兩個 panel 的 BTC NET 連正負號都不同（−0.95pp vs +2.70pp）。
> 其餘（asymmetric Granger / QR sign reversal / 2020 regime watershed / DCC / OOS DM NULL）
> **未經過 FEVD，複製結論不受影響**。

## Files

- `k1025b.py` — fork from `experiments/k1025/k1025.py`（2026-07-13：spillover 估計量已改 canonical KPPS + 撤回 banner）
- `k1025b_results.json` — ⛔ spillover 段已撤回；其餘有效。原地保留未手改（歷史紀錄）
- `k1025b_results.png` — visualization（spillover panel 已失效）
- **`k1025b_v2.py`** — ✅ canonical：order-invariant KPPS 重估 + 6 排序全枚舉 + 無傳染 null
- **`k1025b_v2_results.json`** / **`k1025b_v2_results.png`** — ✅ canonical 結果與圖
- **`ordering_audit.md`** — 全量下游稽核 + 交回主線程的污染清單
- `data/qqq_btc_vxn_2015-2026.csv` — pinned snapshot（reproducibility；無 live fetch）
- `README.md` (this file)

## Cross-link

- Parent: `experiments/k1025/`
- Paper: `paper/crypto-fear-channel/`
- Cross-paper meta-evaluation: `paper/crypto-fear-channel/research_notes/cross_paper_meta_eval_2026_04_28.md` (Section 6 multi-asset OOS blocker)
- Knowledge entry: pending (will write to `storage/memory/knowledge.json` after main.tex §6 update)

---

## v2 更正 (2026-07-13) — order-invariant 重估

**腳本**：`k1025b_v2.py` → `k1025b_v2_results.json` + `k1025b_v2_results.png`
**觸發**：K865b class sweep 標記本檔以 Cholesky FEVD 推導 NET 方向性結論，未做排序置換。

### 方法

- **估計量**：KPPS generalized FEVD（Koop-Pesaran-Potter 1996；Pesaran-Shin 1998），order-invariant。
  函式**直接 import `k1025_v3.py`**，不重寫第二套 —— 兩套實作分歧才是下一個 bug。
- **隔離原則**：資料建構、ADF 條件差分、VAR lag 規則（AIC, maxlags=5）、rolling 視窗（252d）
  與 step（5）**全部照抄原始 k1025b.py**，只換估計量。否則「估計量修正」會和「規格變動」混在一起。
- **資料**：pin 成 snapshot `data/qqq_btc_vxn_2015-2026.csv`（QQQ / BTC-USD / ^VXN），
  無 live fetch。N = 2,812，2015-02-02 → 2026-04-08，seed = 42。
- **先重現缺陷再談更正**：在同一份資料上位元級重現原始 bug
  （rolling net **−76.62** vs 發表 −76.64；TCI **90.09%** vs 發表 90.09%；**512** 視窗）
  → before/after 是**實測**，不是宣稱。

### 結果

| 估計量 | TCI | NET_BTC |
|---|---|---|
| 發表版（誤切 + Cholesky） | 90.09% | **−76.64pp** |
| Cholesky（切對）6 種排序全枚舉 | 8.2–12.5% | **−2.60 ~ +8.96pp**（跨 11.55pp，**變號**） |
| **KPPS generalized（canonical）** | **13.72%** | **+2.70pp** |

KPPS 在同 6 種排序下 NET 跨度 = 3.2e-12pp → order-invariant 確認。

**NET 對照「無傳染 null」而非對照 0**（circular-shift randomization，B=1000，
保留自身自相關與邊際分布、破壞跨序列對齊）：null 95% 區間 [−1.06, +0.96]，
觀測 +2.70pp → **p = 0.005**。

### 誠實讀法

**可以說**：發表的量級（−76.6pp）與「強淨接收者」讀法是假象；order-invariant 下 BTC 淨連動
小一個數量級，且**符號不穩定**（全樣本 +2.7pp，rolling 均值 −0.11pp，65% 視窗為負）。

**不可以說**：「BTC 其實是淨傳播者」。全樣本 +2.7pp 雖過 null，但相對它取代的 −76.6pp
在經濟意義上可忽略，rolling 口徑也不支持穩定方向。**不要把一個 overclaim 換成它的鏡像。**

### 復現

```bash
uv run --extra dev python experiments/k1025b/k1025b_v2.py
```
