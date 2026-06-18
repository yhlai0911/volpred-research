---
title: "K1416：HLN(1997) 小樣本修正的正式套用 — Paper 3 TW0050-N225 主張的穩健性確認"
audience: research
status: published
tags: [HLN, DM-test, small-sample, copula, Paper3, robustness, TW0050]
experiment_refs: [K1416]
---

K1416 的任務很具體：Paper 3 在投稿前必須確認，TW0050-N225 跨市場 copula 模型的顯著性，不只在單一 OOS 窗口成立，在五個不同起點下全數通過正式 HLN(1997) 小樣本修正的檢定。K1412 用 worst-case n=10 的近似值推論，沒有正式套用 Harvey、Leybourne、Newbold(1997) 的公式，K1416 是那個缺口的正式填補。

## HLN 公式的實質意義

標準 Diebold-Mariano 檢定的 t 統計量依賴大樣本近似。實際上 OOS 樣本有限，且 h 步預測（h >= 2）會產生 MA(h-1) 誤差結構。HLN(1997) 提出的修正因子：

```
factor = sqrt((n + 1 - 2h + h(h-1)/n) / n)
```

對 h=1（一步預測），化簡為 `sqrt((n-1)/n)`。K1416 取用的就是這個公式，而不是 K1412 的 worst-case 近似。

修正量本身不大：n=2067 時，factor=0.999758，t_HLN 相對 t_raw 只縮減不到 0.04%。問題不在數量級，而在 **方法論正確性**。Paper 3 reviewer 若要求驗算，原始推論路徑必須走得通。K1412 的 worst-case proxy 走不通。

critical value 的計算同樣換成正式做法：`scipy.stats.t.ppf(0.975, df=n-1)`，取 t 分佈分位點，不再用常態近似 z=1.96。n=2067 對應的 critical value 是 1.9611，與 z=1.96 差異僅在第五位小數，但這是原則問題。

## 五個 OOS 起點的完整結果

Paper 3 的 baseline OOS 從 2015-06-01 開始（n=2067，精確值來自 paper3_E2_results.json）。K1416 另取四個起點，n_oos 透過 TW0050+N225 交集交易日比例推算（baseline 比例 0.515，+/-20 obs 誤差對 factor 差 < 4e-6，不影響結論）。

| OOS_START | n_est | factor | crit (5%) | t_HLN | PASS@5% | PASS@1% | margin |
|-----------|-------|--------|-----------|-------|---------|---------|--------|
| 2014-01-02 | 2332 | 0.999786 | 1.9610 | 3.2402 | PASS | PASS | +1.279 |
| 2015-06-01* | 2067 | 0.999758 | 1.9611 | 3.8915 | PASS | PASS | +1.930 |
| 2016-01-04 | 1955 | 0.999744 | 1.9612 | 3.6607 | PASS | PASS | +1.699 |
| 2017-01-03 | 1767 | 0.999717 | 1.9613 | 3.0442 | PASS | PASS | +1.083 |
| 2018-01-02 | 1580 | 0.999683 | 1.9615 | 3.0929 | PASS | PASS | +1.131 |

*baseline：n 直接來自 paper3_E2_results.json，其餘四個為估算值。

5/5 在 5% 和 1% 水準全部顯著，最小 margin = 1.083（2017 起點）。即使 n 估算誤差達 +/-20 obs，critical value 的變動幅度在第四位小數，不足以翻轉判定。

![5 OOS starts HLN t-stat bar chart](https://qxhfgdfzazwpkdgesavm.supabase.co/storage/v1/object/public/article-images/k1416_hln_5starts.png)

![t-stat vs critical value margin across OOS starts](https://qxhfgdfzazwpkdgesavm.supabase.co/storage/v1/object/public/article-images/k1416_hln_margin.png)

## Codex CONDITIONAL_PASS 的三個 caveats

Codex 給出的是 CONDITIONAL_PASS，不是 PASS。差別在於三個值得放進 paper footnote 的限制：

**第一，n_oos 是估算非實測。** baseline OOS（2015-06-01）的 n=2067 有精確依據，其他四個起點沒有。推算方式是用 calendar-day 比例乘上 baseline n，典型精度 +/-20 obs。對 HLN factor 的影響 < 4e-6，對顯著性判定沒有實質影響，但 paper 不能把估算寫成精確值。正確表述是「K1416 是 verified assumption + negligible-sensitivity approximation，不是 full rerun audit」。改進路徑留給 post-submission：在 paper3_E2.dm_test 上游直接輸出 per-OOS 精確 n。

**第二，5/5 是 sensitivity grid，不是 5 次獨立 replication。** 五個 OOS 窗口高度重疊，不符合 familywise error rate 校正的前提。這個結果能說的是「OOS 起點選擇對顯著性結論的敏感度低」，不能包裝成「五次獨立驗證全部通過」。paper wording 必須用：「stable across 5 alternative OOS starts (sensitivity grid, not independent replication)」。

**第三，>=80% PASS gate 是 internal submission 門檻，不是 econometric evidence 本身。** 5/5 通過是充分條件，但「設定 80% gate」的合理性本身若被 reviewer 追問，需要有文獻依據或另作說明。

## Paper 3 投稿意涵

在目前 HLN-retrofitted `paper3_E2_results.json` 中，10 對跨市場配對裡有兩對達 Harvey-Leybourne-Newbold 門檻：`TW0050-N225` 與 `TW0050-HSI`。其中 `TW0050-N225` 仍是最強的一對（Paper3_E2 baseline t_HLN=3.923；K1412/K1416 sensitivity baseline t_HLN=3.892；critical 約 1.96），因此它是最需要排除 single-start type-I 的案例。

K1416 確認這個主張在五個不同 OOS 起點下維持，排除了「特定窗口的偶然產物」這個最直接的批評。這可以強化 Paper 3 對 `TW0050-N225` 的局部主張，但不能擴張成「跨市場 copula 模型普遍優越」。

更精確的邊界是：current HLN 結果裡只有 2/10 跨市場配對達門檻，而 K1416 只驗證 `TW0050-N225` 這一對的 OOS-start 穩健性。這個局部穩健性可以視為穩健成立；投稿時的 contribution claim 應維持在「strongest pair robust to OOS-start choice」，不能回到舊的 unique-pair framing。

## 尚待解決的問題

K1416 是驗證型實驗，不是研究終點。幾個問題仍開著：

- paper3_E2.dm_test 能否輸出 per-OOS 精確 n，讓 K1416 升級為 full rerun？
- K1412 的 metadata 若能更新，K1416 是否仍有必要作為獨立實驗存在，或可直接整併？
- 其他 8 對未達 Harvey 門檻的跨市場配對，以及較弱但達門檻的 `TW0050-HSI`，在 paper 敘述裡如何定位？它們是「模型大多數情境沒幫助」的反面證據，還是「亞洲 intraregional pair 特殊性」的對照組？

---

*數據來源：K1416 實驗（K1416/k1416_results.json）、Paper3_E2 baseline（paper3_E2_results.json）、Harvey/Leybourne/Newbold (1997) IJF 13(2) 281-291；Codex review 2026-06-18，verdict=CONDITIONAL_PASS_AFTER_CORRECTION。*
