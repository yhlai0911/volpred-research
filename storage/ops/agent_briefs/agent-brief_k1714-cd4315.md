# K1714 — 已實現共變異數 HAR → 最小變異組合的樣本外檢定

**Model**: opus / xhigh (per model_router, task_type=experiment)
**Task id**: `K1714`（統一任務池；完成後由收件班負責 complete）
**Worktree（你的 cwd）**: `.claude/worktrees/dispatch-slot-3-3896dcaa-k1714`，branch `wt/dispatch-slot-3-3896dcaa-k1714`
**產出契約**: `experiments/K1714/K1714_results.json`（byte-traceable）+ `experiments/K1714/README.md` + `experiments/K1714/K1714.py`

## 開工前必讀

1. `.claude/rules/experiments.md` — 這是實驗的規格書，不是建議。README / code / results.json 三件套、`signal.shift(1)`、`seed=42`、lookahead policy、success criteria 事前寫死。
2. `CLAUDE.md` 的研究誠實條款。**假數字 = 整個實驗作廢**。
3. 庫內相鄰 K：`experiments/k529`（multi-scale HAR 結構）、K442（long memory 確認但無 OOS 增益）。本實驗庫內幾乎全是**單變量**波動率預測，**realized covariance matrix → 組合**是新面向 —— 差異化就在這裡，不要把它做成又一個單變量 HAR。

## 研究問題

對多資產用 HAR **直接建模 realized covariance 矩陣**，比對傳統 shrinkage / EWMA 共變異數估計，在 **GMV（global minimum variance）組合**上的樣本外表現。

**資產集**：擇一並在 README 說明理由 —— (a) SPY/QQQ/GLD/TLT（跨資產類別，相關性結構有變化，yfinance 資料乾淨）或 (b) TW0050/TSMC/金融股（在地角度，但要處理台股停牌與除權息）。**建議 (a) 為 primary**：資料品質與可重現性優先，若時間允許再把 (b) 當 robustness。

**資料**：yfinance 日資料。日頻下沒有 intraday realized covariance，所以你必須明確選擇並在 README 交代 RV/RCov proxy 的建構方式（例如 Parkinson range-based variance + 滾動窗口共變異數，或以日報酬外積的滾動平均為 realized 代理）。**這個選擇是本實驗最大的方法論風險，不要含糊帶過** —— 若 proxy 本身就是滾動平均，HAR 對它建模的增益可能只是在對平滑後的東西再平滑，README 必須正面回答「我的 RCov proxy 有沒有讓 HAR 的優勢變成套套邏輯」。

## 方法要求

1. **參數化**：Cholesky 或 log-matrix（matrix logarithm）參數化，確保預測出的矩陣**正定**。做哪一個都行，但要說明選擇理由，並在 results.json 記錄每期預測矩陣是否通過正定檢查（失敗率是一個要報的數字）。
2. **對照組（至少三個）**：
   - sample covariance（滾動窗口）
   - Ledoit-Wolf shrinkage
   - EWMA（RiskMetrics λ=0.94）
3. **評估指標**：GMV 組合的 **OOS 實現波動**（主要）、**換手率**（turnover，次要但必報 —— 高頻換手的「低波動」在成本後可能是幻覺）、權重集中度。
4. **推論**：OOS 波動差異要有**統計檢定**，不是只報點估計。多個比較要做**多重比較修正**（BH FDR 或 Bonferroni，family 事前在 code 裡寫死）。
   ⚠️ 這一條是 K1623 五輪審查連續被打回的直接原因：只報點估計、宣稱「顯著更好」而沒有檢定與修正 = 必 FAIL。
5. **Lookahead**：所有共變異數估計與參數估計只能用 t 以前的資料；rebalance 用 `shift(1)`。在 README 寫死 lookahead policy 並在 code 裡有可驗證的對應。

## Success criteria（事前寫死，不許事後調整）

在 README 事前寫下：什麼結果算 HAR-RCov 贏、什麼算平手、什麼算輸。**NULL 結果完全可接受且同樣有價值** —— 「realized-cov HAR 在 GMV 上贏不過 Ledoit-Wolf」是一個乾淨、可發表、對組合構建產品直接有用的結論。不要為了做出正結果而調參數或挑期間。

## 宣稱紀律（本班從 K1623 學到的，直接寫進你的 brief）

- 只寫**證據撐得住**的宣稱。點估計方向 ≠ 統計顯著；統計顯著 ≠ 成本後可交易。
- **沒做過的測試不要暗示做過**。沒做交易成本分析就不要對「可交易性」表態。
- README 每一條 headline 宣稱，都要能指到 results.json 裡的一個具體欄位。

## 完成後

1. 在 worktree 內 commit（**不要** merge，merge 由收件班走 `scripts/merge_worktree.sh`）。
2. 產出 `experiments/K1714/K1714_results.json`。
3. **不要自行寫 knowledge.json**（K1259 教訓）—— 要等 Codex primary-path review 至少 CONDITIONAL_PASS。
4. 在 README 末段寫一段「給審查者：我認為最脆弱的三個地方是什麼」—— 誠實列出你自己最不放心的設計選擇。
