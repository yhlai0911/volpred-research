# K1380_v4 — Paper 9 White RC / Hansen SPA Test (3-Strike Refactor)

## Background

K1380 failed 3 times with `n_valid=0` due to joint mask logic. This is the mandated 3-strike
refactor with root-cause fixes.

**Three-Strike trigger**: K1380 v1/v2/v3 all produced `n_valid=0` because `np.all(..., axis=0)`
required ALL 17 models to have non-NaN forecasts at the same OOS step. When any MIDAS model
failed to converge at certain refit windows, the joint mask collapsed to empty.

## Root-Cause Fixes Applied in v4

| # | Fix | Root Cause |
|---|-----|-----------|
| 1 | Per-model valid_i masks (not joint valid_all) | Joint mask: any MIDAS NaN → zero valid obs |
| 2 | SPA/RC restricted to specs with coverage ≥ 95% | Ineligible models polluted joint mask |
| 3 | Per-model NaN/coverage diagnostic prints | Silent failure: only showed aggregate n_valid=0 |
| 4 | MIDAS B-series lag matrix via slicing (no np.roll) | np.roll wraps first K rows with tail data |

### Fix 4 Detail: np.roll lag matrix bug

**Old code** (K1380):
```python
lv_mat = np.column_stack(
    [np.roll(tr_lv, k+1)[(K+1):] for k in range(K)]
)
tr_ret_k = tr_ret[(K+1):]
```
`np.roll(tr_lv, k+1)` wraps around: first k+1 positions contain tail data.
Taking `[(K+1):]` removes only K+1 rows — lag K-1 (k=K-2, shift=K-1) still has 1 contaminated row at position 0. Off-by-one on row count too: gives `ntr-K-1` rows instead of `ntr-K`.

**Fixed code** (K1380_v4):
```python
lv_mat = np.column_stack([tr_lv[K-1-k:ntr-1-k] for k in range(K)])
tr_ret_k = tr_ret[K:]
```
Column k = lag k+1: `tr_lv[K-1-k : ntr-1-k]`. No wrapping, correct `ntr-K` rows.

## Method

- Same 17-spec horse race as K1380 (A1-A5, A2f/A4f/A3f/A2n/A4n, B1-B3, C1-C3, B0)
- OOS: 2019-01-01 onward, rolling W=2000, refit_every=63
- Per-model valid masks for QLIKE; SPA uses intersection of ≥95%-coverage specs
- Stationary bootstrap B=499, seed=42
- Harvey threshold |t| > 3.0

## Success Criteria

- `n_valid_spa > 1500`
- `≥ 12/17 models with coverage ≥ 95%`
- Script completes without `n_valid=0` error

## 2026-07-05 rerun

Task `experiment_k1380v4_rerun_atomic_results_c5` reran v4 after fixing the
truncated-results failure mode:

- Results JSON now writes to `k1380_v4_results.json.tmp`, validates with
  `json.load`, then atomically replaces the final file with `os.replace`.
- Snapshot duplicate dates are de-duplicated at load time (`10` duplicate rows
  dropped, keep last).
- QLIKE direction now matches the project canonical Patton form:
  `actual_r2 / forecast_variance - log(actual_r2 / forecast_variance) - 1`.
- Fresh rerun completed in `934.5s`; `n_valid_spa=1879`, `15` non-benchmark
  specs met the 95% coverage threshold; C1 remained ineligible at 0% coverage.
- Hansen SPA: `p=0.2886`, so the joint data-snooping null is not rejected.
- A4f White RC: `t=4.1335`, `p=0.0000`, so A4f beats GJR in the targeted RC
  comparison.
- Verdict remains `C3 MIXED`: the paper needs nuanced data-snooping discussion,
  not a blanket claim that the full 17-spec horse race survives SPA.

## Output

- `k1380_v4_results.json` — SPA/RC test results + per-model coverage
- `k1380_v4_losses_all.npy` — (17, n_oos) QLIKE loss matrix

## Paper Linkage

**Paper 9** (`paper/garch-x-vix/`), Critical Issue C3:
> "17-specification ranking requires multiple testing correction (White RC / Hansen SPA)."

K1380_v4 resolves C3 by providing valid SPA + RC test results under corrected per-model masks.

## Related

- K1380 (original, 3× failed), K988 (GARCH-X horse race baseline)
- Triggered: `3-strike trigger 2026-05-22` per CLAUDE.md Three-Strike Rule

---

## ⚠️ 2026-07-29 資料窺探修正（RC/SPA 重新分析）

`k1380_v4_results.json` 的 `white_rc_test` 與 `hansen_spa_test` **兩個欄位都被錯誤標示**，
且方向相反。修正產物：`k1380_v4_rc_correction.py` → `k1380_v4_rc_correction_results.json`。
v4 原始 results JSON **未被修改**（永遠修流程，不修資料）。

| 欄位 | v4 宣稱 | 實際是什麼 |
|---|---|---|
| `white_rc_test` p=0.000 | 「A4f significantly beats GJR **after RC correction**」 | **單一 spec 的 bootstrap DM t 檢定，完全沒做窺探修正**（`k1380_v4.py:771-782`：`max(0.0, t_b_a4f)` 是對純量取 max，不是跨候選集合取 max）→ **高估** |
| `hansen_spa_test` p=0.2886 | 「Hansen SPA，不拒絕 H0」 | 每個 spec 都用自己的 d-bar 重新置中 = **least-favourable 的 SPA_u**（studentized White RC），不是 Hansen 建議回報的 consistent SPA_c → **低估** |

**為什麼不需要重跑 GARCH**：`k1380_v4.py:693` 在任何檢定之前就存下完整 17×n_oos QLIKE
矩陣，缺陷完全在該產物的下游，屬純重新分析。修正腳本內建 4 項 v4 數字的**逐位重現**
（atol=1e-12）作為前置斷言，重現失敗即中止 — 沒有這道檢查，後面的修正數字無從取信。

**關鍵證據（least-favourable 尾部歸因）**：499 次 bootstrap 中有 144 次超過觀測統計量，
而這 144 次的 max **全部**由 A5(t=-11.2) / C2(t=-21.1) / C3(t=-10.0) 三支
「比 benchmark 差 10-21 個標準差」的 spec 取得（77/48/19），**沒有任何一次**由具競爭力的
spec 取得。v4 的「不顯著」量到的是這三支的退化程度，不是候選集合的競爭力 —— 這正是
Hansen SPA_c 要移除的保守性。

**修正後結論**：SPA_c p < 1/499（fixed-omega 與 v4 的 per-resample studentization
**兩種慣例下皆然**，故非 studentization 選擇的產物）；Holm step-down 在 FWER 0.10 下
15 支中 11 支拒絕，A4f adj p < 1/499。**聯合窺探修正後的檢定拒絕 H0**。

⚠️ 這**推翻**了先前「真正做了多重檢定修正的檢定沒有拒絕」的讀法 —— 因為當時被當成
「有做修正」的那個 SPA 數字本身也是錯的。

**遺留待查**：A5/C2/C3 的極端 QLIKE 損失本身可能是數值退化。SPA_c 依統計理由捨棄它們；
但若它們根本是壞的，就不該出現在候選集合裡。兩條路徑導向同一修正結論，但成因仍需查明。

## Output（更新）

- `k1380_v4_results.json` — v4 原始（RC/SPA 欄位已被上表取代，保留供稽核）
- `k1380_v4_losses_all.npy` — (17, n_oos) QLIKE 損失矩陣
- `k1380_v4_rc_correction_results.json` — **窺探修正後的 canonical RC/SPA 數字**
