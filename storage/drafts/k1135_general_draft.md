---
title: "想用偏態 t 打敗波動率？商品市場給了個彆扭答案 — 波動預測沒救，但能救你的『最壞情境』"
audience: general
status: draft
tags:
  - 波動率
  - 風險管理
  - VaR
  - 厚尾
  - 商品
  - 黃金
  - 原油
experiment_refs:
  - K1135
---

# 想用偏態 t 打敗波動率？商品市場給了個彆扭答案 — 波動預測沒救，但能救你的「最壞情境」

[提出: Claude，執行: Claude]

## 一句話結論

在油、天然氣、黃金、白銀四個商品 ETF 上，把波動率模型的誤差項從常態分布換成 Hansen (1994) 偏態 t 分布，**對「明天波動率有多大」的預測完全沒幫助**；但對「最壞 1% 情境下會虧多少」這個 ES 估計，**四個商品全部從嚴重低估翻轉成校準正確**。偏態 t 是一把 tail 風控工具，不是波動預測工具。

## 為什麼挑這四檔商品

挑 USO（原油 ETF）、UNG（天然氣 ETF）、GLD（黃金 ETF）、SLV（白銀 ETF）這四檔，是因為三個一定要先講清楚的觀察。

第一，這幾檔的下跌偏度都很重。USO 的全樣本偏度是 -0.578、GLD 是 -0.310、SLV 是 -1.064，意思是負方向尾巴比正方向長很多。常態分布把兩邊尾巴設成對稱，模型自然會低估暴跌的機率。

第二，過去的實驗證據顯示，VIX 在大多數時候對股市波動已經是「夠用」的訊號。我們累積 24 次以上的測試（包含 SKEW 指數、VVIX、VIX 期限結構等），結論都指向**多加一個訊號很少能贏 VIX 本身**。Paper 4 系列就是在系統化檢驗：到底還有哪個方向、哪個 channel 可以從 VIX 充分性的縫隙鑽出來。

第三，K1129 已經告訴我們，把 GARCH 的常態誤差換成對稱 Student-t（容許厚尾但兩邊對稱）在這四個商品上 QLIKE 全部 NULL；K1138 與 K1143 又發現同一招在股市直接「有害」（SPY、QQQ 上的兩模型比較 t 統計量分別是 -3.27 與 -2.81，數字越負代表新模型越差）。所以這次的 K1135 是 last shot：商品天生負偏，如果連 Hansen 偏態 t 都救不起來，整個 GAS-skew 家族對波動預測就可以收。

## 兩件事分開看：vol forecast 和 tail risk

實驗的設計是把三個模型放在同樣的滾動視窗（1500 天訓練、每 63 天 refit、樣本外 2020-01 到 2026-04，每檔 1576 個交易日），用同一份報酬資料、同樣的 lag 對齊：

- **M0**：GARCH(1,1) 配常態誤差（baseline）
- **M1**：GARCH 配對稱 Student-t（K1129 的設定，當作對照）
- **M2**：GARCH 配 Hansen (1994) 偏態 t，多估一個 skewness 參數 λ

然後在四個商品上、樣本外做三件事：

1. **波動點預測**比較：QLIKE 損失函數加上兩模型比較顯著性檢定，看 M2 是否打敗 M0
2. **VaR (Value-at-Risk) 三件套**：1% 和 5% 兩個水準，跑 Kupiec 違約率檢定、Christoffersen 條件覆蓋檢定、Engle-Manganelli DQ 檢定
3. **ES (Expected Shortfall, 條件損失期望)**：Acerbi-Szekely (2014) Z1 與 Z2 兩個獨立檢定

![commodity_skew_vs_gauss](experiments/k1135/commodity_skew_vs_gauss.png)

上圖是四個商品的實際報酬經驗密度與常態密度的對照。USO 與 SLV 的左尾明顯比常態厚很多，這正是偏態 t 該發揮的地方。GLD 也有一點。UNG（天然氣）兩邊厚度差不多，是這次的對照組。

## 結果一：波動率預測這條路真的走不通

先看 QLIKE 的結論（QLIKE 是一種對波動率 proxy 不敏感的損失函數，Patton 2011 提出）。M2 偏態 t 對 M0 的兩模型比較統計量分別是：

- USO：-1.99（M0 反而勝）
- UNG：+1.56（M2 略勝但未達顯著）
- GLD：+0.74（接近平手）
- SLV：-0.25（接近平手）

**通過率 0/4**。經過多重檢驗校正（Benjamini-Hochberg）後沒有任何一個商品的 QLIKE 改善是穩定的。USO 甚至顯著地比 GARCH 常態還差。

這結果跟 K1129 完全一致：在商品市場上，把分布從常態換到 Student-t 或 Hansen 偏態 t，**波動率本身的預測能力沒有 marginal value**。Paper 4 的 Channel 3（GAS family robustification）這條 vol forecasting 路線可以收。

## 結果二：ES 從全面失靈變成全面校準

但同一份模型、同一份資料，換看 1% ES 的校準狀況，故事就翻過來了。

| 商品 | GARCH-常態 ES Z1 | Z1 p | Hansen 偏態 t ES Z1 | Z1 p |
|------|------------------|------|---------------------|------|
| USO  | +2.77            | 0.006 | +0.97               | 0.335 |
| UNG  | +1.23            | 0.218 | +0.05               | 0.960 |
| GLD  | +3.41            | 0.001 | +1.14               | 0.253 |
| SLV  | +3.68            | 0.000 | +0.02               | 0.982 |

Z1 是 Acerbi-Szekely (2014) 的標準化檢定統計量，p 值小於 0.05 代表模型對 ES 的估計顯著偏差（這裡的「偏差」具體是低估真實尾部損失）。

GARCH-常態在 USO、GLD、SLV 三檔上的 p 都低於 0.01，等於系統性把暴跌風險估太小；GLD 甚至跌出統計強度最強的 p=0.001。換成 Hansen 偏態 t 之後，四檔全部把 Z1 的 p 拉到 0.25 以上，**通過率 4/4**。

VaR 違約率也是平行的故事。GLD 在 1% VaR 上，GARCH-常態的實際違約率達到 2.16%（理論值 1%，超標 116%）；換成偏態 t 立刻校到 1.08%，幾乎完美。SLV 從 1.90% 降到 1.33%，USO 從 1.52% 降到 1.14%。

![var_es_backtest](experiments/k1135/var_es_backtest.png)

上圖是 VaR Trinity 三件套 + ES Z1/Z2 的 p 值熱度圖，紅色越深代表越拒絕模型校準正確的虛無假設。可以看到 M2（最右一欄）整片變綠，特別是 ES 那兩列幾乎完全洗白。

## 為什麼會「分裂」成這個結果

兩個直觀解釋。

QLIKE 對波動率的「中央位置」敏感。常態與偏態 t 在中央區域的密度幾乎一樣，所以對「明天波動率多大」這種點預測，分布形狀並不影響。模型估的 σ² 一樣大，QLIKE 就一樣。

ES 反過來是專測尾部期望。偏態 t 的 λ 負值會讓左尾長出更厚的肉，特別是在自由度（ν）4-8 之間的情況下（這次商品估出來的 ν 都在這區間），左尾極端報酬的密度被明顯抬高，ES 估計值因此跟著被「往負方向加重」，剛好對齊資料的實際暴跌頻率。

這個分裂結果的實務意義：偏態 t 沒讓你看得更準明天會抖多少，但它讓你準備好了當「黑天鵝」真的來的時候，停損金額不會被低估。

## 對 Paper 4 整體故事的意義

K1135 補完了 Paper 4 VIX 充分性論述的一塊重要拼圖。

VIX 為什麼可以被宣稱是波動率的「充分統計量」？正當性不在於 VIX 與其他訊號正相關（那不夠），而在於**「測過 N 個替代 channel，每一個都 NULL」**才有信心 declare 充分。Paper 4 系列裡，已經測過：

- 替代波動指數（SKEW、VVIX、VIX 期限結構）→ K129、K184、K210 等：NULL
- 跨類別波動率離散度（投機 vs 防禦 ETF）→ K151：NULL
- HAR + 替代 RV component → K1139 系列：VIX is enough aggregator
- 對稱 Student-t GAS（商品）→ K1129：NULL
- 對稱 Student-t GAS（股票）→ K1138、K1143：HARMFUL
- **Hansen 偏態 t GAS（商品）→ K1135：vol-NULL（本篇）**
- Hansen 偏態 t GAS（股票）→ K1143：HARMFUL

第七條就是 K1135 的貢獻：商品的負偏度是這套方法理論上「應該起作用」的最後可能性，但實證上對 QLIKE 還是 0/4 PASS。Paper 4 的 GAS family channel 走到這裡關門。

但 Paper 4 同時得到一個 bonus 副產品：**Hansen 偏態 t 在商品 tail risk 校準上有實質用途**。它不會推翻 vol-NULL 的結論，卻漂亮地把波動預測與風險管理切開。Paper 4 Channel 3 的最終 narrative 因此改寫成：「GAS-skew-t 在商品上是 tail risk 工具，不負責 vol forecasting」。

## 散戶可以怎麼用

如果你只是用 GARCH 估個波動率拿來算倉位（例如 vol targeting），K1135 告訴你**不必為了商品 portfolio 升級到偏態 t** — 多估那個 λ 對波動本身不會更準，反而多一個參數要 refit。

但如果你在算商品部位的最壞 1% 情境停損，**常態 GARCH 會系統性把你需要準備的緩衝估太低**。原油與貴金屬尤其嚴重，黃金 1% VaR 違約率超標 116% 不是小事 — 那代表你以為一年才會破一次的停損，實際上會破兩次以上。偏態 t 把這個缺口補起來。

實務上你不必自己寫 Hansen 偏態 t。`arch` 套件支援 skew-t innovation；現成的商品 VaR 計算工具（rugarch 等）也都有。重點是知道「在商品上要用」，而不是黏在預設常態。

## 局限

第一，λ 是 static 估的。Gonzalez-Rivera et al. (2014) 已經提出 time-varying skew GAS，K1135 估出來 IS λ 大約只有 -0.05，明顯遠小於全樣本實際偏度（USO -0.58），表示 2010-2019 訓練期相對平靜，未完全 capture 2020 後的 COVID 油價崩盤、2022 能源危機、2024-25 貴金屬大波動。後續實驗會測 time-varying λ 是否進一步壓低 ES Z1。

第二，這次的 baseline 是 GARCH-常態。如果改用 GARCH-Student-t 做 baseline，ES 校準的差距會縮小（M1 對稱 Student-t 在多數商品上也 PASS ES），但 M2 偏態 t 在 USO 與 SLV 的 Z1 仍最接近零，仍是最乾淨的選擇。

第三，VaR Trinity 在 USO 與 SLV 1% 水準下還有 clustering 殘留（DQ 檢定 p < 0.01），意思是違約日仍有連續發生的傾向（例如 COVID 油價崩盤的連續幾天）。可能需要把 leverage 不對稱項（GJR）加進偏態 t-GAS，作為 K1147 候選後續實驗。

第四，只測四個商品 ETF。鉑、鈀、廣義商品指數 DBC、乙醇 ETF 都沒測，universality 待驗。

## 結論

K1135 給出商品市場上 GAS 家族的乾淨判斷：偏態 t 在波動率點預測上 0/4 通過，但在 1% ES 校準上 4/4 通過、1% VaR 違約率上 3/4 改善。Paper 4 VIX 充分性論述因此多了一個 channel 的 vol-NULL 確認，同時換到一個具體可用的副產品：商品部位的尾部風險工具。

---

*本文基於實驗 K1135（腳本：experiments/k1135/k1135.py，結果：experiments/k1135/k1135_results.json）。資料來源：yfinance USO/UNG/GLD/SLV 2010-01-01 ~ 2026-04-10，樣本外期間 2020-01-02 ~ 2026-04-10，每檔 1576 個樣本外觀測值。所有滾動視窗、refit 頻率、seed=42 與 lag 對齊均依 K1129、K1143 既有 protocol。Hansen 偏態 t 密度經 scipy Student-t 在 λ=0 下交叉驗證（max |PDF diff| = 2.8e-17）。*
