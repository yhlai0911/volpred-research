# K1470 — Main Table 1 Spec (K1145/K1147/K1150) 100-Multistart Re-estimation

> **TL;DR**: paper/eav-universal-magnitude 的主 Table 1（TW/US/JP 三市場 pooled
> θ_EAV）是 default single-init BCD 估計。§6.6.4 multistart audit（K1213/K1216/
> K1216b/K1216c）證明同 family spec 有 panel-wide two-basin pathology（10/10
> markets FRAGILE）。K1470 對主三市場 **原 BCD spec（N=30/31 全 panel）** 跑同
> 協議 ≥100-multistart 重估，回答：canonical θ̂_EAV 是否在 inferior basin？
> US>JP>TW magnitude ordering 是否保持？

[提出: Claude（§6.6.4 mandated re-run，body.tex:598-607 明文標註）, 執行: Claude subagent background run]

- Status: **completed 2026-06-11**（runtime 1697s = 28.3 min；100 starts × 3 markets，295/300 valid）
- Verdict: **TW STABLE-but-FLAT_RIDGE / US FRAGILE / JP FRAGILE；US>JP>TW magnitude ordering 在 refined 下保持**

---

## 1. 動機（Why）

`paper/eav-universal-magnitude/body.tex` Table~`tab:main_results`（line ~596-622）：

| Market | Exp | N | pooled obs | θ̂_EAV (canonical) | bootstrap t |
|--------|-----|---|-----------|--------------------|-------------|
| Taiwan | K1145 | 31 | 121,014 | 6.36×10⁻⁵ | 5.24 |
| United States | K1147 | 30 | 90,479 | 1.91×10⁻⁴ | 4.50 |
| Japan | K1150 | 30 | 87,917 | 1.41×10⁻⁴ | 11.99 |

這三個數字全部來自 **default single-init** BCD pooled MLE（init_vix=1e-7,
init_eav=5e-5, L-BFGS-B inner）。§6.6.4（`sec:multistart_method`）的 audit 在
joint pooled-MLE 變體（S≤10 pools, K1168/K1172 ladder spec）發現 **two-basin
likelihood surface**：10/10 markets default-init 落在 inferior basin-A（LR
146-2837 vs χ²(1)=3.84）。body.tex 明文寫：

> "(K1145/K1147/K1150) are produced under default single-init L-BFGS-B and
> must be re-run under the same multistart protocol before these magnitudes
> are quoted as final."

K1216c 的 cross-check 段（README L60）已顯示 BCD canonical 與 single-init
joint canonical 都落在 inferior basin（S=10 子樣本上）——但 **主 Table 1 的
full-panel（N=30/31）BCD spec 從未被 multistart audit 過**。K1470 補上這個 gap。

### 與 K1216c 的差異（為什麼不是重複）

| | K1216c | K1470 |
|---|--------|-------|
| Spec | joint pooled MLE（單一 L-BFGS-B over 3+3S params） | **原 BCD spec**（inner per-stock 3-start L-BFGS-B × outer shared 2-D update） |
| Panel | S=10 top-cap 子樣本 | **full N=31/30/30 主 panel（Table 1 原樣本）** |
| Canonical 對照 | K1216c 自建 joint single-init | **K1145/K1147/K1150 results.json 原 canonical（先 reproduce 再 audit）** |
| 回答的問題 | pathology 是否 EM-specific | **主 Table 1 數字本身是否站得住** |

## 2. 方法（What）

協議 = §6.6.4 `sec:multistart_method`（K1213/K1216/K1216b/K1216c 同款），
adapted to BCD spec：

1. **100 random inits / market**，seeds **43..142**（與 9-market audit 完全相同
   的 seed discipline）：
   - `init_eav ~ log-uniform [1e-6, 5e-4]`（協議 step 1 verbatim）
   - `init_vix ~ log-uniform [1e-9, 1e-3]`（BCD shared bound box；BCD 的
     θ₀ᵢ 是 stock fixed effects，每輪 inner loop 重新 fit，不在 shared init
     維度）
   - 每個 start 的估計程序 = **原 main fit call 一字不差**：
     `fit_pooled_panel(stocks, max_outer=8, time_budget=600)`（同 inner
     3-start per-stock L-BFGS-B、同 bounds、同 lag 慣例）
2. **Penalty-trap guard**：reject non-finite LL 或 LL < 1000
3. **K-means (K=2)** basin identification on (θ̂_EAV, LL)（`kmeans_basins`
   verbatim vendored from `experiments/k1216/k1216.py:345`）
4. Best-LL across valid starts = multistart estimate
5. **NM polish**：Nelder-Mead warm-start on shared 2-vector（stock params
   frozen at best fit）→ **BCD continuation（max_outer=3）** 使 polished LL
   與其他 fit like-with-like（含 final inner pass）
6. **Refined = argmax LL** over {canonical, best multistart, NM continuation}
7. **LR = 2(LL_refined − LL_canonical)** vs χ²(1)=3.84：
   - LR > 3.84 → **FRAGILE**（canonical 在 inferior basin）
   - LR ≤ 3.84 → **STABLE**（canonical 即 global basin）
8. **Hessian SE** on θ_EAV at refined（原 module 的 `hessian_se_theta_eav`）
9. **Ordering check**：canonical US > JP > TW 在 refined 下是否保持
10. Seeds：base=42；starts 43..142；K-means 42 — 全部固定

### Spec provenance（研究誠實）

- `load_one_stock` / `fit_pooled_panel` / `shared_objective` /
  `hessian_se_theta_eav` 全部 **importlib verbatim import** 自
  `experiments/k1145/k1145.py`、`k1147/k1147.py`、`k1150/k1150.py` —
  **零 re-implementation**，lag 慣例（`_negll_numba` 內 `vix[t-1]`,
  `eav[t-1]`）原封不動。
- 資料 = 各原實驗 `data/` 內 cached parquet/json（無網路、無 revision risk）。
- **Canonical 先 reproduce 再 audit**：用原 call 重現 canonical fit，與
  stored results.json cross-check（θ rel-tol 1e-3、LL rel-tol 1e-4）；
  不過 → 該市場標 `INCONCLUSIVE_REPRO_MISMATCH`，不硬比。

### Canonical 對照值（verbatim from stored results.json）

| Market | Exp | θ̂_EAV | pooled LL |
|--------|-----|--------|-----------|
| TW | K1145 | +6.362165e-05 | 329,349.98 |
| US | K1147 | +1.908986e-04 | 256,713.70 |
| JP | K1150 | +1.412787e-04 | 234,432.52 |

## 3. 執行（How）

```bash
# 全量（2026-06-11 實際以 background Bash 跑完，1697s）
uv run python experiments/k1470_eav_multistart_main_spec/k1470.py

# smoke test（單市場、少 starts）
K1470_N_STARTS=2 K1470_MARKETS=TW uv run python experiments/k1470_eav_multistart_main_spec/k1470.py
```

- 每市場跑完即寫 checkpoint `k1470_results_partial.json`（long-job 安全）
- 產出：`k1470_results.json` + `k1470_multistart_<MKT>.csv` ×3 +
  `k1470_basin_hist_<MKT>.png` ×3

## 4. 結果（completed 2026-06-11，runtime 28.3 min）

### 4.0 Canonical reproduction（audit 前提）

三市場 canonical fit **bit-exact 重現** stored results.json（rel Δθ = rel ΔLL =
0.00e+00）— audit 基準完全成立，無資料 / 環境漂移。

### 4.1 主表：canonical vs refined

| Market | canonical θ̂_EAV | refined θ̂_EAV (source) | ratio | LL gain | LR | χ²(1) multiple | Verdict | identification |
|--------|-----------------|--------------------------|-------|---------|-----|----------------|---------|----------------|
| TW (K1145) | +6.362e-05 | +6.844e-04 (best multistart, seed 見 csv) | 10.8× | +0.72 | **1.43** | 0.37× | **STABLE** | **FLAT_RIDGE** |
| US (K1147) | +1.909e-04 | +5.341e-03 (best multistart) | 28.0× | +20.28 | **40.56** | 10.6× | **FRAGILE** | OK |
| JP (K1150) | +1.413e-04 | +2.876e-03 (NM continuation) | 20.4× | +5.39 | **10.78** | 2.8× | **FRAGILE** | OK |

- valid starts: TW 100/100、US 95/100、JP 100/100（5 個 US start 被 penalty guard 排除）
- refined Hessian t：TW 14.13、US 22.39、JP 20.27（正向顯著性不受影響）
- refined θ_rel（θ̂_EAV / mean σ²）：TW 1.80、US 16.41、JP 7.90

### 4.2 Ordering check（核心問題之一）

| | TW | JP | US | order |
|---|----|----|----|----|
| canonical | 6.36e-05 | 1.41e-04 | 1.91e-04 | **US > JP > TW** |
| refined | 6.84e-04 | 2.88e-03 | 5.34e-03 | **US > JP > TW** |

→ **US > JP > TW magnitude ordering 在 multistart refinement 下保持**（且
refined 下市場間 gap 拉大）。

### 4.3 Basin 結構

| Market | basin A frac (θ mean) | basin B frac (θ mean) | 備註 |
|--------|----------------------|----------------------|------|
| TW | 0.87 (3.16e-03) | 0.13 (1.00e-02) | basin B 聚在 shared bound 上界 1e-2，LL 較低 |
| US | 0.59 (1.76e-03) | 0.41 (9.99e-03) | 同上 |
| JP | 0.61 (1.32e-03) | 0.39 (9.92e-03) | 同上 |

### 4.4 誠實結論

1. **單一 init 的 pathology 在主 BCD spec 也存在，但程度遠輕於 K1216c 的 S=10
   joint spec**：LR 1.4 / 40.6 / 10.8 vs K1216c 的 588 / 2837 / 236（TW/US/JP）。
   Full-panel（N=30/31）BCD 比 small-S joint MLE 穩健一個數量級以上。
2. **US 與 JP canonical 落在 inferior basin（FRAGILE）**：refined θ̂_EAV 比
   canonical 大 28× / 20×，LR 顯著超過 χ²(1)。Table 1 的 US/JP point estimates
   不能當 final magnitude 引用。
3. **TW 名義 STABLE 但實質 FLAT_RIDGE**：θ̂_EAV 從 6.36e-05 移到 6.84e-04（10.8×）
   而 LL 只 +0.72 — likelihood 在 θ_EAV 方向接近平坦。「STABLE」只說 canonical
   不輸 refined 超過 χ²(1) 噪音，不代表 magnitude 良好識別。
4. **三市場共同訊息**：pooled θ_EAV 的「正向、顯著」結論 robust（refined Hessian
   t = 14-22，全部 ≫ 3）；但 **magnitude 本身識別薄弱**（LL 對 θ_EAV 在 1-2 個
   數量級範圍內幾乎不變）。Paper 的 'universal magnitude' 主張需要降級為
   'universal sign + ordering'，或改報 basin-aware CI。
5. **Ordering robust**：US > JP > TW 在 canonical 與 refined 下都成立 — Table 1
   的相對排序結論存活，絕對 magnitude 不存活。
6. Limitation：本 audit 不重做 cluster bootstrap（Table 1 的 t_CB 是 bootstrap
   口徑）；refined 點的 bootstrap SE / CI 留待 follow-up（若 narrative 需要）。

### 4.4b Codex review caveats（2026-06-11，CONDITIONAL_PASS）

Codex methodological review（gpt-5.4 high reasoning，verbatim 紀錄）：

1. **(HIGH) LR vs χ²(1) 是優化敏感性描述，非正式 nested test**：canonical / best_multistart / nm_continuation 都是同維度同模型不同初始化/優化路徑，不是 nested restriction；2(LL_refined − LL_canonical) 沒有 χ²(1) 漸近分布。本 README 的 FRAGILE/STABLE verdict 應理解為「優化敏感性 / multi-basin 證據」**descriptive label**，**不是統計顯著性檢定**。section 4.4 #3 已自承「'STABLE' 不代表 magnitude 良好識別」呼應此 caveat；正式 inference 留給 paper narrative 改寫時的 cluster bootstrap CI。
2. **(MED) NM polish 的 θ_EAV bound [-1e-2, 1e-2] 超出 multistart init 範圍 [1e-6, 5e-4]**：refined 候選集已非單純 multistart family，可能拉到 search-space 邊緣。實證上 best-multistart 與 NM-continuation 的 θ_EAV 接近（TW 6.84e-4 vs 6.84e-4 / US 5.34e-3 vs 5.25e-3 / JP 2.88e-3 從 NM 取），shift 都遠在 NM bound 內，**結論不被 bound mismatch 翻轉**；但 paper 文字若引用 refined 數字，應註明此 bound expansion。
3. **(MED) Basin K-means 只跑 seed=42 一次，沒有 multi-restart stability check**：basin A/B fraction 解讀（TW 0.87/0.13、US 0.59/0.41、JP 0.61/0.39）為單樣本 K-means partition，僅作視覺摘要用；basin mass 不應上升為 inference statement。

**綜合**：實作面 provenance / seed discipline / canonical reproduction / no-oracle-init 全過關（Codex LOW finding 明文確認）；本 audit 結論強度應降為「optimization sensitivity audit」而非「正式 LR 檢定」，ordering preserved 限定 in point estimates，magnitude robustness 留 follow-up bootstrap。

### 4.5 後續（主線程）

- [x] TW/US/JP canonical reproduction PASS（bit-exact）
- [x] 各市場 LR + FRAGILE/STABLE verdict
- [x] refined θ̂_EAV vs canonical（shift ratio）
- [x] US > JP > TW ordering 保持確認
- [x] basin 結構（A/B fraction、LL gap）
- [ ] Codex review → knowledge.json（主線程）
- [ ] Paper narrative 決策（Option A rewrite — 主線程，**本實驗不改 .tex**）；
      建議方向：tab:main_results footnote 更新 + §6.6.4 加 K1470 行 +
      'universal magnitude' → 'universal sign + preserved ordering' 重新定調

## 5. 防錯規則 checklist

- [x] Lookahead：lag 在 `_negll_numba` 內（`vix[t-1]`, `eav[t-1]`），verbatim 繼承
- [x] 所有隨機程序 seed 固定（base 42 / starts 43..142 / K-means 42）
- [x] Baseline 與 audit 同 spec、同 lag、同 call
- [x] 套件限制 ≠ 模型無效（自家 MLE，無套件依賴問題）
- [x] Pooled-MLE 必 100+ multistart（本實驗就是執行此規則）
- [x] 對稱 refinement（三市場同協議、同 seeds — 不會重蹈 K1216b asymmetric artifact）
- [x] 不改 paper .tex、不寫 knowledge.json（主線程負責）
