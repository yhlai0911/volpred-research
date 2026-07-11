# Task: K1025_v3 — crypto-fear FEVD 修正重跑（KPPS generalized + pinned snapshot）

**Task ID**: fable0711_cryptofear_k1025v3
**Model**: opus / xhigh (per task_type routing)
**Type**: experiment (worktree)
**你在一個 git worktree 裡工作。只准產出 `experiments/k1025/` 內的檔案 + `scripts/tests/` 的一個新測試檔。禁改 feed.json / storage/memory/*.json / Supabase / Mirror sync。**

## 背景

`experiments/k1025/k1025_v2.py` 的 Diebold-Yilmaz spillover index 有**致命 bug**：
`statsmodels` 的 `FEVD.decomp` shape 是 `(neqs, periods, neqs)`，但 v2 把它當成 `(horizon, n, n)`
用 `decomp[-1]` 取最後一期 → 實際取到的是**第 3 個方程式的整條時間路徑**，不是 h=10 的 FEVD 矩陣。
結果 total spillover 被灌成 90.11%（接近恆等式），論文 crypto-fear-channel 的 §5.3/§6.1 敘事建立在這個假數字上。

正確切片：`res.fevd(h).decomp[:, -1, :]` → `(neqs, neqs)`，row=equation, col=shock。
參考已驗證的診斷腳本：`paper/crypto-fear-channel/review_history/fable_deep_review_20260711/dy_corrected_diagnostic.py`
（該腳本已在 pinned snapshot 上跑通，可直接改造）。

深審 brief 全文：`paper/crypto-fear-channel/review_history/fable_deep_review_20260711/README.md` §5 P0-1。

## 必做項目（產出 `experiments/k1025/k1025_v3.py` + `k1025_v3_results.json` + `k1025_v3_results.png` + 更新 `experiments/k1025/README.md`）

1. **修 FEVD 切片**：`decomp[:, -1, :]`，row-normalize 後算 DY total / directional / net index。
2. **主結果改用 KPPS generalized FEVD**（Koop-Pesaran-Potter / Pesaran-Shin；order-invariant）。
   統計量：total connectedness、directional TO/FROM、net（BTC 是 net transmitter 還是 receiver）。
   附 **兩種 Cholesky 排序**當 sensitivity（顯示 generalized 不受排序影響、Cholesky 會）。
3. **Pinned snapshot**：讀 `paper/crypto-fear-channel/data/spy_btc_usd_vix_2015-2026.csv`，
   `auto_adjust=False` 對應的欄位（`*_adj_close`），**SPY / BTC return 定義統一為 log return**
   （v2 的 SPY simple / BTC log 混用要修正；診斷腳本沿用舊定義，你要改成雙雙 log 並在 README 說明差異）。
   不再上網抓資料（禁 yfinance live fetch — 必須用 pinned CSV，reproducibility）。
4. **AR lag grid 延到 22**（`select_order(maxlags=22)`，AIC 選；記錄選到的 lag）。
5. **QR 加 lagged-VIX 控制**（quantile-Granger 規格）+ **moving-block bootstrap**（seed 固定，B≥500，block length 記錄）
   → 檢查原本的 sign-reversal 結論在加控制後是否存活。存活/陣亡都如實報告（null result 是結果）。
6. **Subsample DM 補 HAC**：per `.claude/rules/experiments.md` 硬規則 —
   HAC lag = `max(h-1, ceil(h^(1/3) * n^(1/3)))`，**優先用 `volpred.stats.model_evaluation.dm_test`**（canonical），
   不要自寫 local DM 蓋掉 canonical。若必須自寫，以 canonical 為對照下限。先看 loss differential 的 acf 再判斷方向。
7. **Rolling connectedness 圖**：200d rolling window 的 total connectedness（預期 COVID 2020 有峰值 — 這是修正後更強的故事）。
8. **機械 gate**：寫 `scripts/tests/test_fevd_iid_placebo.py` —
   對 iid Gaussian noise 的 3 變數 VAR 做同一個 FEVD pipeline，斷言 total spillover index ≈ 0（例如 < 15%）。
   若有人再犯同樣的 shape 誤切，這個測試會 FAIL。（比照 `scripts/tests/test_dm_hac_lag_ratchet.py` 的 ratchet 模式。）
   **測試必須 hermetic：不碰 canonical storage/、不寫 repo 外檔案。**

## 硬規則（違反 = 實驗失敗）

- **研究誠實**：所有數字來自實際計算；修正後 total spillover 預期落在 ~18-22%（若不是，如實報告你算到的，不要湊）。
- **固定 seed**（bootstrap / 任何抽樣）。
- **Lookahead**：rolling window 與 QR 特徵不得看未來；有 forward label 就 shift。
- 先讀 `docs/error_log.md`（近期 entries）+ `.claude/rules/experiments.md` 的 methodology 硬規則。
- `experiments/k1025/README.md` 要更新：說明 v2 的 bug、v3 的修正、v2 JSON 標 **superseded**（在 README 標註即可，
  **不要**手改 v2 的 results JSON — 永遠修流程不修資料）。
- README 必含：資料來源 / 期間 / 樣本數 / 方法 / 主要結果表 / 與 v2 的 before-after 對照 / limitations。

## 成功標準

- `k1025_v3_results.json` 含：generalized FEVD 矩陣、total/directional/net index、兩種 Cholesky 排序的 sensitivity、
  選到的 VAR lag、QR-with-VIX-control 係數 + bootstrap CI、subsample DM + HAC lag、rolling connectedness 序列。
- `scripts/tests/test_fevd_iid_placebo.py` 在本 worktree 內 `uv run --extra dev python -m pytest` PASS。
  （worktree 內**不要**用 `uv run pytest` — 會靜默掉到系統 py3.9。）
- README 完整；v3 圖表為真圖（matplotlib PNG）。
- 完成後在 worktree 內 `git add experiments/k1025/ scripts/tests/test_fevd_iid_placebo.py && git commit`。

## 完成後回報

一段摘要：修正前後 total spillover 對照、BTC net 方向（generalized vs 兩種 Cholesky）、QR sign-reversal 是否存活、
DM+HAC 結論、placebo 測試結果、以及這對 crypto-fear-channel 論文敘事的意涵（生 or 死）。
