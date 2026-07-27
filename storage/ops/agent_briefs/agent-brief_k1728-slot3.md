# K1728 — 新聞情緒 / 總經注意力對美股 RV 的增量預測力

**Model**: opus / xhigh (per model_router experiment)
**Source task**: K1728 (P3 experiment, claimed hourly-slot-3)
**Worktree (cwd)**: `.claude/worktrees/dispatch-slot-3-c6322072-k1728`
**Result artifact (hard postcondition)**: `experiments/k1728/k1728_results.json`

## 0. 研究誠實鐵律（AGENTS.md，違反即失敗）

- **Lookahead 是最高風險**：所有 predictor 一律 `.shift(1)`（signal at t-1 → RV at t）。
  baseline HAR 與 augmented 用**同一** lag 慣例。代碼裡要有明確 shift。
- 固定 `seed=42`（train/test split、任何抽樣、bootstrap、CW/DM 的 block）。
- 資料來源、期間、樣本數必須標明。Null result 如實報告。結論強度不得超過證據。
- 觀察先於計算：先資料診斷/描述統計，再估計。方法論要有正式檢定（DM / Clark-West）。

## 1. 動機（grounded in literature）

文獻（J.Forecasting / arXiv 2025 macro-attention & sentiment vol；JPM *The Impact of
Volatility Targeting*；Man Group 2025）指出：總經**注意力**（investor/media attention）
與**新聞情緒**在高不確定期領先已實現波動（RV）。HAR-RV（Corsi 2009）雖是 RV 預測的
強 baseline，但只用 RV 自身的 daily/weekly/monthly 分量；本實驗檢定「加入**免費**的
總經注意力 / 情緒 regressor 後，對美股 RV 是否有**統計顯著的增量 OOS 預測力**」。

**核心問題**：Attention/sentiment regressor 加進 HAR，增量 OOS R² 是否 > 0 且顯著（Clark-West，
nested model）？在高 EPU / 危機期增益是否更大（條件分析）？

## 2. 資料（全部免費，見 .claude/skills/external-data-sources）

- **RV target**：美股指數 RV。優先用日內資料算 RV（若無穩定日內源，退而用 yfinance 日資料的
  Garman-Klass / Parkinson range-based RV 或 squared daily return 作 proxy，並在 README 明標
  這是 proxy 及其限制）。標的：SPY 或 ^GSPC（同時可加 QQQ 做 robustness）。
- **Attention**：Google Trends（`pytrends`，免費）—— 關鍵字如 "recession"/"inflation"/"stock market
  crash"，週頻 → 對齊到日（forward-fill 到有值日、務必只用 t-1 之前已可得的值）。若 pytrends
  被 rate-limit，改用 **FRED** 的替代注意力/情緒序列。
- **Sentiment / uncertainty（FRED，最穩）**：
  - `USEPUINDXD`（Daily Economic Policy Uncertainty Index，Baker-Bloom-Davis）
  - `VIXCLS`（VIX，作 attention/risk proxy 與對照）
  - 若可得：SF Fed Daily News Sentiment Index（若 FRED/官方 CSV 可抓）
- 期間：盡量長（EPU daily 自 ~1985；VIX 自 1990；Google Trends 自 2004）——
  以**交集期間**為準，OOS 用後段（例如 2015-01 起或後 30% expanding window）。

## 3. 方法

1. **RV 建構**：log-RV（標準化波動預測慣例），描述統計 + ACF 先看。
2. **Baseline**：HAR-RV = RV_d(t-1) + RV_w(t-1) + RV_m(t-1)（Corsi），OLS，expanding/rolling OOS。
3. **Augmented**：HAR + {EPU, attention, sentiment}（各自 shift(1)；可先單獨加、再全加）。
   考慮 log/標準化 predictor；注意共線性（VIX vs EPU）。
4. **評估**：
   - **增量 OOS R²**（相對 HAR baseline，Campbell-Thompson OOS R²）。
   - **Clark-West test**（nested model 的正確檢定，MSPE-adjusted）——主判準。
   - **DM test**（HLN small-sample factor）作併列參考。
   - QLIKE / MSE 兩個 loss 都報。
5. **條件分析**：高 EPU / 高 VIX regime（用 t-1 的 regime 分箱）下增益是否更大。
6. **穩健性**：不同 OOS start、rolling vs expanding、QQQ 複核、predictor 子集。

## 4. Lookahead policy（README 必寫一節）

- 所有 predictor `shift(1)`：用 t-1（含）之前可得資訊預測 t 的 RV。
- Google Trends 週頻對齊到日只能用「該週結束後才可得」的值 → 對齊時要 lag 到可得日，禁用未來週值。
- OOS 為真 out-of-sample：expanding window 重估係數，只用 ≤ t-1 的資料 fit。
- baseline 與 augmented 完全相同的 lag / 樣本 / OOS 切點。

## 5. 成功判準（README 必寫）

- **PASS（有增益）**：至少一個 augmented spec 的 Clark-West p < 0.05 且增量 OOS R² > 0（穩健於
  OOS start）。報告哪個 regressor 貢獻、在哪個 regime 最強。
- **NULL（無增益）**：增量 OOS R² ≤ 0 或 CW 不顯著 —— 如實報 NULL，這也是有價值的結果
  （免費注意力/情緒在日頻對美股 RV 無超越 HAR 的增量）。
- 禁止 overclaim：小樣本 / proxy RV / 單指數都要在 caveats 下修結論。

## 6. 交付物（實驗三件套 + 圖，per .claude/rules/experiments.md）

- `experiments/k1728/README.md`：motivation + data(來源/期間/n) + method + **lookahead policy** +
  success criteria + results table + **verification checklist（給收件主線程）** + Codex 審碼要點 +
  proposed knowledge summary（主線程寫 knowledge，agent 不要寫 knowledge.json）。
- `experiments/k1728/k1728.py`：可重現，`seed=42`，明確 `shift(1)`，baseline 同 lag。
- `experiments/k1728/k1728_results.json`：byte-traceable，含 OOS R²、CW/DM 統計量+p、各 spec、regime
  分析、data provenance（tickers/series ids/期間/n）。
- 圖：OOS R² by spec、增益 by regime、predictor 時序 vs RV。
- `reproduce_spec.json`（跑 `scripts/check_experiment_artifacts.py` 產/驗）。

## 7. 收尾（agent 自己做到可被收件）

- 跑 `python3 scripts/check_experiment_artifacts.py check --path experiments/k1728` 與
  `uv run python scripts/experiment_gates.py run --path experiments/k1728`，兩者 PASS。
- 在 worktree branch `git add` 三件套 + 圖 + reproduce_spec 並 commit（純 ASCII commit message，
  用 `git commit -F`）。**不要** merge、**不要**寫 knowledge.json（主線程負責）。
- README 末段寫清楚 headline 數字位置，供收件主線程驗證 + Codex 審碼 + merge。

## 8. 資料抓取務實提醒

- 先 smoke-test 每個資料源（FRED/pytrends/yfinance）能回資料再跑 production，避免像 2026-05-29
  E3 那樣 silent-fail。pytrends 若不穩就降級到純 FRED（EPU+VIX），並在 README 標註 attention
  源的替代與限制。
- Heavy 迴圈（expanding OOS 重估）注意時間；必要時縮短 OOS 頻率或用 rolling 固定窗以控時。
