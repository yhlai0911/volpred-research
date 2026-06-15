---
title: K189 修正版：跨資產注意力沒贏 EWMA，但 5/6 顯著勝 GJR
phase: research
audience: research
status: published
tags: ["K189", "波動率預測", "注意力機制", "跨資產", "EWMA", "GJR-GARCH", "QLIKE"]
kid: K189
description: "K189 依 Codex review 重跑後，跨資產注意力模型在 6 個 ETF 上仍沒有穩健打贏單資產 EWMA；但舊文「GJR 全勝」結論方向錯了，修正版結果顯示 attention 對 GJR 方向上 6/6 較好、5/6 通過 Bonferroni-12。"
---

# K189 修正版：跨資產注意力沒贏 EWMA，但 5/6 顯著勝 GJR

*2026-06-15 修訂：舊版本文把 DM 統計量的符號方向讀反，且數字表沿用 2026-06-11 corrected rerun 之前的結果。本文改用 `experiments/k189/k189_attention_vol_results.json` 重新整理。舊結論「GJR-GARCH 全勝注意力模型」撤回。*

## 摘要

K189 測試六個 ETF 的跨資產注意力加權波動率預測：SPY、QQQ、GLD、TLT、EEM、IWM。修正版採 yfinance 日資料，有效樣本外期間為 2023-01-03 到 2024-12-31，共 502 個交易日。所有 forecast 都使用 t-1 以前資訊，alpha 也在每個樣本外日期用前 500 個交易日 rolling ex-ante 選擇。

修正後的結論分成兩層。第一，attention 模型仍然沒有打贏最簡單的單資產 EWMA，6/6 資產 QLIKE 都小幅變差。第二，舊文說 attention 輸給 GJR-GARCH 是錯的；目前 JSON 顯示 attention 對 GJR 方向上 6/6 較好，其中 QQQ、GLD、TLT、EEM、IWM 的 DM 檢定在 Bonferroni-12 後仍達 5% 顯著水準。

## 方法與資料

| 項目 | 設定 |
|---|---|
| 資產 | SPY、QQQ、GLD、TLT、EEM、IWM |
| 資料來源 | yfinance daily close |
| 有效 OOS | 2023-01-03 到 2024-12-31 |
| OOS 樣本 | 502 個交易日 |
| 目標 proxy | 22 日 rolling realized variance，`returns.rolling(22).var() * 252` |
| EWMA | lambda = 0.94，forecast for t 只用 t-1 以前報酬 |
| Attention window | 252 日，權重估計不含 forecast date t |
| Alpha grid | {0.3, 0.5, 0.7, 0.9} |
| Alpha selection | 每個資產、每個 OOS 日期，用前 500 個交易日 ex-ante 選擇 |
| GJR benchmark | rolling GJR-GARCH(1,1)，500 日訓練窗，normal innovations |
| 檢定 | QLIKE pointwise loss + Newey-West DM，12 tests 做 Bonferroni 與 BH-FDR |

DM 的定義是 `loss_attention - loss_baseline`。QLIKE 愈低愈好，因此 DM t-stat 為正代表 attention 較差，為負代表 attention 較好。這一點是舊文錯讀的核心。

## 結果一：attention 沒有贏過單資產 EWMA

![K189 corrected QLIKE relative changes](experiments/k189/k189_corrected_loss_changes.png)

相對單資產 EWMA，attention 在六個資產全部變差：

| 資產 | EWMA QLIKE | Attention QLIKE | 相對 EWMA | DM t vs EWMA | Bonferroni-12 |
|---|---:|---:|---:|---:|---:|
| SPY | -3.1968 | -3.1864 | +0.33% | +4.34 | 0.00021 |
| QQQ | -2.5066 | -2.5059 | +0.03% | +1.22 | 1.00000 |
| GLD | -3.0071 | -2.9992 | +0.26% | +4.29 | 0.00026 |
| TLT | -2.6685 | -2.6665 | +0.07% | +2.01 | 0.54525 |
| EEM | -2.7708 | -2.7693 | +0.05% | +1.94 | 0.64252 |
| IWM | -2.2528 | -2.2519 | +0.04% | +1.00 | 1.00000 |

平均相對變化為 +0.1309%，方向很一致，但幅度很小。SPY 與 GLD 的劣化在多重比較校正後仍顯著；其他四個資產沒有足夠證據說差異穩定。這支持較保守的說法：在這個日頻 ETF 設定下，跨資產 attention 沒有提供可依賴的 EWMA 增量。

## 結果二：GJR-GARCH 不是這輪的贏家

舊文最大錯誤在這裡。修正版結果顯示，attention 對 GJR-GARCH 方向上 6/6 較好，且 5/6 通過 Bonferroni-12：

| 資產 | GJR QLIKE | Attention QLIKE | 相對 GJR | DM t vs GJR | Bonferroni-12 |
|---|---:|---:|---:|---:|---:|
| SPY | -3.1812 | -3.1864 | -0.16% | -0.93 | 1.00000 |
| QQQ | -2.4851 | -2.5059 | -0.84% | -6.73 | 0.00000 |
| GLD | -2.9250 | -2.9992 | -2.53% | -6.67 | 0.00000 |
| TLT | -2.6389 | -2.6665 | -1.05% | -5.19 | 0.00000 |
| EEM | -2.7381 | -2.7693 | -1.14% | -5.82 | 0.00000 |
| IWM | -2.2141 | -2.2519 | -1.71% | -5.66 | 0.00000 |

![K189 corrected DM sign](experiments/k189/k189_corrected_dm_tests.png)

這不代表 attention 很強。GJR 在這個設定下使用 500 日 rolling window 與 normal innovations，2023 到 2024 的六資產樣本裡表現弱於 EWMA。真正硬的 baseline 是單資產 EWMA，不是這版 GJR。

## Alpha selection：0.9 仍然被全部選中，但口徑要改

修正版不是先看完整 OOS 後挑 best alpha。程式對每個資產、每個 OOS 日期，都只用此前 500 個交易日計算四個 alpha 的 QLIKE，再選當天可用的 alpha。

結果仍然很極端：六個資產的 502 個 OOS 日期全部選到 0.9。解讀應該是「rolling ex-ante 選擇幾乎把跨資產成分壓到 10%」，不是「研究者事後知道整段 OOS 的最佳 alpha 是 0.9」。

這一點保留了舊文的一部分直覺：跨資產訊號沒有被模型大量採用。差別在於，現在的說法避免 OOS hindsight。

## 限制與穩健性

第一，QLIKE proxy 是 22 日 rolling realized variance，不是單日 `r_t^2`。這個 proxy 比單日平方報酬平滑，但相鄰觀測高度重疊，DM p-value 需要保守解讀。程式有 Newey-West 修正，但 `n^(1/3)` 的 lag 長度未必完全吸收 22 日 overlap。

第二，attention 權重是簡化規格：用 252 日 rolling RV correlation 做 softmax，沒有學習非線性特徵，也沒有使用 high-frequency RV、jump、co-jump 或 implied volatility surface。本文只能否定這個日頻 attention 規格相對 EWMA 的增量，不能否定所有跨資產資訊。

第三，GJR-GARCH 在本實驗不是強 benchmark。若換成 Student-t/GED innovations、不同 refit cadence，或與已知強模型如 HAR family 比較，排序可能改變。本文不應再寫「GJR 全勝」，也不應把「attention 勝 GJR」包裝成新模型成功。

## 結論

K189 修正版給出的正確訊息比較細：跨資產 attention 沒有贏過單資產 EWMA，六個資產全部小幅變差；但它也沒有輸給這版 GJR-GARCH，反而在 5/6 資產上顯著勝出。

所以本文的投資與研究含義是：在 2023 到 2024 的日頻 ETF 波動率預測裡，資產自己的 EWMA 仍是最難打的基準。跨資產 attention 可以打贏一個表現較弱的 GJR 設定，但無法證明跨資產訊號帶來穩健增量。下一步若要繼續測，應該把比較對手升級到 HAR / GJR-GED / high-frequency RV，並把 22 日 overlap 的推論風險納入正式檢定設計。

---

*本文基於實驗 K189（腳本：`experiments/k189/k189_attention_vol.py`，結果：`experiments/k189/k189_attention_vol_results.json`，繪圖：`experiments/k189/plot_qlike_comparison.py`）。資料來源：yfinance daily close，資產為 SPY、QQQ、GLD、TLT、EEM、IWM，effective OOS 為 2023-01-03 至 2024-12-31，樣本數 502。本文為 2026-06-15 Codex review 後的 in-place correction。*
