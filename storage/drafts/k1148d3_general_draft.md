---
title: 「設計被否決」比「結果是 null」更冷峻 — 一個 paper subsection 連 hypothesis 都不成立的故事
audience: general
phase: research
category: milestone
tags: [研究方法, 台股, 多重檢定, 樣本量, 反面教材]
experiment_refs: [K1148_D3]
proposer: Claude
status: draft
image_url: "https://qxhfgdfzazwpkdgesavm.supabase.co/storage/v1/object/public/article-images/k1148d3_effect_size_4a5cca.png"
---

## 開場：研究最難堪的時刻不是「沒效」

寫論文寫到中後段，作者多半已經有一個故事原型在腦中。資料、模型、檢定，多半是去**支援**那個故事。所以一份實證研究最常見的失敗，是「結果沒效」 — 我們以為 X 會影響 Y，跑出來 t-stat 是 0.4，攤手認賠，找另一個變數試。

但我們最近這個 Paper 2 §5 的小節碰到的，是**比「沒效」更冷的一種失敗**：連「該怎麼說這個故事」這件事，**設計層面就被自己的資料推翻**。我們本來想寫的層級更高一點：要回答「在『哪一群股票』身上 X 才會影響 Y」這種**結構性命題**，而不是停在「X 影響 Y 多少」這種單一估計。這個小節的整個 hypothesis 是「heterogeneity（異質性）」 — 結果跑完，連『可以辨識出哪一群』這件事，資料都不允許我們講。

這個 K1148_D3 實驗的標題在我們內部叫做 **Option 3 REJECTED**。今天這篇文章就把這個 rejection 攤開來講，因為它示範了一個讀者通常看不到的研究面向：**設計被否決，比實證沒效更需要面對。**

## 背景：我們本來想寫什麼

Paper 2 §5 在處理一個技術細節：在台股 GJR-GARCH 波動率模型裡，加入「財報公告日當天的額外波動 (EAV, Earnings Announcement Variance)」這個變數，到底有沒有實質改善預測？

前一支實驗 K1148_D1 已經給出答案：29 檔台股裡，只有 **9 檔通過 OOS DM 檢定門檻**（樣本外比較的 t-stat ≤ -2，即 EAV 模型顯著優於 baseline），剩下 20 檔不顯著。31% 的 hit rate 對 paper main claim 來說太尷尬 — 既不能說「EAV 全面有效」，又不能說「EAV 全面無效」。

於是我們生了三個選項：

- **Option 1**：放棄 OOS、改靠 IS（樣本內）結果撐 main claim
- **Option 2**：誠實報告 9/29 是事實，但**不解釋**為什麼是這 9 檔
- **Option 3**：找出這 9 檔的**共同特徵**，把 §5 重寫成「EAV 是 firm-heterogeneous（取決於個股特性），不是 universal」

Option 3 在三個選項裡學術價值最高 — 因為它把一個尷尬的 31% 命中率，轉化成一個有結構的發現：「在 X 類型的台股上 EAV 有效，在 Y 類型上沒效，原因是 Z」。如果做得出來，這個小節會是 Paper 2 最有貢獻的部份之一。

K1148_D3 就是去檢驗 Option 3 到底**做不做得起來**。

## 設計：16 個特徵、6 個產業，看能不能切出 PASS 和 FAIL

我們從 yfinance 抓了這 29 檔台股的特徵，分成 5 大類：

- **規模類**：市值、2015-2019 平均日成交金額
- **波動類**：年化波動度、波動度的波動度（vol of vol）
- **報酬類**：年化報酬、最大回撤
- **GJR 參數類**：alpha（短期衝擊）、gamma（負向不對稱）、beta（持續性）、persistence
- **財報類**：每年公告次數、平均絕對 surprise、surprise 對稱性

外加產業分類（6 個產業）。

然後跑 PASS（9 檔）vs FAIL（20 檔）兩組對比：

- **數值特徵**：用 Welch t-test 與 Mann-Whitney U-test 兩種檢定
- **產業分類**：用 Fisher exact test
- **多重檢定校正**：所有 p-value 跑 Benjamini-Hochberg（BH）step-up，控制 FDR 在 10%
- **顯著性門檻**：BH 校正後 p < 0.1 **且** |Cohen's d| > 0.5（數值類）或 BH 校正後 Fisher p < 0.1（產業類）

樣本量 N=29 很小，所以門檻刻意設嚴。這是為了**防止我們自己騙自己** — 16 個特徵跑下去，光憑運氣就有 1-2 個會 raw p < 0.05。沒有 BH 校正就宣稱「找到了 heterogeneity」，是典型的多重檢定犯罪。

## 結果：最像有意義的特徵，BH 校正後 p=0.60

下面這張圖是 Top-5 特徵的效應量 |Cohen's d|（越大代表 PASS 跟 FAIL 兩組差越多）：

![K1148_D3 特徵效應量 Top 5](https://qxhfgdfzazwpkdgesavm.supabase.co/storage/v1/object/public/article-images/k1148d3_effect_size_4a5cca.png)

最顯眼的是「surprise_symmetry_ratio（財報 surprise 方向對稱性）」：

- PASS 組平均 0.475（surprise 比較系統性地偏一個方向：要嘛長期超預期、要嘛長期不及預期）
- FAIL 組平均 0.240（surprise 比較對稱：時好時壞）
- Cohen's d = 1.026（大效應）
- **原始 p = 0.037**（看起來很顯著）

但是套上 BH 校正，**adj p 跳到 0.60** — 完全不顯著。為什麼差這麼多？因為我們是在「16 個特徵裡挑最像有意義的那個」報告。16 個變數跑下去，純運氣有 1-2 個 raw p < 0.05 是預期內事件。BH 把這層偏差吃掉，結果就是 0.60 — 跟 0.50 的隨機 chance 沒差幾步。

剩下 Top-5 的 |d| 都在 0.3 上下，連單一變數的標準（d > 0.5）都過不了。

### 那產業層級呢？

下面這張圖是 PASS 跟 FAIL 兩組在 6 個產業的組成比例：

![K1148_D3 產業組成 PASS vs FAIL](https://qxhfgdfzazwpkdgesavm.supabase.co/storage/v1/object/public/article-images/k1148d3_sector_composition_d42af5.png)

唯一看起來有點 pattern 的是 Industrials（航運：2603 長榮、2615 萬海；鋼鐵：2002 中鋼）— PASS 組裡占 33%，FAIL 組裡只占 5%。Fisher exact 原始 p=0.076，校正後 p=0.46。

問題是樣本太薄：整個 29 檔裡只有 4 檔是 Industrials，3 檔在 PASS 組。3/4 看起來像 pattern，但任何只靠 4 個樣本的「產業效應」都不該被信。如果這 4 檔裡剛好 2603 因為運氣分到 FAIL 組，比例就變 2/4 — 完全不 pattern 了。

## 為什麼這算 Option 3 REJECTED，不是「再多跑一些就好」

到這裡有個誘惑：「N=29 太小，再加 100 檔台股就行了吧？」

實話：**不能**。理由有兩層：

第一層是樣本本身。K1148_D1 的 29 檔已經是「市值前 30 且有完整 2010-2019 財報 surprise 資料」的篩選結果。要再擴 100 檔，會碰到 2010-2015 段 surprise 資料缺漏、上市時間短於 OOS window 等問題 — 不是有多少股票就能抓多少。

第二層才是關鍵：**這個小節的學術主張本來就是「heterogeneity 可以被 firm characteristics 解釋」**。如果連 N=29 的探索都看不到一個 Cohen's d > 1 的真效應（surprise_symmetry 看起來有，校正後就沒了），這意味著「firm 特徵跟 EAV PASS / FAIL 的關係」**本來就不是強訊號**。再加樣本只會把已經邊緣的 effect size 推到統計上顯著，但**實務上的差距還是極小** — 用這種微弱訊號去支撐論文 main subsection 站不住。

換句話說：Option 3 不是「資料量不夠」失敗，是「設計層假設可能根本不成立」失敗。這兩種失敗的處置方式完全不同。前者該補資料；後者該換主張。

## 我們的選擇：往 Option 1 或 Option 2 退守

K1148_D3 的結論讓 Paper 2 §5 的可行路線收斂成兩條：

- **Option 1（IS-only evidence）**：靠 K1148_D1 的 in-sample pooled θ_EAV t_Hessian = 10.43（樣本內 EAV 係數非常顯著）和 K1145 的 31 檔 IS 證據撐 main claim，**明白地把 OOS panel DM 標成 inconclusive**。學術上誠實，但 main claim 弱化。
- **Option 2（OOS heterogeneity without characterization）**：直接報告「29 檔裡 9 檔 OOS 通過」這個實證事實，但**拒絕把它歸因於 firm 特徵**，理由就是 K1148_D3 已經查過、找不到穩健 differentiator。

兩個都比 Option 3 守 — 但都比硬寫一個站不住的「heterogeneity 故事」誠實。

並列補一個 footnote：K1148_D3 看到的 exploratory pattern（PASS 組 surprise 偏系統性方向、PASS 組 Industrials 略多）**可以放在 appendix**，但要明白標「未通過 multiple-comparison 校正、僅供 pattern 完整性參考」。這比把它升格成 main text claim 安全很多。

## 對讀者的三個 takeaway

第一，**「研究淘汰」是常態，不是失敗**。一個 paper 後期能淘汰一條可行路線（哪怕是看起來最 attractive 那條），意味著作者願意讓資料說話，而不是讓敘事說話。在金融實證裡，N 不大、特徵很多的小節，能不能撐起 narrative，BH 校正後說了算 — 不是「raw p 0.04 故事好聽」說了算。

第二，**設計層 rejection 是研究的進步，不是退步**。Option 3 被否決，等於替 Paper 2 主作者省下後續可能花在「為弱訊號編故事」的時間，也省下審稿人攻擊「為什麼 N=29 就敢宣稱 heterogeneity」的火力。提早死掉一個壞 subsection，整篇 paper 反而更穩。

第三，**多重檢定校正是研究的本分，不是 optional**。16 個變數隨便跑，總有一個 raw p < 0.05；6 個產業隨便檢，總有一個 raw Fisher p 接近顯著。BH 校正就是這個自我約束的工具。沒有這層約束，「探索性 finding」很容易被自己騙進 main claim，paper 一上 review 就被擊穿。

研究做久了會慢慢學會：**最有價值的實驗結果，常常是那個讓你「不能寫」的結果**。它替你擋掉了未來會反咬一口的論述。

---

*本文基於實驗 K1148_D3（腳本：experiments/k1148_d3/k1148_d3.py，結果：experiments/k1148_d3/k1148_d3_results.json）並對比 K1148_D1（mile_17f67ce8 已收錄）。數據來源：yfinance 個股資料 + K1148/K1148_D1 之台股 GJR-VIX²-EAV 模型，IS 期間 2010-2019，N=29 檔台股。*
