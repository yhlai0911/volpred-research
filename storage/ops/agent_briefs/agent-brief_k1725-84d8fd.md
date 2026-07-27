# K1725 — 現貨 BTC ETF 上市對加密 vol「時段結構」的改變

**Model**: opus / xhigh (per model_router)
**Task type**: experiment（worktree）
**Working dir**: `.claude/worktrees/dispatch-slot-1-a630a051-k1725`（你只在此 worktree 內寫檔，禁碰 main / 其他 worktree / feed.json / knowledge.json）
**Source task**: `K1725`

## 開工前必讀
先讀 `.claude/rules/experiments.md`（完整實驗工作流規範）。三項交付物缺一不可：
1. `experiments/k1725/README.md` — motivation + method + lookahead policy + success criteria
2. `experiments/k1725/k1725.py` — 可重跑腳本，`seed=42`；任何預測性訊號一律 `signal.shift(1)`（避免前視）
3. `experiments/k1725/k1725_results.json` — byte-traceable 輸出（每個數字可回溯到腳本）

## 研究動機（research_program.md line 581，來源 J. Futures Markets 2025）
現貨 BTC ETF（IBIT 等）於 **2024-01-11** 在美股掛牌。假說：ETF-ization 把加密資產的波動「**時段分配結構**」拉向傳統市場時鐘 —— 即美股交易時段（RTH）承載的 realized variance 佔比在 IBIT 後**上升**，非時段/週末佔比下降。這是**時間分配結構**的改變，與既有的 vol-of-vol spillover（外溢）研究本質不同：不是「量」的外溢，而是「何時發生」的重分配。

## 方法（建議，容許你依資料實況調整並在 README 記錄）

### 資料
- **BTC 小時資料首選 Binance 公開 klines API**（`GET https://api.binance.com/api/v3/klines?symbol=BTCUSDT&interval=1h`，無需 API key，可回溯到 2017，分頁 startTime/endTime 每次 1000 根）。
- ⚠️ **不要用 yfinance `interval='1h'`**：它硬上限 ~730 天回溯，2026-07 往回只到 ~2024-07，**吃不到 2024-01 斷點**，會讓整個 pre/post 設計失效。若你要用 yfinance 當交叉驗證可以，但主資料走 Binance klines。
- 窗口：至少 2023-01 → 資料末端（涵蓋 IBIT 前後各 ~1 年）。記錄實際起訖與根數。
- 先做資料衛生：去重（本專案有 snapshot-dup 污染前科，見 `storage/ops/snapaudit_reconciliation_20260722.md`）、缺根檢查、時區一律以 **UTC** 為基準明確標註。

### RV 時段拆解
- 小時 log return \(r_t = \ln(C_t/C_{t-1})\)。日 RV = 該日該桶內 \(\sum r_t^2\)。
- 三桶（以 UTC 小時映射美股 ET；注意 DST：ET RTH = 冬令 14:30–21:00 UTC / 夏令 13:30–20:00 UTC，請正確處理夏令時或在 README 說明近似法）：
  1. **US-session (RTH)**：美股常規交易時段對應的 UTC 小時
  2. **non-session**：週間非 RTH 小時
  3. **weekend**：週六、週日全日
- 對每日計算三桶 RV 佔比（bucket_RV / total_daily_RV），得三條時間序列。

### 斷點檢定
- 主檢定：以 2024-01-11 為 known breakpoint，對「US-session RV 佔比」做 **pre vs post 均值差異檢定**（Welch t-test）+ 效果量（Cohen's d 或佔比百分點差）+ **block bootstrap CI**（處理自相關）。
- 補強：Bai-Perron 或 Chow test 找/驗證斷點位置是否落在 IBIT 附近（勝過只信先驗日期）。
- 穩健性：(a) 剔除 IBIT 前後各數週「事件緩衝」重跑；(b) 對三桶都檢定，確認是「重分配」（US↑ 同時 weekend/non-session↓）而非全面放大；(c) 考慮以 log-share 或 logit-share 做常態化。

## Success criteria（CONDITIONAL_PASS 最低門檻）
- 明確回答：US-session RV 佔比在 IBIT 後是否**統計顯著**改變？方向與量級為何？
- 三桶合計佔比 = 1 的一致性檢查通過。
- 至少一個正式斷點/差異檢定 + 效果量 + CI；穩健性至少 2 項。
- 結論須誠實標註資料限制（DST 近似、窗口長度、Binance 單一交易所代表性）。**寧可 NULL / CONDITIONAL_PASS 也不誇大**；研究誠實 > 一切。禁造數字。

## 審核
- Codex review 走 primary path（quota 被擋則 fallback subagent/audit）。
- knowledge 條目**不由你寫**（K1259 gate）；你只產出三交付物 + 一段給主線程的 knowledge 草稿建議放進 README「## Knowledge draft」段。

## 收件時（followup）
主線程會在你完成後：驗 results.json 數字自洽（agent-result-verification）、Codex 二審、merge worktree、寫 knowledge。你的職責到三交付物齊全且自驗通過為止。
