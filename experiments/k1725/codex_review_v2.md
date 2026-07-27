# K1725 Codex Review v2

## 審查範圍與結論

審查角色：資深計量金融 code reviewer  
審查日期：2026-07-27  
本輪 claim surface：

- `experiments/k1725/k1725.py`
- `experiments/k1725/README.md`
- `experiments/k1725/k1725_results.json`

另讀取 `experiments/k1725/codex_review_v1.md`，逐項追蹤 v1 的 B1–B4。三個 claim
surface 均未修改；除逐行審查外，另以 frozen local cache 做只讀重算，沒有執行會覆寫
`k1725_results.json` 的 `main()`。

**裁決：PASS。** v1 的四個 blocking defects 均已實質修復，現行結果可由 frozen code 與
cache 重現；README 主表、指定 robustness 數字及 `NULL` verdict 與 JSON 一致。仍有數項
nonblocking 的 schema／hardening／措辭問題，列於後文，但沒有任何一項改變本次估計或
`NULL` 結論。

## v1 blocking defects 逐項複核

### B1 — 不完整終端週、日層級部分日與 gap return：已修復

#### 程式路徑

- `k1725.py:183-190` 先計算 close-to-close log return，再以
  `gap == pd.Timedelta(hours=1)` 過濾。第一根與任何 gap 後跨多小時的 return 都設為
  NaN 並排除。
- `k1725.py:368-378` 在所有正式週分析前套用
  `weekly["n_bars"] >= MIN_WEEK_BARS`；`MIN_WEEK_BARS=160` 定義於 `:69`。
- primary、sup-Wald、Chow、R1、R2、R3 全部引用 gate 後的同一個 `weekly`
  （`:407-421, 449-470`），沒有旁路使用 gate 前樣本。
- R4 日層級集中度在 `:472-480` 套用 `MIN_DAY_BARS=20`。

#### 只讀重算證據

- 週數由 237 降至 236，唯一剔除的是 `2026-07-27`：
  `n_bars=9`，三桶 share 為 `(US, non-session, weekend)=(0,1,0)`。
- 保留週的 `n_bars` 範圍為 166–169；三桶中沒有任何 exact 0 或 exact 1 share。
  因此 v1 所見的 9-bar 極端週不再驅動 logit。
- US primary post 樣本由 v1 的 133 降至 132。修正後 R2 US logit
  `p=0.396577`；weekend logit `p=0.038769` 且方向為上升，與 JSON 一致。
- 日資料由 1,192 日降至 1,190 日；剔除資料起點的 `2021-12-31`（4 bars）及終端
  `2026-07-27`（9 bars）。前者本來就在分析窗口外，後者不再污染 R4。
- raw index 唯一實質 gap 的下一根為 `2023-03-24 14:00 UTC`，index diff 為 2 小時；
  該 timestamp 確實不在 `build_bucketed_returns()` 的有效 `r2` bars。

JSON 的 `complete_week_gate={min_week_bars:160, weeks_before_gate:237,
weeks_after_gate:236, partial_weeks_dropped:1}`、`n_weeks_total=236` 與上述重算完全一致。

**B1 判定：CLOSED。** 本次 frozen 樣本的 partial terminal week 已真正排除，logit 不再由
0/1 週機械性驅動，gap 後 return 亦已移除。

### B2 — sup-Wald 15% trim、合法 argmax 與 critical value：已修復

`sup_wald_break()`（`k1725.py:288-327`）目前使用：

```python
lo = ceil(n * trim)
hi = floor(n * (1 - trim))
for k in range(lo, hi + 1):
```

只讀獨立重算得到：

- `n=236`
- 合法 index range `[36, 200]`
- 左尾最少 `36/236=15.254%`
- 在最大合法 index 時，右尾亦為 `36/236=15.254%`
- 合法候選數 165
- argmax `k=74`，在合法區間內
- `break_date=2023-06-19`
- `sup-F=9.495967`

上述與 JSON 的 `sup_wald_break_us_session.{n, legal_break_index_range,
break_index, break_date, sup_f}` 完全一致。候選 F 使用

```text
((SST - SSE) / 1) / (SSE / (n - 2))
```

對 intercept-only 單一 mean shift 而言，restriction 數為 1、unrestricted parameter
數為 2，故分母自由度 `n-2` 正確。

程式同時保留 Andrews (1993) 5% 值 8.85，並以 Andrews (2003) corrigendum、
`p=1`、15% trim 的 8.68 作 `significant_5pct` 判定（`:312-322`）。9.495967 同時高於
8.68 與 8.85；目前顯著性不是由非法候選點產生。2003 corrigendum 原表亦確認該格為
8.68：

- Donald W. K. Andrews (2003), *Tests for Parameter Instability and Structural Change
  With Unknown Change Point: A Corrigendum*, Econometrica 71(1), 395–397:
  https://users.ssc.wisc.edu/~behansen/718/Andrews2003.pdf

**B2 判定：CLOSED。** legal break set、argmax、樣本輸入及 5% 判定均正確。

### B3 — directional/compositional verdict gate：已修復

`k1725.py:523-565` 的 PASS gate 現在實際要求：

1. raw primary US-session 方向上升；
2. primary Welch、R1 event-buffer Welch、R2 logit Welch 的 US 規格皆在 5% 顯著；
3. weekend 或 non-session 至少一桶如預期下降；
4. weekend 不得反向上升。

這與本輪明定的 compound gate「US direction up + 三個主窗口 US 規格皆顯著 +
至少一抵銷桶下降 + 週末不反向」一致。它不再可能因三個顯著的 US 下降而 PASS，也不會在
weekend 上升時 PASS。

Frozen JSON 的實際 checks 為：

- `us_direction_up=true`
- `primary_us_welch_sig5pct=false`
- `event_buffer_us_welch_sig5pct=false`
- `logit_us_welch_sig5pct=false`
- `weekend_direction_down_as_predicted=false`
- `non_session_direction_down_as_predicted=true`
- `weekend_contradicts_clean_hypothesis=true`

因此 PASS 條件明確失敗；primary Welch 與 bootstrap 又都沒有 US 顯著支持，所以落入
`NULL`，與 `conclusion.verdict` 一致。`CONDITIONAL_PASS` 被保留給只有 primary US 正向且
有 nominal primary evidence、但未通過完整 robustness/composition gate 的情況，沒有冒充完整
複合假說 PASS。

**B3 判定：CLOSED。**

### B4 — overclaim、logit 單位與 robustness 編號：blocking overclaim 已修復

README 已做下列實質修正：

- `README.md:66-72,130-134` 把 sup-Wald 降格為 assumption-heavy 的樣本內最強
  mean-shift 候選，只讀位置；明寫不能證明唯一斷點或排除次級斷點。
- `:135-138,159-166` 對 2022 regime 只稱「可能混淆」，並明寫不能歸因於 IBIT；
  known date 重合本身不是證據，研究是 observational event-window，不是因果識別。
- `:155-156` 明寫未剔 NYSE 假日的偏誤方向未知，不再宣稱必然偏保守。
- `:76-82` 的 robustness 編號已統一為 R1 event buffer、R2 logit、R3 extended pre、
  R4 daily。
- `:77-78,140-141` 把 logit 效應標為 log-odds；README 使用的 US 差
  `+0.094` 是 `-0.348614 - (-0.442872)`，單位與數值正確。
- non-session 只稱 exploratory secondary evidence，並明示未做三桶 joint /
  multiple-testing inference（`:144-149`）。

**B4 判定：CLOSED（blocking 層級）。** 原 v1 指出的「證明真斷點」、2022/IBIT 歸因、
假日偏誤方向與日期重合證據等過度宣稱均已移除。

## README 與 results JSON 數字逐項 reconciliation

| 項目 | README 報告 | JSON／只讀重算 | 判定 |
|---|---|---|---|
| Data hygiene | 40,044 bars、缺 1、0.0025%、236 完整週、剔 1 週 | `rows_raw=rows_after_dedup=40044`、`missing_bars=1`、`missing_bar_fraction=2.5e-05`、237→236 | 一致 |
| US primary | 0.399→0.418、+1.86pp、t=0.77、p=0.441、d=0.15、CI [−0.021,+0.059] | +1.855134pp、t=.774766、p=.441017、d=.146977、CI [−.021364,.059324] | 一致 |
| non-session primary | 0.463→0.417、−4.61pp、t=−1.89、p=0.063、d=−0.38、CI [−0.083,−0.011] 排除 0 | −4.605968pp、t=−1.892591、p=.062698、d=−.375182、CI [−.082897,−.011472] | 一致 |
| weekend primary | 0.137→0.165、+2.75pp、t=1.61、p=0.110、d=0.26、CI [−0.005,+0.060] | +2.750834pp、t=1.614814、p=.109519、d=.256745、CI [−.004985,.059971] | 一致 |
| sup-Wald | 2023-06-19、F=9.50、crit=8.68、距 IBIT −206d | F=9.495967、同日期、同距離、`significant_5pct=true` | 一致 |
| R1 US | +1.44pp、p=0.572 | +1.434992pp、p=.571643 | 一致 |
| R2 logit US | +0.094 log-odds、p=0.397 | post−pre=.094258、p=.396577 | 一致 |
| R2 logit weekend | p=0.039，方向上升、反假說 | p=.038769；post log-odds 高於 pre | 一致 |
| R3 US | +3.88pp、p=0.025 | +3.882049pp、p=.024937 | 一致 |
| R3 non-session | −5.29pp、p=0.002 | −5.290252pp、p=.001884 | 一致 |
| Chow@IBIT | F=5.43、p=0.021 | F=5.427501、p=.020674 | 一致 |
| R4 daily | +2.96pp、p=0.068、bootstrap CI 含 0 | +2.959972pp、p=.067816、CI [−.005681,.064372] | 一致 |
| Serial dependence | acf1=0.097、LB(4) p=0.031 | .097289、.030908 | 一致 |

表格、核心敘述與 knowledge draft 的重複數字均使用正確四捨五入。沒有會影響判定的
overclaim、underclaim 或數字不符。

## 統計方法複核

### Welch 與 Cohen's d

- `ttest_ind(post, pre, equal_var=False)` 正確使用 Welch–Satterthwaite 檢定；t 的符號與
  post−pre 一致。
- Cohen's d 使用兩組 sample variance 的 pooled SD，分子為 post−pre，公式正確。
  在 Welch 不等變異框架旁使用 pooled d 應解讀為描述性 standardized effect size，而非
  重新引入等變異的顯著性假設；README 的使用方式符合此界線。

### Circular block bootstrap

- pre 與 post 各自作 circular block resampling，index 以 modulo wrap-around，最後截回原
  樣本長度；兩組再取 mean difference，實作正確。
- `B=5000`、`seed=42`、`L≈round(n^(1/3))`；主樣本 block lengths 4/5 與 JSON 一致。
- percentile CI 是合理的弱相依 mean-difference sensitivity，但 block length 是 heuristic，
  且三桶沒有 joint/multiplicity inference。README 已把唯一排除 0 的 non-session 結果限制為
  exploratory，沒有超過此方法能支持的強度。

### sup-Wald／Chow

- mean-only break 的 restricted model 有 1 個 intercept，unrestricted model 有 2 個
  segment intercepts；`q=1`、denominator df=`n-2`，sup-F 與 Chow 公式均正確。
- Chow 的獨立重算為 `F(1,234)=5.427501, p=.020674`，pre/post n=104/132。
- Chow 與 sup-F 都是 classical pooled SSE，沒有 HAC／heteroskedasticity-robust
  inference；週序列 LB(4) 拒絕無自相關，因此其 nominal inference 不是精確的 robust
  結論。程式、JSON 與 README 都已如實標為 assumption-heavy。
- Chow 使用 2 年 extended pre，而 primary Welch 使用 1 年 pre，不能視為完全相同樣本的
  cross-check；README 已揭露 Chow 混入 2022 regime，沒有把它提升為主證據。

### Serial-dependence diagnostic

程式在 IBIT split 前後分別 demean，再計算 lag-1 correlation 與 Ljung–Box lag 4。
只讀重算與 JSON 的 `acf1=.097289`、`LB p=.030908` 一致。這是適當的警示診斷；它不能自行
修正 classical break inference，而 README 也沒有宣稱已修正。

## Lookahead、RV 對齊與窗口邊界

- 本研究比較同期 realized RV shares，沒有 forecasting origin、predictive signal、交易
  position 或 P&L。因此沒有 `signal.shift(1)` 的適用對象；README 的 lookahead 說明成立。
- Binance open time 為 `t` 的 bar，其 close 約位於 `t+1h`。程式的
  `log(C_t/C_{t-1})` 對應 current bar 的 `[t,t+1h)` 價格變動；以 current bar 的 open time
  做 ET bucket label 沒有一小時 off-by-one。
- UTC-aware index 經 `America/New_York` 轉換，DST mapping 正確。近似只來自 1h grid
  對 09:30–16:00 RTH 的半小時邊界，不是 DST 近似。
- primary 依 Monday week label 分割，`2024-01-08` crossing week 全歸 pre。這不是隱藏的
  off-by-one：README `:64-65,163` 已明示，且 R1 ±4週 buffer 移除 crossing week 後 US
  仍不顯著。因此它是設計限制，不推翻本次 `NULL`。

## `verdict=NULL` 複核

`NULL` 是誠實且正確的 failure-to-support 結論：

- 主 US 效應只有 +1.86pp，Welch `p=.441`，block-bootstrap CI 含 0。
- R1 US `p=.572`、R2 logit US `p=.397`，沒有主窗口 robustness 支持。
- weekend 反而 +2.75pp；R2 logit 下更呈名義顯著上升，直接反對 clean
  ETF-clock 方向。
- non-session 的 bootstrap CI 雖排除 0，但 Welch `p=.063`，又未做 compositional joint /
  multiplicity inference；降格為 exploratory 合理。
- R3 與 Chow 的 nominal significance 使用含 2022 的較長 pre 樣本，且 break inference
  受序列相依限制。
- endogenous 最強候選距 IBIT −206 天，沒有提供事件附近斷點位置支持。

因此不能升級為 PASS 或 CONDITIONAL_PASS。較精確的口語是「主複合假說未獲支持」，而不是
證明 effect 恰為零；README 已提供完整 p-value、CI、反向 weekend 與方法限制，使現行
`NULL` 不構成隱瞞 null uncertainty。

## Remaining findings

### Blocking defects

**無。**

### Nonblocking hardening／措辭事項

1. **bar-count gate 不是嚴格 calendar-closure gate。** `MIN_WEEK_BARS=160` 可能在週日晚、
   尚未完整收盤但已累積 160–166 根時放行；`MIN_DAY_BARS=20` 同理可能放行 20–23 根的部分日。
   本次 frozen run 的 9-bar 終端週／日確實被剔除，所以不影響本輪結果；未來若要求 intraweek
   rerun 穩定性，宜再加「period 已閉合」判定。
2. **`redistribution_check.is_redistribution_toward_rth` 名稱仍易誤導。** 其 predicate 是
   `US↑ AND (weekend↓ OR non-session↓)`，所以 frozen JSON 同時出現
   `is_redistribution_toward_rth=true` 與 `weekend_contradicts_clean_hypothesis=true`。
   README 已醒目警告且正式 verdict gate 不使用此欄作 PASS，故不是本輪 blocker；machine
   consumer 面建議日後改名或改為完整 conjunctive predicate。
3. **R2 JSON 的 `diff_pp` schema 仍不理想。** generic `welch_test()` 把 logit post−pre
   乘 100，因此 US `diff_pp=9.4258`，而真正 log-odds 差是 `+0.094258`。README 用的是正確
   +0.094，JSON 也有 `_scale_note`，p-value/verdict 不受影響；但欄名仍可能被下游誤讀，
   宜另設 `diff_log_odds` 或避免在 logit 規格沿用 `diff_pp`。
4. **兩句 robustness 敘事可再精確。** README `:135` 的「名義顯著性只出現在……」宜限定為
   「支持 US↑ 的名義顯著性」，因 R2 weekend 另有反方向 nominal significance；
   `:141` 的「raw +1.86pp 對 logit 不穩健」宜改成「logit 規格同樣不顯著」，因 raw 與
   logit 都是正向且不顯著。上下文已列出 weekend p=.039、raw p=.441、logit p=.397，
   故目前不會扭轉讀者對 `NULL` 的理解。
5. **「假說不成立」宜作 failure-to-reject 表述。** README 同時提供「於常規顯著水準」、
   p-value、CI 與完整 caveats，實質結論是未獲支持而非接受精確零假說。這是措辭精度問題，
   非方法或 verdict blocker。

FINAL_VERDICT: PASS
