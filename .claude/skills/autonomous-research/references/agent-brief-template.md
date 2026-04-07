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

## 已知約束

[從 error_log/preamble 提取的適用規則——明確列出，不要說「參考 error_log」]

例：
- 此實驗需注意的 error log 規則：DM test 用 `strategy_dm_test`、0050.TW 必須 `clean_tw50_data`
- 統計門檻：Harvey (2016) t>3.0
- 模型-Target 匹配：GARCH 用 r² 評估、HAR 用 RV 評估

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

- `.claude/skills/autonomous-research/references/experiment-preamble.md`（方法論規則）
- [其他相關的 skill 或參考文件路徑]
