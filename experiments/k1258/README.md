# K1258 — Forgetting-Factor BMA Volatility Forecast

- **Experiment ID**: `k1258`
- **Status**: **completed 2026-04-20, awaiting Codex review**（executed by Claude sub-agent; main-thread direct run, single commit）
- **Created At**: 2026-04-20T02:10:00+08:00
- **Executed At**: 2026-04-20T~15:00+08:00 (runtime 5.83 min, seed=42)
- **Proposer**: Claude (K1257 H3 rejection 的 structural fix 候選)
- **Executor**: Claude sub-agent（main-thread direct run — not worktree）

## 問題描述

K1257 結論：standard Bayesian Model Averaging 的 posterior update

$$w_{i,t+1} \propto w_{i,t} \cdot p(y_{t+1}|M_i)$$

是 product-of-likelihood，累積若干年 log-lik 後 best model 的 weight exponential → 1（K1257 README 的「約 500 天」係 weight-evolution 圖的目測描述，非量化 hitting-time），posterior **lose all uncertainty** 且 **cannot un-concentrate** 當 regime 轉換。結果：H3（regime-adaptive weight shift）**FAIL**。

**K1258 問題**：加入 forgetting factor $\lambda \in (0, 1]$ 到 posterior update 能否救回 regime-adaptivity？

## 動機（Why this experiment）

1. **K1257 H3 FAIL 是已識別的 structural limitation**（文件化於 K1257 README + mile_5173955c article）
2. **Forgetting factor 是 Raftery-Kárný-Ettler (2010) standard fix** for dynamic model averaging
3. **對應 K593 "no universal winner regime-dependent"** — 若 forgetting-factor BMA 成功，standard BMA 的 regime-incapable 問題有解，ensemble framework 回到桌面
4. **Feed coverage after K1257 article**: 僅討論 standard BMA FAIL，未探索 fix — K1258 若 PASS 則是新 positive finding

## 方法

### Forgetting-factor posterior update

Replace standard product-of-likelihood with exponentially-discounted likelihood:

$$\log w_{i,t+1} = \lambda \cdot \log w_{i,t} + \log p(y_{t+1}|M_i, \mathcal{F}_t)$$

這相當於 exponential discount：較舊的 likelihood 隨 $\lambda^k$ decay，最新 likelihood 權重最高。

當 $\lambda = 1$ → 退化為 K1257 standard BMA（benchmark）
當 $\lambda = 0.99$ → 半衰期 ~69 天（1 quarter）
當 $\lambda = 0.95$ → 半衰期 ~14 天（tracking quick regime shifts）
當 $\lambda \to 0$ → 退化為「只看最新 observation」（極短期 memory）

### Grid of $\lambda$ values to test

- 0.99（long memory）
- 0.975（half-life ~28 天，monthly regime）
- 0.95（quick tracking）
- 0.90（very reactive）

### Assets + window + refit

與 K1257 完全一致（rolling 1250 / refit 63 / seed 42 / 6 models），方便 apples-to-apples 比較：
- SPY / GLD / 0050.TW
- OOS 2020-2026
- 6 models（GARCH / GJR / GJR-t / EGARCH / HAR-RV-proxy / A4f-IV²）

## 預期結果

### H1 primary: Forgetting-factor BMA beats standard BMA (λ=1) on QLIKE

- Null: forgetting-factor BMA QLIKE ≥ standard BMA QLIKE
- Alt: λ<1 variant QLIKE < λ=1 baseline + Harvey |t| > 3

### H2: Forgetting-factor BMA 恢復 posterior switching / deconcentration

- 每 λ variant 計算 regime-avg weight（VIX regime buckets）作為描述性輸出
- **實際檢驗的統計量**：max-weight model 的 switch frequency 是否 ≥ 2× λ=1 baseline（`k1258_forgetting_factor_bma.py:885`）。這是 unconditional 的切換頻率，**不是**「切換與 VIX regime 對齊」的檢定

### H3: Optimal λ 因 asset 而異

- SPY/GLD 可能 λ 高 (long memory 有效，因 A4f-IV² 一直好)
- 0050.TW 可能 λ 低 (posterior 原本 concentrate GJR-t by default，forgetting 可能讓其他 model 有機會)

### H4: λ sensitivity → production recommendation

- 若 λ=0.97 在 3 assets 都 dominant → production default
- 若 sensitive across assets → 需 adaptive λ 選擇 mechanism（更深研究）

## 評估指標

- QLIKE（primary）, MSE, FZ 1%/2.5%（VaR 額外加值）
- Harvey |t|>3 DM test
- Per-regime QLIKE（VIX <15 / 15-20 / 20-25 / >25）
- Weight-switching frequency（多少 % 的時間 max-weight 切換 model）

## Data sources

- yfinance SPY + GLD + 0050.TW + ^VIX daily（同 K1257）
- **Reuse K1257 stored model forecasts** if possible（避免重跑 6 models × 1580 refits）

## 實驗三件套

- [x] `README.md`（本檔）
- [x] `k1258_forgetting_factor_bma.py`（completed 2026-04-20）
- [x] `k1258_results.json`（completed 2026-04-20，3 assets × 5 λ = 15 runs）
- [x] `forecasts_{SPY,GLD,0050_TW}.parquet`（per-model forecast cache — λ sweep reads in O(T)）
- [x] `k1258_qlike_by_lambda.png` + `k1258_weight_switch_freq.png`（diagnostic charts）

## 結果簡述（pending Codex review）

| Hypothesis | Verdict | Key evidence |
|---|---|---|
| **H1** QLIKE improvement | **FAIL** | No λ<1 cell hits Harvey \|t\|>3 + lower QLIKE. SPY/GLD λ<1 QLIKE worse (Harvey t spans +0.207 to +2.659 across the 8 SPY/GLD λ<1 cells); 0050.TW λ<1 marginally better but Harvey max \|t\|=2.00 (below 3 threshold). |
| **H2** switching / deconcentration restored | **PASS** | All 3 assets: weight-switch-freq λ=0.90 >> λ=1 (SPY 1.1%→19.81%, GLD 2.5%→24.0%, 0050.TW 0.3%→21.5%). Posterior avg max-weight drops 0.93→0.29, confirming ff-BMA structurally un-concentrates. **What the code tests is switch frequency ≥2× the λ=1 baseline** (`k1258_forgetting_factor_bma.py:885`) — i.e. that the posterior moves and stays diffuse. It does **not** test whether the switches align with VIX regimes, so this is not evidence of restored regime tracking. |
| **H3** asset-specific optimal λ | **PASS** | SPY opt=1.0, GLD opt=1.0, 0050.TW opt=0.90 — 0050.TW differs. |
| **H4** production default | λ=1.0 (standard BMA) | No forgetting variant beats baseline QLIKE with Harvey gate. 0050.TW QLIKE gain at λ=0.90 (+0.016 QLIKE units) is real but sub-threshold. |

### Apples-to-apples sanity check
- K1258 λ=1.0 QLIKE is **byte-identical to K1257's `qlike_own_sample` BMA figure** across all 3 assets (diff=0.00 to numerical precision; e.g. SPY −8.227435956662777 in both). Confirms the refactor preserves the K1257 baseline.
- **限定**：這條等式**只**對 K1257 的 own-sample 欄位成立。K1257 現行 headline 已 realign 為 common-sample（SPY headline BMA = **−8.18639**，n_common=1518），而 K1258 的 λ sweep 全部跑在各序列自身樣本上。**不可**把 K1258 λ=1 的數字直接與 K1257 headline 表比較。

### Multiple comparisons — 為什麼 `|t|>3` 已經是 de-facto FWER 保護

本實驗跑 **m = 12 個 λ<1 vs λ=1 的 Harvey DM 檢定**（3 assets × 4 個 λ ∈ {0.99, 0.975, 0.95, 0.90}）。

| 量 | 值 |
|---|---|
| 檢定數 m | 12 |
| 5% Bonferroni 校正門檻 | 0.05 / 12 = **0.00417** |
| 本實驗實際門檻 `\|t\|>3` 的 two-sided p（t-dist, df≈1580） | **≈0.00274** |

`\|t\|>3` 對應的 p 值比 12-comparison 的 Bonferroni 門檻**更嚴**（0.00274 < 0.00417），因此 H1 FAIL 的裁決不可能是 multiplicity 造成的假陰性放寬；反過來說，若有任何 cell 曾通過 `\|t\|>3`，它也已自動通過 family-wise 校正。這是本設計的 **de-facto FWER 保護**，不是事後才補的校正。

### Key finding
- **Forgetting factor fixes K1257's H3 concentration problem (H2 PASS) but does NOT produce predictive gains (H1 FAIL)**. The extra switching dissipates into noise — the BMA forecast is variance-weighted, and shifting mass away from the best model (A4f-IV² for SPY/GLD, GJR-t for 0050.TW) hurts calibration faster than it helps regime adaptation.
- **Null result, scoped**: within this design — 3 assets (SPY / GLD / 0050.TW) × 5 fixed λ ∈ {1.0, 0.99, 0.975, 0.95, 0.9} × a single 2020–2026 OOS window — log-posterior discounting alone did not yield a QLIKE improvement clearing the Harvey \|t\|>3 gate in any cell. This is evidence about *these* λ-discounted BMA specifications on *these* three series, not about the BMA family in general: untested alternatives include adaptive/estimated λ, other model pools, other assets, and other OOS windows. Whether **switching models / mixture-of-experts / regime-conditional priors** do better is a hypothesis this experiment motivates but does not test.
- 0050.TW is the sole asset where λ<1 QLIKE improves marginally, but below Harvey significance — may be artefact of single-asset noise OR signal of TW-specific regime structure warranting a follow-up (K1259+).

### Hypotheses answered vs README predictions
| README prediction | Actual | Status |
|---|---|---|
| SPY/GLD λ high (A4f dominant) | Confirmed — λ=1 is optimum | ✓ |
| 0050.TW λ low | Confirmed — λ=0.90 optimum | ✓ |
| λ=0.97 universal dominant | Rejected — no universal λ<1 wins | ✗ |
| Adaptive λ needed | Implied but sub-threshold — FAIL not PARTIAL | inconclusive |

## 相關 K

- **K1257** standard BMA （本實驗直接 extension）
- **K482** MCS-weighted ensemble（K1257 已 extend equal-weight puzzle；K1258 可能破除 puzzle if λ<1 works）
- **K593** regime-dependent（motivation）
- Raftery, A.E., Kárný, M., Ettler, P. (2010) "Online prediction under model uncertainty via dynamic model averaging" *Technometrics* 52(1) — primary method reference

## Random seed

**42**（同 K1257，便於 apples-to-apples）

## 防錯檢查清單

- [ ] Lag discipline: signal shift(1), return at t
- [ ] Forgetting factor applied BEFORE log-lik of current obs（posterior decay → then update with new data）
- [ ] Numerical: forgetting 不讓 min log-weight → -inf（若有 threshold renormalize）
- [ ] Rolling window 1250 保持（forgetting vs window 是 orthogonal 機制）
- [ ] Seed 42 固定

## Open questions

- Prior re-set on each refit window or carry posterior across? （carry-across is purer, but may interact with forgetting）
- λ=1 as in-run benchmark vs K1257 stored as external benchmark — 選哪個？
- Multi-asset shared-λ vs asset-specific λ？

## Runtime estimate

~20-30 min（reuse K1257 forecasts）或 ~60 min（重跑）。

## 為什麼這是重要的

- K1257 文章 mile_5173955c 已承諾「forgetting-factor / sliding-window 是下一步」— 本實驗兌現承諾
- 若 K1258 PASS：K1257 H3 的 concentration 問題有一個具體修法，ensemble framework 的 adaptive-weighting 路線值得續推
- 若 K1258 FAIL：得到一個**範圍受限的 NULL** — 在本設計下（3 檔資產、固定 λ 網格、單一 2020–2026 OOS window），log-posterior discounting 這一種 forgetting 機制不足以產生預測增益

**實際結果的正確讀法（不可外推）**：H1 FAIL 是 **descriptive** 的——它說的是「這 5 個固定 λ、這 6 個模型、這 3 檔序列、這一個 OOS window」下沒有 cell 通過 Harvey \|t\|>3。它**不**構成「BMA family 沒有前途」的證據，也**不**足以建議社群停止投入 BMA 方向：adaptive/estimated λ、其他 model pool、其他資產、其他 window、以及 switching models / mixture-of-experts / regime-conditional priors 全部未被本實驗檢驗。把單一 null cell 升級成 family-level 判決，正是本 README 先前版本的過度外推。
