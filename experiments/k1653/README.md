# K1653 — 成交量能否預測「隔日報酬方向（漲跌 sign）」？

**技術分析迷思實驗室｜量能篇**

## 動機（散戶迷思）

散戶技術分析最常見的兩條「量能」信仰：

1. **「量先價行」** — 成交量放大 / 量增，價格會跟著漲（量是價的先行指標）。
2. **「爆量長黑是出貨」** — 出現「爆量 + 大跌長黑K」代表主力出貨，隔天會續跌。

本實驗把這兩條迷思拆成可檢定的假說，用嚴格的方向性統計檢定（不看圖下結論）驗證成交量到底能不能預測**隔日報酬的方向（漲/跌 sign）**。

## 與既有 K 的差異化（正交角度，非重複）

已有 volume 相關 prior，但**全部測 volume → 波動率**；K1653 測的是 volume → **報酬方向（price direction / sign）**，是全新未覆蓋的角度：

| K | 測什麼 | 結論 |
|---|--------|------|
| K710 | Volume as Vol Predictor（volume → **波動率**） | incremental R²=0.0023 beyond VIX |
| K753 / K754 | Volume Exhaustion Effect（extreme volume → future **VIX/波動率**） | extreme volume 不預測未來波動率 |
| **K1653（本實驗）** | volume → 報酬 **方向 / sign** | 見下方 verdict |

**本實驗測 return DIRECTION (sign)，與 K710/K753/K754 測 volatility 正交。**

## 資料

| 資產 | ticker | 期間 | 樣本數 |
|------|--------|------|--------|
| TW0050（台灣 50 ETF） | `0050.TW` | 2015-01-06 ~ 2026-07-06 | 2,796 |
| SPY（S&P 500 ETF） | `SPY` | 2012-01-04 ~ 2026-07-06 | 3,645 |

- 來源：yfinance daily OHLCV（`auto_adjust=True`）。
- TW0050 起始選 2015-01-01 以**避開 2014-01-02 的 1:4 split 斷點**（`volpred.utils.clean_tw50_data` 亦套用作雙保險），避免假報酬 / 假量能跳點污染。
- 兩資產樣本數均遠超 ≥500 門檻，且各含至少一次空頭（2015-16、2018、2020、2022）。

## 方法

**Target**：`sign(close-to-close daily return)`（隔日漲=+1 / 跌=−1）。

**防錯（Lookahead 最高優先）**：
- 所有 volume 訊號一律 `signal.shift(1)` —— 第 `i` 列的預測子取自第 `i−1` 日（昨日已收盤、完全 realized）的量特徵，預測第 `i` 日的報酬方向。等價於「今日觀察到的量預測明日方向」。程式碼有明確 `.shift(1)`（迷思 1 三訊號 + logistic X + subperiod；迷思 2 event study 用 `ret.shift(-1)` 取事件日的隔日報酬，等價 `event.shift(1)`）。
- Horizon **H=1**（單日 ahead），無 overlapping target，檢定 horizon = 1。
- 所有隨機程序固定 **seed=42**。

**迷思 1（量先價行）檢定**（全樣本 directional test）：
- 訊號 (a) 量增 `vol_change = log(V_t/V_{t-1})` sign 規則（量增→預測漲）
- 訊號 (b) 量能水準 `vol_ratio20 = V_t / MA20(V)` high 規則（量 > 中位數→預測漲）
- 訊號 (c) 量 z-score `vol_z60` sign 規則
- 訊號 (d) logistic regression（多元量特徵 + 昨日報酬 → P(up)），in-sample + expanding-window OOS refit
- 每個訊號報：directional hit-rate、**binomial test** vs 50%、**Pesaran-Timmermann (1992)** directional test

**迷思 2（爆量長黑續跌）event study**：
- 爆量長黑日(t) = 當日 volume 在**過去 252 日 top decile**（`vol_pct252 ≥ 0.90`）**且** 當日報酬 < 門檻（−1% / −2%）**且** 長黑K（close < open）
- 看這些日子的**隔日(t+1)** 報酬分佈 vs 無條件分佈，做 Welch-t + Mann-Whitney
- 迷思成立需 event 隔日平均報酬**顯著 < 0**

**跨期間穩健性**：各資產切 3 段等長 sub-period，各自報 directional accuracy。

## 結果

### 迷思 1：量先價行（volume → 隔日方向）

| 資產 | 訊號 | hit-rate | binomial p | **PT p** |
|------|------|----------|-----------|----------|
| TW0050 | 量增 sign | 0.519 | 0.051 | **0.035** |
| TW0050 | 量能水準 high | 0.509 | 0.384 | 0.372 |
| TW0050 | 量 z-score sign | 0.491 | 0.349 | 0.988 |
| TW0050 | logistic OOS | 0.531 | 0.011 | **0.257** |
| SPY | 量增 sign | 0.510 | 0.232 | 0.179 |
| SPY | 量能水準 high | 0.509 | 0.287 | 0.276 |
| SPY | 量 z-score sign | 0.501 | 0.947 | 0.144 |
| SPY | logistic OOS | 0.558 | **1.4e-08** | **0.127** |

**關鍵解讀 — binomial 顯著 ≠ 有預測力**：SPY logistic OOS 命中率 55.8%、binomial p=1.4e-8 看似「大勝」，但 PT p=0.127（不顯著）。原因是 logistic 幾乎永遠猜漲（`pred_up_frac=0.984`），命中率只是**複製了股市長期上漲的無條件機率**（SPY unconditional up-rate=55.3%，OOS `expected_hit=0.554` ≈ `actual_hit=0.558`）。TW0050 同理（pred_up 0.92，expected 0.538 ≈ actual 0.531）。**Pesaran-Timmermann 把這個「漂移」扣掉後，真正的方向 skill = 0。** 這正是為何方向預測必須用 PT 而非單純 hit-rate / binomial。

- logistic in-sample pseudo-R²（McFadden）：TW0050 = 0.00125、SPY = 0.00096（≈ 0）；llr_p = 0.34 / 0.32（模型整體不顯著）。
- 唯一「邊緣顯著」是 TW0050 量增 sign PT p=0.035 —— 但 (i) 不跨市場穩健（SPY 同訊號 p=0.179），(ii) 命中率僅 51.9%，(iii) 一資產跑 ~4 個檢定，屬 multiple-testing 範圍，不足以推翻 null。

### 迷思 2：爆量長黑是出貨（隔日續跌？）

| 資產 | 門檻 | 事件數 | 事件隔日平均報酬 | 隔日勝率 | Welch p | 迷思成立? |
|------|------|--------|------------------|----------|---------|-----------|
| TW0050 | ret<−1% | 87 | **+0.246%** | 55.2% | 0.549 | ✗ |
| TW0050 | ret<−2% | 51 | **+0.317%** | 52.9% | 0.588 | ✗ |
| SPY | ret<−1% | 136 | **+0.297%** | 58.8% | 0.238 | ✗ |
| SPY | ret<−2% | 57 | **+0.279%** | 57.9% | 0.581 | ✗ |

**迷思講反了**：爆量長黑之後，隔日平均報酬是**正的**（+0.25% ~ +0.32%），勝率 53–59%，方向與「續跌」**相反**——恐慌爆量殺盤隔天更傾向小幅**反彈**而非續崩（雖然統計上不顯著）。無論台股或美股、−1% 或 −2% 門檻，結論一致。

### 跨期間穩健性（量增 sign 規則命中率）

| 資產 | P1 | P2 | P3（最近期） |
|------|----|----|----|
| TW0050 | 0.532 (PT p=0.053) | 0.527 (0.084) | **0.499 (0.937)** |
| SPY | 0.521 (0.140) | 0.505 (0.604) | **0.503 (0.773)** |

任何早期樣本的微弱 edge 在**最近期（P3）完全消失**、命中率回到 50%，與市場效率 / 訊號被套利掉一致。

### 圖表
- `k1653_hitrate_by_period.png` — 各資產量增訊號隔日命中率 by sub-period（皆貼近 50% 基準線）
- `k1653_event_study_dist.png` — 爆量長黑後隔日報酬分佈 vs 無條件分佈（事件分佈均值落在 0 右側）

## 結論（Verdict：**NULL — 兩條迷思皆破解，跨市場一致**）

1. **「量先價行」= NULL**：成交量（量增 / 量能水準 / 量 z-score / logistic 多元）對隔日報酬方向的預測力，在 Pesaran-Timmermann 校正掉市場長期漂移後 ≈ 0。命中率看似 51–56% 純粹是「股市偏漲」的無條件機率，不是方向 skill。台股 TW0050 與美股 SPY 結論一致，且 edge 在最近期完全消失。
2. **「爆量長黑是出貨、隔天續跌」= 破解且方向講反**：爆量長黑之後隔日平均報酬為正（輕微反彈傾向），勝率 >50%，與「續跌」相反；統計上不顯著，跨資產、跨門檻一致。

**Prior context**：本結果與 K710（volume 對波動率只有 R²=0.0023 微弱增量）、K753/K754（extreme volume 不預測未來波動率）方向一致——成交量作為「未來」的預測子，無論預測**波動率**（K710/K753/K754）或**報酬方向**（K1653），實證上都極弱或不存在。成交量的資訊價值主要在**同期**（contemporaneous）描述，而非跨期預測。

## 防錯聲明
- **Lag-1**：所有量訊號 `signal.shift(1)`，target = 當日報酬 sign；event study 用 `ret.shift(-1)` 取事件隔日報酬（等價 `event.shift(1)`），無 lookahead。
- **Seed**：固定 seed=42（`np.random.seed`；expanding OOS refit 為 deterministic logit，無隨機抽樣）。
- **Baseline**：50% 隨機基準；方向預測與報酬用同一 lag 對齊。
- **PT test**：以 Pesaran-Timmermann (1992) 作方向 skill 的誠實標尺，避免被市場漂移造成的假 hit-rate 誤導。
- **0050.TW split**：起始 2015 避開 2014-01-02 斷點 + `clean_tw50_data` 雙保險。
- **Null 如實報告**，未為「有故事」誇大唯一邊緣顯著（TW0050 量增 PT p=0.035，已註明非跨市場穩健且屬 multiple-testing）。

## 復現
```bash
uv run python experiments/k1653/k1653.py
```
產出：`k1653_results.json`、`k1653_hitrate_by_period.png`、`k1653_event_study_dist.png`
