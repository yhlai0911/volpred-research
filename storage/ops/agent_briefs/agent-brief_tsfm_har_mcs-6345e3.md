# K-experiment：時序基礎模型 × Log-HAR 的預測「組合」誠實檢定

**Model**: opus / xhigh (per model_router)
**Worktree（唯一可寫範圍）**: `.claude/worktrees/dispatch-slot-1-8157aca3-tsfmhar`
**Pool task**: `research_har_mcs_spy_0050_tw_tx_tsfm_timesfm_ttm_log_har`

## 開工前必讀（不可跳）
1. `docs/error_log.md` — 近期實驗踩過的坑
2. `.claude/rules/experiments.md`（含 §審查認證：merge 前要有 `review_verdict.json`）
3. `.claude/rules/worktree.md` — worktree agent 禁忌
4. 查庫內相似 K：先搜 `storage/memory/knowledge.json` 的 HAR / TSFM / forecast-combination 條目，
   **若已有同構結論，回報 `status=already_covered` 並停手**，不要再跑一次得到第 10 個 ML ceiling null。
5. 讀 ≥3 篇文獻（TimesFM / Tiny Time Mixers 原文 + forecast combination bias correction + MCS Hansen et al. 2011）

## 研究問題（**問法本身就是設計**，不可改寫成「誰贏」）
庫內 ML ceiling 已 **9 次確認**：novel ML 方法單挑計量 baseline 幾乎必 null。所以本實驗
**不問「TSFM 是否打敗 HAR」**（那題已知答案），而問：

> **把 TSFM 併進 Log-HAR 的預測組合，該組合是否穩定進入 MCS superior set？**

這是 forecast-evaluation 方法學題，不是模型競賽題。null 結果（組合進不了 superior set，或進了但
與單獨 Log-HAR 無法區分）**是完全可接受、可發表的結論**，請如實回報，不要為了「有發現」而調參。

## 資料
- SPY（yfinance）、0050.TW（yfinance）、TX 台指期（TAIFEX；見 `.claude/skills/external-data-sources/SKILL.md`）
- realized volatility 的建構方式請沿用庫內既有 HAR 實驗的慣例（先找出來，不要自創口徑）

## 方法
1. **Log-HAR** baseline（庫內已有實作就重用，不要重寫）
2. **TSFM**：TimesFM 與 TTM 的**免費開源權重**，zero-shot 預測。權重下載失敗 / 授權不允許 →
   回報 `status=blocked_no_weights`，**不准用別的模型假裝成 TSFM**
3. **組合**：(a) equal-weight (b) bias-corrected（Mincer-Zarnowitz 迴歸校正）
4. **檢定**：MCS（Hansen-Lunde-Nason）+ DM-HLN（小樣本修正）。loss 用 QLIKE 與 MSE 各跑一次
5. **out-of-sample 紀律**：rolling / expanding window，**任何用到未來資訊的步驟都是 fail**。
   bias correction 的校正係數只能用訓練窗估。這一條是本實驗最容易踩的坑（近期 K1095 就是
   pre-event branch 含 ex-post 資訊被 Codex 判 FAIL）。

## 誠實條款（硬性）
- 拿不到某個資產的資料 → 該資產標 `skipped` 並寫原因，不要用替代品頂替後宣稱做了三個市場
- MCS 結果不顯著 → 就寫不顯著。**禁止**改 loss function / 改窗長 / 挑資產直到出現顯著
- 所有數字必須能從 `<kid>_results.json` 追回；README 裡的每個數字都要在 JSON 裡找得到

## 產出（實驗三件套，只寫在 `experiments/<kid>/`）
- `experiments/<kid>/README.md`（研究問題 / 資料 / 方法 / 結果表 / 誠實的結論 / 限制）
- `experiments/<kid>/<kid>.py`（可重跑）
- `experiments/<kid>/<kid>_results.json` ← **result artifact**
- 圖表（MCS p-value、組合 vs 單模型 loss）

kid 請沿用庫內編號慣例自行取下一個可用號碼，並在 README 首行標明。

## Scope 限制
- **禁止**改 `storage/reports/feed.json`、`storage/memory/*.json`、`paper/**`
- **禁止** git push；在 worktree branch commit 你自己的 `experiments/` 檔案即可
- 完成後主線程會跑 Codex review → certify → merge

## 成功標準
JSON 內含三資產 × 兩 loss 的 MCS/DM 結果（或明確標註的 skip 理由），README 結論與 JSON 數字一致，
且結論用「組合是否進 superior set」的語言陳述，而非「誰贏誰輸」。
