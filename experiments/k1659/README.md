# K1659 — 投資迷思驗證：「量先價行 / 爆量長黑是出貨」的跨市場延續性 + 經濟價值 + 穩健性檢定

**類型**：投資迷思驗證系列（迷思實驗室）
**主題**：成交量事件（爆量 / 爆量長黑）能否預測**隔日報酬方向**？
**前身**：`experiments/k1636/`（同主題，逐資產 next-day 方向 BH-FDR）

---

## 結論

**`myth_verdict = not_supported_as_next_day_direction_rule`**

「量先價行」（爆量預示方向延續）與「爆量長黑是出貨」（爆量大跌預示隔日續跌）在 SPY / QQQ / 0050.TW / 2330.TW（2010–2026）**均不成立**：

- **統計**：13 個 primary 檢定（4 資產 × 3 迷思臂 + 1 跨市場 pooled）做 BH-FDR 後，**沒有任何一個「與迷思方向一致」的格通過**（所有 q ≥ 0.39）。跨市場正確聚合（K1355：先按日期聚合再 HAC）的延續性下注平均報酬 = −1.2 bps，t = −0.19，p = 0.85（n = 543 事件日）——完全 null。
- **穩健性**：k × N 參數 grid 共 12 格，**0/12** 支持延續性（全部 |t| < 1.96）→ null 非 cherry-pick。
- **經濟價值**：等權四資產「量先價行」next-day long/short 策略淨 5 bps 換手成本後 **Sharpe = −0.47**，慘輸買進持有 **1.32**；「爆量長黑放空」出貨策略 **Sharpe = −0.58**。迷思若拿去交易是**虧錢**的。

**誠實 nuance（有趣的反向證據）**：美股大型股（SPY / QQQ）的「爆量價漲」日，隔日反而**偏跌**（QQQ 續漲率 lift = −24pp，raw p = 0.030，但 BH q = 0.39 未存活）——與「量先價行」相反，呈輕微**隔日均值回歸**，不是延續。這與 Campbell-Grossman-Wang（1993）「高量伴隨的價格變動較易反轉」一致。

**與 K1636 一致並強化**：K1636 已判方向迷思不成立；K1659 用跨市場正確聚合 + 經濟價值 + 全參數 grid 三個 K1636 未做的角度，把「不成立」從單資產統計推進到**可交易性層級的 null**。

---

## 與 K1636 的差異（為何不是重工）

K1636 做了：SPY/0050/2330 逐資產 × {高量日, 爆量長黑} → next-day 平均報酬 / 下跌機率，12 test BH-FDR + 連續回歸 + forward 5d RV。verdict = 方向不成立、波動會升。

K1659 **補齊 K1636 未做、且 `.claude/rules/experiments.md` 硬性要求的四件事**：

| # | K1659 新增 | K1636 是否有 |
|---|---|---|
| 1 | **跨「市場」正確聚合（K1355）**：先按日期 equal-weight 聚合 cross-asset 延續性報酬，再對日期序列 Newey-West HAC；stacked asset-day 僅列 diagnostic | ❌ 只逐資產 BH-FDR，未做 date-aggregate pooled |
| 2 | **「量先價行」= 延續性雙臂**：量增價漲→續漲 + 量增價跌→續跌 的方向 hit-rate（binomial vs unconditional baseline） | ❌ 只測「爆量偏跌」單臂 |
| 3 | **經濟價值**：next-day long/short 策略淨交易成本 Sharpe vs 買進持有；含出貨放空策略 | ❌ 純統計，無策略 |
| 4 | **參數穩健 k×N grid（12 格）+ 空頭次期間分割（2020/2022 崩盤、多/空頭 regime）** | ❌ 單一門檻，無 grid/regime |

新增第 4 資產 **QQQ**（美 2 + 台 2）讓跨市場聚合平衡。

---

## 動機與文獻

零售技術分析口訣把兩件事混為一談：成交量與當日價格變動的**同時關係**（真實存在），以及成交量是否能預測**下一天方向**（本實驗檢驗）。文獻反覆提醒兩者必須分開，且日頻方向預測性弱。

- **Karpoff (1987)**, *The Relation Between Price Changes and Trading Volume*, JFQA — price-volume 關係強，但主要是價格**變動幅度**與 volume 的**同時**關係，非隔日方向。
- **Campbell, Grossman & Wang (1993)**, *Trading Volume and Serial Correlation in Stock Returns*, QJE — 高量伴隨的價格變動**較易反轉**（liquidity/risk-premium 機制），與「量先價行=延續」相反；本實驗證實美股大型股確有此微弱反轉。
- **Llorente, Michaely, Saar & Wang (2002)**, *Dynamic Volume-Return Relation of Individual Stocks*, RFS — volume 對報酬自相關的效果依 information vs hedging trading 而異、逐股不同，無普世「爆量→續漲」規則。
- **Gervais, Kaniel & Mingelgrin (2001)**, *The High-Volume Return Premium*, JF — high-volume-return premium 是**週/月頻**現象，非日頻方向延續。
- **Lamoureux & Lastrapes (1990)**, *Heteroskedasticity in Stock Return Data: Volume versus GARCH Effects*, JF — volume 更像 volatility / 資訊到達 proxy，提醒把 **direction 與 volatility 分開**。

本專案相近知識：
- **K1636**：直接前身（同主題逐資產方向 null）。
- **K1355**：跨資產 pooled inference 不可把 asset-day 當 iid（本實驗遵守）。
- **K160 / K710**：volume-volatility 同時關係成立，但對 vol 的 lagged 增量極小、對 direction 更弱。
- **K948**：週頻 return 亦不可預測，vol targeting 才是正確方向。

---

## 資料

- **來源**：yfinance daily OHLCV，快取於 `experiments/k1659/data/`（SPY/0050/2330 由 K1636 快取複製、QQQ 新下載；均輕量日頻，非 heavy tick）。
- **樣本**：2010-01-04 至 2026-07-02/03，依資產可得日不同（每資產 ~4,000–4,150 交易日，遠超 ≥500 門檻）。
- **期間含空頭**：2020 COVID 崩盤、2022 升息熊市，均在樣本內並單獨分割檢驗。
- **標的**：
  - `SPY`（美股大盤 ETF）、`QQQ`（那斯達克 100 ETF）— 美國市場。
  - `0050.TW`（台灣 50 ETF）、`2330.TW`（台積電）— 台灣市場。
- **報酬**：`Adj Close` 的 `pct_change`（含股利/分割調整）。
- **0050.TW split 修正**：呼叫 `volpred.utils.clean_tw50_data` 修 yfinance 2014-01-02 假 −75% split artifact。
- **seed = 42**；bootstrap reps = 10,000。

---

## 方法

### 事件定義（有 justification，不 cherry-pick）

- **爆量（volume spike）**：`volume[t] > 2.0 × rolling_mean(volume, 20).shift(1)[t]`
  — 零售技術分析最常見定義「今日量 > 2 倍 20 日均量」。`rolling_mean` 用 `.shift(1)`，今日 volume **絕不進入自己的門檻**。
- **量增價漲（`hv_up`）**：爆量 且 `ret[t] > 0`（量先價行多頭臂）。
- **量增價跌（`hv_down`）**：爆量 且 `ret[t] < 0`（量先價行空頭臂）。
- **爆量長黑（`hv_black`）**：爆量 且 `ret[t] ≤ −2%`（出貨）。

### 目標與檢定

- **隔日方向 hit-rate**：事件 `signal.shift(1)` 對齊 `ret[t+1]`；conditional 命中率 vs **unconditional baseline**（up/down/continuation frequency）→ `scipy.stats.binomtest` + 10,000-rep bootstrap 95% CI。
- **延續性下注報酬**：爆量日 `sign(r_t) · r_{t+1}` 的均值 → Newey-West HAC（maxlags=5）t 檢定。
- **跨市場 pooled（K1355）**：每日先 equal-weight 聚合 cross-asset 延續性報酬 → 對日期序列 HAC。stacked asset-day 僅列 diagnostic。
- **經濟價值**：等權四資產 next-day long/short 策略，淨 5 bps/單位換手成本，年化 Sharpe（×√252）vs 買進持有。
- **多重檢定**：13 個 primary p-values 做 BH-FDR，只把「方向與迷思一致（lift>0）且 q<0.05」算支持。
- **穩健性**：k ∈ {1.5, 2.0, 2.5, 3.0} × N ∈ {20, 50, 100} 共 12 格重算 pooled t-stat。
- **Regime**：SPY 200 日 SMA（`.shift(1)`）分多/空頭 + 2020/2022 崩盤窗口。

### 防錯對照（依 `.claude/rules/experiments.md`）

- **Lookahead（最高優先）**：所有事件訊號一律 `signal.shift(1)` 對齊 `r[t+1]`（`next_ret_after` / 策略 position / 跨市場聚合 / regime 全部一致）；rolling volume 門檻 `.shift(1)`。**獨立 reviewer 逐 row 索引推導確認無 off-by-one**（見下）。
- **跨資產不當 iid**：K1355 date-aggregate then HAC；stacked 只 diagnostic。
- **Baseline 同對齊**：unconditional up/down/continuation frequency 為 null，binomial 對比。
- **seed 固定**：所有 bootstrap 用單一 `rng = np.random.default_rng(42)`。
- **不 cherry-pick**：k/N/threshold 有標準定義 + 全 grid robustness。
- **Null 如實報告**：迷思判定不成立，並如實記錄美股輕微反向 nuance。

---

## Code Review

- **Primary path（Codex）不可用**：`codex exec` 於 2026-07-08 撞 usage limit（`ERROR: You've hit your usage limit ... try again Jul 11`），屬外部額度 blocker，非 Codex 故障。
- **Sanctioned fallback**：改派 `feature-dev:code-reviewer` subagent 做 independent fresh-context review（同 K1259/K1261/K1262 fallback path）。
- **Reviewer verdict = `PASS`**：逐一具體追蹤 5 個計算 event-conditional 隔日報酬的函數（`next_ret_after` / `evaluate_asset` test D / `cross_market_pooled` / `continuation_strategy`·`distribution_short_strategy` / `regime_split`）的 `shift(1)` 對齊（row 級 `d_i` vs `d_{i-1}` 索引推導），確認無 lookahead、無 off-by-one、baseline 正確、K1355 聚合合規、HAC/BH-FDR/bootstrap 教科書正確、seed 完全可再現。無任何會改變 null 結論的 bug。
- **唯一非缺陷小註**：portfolio `active_day_hit_rate` 診斷欄位可能把「僅換手成本日」誤標為 active——僅影響該 diagnostic 欄，不影響 Sharpe/verdict。
- ⚠️ 依 K1259 教訓：Codex 額度 2026-07-11 恢復後，建議主線程用 primary-path Codex 二次驗證再標最終 closure（本 PASS 為 fallback bar，已達寫 knowledge 門檻）。

---

## 檔案

- `k1659.py`：完整可重跑實驗（signal.shift(1) 明確、seed=42）。
- `k1659_results.json`：全部統計量 + 期間 + n + p-value + verdict（byte-traceable）。
- `data/`：SPY / QQQ / 0050.TW / 2330.TW 日頻 OHLCV 快取。
- `fig1_next_day_hit_rate.png`：三迷思臂的隔日方向命中率 vs 無條件基準（95% bootstrap CI）。
- `fig2_cross_market_regime.png`：跨市場 + regime 延續性下注報酬（K1355 聚合 + HAC，t-stat 標註）。
- `fig3_economic_value.png`：量先價行策略 vs 買進持有累積淨值（淨成本）。
- `fig4_robustness_grid.png`：k×N pooled HAC t-stat heatmap（全格 |t|<1.96）。

## 復現

```bash
uv run python experiments/k1659/k1659.py
```

## Success criteria（全數達成）

- ✅ 三件套齊全（README / py / results.json + 4 圖）。
- ✅ Lookahead-clean（signal.shift(1) 明確 + 獨立 reviewer 逐 row 確認 PASS）。
- ✅ 跨市場聚合正確（K1355：date-aggregate then HAC）。
- ✅ 檢定口徑正確（binomial vs baseline + Newey-West HAC + BH-FDR）。
- ✅ 明確 verdict：**not_supported**（誠實 null，附反向 nuance）。
- ✅ 樣本 ≥500 / 資產、跨 2 市場、含 2020/2022 空頭。
