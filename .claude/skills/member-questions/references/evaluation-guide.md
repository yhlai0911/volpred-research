# 會員問題評分與狀態 Reference

只在有 pending 題目、duplicate branch 或 lifecycle 異常時載入。

## 評分 payload

四個維度各 0–25，總分 0–100：

| 維度 | 高分證據 |
|---|---|
| 研究可行性 | 現有或可取得資料能正式檢驗 |
| 讀者價值 | 回答可泛化成具體決策／教育價值 |
| 研究相關性 | 直接連到波動率、風險、策略或 macro-vol 主軸 |
| 預期影響力 | 能形成有證據的文章或解鎖後續研究 |

客服／帳務、不可驗證問牌、無語意輸入與高度私人的題目不應硬轉成研究文章。

```json
[
  {
    "question_id": "uuid",
    "score": 78,
    "score_breakdown": {
      "研究可行性": 22,
      "讀者價值": 21,
      "研究相關性": 20,
      "預期影響力": 15
    }
  }
]
```

`score` 必須等於 breakdown 加總；維度名稱固定。依 before summary 建立 temporary
evaluation 檔，不把中間 payload 寫進 canonical storage。

## Stable insertion

- 只把本輪 evaluated pending 題插入既有 ranked 序列。
- 既有 ranked 題彼此相對順序保持不變。
- researching 題保持在 ranked 題之前。
- 同分候選遵守 canonical reranker 的 deterministic order。
- mutation receipt 中 `evaluated_count`、`updated_count`、`skipped` 必逐題核對。
- after summary 必驗舊題順序與新題 rank；只看 count 不夠。

## State machines

| Question status | 進入條件 |
|---|---|
| `pending` | 新題，尚未評分 |
| `ranked` | rerank 成功 |
| `researching` | atomic claim 成功 |
| `answered` | 已發佈文章完成正式綁定 |
| `archived` | 正式 archive command + audit reason |

Candidate pool 若出現，遵守其 canonical `queued → claimed → completed/cancelled`
lifecycle；它不是 question status 的替代品。

## Duplicate branches

- `question-claim` 的 duplicate refusal 是正常 gate，不是可忽略錯誤。
- 同題重問：優先把既有 published article 綁給新題。
- 新角度續作：claim 需要 `--allow-duplicate` 與具體 `--new-angle`；publish 需要
  `--supersedes` 列出所有既有 answer article ids。
- 任何 override 都必須在 command receipt／audit trail 可回讀；缺 receipt 不繼續。

## Publish contract

member QA publish 至少包含：

- `--phase member_qa`
- `--audience member_qa`
- `--proposer <會員名稱>`
- `--question-id <uuid>`
- `--status published`

不要添加 live help 不存在的 option。publish gate、圖表、來源、查重與文字品質由
`feed-publisher` 執行；本 skill 只保存 question identity 與 lifecycle。

## Failure boundaries

- claim 後研究失敗：保留可稽核狀態並走正式 remediation，不手改回 ranked。
- publish 未被 public endpoint 回讀：不執行 `question-answer`。
- `question-answer` 回傳 `already_answered`：核對 `existing_articles`；若是同一既有答案，
  視為冪等 skip，不產生第二篇。
- article 不是 published：question 維持 researching，不能人工標 answered。
