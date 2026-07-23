# K1436 v2：先解資料封鎖，再跑 HAR-RV + BTC funding rate

**Model**: opus / xhigh (per model_router, task_type=experiment)
**Task id**: `K1436_btc_funding_rate_vol_covariate`（P3，保底席）
**Worktree**: `.claude/worktrees/dispatch-slot-1-20b291d5-k1436`（branch `wt/dispatch-slot-1-20b291d5-k1436`）

## 為什麼是 v2（先讀這段，不要從零開始）

2026-06-09 的第一輪已經做過可行性稽核，結論是 **`BLOCKED_DATA_UNAVAILABLE`** —— 見
`experiments/k1436/README.md` 與 `experiments/k1436/k1436_results.json`。**先讀完這兩個檔**。
當時的雙重資料缺口：

1. repo 內沒有 canonical Binance perpetual funding-rate 序列
2. 沒有 BTC intraday cache，無法構造 HAR-RV 的 RV target（只有 daily OHLCV）

**所以本輪的第一優先不是跑模型，是把這兩條資料誠實地落地。** 如果資料真的拿不到，
如實回報第二次 BLOCKED 並寫清楚卡在哪 —— 但**不要在沒解封鎖前就用 daily proxy 硬湊 RV 然後假裝跑完**。

## 階段 1：資料落地（必須先完成）

- **Funding rate**：Binance USDⓈ-M futures REST `GET /fapi/v1/fundingRate`
  （`symbol=BTCUSDT`，`limit=1000`，用 `startTime` 分頁往前抓到 2020-01-01）。8h 結算 → 每日 3 obs。
  落地成 `experiments/k1436/data/btc_funding_rate_8h.csv`（欄位至少 `fundingTime, fundingRate`，UTC）。
- **RV target**：Binance klines `GET /fapi/v1/klines`（或 spot `/api/v3/klines`），
  `interval=5m`，同樣分頁抓 2020-01-01 起。落地 `experiments/k1436/data/btcusdt_5m.csv`。
  由 5m log-return 平方和構造 daily RV（UTC 日界，明確寫在 README）。
- 先讀 `.claude/skills/external-data-sources/SKILL.md` 確認 repo 既有的抓取慣例與已知陷阱，
  沿用既有 helper 就不要另寫一套。
- 兩個 CSV 都要記 **抓取時間、期間、列數、來源 endpoint** 到 results.json。
- **若 endpoint 被擋 / 抓不到**：如實記錄 HTTP 狀態與嘗試過的替代路徑，回報 BLOCKED，**到此為止**。

## 階段 2：實驗（資料落地成功才做）

- **Hypothesis**：BTC perpetual funding rate 反映 leveraged positioning 失衡，能預測 next-day RV。
- **Method**：HAR-RV baseline vs HAR-RV + lag-1 funding covariate。
  funding covariate = **t-1 日**三個 8h obs 的均值。
- 🔴 **Lookahead（最高風險，AGENTS.md 第 11 條）**：絕對不可用 t 日 funding 預測 t 日 RV。
  程式碼裡要有明確 `.shift(1)` 或等效 lag，並在 README 標出是哪一行。
- **評估**：OOS 2024-2026，rolling window W=1000，QLIKE + MSE，**DM test**（Harvey 修正）。
  baseline 與新模型必須用**同一個 lag 慣例、同一個 OOS 期間**。
- **Seed = 42**（bootstrap / 任何隨機程序都固定）。
- **差異化**：vs K1431（用 VIX9D-VIX，美股 implied spread），本實驗用 crypto realized leverage signal。
  開工前 grep `storage/memory/knowledge.json` 找 K1431 與其他 funding / crypto covariate 的既有結論，
  在 README 寫明差異，不要重跑已有結論。

## 誠實原則（AGENTS.md，違反即研究失敗）

- Null result 如實報告 —— **「funding rate 沒有預測力」是完全可接受的產出**，不要為了有結論而挑期間。
- DM 不顯著就寫不顯著，不要改成「有改善趨勢」。
- β 顯著但 QLIKE 沒改善 → 兩件事都要報，不可只報好的那個。
- 承認局限：Binance 單一交易所、perpetual 單一合約、2020 起樣本相對短。

## 硬性禁止

- ❌ 修改共享狀態：`storage/reports/feed.json`、`storage/memory/knowledge.json` /
  `thinking_journal.json` / `experiment_experiences.json`、Supabase / Mirror sync。
  knowledge 條目**只能主線程寫**（K1259）。
- ❌ `git worktree remove --force`。
- ❌ 資料抓不到就用 daily OHLCV 的 Parkinson / Garman-Klass 冒充 intraday RV 然後不說明。
  真要用 daily-range proxy，必須在 README 與 results.json 的 `limitations` 明確標成 proxy 且降級結論強度。

## 產出（success criterion）

更新 `experiments/k1436/` 三件套（覆寫舊的 BLOCKED 版本，但在 README 保留「v1 為何 BLOCKED」的歷史段）：

- `README.md` — 動機、與 K1431 差異、資料來源與期間、lookahead 防護在哪一行、方法、結果、DM 檢定、局限
- `k1436.py` — 可重跑，固定 seed
- `k1436_results.json` — **result artifact**，必須含：
  `data_status`（`materialized` 或 `blocked` + 原因）、`sample`（期間 / n_obs）、
  `baseline`（QLIKE / MSE）、`with_funding`（QLIKE / MSE）、`dm_test`（stat / p / 方向）、
  `beta_funding`（估計值 / se / p）、`verdict`（PASS / NULL / BLOCKED）、`limitations[]`
- `reproduce_spec.json`（artifact gate 要求）
- 圖表（RV 序列 + funding rate 疊圖、OOS 誤差比較）

自查：`python3 scripts/check_experiment_artifacts.py check --path experiments/k1436`

## 收尾

- 在 worktree 內 commit（**不要 merge**，主線程負責）。
- 最終回覆是資料不是給人看的信：`data_status` / `verdict` / QLIKE before-after / DM stat 與 p /
  β 與 p / 局限一句話。
