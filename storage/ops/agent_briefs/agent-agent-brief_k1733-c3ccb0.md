# K1733 — AI 基建資金鏈的波動傳導（infra/credit vol → Nasdaq RV 的 lead-lag）

**Model**: opus / xhigh (per model_router)
**Task**: K1733 (experiment lane, worktree topology)
**來源接地**: research_program.md line 606（unchecked open item）；文獻線索 J.P. Morgan 2026 alternatives outlook（AI data-center financing / public-private market shift）。

## 研究誠實原則（不可違反 — 見 AGENTS.md）
- 一切數字來自實際計算；標明資料來源、期間、樣本數。
- **Lookahead 是最高風險**：任何 lead-lag / 預測聲明都要 `signal from t-1, target at t`，`.shift(1)` 明確；**絕不可用 same-day infra vol 去「預測」same-day Nasdaq vol**。Granger / lead-lag 的方向性要嚴格用滯後項。
- 隨機程序 `seed=42`（bootstrap / 任何抽樣）。
- Null result 如實報告；結論強度不可超過證據；區分實證與模擬。

## 假說（可證偽）
1. **H1（傳導方向）**：AI capex shock 先在 **power-grid/infra（XLU/PAVE）與 credit（HYG/LQD）** 的波動出現，**再**傳到 hyperscaler/semis（MSFT/NVDA/SMH）與 Nasdaq RV。即 infra/credit vol **領先** tech RV（正向 lead-lag），反向領先較弱。
2. **H2（可用性）**：infra/credit vol 的落後項對 tech/Nasdaq 次日 RV 有**增量**預測力（超越 tech RV 自身的 HAR baseline）。
3. **H3（不對稱/狀態依賴，選作）**：傳導在高壓（credit spread widening / 高 vol regime）時是否更強。

## 資料（唯一來源 yfinance，免費）
- 三籃 proxies：
  - hyperscaler/semis：MSFT, NVDA, SMH（+ 可加 QQQ 作 Nasdaq RV 目標）。
  - power-grid/utility/infra：XLU, PAVE。
  - credit：HYG, LQD（credit vol；HYG-LQD 或 spread proxy 亦可）。
- 頻率：daily OHLC → 日 RV proxy（用 Parkinson/Garman-Klass high-low estimator 或 |log return|；講明選擇）。可加 5-day realized。
- 期間：各 ETF 資料起點（PAVE ~2018、SMH ~2000、HYG ~2007…）→ 最新；**明列每籃實際共同樣本期間與 N**（PAVE 2018 起會綁定共同期間，如實記錄此限制）。
- OOS split：明定 in-sample / OOS 切點（如 2022-01），係數只在 in-sample 估、OOS 驗增量預測力。

## 方法（觀察先於計算）
1. **描述統計先行**：三籃 RV 的相關矩陣、滾動相關、共同期間覆蓋表。先看資料。
2. **Lead-lag / Granger**：infra/credit RV 的落後項 → tech/Nasdaq RV 的 Granger causality（雙向都測），**HAC SE**；報方向性與落後階數。
3. **增量預測（H2，主結論）**：baseline = tech/Nasdaq RV 的 HAR（RV_{d,w,m}, 全部 `.shift(1)`）；augmented = HAR + infra/credit RV 落後項。比較 **OOS** 預測（RMSE/QLIKE），並做 **Diebold-Mariano** 檢定（HAC）。多重比較（多籃×多目標）BH-FDR。
4. **不對稱（H3，選作）**：以 credit-spread / VIX regime 分層或交互項檢定狀態依賴。
5. 穩健性：不同 RV estimator、不同 split、去 2020 極端期後重估。

## 交付物（三件套，寫入 worktree）
- `experiments/k1733/README.md`：motivation + 資料契約（含共同期間限制）+ method + **lookahead policy 明述** + success criteria + 結果摘要 + 局限。
- `experiments/k1733/k1733.py`：可重跑，`seed=42`，HAR 與落後項 `.shift(1)` 明確，RV estimator 與 DM 檢定清楚。
- `experiments/k1733/K1733_results.json`：byte-traceable（README 每個數字對應 json key）。
- 圖表（滾動相關、lead-lag cross-corr、OOS RMSE by model、equity/signal 若有 timing 應用）放 `experiments/k1733/`。

## Success criteria
- H1/H2 各給明確 accept/reject + 檢定統計量 + p 值（FDR 後）+ 落後階數。
- **主結論以「OOS 增量預測 + DM 顯著」為準**：若 infra/credit 落後項在 HAR baseline 之上無 OOS 顯著增益 → 如實報 null（有價值）。
- 傳導方向若與假說相反（tech 領先 infra）也如實報。

## Codex 二審（primary path）
完成後產出 `experiments/k1733/review_verdict.json`（Codex；quota 擋則 fallback subagent / audit）。未達 **CONDITIONAL_PASS** 不得宣稱結論、不得寫 knowledge（K1259：agent 禁寫 knowledge.json，主線程收件時寫）。

## 收件（future PHASE A followup 會做，agent 不必做）
verify results==README==agent 三者一致 → 檢 verdict → 主線程寫 knowledge → merge_worktree.sh 整合 dispatch-slot-1-1e5922b4-k1733 → 若傳導 edge 乾淨且有 reader 價值，考慮 reader-facing 選題（先過 arc-dedup gate）。
