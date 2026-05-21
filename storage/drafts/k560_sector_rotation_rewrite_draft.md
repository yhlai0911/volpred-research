# 用 VIX 做類股輪動，真的能幫投資組合加分嗎？21 年回測誠實答案

## 一句話結論

**不能。** 在 21 年、5,310 個交易日、9 個 SPDR 類股 ETF + GLD 的完整回測裡，**所有**用 VIX-VT 做類股輪動的策略 Sharpe 全部落在 **0.73 ~ 0.94** 之間，沒有任何一個贏過簡單的「SPY-VT + GLD」基準（Sharpe 0.944），也**沒有任何一個通過 Harvey (2016) 嚴謹門檻**（要求 |t| > 3.0）。更殘酷的是，這篇文章本來在 2026-05-05 以「Sharpe 2.16 momentum_top1」的版本發過 draft —— 那組亮眼數字，是程式裡一行 lookahead bug 的產物。我們在 2026-05-06 修補，重新跑出真實答案，並把舊版本撤回改寫成你現在讀到的這一版。

## 為什麼要重寫這篇

這個系統的最高原則是「研究誠實」：所有發出去的數字必須能 byte-for-byte 對應到實驗檔，數字錯了就要更正、要說明、要把根因寫進錯誤庫。

K560 這個實驗的第一版（2026-04 跑完）給了一組驚人結果：用 60 日動能挑類股、套上 12/VIX 的 volatility targeting 倉位、加 50% GLD 的避險腳，**momentum_top1 跑出 Sharpe 2.16，relative_strength 跑出 1.876**。當時的文章用「誠實答案」當標題，意思是「我們檢驗過了，VIX 類股輪動真的有用」。

但在 K547 lookahead 稽核家族（K547、K562、K560 sibling chain）的 audit 中，我們在 K560 的主迴圈裡找到一行同樣的時序錯位：訊號用了 day-t 收盤後才知道的資訊，卻被套用到 day-t 全天的權重 × day-t 報酬。這就是教科書級的 lookahead bias。

修補補丁參考 `experiments/k560/k560_sector_rotation_vt.py` 的 L249-L262：把 `vt_w = vt_weights[i]` 改成 `vt_w = vt_weights[sig_idx]`，其中 `sig_idx = i - 1`。同 patch 也套用到 `sec_moms / sec_vols / sec_rs`。這個一行字的差異，把所有亮眼結果歸零。

## 實驗設定

- **實驗編號**：K560（"Sector Rotation with VT — Can Rotating Between Sectors Improve Upon SPY VT?"）
- **資料源**：yfinance
- **樣本期**：2005-03-30 → 2026-05-06，共 5,310 個交易日（約 21 年）
- **資產**：SPY、9 個 SPDR sector ETFs（XLK / XLF / XLV / XLE / XLI / XLY / XLP / XLU / XLB）、GLD（避險腳）、^VIX（VT 倉位用）
- **組合結構**：50% 「類股 ETF × VT 倉位」 + 50% GLD（每日再平衡）
- **VT 公式**：`12 / VIX`，clip 在 [0, 1] 之間
- **基準**：SPY-VT + GLD（同樣 50/50 結構）+ SPY 買進持有 + GLD 50/50
- **檢驗**：Diebold-Mariano + Newey-West，Harvey (2016) 門檻 |t| > 3.0；3 個獨立 OOS 子期間 cross-validation
- **交易成本**：5 bps 單邊

測試的 7 個輪動訊號：

| 訊號 | 規則 |
|------|------|
| momentum_top1 | 60 日累積報酬最高的類股，全部押注 |
| lowvol_top1 | 22 日波動最低的類股 |
| mean_reversion_top1 | 60 日累積報酬最低的類股（反轉） |
| relative_strength | 表現勝過 SPY 的類股等權重平均 |
| momentum_top3 | 動能前三名等權重 |
| mom_lowvol_combo | 動能前三再選波動最低的 |
| equal_weight_all_sectors | 9 類股等權重（無輪動的對照組） |

## 舊版本的問題：那個 Sharpe 2.16 哪來的

舊版 errata 記載了當時的數字：momentum_top1 Sharpe = 2.16、relative_strength Sharpe = 1.876。直觀上這非常吸引人 —— 一個簡單的「最強動能 × VIX-VT × 50% GLD」組合，在 21 年裡跑出機構級的風險調整後報酬？

但那是 lookahead 的功勞。同一個 K547-family 補丁套用到姊妹實驗 K562（單獨上架候選的 sector momentum VT）時，Sharpe 也從 **2.16 崩到 0.72**。當兩個獨立寫的策略都在同一個補丁下崩潰一樣的幅度，就不是巧合，是同一個訊號 leak 模式。

這次發現帶出兩條原則性教訓，之後我們把它們寫進規則庫：

1. **「漂亮到不像真的」 = 90% 有 bug**。Sharpe > 1.5 的策略要先當作可疑，不是先當作發現。
2. **K547 lookahead 家族**：任何用「天頻訊號 + 同檔資產報酬」的回測，必須能在程式碼裡指出明確的 `signal.shift(1)` 或等效 lag；不能就算錯到底。

## Patch 後的真實數字

### 全期間風險調整後報酬（5,310 天）

| 策略 | 年化報酬 | 年化波動 | Sharpe | 最大回撤 | DM 比較 SPY-VT 的 t-stat |
|------|----------|----------|--------|----------|--------------------------|
| **基準 SPY-VT + GLD** | **9.93%** | **10.52%** | **0.944** | **-21.0%** | — |
| 基準 SPY 買進持有 + GLD | 12.52% | 13.57% | 0.922 | -32.5% | — |
| equal_weight_all_sectors | 9.83% | 10.41% | 0.944 | -20.3% | -0.37 |
| mean_reversion_top1 | 11.04% | 11.82% | 0.934 | -25.5% | +0.98 |
| relative_strength | 9.69% | 10.60% | 0.914 | -20.3% | -0.49 |
| momentum_top3 | 9.62% | 10.65% | 0.903 | -21.1% | -0.55 |
| mom_lowvol_combo | 9.40% | 10.49% | 0.897 | -20.4% | -0.67 |
| lowvol_top1 | 9.11% | 10.20% | 0.894 | -19.9% | -1.01 |
| momentum_top1 | 8.61% | 11.74% | **0.734** | -21.9% | -1.21 |

注意三件事：

1. **沒有任何輪動策略 Sharpe 高於基準的 0.944**。當年那個「Sharpe 2.16」的 momentum_top1 ，patch 後實際是 0.734 —— 還是七個策略裡**最差的**。
2. **沒有任何 DM t-stat 大於 Harvey 門檻 |t| > 3.0**。所有 t-stat 落在 [-1.21, +0.98] 區間，p-value 全部 > 0.22。意思是：上面表格裡 mean_reversion 比基準高出來那點點，**統計上完全分不出來是運氣還是訊號**。
3. **5 bps 交易成本後**，momentum_top1 Sharpe 進一步掉到 0.580、lowvol_top1 掉到 0.752、momentum_top3 掉到 0.801；只有 relative_strength 跟 equal_weight_all_sectors 勉強守住基準（因為他們 turnover 低）。

![K560 patch 前後 Sharpe 對照](experiments/k560/figures/k560_pre_post_sharpe.png)

### 跨 OOS 子期間：3 個獨立窗口都站不住

我們把樣本切成三段獨立 OOS：2013-2016（量化寬鬆中後段）、2018-2021（疫情前後）、2022-2026（升息循環 + AI 行情）。

| 策略 | OOS-1 (2013-2016) | OOS-2 (2018-2021) | OOS-3 (2022-2026) |
|------|-------------------|-------------------|-------------------|
| 基準 SPY-VT + GLD | 0.019 | 1.087 | 1.311 |
| momentum_top1 | 0.210 | 0.409 | 1.287 |
| lowvol_top1 | -0.215 | 1.121 | 1.219 |
| mean_reversion_top1 | -0.164 | 1.115 | 1.516 |
| relative_strength | 0.017 | 0.943 | 1.296 |
| momentum_top3 | -0.007 | 0.936 | 1.364 |
| mom_lowvol_combo | -0.236 | 1.074 | 1.211 |
| equal_weight_all_sectors | 0.004 | 1.033 | 1.354 |

**沒有任何一個輪動策略在 3 個窗口都贏基準** —— 這是 OOS-consistent 的硬定義，K560 整批策略全部不滿足。OOS-1 連基準自己都只有 0.019（QE 中後段純 buy-and-hold 不太能贏 VT），輪動策略隨機散在 -0.24 到 +0.21 之間，沒有方向性。

![K560 patch 後 OOS Sharpe](experiments/k560/figures/k560_post_patch_oos_sharpe.png)

## Lookahead 是怎麼一行字偷渡的

下面這張圖比兩百字解釋更清楚：

![K560 lookahead patch 示意圖](experiments/k560/figures/k560_lookahead_illustration.png)

**Patch 前**：迴圈第 `i` 天時，程式抓 `vt_weights[i]` 與 `mom_arrays[ticker][i]` 來算當天權重，但這些值是用「day-t 全天資料」算出來的。等於用 day-t 收盤才知道的東西，倒回去決定 day-t 早上的部位 —— 你今天早上沒開盤就「先知道」今天 VIX 收在哪、哪個類股最強。

**Patch 後**：強制 `sig_idx = i - 1`，所有訊號退一天。day-t 的權重用 day t-1 收盤算出來的訊號，再去乘 day-t 的當日報酬。這才是合法的回測時序。

這個 patch 的 4 行 diff 在 `experiments/k560/k560_sector_rotation_vt.py` 的 L249-L262。同 patch 已經套到 K547、K562 全家族。

## 教訓：研究誠實的具體成本

把舊版「Sharpe 2.16」的文章改寫成「全部 0.7-0.9、Harvey 全 fail」的版本，對平台短期是「壞消息」—— 我們撤回了一個聽起來很有說服力的 strategy。但這正是研究誠實原則最具體的展現：

1. **數字錯了就改數字、改文章、改結論**。不能因為「文章已經發了」就硬凹。
2. **Lookahead 是 backtest 最高優先風險**。任何看起來太好的策略，先懷疑時序，再懷疑模型。
3. **跨 K 共用同一 lookahead 模式**就是系統性風險。K547 audit 攔下 K562 之後，必須回頭掃 K560、K866 等家族成員 —— 結果 K560 一樣中招。
4. **配套的事後復盤** mile_91af7c48「從 Sharpe 2.16 到輸基準：一場 lookahead 的攔截實錄」記錄了同類問題在 K562 的攔截過程，可一起讀。

## 投資建議

**用 VIX 做類股輪動，目前在 K560 的設定下不是可行策略。** 7 種訊號（動能、低波、反轉、相對強弱、三檔組合）在 21 年資料、3 個 OOS 窗口、Harvey + DM 雙重檢驗下全部 fail。如果你想要一個 VIX 相關的可實作組合，目前較可信的路徑仍是：

- **單純 VT 在 SPY** 上加 GLD 50/50（基準 Sharpe 0.944、MDD -21%、這是這篇研究的勝者）
- 或是固定 9 類股等權重（Sharpe 0.944、MDD -20.3%，跟 SPY-VT 平手）

**不要**用「最強動能類股 + VIX-VT」這種 narrative 漂亮的組合 —— patch 後它是七個策略裡最差的那個。

## 參考資料

- 主實驗檔：`experiments/k560/k560_sector_rotation_vt.py`、`k560_sector_rotation_vt_results.json`
- Lookahead patch 對照：`experiments/k560/k560_sector_rotation_vt.py` L249-L262（K547-family）
- 同類事後復盤：mile_91af7c48「從 Sharpe 2.16 到輸基準：一場 lookahead 的攔截實錄」
- Harvey, C. R., Liu, Y., Zhu, H. (2016). "...and the Cross-Section of Expected Returns." *RFS* 29(1).
- Moreira, A., Muir, T. (2017). "Volatility-Managed Portfolios." *Journal of Finance* 72(4).
- Moskowitz, T., Ooi, Y. H., Pedersen, L. H. (2012). "Time Series Momentum." *JFE* 104(2).
