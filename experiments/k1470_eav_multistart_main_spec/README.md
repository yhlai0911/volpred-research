# K1470 — Main Table 1 Spec (K1145/K1147/K1150) 100-Multistart Re-estimation

> **TL;DR**: paper/eav-universal-magnitude 的主 Table 1（TW/US/JP 三市場 pooled
> θ_EAV）是 default single-init BCD 估計。§6.6.4 multistart audit（K1213/K1216/
> K1216b/K1216c）證明同 family spec 有 panel-wide two-basin pathology（10/10
> markets FRAGILE）。K1470 對主三市場 **原 BCD spec（N=30/31 全 panel）** 跑同
> 協議 ≥100-multistart 重估，回答：canonical θ̂_EAV 是否在 inferior basin？
> US>JP>TW magnitude ordering 是否保持？

[提出: Claude（§6.6.4 mandated re-run，body.tex:598-607 明文標註）, 執行: compute_queue worker]

- Status: **queued → compute_queue**（見下方 job id）
- Verdict: PENDING（待 compute job 完成）

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
# 全量（compute_queue worker 跑）
uv run python experiments/k1470_eav_multistart_main_spec/k1470.py

# smoke test（單市場、少 starts）
K1470_N_STARTS=2 K1470_MARKETS=TW uv run python experiments/k1470_eav_multistart_main_spec/k1470.py
```

- 每市場跑完即寫 checkpoint `k1470_results_partial.json`（long-job 安全）
- 產出：`k1470_results.json` + `k1470_multistart_<MKT>.csv` ×3 +
  `k1470_basin_hist_<MKT>.png` ×3

## 4. 結果（PENDING）

待 compute_queue job 完成後由主線程 followup 填寫：

- [ ] TW/US/JP canonical reproduction PASS?
- [ ] 各市場 LR + FRAGILE/STABLE verdict
- [ ] refined θ̂_EAV vs canonical（shift ratio）
- [ ] US > JP > TW ordering 是否保持
- [ ] basin 結構（A/B fraction、LL gap）
- [ ] Codex review → knowledge.json（主線程）
- [ ] Paper narrative 決策（Option A rewrite — 主線程，**本實驗不改 .tex**）

## 5. 防錯規則 checklist

- [x] Lookahead：lag 在 `_negll_numba` 內（`vix[t-1]`, `eav[t-1]`），verbatim 繼承
- [x] 所有隨機程序 seed 固定（base 42 / starts 43..142 / K-means 42）
- [x] Baseline 與 audit 同 spec、同 lag、同 call
- [x] 套件限制 ≠ 模型無效（自家 MLE，無套件依賴問題）
- [x] Pooled-MLE 必 100+ multistart（本實驗就是執行此規則）
- [x] 對稱 refinement（三市場同協議、同 seeds — 不會重蹈 K1216b asymmetric artifact）
- [x] 不改 paper .tex、不寫 knowledge.json（主線程負責）
