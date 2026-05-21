---
title: "VIX 該選哪個天期？四種 VIX 同台比拚波動率預測力"
audience: general
status: draft
tags: [VIX, 波動率預測, GARCH, SPY, 隱含波動率, 模型比較, 實證研究]
experiment_refs: [K1073]
---

# VIX 該選哪個天期？四種 VIX 同台比拚波動率預測力

## 一、為什麼這個問題重要

談到「市場恐慌指標」，多數投資人腦中跳出來的就是 VIX。但很少人知道，CBOE 其實同時公佈四種不同天期的 VIX 家族指數：

- **VIX9D**：9 天期，最敏感、最快反應
- **VIX**：30 天期，業界標準
- **VIX3M**：3 個月期，最平滑
- **VVIX**：VIX 的波動率，屬於「波動率的二階指標」

對於做波動率預測模型的研究者來說，這個分歧很重要。我們在前期實驗（K988、K1056、K1066）已經確認，把 VIX² 當作 GARCH 模型的外生變數（也就是業界稱呼的 GARCH-MIDAS 或 A4f 規格）能顯著提升 SPY 的波動率預測準確度。但接下來自然要問：**如果改用 VIX9D、VIX3M 或 VVIX，預測會更準嗎？或者其實差不多？**

這不是吹毛求疵的學術問題。對於做選擇權避險、做波動率交易、做風險預警的實務工作者來說，選錯天期可能導致：

- **過度反應**：用太短天期的 VIX9D 當訊號，可能把短期雜訊當成趨勢，頻繁變動部位
- **反應遲鈍**：用太平滑的 VIX3M，碰到突發事件可能來不及調整
- **訊號失真**：用 VVIX 這種二階指標，可能根本抓不到一階波動率訊號

K1073 這個實驗的目的，就是用嚴謹的統計方法，回答這個業界一直沒有完整回答的問題。

## 二、實驗設計：14 個模型的同場較量

### 資料來源

- **標的**：SPY（S&P 500 ETF）日資料，調整後收盤價、收盤價、開盤價
- **VIX 家族**：^VIX、^VIX9D、^VIX3M、^VVIX，皆來自 yfinance
- **樣本期間**：2011-01-04 至 2026-04-10（VIX9D 從 2011 年才有完整資料，這是 binding constraint）
- **總樣本數**：3,831 個交易日
- **樣本外（OOS）**：2013-01-02 起，共 3,330 個觀察值，約 13 年

### 模型規格

我們採用 Engle、Ghysels 與 Sohn（2013）的乘法分解架構，把波動率拆成兩個部分：

> σ²_t = τ_t · g_t

其中 g_t 是傳統 GJR-GARCH 的短期成分，τ_t 是長期成分，由 VIX 家族驅動。我們設計了七種 τ_t 規格：

1. **GJR baseline**：純 GJR-GARCH，沒有外生變數
2. **A4f-VIX**：τ 由 VIX² 驅動（Paper 9 主規格）
3. **A4f-VIX9D**：τ 由 VIX9D² 驅動
4. **A4f-VIX3M**：τ 由 VIX3M² 驅動
5. **A4f-VVIX**：τ 由 VVIX² 驅動
6. **A4f-SLOPE**：VIX² 加上 (VIX3M - VIX) 期限結構斜率
7. **A4f-COMBO**：VIX9D²、VIX²、VIX3M² 三者一起放

每個 A4f 規格各跑兩個目標：close-to-close 報酬平方（r²_close）與 open-to-close 報酬平方（r²_oc），總計 14 個模型。

### 估計與評估

- **估計方法**：L-BFGS-B 配 3 次 multi-start 起始值，A4f 的負對數似然函數用 numba 編譯加速
- **滾動視窗**：2,000 天訓練窗，每 63 個交易日（約季度）重估一次，總共 53 次 refit
- **評估指標**：Patton（2011）的 QLIKE 損失函數（對波動率代理變數穩健）、MSE、MAE、Spearman 相關係數
- **比較檢定**：兩兩配對的比較檢定（Newey-West HAC 標準誤，落後階數 T^(1/3)）
- **顯著性門檻**：HLZ (2016) 統計強度 > 3.0 的嚴格統計門檻

### Lookahead audit（已通過）

- VIX 落後 1 期：`vix_lag[t] = vix[t-1]` 在 `build_vix2_lag` 函式內明確實作
- 樣本外預測在 t 期使用的是 t-1 期已知的 X²，不會洩漏未來資訊
- g 狀態在 refit 之間連續傳遞，不會偷看未來報酬
- 隨機種子固定為 42，重抽樣與起始值搜尋都可重現

## 三、QLIKE 排名：誰是冠軍？

### close-to-close 目標

| 排名 | 模型 | QLIKE | Spearman ρ |
|------|------|-------|-----------|
| 1 | A4f-VIX9D | -8.6675 | 0.4490 |
| 2 | A4f-VIX | -8.6499 | 0.4347 |
| 3 | A4f-SLOPE | -8.6221 | 0.4373 |
| 4 | A4f-VIX3M | -8.6116 | 0.4111 |
| 5 | A4f-VVIX | -8.5880 | 0.4000 |
| 6 | GJR baseline | -8.5607 | 0.3727 |
| 7 | A4f-COMBO | -8.4803 | 0.4345 |

### open-to-close 目標

| 排名 | 模型 | QLIKE | Spearman ρ |
|------|------|-------|-----------|
| 1 | A4f-VIX9D | -9.0959 | 0.4373 |
| 2 | A4f-VIX | -9.0768 | 0.4250 |
| 3 | A4f-COMBO | -9.0481 | 0.4557 |
| 4 | A4f-VIX3M | -9.0436 | 0.4078 |
| 5 | A4f-VVIX | -9.0146 | 0.3969 |
| 6 | GJR baseline | -8.9789 | 0.3680 |
| 7 | A4f-SLOPE | -8.9807 | 0.4248 |

![QLIKE 排名比較](../experiments/k1073/k1073_qlike_ranking.png)

兩個目標下，**VIX9D 都拿了第一**。但 VIX 緊追在後，差距非常小（QLIKE 改善只有 0.18% ~ 0.21%）。COMBO 在 close 目標下竟然比 GJR baseline 還差，這是個有趣的訊號，後面會解釋。

## 四、比較檢定：差距是真的，但有多大？

光看 QLIKE 排名不夠，必須做正式的**兩模型比較顯著**檢定，看差距是不是統計上站得住腳。

### 各 A4f 變體 vs GJR baseline（r²_close）

| 模型對 | 統計強度 | 是否達 HLZ 嚴格門檻 |
|--------|----------|-------------------|
| A4f-VIX9D vs GJR | +7.51 | ★★★ 是 |
| A4f-VIX vs GJR | +7.17 | ★★★ 是 |
| A4f-VIX3M vs GJR | +4.64 | ★★★ 是 |
| A4f-VVIX vs GJR | +2.84 | 否（接近邊界） |
| A4f-SLOPE vs GJR | +2.21 | 否 |
| A4f-COMBO vs GJR | -0.63 | 否（GJR 反而勝） |

### 各 A4f 變體 vs GJR baseline（r²_oc）

| 模型對 | 統計強度 | 是否達 HLZ 嚴格門檻 |
|--------|----------|-------------------|
| A4f-VIX9D vs GJR | +6.22 | ★★★ 是 |
| A4f-VIX vs GJR | +6.08 | ★★★ 是 |
| A4f-SLOPE vs GJR | +5.60 | ★★★ 是 |
| A4f-COMBO vs GJR | +5.53 | ★★★ 是 |
| A4f-VIX3M vs GJR | +4.75 | ★★★ 是 |
| A4f-VVIX vs GJR | +3.17 | ★★★ 是 |

![DM 矩陣熱圖](../experiments/k1073/k1073_dm_matrix.png)

### 關鍵頭對頭：VIX9D vs VIX

這才是真正要回答 H1（VIX² 是不是最佳天期）的關鍵：

- **r²_close 目標**：統計強度 +2.70，**未達**嚴格統計門檻（H1 在 close 目標下為 FAIL）
- **r²_oc 目標**：統計強度 +3.53，**達顯著水準**（H1 在 oc 目標下 PASS）

換句話說，VIX9D 確實在兩個目標上都比 VIX 微幅勝出，但只有在 open-to-close 這個目標上，差距才嚴格顯著。

### 加期限結構斜率有用嗎？

H2 假設加上 VIX3M - VIX 的期限結構斜率作為第二個迴歸子，能再多榨出一點預測力。結果：

- **r²_close**：SLOPE vs VIX 統計強度 -1.10（VIX 反而略好，未達顯著）
- **r²_oc**：SLOPE vs VIX 統計強度 -0.28（VIX 略好，未達顯著）

H2 **FAIL**。期限結構的資訊跟 VIX 水準本身高度重疊，加進去沒有額外貢獻。

## 五、整體結論：VIX 家族都能用，差別不大

![模型比較表](../experiments/k1073/k1073_comparison_table.png)

把所有結果彙整起來，K1073 給出三個明確結論：

### 結論一：四種單一 VIX 變體都顯著贏過 GJR

VIX、VIX9D、VIX3M、VVIX 在 r²_oc 目標下**全部**達到嚴格統計門檻（HLZ 2016 統計強度 > 3.0），打敗純 GJR-GARCH。在 r²_close 目標下，前三者顯著勝出，VVIX 接近邊界。

**意義**：A4f-GARCH 框架對 VIX 天期選擇**不敏感**——重點是「有沒有 VIX 家族變數」，不是「選哪一個天期」。

### 結論二：VIX9D 微幅勝過 VIX，但實務意義不大

QLIKE 改善只有 0.18% ~ 0.21%。比較檢定統計強度 +2.70（close）/ +3.53（oc），只有後者達嚴格統計門檻。VIX9D 的歷史比 VIX 短了 21 年（2011 vs 1990），這對長樣本研究是重大限制。

### 結論三：「越花俏越好」不成立

A4f-COMBO（同時放 VIX9D²、VIX²、VIX3M²）在 close 目標下竟然比 GJR baseline 還**差**（統計強度 -0.63）。原因：VIX 家族兩兩相關係數都超過 0.9，多重共線性讓最佳化過程不穩定，部分 refit 視窗的 MSE 甚至飆到 1.79e+08。**少即是多**——選一個天期，不要硬塞三個。

A4f-SLOPE（VIX² 加期限結構斜率）也是類似情況：close 目標 MSE 也飆到 1.22e+07。

### 一個有趣的反直覺現象

如果看 θ₁（VIX 係數）跨 53 次 refit 的穩定性（變異係數 CV）：

| 模型 | CV |
|------|-----|
| A4f-VVIX_close | 0.60（最穩定） |
| A4f-VIX9D_close | 1.50 |
| A4f-VIX_close | 3.00 |
| A4f-VIX_oc | 5.55（最不穩定） |

**參數越穩定，預測力反而越差**。這聽起來矛盾，但其實是已知的 GARCH-MIDAS 識別問題——我們沒有強加 E[g]=1 的標準化條件，所以 τ 與 g 兩個成分的個別參數可以「自由分工」，但乘積 τ·g 仍然 well-identified（預測本身有效）。研究誠實的角度，這個侷限必須誠實揭露。

## 六、對 Paper 9 的具體建議

最終建議：**保留 A4f-VIX 為主規格，把 A4f-VIX9D 放進 robustness 附錄**。

理由有四：

1. **邊際改善小**：QLIKE 改善 < 0.3%，比較檢定統計強度只有一個目標（r²_oc）跨過 HLZ 嚴格統計門檻
2. **資料覆蓋窄**：VIX9D 從 2011 年起，VIX 從 1990 年起。改用 VIX9D 會犧牲 21 年的潛在 OOS 樣本，包含 2008 金融海嘯這種重要的歷史壓力情境
3. **業界先例**：VIX² 是 GARCH-MIDAS 文獻的業界標準（Engle, Ghysels, Sohn 2013），偏離標準需要更強的證據
4. **強化 robustness**：把 VIX9D 放進附錄，可以證明「A4f 的有效性是 VIX 內容驅動，不是特定天期驅動」——這個 framing 反而強化 Paper 9 的核心主張

## 七、限制與未來方向

K1073 不是最終答案。誠實揭露五個限制：

1. **標準化未強加**：自由 ω_g 參數化導致 τ 與 g 個別不可識別。未來 K 應重估 E[g]=1 約束版本
2. **雙峰最佳化**：L-BFGS-B 在不同 refit 視窗找到「τ 主導」與「g 主導」兩個局部最優解。預測本身一致，但參數軌跡呈現雙峰
3. **樣本起點 2013**：無法外推到 2008-09 危機期間。VIX9D 可得性是 binding constraint
4. **VIX 家族多重共線性**：VIX 與 VIX9D / VIX3M 兩兩相關係數 > 0.9，COMBO 規格因此數值不穩定
5. **單一資產**：只測 SPY。QQQ、GLD、台灣 0050 的跨資產驗證留待後續 K

未來研究方向：

- 用 E[g]=1 標準化重估，讓 τ/σ² 比例可解釋
- 測試 log(VIX) 變換或平方根變換
- 跨資產 VIX 敏感度（QQQ、GLD、0050.TW；對 0050 主用 VIXTWN，VIX 當跨市場 proxy）
- 時變 VIX 選擇：高波動率體制下 VIX9D 是否勝出？低波動率體制下 VIX3M 是否勝出？
- 延伸到 2000 年起，犧牲 VIX9D，但納入 2008 危機

## 八、給投資人的三個 take-away

1. **「選對 VIX 天期」沒有大家想的那麼重要**：四種天期全部都比沒有 VIX 的 GARCH 模型好。重點是「有用 VIX」，不是「用哪一個」
2. **更花俏不一定更好**：把三種 VIX 一起塞進去，反而因為共線性而讓模型崩潰。簡單、單一變數的規格才穩定
3. **歷史長度有實務價值**：VIX9D 雖然反應快，但只回到 2011；如果你的策略需要驗證跨多次危機（2008、2011、2015、2018、2020、2022），VIX 仍是首選

## 資料來源

- **實驗代號**：K1073（A4f Exogenous Variable Sensitivity — VIX9D vs VIX vs VIX3M vs VVIX）
- **資產**：SPY（S&P 500 ETF）
- **VIX 家族**：^VIX、^VIX9D、^VIX3M、^VVIX，皆來自 yfinance
- **樣本期間**：2011-01-04 至 2026-04-10
- **OOS 期間**：2013-01-02 起，共 3,330 個觀察值
- **滾動視窗**：2,000 天，每 63 日 refit，總計 53 次重估
- **隨機種子**：42（可重現）
- **相關 K**：K988（A4f-VIX vs GJR 首次驗證）、K1056（A4f-VIX 跨子期間穩定性）、K1066（A4f_oc vs GJR_oc 在 r²_oc 上首次驗證）、K1024（同 family 跨資產延伸）

## 參考文獻

- Engle, R. F., Ghysels, E., & Sohn, B. (2013). Stock market volatility and macroeconomic fundamentals. *Review of Economics and Statistics*, 95(3), 776-797.
- Patton, A. J. (2011). Volatility forecast comparison using imperfect volatility proxies. *Journal of Econometrics*, 160(1), 246-256.
- Harvey, C. R., Liu, Y., & Zhu, H. (2016). …and the cross-section of expected returns. *Review of Financial Studies*, 29(1), 5-68.
- Hansen, P. R., & Lunde, A. (2005). A forecast comparison of volatility models. *Journal of Applied Econometrics*, 20(7), 873-889.
- CBOE. VIX, VIX9D, VIX3M, VVIX methodology white papers.
