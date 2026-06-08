# Codex 24h Review — mile_7c104f6d (K469)

- **Article**: 換把獨立的尺量，結果還是一樣：HAR Log-Range 的可靠性再確認
- **Draft source**: `storage/reports/feed.json` (`mile_7c104f6d`)
- **Task**: `paper_review_mile_7c104f6d`
- **Reviewed**: 2026-06-09 台灣時間
- **Reviewer**: Codex CLI
- **Verdict**: **CONDITIONAL_PASS**

## 結論摘要

K469 的核心方法是乾淨的：`r²` proxy 的確獨立於高低點，HAR 的 scale calibration 只用各期
IS 均值，沒有 OOS leakage；HAR 也確實在 `SPY 5/5`、`EWT 4/5` 的 QLIKE 排名上領先 GJR。
但文章把這個結果包得太強，尤其把 `DM p<0.05` 當成足夠顯著，忽略了 repo 一貫的
Harvey `|t|>3.0` 標準。對研究讀者而言，這會高估「換 proxy 後結論依然很穩」的強度。

## Findings

1. **DM 顯著性 overclaim（高優）** — `storage/reports/feed.json:99`
   - 文中寫「SPY 5 個區間：HAR vs GJR DM 全部顯著（p < 0.05）」與「EWT 2019-2020 到 2023-2025：HAR 贏，DM 均顯著」。
   - 但若用 repo 常規的 Harvey 強門檻，`SPY 2019-2020` 的 `t=2.54`、`EWT 2019-2020` 的 `t=2.45`、`EWT 2021-2022` 的 `t=2.11` 都**不算強顯著**；EWT 4 個 HAR 勝局中只有 `2023-2025` (`t=4.30`) 過 Harvey。
   - 建議：把文字降成「傳統 5% 水準下顯著」或直接補一句「若用 Harvey 多重檢定門檻，只有 SPY 4/5、EWT 1/5 過關」。

2. **`8/10` robustness 講法略過了 `EWT 2017-2018` 的非顯著勝局（中優）** — `storage/reports/feed.json:99`
   - 文章把 `8/10` 寫成 proxy 替換後依然穩健，但 `EWT 2017-2018` 其實只是 QLIKE 小勝，`DM p=0.46`、`t=0.74`，屬統計噪音範圍。
   - 影響：讀者會把 `4/5` EWT 勝局當成相近強度的證據，實際上 EWT 的 robust 程度明顯弱於 SPY。
   - 建議：補一句「EWT 的 4/5 主要是方向性優勢，不等於 4/5 都有強統計支持」。

3. **校準比率敘述過度簡化（中優）** — `storage/reports/feed.json:99`
   - 文中寫「SPY 約 1.45、EWT 約 2.5」，容易讓人以為每個資產用固定單一 ratio。實際程式是**每個 OOS period 各自用該期 IS 均值重算 ratio**。
   - 例如 `SPY` 各期 ratio 約 `1.45–1.76`，`EWT` 全樣本 diagnostics 約 `2.53`。
   - 建議：改成「各 OOS 區間都用該段 IS 均值重新校準；SPY 多落在 1.45–1.76，EWT 約 2.3–2.5」。

4. **方法論透明度不足：README 仍是空殼，文章比實驗說明完整（低優）** — `experiments/k469/README.md:1`
   - `README.md` 幾乎沒有內容，實際方法都只在程式與 results JSON 裡。
   - 這不影響文章真假，但降低可審計性，也讓後續引用更容易只看 prose 不看 code。
   - 建議：補完整 README，至少寫資料期間、proxy 替換邏輯、IS ratio 校準、DM/Harvey 口徑。

## Recommendation

`CONDITIONAL_PASS`。核心 thesis 可以保留：

- 「K465 有 proxy favoritism」
- 「改用獨立 r² 後，HAR 排名優勢沒有翻轉」

但文章應補一段方法局限，至少說清楚：

1. `8/10` 是 ranking count，不等於 8/10 都有強統計支持。
2. DM 若用 Harvey `|t|>3.0`，證據比正文目前寫法弱。
3. scale calibration 是每期 IS 重新估，不是固定常數。
