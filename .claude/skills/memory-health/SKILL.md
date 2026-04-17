---
name: memory-health
description: >
  記憶系統（knowledge.json、thinking_journal.json 等）的健康檢查與維護。
  防止檔案膨脹、重複累積、格式不一致。2026-04-10 教訓：knowledge.json
  膨脹到 54.5MB（50,304 筆中 96.4% 是重複），根因是 merge_worktree.sh
  的 jq 去重 bug。Trigger: 每週一次自動檢查，或手動觸發。
  Do not use for normal experiment execution or publishing.
user-invocable: true
---

# Memory Health Check

## Scope Boundary

Use this skill for：

- 記憶檔案大小、重複與格式健康檢查
- knowledge / thinking / experience 類檔案維護
- 孤兒 worktree 檢查

Do **not** use this skill for：

- 一般研究與實驗執行 → `autonomous-research`
- 發文與排程 → `feed-publisher` / `admin-ops`

## 定期檢查（建議每週一次）

### 1. 檔案大小監控
```bash
for f in storage/memory/knowledge.json storage/memory/thinking_journal.json \
         storage/memory/experiment_experiences.json storage/memory/experiments.json; do
    size=$(du -h "$f" | cut -f1)
    count=$(python3 -c "import json; print(len(json.load(open('$f'))))" 2>/dev/null)
    echo "$f: $size, $count entries"
done
```

**警戒線**：
| 檔案 | 正常大小 | 警告門檻 | 危險門檻 |
|------|---------|---------|---------|
| knowledge.json | 1-3 MB | > 5 MB | > 10 MB |
| thinking_journal.json | 0.5-2 MB | > 3 MB | > 5 MB |
| experiment_experiences.json | < 100 KB | > 200 KB | > 500 KB |
| experiments.json | < 500 KB | > 1 MB | > 2 MB |

### 2. 重複檢測
```python
import json, hashlib
with open('storage/memory/knowledge.json') as f:
    data = json.load(f)
seen = set()
dups = 0
for e in data:
    h = hashlib.md5(json.dumps(e, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()
    if h in seen:
        dups += 1
    seen.add(h)
print(f"Total: {len(data)}, Duplicates: {dups}, Unique: {len(seen)}")
```
**如果 duplicates > 0 → 立即去重**。

### 3. 格式一致性
兩種格式共存是歷史遺留：
- 舊格式：`{item_id, category, content, evidence, confidence, created_at}`（MemorySystem.add_knowledge 產生）
- 新格式：`{id, type, title, content, confidence, category, tags, experiment_ids, timestamp, source}`（Claude 直接寫入）

目前不需要強制統一，但新增 entry 應一律用新格式。

### 4. 孤兒 worktree 清理
```bash
# 檢查 .claude/worktrees/ 中沒有 .git 的目錄
for d in .claude/worktrees/agent-*; do
    if [ ! -f "$d/.git" ] && [ ! -d "$d/.git" ]; then
        echo "Orphaned: $(basename $d)"
    fi
done
```

## 歷史事件

| 日期 | 問題 | 大小 | 根因 | 修復 |
|------|------|------|------|------|
| 2026-04-10 | knowledge.json 96.4% 重複 | 54.5 MB → 1.4 MB | merge_worktree.sh jq 用 item_id 去重，新格式用 id，null key 導致去重失敗 | 改用 Python content-hash 去重 |
| 2026-03 | 85/124 實驗不在 knowledge.json | N/A | 只存 results JSON 不進知識庫 | CLAUDE.md 強制規定三項產出 |

## 去重腳本（緊急修復用）
```python
import json, hashlib
src = 'storage/memory/knowledge.json'
with open(src) as f:
    data = json.load(f)
seen = set()
unique = []
for e in data:
    h = hashlib.md5(json.dumps(e, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()
    if h not in seen:
        seen.add(h)
        unique.append(e)
with open(src, 'w') as f:
    json.dump(unique, f, indent=2, ensure_ascii=False, default=str)
print(f"Deduped: {len(data)} → {len(unique)}")
```
