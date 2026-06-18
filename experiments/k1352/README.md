# K1352: 美元指數作為跨資產波動條件變數（duplicate closure）

## 問題

原任務：

> 美元指數（DXY / UUP）作為跨資產 vol 的條件變數：強弱美元 regime 下 EM/商品/黃金 vol 的差異（yfinance）

## 判定

**VERDICT = SUPERSEDED_BY_K1439_AND_K1330**

K1352 是 `research_program.md` 同一行再次 auto-generated 出來的重複任務。它已被兩層既有產物覆蓋：

- `experiments/k1439/`：canonical empirical experiment，已實測 UUP/DXY regime 對 `EEM`, `GLD`, `DBC`, `USO`, `DBB` 的 21 日 realized volatility 條件差異。
- `experiments/K1330/`：已在 2026-06-14 將同題正式去重結案，判定 `SUPERSEDED_BY_K1439`。

本 tick 已重新執行：

```bash
uv run python experiments/k1439/reproduce.py
```

結果仍為 `CONDITIONAL_PASS`：只有 `USO` 在 level 與 trend 兩種美元 regime 定義下都通過 HAC + Bonferroni；`EEM/DBC/DBB` 方向為正但不達 paper-grade；`GLD` 為 null。

## 為何不重跑

若重跑 K1352，會複製 K1439 的設計與資料：

- 美元 proxy：`UUP`
- 資產：`EEM`, `GLD`, `DBC`, `USO`, `DBB`
- regime：強美元 / 弱美元
- lookahead guard：regime bucket 明確 `shift(1)`
- canonical inference：OLS-HAC / Newey-West，修正 21 日 RV overlap autocorrelation

重複跑不會增加新知識，反而會讓任務池與 research backlog 更難維護。正確處理是建立 machine-readable receipt 並關閉母本 checkbox。

## 文獻檢索

本次只做 framing，不新增實證 claim。查核來源：

- Lustig, Roussanov, Verdelhan, *Common Risk Factors in Currency Markets*：美元/貨幣共同風險因子背景。
  - https://www.nber.org/papers/w14082
- Lustig, Roussanov, Verdelhan, *Countercyclical Currency Risk Premia*：美元風險溢酬與 bad-times risk compensation 背景。
  - https://www.nber.org/papers/w16427
- Baur and McDermott, *Is gold the best hedge and a safe haven under changing stock market volatility?*：黃金 safe-haven channel 背景。
  - https://onlinelibrary.wiley.com/doi/10.1016/j.rfe.2013.03.001

## 防錯與限制

- 本 receipt 不新增策略回測，因此沒有 same-day signal/return join。
- `K1352.py` 仍明確記錄未來若轉成交易訊號必須使用 `signal.shift(1)` 或等效一階滯後。
- 不寫入 `knowledge.json`，因為這不是新的 empirical finding。
- 若未來要重開，只能做與 K1439 明確不同的問題，例如用實際 `DX-Y.NYB` 替代 UUP、加入 FRED real rates、或做 moving-block bootstrap robustness。

## Files

- `K1352.py`
- `K1352_results.json`
