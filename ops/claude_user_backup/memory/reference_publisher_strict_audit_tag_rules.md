---
name: feed-publisher strict audit tag rules
description: Publisher 自動把 K-id 從 user-facing tags 剝離到 details.experiment_refs metadata；tag ≤8；禁 t-stat/Harvey/|t| 等統計術語
type: reference
originSessionId: 91283b9e-7227-43f5-88bb-9d92168d243a
---
# feed-publisher Strict Audit Rules

`feed-publisher` skill 的 publisher 在 publish 階段執行 strict audit（SKILL.md L306）— **不是 agent 自由發揮**，是 publisher 自動 enforce 的硬規則。

**Why**：用戶 2026-04-26 規則 update — feed user-facing tags 為 reader-readable 標籤，不該混 K 編號或統計檢定術語（讀者看不懂）；K 編號要保留但歸到 metadata 層（後台 cross-link 用）。

**驗證來源**：2026-04-27 K567 dispatch agent callback 報告（mile_5052651e）+ K908 dispatch agent callback (mile_3eb8657c) 同樣行為 — `details.experiment_refs=["K567"]` / `["K908"]` metadata，user-facing tags 不含 K-id。

## 規則清單

| 規則 | 說明 |
|---|---|
| **Tag count** | ≤8 個 user-facing tags |
| **K-id stripped to metadata** | K567 / K908 等自動從 tag list 剝離 → `details.experiment_refs` array |
| **禁術語** | t-stat / Harvey / \|t\| / DM / Kupiec / Christoffersen 等統計檢定符號類（reader 看不懂）|
| **允許術語** | Basel Trinity / VaR / VT / GARCH / VIX / MF-GJR 等 reader-recognizable 名詞 |
| **語言要求** | tag 用繁中或常見英文縮寫（VIX/VaR/GARCH 等），避免 LaTeX 符號 |

## How to apply

### Brief 撰寫時（next_draft_candidate_k*.md）

❌ **不要這樣寫 brief**：
```
Tags（必填，下次 agent dispatch 時 enforce）：
`K567`, `國際市場`, `VIX`, ...
```

✅ **應這樣寫 brief**：
```
Tags（user-facing ≤8，由 publisher strict audit 自動處理）：
`國際市場`, `VIX`, `波動率目標化`, `跨市場`, `方法論`, `槓桿策略`, `一般讀者`
（K-id 由 publisher 自動歸到 details.experiment_refs metadata，brief 不必列）
```

### Agent dispatch prompt

❌ **不要這樣寫 agent prompt**：
```
tags 必含 `K567`（K908 dispatch 教訓 — 這是錯的判斷）
```

✅ **應這樣寫**：
```
tags ≤8 reader-friendly 名詞，K-id 由 publisher 自動歸 details.experiment_refs，agent 不必特意加 K-id 到 tag list
```

### Verify 階段（agent-result-verification skill）

✅ K-id audit 改查 metadata 不查 tags：
```bash
jq -r '.[] | select(.id == "mile_xxx") | {tags_count: (.tags | length), experiment_refs: .details.experiment_refs}' storage/reports/feed.json
```
- tags_count ≤8 ✓
- experiment_refs 含預期 K-id ✓

## 教訓 reference

- 2026-04-26 K908 dispatch：我誤判 tags 缺 K908 = minor 違規。實際上 mile_3eb8657c experiment_refs=["K908"] metadata 正確
- 2026-04-26 K567 dispatch：我誤判「第二次缺 K-tag = agent enforce 不可靠」。實際上 mile_5052651e experiment_refs=["K567"] metadata 正確 + tags 7 個全 reader-friendly + 統計術語「Harvey/t-stat」用「統計顯著性指標 / 嚴格門檻」白話包裝
- 兩次都不是 agent bug，是我沒讀 publisher SKILL.md L306 strict audit + 沒查 details.experiment_refs metadata

## Anti-pattern

- ❌ Brief tag list 明示 K-id 為 mandatory（與 publisher 規則衝突）
- ❌ Verify 階段只看 user-facing tags 不查 details.experiment_refs metadata
- ❌ 把 t-stat / Harvey 等統計符號塞進 user-facing tags（reader 看不懂）
- ❌ 因 tag 缺 K-id 認定 agent 違規 + 派 follow-up fix（產生 false positive 工作）

## Cross-link

- `.claude/skills/feed-publisher/SKILL.md` L306（strict audit 規則 canonical source）
- `.claude/rules/publishing.md`（feed publish 硬規則）
- 相關 memory：`feedback_website_article_quality_4dim.md`（4 維度標準，不衝突，並行 enforce）
