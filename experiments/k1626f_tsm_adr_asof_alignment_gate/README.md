# K1626f — TSM ADR vs 2330.TW timestamp/asof 對齊 robustness gate

## 動機

K1626 的 Codex review 給出 `CONDITIONAL_PASS`，唯一必修 blocker 是：母實驗用 `TSM` 與 `2330.TW` 的 common-calendar inner join 後再 `diff()`，不是以實際收盤時間做 event-time/asof 對齊。台美假日不一致時，common-date 對齊可能：

1. 漏掉 ADR-only 日的最新可用 ADR 收盤資訊。
2. 把多日 return 聚成一格。
3. 讓 `.shift(1)` 的「前一筆」變成 common-calendar 前一筆，而不是「目標收盤前最近可得資訊」。

K1626f 的目的不是提出新結論，而是驗證 K1626 的核心結論「TSM ADR/US 資訊領先次日台股 2330.TW」在嚴格 timestamp/asof 對齊後是否仍成立。

## 文獻脈絡

本 robustness gate 接續 cross-listed / ADR price discovery 文獻：Hasbrouck (1995) 的多市場 price discovery / information share 架構、Eun and Sabherwal (2003) 的美加 cross-listing price discovery、Kim, Szakmary and Mathur (2000) 的 ADR 與 underlying price transmission、以及 Chen, Choi and Hong (2013) 對 cross-listed pair 非線性 price discovery 的延伸。這些文獻共同提示：雙市場同一證券的價格發現不能只用 date label 對齊，必須清楚處理交易時段、資訊順序、匯率與市場摩擦。

參考來源：
- Hasbrouck (1995), *One Security, Many Markets* — Journal of Finance.
- Eun and Sabherwal (2003), *Cross-Border Listings and Price Discovery* — Journal of Finance.
- Kim, Szakmary and Mathur (2000), *Price transmission dynamics between ADRs and their underlying foreign securities* — Journal of Banking & Finance.
- Chen, Choi and Hong (2013), *How smooth is price discovery? Evidence from cross-listed stock trading* — Journal of International Money and Finance.

## 資料

| 項目 | 內容 |
|---|---|
| ADR | `TSM` |
| 台股 | `2330.TW` |
| FX | `TWD=X` |
| 來源 | `yfinance 1.2.0` via `yf.download(auto_adjust=False)` |
| ADR 期間 | 2003-01-02 至 2026-07-02 |
| 2330.TW 期間 | 2003-01-01 至 2026-07-03 |
| ADR rows | 5,912 |
| 2330.TW rows | 5,807 |
| common-calendar equity days | 5,616 |
| seed | 42 |

報酬使用各市場自己的 `Adj Close` 連續交易日 log return。波動 proxy 沿用母實驗的 Parkinson range，因為此 gate 只檢查日資料 timing alignment，不引入 5-min RV。

## 方法

### 實際收盤 timestamp

- `2330.TW`：台灣交易日 13:30 Asia/Taipei。
- `TSM ADR`：美東交易日 16:00 America/New_York，轉成 Asia/Taipei；約落在台灣次日 04:00 或 05:00。

### asof 對齊規則

每個 target close 只允許使用「嚴格早於 target close timestamp」的最近 opposite-market close：

- **US→TW**：每個 2330.TW close 對上最近且更早的 TSM ADR close。
- **TW→US**：每個 TSM ADR close 對上最近且更早的 2330.TW close。

實作使用：

```python
pd.merge_asof(..., direction="backward", allow_exact_matches=False)
```

### 重跑項目

1. Return price discovery：eqA / eqB / controls。
2. Direction-specific asof Granger。
3. Parkinson vol transmission：eqVA / eqVB。
4. US→TW vol 的 HAC lag sensitivity 與 moving-block bootstrap block-length sensitivity。

## 對齊診斷

| 指標 | 數值 |
|---|---:|
| common-calendar equity days | 5,616 |
| ADR-only trading days | 296 |
| 2330.TW-only trading days | 191 |
| eqA US→TW asof rows | 5,804 |
| eqA 新增 loc-only target rows | 190 |
| eqA 在 common rows 中 predictor date 改變 | 149 |
| eqB TW→US asof rows | 5,911 |
| eqB 新增 ADR-only target rows | 296 |
| eqB 在 common rows 中 predictor date 改變 | 0 |

這證實母實驗的 common-calendar join 確實丟掉不少假日不一致資訊；尤其 US→TW 方向有 190 個額外台股 target rows，且 common rows 裡有 149 列的 ADR predictor date 會改變。

## 主要結果

### Q2 price discovery：核心 US→TW 結論穩健

| 規格 | K1626 common-date β / t | K1626f timestamp-asof β / t | 變化 |
|---|---:|---:|---:|
| eqA US→TW return | 0.3597 / 27.81 | 0.3661 / 27.41 | β +1.8%，同向且極顯著 |
| eqB TW→US return | 0.4918 / 25.15 | 0.4370 / 21.26 | β -11.1%，同向且仍顯著 |

asof 後，ADR/US 資訊領先下一個台股收盤的核心結果沒有消失，係數與 t-stat 幾乎維持。這通過 K1626 的主要 timing blocker。

但 Granger 需要降強度詮釋：

- US→TW asof Granger：lag 2-5 顯著，lag 1 不顯著。
- TW→US asof Granger：lag 3 與 lag 5 弱顯著，lag 1/2/4 不顯著。

因此，K1626 可說「asof 後核心 US-leading regression 穩健」，但不宜再用無條件語氣說「TW→US Granger 完全 null」。

### Q3 vol transmission：方向仍正，但 robust wording 要保守

| 規格 | K1626 common-date β / t | K1626f timestamp-asof β / t | 變化 |
|---|---:|---:|---:|
| eqVA US→TW vol | 0.1342 / 3.25 | 0.1413 / 3.57 | β +5.3%，同向 |
| eqVB TW→US vol | 0.2907 / 7.94 | 0.2972 / 7.34 | β +2.2%，同向 |

US→TW vol 的 block bootstrap sensitivity 全部 CI 不跨 0：

| block length | mean β | 95% CI |
|---:|---:|---:|
| 5 | 0.1472 | [0.0727, 0.2482] |
| 20 | 0.1438 | [0.0658, 0.2382] |
| 60 | 0.1445 | [0.0527, 0.2524] |

HAC lag sensitivity 顯示方向穩定但 Harvey `|t|>3` 不是每個 lag 都過：

| HAC maxlags | t-stat |
|---:|---:|
| 1 | 2.72 |
| 5 | 3.42 |
| 9 | 3.57 |
| 20 | 3.30 |
| 40 | 2.89 |

所以 vol 結論應寫成「US→TW 波動傳導方向為正，default HAC 與 block bootstrap 支持；但極寬 HAC lag 下 t-stat 低於 Harvey 門檻，不宜宣稱 fully robust」。

## Verdict

**Overall: CONDITIONAL_PASS。**

- **Asof alignment gate: PASS**。K1626 的 common-calendar timing blocker 已被 timestamp/asof 設計解除，且核心 eqA US→TW return 結論維持。
- **Price discovery: CONDITIONAL_PASS**。核心 regression 穩健，但 asof Granger 在 TW→US 較長 lag 出現弱顯著，不能再用「TW→US Granger 完全 null」強語氣。
- **Vol transmission: CONDITIONAL_PASS**。方向正、block bootstrap CI 不跨 0；但 HAC lag 1/40 低於 `|t|=3`，robust wording 要保守。

建議回填 K1626 wording：

> K1626f timestamp/asof robustness check confirms the core ADR/US-leading next-TW-close regression. The previous common-calendar alignment concern is resolved for the main result. Granger and volatility-transmission claims should keep the K1626f caveats.

## 限制

1. 仍是日資料，不是 intraday information share。不能替代 K1626b 的 5-min Hasbrouck / Gonzalo-Granger。
2. Asof Granger 使用 direction-specific close grid，非等距連續交易時鐘；HAC event-time regression 才是 primary evidence。
3. Parkinson range 是日內 high-low proxy，不是真 RV。
4. yfinance 不是 time-travel 資料源；本次結果以 2026-07-05 重抓資料為準。

## 檔案

- `k1626f_tsm_adr_asof_alignment_gate.py`
- `k1626f_results.json`
- `k1626f_asof_beta_comparison.png`
- `k1626f_vol_hac_sensitivity.png`

## 復現

```bash
uv run python experiments/k1626f_tsm_adr_asof_alignment_gate/k1626f_tsm_adr_asof_alignment_gate.py
```
