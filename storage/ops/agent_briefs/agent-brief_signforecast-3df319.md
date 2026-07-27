# 實驗 Brief：方向（漲跌）可預測性的誠實樣本外檢定

**Model**: opus / xhigh (per model_router)
**Task id**: research_direction_predictability_signforecast
**Source**: 老闆 Telegram msg855（研究線為何不多研究漲跌預測）
**Experiment id**: `direction_predictability_signforecast`
**Worktree cwd**: `.claude/worktrees/dispatch-slot-2-7087efc0-signfc`（你就在這個 worktree 內工作，禁止碰 main checkout）

## 研究誠實原則（最高優先，先讀 canonical_root/AGENTS.md §研究誠實）
- 這是**誠實方向檢定，非過度承諾**。先驗假說：方向近隨機漫步（EMH），次日 sign 命中率難穩定 > 50%。
- **Lookahead bias 是最高風險**：所有特徵必須 `signal from t-1 → return at t`；程式碼要有明確 `.shift(1)`；嚴禁 same-day 訊號乘 same-day 報酬。
- 隨機程序固定 seed（train/test split、gradient boosting、任何抽樣）。
- Null 如實報告；結論強度不得超過證據。若有 edge，必須過**多重檢定校正 + 交易成本**後仍成立才算數。

## 資料
- 資產：`SPY`, `QQQ`, `0050.TW`, `TWII`（用專案既有資料源；us 走 yfinance/storage，tw 走既有 storage）。先做資料診斷：樣本期間、N、缺值、對齊。
- 標的：次日報酬正負號 `y_t = sign(r_t)`，`r_t = close_t/close_{t-1} - 1`。定義 0 報酬歸類規則並記錄。

## 特徵（全部 lag，t-1 之前可得）
- 既有 HAR-RV / GARCH 族波動率特徵（realized vol、GARCH 條件波動、HAR 分量 RV_d/RV_w/RV_m）。
- 報酬滯後與動能：`r_{t-1..t-k}`、多窗口動能（5/10/21 日）、波動調整動能。
- 可加：波動率狀態（高/低 regime）、星期效應 dummy。全部確保 t-1 資訊集。

## 模型與評估
- 分類器：logistic regression + gradient boosting（兩者對照）。
- **Rolling / walk-forward 樣本外**：固定訓練窗，逐步前推預測次日 sign。記錄每資產 OOS 命中率 vs 50% 基準。
- 正式檢定：
  - **Pesaran-Timmermann (1995/2004)** 方向準確度檢定（PT statistic + p 值）。
  - **Diebold-Mariano** 與 naive 基準（always-up / majority-class / random）比較。
  - 命中率的 binomial 檢定 + Newey-West 穩健。
- **多重檢定**：4 資產 × 2 模型 = 8 條，套 Benjamini-Hochberg 或 Bonferroni，報 adjusted p。
- **交易成本**：把 sign 預測轉成 long/short 部位，扣單邊成本（US ~1-2bp、TW ~4-5bp+稅，記錄假設），算成本後 Sharpe / 命中率 edge 是否存活。
- **對照波動率可預測性**：同資產同框架下，波動率（QLIKE / R²_oos）可預測性 vs 方向可預測性，量化「為什麼波動好預測、方向難」。

## 文獻 grounded
- Christoffersen & Diebold (2006) — 波動可預測但方向可預測性隨 horizon/vol 條件變化。
- Pesaran & Timmermann (1995, 2004) — 方向預測與市場可預測性檢定。
- 開工前在 knowledge.json 檢索既有相關 K（方向/sign/momentum），避免重複；README 引用。

## 交付（實驗三件套，缺一不可，全在 worktree 內）
- `experiments/direction_predictability_signforecast/README.md`（假說、資料來源與期間與 N、方法、結果表、正式檢定、交易成本、結論與局限、文獻）
- `experiments/direction_predictability_signforecast/direction_predictability_signforecast.py`（可重跑、固定 seed、有 shift(1)）
- `experiments/direction_predictability_signforecast/direction_predictability_signforecast_results.json`（**必產出，收件驗證此檔存在**：每資產每模型 OOS 命中率、PT stat/p、DM、adjusted p、成本後 edge、vol 對照）
- 圖表（命中率 vs 基準、rolling 命中率、方向 vs 波動可預測性對照）放同目錄 figures/。

## 完成後
- 自我核實：results.json 數字與 README 敘述一致（不得反向宣稱）；命中率的信賴區間；PT/DM 口徑正確。
- 收件 fire 會派 Codex round 二審 + 合併 worktree + 寫 knowledge.json（agent 禁止自己寫 knowledge.json，K1259 教訓）。
- 若結果為 null（命中率不穩定 > 50% 或成本後消失）→ 照實寫，這就是有價值的結論。
