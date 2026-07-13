# 學術審查詳細標準

## 方程式審查

### 常見問題類型

1. **符號未定義**
   - 變數首次出現未說明含義
   - 下標/上標意義不明

2. **數學形式錯誤**
   - 矩陣維度不符
   - 積分/求和範圍錯誤
   - 條件機率符號錯誤

3. **推導邏輯問題**
   - 跳躍過大缺乏中間步驟
   - 假設條件未明確說明

4. **與文獻不一致**
   - 引用公式與原文獻不符
   - 符號慣例與領域標準不同

### 驗證方法

- 手動推導驗證
- 與引用文獻原文對照
- 檢查維度/單位一致性
- 驗證邊界條件

## 符號審查

### 檢查項目

| 項目 | 說明 |
|------|------|
| 首次定義 | 符號首次出現時是否有明確定義 |
| 一致性 | 同一符號全文是否代表相同意義 |
| 衝突 | 不同概念是否使用相同符號 |
| 慣例 | 是否符合領域符號慣例 |

### 常見符號衝突

- $\rho$：相關係數 vs 譜半徑 vs 密度
- $\sigma$：標準差 vs 波動率 vs 應力
- $\alpha$：顯著水準 vs 衰減參數 vs 係數
- $\beta$：迴歸係數 vs 傳染參數

## 縮寫審查

### 首次出現規則（重要！）

**所有縮寫在首次出現時必須寫出全名，並在括號內標註縮寫。**

| 正確寫法 | 錯誤寫法 |
|----------|----------|
| 最小變異避險比率（Minimum-Variance Hedge Ratio, MVHR） | MVHR |
| 廣義動差法（Generalized Method of Moments, GMM） | GMM 估計 |
| 動態條件相關（Dynamic Conditional Correlation, DCC） | DCC-GARCH |

### 後續使用

首次定義後，後續可直接使用縮寫，無需再寫全名。

### 常見需定義的縮寫

- MVHR（Minimum-Variance Hedge Ratio）
- GMM（Generalized Method of Moments）
- OLS（Ordinary Least Squares）
- GARCH（Generalized Autoregressive Conditional Heteroskedasticity）
- DCC（Dynamic Conditional Correlation）
- HAR（Heterogeneous Autoregressive）
- VaR（Value-at-Risk）
- CVaR（Conditional Value-at-Risk）

### 審查檢查清單

- [ ] 所有縮寫首次出現時有完整定義
- [ ] 縮寫定義格式一致（全名在前，縮寫在括號內）
- [ ] 無未定義即使用的縮寫

---

## 引用審查

### 首次引用規則（重要！）

**首次引用某文獻時，必須列出所有作者全名；後續引用方可使用 et al.**

| 情境 | 正確寫法 | 錯誤寫法 |
|------|----------|----------|
| 首次引用（3人以上） | Aït-Sahalia, Cacho-Diaz, and Laeven (2015) | Aït-Sahalia et al. (2015) |
| 後續引用 | Aït-Sahalia et al. (2015) | （可使用 et al.） |
| 首次引用（2人） | Barndorff-Nielsen and Shephard (2006) | Barndorff-Nielsen & Shephard (2006) |
| 首次引用（1人） | Merton (1976) | （無需變化） |

### 專有名詞引用格式

```
方法名稱（Author, Year）
```

或

```
Author (Year) 提出的方法名稱
```

### 必須引用的情況

1. 首次提出的模型/方法
2. 專有名詞/術語
3. 重要公式的原始來源
4. 實證發現/數據

### 檢查清單

- [ ] 首次引用列出所有作者（非 et al.）
- [ ] 專有名詞有引用
- [ ] 引用格式一致（使用 "and" 而非 "&"）
- [ ] 引用在參考文獻中有對應條目
- [ ] 年份/作者名正確

## 公式編號規則

### 良好實踐

- 重要公式獨立編號
- 相關公式使用連續編號
- 避免使用組合編號如 (1-2)
- 交叉引用時確保編號正確

### 編號格式

| 格式 | 使用情境 |
|------|----------|
| (1), (2), (3) | 標準連續編號 |
| (1a), (1b) | 密切相關的子公式 |
| (A.1), (A.2) | 附錄公式 |

## 表格與圖片格式規範

### 標題位置規則（重要！）

| 元素 | 標題位置 | 說明 |
|------|----------|------|
| **表格** | **上方** | `\caption` 置於 `\begin{tabular}` 之前 |
| **圖片** | **下方** | `\caption` 置於 `\includegraphics` 之後 |

### 正確的 LaTeX 表格結構

```latex
\begin{table}[h]
\centering
\caption{表格標題在此}  % ← 標題在 tabular 之前
\small
\begin{tabular}{@{}lcc@{}}
\toprule
...
\bottomrule
\end{tabular}
\end{table}
```

### 正確的 LaTeX 圖片結構

```latex
\begin{figure}[h]
\centering
\includegraphics[width=0.8\textwidth]{figure.pdf}
\caption{圖片標題在此}  % ← 標題在圖片之後
\end{figure}
```

### 常見錯誤

1. **表格標題放在表格下方** ❌
   - 錯誤：`\end{tabular}` 之後才放 `\caption`
   - 正確：`\centering` 之後、`\begin{tabular}` 之前放 `\caption`

2. **圖片標題放在圖片上方** ❌
   - 錯誤：`\includegraphics` 之前放 `\caption`
   - 正確：`\includegraphics` 之後放 `\caption`

### 審查檢查清單

- [ ] 所有表格的 `\caption` 在 `\begin{tabular}` 之前
- [ ] 所有圖片的 `\caption` 在 `\includegraphics` 之後
- [ ] 表格使用 `\caption*{}` 或 `\caption{}` 格式正確
- [ ] 圖表編號連續且正確引用
