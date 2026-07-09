# K1667 — 成交量能否預測隔日方向？「量先價行 / 爆量長黑是出貨」迷思破解

## 動機

散戶技術分析有兩句流傳極廣的口訣，都宣稱「今天的成交量」能預告「隔天的漲跌方向」：

- **(A)「量先價行」**：成交量爆大 = 主力／資金進場，隔日股價「易漲」。
- **(B)「爆量長黑是出貨」**：高成交量 + 當日收長黑 K（大跌、收在當日低點）= 主力出貨，隔日「續跌」。

這兩句是典型的 folk claim——聽起來有道理、也常被拿來當進出依據，但很少有人用長期、多市場、統計嚴謹的方式檢定它有沒有**隔日方向**的預測力。本實驗（迷思實驗室系列）用真實日線資料正面檢定。

## 與既有研究 / 既有 K 的差異

- 既有 volume 相關 K（K160 MDH、K510/K527 Volume-GARCH、K710 Volume 作 vol predictor、K753/K754 Volume Exhaustion）全是「成交量 → **波動率**」關係；**沒有任何一支**檢定「成交量 → 隔日**報酬方向**」這個散戶口訣。本 K 補這個缺口。
- 學術對照（見文獻）：本結果與 Campbell-Grossman-Wang (1993)「高量下跌傾向反轉」、Gervais-Kaniel-Mingelgrin (2001)「high-volume return premium（月頻、attention 驅動）」、Llorente et al. (2002)「hedging trades 反轉 vs speculative trades 續強」對得上，但把它們拉到**日頻方向命中率**、**跨台美市場**、**個股 vs 指數 ETF** 的白話檢定。

## 文獻（≥3）

1. **Gervais, S., Kaniel, R., & Mingelgrin, D. H. (2001). The High-Volume Return Premium. *Journal of Finance*, 56(3), 877-919.** — 異常高（低）成交量的股票，在「接下來一個月」傾向上漲（下跌）；機制是成交量衝擊提升股票能見度（visibility/attention）→ 需求與價格。注意其 horizon 是**月頻**，非隔日。
2. **Campbell, J. Y., Grossman, S. J., & Wang, J. (1993). Trading Volume and Serial Correlation in Stock Returns. *Quarterly Journal of Economics*, 108(4), 905-939.** — 報酬自相關隨成交量上升而下降；**高量日的下跌比低量日的下跌更可能伴隨預期報酬上升（即傾向反轉）**。此點直接與「爆量長黑續跌」相反。
3. **Llorente, G., Michaely, R., Saar, G., & Wang, J. (2002). Dynamic Volume-Return Relation of Individual Stocks. *Review of Financial Studies*, 15(4), 1005-1047.** — 風險分擔（hedging）交易造成的報酬傾向反轉，資訊（speculative）交易造成的報酬傾向續強；成交量與報酬自相關的關係取決於個股資訊交易程度的橫斷面差異。

## 方法

- **資料**：yfinance 免費日線 OHLCV（`auto_adjust=True`）。5 資產跨台美市場：
  - 台股：0050.TW（台灣 50 ETF）、2330.TW（台積電）、2317.TW（鴻海）
  - 美股：SPY（S&P500 ETF）、QQQ（Nasdaq100 ETF）
  - 期間 2005-01 ~ 2026-06（0050 自 2009 起）；每資產 **4,278 ~ 5,405** 交易日（全部 ≥500），涵蓋 2008/2018/2020/2022 空頭。
- **訊號定義（第 t 日收盤後可得）**：
  - 爆量：`volume_t > k × rolling_mean(volume, 20)`，`k ∈ {1.5, 2.0}`（rolling 窗口結束於 t，只用 t 及之前）。
  - 長黑：`ret_t < -1.5%`（報酬版，主 spec）或 `(close-low)/(high-low) < 0.3`（range 版，robustness）。
  - (A) 量先價行 = 爆量（不分紅黑）；另測「爆量長紅」= 爆量 AND `ret_t>0`。
  - (B) 爆量長黑 = 爆量 AND 長黑。
- **Lookahead policy（一句話）**：訊號在第 t 日收盤形成，預測第 t+1 日報酬；程式用 `signal.shift(1)` 把訊號 lag 一日，對齊 `signal[t-1] → return[t]`（即「昨天出現訊號 → 今天報酬」＝訊號的隔日報酬）。baseline（無條件報酬 / up-down rate）用**同一 index 的全樣本報酬**，同 lag 慣例。
- **檢定**（每資產）：
  1. 條件 vs 對照隔日報酬分佈：Welch two-sample t-test + Mann-Whitney U（非常態穩健）。
  2. 條件 vs 無條件隔日報酬均值差：moving-block bootstrap 95% CI（block=5，`seed=42`，2000 reps）。
  3. 方向命中率：binomial vs 0.5，**以及**「條件命中率 − 無條件 baseline 命中率」兩比例 z 檢定。**誠實關鍵**：股票有 upward drift，隔日上漲率天生 >50%，所以「贏過丟銅板」不算數，要贏過**無條件 baseline** 才是真預測力。
  4. 跨資產 pooled 只當 **diagnostic**（K1355 教訓）：先按日期聚合 cross-asset 平均訊號隔日報酬，再對日期序列做 Newey-West HAC vs 0；**不把 asset-day 當 iid**。primary 結論一律看 per-asset。
- **「顯著」定義（verdict）**：條件 vs 無條件均值差的 bootstrap 95% CI 不含 0，且方向與 folk claim 一致。另記錄「顯著但方向相反」（例如 claim 說續跌但實際顯著反彈）。

## 成功標準

- 每資產 ≥500 日、訊號樣本數揭露；所有統計量可從 `K1667_results.json` byte-trace。
- Lookahead 有明確 `signal.shift(1)`；隨機程序固定 seed。
- Null / 部分成立 如實報告，結論強度不超過證據；跨 k 敏感度一致。

## 主要結果摘要（k=2.0 主 spec；k=1.5 敏感度一致）

### 迷思 (B)「爆量長黑是出貨 → 隔日續跌」— **破解成功（FALSE）**

- **5 資產 × 2 門檻，0 個資產**出現「顯著的隔日續跌」。
- 事實相反：爆量長黑後的隔日平均報酬多為**正**（傾向反彈），部分達顯著——k=2.0 下 2330.TW 隔日均報酬 +1.06%（bootstrap CI [+0.42%, +1.58%] 不含 0，方向與 claim 相反）；k=1.5 下 SPY 隔日 +0.42%（CI [+0.06%, +0.84%]）、2330 +0.36%（CI 不含 0）同樣是顯著**反彈**。
- 隔日「下跌率」普遍**低於**無條件下跌 baseline（例：2330 下跌率 31.0% vs baseline 43.8%；QQQ 34.0% vs 44.1%），即爆量長黑後隔日**更不容易**續跌。
- pooled diagnostic（跨資產日聚合 HAC）：隔日均報酬 **+0.39%**，HAC t=+2.47（p=0.014）——方向為反彈，與「續跌」口訣相反。
- **與 Campbell-Grossman-Wang (1993) 一致**：高量下跌傾向反轉，而非續跌。「爆量長黑是出貨」作為**隔日續跌**訊號，站不住腳。

### 迷思 (A)「量先價行 → 隔日易漲」— **部分成立，但非普世法則（市場/資產依賴）**

- **並非所有市場都成立**：k=2.0 下 5 資產僅 **2 個**（2330.TW、2317.TW，皆台股個股）條件均值差 bootstrap CI 不含 0 且為正；0050.TW、SPY、QQQ（三個 ETF）**不顯著**。
  - 2330.TW：隔日上漲率 60.4% vs baseline 48.4%（+12.1pp），均差 +0.49%（CI [+0.18%,+0.78%]），兩比例 p=0.001。
  - 2317.TW：上漲率 54.4% vs 46.4%（+8.0pp），均差 +0.51%（CI [+0.17%,+0.85%]），p=0.013。
  - SPY 反而 49.5% vs 55.1%（低於 baseline）；QQQ 55.0% vs 55.4%（無邊際）。
- k=1.5 敏感度一致：2330/2317 仍顯著正，ETF 仍不顯著。
- 解讀：**個股**的爆量常伴隨財報／新聞的 attention 衝擊（GKM 2001 能見度機制 + post-earnings drift），確有溫和隔日續強；但**廣基指數 ETF** 的爆量多為 risk-sharing／再平衡流量，隔日無方向優勢（甚至偏反轉，呼應 CGW/Llorente）。
- 即使在成立的個股，**效果小**（隔日均差約 +0.2%~+0.5%、命中率邊際 +8~12pp），單靠此訊號難扣掉交易成本後獲利。

**一句話結論**：「爆量長黑是出貨、隔日續跌」在台美 5 大標的、兩種門檻下**全數不成立，甚至偏反彈**；「量先價行、隔日易漲」只在**台股個股**溫和成立、對**指數 ETF 無效**，且效果偏小——都不是可無腦套用的「鐵律」。

## 資料來源 / 期間 / 樣本數

| 資產 | 名稱 | 期間 | 交易日 | 爆量日(k=2.0) |
|---|---|---|---|---|
| 0050.TW | 台灣50 ETF | 2009-01 ~ 2026-06 | 4,278 | 314 |
| 2330.TW | 台積電 | 2005-01 ~ 2026-06 | 5,280 | 192 |
| 2317.TW | 鴻海 | 2005-01 ~ 2026-06 | 5,280 | 250 |
| SPY | S&P500 ETF | 2005-01 ~ 2026-06 | 5,405 | 97 |
| QQQ | Nasdaq100 ETF | 2005-01 ~ 2026-06 | 5,405 | 91 |

## 檔案

- `K1667.py` — 可重跑（`uv run python experiments/K1667/K1667.py`）；含 `signal.shift(1)` lag、`seed=42`、results.json 原子寫入。
- `K1667_results.json` — 全部統計量（per-asset × k × claim：hit rate / baseline / mean diff + bootstrap CI / Welch / MWU / binom / two-prop z；pooled HAC diagnostic；verdict 摘要）。
- `K1667_hitrate.png` — 各資產 條件命中率 vs 無條件 baseline（A 上漲率 / B 下跌率）。
- `K1667_black_meanret.png` — 爆量長黑 條件 vs 無條件 隔日均報酬（含 bootstrap CI）。

## Reviewer

- **Primary path（Codex `codex exec`）當日不可用**：`codex exec` 回 `You've hit your usage limit`（額度用罄，重置 2026-07-11）。
- **Fallback：`feature-dev:code-reviewer` subagent（fresh-context independent review）** — 2026-07-09。
  - Verdict：**CONDITIONAL_PASS**。Lookahead 對齊（`signal.shift(1)` 昨訊號→今報酬）、pooled K1355 合規（日聚合 + Newey-West HAC + diagnostic-only）、results.json atomic write、seed、除零/NaN 防護均判定正確。
  - **抓到 1 個阻擋性資料 bug（已修）**：`close_pos` 原本混用「split 修正後的 close」與「未修正的 high/low」，使 pre-2014 0050.TW 的 range 版長黑訊號（B2）失真。**修正**：`close_pos` 改用 raw 價計算（same-day 內尺度不變、raw 日內 OHLC 互相一致），`close` 只在算 ret 時 clean。修後 0050 B2 隔日下跌率 40.7%（合理，非退化），primary 結論（用 ret 版）不受影響。
  - 低信心備註（reviewer 明示不列為正式問題）：two-prop z 的條件樣本是無條件樣本子集（輕微重疊），方向偏保守、不推翻 null-leaning 結論。
- **注意**：subagent fallback 通過**不等於** primary-path Codex 通過。待 Codex 額度恢復（2026-07-11），建議主線程用 `codex exec` 二次驗證後再把本 K 標 closure（K1259 教訓）。

## 迷思實驗室文章適配

**適合**（★★★★）：主題貼近散戶日常口訣、結論反直覺且穩健（B 完全破解、A 有市場依賴的細膩結論）、有跨台美真數據 + 兩張圖表、與經典文獻對得上。是很好的一篇「破解 + 但要講清楚 nuance」的迷思實驗室內容。
