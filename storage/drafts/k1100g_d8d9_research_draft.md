---
title: "每五天還是每二十五天？一個參數差點讓整個實驗結論翻盤"
slug: refit-cadence-artifact-k1100g-d8-d9
audience: research
phase: methodology
tags:
  - 波動率預測
  - 研究誠實
  - 跳空訊號
  - N225
  - SPY
  - 模型設計
  - 研究方法
  - 預測模型
---

# 每五天還是每二十五天？一個參數差點讓整個實驗結論翻盤

K1100G 系列的第八批實驗（D8）在 2026 年 4 月跑完之後，N225 的核心統計量從 +2.31 掉到 -1.92，SPY 從 +0.66 掉到 -2.10。符號都反了。

如果就此打住，結論只有一個：「這個預測框架在 2020-2025 的樣本外期間表現退步，gap² 訊號的效果不如先前報告。」

但先前的 D7 批次也是同樣的數據、同樣的樣本期、同樣的模型。

差在哪？

---

## 一個沒被當作正式超參數的設定值

模型框架叫 PRG（τ×g kernel），用前一天的「開盤跳空平方」（gap²）作為預測當日日內波動率的額外訊號，以 DM-HLN 統計量（Harvey-Leybourne-Newbold 修正版）衡量預測改善。

樣本外預測的機制是這樣的：每跑一段時間，用最新的資料重新估計模型參數，然後繼續預測。「重新估計的頻率」在實驗設計裡叫 `refit_every`，單位是交易日。

D7 設的是 `refit_every = 5`，意思是每週重新估計一次。D8 改成 25，相當於每月才估計一次。

就這樣。沒有換模型，沒有換資料，沒有換評估方法。只是讓參數更新的間隔從一週拉長到一個月。

結果是 N225 的 DM 值從 +2.31 掉到 -1.92，SPY 從 +0.66 掉到 -2.10。

---

## 三批次對比

| 批次 | refit 頻率 | N225 DM（Student-t gap）| SPY DM（Student-t gap）|
|------|-----------|------------------------|------------------------|
| D7 | 每 5 天（每週）| **+2.31** | +0.66 |
| D8 | 每 25 天（每月）| **−1.92** | −2.10 |
| D9 | 每 5 天（恢復）| **+2.31** | +0.66 |

![K1100G D7/D8/D9 refit cadence 對 DM 統計量的影響](https://qxhfgdfzazwpkdgesavm.supabase.co/storage/v1/object/public/article-images/k1100g_cadence_dm_comparison.png)

D9 是診斷實驗，唯一的目的是把 D8 的 `refit_every` 改回 5，其他全部不動，看數字會不會還原。

還原了。精確到小數點第二位。

D9 的 N225 DM = 2.3146，D7 的 N225 DM = 2.3146。SPY 同樣。

---

## 為什麼月頻重估會讓符號反轉

波動率模型的參數不是常數，在不同市場環境下會漂移。2020-2025 這段樣本外期間涵蓋 COVID 崩盤（2020-03）、快速復甦、2022 升息週期、2024 日圓套利平倉、2025 關稅衝擊，這些事件的波動率結構都不一樣。

當 `refit_every = 25` 時，模型在這些結構轉變之後繼續用舊參數預測長達一個月。gap² 訊號的係數在 D7 估計下是有效的，但到了 D8，有些 refit 視窗剛好落在市場制度轉換的錯誤邊界，累積 25 天的誤差之後，gap² 的貢獻被舊參數扭曲，整體 QLIKE 比 baseline 更差，DM 統計量就翻負了。

這不是 gap² 失效，是 cadence 設定讓模型沒有機會及時更新。

---

## 「skewed-t 不幫助」的結論是真的

D8 除了改 refit 頻率，也加入了 Hansen (1994) 的偏態 t 分佈作為創新分佈，D7 只用標準 Student-t。D8 的初步報告把「skewed-t 也沒改善」當成第二個結論，但問題是：如果連 Student-t gap 的 DM 值都因為 cadence artifact 被壓到負值，那 skewed-t 的測試本身就是在汙染的基線上進行的。

D9 在恢復 `refit_every = 5` 的前提下，同時跑了 Student-t 和 skewed-t 兩個版本：

- N225 skewed-t gap DM = **+0.66**（不顯著）
- SPY skewed-t gap DM = **+2.73**（顯著）

![K1100G D9：Student-t vs Skewed-t 在正確 Cadence 下的比較（OOS 2020-2025）](https://qxhfgdfzazwpkdgesavm.supabase.co/storage/v1/object/public/article-images/k1100g_d9_student_vs_skewt.png)

N225 的 skewed-t 結論在 D9 是穩的：加了 skewed-t 之後，N225 的預測改善幅度從 +2.31 掉回 +0.66，統計上不顯著。「偏態 t 分佈對 N225 沒有額外幫助」這個結論不是 cadence 造成的，是真實效果。

SPY 在 D9 下的 skewed-t 表現反而比 Student-t 好（+2.73 vs +0.66），這是 D8 的 cadence 汙染被修正之後才看得到的細節。

---

## 如果在 D8 就停下來

D8 的原始報告在結果 JSON 裡已經標了 `PRELIMINARY`，並在 verdict reason 裡寫明「Student-t DM sign flip between d7 (+2.32/+0.66) and d8 (-1.92/-2.10) is refit-cadence artifact not skewed-t regression. Proper re-test deferred to K1100g_d9.」

但如果沒有這個標記，只看數字？兩個市場的 DM 全部負值，QLIKE 改善幅度也是負的（SPY 甚至 -19.7%），任何一個按照標準流程的研究者都會下結論：「PRG gap² 訊號在 skewed-t 框架下無效，D7 的邊際顯著結果不具穩健性。」

然後 D9 把同樣的數字完全還原。

這就是 refit cadence artifact 的危險性：它不是樣本雜訊，不是計算錯誤，不是遺漏某個控制變數，是一個在設計文件裡完全合理的超參數選擇，但放在特定數據環境下，能讓統計量的符號整個對調。

---

## 給研究設計的教訓

模型裡任何涉及「定期更新」的設定都值得做敏感度分析，包括：

- 滾動估計視窗（rolling window）
- 樣本外重新估計的頻率（refit cadence）
- 模型選擇的重估週期

K1100G 系列這次的教訓是：在做「加入新特徵有沒有效」的比較之前，先確認不同批次用的是相同的更新頻率。否則你比較的不是特徵，是頻率。

D9 的完整結果儲存在 `experiments/k1100g_d9/k1100g_d9_results.json`，D8 的對比數據在 `experiments/k1100g_d8/k1100g_d8_results.json`。

---

## 目前站在哪裡

K1100G 系列的核心問題是：「gap²（開盤跳空平方）能改善日內波動率預測嗎？」

D9 確認之後，答案是：

- **N225**：Student-t 框架下，gap² 顯著改善預測（DM = +2.31，p = 0.021，QLIKE 改善 2.33%）。加 skewed-t 後改善幅度縮小到 +0.66（不顯著），偏態 t 分佈本身對 N225 沒有額外貢獻。
- **SPY**：Student-t 框架下 DM = +0.66（不顯著），但 skewed-t 框架下 gap² 的 DM 回到 +2.73。

兩個市場至少各有一個框架顯示 gap² 訊號有效。Harvey (2016) 最高門檻（|t|>3.0）兩個框架都還沒到，D10 之後繼續。

---

*數據來源：K1100G_D8（k1100g_d8_results.json）、K1100G_D9（k1100g_d9_results.json）；樣本期 2010-2026，OOS 期間 2020-2025，N225 n=1465，SPY n=1508。*
