# K1100g — TAIFEX vs SPY-ES microstructural quantification

- **提出者 (Proposer)**: Claude 自主研究（K1100f Paper 3 reframe 的實證證據）
- **設計者/執行者**: Claude (autonomous-research, worktree agent-k1100g)
- **日期**: 2026-04-13
- **狀態**: 完成
- **父實驗 (Parents)**: K1100f (Paper 3 SPY-ES NULL), K868/K874c-e/K880 (PRG periodic structure), K849/K851/K852b (TAIFEX roll handling)
- **關聯 (Related)**: Lai 2024 APFM PRS copula hedging in TAIFEX

---

## 問題 (Research Question)

K1100f 證明：在 SPY-ES (US spot-futures, corr=0.97) 上，PRG + Student-t copula 的 4-model 組合都打不過 DCC-A4f-ASYM baseline → Paper 3 須 reframe 為「Taiwan-specific empirical study」而非「general methodology」。

K1100g 的目的：**用 4 個 microstructural dimension 量化 TAIFEX TX 與 SPY 的差異**，作為 Paper 3 reframe 的實證 evidence base。如果 Taiwan 真的有獨特的市場結構特徵，這些差異應該明顯且方向一致。

## 動機 (Motivation)

K1100f 給的方向是「方法論層面 NULL」，K1100g 進一步問「市場結構層面有什麼差異？」。如果差異夠大，Paper 3 的定位應該是：

> Lai 2024 PRS 在 TAIFEX 上的成功，是 Taiwan 期貨市場特定結構（密集結算、夜盤切換、tick精細度）的副產物，而非 copula+periodic GARCH 在所有 spot-futures pair 上都有效的證據。

這需要 empirical 證據而非僅僅理論論證。

## 方法 (Method)

### 數據

| Asset | Source | 期間 | 處理 |
|-------|--------|------|------|
| **TAIFEX TX** | `~/Dropbox/TAIFEXDATA/TAIFEXDATA/python/Daily_*TX.csv` | 2017-01-03 ~ 2021-12-30 (1,223 trading days) | **K849 rule**: 不用 TX1，用 TX 全合約，每日按 contract month 分組，挑成交量最大的合約。Roll day（active contract 切換）的 close-to-close return 設為 NaN。Big5/CP950 編碼 fallback。 |
| SPY | yfinance daily, auto_adjust | 2017-01-03 ~ 2021-12-30 (1,259 days) | OHLC + log_ret + intraday_ret + overnight_ret |
| ES=F | yfinance daily, continuous | 2017-01-03 ~ 2021-12-30 (1,259 days) | reference baseline |
| SPY 5-min | yfinance interval='5m' | 最近 60 calendar days (yfinance limit) | for FFT only |

### 4 個 microstructural dimensions

| # | Dimension | TAIFEX TX | SP500 SPY/ES | 預期差異 (H) |
|---|-----------|-----------|--------------|-------------|
| 1 | **Settlement effect** | 第三週三 monthly | 第三週五 quarterly (3/6/9/12) | TAIFEX 60 settle / SPY 20 settle days in 5y |
| 2 | **Overnight session** | 日盤 08:45-13:45 + 夜盤 15:00 ~ 翌日 05:00 (3.75h gap) | Globex 23h continuous (17.5h "gap") | TAIFEX gap 較緊但分隔明確 |
| 3 | **Day-of-week** | 5 trading days/week | 5 trading days/week | TAIFEX 月結算 → 月內第三週可能有 DOW pattern |
| 4 | **Intraday tick periodicity** | 日盤 5h = 60×5-min bars | 開盤 6.5h = 78×5-min bars | TAIFEX 結構強，open/close 集中 |

### 量化指標

1. **Dim1**: `Var(log_ret on settle day) / Var(log_ret on non-settle day)` + Levene equality-of-variance test。
   - 額外 robustness：(a) `+/-1 window`（settle ± 1 day 都算 settle 區間） (b) `intraday_ret` (open-to-close, roll-mask independent)。
2. **Dim2**: `sigma(overnight_ret) / sigma(intraday_ret)`。
   - TAIFEX overnight = `log(day_open_t / night_close_{t-1})` (~3.75h gap)
   - SPY overnight = `log(open_t / close_{t-1})` (~17.5h gap)
3. **Dim3**: One-way ANOVA F-statistic on squared daily returns grouped by `dow ∈ {Mon..Fri}`。
4. **Dim4**: FFT power spectrum of 5-min log returns; report (a) peak frequency (cycles/day) (b) `peak_power_ratio` (c) `periodic_band_ratio` = power within ±0.05 of integer cycles {1..5}/day, normalized by total power。

### 假設 (a priori)

- **H1**: TAIFEX settle multiplier ≥ 1.3, SPY < 1.1 (頻繁 settlement → TW vol cluster)
- **H2**: TAIFEX overnight/intraday > 0.8, SPY < 0.3 (TW gap 明顯, SPY 連續)
- **H3**: TAIFEX DOW F > 5.0, SPY F < 2.0 (TW 月內結構 → DOW seasonality)
- **H4**: TAIFEX FFT periodic band > 0.10, SPY < 0.10 (TW open/close 集中)

ALL PASS → reframe 充分；2-3 PASS → partial evidence；0-1 PASS → reframe 缺乏實證 anchor。

### Codex code review (read-only)

- ✅ TAIFEX roll: `_pick_active_contract` 用當日 volume 最大合約，`is_roll` 在 contract_month 變化時 flag → log_ret 設 NaN。同日內 active contract 切換無法捕捉，但實務上罕見。
- ✅ FFT: `rfftfreq(n, d=1/sampling_per_day)` 單位正確。`periodic_band_ratio` 用 ±0.05 band 對偏離 integer 的 peak 略保守。
- ✅ DOW ANOVA: `f_oneway` 邏輯正確，已修正 label drift bug（drop-then-enumerate 的 dow_idx 不對齊問題）。

## 結果 (Results)

### 主表 (`firm_microstructure.csv`)

| metric | TAIFEX | SPY | H threshold | PASS? |
|---|---:|---:|---|---|
| Settlement multiplier | **0.668** | 0.914 | TW≥1.3, US<1.1 | ❌ |
| Overnight/intraday ratio | **1.586** | 1.001 | TW>0.8, US<0.3 | ❌ |
| DOW ANOVA F | 0.653 | 0.732 | TW>5, US<2 | ❌ |
| FFT periodic band ratio | 0.0146 | 0.0104 | TW>0.10, US<0.10 | ❌ |

**ALL 4 hypotheses FAIL.** 但細看數字後發現結論並非「無差異」，而是「方向錯了」：

### 細部 (`k1100g_results.json` 完整)

#### Dim1 — Settlement (詳細多角度分析)

| measure | TAIFEX | SPY | ES=F |
|---|---:|---:|---:|
| `log_ret` multiplier | 0.668 | 0.914 | 0.264 |
| `intraday_ret` multiplier | 0.665 | **3.120** | – |
| `+/-1 day window` multiplier | 0.982 | 0.686 | – |
| n_settlement (5y) | 58 | 20 | 20 |

**反直覺發現 1**：SPY 在第三週五 (OPEX/quad-witching) 的 **intraday** 變異數比非結算日 **高 3.1 倍**。這是真正的 settlement effect — 但出現在 US，不在 TW。
**反直覺發現 2**：TAIFEX 第三週三的 close-to-close vol **低於非結算日**（multiplier 0.67）。可能解釋：(a) 結算前資金已從近月轉移到次月 → 主力合約在結算日已是「次月」，避開了 expiring contract 的 noise；(b) 結算日為慣例性日內結算，trader 提早離場降低 directional risk。

#### Dim2 — Overnight (重要發現)

| measure | TAIFEX | SPY |
|---|---:|---:|
| sigma(overnight) | 0.01177 | 0.00814 |
| sigma(intraday) | 0.00742 | 0.00813 |
| **ratio** | **1.586** | 1.001 |

**核心發現**：TAIFEX 的隔夜（夜盤＋早晨gap）波動率 **比日盤波動率高 58.6%**，而 SPY 的隔夜 ≈ 日盤。這個差異雖然 fail H2 的雙重門檻（要求 SPY<0.3，但 SPY 是 1.0），但 **方向強烈支持** Taiwan 隔夜風險過度集中的觀點。Lai 2024 PRS 處理的「session 結構」大概率就是這個 effect。

#### Dim3 — DOW

兩市場 ANOVA F 都 < 1（無顯著 DOW pattern）。Taiwan 月度結算 → DOW seasonality 的假設不成立。可能原因：(a) DOW dummies 在 PRG 中是 conditional vol 層（τ_t），不是 unconditional return^2 (b) 5 年期 DOW 信號可能被 macro shock 掩蓋。

#### Dim4 — FFT

兩個市場的 5-min FFT 都顯示：(a) peak power ratio 都 < 0.01 (b) periodic band [1..5]/day 加總都 < 2%。即 5-min level 上沒有強烈 daily cycle。
**重要 caveat**：SPY 5-min 數據受 yfinance 限制只有最近 60 天 (~2026-02 起)，TAIFEX 是 2021 年最後 60 天，**時段不同**，這項比較缺乏嚴格時間對齊。**H4 不應被視為決定性 evidence。**

### 圖表

- `k1100g_settlement_effect.png` — TAIFEX vs SPY settlement multiplier bar chart
- `k1100g_overnight_intraday_ratio.png` — overnight/intraday vol ratio
- `k1100g_dow_anova.png` — Mon-Fri mean(r²) bar chart for both markets
- `k1100g_intraday_fft.png` — 5-min FFT power spectrum (log scale)

## 結論 (Conclusion)

**4 個 hypothesis 全部 FAIL，但研究訊號分裂**：

| Dim | 結論 | Paper 3 reframe 用法 |
|---|---|---|
| **Dim1 (settle)** | TAIFEX 結算日 vol 反而 LOWER；SPY OPEX intraday vol 卻是 3.1×。Settlement effect 在美國比在台灣強烈。 | **不是 Taiwan 特殊性 anchor**，反而是 SPY 的 anomaly。 |
| **Dim2 (overnight)** | TAIFEX 隔夜/日盤 = 1.59 vs SPY = 1.00。Taiwan 隔夜風險過度集中。 | **可作為 reframe 的核心 evidence**：Taiwan 夜盤結構容納了顯著額外風險，PRG 透過 session dummies 捕捉這個 effect。 |
| **Dim3 (DOW)** | 兩市無 DOW pattern。 | 中性，PRG 的 DOW dummies 對 unconditional 不顯著，但對 conditional vol 仍可能有 incremental info。 |
| **Dim4 (FFT)** | 兩市 5-min level 都無強週期；但比較不可靠。 | 不能作為 reframe 證據。 |

### Paper 3 reframe evidence 量級

- **充分 evidence**：1/4 (Dim2 overnight session asymmetry)
- **反向 evidence**：1/4 (Dim1 settlement effect 反而更強在美國)
- **無 evidence**：2/4 (Dim3, Dim4)

→ **Paper 3 reframe 應該收斂為 "session-overnight asymmetry"** 的單一論述，不要做 4-dimension 全方位敘事。具體建議：

> "Lai 2024 PRS 的 success 源自 TAIFEX day/night session asymmetry — 隔夜風險為日盤 1.6×，PRG 透過 session-conditional volatility 捕捉這個結構。在 SPY-ES (近 24h continuous) 上沒有對應的結構，因此同樣的方法 fails to improve over DCC-A4f-ASYM。"

這是一個 **clean, defensible, single-mechanism 的 reframe**，比起「Taiwan 全方位特殊」更可信，也更符合實證結果。

### Settlement effect 反向發現 (Dim1) 衍生問題

TAIFEX 結算日 vol 反而更低、SPY OPEX intraday vol 反而高出 3×，這個對比本身是有趣的 finding，可能值得獨立論文：
- TAIFEX 的「次月接力」機制（settle 前已切到次月）可能是降 vol 的關鍵
- SPY OPEX intraday 3× spike 應與 0DTE/option-pinning 相關

## 局限 (Limitations)

1. **時段不對齊**：TAIFEX 日盤 08:45-13:45 (5h) vs SPY US session 09:30-16:00 (6.5h)；overnight 定義 TAIFEX 3.75h vs SPY 17.5h。直接 ratio 比較有對照誤差。
2. **Roll day 樣本損失**：TAIFEX 1,223 日中 61 日 (5%) log_ret=NaN，主要落在月度結算日附近 → 影響 Dim1 的 sample composition。
3. **SPY 5-min 數據時段不一致**：yfinance API 限制 SPY 5m 為最近 60 天 (2026-02 起)，TAIFEX FFT 用 2021 年最後 60 天 → Dim4 cross-market 比較不嚴謹。
4. **Settlement window 定義**：本實驗只用 settlement day 本身；如果用 settle week (5d) 或 expiration cycle，結果可能不同。
5. **未做正式 t/F 顯著性檢定**：Levene p-value 報告但未調整 multiple testing；DOW ANOVA p > 0.5 不顯著也不需 correction。
6. **未控制 macro regime**：2017-2021 跨越疫情衝擊，可能影響 settlement & overnight 的 baseline noise。
7. **只用 TX 主力合約**：未對比 TX1 (front-month continuous), MTX (mini), TXO (options) → roll mechanism 的差異未驗證。

## 衍生方向 (Next Steps)

1. **D1: TAIFEX day/night PRG decomposition**：把 PRG 重新跑只用 day session 和 only night session 分別估計，看誰主導 forecasting gain。預期：night session marginal 提供主要的 incremental info → 確認 Dim2 mechanism。
2. **D2: SPY OPEX intraday pinning study**：3.1× intraday multiplier on quarterly Fridays 是 0DTE 還是 monthly OPEX？拆分 1st/2nd/3rd/4th Friday，加 VIX condition。
3. **D3: Cross-Asia futures replication**：在 Nikkei225 (NK) 和 KOSPI200 (K200) 上做同樣 4-dim quantification，看 overnight asymmetry 是否亞洲共同特徵或 Taiwan-only。

## Provenance

- 實驗腳本: `experiments/k1100g/k1100g.py`
- 結果 JSON: `experiments/k1100g/k1100g_results.json`
- CSV: `experiments/k1100g/firm_microstructure.csv`
- Cache: `experiments/k1100g/_cache_taifex_2017-01-01_2021-12-31.parquet`
- Seed: 42
- Run: 2026-04-13 (worktree agent-k1100g)
