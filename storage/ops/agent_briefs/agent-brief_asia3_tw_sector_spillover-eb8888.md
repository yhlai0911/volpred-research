# 實驗 brief — ASIA-3：台股產業層級波動溢出網絡

**Model**: opus / xhigh (per model_router)
**Task id**: asia3_tw_sector_spillover
**Worktree (你的唯一可寫工作目錄)**: `.claude/worktrees/asia3-a4fe4570`（branch `asia3-tw-sector-spillover-a4fe4570`）
**Experiment id**: `asia3_tw_sector_spillover`（產出放 `experiments/asia3_tw_sector_spillover/`）

## 研究誠實原則（最高優先，違反即實驗失敗）
先讀 worktree 內 `AGENTS.md`「研究誠實原則」全 11 條。重點提醒：
- 不可造假、不可虛構；所有數字來自實際計算。
- 資料來源、期間、樣本數必須標明。
- **Lookahead bias 是最高風險**：signal 用 `t-1`、報酬對 `t`；波動溢出網絡的估計窗口不可用到未來資訊。
- Null result 如實報告；結論強度不可超過證據。
- 觀察先於計算：先做資料期間診斷與描述統計，再估計。

## 開工強制前置（照順序做，缺一不可）
1. 讀 `docs/error_log.md`，特別找 spillover / DY / VAR / FEVD / 台股 相關教訓。
2. 搜 `storage/memory/knowledge.json`（用 grep/jq，**禁止整檔讀**）找相似 K：關鍵字 `spillover`、`Diebold`、`Yilmaz`、`FEVD`、`台股`、`sector`、`T5a`、`TAIEX`。對照 **T5a 已知結構**（TAIEX gamma > 0050 > TSMC）——你的產業層級結果要能和 T5a 對話。
3. 學術文獻 ≥3 篇：Diebold & Yilmaz (2012, IJF) generalized spillover index、Diebold & Yilmaz (2014, JoE) network connectedness、以及至少一篇產業/板塊層級 volatility connectedness 或台股相關實證。把引用寫進 README 參考文獻。

## 資料
產業代表股（yfinance，2026-07-15 smoke test 全數可用，但 smoke 只驗 2y）：
- 電子/半導體：2330.TW、2317.TW、2454.TW
- 金融：2881.TW、2891.TW
- 航運：2603.TW、2609.TW
- 塑化：1301.TW
- 光學：3008.TW

**資料要求（硬規則）**：
- 實驗要拉**最長可得樣本**（不是 smoke 的 2y）。先做資料期間診斷：各標的起訖日、缺漏、除權息跳空、停牌。
- OOS 期必須**至少涵蓋一次空頭**（例如 2022 全球熊市、或更早）。
- 跨市場/跨標的**假日 alignment** 依 `docs/methodology.md`（或 `research_program.md` 指向的 methodology）處理；不可用前向填補製造假相關。
- 波動度量：用已實現波動或條件波動皆可，但要說明口徑；若用日報酬平方/GARCH 需一致。

## 方法
1. **Diebold-Yilmaz spillover index**（connectedness）：
   - **必用 generalized FEVD（GFEVD, Pesaran-Shin）**，不可用 Cholesky-FEVD —— Cholesky 對變數排序敏感、會產生排序假象。這是本任務點名的陷阱。
   - 報告：total spillover index、directional（to / from each sector）、net spillover、net pairwise（產業對產業）。
   - rolling window 版本觀察時間演化（窗長度、步進要說明並做敏感度）。
2. **Granger 網絡**：產業間 Granger causality 網絡作為 robustness / 補充視角。
3. **統計嚴謹**：
   - 若要做預測比較，DM 檢定用 canonical `volpred.stats.model_evaluation.dm_test`（遵守 HAC bandwidth 規則），不可自刻。
   - VAR lag 選擇用資訊準則並報告；殘差做基本診斷。

## 產出（實驗三件套 + 圖表，缺一不可）
在 `experiments/asia3_tw_sector_spillover/`：
- `README.md`：動機、資料（來源/期間/樣本數）、方法、結果表、與 T5a 的對照、限制、參考文獻。
- `asia3_tw_sector_spillover.py`：可重跑的完整腳本（含 signal.shift(1) 明確 lag）。
- `asia3_tw_sector_spillover_results.json`：所有數字（total/net spillover、網絡矩陣、rolling 序列摘要、檢定結果）。
- 圖表：spillover 網絡圖 + total spillover rolling 時間序列（存 assets/）。
- 收工前跑 `uv run python scripts/experiment_gates.py`（或 worktree 內對應路徑），全綠才算完成。

## 面向讀者的角度（供後續文章，不在本實驗發佈）
結論要能延伸出「產業輪動 technical analysis」的一般讀者角度：哪個產業是波動的**發送者**（淨溢出為正）、哪個是**接收者**，以及在空頭期網絡如何收斂/放大。但本 job 只做實驗與 JSON/README，**不寫 feed 文章、不碰 feed.json / supabase**。

## 收工契約
- 只在你的 worktree 內寫檔；不碰 canonical `storage/` 佇列。
- 完成後在 worktree 內 commit（ASCII message，含 task id `asia3_tw_sector_spillover`）。
- runner 會驗 `--result-artifact` 存在；請確保 `experiments/asia3_tw_sector_spillover/asia3_tw_sector_spillover_results.json` 落地。
- 若資料期間不足以覆蓋一次空頭、或某標的樣本嚴重不足 → 如實在 README 記錄限制並縮小宣稱，不可造數。
