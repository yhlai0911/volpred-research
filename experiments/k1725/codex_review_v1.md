# K1725 Codex Review v1

## 審查範圍與裁決

審查角色：資深計量金融 code reviewer  
審查日期：2026-07-27  
claim surface（均已逐行完整讀取，未修改）：

- `experiments/k1725/k1725.py`
- `experiments/k1725/README.md`
- `experiments/k1725/k1725_results.json`

另以本地 frozen cache 做只讀重算；沒有執行會覆寫 results 的 `main()`。

**裁決：FAIL。** 主結論採 `NULL` 的方向是克制的，主要 Welch 數字、weekend 反向結果及
`conclusion.one_line` 大致忠實對應 JSON；但目前有四組 blocking defects：

1. 不完整終端週被當成完整週納入所有檢定，正式估計與 logit robustness 受機械性污染。
2. sup-Wald 的 15% trim 下界 off-by-one；報告的最大值恰好來自不合 15% 條件的候選點，
   修正後 `F=8.455`，不再達 5% 顯著。
3. machine-derived PASS gate 只查三個 US-session p-value，不查方向，也不查
   weekend/non-session，無法機械化它聲稱判定的複合假說。
4. README 把不穩健的單斷點掃描寫成「已證明真斷點」，進一步作 2022 regime 歸因；
   limitations 又宣稱假日污染必然偏保守、known date「重合」支持假說，均超出證據。

在修正程式、重跑 results 並同步收斂 README 前，不可合併或對外發布。

## Blocking defects

### B1 — 未排除不完整最後一週，違反主要週資料設計

`k1725.py:349-353` 的註解說要保留「full-ish weeks」，實作卻只有
`weekly.index >= EXTENDED_PRE_START`，沒有任何完整週、bar 數或三桶均已觀測的 gate。

JSON 顯示資料截至 `2026-07-27T12:00:00+00:00`。該日是星期一；轉成 ET 後，最後一個
Monday-labelled week `2026-07-27` 只有 9 根（ET 00:00–08:00）：

| week | bars | US-session share | non-session share | weekend share |
|---|---:|---:|---:|---:|
| 2026-07-27 | 9 | 0.000 | 1.000 | 0.000 |

它仍進入 post `n=133`、primary、event-buffer、logit、extended-pre、Chow 與 sup-Wald。
這直接違反 README `48-53`「一週同時含三桶、聯合非退化」的設計前提。三 share 仍會代數上
加總為 1，因此 `consistency_shares_sum_to_one.passed=true` 無法偵測這個錯誤。

只移除這個不完整週的重算：

| 桶 | 報告值 diff / Welch p | 移除 partial week |
|---|---:|---:|
| US-session | +1.54pp / 0.525 | +1.85pp / 0.441 |
| non-session | −4.17pp / 0.096 | −4.61pp / 0.0627 |
| weekend | +2.63pp / 0.126 | +2.75pp / 0.109 |

`NULL` 沒有反轉，non-session bootstrap CI 也仍排除 0；但正式外報數字不是由可比的完整週樣本
產生。更嚴重的是 logit 對 0/1 share 先 clip 到 `1e-6/1-1e-6`，這個 9-bar 週變成極端
log-odds，導致：

- US logit：報告 `p=0.963`；移除後 `p=0.397`。
- weekend logit：報告 `p=0.252`；移除後為顯著上升 `p=0.0388`，方向仍反對原假說。

因此 README `129-130` 所稱「logit 下 US 效應歸零」在數值上主要受不完整週驅動。此缺陷也使
結果依腳本在一週內何時執行而漂移，屬 blocking method defect。

### B2 — sup-Wald 15% trim off-by-one，報告的顯著斷點不成立

`k1725.py:282-287` 使用：

```python
lo = floor(n * 0.15)
hi = ceil(n * 0.85)
for k in range(lo, hi):
```

當 `n=237` 時，`lo=35`，但 `35/237=14.77%`；若宣稱兩端各 trim 15%，首個合法 split
應為 `ceil(35.55)=36`。JSON 的 argmax 恰好是這個不合法的 `k=35`：
`2022-09-19, F=10.180, significant_5pct=true`。

只讀重算結果：

| 規格 | argmax | sup-F | 與 5% critical 比較 |
|---|---|---:|---|
| 現行 code（含 partial week、k≥35） | 2022-09-19 | 10.180 | 顯著 |
| 嚴格 15%（含 partial week、k≥36） | 2022-09-26 | 8.455 | **低於 8.85，不顯著** |
| 嚴格 15% 且移除 partial week | 2023-06-19 | 9.493 | 顯著，但日期大幅改變 |

故 JSON `96-105`、README `121-127` 的斷點日期、顯著性與「dominant structural break」
對一個無經濟意義的終端 partial week 及 rounding 極敏感。即使沿用 code 的 1993 臨界值
8.85，合法樣本的 8.455 也不顯著；Andrews 2003 較精確的 `p=1, trim=15%` 5% 值為
8.68，結論仍相同。

F 統計量本身對「intercept-only、單一 mean shift」的候選 split 是正確的；blocking defect
在掃描集合與其造成的錯誤顯著性，不在 `F=((SST-SSE)/1)/(SSE/(n-2))` 公式。

### B3 — verdict gate 沒有判定所宣稱的假說

README `6-8` 與 JSON `conclusion.primary_hypothesis` 的假說是：

> US-session share 上升，且 weekend / non-session share 下降。

但 `k1725.py:479-489` 的 PASS 只要求：

```text
primary US Welch p<.05
AND event-buffer US Welch p<.05
AND logit US Welch p<.05
```

它不查三個 US 效應是否為正，也不查 weekend/non-session 方向或顯著性。因此：

- 三次「US 顯著下降」也會得到 PASS。
- US 三次顯著上升、但 weekend 顯著上升，仍會得到 PASS。
- `CONDITIONAL_PASS` 同樣只查顯著性、不查方向。

本次三關都是 false，所以 frozen JSON 的 `NULL` 恰好正確；但這個 gate 並不合理，也不能稱為
primary hypothesis 的 mechanical derivation。至少須將正方向與宣稱的 compositional
redistribution 條件納入，或把 verdict 明確縮窄為「US share 單變量結果」。

### B4 — 對斷點、成因與偏誤方向的文字超出證據

README `124-127` 稱 sup-Wald「已證明真斷點在此」，並據此把 extended-pre 顯著性
「歸因於 2022 regime 而非 IBIT」。這在 B2 修正前已不成立；即使掃描正確，單一 mean-shift
argmax 也只能說「樣本內最強候選點不靠近 IBIT」，不能證明唯一真斷點、排除第二個較小斷點，
或識別 2 年 Welch 顯著性的成因。README `121-123` 把日期對應到 Ethereum Merge / pre-FTX，
同樣沒有事件歸因設計。

另有兩個對外會誤導的 limitations 句子：

- README `142-143`：未剔 NYSE 假日「偏保守，不會誇大」。偏誤方向取決於假日 crypto RV
  及 pre/post 假日構成，不能保證只會稀釋。
- README `148-149`：「斷點與 IBIT 時點重合支持假說」。known breakpoint 是研究者事前固定，
  日期重合本身不是證據；本實驗的主 US 檢定不顯著，endogenous argmax 又不靠近 IBIT。

「非因果」標籤本身有揭露，但上述確定性／因果語句抵銷了這項 caveat，須改成
「可能受 2022 regime 混淆；不能歸因」。

## 七項指定風險逐項查核

### 1. Lookahead 與 RV bar 對齊 — PASS（另有微小 gap 限制）

- `k1725.py:179-185` 的 Binance `C_t` 是 open_time 為 `t` 的 bar 在該小時末的 close。
  `ln(C_t/C_{t-1})` 因此涵蓋 current bar 的 `[t,t+1h)` 價格變動；按 current bar 的
  `open_time=t` 分桶是正確的，沒有一小時 off-by-one。
- 本研究使用同期 realized variance share 描述 pre/post 結構，沒有 forecast origin、
  predictive signal 或 trading P&L；README `78-87` 所述「無 `signal.shift(1)` 適用對象」
  成立。
- 唯一缺根為 `2023-03-24 13:00 UTC`。下一根 `14:00 UTC` 的 diff 實際是 2 小時 return；
  兩段皆在 ET 09:00–11:00 RTH，因此本次沒有跨桶誤分，但它不再是嚴格 1h RV。
  建議未來對 gap 後 return 設 NaN，或至少把此處列為限制。此點單獨不 blocking。

### 2. DST／時段映射 — PASS

- UTC-aware index 經 `tz_convert(ZoneInfo("America/New_York"))` 轉 ET，DST 處理正確。
- `weekend = dow>=5`；`RTH = not weekend AND hour∈{9,...,15}`；
  `non-session = not weekend AND not RTH`，三桶互斥且窮盡。
- 全部 40,043 個有效 return 都恰有一個 bucket，無 null label。
- 只讀抽查：2023 spring-forward 週有 167 bars（weekend 47），fall-back 週有 169 bars
  （weekend 49）；weekday RTH 始終為 35 bars，符合 ET wall-clock 定義。
- `zoneinfo` 的 DST 轉換不是近似；近似的是 1h grid 對 09:30–16:00 RTH。
  `{9..15}` 實際多含 09:00–09:30 的半小時 pre-open。

### 3. Share 一致性 — PASS，但完整週 gate 缺失

- nested `np.where` 使每根 bar 只進一桶。
- `pivot_table(..., aggfunc="sum")` 後 reindex 三欄，沒有漏桶或 double count。
- `total_rv` 正是三桶 RV 之和；正 total 後三 share 代數上恆等於 1。
- JSON 最大偏差 `2.220446049250313e-16` 與重算一致。
- 這個 consistency check 只驗證 composition identity，不驗證該週是否完整；B1 的
  `(0,1,0)` partial week 仍會通過。

### 4. 統計檢定 — 部分 PASS；sup-Wald inference FAIL

#### 公式正確部分

- Welch：`ttest_ind(post, pre, equal_var=False)` 使用 Welch–Satterthwaite 推論；
  t 的符號是 post−pre，與 JSON 一致。
- Cohen's d：以兩組 sample variance 的 pooled SD 標準化 post−pre，公式正確。
- circular block bootstrap：pre/post 各自獨立 circular resampling、wrap-around 正確；
  `B=5000`、`seed=42`、`L=round(n^(1/3))`。主樣本 block 長度 4/5 與 JSON 一致。
- Chow／候選 split 的 intercept-only mean shift：restricted model 1 個 intercept，
  unrestricted model 2 個 intercept，restriction 數 `q=1`，故
  `F=((SST-SSE)/1)/(SSE/(n-2)) ~ F(1,n-2)`；公式與自由度正確。

#### 推論限制／錯誤

- sup-Wald 掃描集合的 15% trim 錯誤，且改變顯著性：見 B2。
- 8.85 是 Andrews 1993 較舊的模擬值；2003 corrigendum 的較精確 5% 值為 8.68。
- QLR／Chow 均使用 classical pooled SSE，沒有 HAC 或 heteroskedasticity robustness。
  只讀診斷顯示 candidate-break residual 的 Ljung–Box lag-4 `p=0.040`；IBIT split 的
  Brown–Forsythe `p=0.0149`，故 iid／等變異假設並非無害。它們最多應列為
  assumption-heavy cross-check，不宜寫成「證明」。
- Chow 使用全部 extended pre（104 vs 133），primary Welch 使用 1 年 pre（52 vs 133），
  因而不是同樣本的直接 cross-check。README `127` 後段有揭露 full 2y，這點不單獨 blocking。

### 5. 窗口切分與事件週 — 有邊界污染；R1 使其不單獨推翻 NULL

`split_pre_post()` 比較的是 Monday week label，不是 underlying bar timestamp。因此：

- 實際 primary pre labels 為 `2023-01-16` 至 `2024-01-08`，不是逐 bar 的
  `[2023-01-11, 2024-01-11)`。
- `2024-01-08` 事件週整週進 pre；168 根中有 101 根位於 `2024-01-11 00:00 UTC` 後，
  cutoff 後 RV 佔該週 51.23%。
- 該週 US share 為 0.5346，高於 pre 平均。移除事件週後，US 主結果由
  `+1.54pp, p=.525` 變成 `+1.81pp, p=.461`；再移除 partial last week則為
  `+2.12pp, p=.384`。方向仍不顯著。

R1 的 bounds 確實移除斷點前後各四個 Monday-labelled weeks，包含整個事件週；US 仍
`+1.11pp, p=.663`。因此事件週錯置會使主估計偏向 NULL，也使 README 的窗口文字不精確，
但在已有 R1 的情況下不單獨改變最終 `NULL`。應刪除 crossing week 或明示 primary 是
week-label convention。

### 6. 敘事誠實性 — 主表誠實；斷點／因果文字 FAIL

#### 與 JSON 一致、處理正確

- **(a) US-session 主檢定不顯著：有如實陳述。** README `108,114-115` 與 JSON 一致：
  0.3993→0.4147、+1.5401pp、Welch `p=.5251`、`d=.1188`、bootstrap CI
  `[-.02526,.05589]` 含 0。
- **(b) weekend 上升且反對假說：有醒目揭露。** README `110,117-120` 與 JSON 一致：
  +2.6270pp、`p=.1263`，並標出 `weekend_contradicts_clean_hypothesis=true`。
- **frozen verdict `NULL`：與現行 checks 一致。** primary／buffer／logit 三個 US p-value
  都不顯著；主結果也未通過 bootstrap。只是 PASS gate 的一般邏輯不合理，見 B3。
- **(d) `is_redistribution_toward_rth=True` 沒有被 README 當成支持假說。**
  README `119-120` 明確寫「不可據此宣稱假說成立」，此處敘事誠實。

#### 必須修正

- `is_redistribution_toward_rth` 的 predicate 只要求 `US↑ AND (weekend↓ OR non-session↓)`，
  不要求顯著，也容許 weekend 上升；名稱本身易誤導 machine consumer。應改名為純方向描述，
  或改成與完整假說一致的 conjunctive condition。
- QLR「證明真斷點」、2022 成因歸因及 limitations 的過度語句：見 B4。
- README `129` 的「−0.70 logit-pt」單位錯誤。JSON `diff_pp=-0.703` 是 generic helper
  將真正 log-odds mean difference `−0.00703` 乘 100；logit 尺度沒有 percentage point。
- robustness 編號不一致：方法段 logit=R3、extended-pre=R4，但結果段寫成 R2、R3。
- README `175` 稱 non-session 為「唯一站得住的訊號」略強：Welch `p=.096`、
  buffer `p=.174`、logit `p=.612`，且未做三桶 joint／multiple-testing inference。
  可誠實稱為「exploratory secondary evidence」。

`conclusion.one_line` 的主 Welch、bootstrap、weekend 方向及 frozen robustness p-value
敘述與 JSON 相符；但它所依賴的 partial-week 與 QLR 數字有 B1/B2 的底層錯誤，所以不能因
字面一致就視為可發布。

### 7. 資料限制 — 大項有列出，但兩個方向性聲明不誠實

README 有明示：

- 1h bar 對 9:30 RTH 的半小時近似；
- 未剔 NYSE 假日；
- 單一交易所 Binance；
- 主 pre 僅 1 年、extended pre 混入 2022 regime；
- observational event-window、非嚴格因果。

缺失／錯誤：

- 未揭露最後一週不完整且被納入（B1）。
- 未揭露 crossing event week 被歸 pre（第 5 節）。
- 「未剔假日必然偏保守、不會誇大」沒有依據（B4）。
- 「斷點與 IBIT 時點重合支持假說」把事前固定的 known date 當成資料證據（B4）。
- 「DST 近似」名稱不準；DST 映射正確，近似的是 RTH half-hour grid。

## 建議的最低修正 gate

1. 僅保留完整 ET Monday–Sunday weeks；至少要求預期 bar 數並對 DST 週容許 167/169，
   或以明確 week-end cutoff 排除當週。對 gap 後 return 設 NaN。
2. 以合法 break fractions 建 QLR 候選集合，更新 Andrews critical value／假設說明，
   重跑全部 results；對 serial dependence 至少做 robust／bootstrap sensitivity。
3. verdict 明確檢查正方向；若 verdict 名稱代表完整 ETF-clock 假說，必須同時要求
   weekend/non-session 的預定方向與適當 joint inference。
4. 主規格排除 crossing event week，或將 week-label convention 明示並把 buffered
   specification 升為主要佐證。
5. 移除「證明真斷點」「歸因 2022」「假日必然偏保守」「日期重合支持假說」等超證據文字；
   修正 logit 單位與 robustness 編號。
6. 從修正後程式重新產生 JSON，再逐字同步 README；不可手改結果數字。

## 外部方法參考

- Donald W. K. Andrews (1993), *Tests for Parameter Instability and Structural Change With
  Unknown Change Point*, Econometrica 61(4), 821–856:
  https://cowles.yale.edu/sites/default/files/2022-08/d0943.pdf
- Donald W. K. Andrews (2003), *Tests for Parameter Instability and Structural Change With
  Unknown Change Point: A Corrigendum*, Econometrica 71(1), 395–397:
  https://users.ssc.wisc.edu/~behansen/718/Andrews2003.pdf

## 最終裁決

**FAIL — 有 blocking method defects 與會誤導對外結論的 overclaim，現況不可合併。**

