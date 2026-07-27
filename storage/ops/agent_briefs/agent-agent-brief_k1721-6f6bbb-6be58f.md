# K1721 — GPR 日頻 Acts vs Threats 分解對 vol 的不對稱預測

**Model**: opus / xhigh (per model_router)
**Task id**: K1721 (P3 experiment)
**Worktree cwd**: `.claude/worktrees/dispatch-slot-3-87c7269d-k1721`（唯一允許寫入處；禁碰 canonical checkout、禁 git add/commit，merge 由後續 fire 走 merge_worktree.sh）

## 研究問題（grounded：research_program.md line 574）

Caldara-Iacoviello Geopolitical Risk (GPRD) 日頻指數可拆為 **GPRA（Acts，已發生事件）**與
**GPRT（Threats，威脅/風險言論）**。假說：兩者對已實現波動的預測力**不對稱** —— Threats 帶前瞻/
不確定性成分，可能對未來 vol 有增量預測力，而 Acts 多為當下衝擊。將 GPRA/GPRT 加入 HAR-RV
基準，檢定對 **SPY / GLD / XLE / ITA**（ITA=航太國防 ETF）在不同 horizon（1/5/22 日）的增量預測力。
來源：Caldara & Iacoviello (AER 2022) + IMF GFSR 2025-04 Ch.2。

## 資料

- GPR 日頻：Caldara-Iacoviello GPRD（GPRD_ACT / GPRD_THREAT 分項），從官方資料頁下載日頻 csv。
  取用方式見 `.claude/skills/external-data-sources`（若已有本地快取優先用；無則下載並記錄來源 URL 與抓取日）。
- 標的 RV：SPY / GLD / XLE / ITA 日頻 OHLC（yfinance），以日內 range 或 daily squared return 建 RV proxy；
  盡量長樣本（GPRD 可回溯數十年，RV 受 yfinance 限制 → 以可得交集窗為準，README 記錄）。

## 方法（依 .claude/rules/experiments.md — 先讀）

1. **README.md**：motivation + method + **lookahead policy** + success criteria（明確 CONDITIONAL_PASS / PASS 門檻）。
2. **K1721.py**：
   - 基準 HAR-RV：RV_t = β0 + β_d·RV_{t-1} + β_w·RV_{t-1:t-5} + β_m·RV_{t-1:t-22} + ε。
   - 擴充模型：加入 lagged GPRA、GPRT（分別與同時），比較 in-sample adj-R² 與 **out-of-sample** QLIKE / RMSE
     （expanding 或 rolling window，OOS 一定要有）。
   - 不對稱檢定：GPRA vs GPRT 係數差異的顯著性；跨四資產比較（避險 GLD、能源 XLE、國防 ITA、大盤 SPY 預期方向不同）。
   - **嚴禁 lookahead**：所有 predictor `signal.shift(1)`；固定 `seed=42`；OOS 切分不得用未來資訊。
   - 統計檢定：係數 t-stat + **Diebold-Mariano / Clark-West** 比較 HAR vs HAR+GPR 的 OOS 預測差異。
3. **K1721_results.json**：byte-traceable outputs（樣本窗、各資產各 horizon 的係數/p-value/OOS QLIKE/DM 統計量）。

## 產出物（相對 cwd）

- `experiments/K1721/README.md`
- `experiments/K1721/K1721.py`
- `experiments/K1721/K1721_results.json`  ← result-artifact，runner 只驗存在

## 誠實與 sanity check（HARD）

- 研究誠實 > 一切：不得編數字；GPR 對 vol 無增量預測力（NULL）是完全可接受且有價值的結論。
- 多資產 × 多 horizon × Acts/Threats = 多重檢定 → 報告時註明並考慮 multiple-testing 校正，不要只挑最顯著那格宣稱發現。
- Mission sanity check：結論須能回答「地緣政治風險的 Acts vs Threats 分解，是否為 vol 的增量可預測驅動，且是否跨資產不對稱」。

## 收尾

- 完成後由後續 fire 的 PHASE A 收：Codex review（primary path；額度不足則 subagent/audit fallback）
  → CONDITIONAL_PASS 以上才寫 knowledge entry → merge worktree。
- 本 agent job 只負責產出上述三檔並自我驗證數字一致，不寫 knowledge.json、不 merge。
