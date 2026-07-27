# Codex 二審：方向可預測性誠實 OOS 檢定（direction_predictability_signforecast）

你是資深計量金融審稿人（JBF/JFE 等級）。以**只讀 sandbox**審查一份宣稱「次日方向近似不可預測、波動率同框架下可預測」的 NULL 實驗。你的職責是**證偽**這個結論，特別是揪出任何會讓 NULL 變成假象、或讓表面 edge 復活的 bug。

## 凍結產物（審這些，不要改）

worktree：`.claude/worktrees/dispatch-slot-2-7087efc0-signfc/experiments/direction_predictability_signforecast/`

- `direction_predictability_signforecast.py`（sha256 302efae4…184f43）
- `direction_predictability_signforecast_results.json`（sha256 c6e63d44…c2a85e）
- `README.md`（sha256 9fa30a86…5e2ee7）
- `figures/*.png`

先跑 `shasum -a 256` 對上述三檔核對凍結雜湊；不一致就在報告首行寫 `STOP: freeze mismatch` 並停止。

## 必查項（逐項給 PASS/FAIL 證據，引用行號）

1. **Lookahead / 洩漏（最高風險）**：逐一驗證每個特徵確實只用 t−1 及更早資訊。
   - `ret_lag*`、`mom*`、`voladj_mom*`、`rv_d/w/m` 是否都有正確 `.shift()`；有無 off-by-one 讓 t 日資訊漏進特徵。
   - GARCH(1,1) 條件波動是否真為 causal（expanding refit + forward filter，不用全樣本估參）；估計失敗是否 log 而非 silent fallback。
   - StandardScaler 是否只 fit 訓練資料（pipeline 內），無測試資料洩漏。
   - walk-forward 每塊訓練列是否嚴格早於預測日；`init_train_days=1000`、`retrain_freq=63` 實作是否與宣稱一致。
   - 星期 dummy 不 shift 是否正當（第 t 日星期事前已知）。
2. **檢定正確性**：Pesaran–Timmermann 統計量與 p 值公式是否正確；DM 檢定是否用 Newey–White HAC、對的 benchmark（always-up）、單尾方向正確。Binomial vs 0.5 vs majority 是否分清楚。
3. **多重檢定校正**：BH 與 Bonferroni 是否對全部 8 條 PT p 值套用；README §5.2「校正後 0/8 顯著」是否與 results.json 一致。
4. **交易成本**：`成本 = c·|pos_t − pos_{t-1}|` 全翻倉 2 單位是否正確；US 2bp / TW 5bp 是否如宣稱；net/2×/buy-hold Sharpe 是否可由 results 復現。
5. **數字一致性**：README §5 各表數字是否逐格對得上 results.json（抽查 SPY/QQQ logistic 命中率、PT、DM、vol QLIKE 改善）。
6. **結論強度**：README §6 結論是否 **不超出** 證據範圍（NULL 宣稱、波動可預測對照、0050.TW R²=−1% 例外是否誠實揭露）。有無過度宣稱。

## 輸出格式（最後一行必為 VERDICT）

先寫逐項證據（行號 + 判定），再給 blocking defects 清單（無則寫「無」）。
**最後一行**只能是下列其一：
- `VERDICT: PASS`（方法與 lookahead 無阻斷性缺陷，結論不逾證據，可合併）
- `VERDICT: FAIL`（有至少一項阻斷缺陷；上面已列出）
