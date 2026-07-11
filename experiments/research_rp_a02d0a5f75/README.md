# 波動率管理因子動物園：固定校準的即時 OOS 再驗證

## 研究問題

Moreira and Muir (2017) 顯示，因子波動升高時降低曝險，能提高多個因子的 Sharpe ratio 與 spanning alpha；Cederburg et al. (2020) 則指出，這些優勢通常無法由即時投資人樣本外取得。這個實驗用四個長期美股因子（SMB、HML、MOM、QMJ）做固定校準的直接再驗證，並量化額外槓桿調整成本對結果的影響。

與 K1522 的差異是：K1522 用債券 ETF 建立橫斷面因子 proxy；本實驗直接使用官方發布的美股 long-short factor returns，問題是「個別因子的 inverse-variance scaling 是否在 2000 年後直接勝過原因子」。

## Data & Methodology

- 方法類型：`empirical`，使用公開、實際發布的因子報酬；不做因果推論。
- Ken French Data Library：每日 SMB、HML 與 MOM。French 檔以百分點表示，腳本轉成小數報酬。
- AQR Data Library：每日美國 QMJ（`QMJ Factors` 工作表的 `USA` 欄）。AQR 檔已是小數報酬。
- 資料 vintage：每次執行記錄下載檔 SHA-256、資料起訖日與樣本數。AQR 明示更新時會重建完整歷史，因此結果是「本次 vintage」的估計，不宣稱 point-in-time vintage robustness。
- 共同樣本：四因子皆有資料的交易日；正式期間由實際下載檔決定。
- 校準期：共同樣本起點至 1999-12-31。
- OOS：2000-01 起至共同樣本終點；另報 2000-2012 與 2013-最新兩個子期。
- 月 t 的 realized variance 為該月 daily factor returns 平方和；月 t+1 權重只使用月 t 已完成的 RV：`signal = inverse_variance.shift(1)`。
- 每個因子的縮放常數只用 2000 年前資料估計，使校準期 managed/unmanaged volatility 相同。OOS 全程固定，不重估、不使用 OOS 報酬。
- 比較 uncapped 與 cap=3.0；成本敏感度為每次 factor-level exposure 變動的 0/10/25/50 bps。
- 成本口徑是 **overlay turnover lower bound**：只有 factor-level scaling 變動，沒有 constituent holdings，不能重現 Barroso and Detzel (2021) 的 stock-level netting、spread、short-leg 與基礎因子換股成本。任何結果只能描述為「額外 scaling cost 敏感度」，不可寫成完整交易成本後績效。
- 統計：paired stationary bootstrap（seed=42、2,000 次、平均 block=12 個月）檢定 Sharpe difference；`strategy_dm_test` 比較月報酬；primary 四因子做 BH-FDR；Harvey 門檻採 `|t| > 3`。

## 事前成功標準

Primary 規格定為 cap=3.0、overlay cost=25 bps。只有在下列條件同時成立時，才可稱為跨因子的條件式支持：

1. 至少 3/4 因子 OOS Sharpe 高於 unmanaged；
2. 至少 2 個因子的 paired bootstrap 95% CI 不含 0，且 Harvey/FDR 方向一致；
3. 改善不是只由單一 OOS 子期驅動；
4. 權重、turnover、最大曝險與回撤沒有顯示不可實作的極端值。

否則如實記為 mixed/null。即使 primary 通過，也只能支持免費 factor-return layer 的證據，不能直接宣稱 constituent-level 可交易。

## 防錯與可重現性

- 固定 `SEED = 42`。
- 所有 OOS 權重均由前月資訊產生；程式含明確 `.shift(1)`。
- unmanaged baseline 與 managed 使用完全相同的月報酬列。
- 結果 JSON 先寫同目錄暫存檔、重新解析驗證，再 `os.replace` 原子替換。
- `analysis_panel.csv` 保存每月原因子報酬、primary 權重與 managed return；`summary_table.csv` 保存所有 cell，便於逐 byte 複核 JSON 摘要。
- 原始 ZIP/XLSX 預設 cache 在 `data/`，由 `.gitignore` 排除；可用環境變數指定已下載的唯讀檔。

## 執行

```bash
uv run python experiments/research_rp_a02d0a5f75/research_rp_a02d0a5f75.py
```

可選環境變數：`FF5_DAILY_ZIP`、`MOM_DAILY_ZIP`、`AQR_QMJ_XLSX`。

## 參考文獻

- Moreira, A., & Muir, T. (2017). Volatility-Managed Portfolios. *Journal of Finance, 72*(4), 1611-1644. https://doi.org/10.1111/jofi.12513
- Cederburg, S., O'Doherty, M. S., Wang, F., & Yan, X. (2020). On the Performance of Volatility-Managed Portfolios. *Journal of Financial Economics, 138*(1), 95-117. https://doi.org/10.1016/j.jfineco.2020.04.015
- Barroso, P., & Detzel, A. L. (2021). Do Limits to Arbitrage Explain the Benefits of Volatility-Managed Portfolios? *Journal of Financial Economics, 140*(3), 744-767. https://doi.org/10.1016/j.jfineco.2020.11.006
- DeMiguel, V., Martin-Utrera, A., & Uppal, R. (2024). A Multifactor Perspective on Volatility-Managed Portfolios. *Journal of Finance, 79*(6), 3859-3891. https://doi.org/10.1111/jofi.13395
- Asness, C. S., Frazzini, A., & Pedersen, L. H. (2019). Quality Minus Junk. *Review of Accounting Studies, 24*, 34-112. https://doi.org/10.1007/s11142-018-9470-2

## 結果

正式結果待 pre-run Codex review 通過後由實際執行填入。
