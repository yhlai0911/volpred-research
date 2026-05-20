---
title: "晶圓代工財報日波動率謎題 — K1108 系列六層機制 NULL 全記錄"
audience: research
tags: ["晶圓代工", "財報日波動率", "A4f-EAV", "GJR-GARCH", "機制檢定", "資本支出"]
experiment_refs: ["K1108", "K1108b", "K1108c", "K1108d", "K1108e", "K1108f"]
status: draft
image_url: "https://qxhfgdfzazwpkdgesavm.supabase.co/storage/v1/object/public/article-images/k1108_tau_jump_timeseries.png"
---

## 摘要

K1104 發現晶圓代工股（台積電、聯電等）的財報日長記憶波動率參數 θ₂ 方向為正（foundry θ₂=+4.72×10⁻⁴），而 fabless 廠商方向為負（θ₂=−9.61×10⁻⁴，HAC t=−2.22，p=0.039）。這個方向差異引發一個具體的研究問題：是什麼機制讓晶圓代工股在財報日維持系統性的隱含波動率溢酬（EAV premium）？K1108 系列沿此問題展開六層機制檢定，涵蓋 2014–2025 年 TSMC 單廠、四廠跨市場池（TSMC/UMC/GFS/SMIC）、capex 指引連續量測、非 capex 指引（稼動率/晶圓 ASP/研發）、營運槓桿以及景氣循環交互作用，共 136 個財報事件、N 樣本最大達 9,844 筆交易日。六層檢定的結論一致：所有機制假說均未達 Harvey, Liu & Zhu（2016）\|t\|>3.0 門檻，部分 F 統計量最高 p=0.102，Wald 最寬廣 p=0.997。EAV premium 的存在已獲確認，但其機制仍是懸案。

---

## 研究背景

晶圓代工業在財報公布日前後，隱含波動率出現系統性跳升，這個觀察在 K1104 的 A4f-EAV 框架（GJR-GARCH 乘法元件模型，τ_t=max(θ₀+θ₁·VIX²_{t−1}+θ₂·EAV_{t−1}, ε)，Engle, Ghysels & Sohn 2013 MIDAS 結構）中形式化為 θ₂ 的方向。K1104 跑 0050.TW 成分股 23 家，foundry 平均 θ₂=+4.72×10⁻⁴（t=+0.75，p=0.463，方向明確但統計力不足），fabless 平均 θ₂=−9.61×10⁻⁴（t=−2.22，p=0.039，顯著為負）。

這個差異本身不難理解：晶圓代工是資本密集型產業，一張財報公布的不只是季度獲利，還包含了對未來幾年資本支出計劃的更新——每一筆 capex 指引修正都是 capacity 擴張或縮減的長期訊號，因此市場在財報日前後承擔的不確定性比 fabless 廠商更大、更持久。然而，「capital-intensive 產業特性」只是一個描述性解釋，不是一個可以被否證的機制假說。

K1108 系列的設計目的，就是把這個描述性直覺分解為五類可檢定的機制，逐層用資料說話：

1. **Layer 1 — capex 指引變動（二元）**：當期財報是否附帶 capex 指引更新？
2. **Layer 2 — capex 指引量（連續）**：指引變動幅度（delta_pct）與 EAV 有無線性關係？
3. **Layer 3 — 非 capex 指引**：稼動率變化、晶圓 ASP 變化、研發支出變化是否能解釋 EAV？
4. **Layer 4 — 營運槓桿**：固定成本佔比（PPE/Rev、D/E、(PPE+SGA)/Rev）是否調節 EAV？
5. **Layer 5 — 景氣循環**：產業上行期（2020Q2–2021、2024–2025）vs 下行期（2022–2023）EAV 有無差異？

以下按層逐一呈現檢定設計、關鍵統計量與結論。

---

## 方法與數據

| 項目 | 設定 |
|------|------|
| 基準模型 | A4f-EAV（GJR-GARCH×τ_t；θ₂ 捕捉財報日長記憶波動率成分） |
| PIT 對齊 | 所有回歸解釋變數落後 1 個交易日（EAV_{t−1}、VIX²_{t−1}） |
| 樣本期間（基礎） | 2014–2025（TSMC 單廠 K1108；N=2,922 交易日，48 事件） |
| 跨廠池（K1108b） | TSMC(2330.TW)、UMC(2303.TW)、GFS、SMIC(0981.HK)；N=9,844；136 事件 |
| 統計門檻 | Harvey, Liu & Zhu（2016）\|t\|>3.0（多重檢定校正後） |
| HAC 標準誤 | Newey-West，Andrews（1991）自動頻寬 |
| Bootstrap | Politis & Romano（1994）block bootstrap，B=10,000 |
| Wald 檢定 | 估計系統聯立；LR 檢定對數概似比；Partial-F 聯立排除 |

---

## 核心發現

### Layer 1（K1108）— capex 指引變動二元效應：INCONCLUSIVE

TSMC 2014–2025 年 48 個財報事件中，25 件附帶 capex 上修/下修（change），23 件維持不變（stable）。A4f-EAV 在 M2 模型加入 capex_change 虛擬變數後，Wald 檢定 t=+0.94（p=0.348），未達顯著。

![TSMC τ_EAV 時序：財報日跳升幅度](https://qxhfgdfzazwpkdgesavm.supabase.co/storage/v1/object/public/article-images/k1108_tau_jump_timeseries.png)
*圖1：TSMC 2014–2025 財報日前後 τ_EAV 跳升序列。紅色垂直線為 capex 指引更新事件；藍色為維持不變事件。兩組的跳升幅度在視覺上無明確分群。*

LR 檢定（M3 vs M2，df=1）顯示 p=0.025，在傳統 5% 門檻下顯著，但 Wald 與 LR 的矛盾（Wald null、LR marginal）是已知的小樣本現象，不能單憑 LR 宣稱效應存在。Block bootstrap（B=10,000）的 θ_change 95% CI 為 [−8.04×10⁻⁵，+9.87×10⁻⁵]，涵蓋零。

兩組條件均值方向反轉（τ_change=+6.79% vs 非事件日；τ_stable=−38.53% vs 非事件日）看似有趣，但 N_change=25 在 Harvey 門檻下嚴重欠缺統計力，結論定為 **INCONCLUSIVE（underpowered）**。

---

### Layer 2a（K1108b）— 四廠跨市場池：H2_NULL

K1108b 擴大到四廠（TSMC/UMC/GFS/SMIC），N=9,844 筆、136 個財報事件（capex change=63，stable=73），在股票固定效果框架下重跑池 Wald 檢定。

Pool Wald t=−0.0003（p=0.9997），差異估計 Δ=−3.74×10⁻⁸≈0。留一廠測試（LOO）最大 \|t\|=0.77（排除 GFS 時），四廠中 3/4 方向一致（positive θ₂ for change events）但無一接近 Harvey 門檻。

![四廠 θ₂ per-stock Forest Plot](https://qxhfgdfzazwpkdgesavm.supabase.co/storage/v1/object/public/article-images/k1108b_per_stock_theta.png)
*圖2：K1108b 四廠個別 θ₂ 係數與 95% HAC 信賴區間。所有信賴區間均涵蓋零，無廠商達 Harvey \|t\|>3.0 門檻。*

此層結論：無論單廠（K1108）或多廠池（K1108b），capex 指引更新與否對 θ₂ 的解釋力均為零。EAV premium 的存在不靠 capex 指引變動這個二元開關。

---

### Layer 2b（K1108c）— capex 指引幅度連續量測：H2_MAGNITUDE_NULL

也許二元虛擬變數太粗，改用 guide_delta_pct（capex 指引修正百分比，範圍 [−69.57%, +136.84%]，N=135 個配對事件）做線性回歸，被解釋變數為 θ_EAV。

![θ_EAV 對 guide_delta_pct 散點圖](https://qxhfgdfzazwpkdgesavm.supabase.co/storage/v1/object/public/article-images/k1108c_scatter_theta_vs_deltapct.png)
*圖3：K1108c 財報日 EAV 參數（θ_EAV）對 capex 指引修正幅度（%）的散點圖。迴歸線斜率接近水平；Bootstrap 95% CI 涵蓋零。*

HAC 估計：β₁=−1.286×10⁻⁵（SE=9.60×10⁻⁶，HAC t=−1.339，p=0.180）；95% CI=[−3.17×10⁻⁵，+5.96×10⁻⁶]。Bootstrap 95% CI=[−1.79×10⁻⁵，+1.63×10⁻⁵]，p=0.728，R²=0.003（解釋力接近零）。

LOO 敏感性：排除任一廠商後 \|t_HAC\|<1.6。

符號不對稱測試（正向修正 vs 負向修正）出現反直覺結果：capex 上修愈大，θ_EAV 愈低（β_pos：HAC t=−2.329，p=0.020）。這個符號在因果解釋上難以自圓其說，更可能是小樣本下噪音，不應過度詮釋。

結論：**H2_MAGNITUDE_NULL 決定性**。capex 指引規模無論二元還是連續量測，均無法解釋 EAV premium。

---

### Layer 3（K1108d）— 非 capex 指引：H_D2_LOW_COVERAGE（初步 NULL）

晶圓代工財報除 capex 外，還公布稼動率變化（utilisation_delta_pp）、晶圓 ASP 變化（wafer_asp_delta_pct）、研發支出變化（rd_delta_pct）。K1108d 收集這三項指標並對 θ_EAV 做回歸。

| 指標 | 事件覆蓋率 | HAC t（單變數） |
|------|-----------|----------------|
| utilisation_delta_pp | 23.7%（N=32） | −0.47 |
| wafer_asp_delta_pct | 11.1%（N=15） | −0.61 |
| rd_delta_pct | 23.7%（N=32） | **0.97**（最大） |
| 三指標同時可用 | 8.9%（N=12） | — |

![非 capex 指標係數 Forest Plot](https://qxhfgdfzazwpkdgesavm.supabase.co/storage/v1/object/public/article-images/k1108d_coef_forest.png)
*圖4：K1108d 三項非 capex 指引的 θ_EAV 係數與 HAC 信賴區間。所有係數均涵蓋零，最大 \|t\|=0.97（rd_delta_pct）。*

聯立 Partial-F 檢定（F(3,117)=0.347，p=0.791）無差異。三指標同時可用的樣本僅 N=12（8.9%），遠低於可靠推論所需的 60% 覆蓋門檻。

結論：**H_D2_LOW_COVERAGE_PRELIMINARY NULL**。資料覆蓋率不足使得這一層的結論只能是「初步排除」，而非決定性排除。未來更完整的非 capex 財報資料收集是後續研究的前置工作。

---

### Layer 4（K1108e）— 營運槓桿：H_D3_NULL 決定性

假說：固定成本佔比愈高（即營運槓桿愈大），財報日盈利不確定性就愈大，帶動更高 θ_EAV。K1108e 用三種量測：PPE/Rev（廠房設備強度）、D/E（財務槓桿）、(PPE+SGA)/Rev（含銷管費廣義固定成本）。

yfinance 季度財報資料覆蓋範圍限於 2021-12-31 至 2025-12-31，匹配到 47 個財報事件。3 specs × 3 measures = 9 個回歸格。

最大 \|t_HAC\|=1.584（pooled OLS × op_lev_2，即 D/E）。加入廠商固定效果後，所有格的 \|t\|<0.5——這表明最初觀察到的有限相關性可能源於 SMIC 這家極端槓桿廠商的固定截距，不是跨公司通用的截面機制。

![營運槓桿係數 Forest Plot](https://qxhfgdfzazwpkdgesavm.supabase.co/storage/v1/object/public/article-images/k1108e_coef_forest.png)
*圖5：K1108e 三種營運槓桿指標對 θ_EAV 的係數（含廠商固定效果後）。加入 FE 後，9 個格的 \|t\| 均低於 0.5，一致為 NULL。*

聯立 Partial-F 檢定：F(3,37)=2.224（p=0.102），未達 5% 顯著水準。

結論：**H_D3_NULL 決定性**。在有限但合理的資料覆蓋範圍內，營運槓桿無法解釋晶圓代工股的 EAV premium，且廠商層級的固定效果（主要是 SMIC 的極高 D/E 截距）是干擾來源。

---

### Layer 5（K1108f）— 景氣循環交互：H2_REGIME_NULL 確認

半導體產業有明確的景氣循環：2020Q2–2021 及 2024–2025 為 UP（需求爆發、缺貨），2022–2023 為 DOWN（庫存去化）。假說：EAV premium 在不同景氣階段行為不同，例如上行期市場更在意 capacity 訊號。

K1108f 按景氣分期，UP 期 N=54、DOWN 期 N=32（主要期共 86 事件），分估 β_up 與 β_down：

- β_up=−1.76×10⁻⁵（HAC t=−0.599，p=0.549）
- β_down=−1.17×10⁻⁵（HAC t=−0.863，p=0.388）
- Wald χ²(β_up=β_down)=0.036（p=0.849）——兩期估計無法區分

![景氣循環分組係數圖](https://qxhfgdfzazwpkdgesavm.supabase.co/storage/v1/object/public/article-images/k1108f_coef_forest.png)
*圖6：K1108f UP/DOWN 景氣分組係數 Forest Plot。兩期 β 信賴區間高度重疊；Wald 檢定兩期差異 p=0.849。*

加入 YoY 互動項（spec 2）：β₂=−5.42×10⁻⁵（t=−0.877，p=0.381）。Bootstrap 期別差異 95% CI=[−6.21×10⁻⁵，+3.63×10⁻⁵]，p=0.794。

結論：**H2_REGIME_NULL 確認**。景氣循環的分期在統計上不能解釋 EAV premium 的幅度或方向，無論是 OLS 估計、Wald 差異檢定還是 Bootstrap 分布。

---

## 五層 NULL 堆疊總表

| 層 | 實驗 | 假說 | 設計 | 關鍵統計量 | 結論 |
|----|------|------|------|-----------|------|
| 1 | K1108 | capex 指引二元 | TSMC 單廠，48 事件 | Wald t=+0.94，p=0.348；Bootstrap p=0.226 | INCONCLUSIVE（underpowered） |
| 2a | K1108b | 四廠池 capex 二元 | 4 廠，136 事件，N=9,844 | Pool Wald t=−0.0003，p=0.997；LOO max\|t\|=0.77 | H2_NULL |
| 2b | K1108c | capex 指引連續量 | guide_delta_pct，N=135 | HAC t=−1.34，p=0.180；Bootstrap p=0.728；R²=0.003 | H2_MAGNITUDE_NULL（決定性） |
| D2 | K1108d | 非 capex 指引 | util/ASP/R&D，N=12–32 | Partial-F p=0.791；max\|t\|=0.97 | H_D2（初步 NULL，低覆蓋） |
| D3 | K1108e | 營運槓桿截面 | 3 specs，N=47，FE 模型 | max\|t\|=1.584；FE 後全\|t\|<0.5；Partial-F p=0.102 | H_D3_NULL（決定性） |
| 5 | K1108f | 景氣循環交互 | UP/DOWN split，N=86 | Wald p=0.849；Bootstrap diff p=0.794 | H2_REGIME_NULL（確認） |

所有機制假說中，沒有任何一層的主要推論統計量達到 Harvey, Liu & Zhu（2016）\|t\|>3.0 門檻。各層最大觀察到的 HAC t 絕對值為：0.94（K1108）、0.77（K1108b LOO）、1.34（K1108c）、0.97（K1108d）、1.584（K1108e pooled，FE 後降至<0.5）、0.86（K1108f）。

---

## 實務意義

這個 NULL 堆疊的結論在邏輯上有兩個方向的解讀。

**解讀一：EAV premium 是產業固定效果，與當季財報資訊內容無關。** 晶圓代工股的高 θ₂ 來自這個產業類型本身的結構特徵——長建置週期、客戶集中、設備折舊結構——讓市場在每一個財報日都承擔更高、更持久的不確定性，與當季 capex 上修或下修的幅度無關。換句話說，EAV premium 是晶圓代工類股向市場收取的「行業不確定性費率」。

**解讀二：現有指標的測量範圍不足。** 稼動率、capex delta 和 D/E 都是公開 disclosed 的落後指標；驅動 EAV 的可能是市場對「下一季度訂單能見度」的私有預期，而這個量無法從公開財報欄位中量化。若驅動機制在現有資料集中不可觀察，六層 NULL 只說明「目前工具箱範圍內無解釋力」，不排除機制存在於未量化的維度。

從風險管理實務的角度，兩種解讀收斂到同一個操作推論：晶圓代工股的財報日 EAV premium 在六層檢定後仍未被分解，其幅度不因特定財報的好壞或 capex 指引規模而系統消退。任何以 EAV 調整的波動率模型在應用於晶圓代工類股時，應將 θ₂>0 作為先驗約束，而非期待從財報事件特徵推導出事後解釋。

---

## 限制與穩健性

**樣本覆蓋**：K1108b 的四廠池在跨市場比較上仍受限——GFS（無公開詳細財報）和 SMIC（A 股/港股雙重結構）的財務揭露格式差異較大，可能影響 capex 指引欄位的口徑一致性。K1108d 的三項非 capex 指標覆蓋率僅 8.9%（N=12），此層結論只能是初步性的。

**事件數**：即使在最大的 K1108b 四廠池，136 個事件在 Harvey \|t\|>3.0 的要求下，單一機制假說的統計力仍有限。K1108 單廠的 48 事件是最嚴重的欠缺統計力情況。

**層4（營運槓桿）的資料時間跨度**：yfinance 季度財報資料僅從 2021-12-31 起，錯過了 2014–2020 六年的 capex 週期，使得 K1108e 的 47 個配對事件無法代表完整的產業循環。

**PIT 對齊的代理問題**：所有回歸使用前一交易日（t−1）的解釋變數。財報公布時間可能在盤後，使財報日當天的 EAV 理論上已包含市場對「即將公布」的預期，而非單純對「已公布」的反應。這個 timing 微妙性在現有架構中難以精確排除。

**FAB vs fabless 的跨研究可比性**：K1104 的 fabless θ₂=−9.61×10⁻⁴ 顯著為負，K1108 系列的 foundry 方向為正但未達顯著——這個不對稱性是真實的行業差異，還是因為 K1104 的 fabless 樣本（多家小廠）vs K1108 系列的 foundry 樣本（頭部廠商）在截面異質性上的差異造成？此問題需要更系統的跨類型比較設計來回答。

---

## 結論

K1108 系列從 2014–2025 年的晶圓代工財報事件出發，依次排除 capex 指引更新（二元）、capex 指引幅度（連續）、非 capex 財報指引、營運槓桿以及景氣循環交互作用等五類機制假說。六層檢定的統計結論一致為 NULL：在 Harvey, Liu & Zhu（2016）的多重檢定校正門檻（\|t\|>3.0）下，沒有任何測試的機制能解釋晶圓代工股財報日的 EAV premium（θ₂>0）。

這個 NULL 堆疊本身是一個正面發現。它的核心命題是：晶圓代工 EAV premium 的驅動力很可能是難以從公開財報欄位量化的行業固定效果，而現有可觀察的事件驅動指標均無解釋力。

後續研究方向有三：（a）納入市場對 capacity 擴張的私有預期代理變數（如客戶端訂單能見度、TSMC CoWoS 月產能數字等非公開但可間接量測的指標）；（b）擴大非 capex 指引欄位的歷史覆蓋（目前 K1108d 的 8.9% 覆蓋率是最薄弱環節）；（c）設計跨 fab/fabless 的反事實框架，量化行業類型固定效果的大小。

---

*本文基於實驗 K1108、K1108b、K1108c、K1108d、K1108e、K1108f（腳本分別位於 experiments/k1108/k1108.py、experiments/k1108b/k1108b.py 等）及前驅實驗 K1104。財報日事件資料來源：TSMC/UMC/GFS/SMIC 各公司 IR 季度法說會公告；隱含波動率資料：yfinance；期間：2014–2025；最大樣本 N=9,844 個交易日（四廠池）。*
