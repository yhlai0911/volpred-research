# K901 Code Review v2

## VERDICT: CONDITIONAL PASS

## Previous FAIL Issues — Resolution Status
### Issue 1: GJR-GARCH convergence failures silently swallowed — FIXED
Line(s): 227-238, 262-264, 269-300, 302-307, 425-432, 640

Code snippet:
```python
try:
    model = arch_model(r_scaled, vol='GARCH', p=1, o=1, q=1,
                     mean='Constant', dist='normal')
    res = model.fit(disp='off', show_warning=False)

    if res.convergence_flag != 0:
        n_failed += 1
        warnings.warn(
            f"GJR rolling window end={end_idx}: convergence_flag={res.convergence_flag} — excluded",
            RuntimeWarning, stacklevel=2
        )
        continue
...
except Exception as e:
    n_failed += 1
    warnings.warn(f"GJR rolling window end={end_idx}: {e}", RuntimeWarning, stacklevel=2)
```

```python
return {
    'results': results,
    'n_attempted': n_attempted,
    'n_converged': n_converged,
    'n_failed': n_failed,
}
```

Assessment: 前版 FAIL 的核心問題已解除。全域 `warnings.filterwarnings("ignore")` 已移除，`bare except: pass` 已改為 `except Exception as e` 並 `warnings.warn(...)`，且 `convergence_flag != 0` 的視窗會被排除、不再進入 summary。`n_attempted / n_converged / n_failed` 也有落到結果結構與 config 註記中。

### Issue 2: Bootstrap Sharpe CI missing fixed seed — FIXED
Line(s): 91-93, 310-332, 637-638

Code snippet:
```python
N_BOOTSTRAP = 5000      # for Sharpe CI
BOOTSTRAP_SEED = 42     # fixed seed — reproducibility rule
```

```python
def bootstrap_sharpe_diff(ret1, ret2, n_boot=N_BOOTSTRAP, seed=BOOTSTRAP_SEED):
    ...
    rng = np.random.default_rng(seed)
    diffs = []
    for _ in range(n_boot):
        idx = rng.choice(n, size=n, replace=True)
```

```python
"bootstrap_seed": BOOTSTRAP_SEED,
```

Assessment: 這個修正是完整的。seed 不只宣告，還真的傳進 bootstrap 函式預設值並用 `default_rng(seed)` 建立 RNG，結果 JSON 也有寫出 `bootstrap_seed`。

## Additional Checks
### Lookahead Bias — OK
Line(s): 177-185

Code snippet:
```python
raw_signal = VT_NUMERATOR / vix_series
raw_signal = raw_signal.clip(upper=MAX_WEIGHT)

# LAG the signal by 1 day — this is the critical anti-lookahead step
signal = raw_signal.shift(1)  # signal.shift(1) — NO LOOKAHEAD

# Drop the lagged NaN (first day); portfolio starts from day 2 for semantic correctness
signal = signal.dropna()
```

Assessment: `signal = raw_signal.shift(1)` 明確存在，方向正確。對於 return date `t`，實際用到的是 `VIX_{t-1}`。

### DM Test Direction — ISSUE
Line(s): 409-414; `src/volpred/stats/model_evaluation.py:83-87, 141-151`

Code snippet:
```python
dm_stat, dm_pval = strategy_dm_test(
    vt_ret[:n_dm],
    bh_ret[:n_dm],
    h=1,
    loss_fn="negative_return"
)
```

```python
if loss_fn == "negative_return":
    loss1, loss2 = -r1, -r2
...
d = np.asarray(loss1, dtype=np.float64) - np.asarray(loss2, dtype=np.float64)
```

Assessment: 這裡不是「VT minus BH，所以正值代表 VT 較好」。實際上在 `negative_return` 下，`d = (-VT) - (-BH) = BH - VT`，因此 **負的 DM t-stat 才代表 VT 較好，正的 t-stat 代表 BH 較好**。目前表格與任何口頭解讀若把正號當成 VT better，會寫反。`0/13` 個 `|t|>3.0` 的顯著性計數因為用了絕對值，不受這個符號問題影響。

### Silent Failure Paths — MINOR
Line(s): 232-238, 262-264, 274-300, 406-418, 250-252

Code snippet:
```python
if res.convergence_flag != 0:
    n_failed += 1
    warnings.warn(...)
    continue
...
except Exception as e:
    n_failed += 1
    warnings.warn(...)
```

```python
if not (np.isfinite(gamma) and np.isfinite(tstat)):
    n_failed += 1
    continue
```

```python
except Exception as e:
    print(f"  DM test failed: {e}")
```

Assessment: 前版那種研究致命的「靜默吞掉 GJR 失敗」已經修正，不再是 FAIL。剩下兩個較弱的寬鬆路徑：一是 `gamma/tstat` 非有限值時只計入 `n_failed`、不附帶 warning；二是 DM test 失敗時只 `print` 後繼續執行，該市場會留下 `NaN`。這些不算完全 silent，但仍偏寬鬆。

### Data Alignment — ISSUE
Line(s): 362-370, 182-196, 375-379, 408-420

Code snippet:
```python
mkt_ret = merged[col_mkt].pct_change()
shy_ret = merged[col_shy].pct_change()
vix_level = merged[col_vix]

valid_idx = mkt_ret.index[1:]
mkt_ret = mkt_ret.loc[valid_idx]
shy_ret = shy_ret.loc[valid_idx]
vix_level = vix_level.loc[valid_idx]
```

```python
signal = raw_signal.shift(1)
signal = signal.dropna()
common_idx = mkt_ret_series.index.intersection(shy_ret_series.index).intersection(signal.index)
...
return compute_metrics(port_ret, name), port_ret, common_idx
```

```python
bh_metrics, bh_ret = run_bh(mkt_ret, f"{ticker} B&H")
vt_metrics, vt_ret, vt_idx = run_vt(mkt_ret, shy_ret, vix_level, f"{ticker} VT")
...
n_dm = min(len(vt_ret), len(bh_ret))
dm_stat, dm_pval = strategy_dm_test(
    vt_ret[:n_dm],
    bh_ret[:n_dm],
```

Assessment: `VIX` 對 return date 的對齊本身是正確的，先把價格序列 inner join，再在 return 序列上做 `shift(1)`。但 **BH 與 VT 的比較樣本沒有用相同日期集合**。`VT` 因 lag/dropna 少一天，`vt_ret` 對應的是 `d2..dN`；`bh_ret[:n_dm]` 則是 `d1..dN-1`。這會影響：

- `sharpe_diff = vt_metrics['sharpe'] - bh_metrics['sharpe']`：兩者 sample 不完全相同
- `strategy_dm_test(vt_ret[:n_dm], bh_ret[:n_dm], ...)`：逐日配對錯位一天
- `bootstrap_sharpe_diff(vt_ret, bh_ret)`：兩者樣本窗也不完全相同

這個錯位只有一天，通常不太可能把「13/13 MDD 改善、0/13 Sharpe 改善、0/13 |DM|>3」整體型態翻盤，但它確實是應修的比較邏輯問題。

### show_warning=False — ACCEPTABLE
Line(s): 230, 272

Code snippet:
```python
res = model.fit(disp='off', show_warning=False)
```

Assessment: 在目前這版，`show_warning=False` 是可接受的，因為真正研究風險已由 `convergence_flag` 檢查、`warnings.warn(...)`、以及「非收斂視窗直接排除」控制住。它會隱藏 `arch` 套件內部 warning 的 console 噪音，但不再造成前版那種假裝所有視窗都正常的問題。若之後需要更細的 optimizer 診斷，再考慮把 warning 類型結構化寫入結果。

## Summary
前版兩個 FAIL 項目都已實質修正：GJR 非收斂不再被靜默吞掉，bootstrap 也已固定 seed，因此原本的 reproducibility / convergence 研究違規已解除。`signal.shift(1)` 的 anti-lookahead 實作也正確，13/13 市場 MDD 改善、0/13 市場 Sharpe 改善這種 null pattern 在策略邏輯上是合理的，並不顯示有明顯 lookahead bug。  

不過目前仍有兩個需要修的比較層面問題：DM 統計量符號解讀與文件直覺相反，以及 BH/VT 在 DM、bootstrap、Sharpe diff 上的樣本日期錯開一天。基於這兩點，我給 `CONDITIONAL PASS`，建議修正並重跑後，再決定是否寫入 `knowledge.json`。

## Issues Requiring Action (if any)
- MAJOR, `experiments/k901/k901_international_vt_13markets.py:409-414` and `src/volpred/stats/model_evaluation.py:141-151`, DM sign interpretation is reversed relative to "positive = VT better". Required fix: explicitly document `negative t = VT better`, or invert/report the statistic consistently if Table 5 expects `VT - BH`.
- MAJOR, `experiments/k901/k901_international_vt_13markets.py:375-420`, BH and VT comparison windows are off by one day. Required fix: align BH returns to `vt_idx` before computing Sharpe diff, DM test, and bootstrap Sharpe CI; then rerun the experiment.
- MINOR, `experiments/k901/k901_international_vt_13markets.py:250-252, 416-418`, some failure modes are only counted or printed. Required fix: add a structured warning/review flag when DM fails or when finite-parameter checks fail without convergence warnings.
