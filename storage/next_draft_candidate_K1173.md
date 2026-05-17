---
title: 換掉 yfinance 也救不回來：新興市場法人持股階梯為何是結構問題
audience: research
phase: research
tags: [新興市場, 法人持股, 跨市場研究, 法說會, 資本成本, paper-2]
experiment_refs: [K1173]
image_url: "https://qxhfgdfzazwpkdgesavm.supabase.co/storage/v1/object/public/article-images/k1173_scatter_refined_vs_yfinance.png"
---

## 摘要

在先前的 12 市場法說會研究（K1172）中，巴西、印度、墨西哥、中國四個新興市場在「法人持股 vs 超額已實現波動」的散布圖上明顯偏離已開發市場拉出的階梯。一個合理懷疑是：yfinance 的 `institutionsPercentHeld` 對新興市場的股權結構抓不準——印度沒把 FII+DII 加全、中國把國資看成「私人公司」、巴西把控股私募當成法人。本研究把這 40 家新興市場標的的法人持股，改用 SEBI 季報、CVM/BMV、SSE 公開揭露重新估計，再放回 K1172 的檢定。結果是 NULL：Spearman ρ 從 +0.441（yfinance）退到 +0.385（refined），方向甚至往反方向走 0.056。Panel OLS 裡的分析師人數 t-statistic 反而從 +3.79 升到 +3.86，法人持股仍然不顯著（t=-1.20）。結論：新興市場偏離階梯這件事不是代理變數造成的，是結構性的，K1172 §6.1 提的「資本成本／pooled θ_EAV 規模因子」變成唯一沒被排除的候選機制。

## 研究背景

K1165 在 N=7 已開發市場看到 Spearman ρ=+0.75 的乾淨階梯：法人持股高的市場，法說會當天的超額波動（θ_rel）相對低，符合 Ferreira & Matos (2008) 與 Bartram, Brown & Stulz (2012) 的「資訊機構快速吸收衝擊」框架。K1168 把巴西、中國、印度加進來（N=10），ρ 掉到 +0.612，但仍 STRENGTHENED 過關。K1172 再補墨西哥與印尼、踢掉樣本不足的南非（N=12），ρ 進一步退到 +0.441（p=0.152），被判 PARTIAL。

問題不是相關性消失，是新興市場全部坐在階梯外。巴西、印度、墨西哥（後來中國某種程度上也跟進）yfinance 統計的法人持股都落在 15-49% 中段區間，理論上 θ_rel 應該停在 0.2-0.4，但實際值跳到 0.3 到 1.9 之間。

K1172 §6.1 留下兩個候選解釋：

1. **資本成本／規模因子**：這幾個新興市場的 pooled θ_EAV 本身就比已開發市場高 3 到 25 倍，θ_rel 的分子被自動撐大。
2. **yfinance proxy 錯位**：中國國資被歸成 Private Companies、印度 SEBI 把 promoter 跟 FII+DII 分開但 yfinance 合併不一致、巴西把 Itaúsa 這類控股私人公司算進 institutions。

K1173 直接打第二個解釋。

## 方法與數據

| 項目 | 設定 |
|------|------|
| 樣本 | 12 市場 × 對應 stocks（panel N=172）；新興市場 refined 標的 BR/CH/IN/MX 各 10 共 40 |
| 期間 | K1172 panel 期間沿用；refined 持股 snapshot 落在 2025-12 / 2026-03 / 2026-04 |
| Refined 規格 | IN: FII + DII (SEBI 季報) ; BR: simplywall.st Institutions, 排除 Private Companies / Government / Insiders ; MX: 同 BR 規格，排除家族信託 ; CH: Institutions + Sovereign Wealth Funds, 排除 State / SOE 母公司 |
| 數據來源 | screener.in（直接刻 SEBI BSE/NSE 揭露）；simplywall.st（彙整 CVM / BMV / SSE / Form 20-F） |
| 主要檢定 | 跨市場 Spearman ρ(refined inst_pct, θ_rel)，與 K1172 baseline 對照 |
| 補充檢定 | Leave-one-out（drop 一市場）；Panel OLS N=172 帶 market dummy |
| 隨機種子 | 42（不過此實驗無 bootstrap） |

40 個標的全數成功匹配，超過 brief 設的 30/40 門檻。新興市場的 refined 數字直接覆蓋 K1172 市場層級平均；已開發市場保留 yfinance 原值不動。

## 核心發現

### 發現一：每家公司差異很大，市場平均差異有方向

![per-stock 與 per-market 差異 barplot](https://qxhfgdfzazwpkdgesavm.supabase.co/storage/v1/object/public/article-images/k1173_diff_barplot.png)

*圖 1：左圖為四個市場 yfinance 與 refined 平均的對比；右圖為 40 個標的的 refined − yfinance 差異橫條，正向表示 yfinance 低估，負向表示 yfinance 高估。*

| 市場 | N | yfinance 平均 | refined 平均 | Δ |
|---|---|---|---|---|
| IN | 10 | 0.383 | 0.569 | **+0.186** |
| CH | 10 | 0.157 | 0.283 | **+0.126** |
| MX | 10 | 0.195 | 0.236 | +0.045 |
| BR | 10 | 0.486 | 0.368 | **−0.117** |

差異有清楚的方向：

- **印度**被 yfinance 系統性低估（+0.186），主因是 DII（domestic institutional investors）整個 bucket 沒進。ITC 從 50.2% 跳到 85.0%、ICICIBANK 從 55.9% 跳到 90.6%、HDFCBANK 從 55.6% 跳到 84.2%——這三家本來就沒有 promoter，FII+DII 加起來逼近總股權的 85%。
- **中國**也低估（+0.126），國資母公司（如 ICBC 的 MoF 31.1% + Central Huijin 34.8%）被 yfinance 歸到「Private Companies」，refined 規格把 Sovereign Wealth Funds 收回到 institutions 後，ICBC 從 7.5% 跳到 47.4%、Ping An 從 20.7% 跳到 43.2%。
- **巴西**反過來，yfinance 高估（−0.117），把 Itaúsa（控股 ITUB4 46.3%）、Cidade de Deus（控股 BBDC4 28.5%）這類私人控股公司算進 institutions。refined 把它們排除後 ITUB4 從 60% 掉到 31%、PETR4 從 61% 掉到 36.5%（後者另外把 29% 政府股權拆掉）。
- **墨西哥**幾乎沒動（+0.045），yfinance 和 refined 對 Slim、Servitje、Larrea 家族控股的處理方式類似——都不算 institutions。

如果「yfinance 抓不準」是新興市場偏離階梯的主因，把這些差異補回去，cross-market 排序應該會往階梯回收。

### 發現二：但跨市場 Spearman 沒收斂，反而退一點

![refined 與 yfinance 法人持股 vs theta_rel 散布圖對照](https://qxhfgdfzazwpkdgesavm.supabase.co/storage/v1/object/public/article-images/k1173_scatter_refined_vs_yfinance.png)

*圖 2：N=12 跨市場散布圖，左為 yfinance 法人持股，右為 refined 規格；新興市場（BR、CH、IN、MX）標方塊，已開發市場標圓點。新興市場標的的橫軸位置雖然平移，但縱軸 θ_rel 沒挪動，仍然坐在已開發市場拉出的階梯上方。*

| Spec | ρ | p | N |
|---|---|---|---|
| yfinance baseline (K1172) | +0.441 | 0.152 | 12 |
| refined (本研究) | **+0.385** | **0.217** | 12 |
| Δρ | −0.056 | +0.065 | — |

方向是負的——refined ρ 比 yfinance 退 0.056，不是進。K1165 N=7 時 ρ=+0.75、K1168 N=10 時 ρ=+0.612 的水準，refined 也沒摸到。Δρ 落在預先設定的 ±0.10 NULL band 內，但既然方向是反的，proxy-artefact 假設沒有任何證據支持。

新興市場四個點在散布圖上的位置基本沒挪動：BR θ_rel=1.89、IN 1.17、MX 1.20、CH 0.30，refined 後仍坐在已開發市場（EU 0.14、TW 0.17、HK 0.18、KR 0.28、JP 0.39）拉出來的階梯上方。

### 發現三：LOO 的 MX 仍是最大支點

| Drop | refined ρ | p |
|---|---|---|
| MX | **+0.609** | **0.047** |
| EU | +0.518 | 0.103 |
| BR | +0.418 | 0.201 |
| 其他 9 個 | 0.29 - 0.46 | 0.16 - 0.39 |

把墨西哥踢掉，refined ρ 跳到 +0.609 並越過 5% 顯著線。問題是：refined 的墨西哥定義跟 yfinance 一樣排除 Slim 家族控股，inst_pct 從 0.195 微調到 0.236——proxy 怎麼改，墨西哥這個點的位置都動不了，θ_rel=1.20 在 inst_pct 0.2 附近是純粹的離群值。這代表 MX 的離群不是「我們把它的法人持股算錯了」，是這個市場法說會反應強度本身結構性高。

### 發現四：Panel OLS 把分析師人數推得更顯著

| Spec | log_analyst β (t) | institutions_pct β (t) | R² |
|---|---|---|---|
| K1172 yfinance joint | +1.28e-3 (+3.79) | -2.15e-3 (-1.32) | 0.237 |
| K1173 refined joint | **+1.24e-3 (+3.86)** | -1.69e-3 (-1.20) | 0.236 |

panel 內部（控制 market dummy 後 within-market 通道）的分析師人數 t 從 +3.79 升到 +3.86——K1165→K1168→K1172→K1173 序列中最高。法人持股係數則維持不顯著、符號不變、量級接近——當 between-market 那一層用乾淨的 proxy 換上去，within-market 那一層完全不受影響。這兩個 channel 是分開運作的，refined proxy 不會把它們攪在一起。

## 實務意義

對研究端來說，這篇實驗的價值在「排除了一個聽起來最直覺的解釋」。Paper 2 §5 原本要扛兩個 reviewer 都很可能問的反駁——「你的新興市場 outlier 不就是 yfinance proxy 不準嗎？」——現在有 SEBI / CVM / BMV / SSE 的揭露當證據打回去：proxy 換了，階梯沒回來。剩下的解釋是 K1172 §6.1 寫的資本成本 / pooled θ_EAV 規模因子，巴西（1.22e-3）、印度（3.25e-4）、墨西哥（4.15e-4）、加拿大（3.13e-4）的 pooled θ_EAV 都坐在已開發市場（4-20e-5）的 3 到 25 倍。θ_rel 是 θ_EAV 除以自身基線，分子先被拉高，θ_rel 自然往上跳。

對 portfolio 端讀者來說，這個結果的延伸是：法說會在不同市場的衝擊強度，跟你在 Bloomberg 看到的「法人持股 %」這個欄位的相關性，會被市場的整體波動規模放大或抵銷。比較 BR 跟 EU 的法人持股欄位然後預期它們的法說會反應差距，沒辦法靠單一指標調平。

對下游研究來說，剩下要回答的問題是：θ_EAV 規模差異，是來自無條件波動率本身的市場差距，還是來自「同樣的 EPS surprise → 不同市場的 vol-sensitivity」？這需要做 θ_EAV decomposition，K1175 已列入下一輪 backlog。

## 限制與穩健性

幾個 NULL 結論的可信度限制應該明寫：

1. **N=12 統計能力有限**：Δρ=−0.056 跟 0 不能拒絕，意味著 refined proxy 真的有小幅正向效果但被噪音蓋掉、在 N=18-20 才會看得到的可能性沒被排除。但既然觀察方向是反的，這個 caveat 對結論不利。
2. **Snapshot 對齊問題**：refined 持股取自 2025-12 到 2026-04 之間的單點 snapshot，而 panel 期間是 2014-2025。理想做法是 PIT 法人持股 panel（每年 13F + SEBI 季報），這部分留給 K1174。
3. **CH SOE / private institutional 邊界軟**：央匯（Central Huijin）在 simplywall.st 被歸 SWF（收入 refined），財政部股權被歸 Government（排除）。改變這個邊界 ρ 會微動但不會翻轉 verdict。
4. **MX Televisa、Gruma 用新聞摘要間接抓**：±3 ppt 不確定性，但這兩家不是 LOO leverage point，verdict 穩定。
5. **規格選擇是 pre-specified**：沒有 spec search、沒有換 cutoff、沒有用 Pearson 補打 Spearman；這篇是 NULL 不是 p-hacking 翻車。

## 結論

把新興市場法人持股換成 SEBI/CVM/BMV/SSE 規格之後，K1172 的離群結構幾乎沒移動，θ_rel 跨市場 Spearman 反而退 0.056。yfinance proxy artefact 這個解釋被資料推翻。Paper 2 §5 narrative 改寫的方向是把 caveat 從「proxy 可能不準」收緊到「新興市場本身在 pooled θ_EAV 規模上就高 3-25 倍，這是結構性的資本成本差距，不會因為 proxy 換掉就消失」。Within-market 那條 analyst channel 仍然穩——t=+3.86 是這個序列至今最高的——所以兩層機制的論述還站得住，只是 between-market 那一層必須誠實寫成 PARTIAL with structural caveat。

---

*本文基於實驗 K1173（腳本：`experiments/k1173/k1173.py`、結果：`experiments/k1173/k1173_results.json`、refined 持股 CSV：`experiments/k1173/data/k1173_em_refined_holdings.csv`）。資料來源：screener.in (SEBI Schedule III)、simplywall.st (CVM / BMV / SSE / Form 20-F)、yfinance、K1172 panel。期間：refined snapshot 2025-12 至 2026-04。樣本：12 市場、172 stocks、refined 40 stocks。隨機種子：42。[提出: User brief / K1172 PARTIAL 接續, 執行: Claude worktree agent]*
