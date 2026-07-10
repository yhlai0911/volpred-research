# Agent Brief — K1679：銀行存款週期是否放大區域銀行波動

**Model**: opus / xhigh (per task_type routing: experiment)
**Topology**: worktree（`.claude/worktrees/agent-k1679`，branch `agent-k1679`）
**Task id**: K1679（已 claim，status=in_progress，owner=hourly-23）
**時間預算**: 45 分鐘。做不完就縮小 scope（減資產、減 horizon），**不要交半成品**。

---

## 0. 開工前必讀（依序）

1. `docs/error_log.md` — 至少讀最近 30 條，避免重犯
2. `.claude/rules/experiments.md` — lookahead / seed / audit / DM-HAC 硬規則
3. `.claude/skills/autonomous-research/references/experiment-preamble.md`
4. `.claude/skills/external-data-sources/SKILL.md` — FRED / yfinance 取用方式
5. 知識庫查相似 K：`jq` 搜 `storage/memory/knowledge.json`（**禁止整檔 cat/read**）
   - 已知相關但不重疊：K1120（TLT FinStress，rate-hike regime）、K1265（VIX-managed portfolio NULL）
   - 若發現有 K 已做過「存款流失 → 銀行波動」，**立刻停手回報 arc-covered**，不要硬做

## 1. 研究問題

家庭存款週期（deposit inflow/outflow）是否**領先**區域銀行的波動與下檔風險？

RFS 的 "bank deposits and the stock market" 線索：股市 boom 時家庭把存款移往股市 → 銀行 funding 變薄 → funding fragility 上升。若成立，存款成長率應能**領先預測** KRE 的 RV / downside semivariance / drawdown。

**這是 VolPred 的 funding-risk proxy 候選**（monetization angle：若成立可進策略線做 regional-bank vol regime filter；若 null 也是可發佈的 null result）。

## 2. 資料

| 來源 | 序列 | 頻率 | 注意 |
|---|---|---|---|
| FRED | `DPSACBW027SBOG`（All Commercial Banks, Deposits, weekly, SA） | 週 | **H.8 發布 lag ≈ 8 天**（週三資料、次週五發布） |
| FRED | `DPSACBM027SBOG` 或同族月頻 deposits（若週頻缺） | 月 | 備援 |
| yfinance | `KRE`（區域銀行 ETF）、`XLF`（金融）、`SPY`（控制變數） | 日 | 2007+ |

**FRED key 在主 checkout 的 `.env.local`**（worktree 沒有）：
```bash
set -a; source /Users/yhlai0911/volpred-research/.env.local; set +a
```

## 3. 方法（硬規則）

- **Lookahead 是最高風險。** H.8 是**發布有 lag 的報表資料**：
  - `as-of date`（資料所指週）≠ `available date`（實際可交易時點）
  - 必須把每筆存款觀測值 **shift 到其真實發布日之後**才可進 signal。保守做法：`available_date = as_of_date + 10 days`（涵蓋 H.8 的 8 天 lag + 緩衝），並在 README 明寫此假設。
  - Signal 對齊：`signal from t-1, target at t`，程式裡要有明確 `.shift(1)` 或等效 reindex-ffill-then-shift。
- **Target**：KRE 的 forward realized vol（H=5、H=21 日），以及 downside semivariance、max drawdown（同 window）。
  - **多 horizon forward-label 不可共用同一個 DM/HAC horizon** — 每個 H 的 inference horizon 必須等於該 H（見 experiments.md）。
  - Forward-label 訓練列必須滿足 `target_end < forecast_origin`（`j + H < i`）。
- **Predictor**：存款 4 週 / 13 週成長率（log diff）、其 z-score；控制 SPY 過去 21 日 RV、VIX level（可選）。
- **檢定**：
  - 主檢定 = Newey-West HAC（lag = H）的預測迴歸 t 檢定；HAC lag 必須跟 H 對齊。
  - 對比 baseline（僅用自身 lagged RV 的 AR benchmark）做 **Diebold-Mariano with Harvey (HLN) small-sample correction**，QLIKE 用 `volpred.stats.model_evaluation.qlike_pointwise()`（**不要手寫反向 QLIKE**）。
  - 多重檢定：多個 horizon × 多個 predictor → **Bonferroni 或 BH-FDR**，在 results.json 明記校正前後 p 值。
- **seed=42** 固定；任何 bootstrap / 抽樣都要 seed。
- Bootstrap CI 若跑得慢（>5 分鐘），改小 B（例如 2000）或直接省略並在 README 註明；**不要為了跑滿而超時**。

## 4. 成功標準

實驗**成功**的定義是「結論可信」，不是「找到顯著結果」。**Null result 如實報告，同樣有價值**。

必交付：
- `experiments/K1679/README.md` — motivation / 資料與期間 / 樣本數 / 發布 lag 處理（明寫假設）/ lookahead policy / 方法 / 成功標準 / 結論 / 限制
- `experiments/K1679/K1679.py` — 可重跑，seed=42，含明確 shift/lag
- `experiments/K1679/K1679_results.json` — byte-traceable：每個統計量含 `value` / `n_obs` / `sample_start` / `sample_end` / `p_value` / `p_value_adjusted` / `hac_lag`
- 圖表（`experiments/K1679/*.png`）：至少 1 張（存款成長 z-score vs KRE forward RV 的散佈或 rolling 關係）

## 5. 禁止事項

- ❌ 禁改共享狀態：`storage/reports/feed.json`、`storage/memory/*.json`、Supabase / Mirror sync、`storage/next_tasks.json`
- ❌ 禁 `git worktree remove --force`
- ❌ 禁造假 / 湊數 / 「大約」數字；所有數字來自實際計算
- ❌ Sharpe / t 值高得離譜時**先懷疑自己的 bug**（特別是 lag 對齊）
- ✅ 只產出 `experiments/K1679/` 內檔案，完成後在 worktree 內 `git add experiments/K1679 && git commit`

## 6. 收尾

1. 跑通 `uv run --extra dev python -m pytest`？不需要（本實驗無 repo test），但 `K1679.py` 必須能從乾淨環境重跑並產生同樣的 results.json
2. worktree 內 commit（訊息：`exp(K1679): <一句話結論>`）
3. 回報格式依 `.claude/skills/autonomous-research/references/agent-result-template.md`：結論一句話 + 關鍵數字（含 n、期間、p 值）+ 限制 + 是否建議寫 knowledge

**主線程會做的事（你不要做）**：merge worktree、Codex review、寫 `knowledge.json`、寫 work_log、發文。
