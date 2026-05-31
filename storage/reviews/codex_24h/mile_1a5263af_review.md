# Codex Review — `mile_1a5263af`

## Verdict

`CONDITIONAL_PASS`

核心方法與結果方向大致成立。`experiments/k1135/k1135.py` 的 OOS 迴圈先用 `returns[:t_abs]` refit，再用 `last_r = returns[t_abs - 1]` 對 `t_oos` 做 forecast，lookahead 沒看到問題。`k1135_results.json` 也支持「QLIKE 對 M2 沒過、ES 明顯改善、VaR 部分改善」這個主結論。

但文章有 3 個需要修的地方，其中 2 個屬於結論強度 / 敘事準確度，1 個屬於明顯措辭污染。

## Findings

1. **一句話結論把 UNG 也寫成「從嚴重低估翻正」，超過實際證據。**
   - 文章 line 7 寫「**四個商品全部從嚴重低估翻轉成校準正確**」。
   - 但 `experiments/k1135/k1135_results.json` 顯示 UNG 的 baseline `M0` 在 1% ES 本來就 pass：`Z1_p=0.218`、`Z2_p=0.634`；並不是「嚴重低估」後才被救回來。
   - 真正符合「從 fail → pass」的是 USO、GLD、SLV。UNG 是「原本就過，M2 只是更接近 0」。
   - 建議把這句改成「USO、GLD、SLV 從明顯低估改善為通過；UNG 則從原本已可接受進一步貼近校準」之類的寫法。

2. **QLIKE 段把 USO 說成「顯著較差」，和文內自己採用的 BH 校正口徑衝突。**
   - 文章 line 46 寫「USO 甚至**顯著地**比 GARCH 常態還差」。
   - `k1135_results.json` 的 USO `M2_vs_M0` 是 `DM_HLN_t=-1.995`、raw `p=0.04623`，但 `BH_p=0.1849`。
   - 同段前一句已明說「經過多重檢驗校正後沒有任何一個商品的 QLIKE 改善是穩定的」，所以這裡再用「顯著地」會把 raw p-value 說成 final publication-level evidence。
   - 建議改成「USO 在 raw p-value 下偏向更差，但經 BH 校正後不構成穩健顯著」。

3. **結論末句的 `1% VaR 違約率上 3/4 改善` 口徑不清，且與 JSON 不自然對齊。**
   - 文章 line 119 寫「1% VaR 違約率上 **3/4 改善**」。
   - 如果你指的是 `Trinity_PASS`，那 `M2` 在 1% 其實是 `2/4 PASS`（UNG、GLD），不是 3/4。
   - 如果你指的是單純 violation rate 更接近 1%，那 4 檔其實都比 baseline 更接近目標：USO `1.52%→1.14%`、UNG `1.08%→0.95%`、GLD `2.16%→1.08%`、SLV `1.90%→1.33%`。
   - 這句目前介於兩種口徑中間，建議明確改成 `1% VaR Trinity 只到 2/4 PASS，但 violation rate 四檔都往目標方向修正`。

## Style / Wording

- line 63：`GLD 甚至跌出統計強度最強的 達顯著水準（顯著性 0.001）`
  - 這是明顯 sanitizer/normalizer 污染，句子壞掉了。
- line 113：`DQ 檢定 達顯著水準（顯著性低於 0.01）`
  - 同樣是機械式替換痕跡，讀感很差。
- line 17：`last shot`
  - 不是錯，但在整篇繁中敘事裡偏口語且突兀，可考慮換成「最後一次有理論希望的檢驗」。

## Verification Notes

- Lookahead 檢查：`experiments/k1135/k1135.py:760-838`
  - refit 用 `train_returns = returns[train_start:t_abs]`
  - forecast 用 `last_r = returns[t_abs - 1]`
  - 沒有 same-day return 洩漏進當期 forecast。
- 主要數字核對：
  - USO QLIKE M0/M2 = `1.412237 / 1.437549`，`DM_t=-1.995`，`BH_p=0.1849`
  - UNG 1% ES baseline `M0`：`Z1_p=0.218`、`Z2_p=0.634`
  - GLD 1% VaR violation rate：`2.16% -> 1.08%`
  - M2 1% ES 全部通過：USO `0.335/0.428`、UNG `0.960/0.853`、GLD `0.253/0.577`、SLV `0.982/0.270`

