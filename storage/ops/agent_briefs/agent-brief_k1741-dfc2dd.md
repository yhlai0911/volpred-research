# K1741 — 放空企業債作股票尾部對沖：效率 vs put-proxy / VIX overlay

**Model**: opus / xhigh (per model_router, task_type=experiment)
**Task id**: K1741（pool task，已 in_progress）
**Worktree（唯一可寫路徑）**: `.claude/worktrees/dispatch-slot-1-1d13fe83-k1741`
**必交產物**: `experiments/k1741/K1741_results.json`（相對 worktree root；path 精確，reaper 只驗存在）

---

## 0. 開工前必讀（順序不可跳）

1. `AGENTS.md` §研究誠實原則（13 條，最高優先）
2. `.claude/rules/experiments.md`（實驗三件套 workflow + lookahead policy + success criteria）
3. `research_program.md` line ~727 原始 backlog 條目（本題來源）與 line ~505 既有 tail-hedge 成本軸（正交性依據）

**庫內先行知識（必須讀過再設計，禁止重跑已知結論）**：
- **K544**「Tail Hedge Efficiency」：VIX-overlay 疊在 12/VIX VT 上 NPV=-0.089%，5 策略全虧，cross-OOS 0/5。核心洞見「12/VIX VT 本身就是 tail hedge，雙重保險邊際價值趨零」。
- **K24**：HYG corr(SPY) 最低 0.510、GFC 期間飆到 0.655，HYG MDD -34.2%；credit 在危機時與 equity 同步 → **這正是「放空 credit 應該是有效 hedge」的機制假設來源**，也是本題的先驗。
- **K22**：HYG 有 gamma=0.183 leverage effect，~5%/yr yield（**放空方要付這筆 carry，是本題最大 drag 來源，不可略**）。
- **I3 / 17259 條**：synthetic put（VIX→GLD/TLT linear allocation）是庫內既有 put-proxy 實作，可直接沿用當 benchmark，不要重新發明。
- 在 `storage/memory/knowledge.json` 自行 grep `HYG` / `tail hedge` / `K544` 確認上述引用無誤後再寫 README motivation。

**正交性宣告（README 必寫一段）**：本題與 line 505 的既有 tail-hedge 成本軸差別在**對沖工具換成 credit-short**，不是重測 VIX overlay。若你的設計最後又變成「VIX overlay 再測一次」→ 設計錯了，回頭改。

---

## 1. 研究問題

**放空企業債（HYG / JNK）作為股票尾部對沖，其 beta-adjusted crisis alpha 與平時 drag，是否優於 put-proxy 或 long-VXX overlay？**

來源文獻：arXiv 2504.06289「On the Efficacy of Shorting Corporate Bonds as a Tail Risk Hedging Solution」(2025)。**不要引用你沒讀過的內容**——可以說「本題動機源自該篇的主張」，但任何具體數字不得假借該文。

---

## 2. 資料

- yfinance，**一律 `auto_adjust=True` 或用 `Adj Close`**（K22 教訓：HYG raw close 漏掉 65pp 股息，會把整個 carry 結論做反）。
- 標的：`SPY`, `HYG`, `JNK`, `LQD`, `IEF`, `VXX`, `^VIX`（GLD/TLT 若沿用 synthetic-put benchmark 則一併取）。
- 期間：**2018-01-01 起**（現行 VXX = iPath Series B，2018-01 上市；更早的 VXX 是不同工具，混接就是資料造假）。若你要延長 SPY/HYG 樣本做 calm-period drag，可另取長樣本但**必須在 results.json 分開標示兩個 window，不可混算**。
- 四類 drawdown window（用 SPY 實際 peak-to-trough 定義，**不要硬編日期猜**；程式內以 rolling max drawdown 演算法標出並把實際起訖日期寫進 results.json）：
  1. 2018Q4
  2. 2020 COVID
  3. 2022 全年 bear
  4. 2025（含 4 月關稅急跌；以資料實際判定，若該年無符合門檻的 drawdown 就如實記錄「未達門檻」而非硬湊）

---

## 3. 方法（核心設計，逐項照做）

### 3.1 Short-credit hedge 的正確建構

**天真做法（禁止當唯一口徑）**：直接對 HYG total return 取負號。這會把**存續期間（duration）報酬**也放空掉，等於偷渡一個放空利率的部位，2022 年會虛假地大賺。

必做兩個口徑並列報告：
- **(A) Naive short**：`-1 × HYG_total_return`
- **(B) Duration-hedged credit short**（主口徑）：`-1 × (HYG_ret − β_dur × IEF_ret)`，β_dur 用**擴張窗（expanding window）rolling 回歸**估計、只用 t-1 以前資料，隔離信用利差成分。也可用 HYG−LQD 作次要對照。

兩個口徑結論若不同，**在 README 明講差異來自 duration 而非 credit**——這是本題最容易出的 confounder。

### 3.2 成本（本題成敗關鍵，不可用「忽略成本」了事）

放空 HYG 的持有成本至少三塊，**全部要在 results.json 有獨立欄位**：
1. **Coupon carry**：放空方須付出借券標的的配息 ≈ HYG distribution yield（歷史 ~5%/yr，用實際 yfinance dividends 逐期計算，不要用固定常數）
2. **Borrow fee**：yfinance **拿不到**。→ 這是 blocked data。依 backlog 原文要求「明確標示放空成本/借券費 blocked 用保守 proxy」：用**保守常數 sensitivity grid**（例如 0.5% / 1.0% / 2.0% /yr）跑三檔，results.json 記 `borrow_fee_grid`，並在 README 標明「borrow fee 為 assumption，非觀測值」。**禁止只跑最有利的那檔。**
3. **交易成本 / 再平衡**：hedge ratio 若動態調整，要計入。

### 3.3 Benchmarks（三者同期間、同 hedge budget 比較）

- **Put-proxy**：沿用庫內既有 synthetic-put 實作（VIX→GLD/TLT linear allocation，見 knowledge 17259 條）；不要憑空造新 put 定價模型（無選擇權資料就不要假裝有）。
- **Long VXX overlay**：固定小比例 VXX 配置（VXX 的 roll drag 由其實際價格自然體現，不需另加假設）。
- **Unhedged SPY**：baseline。

**Hedge budget 對齊**：三種 hedge 必須在「平時年化 drag 相同」或「crisis 期間 beta reduction 相同」兩種對齊法**至少一種**下比較。只比未對齊的絕對數字沒有意義。

### 3.4 評估指標

- **Beta-adjusted crisis alpha**：drawdown window 內，hedged portfolio 相對「同 equity beta 的 SPY 縮放部位」的超額報酬。beta 用 **window 外（事前）** 估計，不可用 window 內資料（lookahead）。
- **Calm-period drag**：非 drawdown 期間年化報酬拖累。
- **效率比**：crisis alpha / calm drag（每單位平時成本買到多少危機保護）。
- MDD、CVaR5%、worst-10%-months。
- ⚠️ **MDD scale artifact 硬規則**：比較 MDD 前必須 exposure-match（不同策略平均曝險不同時，MDD 差異可能純粹來自 scale）。照庫內既有規則做。

### 3.5 統計嚴謹度（AGENTS.md #7）

- 四個 window 只有 4 個事件 → **N 極小，這是本題最大限制**。禁止用 4 個 window 的平均值宣稱顯著。
- 必做：**stationary bootstrap**（block bootstrap，**seed=42**）給 crisis alpha 的信賴區間；日頻層級的 Diebold-Mariano + **Harvey 小樣本修正** 比較 hedge 方案。
- 事件研究層級可加 permutation / circular-shift null。
- **結論強度不得超過 N=4 能支撐的程度**（AGENTS.md #10）。

### 3.6 Lookahead（AGENTS.md #11，最高風險）

- 所有 hedge 權重、beta、duration β_dur 一律 `signal.shift(1)`，t-1 訊號 × t 報酬。
- drawdown window 的**識別**本身是事後的——這是合法的 event-study 設計，但 **hedge 決策規則不可用到 window 內未來資訊**。README 的 lookahead policy 段落要把這個區分寫清楚。
- 所有隨機程序 `seed=42`。

---

## 4. 交付物（三件套，缺一不可）

1. `experiments/k1741/README.md` — motivation（含上述庫內先行知識引用 + 正交性宣告）/ method / **lookahead policy** / success criteria / 資料來源與期間與樣本數 / 局限
2. `experiments/k1741/K1741.py` — 可重跑，含 `signal.shift(1)` 與 `seed=42` 明確可見
3. `experiments/k1741/K1741_results.json` — byte-traceable：每個報告數字都能從此檔對回程式輸出。至少含 `data_source`、`sample_period`、`n_obs`、四個 window 的實際起訖日、兩種 short 口徑、`borrow_fee_grid` 三檔、三個 benchmark、bootstrap CI、DM/Harvey 統計量
4. 圖表（≥2 張，放 `experiments/k1741/`）：四個 window 的 hedge payoff 對照、calm-drag vs crisis-alpha 散點（效率前緣）

---

## 5. Success criteria（先寫進 README，做完自評）

- **PASS**：三種 hedge 在對齊 budget 下有可統計區辨的效率差異（bootstrap CI 不重疊或 DM 過 Harvey），且結論對 borrow-fee grid 三檔穩健。
- **CONDITIONAL_PASS**：方向性結論成立但 N=4 使統計檢定不顯著，或結論隨 borrow fee 假設翻轉（如實標明翻轉點）。
- **NULL**：short-credit hedge 在扣成本後不優於 put-proxy / VXX。**Null 是完全可接受的結果，如實報告**（AGENTS.md #9）。考慮到 K544 已顯示 tail-hedge overlay 普遍虧損 + HYG ~5% carry 是巨大 drag，**先驗上 NULL 相當可能——不要為了「有發現」去調參數把它做成 PASS**。

---

## 6. 硬性禁止

- ❌ 寫 `storage/memory/knowledge.json`（K1259 gate：knowledge 只能由 Codex review 通過後、由主線程寫）
- ❌ 碰 worktree 以外的路徑；❌ 動 `storage/next_tasks.json`、feed、supabase
- ❌ `git push` / `--force` / `--no-verify`
- ❌ 任何未實際計算的數字、任何捏造的文獻數字
- ❌ 把 borrow fee 當成觀測值報告（它是 assumption）

## 7. 收尾

在 worktree 內 commit 你的產出（正常 commit，不 push）。最後在 stdout 印一段 ≤15 行摘要：verdict（PASS / CONDITIONAL_PASS / NULL）、三種 hedge 的效率比、borrow-fee 敏感度是否翻轉結論、最大限制。
