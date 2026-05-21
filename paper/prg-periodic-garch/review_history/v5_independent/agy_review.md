這是一份針對手稿 **"Periodic Realized GARCH: Session-Boundary Information Transfers and Volatility Forecasting"**（手稿檔：`paper/prg-periodic-garch/main.tex`）的獨立審查意見。

本審查意見旨在打破「同模型（Claude）自審」容易產生的認知盲點，從計量經濟學嚴謹度、資訊集對稱性、實證邏輯一致性以及金融監管實務等維度進行深度剖析。

---

### (a) 整體傾向：MAJOR_REVISION (有條件的重大修改，若關鍵計量缺陷無法克服則傾向 REJECT)

---

### (b) 審查問題清單（依嚴重度排序）

#### 🛑 BLOCKING ISSUES (致命缺陷 — 必須解決否則直接拒稿)

1. **【方法論缺陷 / 前瞻偏差 (Lookahead Bias) 與資訊集不對稱】**
   * **定位**：`Section 2.2 (Lines 89-94)` / `Section 5 (Lines 295-300)`
   * **問題剖析**：這是本研究最核心的計量防禦漏洞。PRG 模型在預測 day $d$ 的日盤波動度 $h_{d,1}$ 時，使用了當天已實現的夜盤報酬率平方 $x_{d,0} = r^2_{d,0}$（因為夜盤已在日盤開盤前完成）。然而，基準模型（GJR-GARCH 與 HAR）是在 day $d-1$ 收盤時，以當時的資訊集預測 day $d$ 的全天波動度。這意味著 **PRG 模型比基準模型多使用了當天夜盤（開盤價）的即時資訊**。這並非純粹的「模型結構優勢」，而是典型的**前瞻偏差 (Lookahead Bias) 與不公平資訊集對照**。
   * **修改要求**：作者必須引入一個公平的對照組 **GJR-X** 與 **HAR-X**，即在標準的 GJR 與 HAR 模型中，將當天已實現的夜盤報酬（或夜盤 RV）作為外生變數（Exogenous Variable）納入資訊集，再進行日盤波動度預測。只有在 PRG 顯著優於 GJR-X / HAR-X 的情況下，才能證明「跨期週期性遞迴結構（periodic recursion）」本身具有學術價值，而非單純因為「多用了開盤價資訊」。

2. **【內部數值與邏輯嚴重矛盾 / DM 檢定符號錯誤】**
   * **定位**：`Section 4.1, Table 2 (Lines 175-188)` / `Lines 194-196`
   * **問題剖析**：Table 2 中，"PRG vs Sep"（PRG 與無跨期連結的 Separate GJR 比較）的 Diebold-Mariano $t$-statistic 在所有六個市場中**全為負值**（$-4.07$ 至 $-6.69$）。
     * 在標準的預測損失檢定中，若預測目標是證明 PRG 的損失低於 Separate GJR（即 PRG 表現更佳），且以 $\text{Loss}_{\text{Sep}} - \text{Loss}_{\text{PRG}}$ 作為差值，則顯著優於對照組的 DM $t$ 值應該是**正值**（如表中的 "PRG vs GJR" 與 "PRG vs HAR" 皆為正值）。
     * 若表中的負值在數學上成立，則代表 Separate GJR 的預測損失顯著小於 PRG（即無跨期連結的模型反而更好），這與內文第 195 行宣稱的 "confirming that the cross-session information bridge... drives the improvement" **完全矛盾**。這暴露出極其低級的符號排版錯誤，或者是底層代碼在計算損失差值時方向反轉。這在頂尖期刊審查中是絕對無法容忍的硬傷。
   * **修改要求**：徹底檢查並重新計算所有 DM 統計量，澄清差值的定義方向，確保表格數值與全文核心結論（跨期信息橋樑有效性）在邏輯上完全一致。

---

#### ⚠️ MAJOR ISSUES (重大問題 — 嚴重影響論文嚴謹度)

3. **【金融監管指標定義錯誤 / 巴塞爾綠區 (Basel Green Zone) 的宣稱偽造】**
   * **定位**：`Section 4.3, Table 4 (Lines 231-255)` / `Lines 229-230`
   * **問題剖析**：
     * Table 4 中，TAIFEX 1% VaR 的實際違約率（VR）為 **2.49%** (GJR) 與 **0.24%** (PRG Ext)。在 Kupiec 檢定中，這兩者的 $p$-value 皆小於 0.01（顯著拒絕 VR = 1% 的虛無假設），代表在統計上**兩者皆預測失準**。
     * 然而，Table 4 卻將這兩者皆標記為 **Green Zone**。根據巴塞爾委員會（Basel Committee）的 Traffic Light System，在 1% VaR 框架下，對於 843 個觀測值（TAIFEX OOS 樣本數），預期違約次數為 8.43 次。GJR 的實際違約率 2.49% 代表發生了約 21 次違約，這在統計上落入 Green Zone 的機率極低（臨界值通常在 12 或 13 次以下），**絕對屬於 Yellow Zone 甚至 Red Zone**。
     * 論文對 GJR 2.49% 的違約率給予 Green 標記，涉嫌**偽造或錯誤計算監管指標**；同時，將 PRG 的 0.24%（顯著過度保守、資金配置效率低下且被統計檢定拒絕）包裝為 "desirable property"，是極不專業的硬拗。
   * **修改要求**：
     * 依據巴塞爾標準公式（基於累積二項分佈），重新計算 843 天與 1,823 天等不同樣本數下的 Green/Yellow/Red Zone 臨界值，修正 Table 4 中的監管分區。
     * 必須在內文中承認 PRG 在 TAIFEX 上顯著過度保守（Over-conservative）在經濟上的資本成本代價，而非單純美化為優點。

4. **【嚴重缺乏計量模型參數估計與統計性質展示】**
   * **定位**：`Section 2.2` / `Section 4` 全文
   * **問題剖析**：作為一篇提出新 volatility 遞迴模型的計量金融論文，**全文竟然沒有提供任何一個市場的參數估計值、標準誤或 $t$ 統計量**。讀者完全無法得知：
     * 估計出的 session-specific 參數（$\omega_s, \alpha_s, \beta_s, \gamma_s$）在夜盤和日盤之間是否存在顯著的統計差異？
     * 估計出的參數是否在每個 Refitting 窗口中都穩定滿足 $\rho_0 \cdot \rho_1 < 1$ 的平穩性條件？
     * 缺乏這些數據，整個 PRG 模型就如同一個未經檢驗的「黑盒子」。
   * **修改要求**：必須新增一個表格，展示代表性市場（如 TAIFEX 與 SPY）在全樣本或特定區間下的參數估計結果，並提供顯著性檢定（Wald test 等），以證明夜盤與日盤參數的異質性（heterogeneity）在統計上是顯著的。

5. **【Table 4 嚴重缺失對照組數據】**
   * **定位**：`Section 4.3, Table 4 (Lines 231-250)`
   * **問題剖析**：Table 4 作為 VaR 與 ES 的評估核心表，除了 TAIFEX 和 SPY 有列出 GJR 作為對照組外，其餘四個市場（QQQ, GLD, EEM, 0050.TW）**竟然只有 PRG Extended 單一模型的數據，完全沒有任何 benchmark (GJR, HAR, Separate GJR) 的對照**。這使得該表的評估價值大打折扣，無法支持「PRG 在風險管理上全面優於基準模型」的宣稱。
   * **修改要求**：補齊所有六個市場中，GJR、HAR 和 Separate GJR 的 VaR 違約率、Kupiec $p$-value、Basel 燈號以及 ES FZ-loss 數據，進行完整的橫向比較。

6. **【樣本與數據描述不一致】**
   * **定位**：`Section 3, Table 1 (Lines 135-156)`
   * **問題剖析**：
     * Table 1 註記中指出 "U.S. ETFs use daily OHLC data with a 70/30 in-sample/out-of-sample split."
     * 然而，對於 SPY，OOS obs 標記為 **1,823**。如果 1,823 僅佔總樣本的 30%，則代表總樣本需高達 ~6,000 個交易日（約 24 年），但表格中列出的 OOS 期間卻是 "2019/01--2026/04"（恰好約為 1,820 個交易日，亦即這段期間根本是**總樣本**而非 30% 的 OOS）。這代表 In-sample 期間與觀測值完全被隱藏或描述矛盾。
     * TAIFEX TX 的 ON var 比例列為範圍 "27--50"，而其他 ETF 皆為單一數值（如 34.5%）。為什麼 TAIFEX 的夜盤變異數佔比不是一個樣本均值，而是一個範圍？
   * **修改要求**：修正 Table 1，明確列出每個資產的 **In-sample 具體期間與觀測值數量**、**Out-of-sample 具體期間與觀測值數量**，並統一 ON var 比例的計算口徑（皆使用全樣本均值）。

---

#### 💬 MINOR ISSUES (次要問題 — 建議修改以完善論文質量)

7. **【波動度計時策略 (VT Strategy) 未扣除交易成本】**
   * **定位**：`Section 4.4, Table 5 (Lines 263-283)`
   * **問題剖析**：VT 策略未扣除交易成本。由於 PRG 模型運作於 session-level，其換手率（Turnover）相較於日頻率模型可能顯著增加（日盤與夜盤之間的權重動態調整）。雖然作者在 Note 中提到日均換手率介於 4.5% 至 6.6%，但在未扣除交易成本的情況下宣稱 Sharpe ratio 從 1.11 提升至 1.66，在實務上缺乏說服力。
   * **修改要求**：在實證中加入敏感性分析，扣除不同水平的交易成本（例如 0.5 bps, 1 bp, 2 bps 等期貨摩擦成本），展示淨額（Net）Sharpe ratio 與 Sortino ratio，以證實其經濟顯著性在考量摩擦成本後依然存在。

8. **【學術過度宣稱與淡化 HAR 的表現】**
   * **定位**：`Abstract (Lines 39-40)` / `Section 6 (Lines 308-310)`
   * **問題剖析**：作者在摘要與結論中高度宣稱 "PRG model significantly outperforms in all six markets... all exceeding the Harvey threshold"。然而，Table 2 中 PRG vs HAR 在 TAIFEX 上的 DM $t$ 值僅為 **2.63**，並未達到 Harvey (2016) $|t| > 3.0$ 的複式檢定顯著水平。作者在摘要與結論中透過文字遊戲（將主體限縮在 GJR-GARCH）刻意淡化了這一點。對於高頻 RV 數據，PRG 並未能顯著擊敗 HAR。
   * **修改要求**：在摘要與結論中進行更誠實的學術討論，承認在擁有高品質高頻 realized variance 的市場（如 TAIFEX）中，PRG 相較於 HAR 的領先優勢在統計上是不夠顯著的。

9. **【文獻引用不當與缺失】**
   * **定位**：
     * `Line 62`："revealing that previously documented HAR dominance over GJR is largely a target-mismatch artifact..." ➡️ **缺失引用**：是哪些文獻進行了這種不公平的 target-mismatch 對比？必須給出具體的文獻指引。
     * `Line 93`："...quasi-log-likelihood, which produces consistent estimates even under non-Gaussian innovations \citep{Bollerslev1996}." ➡️ **引用錯誤**：證明 QMLE 一致性與漸近正規性的經典文獻是 *Bollerslev and Wooldridge (1992)* 或 *Lumsdaine (1996)*。*Bollerslev and Ghysels (1996)* 是 Periodic GARCH 的開創文獻，並非 QMLE 漸近性質的理論證明來源，此處引用不夠精準。

---

### 總結

這篇論文探討的「夜盤與日盤跨期波動度遞迴橋接」是一個極具實務與學術吸引力的選題。然而，論文目前在**前瞻偏差的防禦**、**關鍵統計表格的符號與邏輯一致性**、**監管指標的計算準確性**以及**實證細節（參數表）的透明度**上存在多處重大盲點。這些問題顯然是之前的同模型自審未能識別的。

建議作者針對上述 **BLOCKING** 與 **MAJOR** 問題進行徹底的實證重新運行與文本修正，以期達到 JBF / FRL 的頂尖學術發表標準。
