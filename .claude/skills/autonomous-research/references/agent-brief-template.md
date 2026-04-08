# Agent Brief Template

**每個 agent prompt 必須填寫此模板。不可省略任何段落。**

主線程負責填寫 WHY 和 CONTEXT，確保 agent 知道為什麼要做這件事。
Agent 完成後，主線程根據動機和結果做解讀，不是照搬 agent 的結論。

---

## 任務（WHAT）

[具體要做什麼——明確的實驗設計、模型、數據、評估指標]

## 動機（WHY）

[為什麼要做這個實驗？至少回答以下問題：]
- 這個實驗要回答什麼問題？
- 跟哪些先前實驗相關？（引用 K 編號和結論）
- 如果結果是正面/負面，分別代表什麼？
- 用戶的關切是什麼？（如果有）

## 此實驗特有的約束

[只列「這次實驗」需要特別注意的規則，不重複 preamble 的通用規則]
[通用方法論（模型-target 匹配、統計門檻、防錯規則）已在 experiment-preamble.md 中，不需重複]

例：
- 此實驗用 0050.TW → 必須 `clean_tw50_data`（preamble 沒有這條，是資產特有的）
- 此實驗做期貨避險 → 注意 roll gap 處理（preamble 第 4 節有，但此處強調因為本實驗會碰到）
- 此實驗的 baseline 是 K687 的 BH 50/50（Sharpe 0.545）→ 超過 1.09 就可疑

## 成功標準

[怎樣算做完？怎樣算異常需回報？]

例：
- 完成：產出 results.json + 至少 1 張圖表 + README.md
- 異常：Sharpe > 2x baseline、parameter 在邊界上、HE < 0
- 失敗：數據不足 (<252 日)、模型不收斂

## 相關知識

[引用相關 K 編號和結論，讓 agent 建立在已有基礎上]

例：
- K849：HAR-RV 在 RV target 上勝 GJR（DM t=-11.14）——預期結果
- K847：隔夜 gap 61% 可交易
- K687：正確 lag 後沒有 VT 策略打敗 BH 50/50

## 必讀文件

[列出 agent 必須讀取的檔案路徑]

- `.claude/skills/autonomous-research/references/experiment-preamble.md`（通用方法論規則——模型-target 匹配、統計門檻、防錯規則。此模板的「特有約束」是補充，不是替代）
- [其他相關的 skill 或參考文件路徑]

---

**本模板與 experiment-preamble.md 的關係：**
- **Preamble**（靜態）= agent 必須遵守的通用方法論規則（不隨實驗變化）
- **Brief**（動態）= 這次實驗的具體任務 + 動機 + 特有約束（每次不同）
- Agent prompt 的結構：`[preamble 全文] + [填好的 brief] + [結尾提醒用 result-template 格式回報]`
