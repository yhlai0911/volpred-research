# K1380_v4 — Paper 9 horse-race loss generation and corrected SPA/RC

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
- Per-model valid masks for QLIKE; formal inference uses the intersection of
  ≥95%-coverage specs
- Stationary bootstrap B=499, seed=42
- Hansen studentization uses a stationary-bootstrap estimate of the long-run
  scale of `sqrt(T) * mean(d_t)`, not raw observation SD
- Finite Monte Carlo p-values use `(exceedances + 1) / (B + 1)`
- Harvey threshold |t| > 3.0

## Success Criteria

- `n_valid_spa > 1500`
- `≥ 12/17 models with coverage ≥ 95%`
- Script completes without `n_valid=0` error

## 2026-07-05 rerun（歷史紀錄；數值已被 2026-08-02 重跑取代）

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
- The historical fields labelled Hansen SPA and White RC were later proven to
  be mislabelled and are not valid evidence. They are retained only in Git
  history and the 2026-07-29 audit below.

## Output

- `k1380_v4_results.json` — model fit receipts, coverage, rankings, and explicitly
  non-canonical raw-scale diagnostics
- `k1380_v4_losses_all.npy` — (17, n_oos) QLIKE loss matrix
- `k1380_v4_rc_correction_results.json` — canonical SPA/RC/Holm inference
- `run_pipeline.py` — only canonical entrypoint; runs both stages and emits one
  full-chain reproduce spec

## Paper Linkage

**Paper 9** (`paper/garch-x-vix/`), Critical Issue C3:
> "17-specification ranking requires multiple testing correction (White RC / Hansen SPA)."

K1380_v4 addresses C3 only through `k1380_v4_rc_correction_results.json`; the
base result deliberately does not issue a C3 verdict.

## Related

- K1380 (original, 3× failed), K988 (GARCH-X horse race baseline)
- Triggered: `3-strike trigger 2026-05-22` per CLAUDE.md Three-Strike Rule

---

## ⚠️ 2026-07-29 資料窺探修正（RC/SPA 重新分析）

2026-07-05 版本的 `k1380_v4_results.json` 中，`white_rc_test` 與
`hansen_spa_test` **兩個欄位都被錯誤標示**，且方向相反。當時的原件可由 Git history
與 `gate_history/` 回收；現行 base artifact 已由修正後 producer 完整重生，並永久移除這些
失實欄位，不能再稱為 07-05「未修改原件」。

| 欄位 | v4 宣稱 | 實際是什麼 |
|---|---|---|
| `white_rc_test` p=0.000 | 「A4f significantly beats GJR **after RC correction**」 | **單一 spec 的 bootstrap DM t 檢定，完全沒做窺探修正**（`k1380_v4.py:771-782`：`max(0.0, t_b_a4f)` 是對純量取 max，不是跨候選集合取 max）→ **高估** |
| `hansen_spa_test` p=0.2886 | 「Hansen SPA，不拒絕 H0」 | 每個 spec 都用自己的 d-bar 重新置中 = **least-favourable 的 SPA_u**（studentized White RC），不是 Hansen 建議回報的 consistent SPA_c → **低估** |

**2026-07-29 修正的有效範圍**：當時只處理 RC/SPA 誤標，所以從已保存的 17×n_oos
QLIKE 矩陣純重新分析即可；修正腳本以 4 項 base 數字的**逐位重現**（atol=1e-12）作為
前置斷言。2026-08-02 後續 audit 又發現 A5/C-series 的上游模型實作錯誤，因此舊矩陣與
其所有數字已失效，必須重跑 GARCH horse race；這不推翻前述統計診斷，而是擴大修復層級。

**關鍵證據（least-favourable 尾部歸因）**：499 次 bootstrap 中有 144 次超過觀測統計量，
而這 144 次的 max **全部**由 A5(t=-11.2) / C2(t=-21.1) / C3(t=-10.0) 三支
「比 benchmark 差 10-21 個標準差」的 spec 取得（77/48/19），**沒有任何一次**由具競爭力的
spec 取得。v4 的「不顯著」量到的是這三支的退化程度，不是候選集合的競爭力 —— 這正是
Hansen SPA_c 要移除的保守性。

**當時的修正結論（已被 2026-08-02 全量重跑取代）**：SPA_c 拒絕 H0；但其
studentization 仍使用 raw observation SD，且用 `p=0` 表示有限 bootstrap，兩者皆已在
下節修正。此段只保留問題演進，不是現行數字。

⚠️ 這**推翻**了先前「真正做了多重檢定修正的檢定沒有拒絕」的讀法 —— 因為當時被當成
「有做修正」的那個 SPA 數字本身也是錯的。

**當時遺留（2026-08-02 已定位）**：A5/C2/C3 的極端 QLIKE 損失來自下節所列 optimizer
與跨頻率 likelihood 缺陷；它們不能被解讀為模型本身的實證表現。

## Output（更新）

- `k1380_v4_results.json` — 現行模型結果與非正式 raw-scale diagnostics；不是歷史原件
- `k1380_v4_losses_all.npy` — (17, n_oos) QLIKE 損失矩陣
- `k1380_v4_rc_correction_results.json` — **窺探修正後的 canonical RC/SPA 數字**

---

## 2026-08-02 A5/C1-C3 model-integrity closure

上一節的「遺留待查」已定位為實作錯誤，不是三支模型真的差 10–21 個標準誤：

- **A5**：外層 Nelder-Mead 宣告了正向 VIX slope bounds，但實際呼叫沒有傳入 bounds，
  結果選擇器也接受 optimizer failure。第一個 2,000 日 window 實際選到
  `theta1=-0.35099`；修正後同 window 為 `theta1=+0.13040`。
- **C1/C2/C3**：舊 likelihood 只有 `K+1` 筆日報酬（7／13／25），並把月頻 lag row
  直接配給日頻 return；C1 因 `<10` gate 結構上永遠 0 coverage。新實作以日期映射將
  每筆 eligible 日報酬對齊前 K 個完整月份的 mean log-VIX；full-history repair 讓第一個
  window 的 C1/C2/C3 都使用完整 2,000 筆日 likelihood，並把短期 GARCH state 濾到
  training tail。
- **共同防線**：所有 bounded multi-start fits 只接受 successful、finite、in-bounds、
  non-penalty iterate；預測月排除 partial current-month VIX，state recursion 依 fixed-span
  MIDAS Eq.4 使用當月 `tau_t`。

完整 OOS 與 RC/SPA 結果一律以本輪重新產生的
`k1380_v4_results.json`、`k1380_v4_losses_all.npy` 與
`k1380_v4_rc_correction_results.json` 為準。K1583 的舊 MCS 結論已標為 `SUPERSEDED`，
必須以新矩陣重跑後才能引用。

**最終完整重跑 read-back（1,900 OOS days，1,397 秒）**：A5/C1/C2/C3 coverage 都是
99.89%，各有 31/31 successful finite in-bounds refits；相對 B0 的 raw-scale diagnostic
t-stat 分別為 +2.617／+2.844／+2.261／+2.394，舊的極端負值與 C1 0 coverage 已消失。
B1/B2/B3 在 scheduled refit 被拒時不再沿用 stale state；31 次中分別 24/23/29 次成功，
coverage 76.68%／73.42%／93.26%，因此依預先存在的 95% gate 排除。其餘 13 支候選與 B0
共同有 `n_valid_spa=1,898`。

正式推論以 stationary-bootstrap mean distribution 估計 long-run omega；SPA_l/c/u、
max-type White RC 均為 `p=0.0020`（0/499 exceedances 經 plus-one convention），Holm FWER
0.10 下 13/13 拒絕，A4f adjusted `p=0.0260`。least-favourable bootstrap 0/499 draws
超過觀測統計量，舊 A5/C2/C3 上尾歸因不再存在。`run_pipeline.py` 是唯一 canonical
entrypoint；base/correction 子腳本單獨執行會 fail closed。每個 stage output 是 atomic，
但 multi-file chain 不是 set-level transaction；中斷後舊 spec/commit 與新輸出 hash 不符，
artifact gate 會 fail closed。B0 benchmark 同樣先清 stale state，31/31 refits 成功並有
receipt。成功 full-chain 的 `reproduce_spec.json` runtime 為 1,400 秒並 hash-bind兩階段
程式、資料、helpers、loss matrix、base result 與 canonical result。
