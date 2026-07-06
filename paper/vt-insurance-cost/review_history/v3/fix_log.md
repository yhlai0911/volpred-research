# v3 修訂 fix log — vt-insurance-cost（Paper 4 / FRL）

**日期**：2026-07-06（台灣時間）
**依據**：`review_history/v2/latex_review_report.md`（3 SEVERE / 7 MODERATE / 4 MINOR）
**修訂範圍（本輪）**：3 SEVERE 中 2 個 text-resolvable + C-01 citation，於主線程直接改 `main.tex`。S-02（heavy cross-OOS 重跑）拆為 compute followup。

## 已修（main.tex，pdflatex 三 pass 乾淨、無 undefined ref/citation）

### S-01 — 50/50 (S4) benchmark 標籤與 code 不符 → RELABEL（不重算）
- **原問題**：Table 1 note 標「S4 is 50/50 SPY/GLD with monthly rebalancing」，但 code（`k811v2_insurance_premium_vov_fixed.py:315`）是 `s4_rets = 0.5*spy + 0.5*gld` — 每日連續、零成本、固定權重，非月再平衡。
- **修法（review 建議 (b)）**：relabel 為「daily constant-weight 50/50（continuous, costless rebalancing）」。code 產出的 Sharpe 0.50 本就是此 daily-constant-weight 定義 → 改標即誠實對齊，**不動任何回報數字**。
- **反混淆**：Table 1 note 明確加註 S4 的 0.50 與 §4.4（sec:results）另算的 monthly-rebalancing premium（2006–2024, 54 bps）是「separately computed」兩回事，杜絕 reviewer 指出的 conflation（M-04 連帶解消）。
- **位置**：main.tex Table 1 note（原 line 143）。abstract / §4.4 / Discussion / Conclusion 的「0.63 vs 0.50 + not apples-to-apples」caveat 本已存在且正確，無需改數。

### S-03 — S3 (Smooth VoV) 論文公式與 code 不符 → 公式對齊 code（不重算）
- **原問題**：LaTeX 寫 binary 0.5 blend `w = w^VT + (1-w^VT)·1(z<1)·0.5`（step function）；code 是 continuous linear `insurance_intensity=clip(z,0,1); w = 1 - intensity·(1-w^VT)`。Table 2 的 S3 數字（opp 2.85 / direct 0.46 / total 3.31）由 continuous-clip code 產出 → 論文公式誤述了產生結果的函數。
- **修法**：把 S3 定義改寫成 code 實際用的 continuous-clip 線性內插：
  `w_t = 1 - clip(z_t^VoV, 0, 1)·(1 - w_t^VT)`，並註明「This continuous specification is the one used to produce the S3 results reported below」。
- **移除無對應輸出的宣稱**：刪掉「0.5 midpoint / alternative values (0.3, 0.7) yield qualitatively similar」— replication package 無此 0.3/0.7 輸出，屬 unsubstantiated claim，予以移除（研究誠實）。
- **位置**：main.tex S3 定義（原 line 101）+ Table 1 note S3 描述同步改為 continuous interpolation。

### C-01 — hasbrouck2009 不支撐「SPY 1–2 bps spread」→ 改述（保留非 orphan bibitem）
- **原問題**：line 108 用 `\citep{hasbrouck2009}` 支撐「SPY typical bid-ask spread of 1–2 bps」，但 Hasbrouck (2009, JF) 估的是 US 股票整體 effective trading cost（daily-data 估法），非 SPY 特定 quoted spread。
- **修法**：改述為「exceeds the small effective trading costs documented for liquid U.S. equities \citep{hasbrouck2009}」（此為該文真正支撐的論點）+「well above SPY's quoted bid-ask spread — on the order of 1–2 bps for this exceptionally liquid ETF」（市場事實陳述，不掛在 Hasbrouck）。hasbrouck2009 bibitem 保留（仍被正確引用，非 orphan）。

## 待辦（compute followup — 見 next_tasks）

### S-02 — Cross-OOS 只有 4/6 windows，需補 2017–18 / 2021–22
- **為何不在本 fire 做**：主腳本 `k811v2_insurance_premium_vov_fixed.py` (a) live-fetch yfinance（line 73，非 pinned snapshot，違 reproduce 規則）、(b) 覆寫 archived `k811v2_..._results.json`（line 972，blast radius）。倉促重跑不符研究誠實。
- **followup 任務**（`paper2_vt_insurance_cost_s02_cross_oos_rerun`）：
  1. 用 pinned snapshot（`auto_adjust=False` raw-Close，per project reproduce rule）改造 cross-OOS runner，window grid 由 4 → 6（加 `("2017-01-01","2018-12-31")`、`("2021-01-01","2022-12-31")`，見 script line 705–708）。
  2. 輸出寫**新** JSON（不覆蓋 archived）。
  3. Codex code review 後才採信。
  4. 依 6/6 結果更新 main.tex §4.5 / Discussion / abstract 的 success-rate framing：若仍弱，把 S2 降級為「hypothesis-generating in-sample accounting result」、移出 contribution tier，只留 threshold-invariant decomposition 這條 robust 貢獻（review S-02 fix 指示）。
- **注意**：main.tex line 194 / 211 已誠實揭露此 4/6 incompleteness 為 provisional / pending re-runs，故現版仍為投稿誠實狀態，S-02 補完後再升級 framing。

## 版本狀態
- `body fixed (S-01/S-03/C-01) / S-02 compute follow-up pending`
- 目標期刊：FRL（est. 3.5★ once S-01/S-02/S-03 resolved per reviewer prediction）
