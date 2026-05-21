---
title: 資訊熵能不能提升波動率預測？K478 給的答案是：不行
audience: general
status: draft
tags:
  - 資訊熵
  - 波動率預測
  - HAR
  - VIX
  - 研究誠實
  - null-result
experiment_refs:
  - K478
---

# 資訊熵能不能提升波動率預測？K478 給的答案是：不行

> 一個流行的學術想法：用「資訊熵」（Shannon、Sample、Permutation entropy）抓住價格序列的複雜度，藉以提升波動率預測。我們在 SPY 上做了 21 年資料、3 年樣本外的乾淨檢驗，得出的結論很乾脆：**資訊熵在樣本外沒贏過 HAR baseline，VIX 仍是最強的單一變數**。這篇文章誠實記錄這個 null result，並說明它為什麼比一篇「成功」的文章更有價值。

[提出: 賴奕豪, 執行: Claude]

## 一個常被論文宣稱的命題

近 20 年常有論文宣稱：股價序列的「資訊熵」可以抓到傳統二階動差（變異數、自相關）抓不到的訊息。

直覺很合理：

- **Shannon entropy** 衡量報酬分佈的不確定性
- **Sample entropy** 衡量序列的「不可預測度」
- **Permutation entropy** 把每個短窗口排序成 pattern，計算 pattern 出現頻率的均勻度

只要市場進入「複雜度高」的狀態，理論上波動率就應該升高；反過來，熵的訊號也許可以**提早**告訴我們波動率即將上升。

這聽起來很美。問題是：**樣本外**真的有用嗎？大量論文用 in-sample（訓練期內）回歸告訴你「熵的係數顯著」，但這不等於它能在未來資料上贏過簡單的基準模型。K478 就是要把這件事做乾淨。

## K478 的設計

我們用 **SPY**（S&P 500 ETF）2005-01 至 2025-12 共 21 年日資料，前 18 年（2005-01 至 2023-01）當訓練期，後 3 年（2023-01 至 2025-12）做**滾動樣本外**驗證。

對手是七個 OLS 線性模型：

| 模型 | 內容 |
|------|------|
| M1 baseline | HAR：用昨日 21 日已實現變異數預測今日 |
| M2 | M1 + Sample entropy lag |
| M3 | M1 + Permutation entropy lag |
| M4 | M1 + Shannon entropy lag |
| M5 | M1 + 三種 entropy 全加 |
| M6 | M1 + VIX lag |
| M7 | M1 + VIX + 三種 entropy |

所有變數都用 lag（昨天觀測到、今天才能用），避免 lookahead；估計用 expanding-window OLS，最小訓練窗 504 日。樣本外總共有 731 個交易日（M2/M5/M7 因為 Sample entropy 需要更長窗口計算，可比樣本縮為 159 日）。

## 核心結果一：HAR baseline 沒被熵打敗

![K478 樣本外 QLIKE 比較長條圖：HAR baseline 與三個 entropy 變體幾乎打平，VIX 才明顯較低](https://github.com/yhlai0911/volpred-research/raw/main/experiments/k478/k478_qlike_comparison.png)

這張圖把四個樣本數可比的模型放在一起。**QLIKE 越低代表預測越準**：

- **M1 HAR baseline**：0.3357
- **M3 HAR + Permutation entropy**：0.3439（**比 baseline 高**，更差一點）
- **M4 HAR + Shannon entropy**：0.3370（與 baseline 幾乎打平）
- **M6 HAR + VIX**：0.2761（明顯改善，QLIKE 下降約 17.8%）

三種 entropy 加進去之後，最好的 case（Shannon）只跟 baseline 打平，**沒有任何一個變體贏過 baseline**。對照之下，把 VIX 加進去就立刻把 QLIKE 砍掉約六分之一——這就是為什麼這篇文章的副標說「VIX 仍是 OOS 最佳」。

## 核心結果二：兩模型比較給出顯著但反向的訊號

光看數字差距還不夠，我們進一步做兩模型逐期預測誤差的正式比較（Diebold-Mariano 框架），結果是：

![K478 兩模型比較顯著性圖：entropy 即便達顯著也是反向，VIX 才是正向勝出](https://github.com/yhlai0911/volpred-research/raw/main/experiments/k478/k478_dm_pvalues.png)

具體數字：

| 比較對象 | 比較顯著性 | 方向 | QLIKE 改善 |
|----------|-----------|------|------------|
| M3 Permutation entropy vs M1 | 達顯著水準（顯著性低於 0.0001） | **Baseline 勝** | -2.42%（更差）|
| M4 Shannon entropy vs M1 | 0.240（不顯著） | 與 baseline 無差異 | +0.38%（噪音級）|
| M6 VIX vs M1 | 達顯著水準（顯著性低於 0.0001） | **挑戰者勝** | +17.76%（明確改善）|

注意 M3 那一行：雖然顯著，但顯著的方向是「baseline 比挑戰者好」——也就是說，**加 Permutation entropy 不只是沒幫忙，而是「顯著地讓模型變差」**。

## 核心結果三：Granger 因果檢驗也支持 null

![K478 Granger 因果檢驗結果：三種 entropy 對 RV 的因果訊號都很弱，僅 Permutation entropy 邊緣顯著](https://github.com/yhlai0911/volpred-research/raw/main/experiments/k478/k478_granger_summary.png)

Granger 檢驗問的是：「昨天的 entropy 能不能在統計上『預告』今天的已實現變異數？」三種 entropy 全部測下來：

- **Sample entropy**：F=0.43，顯著性 0.512（明顯不顯著）
- **Permutation entropy**：F=4.95，顯著性 0.026（邊緣，但係數極小、樣本外無效）
- **Shannon entropy**：F=0.98，顯著性 0.323（不顯著）

結合上面的樣本外結果，這幾乎就是教科書級的「樣本內看到一點點影子，但完全活不出樣本外」案例。

## 為什麼一個 null result 仍然是好結果

這篇文章的結論很容易被誤讀成「研究失敗」。但這恰好是研究誠實原則最重要的場景。

- **樣本內看似漂亮的結果常常活不出去**。M5（HAR + 三種 entropy）的 in-sample R² = 37.6%，比 baseline 的 27.3% 高出整整 10 個百分點，看起來很驚艷。但樣本外 QLIKE 卻直接爆炸到 419，比 baseline 差三個數量級。原因之一是 Sample entropy 的計算窗口導致樣本縮到 159 天，估計過擬合；另一個原因是 entropy 的真正訊號在「平靜期」很弱，模型把噪音當成訊號學進去。
- **VIX 的優勢是真的**。在這份檢驗裡，VIX 是唯一在樣本外把 QLIKE 顯著下壓的變數。這跟過去文獻一致，但這次是在 entropy 競爭下重新確認，不是「沒對手的勝出」。
- **複雜度本身不是訊號**。許多論文把 entropy 包裝成「市場複雜度指標」，但實際上波動率本身就是市場複雜度的最直接讀數。再用一個間接的、計算成本高的指標去抓同一件事，邊際資訊量在樣本外幾乎為零。

## 下一步可能的方向

K478 不是「entropy 永遠沒用」的判決。它只是說：**在 SPY 日資料、HAR baseline、線性 OLS 框架下，entropy 沒有 incremental 的樣本外預測能力**。

合理的下一步至少有三條：

1. **regime-conditional entropy**：在高 VIX 期間，entropy 的訊噪比會不會比較好？或許要先用 regime indicator 切割再看。
2. **跨資產 panel**：S&P 500 是世界上最被研究、最有效率的資產之一。在流動性較差的市場（個股、新興市場、加密貨幣），entropy 也許還有空間。
3. **非線性框架**：OLS 對 entropy 的訊號可能不公平。樹模型、神經網路或 quantile regression 可能抓到 OLS 抓不到的條件結構——但同時也要嚴格防止 overfitting。

這些方向會落到後續的 K-series 實驗。但在那之前，這個 null result 本身就是研究地圖上的一個座標：往這個方向走，先別期待 free lunch。

## 一句話總結

「資訊熵」是一個漂亮但容易被高估的概念。在 SPY 21 年、嚴格樣本外、控制 lookahead 的設計下，三種主流 entropy 變體全部沒贏 HAR baseline，而 VIX 把它們全打趴。

研究做得好不是只記錄勝利，誠實記錄每一個 null result，才是讓下一篇研究站在堅實地基上的方法。

---

**資料來源**：SPY 日資料 from yfinance；VIX 日資料 from yfinance；實驗代碼與結果見 `experiments/k478/`。
