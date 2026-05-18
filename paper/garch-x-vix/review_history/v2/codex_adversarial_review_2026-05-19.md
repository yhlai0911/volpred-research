# Paper 9 (garch-x-vix) — Codex Adversarial Review v2

**Date**: 2026-05-19  
**Reviewer**: Codex gpt-5.4 (adversarial mode)  
**Task**: Paper 9 Codex adversarial review (next_tasks: paper9_codex_adversarial_review, P3)  
**Tokens**: 15,991  

---

## Verdict Summary

| # | Issue | Severity |
|---|-------|----------|
| 3 | MCS indistinguishability | **SERIOUS FLAW** |
| 4 | COVID-19 dominance | **SERIOUS FLAW** |
| 7 | Multiple testing / spec search | **SERIOUS FLAW** |
| 1 | VRP tautology | **SIGNIFICANT CONCERN** |
| 2 | Best model fragility | **SIGNIFICANT CONCERN** |
| 5 | Source decomposition coherence | **SIGNIFICANT CONCERN** |
| 6 | Missing HAR-RV benchmark | **SIGNIFICANT CONCERN** |
| 8 | Cross-asset multiple testing | **MODERATE–SIGNIFICANT CONCERN** |
| 9 | Refit frequency mismatch | **MODERATE CONCERN** |
| 10 | Contemporaneous normalization terminology | **MODERATE CONCERN** |

**Overall**: The paper's main claim "A4f sufficient to replace GARCH-MIDAS" is overstated. The safe conclusion is: "A4f is a parsimonious, competitive alternative that is statistically indistinguishable from best MIDAS in the sample."

---

## Detailed Review

### 1. VRP Tautology — SIGNIFICANT CONCERN

若 g_t = σ²_t/τ_t 而 τ_t 又幾乎由 VIX²_{t-1} 線性張成，則 g_t 與任何「已實現波動/隱含波動」型 proxy 的高度相關，本身就有強烈機械成分；ρ=0.80 不能直接被解讀為結構性經濟發現。作者說「GARCH filter 是貢獻」可以成立，但必須證明這個 filter 帶來的相關性增量超過單純代數分解。更嚴重的是，拿 A4f 的 g_t 與一個粗糙 VRP proxy 比，然後再拿其他不具相同分解結構的模型做 0.80 對 0.15 的比較，並不公平，因為比較基準的 mechanical overlap 不一致。

**Evidence needed**: 需要提供 matched decomposition benchmark：例如對每個 competitor 都構造可比的「short-run/long-run ratio」或以 partial correlation、orthogonalization 證明 g_t 在剔除機械成分後仍有增量訊息。

---

### 2. Best Model Fragility — SIGNIFICANT CONCERN

A4f 與 A4 的 QLIKE 差距只有 0.002 (−8.360 vs −8.358)，量級極小，卻被包裝成可辨識的規格勝出，這在實證上很脆弱。DM t 值從 3.81 到 4.03 的跳升未必代表經濟上有任何可感知改善，可能只是 loss differential 的序列特性、樣本特定共變異結構或數值最佳化細節造成。若 free intercept 只帶來幾乎不可見的平均 loss 改善，則「最佳模型」的結論過強。

**Evidence needed**: 需要提供 rolling subsample DM、block bootstrap confidence interval、以及 A4f 相對 A4 的經濟量化改善，例如 VaR exceedance、capital savings 或 forecast error distribution 的穩健性。

---

### 3. MCS Indistinguishability — SERIOUS FLAW

如果 MCS 在 α=0.10 下無法區分 A4f 與 B1，且 pairwise DM t=−0.90，那麼「GARCH-MIDAS 不必要」這個命題就沒有被統計上支持。最多只能說 A4f 與最佳 MIDAS 在該樣本上表現相當，但不能把「未拒絕差異」倒裝成「簡約模型已證明足以取代 MIDAS」。在頂刊標準下，這屬於把點估計排序誤寫成模型淘汰結論，burden of proof 明顯放錯。

**Evidence needed**: 需要把主張降格為 observational equivalence，或額外提供跨樣本、跨資產、跨損失函數下 A4f 系統性優於 MIDAS 的證據。

---

### 4. COVID-19 Dominance — SERIOUS FLAW

2019–2026 的 OOS 幾乎必然被 2020 年初的 regime break 主導，而 VIX 驅動模型在這種時段自然占優，這使整體結果可能只是 crisis-fit 而非一般性 forecasting superiority。若沒有排除 2020Q1–Q2、winsorize 極端 VIX、或分段報告 pre-COVID/COVID/post-COVID 表現，讀者無法知道 A4f 的勝利是否只來自幾十個極端觀測。這不是次要 robustness；這是核心識別問題。

**Evidence needed**: 需要提供 leave-COVID-out、subperiod DM、以及 crisis vs non-crisis state-conditional evaluation。

---

### 5. Source Decomposition Coherence — SIGNIFICANT CONCERN

一旦 A4f 允許 free ω_g 且 E[g_t] ≠ 1，τ_t 就不再乾淨地承載 unconditional scale，分解的結構詮釋已被鬆動。換言之，作者一邊用 constrained decomposition 講故事，一邊推薦 unconstrained practical winner，理論敘事與實務主模型並不一致。這會讓人懷疑 A4f 的優勢是否只是多一個自由度吸收 misspecification，而不是驗證了「fear component + endogenous component」這個經濟機制。

**Evidence needed**: 需要正式重寫識別與經濟詮釋，並報告在 E[g_t]=1 約束下結果衰減多少，以及 A4f 額外自由度是否只是 generic intercept effect。

---

### 6. Missing HAR-RV Benchmark — SIGNIFICANT CONCERN

在波動預測文獻裡，若完全不納入 HAR-RV 或其合理變體，任何「parsimonious winner」的宣稱都不完整，因為你其實只是在一組偏窄的 GARCH-family 候選中挑冠軍。尤其本文已涉及 realized volatility/QLIKE/VaR，卻缺少最標準的 realized-measure benchmark，會讓讀者懷疑 benchmark set 是否被有利地裁切。這個缺口不一定推翻結果，但足以削弱主要貢獻的外部說服力。

**Evidence needed**: 需要加入 HAR-RV、HAR-RV-VIX，最好再含 realized-GARCH 類 benchmark，並在同一 OOS protocol 下重跑比較。

---

### 7. Multiple Testing / Spec Search — SERIOUS FLAW

17 個規格事後按 QLIKE 排名，再對最優模型報告顯著 DM，若沒有清楚的 ex ante 規格註冊或理論先驗，這就是典型 specification search。Harvey threshold 不是為 data snooping 後的 winner's curse 設計的；它控制的是單次比較的檢定，不是搜尋過程。尤其 A4f 的 winning edge 很小，越讓人擔心它是搜尋噪音上的局部最適。

**Evidence needed**: 需要提供完整 spec genealogy、明確說明哪些設計是 ex ante、並用 White's Reality Check、SPA 或 sample split 驗證選模後顯著性。

---

### 8. Cross-Asset Multiple Testing — MODERATE–SIGNIFICANT CONCERN

六個額外市場只成功四個，且沒有 family-wise 或 FDR 校正，則「跨資產成立」的語氣需要大幅收斂。更不利的是失敗樣本 EEM 與 0050.TW 恰好指出此模型對美股波動恐慌結構相近資產才有效，這比較像條件性適用，而不是一般性可移植。若「高 VIX correlation 資產」是看到結果後才提出，那就是事後解釋，不是預先假說。

**Evidence needed**: 需要事前定義 cross-asset hypothesis、做多重比較校正，並把「何種資產應該有效」寫成可檢驗的 ex ante prediction。

---

### 9. Refit Frequency Mismatch — MODERATE CONCERN

63 日重估對平穩期合理，但對 2020 年那種幾週內 regime shift 的環境可能過慢，因此目前結果有兩種相反解讀：不是模型穩健，而是 VIX regressors 幫它在 stale parameters 下撐過去；或者結果高度依賴這個特定 refit choice。若論文主張 practical risk management superiority，refit frequency 就不能只報一個設定。

**Evidence needed**: 需要提供 21/42/63/126 日重估敏感度，特別是 COVID 期間與非 COVID 期間的相對表現。

---

### 10. Contemporaneous Normalization Terminology — MODERATE CONCERN

若 τ_t 只使用 t−1 可得的 VIX，則用 √τ_t 去標準化 r_{t-1} 並不存在真正的 simultaneity 或 endogeneity 問題，最多只是 timing convention 與 filter design choice。把這件事表述成「避免同時性」容易誇大方法論必要性，讓人誤以為 τ_{t-1} 有識別偏誤而非只是另一種可比規格。這會傷害論文在 econometric terminology 上的精確度。

**Evidence needed**: 需要把術語改成 information-timing normalization choice，並直接比較用 τ_t 與 τ_{t-1} 的 forecast and fit consequences，而非賦予前者過強的識別意涵。

---

## Priority Action Items for R1 Revision

### Critical (must address before top-journal submission)

1. **Challenge 4 — COVID subperiod analysis**: Run leave-COVID-out DM test (2020-02-01 to 2020-06-30 excluded) + pre-COVID (2019) and post-COVID (2021-2026) separate DM. If A4f loses significance without COVID, the main claim collapses.

2. **Challenge 3 — Reframe main claim**: Change from "GARCH-MIDAS is unnecessary" to "A4f is observationally equivalent to best MIDAS at lower parameter cost." MCS result must be front-and-center, not buried in robustness.

3. **Challenge 7 — Spec genealogy documentation**: Add Appendix documenting which specs were pre-specified from theory (VIX² dimensional motivation, free ω for VRP) vs post-hoc ranking. Reference White's Reality Check or SPA results.

### Important (should address)

4. **Challenge 6 — HAR-RV benchmark**: Add HAR-RV and HAR-RV-VIX to Table 2 horse race. This is the #1 missing benchmark that referees will flag.

5. **Challenge 5 — Decomposition coherence**: Add paragraph clarifying that the source decomposition interpretation applies to constrained models (A4), while A4f's free ω_g provides empirical flexibility with slightly weaker structural interpretation.

6. **Challenge 1 — VRP mechanical component**: Quantify the mechanical portion via simulation (fix τ_t at its fitted values, draw g_t i.i.d. from its empirical distribution, compute ρ). Report incremental GARCH-filter contribution.

### Minor (can address in footnotes)

7. **Challenge 9 — Refit sensitivity**: Table in appendix showing DM results for 21/42/63/126-day refit.

8. **Challenge 8 — Cross-asset correction**: Add Bonferroni-adjusted threshold (|t| > 3.0 already conservative, may survive) or FDR correction with note.

9. **Challenge 10 — Terminology**: Change "contemporaneous normalization" to "current-period VIX normalization" and drop "simultaneity" language.

10. **Challenge 2 — A4f vs A4 comparison**: Add block-bootstrap CI for QLIKE difference in footnote or appendix.

---

## Robustness Items to Add as Experiments

The following require new computation (suggest adding to compute queue):

- **K_NEW_A**: leave-COVID-out DM (2019+2021-2026 OOS), requires rerunning evaluate_all_specs.py with COVID dates masked
- **K_NEW_B**: Refit sensitivity table (21/42/63/126-day cycles)
- **K_NEW_C**: HAR-RV + HAR-RV-VIX vs A4f DM test (same OOS period)
- **K_NEW_D**: White's Reality Check / SPA on the 17-spec horse race
