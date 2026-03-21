---
name: latex-academic-reviewer
description: >
  This skill should be used when conducting a comprehensive review of LaTeX academic
  documents (research proposals, journal papers). It covers: logic structure, argument
  quality, model specification, equation derivation, symbol consistency, citation
  completeness, structured review reports, revision with diff reports, PDF compilation,
  and version management.
  Trigger phrases: '審查論文', '審查計畫書', 'review paper', 'review proposal',
  '/latex-academic-reviewer', 'LaTeX review', '學術審查'.
  Trigger situations: after completing a manuscript draft, before submission, or when
  the user requests a formal academic review to improve acceptance probability.
  This skill should NOT be used for: content-level quality checks like claim-evidence
  matching (use finance-paper-quality), citation-only verification (use citation-verifier),
  or publishing to the website feed.
---

# LaTeX 學術文件全面審查與修訂

## 核心理念

**審查目的**：讓研究計畫書更容易通過審查委員評審

審查應從審查委員的角度出發，識別可能導致計畫書被退件或降低評分的問題。

## 工作流程與 Todo List

執行審查時**必須**使用 TodoWrite 工具建立以下步驟清單：

```
審查階段 Todo List：
1. [pending] 審查研究動機與問題陳述
2. [pending] 審查文獻回顧完整性
3. [pending] 審查研究缺口與貢獻宣稱
4. [pending] 審查理論模型設定
5. [pending] 審查方程式與推導
6. [pending] 審查符號定義一致性
7. [pending] 審查研究方法可行性
8. [pending] 審查資料與樣本設計
9. [pending] 審查預期成果合理性
10. [pending] 審查專有名詞引用
11. [pending] 審查參考文獻完整性
12. [pending] 審查文字表述與邏輯
13. [pending] 產生審查報告
```

每完成一個步驟，立即更新 todo 狀態為 completed，並記錄發現的問題。

---

## 版本命名規則

| 類型 | 格式 | 範例 |
|------|------|------|
| 主版本 | `name_v{X.Y}.tex` | `paper_v4.4.tex` |
| 修訂版 | `name_v{X.Y.Z}.tex` | `paper_v4.4.1.tex` |
| 審查報告 | `name_v{X.Y.Z}_review.tex` | `paper_v4.4.2_review.tex` |
| 差異檔 | `name_v{A}_to_v{B}_diff.tex` | `paper_v4.4_to_v4.4.1_diff.tex` |

- X = 重大架構變更
- Y = 內容修訂
- Z = 格式/符號/引用修正

**微小修訂規則**：若修訂極微小（如刪除數字、修正錯字），不建立新版本號，直接修改當前版本並將修訂內容追加至現有差異報告。

---

## 階段一：全面學術審查

### 審查維度總覽

| 維度 | 審查重點 | 常見問題 |
|------|----------|----------|
| A. 邏輯結構 | 論述連貫性、因果關係 | 跳躍推論、循環論證 |
| B. 研究動機 | 問題重要性、研究必要性 | 動機薄弱、缺乏說服力 |
| C. 文獻回顧 | 完整性、批判性分析 | 遺漏關鍵文獻、堆砌引用 |
| D. 研究缺口 | 缺口識別、貢獻宣稱 | 缺口不明確、貢獻誇大 |
| E. 模型設定 | 假設合理性、識別條件 | 假設過強、識別不足 |
| F. 方程式推導 | 數學正確性、推導完整 | 推導跳步、符號錯誤 |
| G. 研究方法 | 可行性、嚴謹性 | 方法不當、缺乏穩健性 |
| H. 資料設計 | 樣本代表性、資料品質 | 樣本偏誤、資料不足 |
| I. 預期成果 | 合理性、具體性 | 過度承諾、成果模糊 |
| J. 引用規範 | 格式正確、收錄完整 | 引用缺漏、格式不一 |

---

### A. 邏輯結構審查

**審查要點**：
1. 整體論述是否形成完整的邏輯鏈條
2. 段落之間是否有適當的轉承
3. 是否存在跳躍推論或循環論證
4. 結論是否由前提充分支持

**常見問題**：
- 「因此」「所以」前後缺乏因果關係
- 研究問題與方法之間缺乏邏輯連結
- 貢獻宣稱與實際研究內容不匹配

**檢查清單**：
```
[ ] 研究動機 → 研究問題 邏輯連貫
[ ] 文獻回顧 → 研究缺口 推導合理
[ ] 研究缺口 → 研究目標 對應明確
[ ] 研究目標 → 研究方法 設計恰當
[ ] 研究方法 → 預期成果 推論合理
```

---

### B. 研究動機審查

**審查要點**：
1. 研究問題是否具有學術或實務重要性
2. 是否清楚說明為何需要進行此研究
3. 是否有具體數據或案例支持問題的重要性

**常見問題**：
- 僅陳述現象，未說明為何重要
- 動機過於籠統，缺乏具體性
- 未連結到學術或實務需求

**評分標準**（審查委員角度）：
- 優：問題重要、動機明確、有數據支持
- 可：問題合理、動機存在但不夠強烈
- 差：問題瑣碎、動機薄弱、缺乏說服力

---

### C. 文獻回顧審查

**審查要點**：
1. 是否涵蓋該領域的關鍵文獻
2. 是否有批判性分析而非僅堆砌引用
3. 是否清楚呈現文獻的演進脈絡
4. 是否識別現有文獻的限制

**常見問題**：
- 遺漏領域內的經典或重要文獻
- 僅列舉文獻，缺乏綜合分析
- 文獻組織混亂，缺乏邏輯結構
- 引用過時文獻而忽略最新研究

**必須引用檢查**：
- 方法論原創文獻（如 GARCH → Engle, 1982）
- 該領域的奠基性研究
- 最新的相關研究（近 3-5 年）
- 台灣市場相關的本土研究（若適用）

---

### D. 研究缺口與貢獻審查

**審查要點**：
1. 研究缺口是否從文獻回顧中自然導出
2. 缺口是否真實存在且值得填補
3. 貢獻宣稱是否與實際研究內容匹配
4. 貢獻是否具有學術或實務價值

**常見問題**：
- 缺口表述模糊（如「較少研究」）
- 貢獻宣稱過於誇大
- 貢獻與現有文獻的區別不明確
- 宣稱的貢獻在方法論中未被實現

**檢查公式**：
```
貢獻宣稱 = 文獻限制 + 本研究突破
每項貢獻必須有對應的方法論支撐
```

---

### E. 模型設定審查

**審查要點**：
1. 模型假設是否合理且有文獻支持
2. 參數是否可識別（identification）
3. 是否討論假設違反的影響
4. 是否提供穩健性檢驗設計

**常見問題**：
- 假設過強但未討論其影響
- 參數識別條件不明確
- 缺乏穩健性分析設計
- 模型選擇缺乏理論依據

**識別性檢查**：
```
參數數量 ≤ 動差條件數
Jacobian 矩陣是否滿秩
是否存在弱識別風險
```

---

### F. 方程式與推導審查

**審查要點**：
1. 數學形式是否正確
2. 推導步驟是否完整（無跳步）
3. 符號是否首次出現時定義
4. 公式編號是否正確引用

**常見問題類型**：
| 類型 | 範例 |
|------|------|
| 邊界條件錯誤 | CDF 邊界 $\neq$ 0 或 1 |
| 維度不匹配 | 矩陣乘法維度錯誤 |
| 符號衝突 | 同一符號代表不同意義 |
| 引用錯誤 | 公式編號指向錯誤公式 |
| 推導跳步 | 關鍵步驟省略 |

**符號定義檢查**：
- 每個符號首次出現時是否有定義
- 相同符號是否全文一致
- 是否有符號衝突（如 $\rho$ 同時代表相關係數和譜半徑）

---

### G. 研究方法審查

**審查要點**：
1. 方法是否適合回答研究問題
2. 估計方法是否有文獻支持
3. 是否說明方法的優缺點
4. 是否設計穩健性分析

**常見問題**：
- 方法與研究問題不匹配
- 缺乏方法論的理論依據
- 未討論方法的限制
- 穩健性分析不足

**穩健性檢驗設計**：
```
[ ] 替代模型設定
[ ] 替代估計方法
[ ] 子樣本分析
[ ] 參數敏感度分析
[ ] 異常值處理
```

---

### H. 資料與樣本設計審查

**審查要點**：
1. 資料來源是否可靠且可取得
2. 樣本期間是否足夠且合理
3. 樣本外期間設計是否恰當
4. 是否討論資料限制

**常見問題**：
- 樣本期間過短
- 未說明資料處理方法
- 樣本外期間設計不當
- 忽略資料品質問題

**數據一致性檢查**：
- 文中數字是否前後一致
- 計算是否正確（如觀測數 = 時間 ÷ 頻率）
- 百分比是否加總正確

---

### I. 預期成果審查

**審查要點**：
1. 預期成果是否具體可衡量
2. 成果是否與研究目標對應
3. 時程規劃是否合理
4. 是否有過度承諾

**常見問題**：
- 成果描述過於籠統
- 承諾發表在超出能力範圍的期刊
- 時程過於樂觀
- 成果與目標不對應

**合理性檢查**：
```
目標期刊 ABS 等級是否合理
時程是否包含緩衝
成果數量是否實際可達
```

---

### J. 引用規範審查

**首次引用規則**：
- 三位作者以內：首次列出所有作者
- 四位作者以上：首次列出首位作者 et al.
- 後續引用：一律使用 et al.

**參考文獻檢查**：
```
[ ] 正文引用 → 參考文獻有收錄
[ ] 參考文獻 → 正文有引用（無孤兒文獻）
[ ] DOI 是否正確
[ ] 格式是否一致
```

---

## 審查報告模板

審查報告必須是可編譯的 LaTeX 文件：

```latex
\documentclass[12pt,a4paper]{article}

\usepackage[top=2cm, bottom=2cm, left=2cm, right=2cm]{geometry}
\usepackage{fontspec}
\setmainfont{Times New Roman}
\usepackage{xeCJK}
\setCJKmainfont{DFKai-SB}
\usepackage{xcolor}
\usepackage{booktabs}
\usepackage{longtable}
\usepackage{amssymb}

\definecolor{errorred}{RGB}{200,0,0}
\definecolor{warncolor}{RGB}{180,100,0}
\definecolor{okgreen}{RGB}{0,128,0}

\begin{document}

\begin{center}
{\Large\bfseries 學術審查報告}\\[0.5em]
{\large [文件名稱]}\\[0.5em]
{\normalsize 文件類型：[國科會研究計畫/期刊論文/...]}\\
{\normalsize 審查日期：YYYY-MM-DD}\\
{\normalsize 審查標準：嚴格}
\end{center}

\section*{審查摘要}

\begin{tabular}{ll}
\textcolor{errorred}{嚴重問題（須修正）} & N 項 \\
\textcolor{warncolor}{中度問題（建議修正）} & N 項 \\
輕微問題（可選修正） & N 項 \\
整體評估 & [優/良/可/待改進] \\
\end{tabular}

\section*{一、邏輯結構審查}
% 論述連貫性、因果關係、結構完整性

\section*{二、研究動機與貢獻審查}
% 問題重要性、缺口識別、貢獻合理性

\section*{三、文獻回顧審查}
% 完整性、批判性、組織結構

\section*{四、模型設定審查}
% 假設合理性、識別條件、穩健性設計

\section*{五、方程式與推導審查}
% 數學正確性、推導完整性、符號定義

\section*{六、研究方法審查}
% 方法適切性、可行性、嚴謹性

\section*{七、資料與樣本審查}
% 資料來源、樣本設計、數據一致性

\section*{八、預期成果審查}
% 合理性、具體性、時程規劃

\section*{九、引用規範審查}
% 首次引用格式、參考文獻完整性

\section*{十、具體問題清單}

\subsection*{\textcolor{errorred}{嚴重問題}}
% 必須修正的問題

\subsection*{\textcolor{warncolor}{中度問題}}
% 建議修正的問題

\subsection*{輕微問題}
% 可選修正的問題

\section*{總結與建議}

\textbf{整體評估}：[詳細評語]

\textbf{修訂優先順序}：
\begin{enumerate}
\item [最優先修正項目]
\item [次優先修正項目]
\item ...
\end{enumerate}

\end{document}
```

---

## 階段二：修訂

### 流程

```bash
# 1. 審查後編譯審查報告 PDF
xelatex -interaction=nonstopmode doc_v4.4_review.tex

# 2. 建立新版本
cp doc_v4.4.tex doc_v4.4.1.tex

# 3. 修訂新版本（保留原版本不變）

# 4. 建立差異對照 LaTeX 文件

# 5. 編譯所有 PDF
xelatex -interaction=nonstopmode doc_v4.4.tex
xelatex -interaction=nonstopmode doc_v4.4.1.tex
xelatex -interaction=nonstopmode doc_v4.4_to_v4.4.1_diff.tex
```

---

## 階段三：差異報告

差異對照檔模板：

```latex
\documentclass[12pt,a4paper]{article}
\usepackage[top=2cm, bottom=2cm, left=2cm, right=2cm]{geometry}
\usepackage{fontspec}
\setmainfont{Times New Roman}
\usepackage{xeCJK}
\setCJKmainfont{DFKai-SB}
\usepackage{xcolor}
\usepackage{booktabs}
\definecolor{addgreen}{RGB}{0,128,0}
\definecolor{delred}{RGB}{200,0,0}

\begin{document}
\begin{center}
{\Large\bfseries 版本差異對照報告}\\
{\large v{A} $\rightarrow$ v{B}}\\
{\normalsize 修訂日期：YYYY-MM-DD}
\end{center}

\section*{修訂摘要}
[簡述本次修訂重點]

\section*{修訂內容}
\subsection*{一、[修訂類別]}
\textbf{位置：}[行號/章節]
\textbf{原文：}
\begin{quote}
\textcolor{delred}{[刪除文字]}
\end{quote}
\textbf{修正後：}
\begin{quote}
\textcolor{addgreen}{[新增文字]}
\end{quote}
\textbf{修正理由：}[說明]

\section*{修訂項目對照表}
\begin{tabular}{|p{3cm}|p{5cm}|p{5cm}|}
\hline
\textbf{議題} & \textbf{v{A}} & \textbf{v{B}} \\
\hline
... & ... & ... \\
\hline
\end{tabular}

\section*{檔案資訊}
\begin{tabular}{ll}
原版本： & \texttt{name\_v{A}.tex} \\
修正版： & \texttt{name\_v{B}.tex} \\
審查報告： & \texttt{name\_v{A}\_review.tex} \\
頁數變化： & X 頁 $\rightarrow$ Y 頁 \\
\end{tabular}
\end{document}
```

顏色標記：
- \textcolor{addgreen}{綠色} = 新增內容
- \textcolor{delred}{紅色} = 刪除內容

---

## 審查委員常見退件理由

審查時應特別注意以下可能導致退件的問題：

1. **研究動機薄弱**：未說明為何此研究重要
2. **文獻回顧不足**：遺漏關鍵文獻或缺乏批判分析
3. **貢獻不明確**：無法清楚區分與現有研究的差異
4. **方法不當**：研究方法與問題不匹配
5. **可行性存疑**：時程、資源、技術能力不足
6. **過度承諾**：預期成果超出合理範圍
7. **邏輯不連貫**：論述跳躍、前後矛盾
8. **細節錯誤**：公式錯誤、符號未定義、引用缺漏

---

## 注意事項

- 原版本保持不變
- PDF 編譯使用 xelatex（支援中文）
- 修改 tex 必須同步編譯 PDF
- 每個審查步驟完成後立即更新 TodoWrite
- 審查報告應提供具體、可操作的修訂建議
