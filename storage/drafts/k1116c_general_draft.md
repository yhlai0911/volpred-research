---
title: 我們把同一份資料的時序對齊改了 6 次：EPU、NFCI 還是贏不了 VIX
audience: general
phase: research
category: milestone
status: draft
tags: [一般讀者, alt-data, EPU, NFCI, VIX, robustness, Paper4]
experiment_refs: [K1116c, K1116, K1116b, K1116f]
proposer: Claude
image_url: https://qxhfgdfzazwpkdgesavm.supabase.co/storage/v1/object/public/article-images/k1116c_variant_spec_dm_bars.png
---

# 我們把同一份資料的時序對齊改了 6 次：EPU、NFCI 還是贏不了 VIX

## 一段話摘要

過去這幾年，每次有讀者問「政策不確定指數（EPU）、芝加哥 Fed 金融壓力指數（NFCI）這些經濟指標對預測股市波動率到底有沒有用？」，我們的研究多半得到一個冷淡的答案：沒有。但每次給出這個答案，總會有人懷疑：「會不會是你們資料時序對得不夠細？實盤上的市場參與者用的是當天剛公布的版本，不是事後修正過的數字。」K1116c 就是把這個質疑做到底——同一份 SPY 週頻資料、6 種不同的時序對齊方式、3 種包裝了不同另類指標的模型，全部跑一遍 Diebold-Mariano 統計檢定（用來比較兩個預測模型誰更準的標準工具）。結果：18 個比較格子裡，沒有任何一格能讓另類資料贏過單純用 VIX 當輸入的基準模型。連最嚴格、模擬真實發布行事曆（point-in-time）的對齊版本也輸。一個 null result（無顯著效果的結論）能撐過 6 種時序設定，比一個只在單一設定下勝出的 positive result 更有說服力。

## 為什麼這篇值得讀完

VolPred 平台寫過好幾篇「另類資料對波動率預測沒幫助」的文章了。如果只是再重複一次「我們又跑了一次、結果還是 NULL」，老實說沒什麼新東西。這篇不一樣的地方是它把「研究怎麼證明自己沒做錯」這件事攤出來給讀者看。研究圈裡有一個常被忽略的真相：證明「A 比 B 好」可能只要找對一組資料、一個模型、一個時間窗就行；但要證明「A 比 B **沒有**比較好」，你必須在多種設定下都重現同一個結果，否則永遠有人能說「啊，你只是參數選錯了」。K1116c 做的就是後者。

順便對照同期完成的 K1116F：把同一套 PIT（point-in-time）對齊方式套到 GLD、TLT、BTC 這三個跨資產上面，結果只有 **TLT 配上金融壓力指數**那一格出現邊際勝出（DM t 值勉強跨過 3.0 的顯著門檻），其他全部還是 NULL。一個 marginal positive vs 18 個 robust null，後者是哪個比較可信？這篇文章的核心就是回答這個問題。

## 真實場景：為什麼「時序對齊」會變成致命爭議

想像你是某基金的量化研究員，2024 年某個週五上午要做下週 SPY 波動率預測。你手邊有三種資訊：

1. **VIX 指數**：每分鐘都在更新的市場恐慌指標，無時序問題。
2. **EPU 指數**：每天晚上 Baker–Bloom–Davis 從報紙文本爬出來的數字，T+1 工作日凌晨發布。
3. **NFCI 指數**：芝加哥 Fed 每週三早上 10:30 中部時間公布的金融壓力指數，內容是「上週五觀察到的金融狀況」。

如果你 2026 年才回頭做研究，去 FRED 資料庫抓 NFCI 歷史值，FRED 給你的是**修正後的版本**——也就是「我們現在認為當年那週應該長這樣」的回顧值。但 2024 年那個週五的你，手上不是這個版本——你只能看到「上週三公布的、針對更上週五觀察的數字」。如果寫程式時不小心讓模型「偷看」到還沒公布的資訊，回測就會虛胖：在過去看起來預測得很準，實盤一上線就崩。

學術上這叫 **lookahead bias**，是回測最大的單一風險來源。也是我們研究流程裡的最高優先警示項。

K1116c 把這件事做了 6 次。

## 6 種時序對齊的差別到底是什麼

| 對齊版本 | 描述 | 對應現實 |
|---|---|---|
| 原版 shift(1) | 把上週的數字當這週的輸入 | 假設資料當週能拿到（其實不行） |
| 修正 shift(2) | 把兩週前的數字當這週輸入 | 補正一週的發布延遲 |
| 保守 shift(2) | 連 EPU 都退兩週 | 給所有指標統一寬鬆假設 |
| **PIT shift(0)** | **依每個指標真實發布日對齊** | **最接近實盤的版本** |
| PIT shift(1) | PIT 之後再退一週 | 額外安全 margin |
| 極保守 shift(3) | 全部退三週 | 極端壓力測試 |

這裡的 PIT（point-in-time）就是學術圈所謂「真實發布行事曆」對齊：在每個預測日 F，只允許用「發布日期早於或等於 F」的那一筆資料。對 NFCI 來說，每週五的 F 對應的合法 NFCI 值是「上上週五觀察、上週三公布」的那筆。對 EPU 來說就是「昨天那筆」。

如果另類資料裡真的藏著被原版 shift(1) 偷看延遲訊息掩蓋的有效訊號，PIT 版本就應該把它釋放出來。

它沒有。

## 真實結果：18 個格子全敗給 VIX

把 6 種對齊 × 3 種另類資料規格（純 EPU 模型、純 FinStress 模型、把 VIX + 全部另類塞一起的 kitchen-sink 模型）的 DM 統計量畫成一張圖：

![6 種時序對齊 × 3 種模型的 DM t-stat — 全部負值](https://qxhfgdfzazwpkdgesavm.supabase.co/storage/v1/object/public/article-images/k1116c_variant_spec_dm_bars.png)

幾個讀者該注意的點：

- Y 軸是 DM t-stat（量測兩個模型預測誰更準的統計強度）。**負值代表 VIX baseline 贏**。
- 紅色虛線是 Harvey (2016) 提出的 |t|=3 顯著門檻——學術上判定「贏」的最嚴格標準之一。
- 18 個 cell 沒有任何一個正值跨過 +3 那條紅線。事實上沒有任何一個正值，連跨過 0 線都沒做到。
- 最值得注意的是 FinStress 模型（橘色）：在 PIT shift(1) 與極保守 shift(3) 對齊下，t 值從 −3.0 變成 −3.66 甚至 −3.99。換句話說，**對齊改得越嚴格，VIX 反而贏得越漂亮**。

這跟「時序對齊修一修，alt-data 就會逆轉」的直覺完全相反。我們把對齊修嚴後，另類資料表現變得更差，不是更好。

## 對比 K1116F：cross-asset 有沒有例外？

那把同一套 PIT 框架套到其他資產呢？K1116F 做的就是這件事——同時拿 GLD（黃金）、TLT（長天期美債）、BTC（比特幣）三個資產跑一輪。

![SPY 6 種對齊全敗 vs 跨資產只有 TLT 邊際勝出](https://qxhfgdfzazwpkdgesavm.supabase.co/storage/v1/object/public/article-images/k1116c_vs_k1116f_contrast.png)

結果：

- GLD：另類資料還是輸給 ^GVZ（黃金的 VIX）。NULL。
- BTC：另類資料還是輸給 30 天滾動已實現波動率。NULL。
- TLT 配上金融壓力指數（FinStress 規格）：DM t 值勉強跨過 +3 邊緣。Marginal positive。

K1116F 的官方 verdict 文字是「ASSET_SPECIFIC — Only ['TLT'] show alt-data DM>3 under PIT; other assets remain NULL」。一個資產、一個規格、剛好跨過顯著門檻——而且是在「金融壓力指數預測長債波動率」這個經濟學上本來就最合理的組合上發生的。

## 一個 marginal positive vs 18 個 robust null，哪個更可信？

這就是這篇文章想留給讀者的硬議題。

如果你只在乎找出能用的 alpha 訊號，你會很興奮地把 TLT/FinStress 那一格寫進部位裡。但 K1116c 整批 18 格 robust NULL 的存在告訴你一件事：**另類資料在預測波動率這件事上，主流結論是「沒幫助」，TLT 那個 marginal positive 比較可能是 cherry-picking 6 種對齊×多個資產×多個模型裡剛好跨線的一格**。

多重比較問題（multiple testing）是這裡的關鍵。如果你跑了 100 個比較，純粹隨機你就會看到大約 5 個顯著（p<0.05）；跑了 6 種對齊 × 4 個資產 × 5 個模型，要找出一格「顯著」幾乎是必然的——不能因為它在你預期的方向上，就把它當成真的訊號。

Harvey (2016) 在 *Review of Financial Studies* 那篇有名的論文裡論證：考慮整個金融學界的多重檢驗背景，要主張一個發現是「真實的」，t 值應該大於 3 而不是傳統的 1.96。TLT/FinStress 那格在 K1116F 裡是 t≈3.6—僅剛跨過這個門檻一點點。同時，K1116c 的 18 個 NULL 全在 −2.2 到 −4.0 之間，也就是 VIX 贏的方向上**更強烈**。

## 投資人能從這篇文章帶走什麼

第一，遇到「我加了某某另類資料模型表現變好」的策略 pitch，先問：**這個結論在多少種設定下測過？只在原版時序對齊下成立，還是在 PIT、shift(2)、極保守 shift(3) 全都成立？**只在一種設定下漂亮的數字，等實盤上線就會收斂。

第二，**null result 在實務上等於省錢**。如果你把 EPU、NFCI、ANFCI、STLFSI 這幾個資料訂閱買下來，每年要付不小的費用。K1116c 告訴你：對 SPY 週頻波動率預測這件事，VIX 已經足夠了，這些訂閱對你沒有額外幫助。省下的訂閱費直接是你的 alpha。

第三，**對齊細節是 due diligence 的核心檢查項目**。買策略、看回測報告時，請主動問供應商：「你的 EPU 是用 publication date 還是 observation date 對齊的？跑 PIT 還是 shift(1)？」答不出來的，回測數字基本不可信。

## 我們仍未完成的部分

誠實寫研究的另一面，是說清楚自己沒做到的事。K1116c 有兩個重要限制讀者應該知道：

- **沒有真實的 vintage 資料**：理想上應該抓 ALFRED（FRED 的歷史快照資料庫）取得 2018-2026 每週「當時市場第一手看到的」first-release 值。但 ALFRED 端點被 Akamai bot 防護擋下，且實驗環境沒有 FRED API key。我們用的是 fredgraph（修正過的版本）加上發布行事曆對齊，理論上修正版資料是真實狀態的更平滑估計，**比 vintage 更乾淨**。所以「修正版 + PIT 都 NULL」可以推論「vintage + PIT 也會 NULL」，但不能反推。若有讀者能贊助 FRED API access，這個實驗值得重跑一次封口。
- **僅週頻、僅 SPY、樣本期只到 OOS 170 週**：日頻 K1121 已經跑過、結論一致 NULL；BTC 用的是 30 天滾動 RV 當 IV proxy 而非實際的選擇權隱含波動率（BTC 沒有官方 VIX）。

## 延伸閱讀（同主題已發布文章）

如果這篇引起你的興趣，平台上還有兩篇相關角度可以接著看：

- 「你追蹤的那個經濟指標，對你的投資可能根本沒用——我們做了 87 個組合測試結果全 NULL」（2026-04-15，一般讀者版）— 同主題首篇，從 K1116 原版實驗的廣度切入。
- 「Alt-data 在預測上失敗，那 allocation 上呢？K1121 給出同樣的答案 — Null」（2026-05-01，研究版）— 把問題從預測轉到資產配置，結論仍然 NULL。

K1116c 是這條研究線上「方法論上最後一道防線」的回應：把時序對齊調到極端嚴格仍 NULL，等於把「但你是不是時序錯了」這個反駁徹底封口。

---

*本文基於實驗 K1116c（腳本：`experiments/k1116c/k1116c.py`，結果：`experiments/k1116c/k1116c_results.json`），對照 K1116F（`experiments/k1116f/`）。數據來源：yfinance（SPY 週頻 RV）+ FRED fredgraph（USEPU / WLEMU / NFCI / ANFCI / STLFSI4）+ 各指標官方發布行事曆。期間：2018-01-12 至 2026-04-10，OOS 樣本 170 週。統計檢定：Diebold-Mariano with Harvey-Leybourne-Newbold (1997) 修正，h=1。顯著門檻：Harvey (2016) |t|=3。圖表程式：`storage/draft_charts/k1116c_general/make_charts.py`。*

*[提出: Claude]*
