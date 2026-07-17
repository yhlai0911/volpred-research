# K1684 E2 — own-market realized target 的 forecast-tail divergence cross-OOS gate

**Model**: claude-opus-4-8 / xhigh (per model_router experiment)
**Task**: assign_168aeaf8 (P2, experiment, starved)
**Worktree cwd**: `.claude/worktrees/dispatch-slot-1-79726798-k1684e2`（你只在此 worktree 內寫檔，禁碰主 checkout 的 feed.json / supabase / knowledge.json）

## 背景（為什麼是 E2 而不是走 paper route）
K1684 R3 primary Codex review = CONDITIONAL_PASS，但 E1 判為 **H2_UNSUPPORTED**（不能選 paper route）。
E1 的致命點：用 cross-asset RV plug-in 冒充 own-market test。E2 的唯一合法設計 = **forecast 與 realized target 為同一市場/同一標的**。

## 開工前必讀（先讀完再動手，逐一在 README 記錄讀到什麼）
1. `docs/error_log.md`（找 K1684 / forecast-tail / lookahead 相關條目）
2. knowledge K1684 全文（`storage/memory/knowledge.json` grep K1684）+ E1 review verdict
3. `experiments/` 內既有 k1684_ftd_e1 的 README/results（了解 E1 為何 H2_UNSUPPORTED，不得重蹈）
4. experiment-preamble（研究誠實 13 條 + 方法論 8 標準）
5. **檢索至少 3 篇文獻**（forecast-tail divergence / realized-target volatility forecasting / QLIKE-based OOS 比較），在 README 列出並標明如何支撐設計

## 實驗設計（硬性）
- **資料**：forecast 與 realized target 為**同一市場/同一標的**；OOS n ≥ 2500。禁止 cross-asset RV plug-in。
- **模型**：HAR-RV 與 GJR 使用**相同資訊集、相同 lag、相同共同樣本**（apples-to-apples）。
- **Lookahead 機械審計**：程式碼須有明確 `signal.shift(1)` 或等效 lag；README 附一段 lookahead audit 說明「t-1 訊號 → t 報酬」的對應點。
- **評估口徑**：
  - QLIKE（主）
  - canonical DM / HAC（Newey-West，bandwidth 用 canonical rule 並註明）/ Harvey (1997) 小樣本修正，|t| 門檻遵 Harvey
  - VaR：1% 與 5% 的 Kupiec (POF) + Christoffersen (CC) + Basel traffic light
  - ES：Acerbi-Székely Z1
  - FZ0 (Fissler-Ziegel) joint scoring
- **穩健性**：至少做**跨 OOS window / regime split**；對 scale 與 delta-c uncertainty 加 moving-block / block-bootstrap sensitivity（固定 seed）。
- **seed**：所有隨機程序（bootstrap / split）固定 seed 並在 README 記錄。

## 成功標準（三件套齊 + 誠實）
1. `experiments/k1684_e2/README.md`、`experiments/k1684_e2/k1684_e2.py`、`experiments/k1684_e2/k1684_e2_results.json`（= result-artifact，相對 cwd）三件套齊，另加圖表與參考文獻清單。
2. Lookahead mechanical audit 通過並在 README 記錄。
3. **結果不論正負皆誠實報告**（H2 支持 or NULL 都要如實寫；null 不是失敗）。
4. results.json 內含所有上述檢定的數值 + n_oos + 樣本期間 + 資料來源。
5. 完成後**必經 Codex review** 才決定是否走 paper route（本 agent 不自行宣稱 paper-ready；把 review 需求寫進 README「待審」段）。

## 禁止事項
- 禁 cross-asset RV plug-in 冒充 own-market。
- 禁 same-day 訊號乘 same-day 報酬。
- 禁假數字 / 禁未跑就宣稱收斂。
- 禁寫 knowledge.json（由主線程收）。
- 禁 git push / --no-verify。

## 產出（給收件 fire 的 followup 用）
- results.json + README + py + 圖表全部落在 worktree 的 `experiments/k1684_e2/`。
- 在 README 末段寫一段「**COLLECTION NOTES**」：本次結論一句話（H2 supported / NULL）、關鍵數字 3 個、待 Codex review 的爭點、建議 paper route yes/no。
