# K1734 — EM 貨幣 carry unwind 的 crash-risk 不對稱

**Model**: opus / xhigh (per model_router)
**Task**: K1734 (experiment lane, worktree topology)
**來源接地**: research_program.md line 625；文獻 BIS / IMF GFSR 2025（EM drawdown 為 EUR 的 3-5 倍；carry crowding / yen-funding）。

## 研究誠實原則（不可違反 — 見 AGENTS.md）
- 數字來自實際計算；標明來源、期間、樣本數。
- **Lookahead 最高風險**：unwind「領先」EM 股 vol 的聲明必須 `signal from t-1, target at t`，`.shift(1)` 明確；不可 same-day 互推。
- `seed=42`（bootstrap / 抽樣）。Null 如實報。區分實證/模擬。
- **資料限制誠實**：leveraged / crowded positioning 的真實部位數據不可得 → 明確標示用 proxy（yen funding stress、carry drawdown、vol），不得宣稱直接觀測 positioning。

## 假說（可證偽）
1. **H1（左尾不對稱）**：EM carry proxy 報酬分佈**左尾**（risk-off / drawdown）比右尾顯著厚且在壓力期急速放大 —— skewness < 0、下行半變異 > 上行、tail ratio 不對稱、CoVaR/ES 在 stress 放大。
2. **H2（yen-funding / risk-off 觸發）**：FXY（yen 走強 = funding unwind proxy）或 risk-off 指標的變動，與 EM carry 左尾事件同期/領先相關。
3. **H3（傳導領先，主結論之一）**：carry unwind 訊號（t-1）是否**領先** EM 股 vol（EEM/EM equity RV）—— 嚴格滯後 Granger / 增量預測。

## 資料（唯一來源 yfinance，免費）
- EM carry/債：CEW（EM currency）、EMLC（EM local-currency bond）、EMB（EM USD bond）。
- Funding/risk-off proxy：FXY（yen）、可加 ^VIX、DXY(UUP)、HYG（credit risk-off）。
- EM 股 vol 目標：EEM（RV proxy，high-low estimator 或 |log ret|）。
- **carry proxy 建構**：以 EM local bond / currency 的 carry-like return（EMLC 相對 UST/現金）或 CEW total return 作 carry proxy；**明述建構口徑**，不可含糊。
- 期間：各 ETF 起點（CEW ~2009、EMLC ~2010、EMB ~2007…）→ 最新；明列共同期間與 N（含 2013 taper tantrum / 2015 / 2018 / 2020 / 2022 等 risk-off 事件覆蓋）。
- OOS split：明定切點；領先預測係數 in-sample 估、OOS 驗。

## 方法（觀察先於計算）
1. **描述統計先行**：carry proxy 報酬分佈（skew/kurt、下行vs上行半變異、tail ratio）、by-regime（VIX 高低 / risk-off）分層表。先看資料。
2. **左尾不對稱檢定（H1）**：skewness 顯著性、Cornish-Fisher / 經驗分位、下行半變異 vs 上行的 bootstrap 檢定（block bootstrap, seed=42）；stress vs calm 期的 ES/VaR 比較。
3. **觸發（H2）**：FXY/risk-off 變動 vs carry 左尾事件的同期與領先相關（event-window around 大 drawdown 日）。
4. **領先預測（H3，主結論）**：carry unwind 訊號落後項 → EEM 次日 RV 的 Granger（HAC）+ HAR baseline 之上的 OOS 增量（DM 檢定）。多重比較 BH-FDR。
5. 穩健性：不同 carry proxy 口徑、去單一事件（2020）後重估、不同 RV estimator。

## 交付物（三件套，寫入 worktree）
- `experiments/k1734/README.md`：motivation + 資料契約（含 positioning proxy 限制明述）+ method + **lookahead policy** + success criteria + 摘要 + 局限。
- `experiments/k1734/k1734.py`：可重跑，`seed=42`，carry proxy 建構與 `.shift(1)` lag、bootstrap/DM 檢定清楚。
- `experiments/k1734/K1734_results.json`：byte-traceable（README 每數字對應 json key）。
- 圖表（報酬分佈/QQ、下行vs上行半變異、event-window、OOS RMSE）放 `experiments/k1734/`。

## Success criteria
- H1/H2/H3 各明確 accept/reject + 檢定統計量 + p 值（FDR 後）。
- **主結論以「左尾不對稱顯著 + unwind 對 EM 股 vol 的 OOS 領先增量」為準**；若不對稱不顯著或無 OOS 領先增益 → 如實報 null。
- positioning 只用 proxy，結論強度不得超過 proxy 能支持的範圍。

## Codex 二審（primary path）
產出 `experiments/k1734/review_verdict.json`；未達 **CONDITIONAL_PASS** 不得宣稱結論、不得寫 knowledge（K1259：agent 禁寫，主線程收件時寫）。

## 收件（future PHASE A followup 會做）
verify results==README==agent 三者一致 → 檢 verdict → 主線程寫 knowledge → merge_worktree.sh 整合 dispatch-slot-1-1e5922b4-k1734 → 若 crash-risk 不對稱/領先訊號乾淨且有 reader 價值，考慮 reader-facing 選題（先過 arc-dedup gate）。
