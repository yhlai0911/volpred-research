---
paths:
  - "src/volpred/publisher/**"
  - "scripts/enqueue_daily_digest.py"
  - "scripts/check_arc_dedup.py"
  - "scripts/refill_*.py"
---

# Dedup Gate Audit Rule

**Pattern 觸發**：2026-06-23 dedup-gate 8-day 內容黑洞 incident（`docs/error_log.md` line 43-49） — fail-closed default + 無 audit trail，content pipeline 變 invisible black hole。

## 規則本體

任何 publish pipeline 中可 block 內容的 gate（dedup / similarity / arc-overlap / quota / safety），**必須**：

### 1. 寫 audit trail
每次 gate 決策（pass / block / warn）寫到 `storage/logs/dedup_decisions.jsonl`：

```python
import json, datetime
def log_gate_decision(gate_name: str, target_id: str, decision: str, reason: str, score: float | None = None):
    entry = {
        "ts": datetime.datetime.now(datetime.UTC).isoformat(),
        "gate": gate_name,
        "target_id": target_id,
        "decision": decision,  # "pass" | "block" | "warn"
        "reason": reason,
        "score": score,
    }
    with open("storage/logs/dedup_decisions.jsonl", "a") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
```

### 2. 區分 hard-block vs warn-only

- **Hard-block** = 確定重複（byte-for-byte / hash collision / exact title match / 同 K id 同 narrative arc）→ 拒絕 publish
- **Warn-only** = fuzzy 判定（title cosine > 0.85 / narrative arc 重疊 / 主題類似但結論不同）→ 記 log 但 publish 通過

**禁止把 fuzzy 判定當 hard-block** — 寧錯放幾篇可接受重複，不可造成 invisible content gap。

### 3. Default 必須 fail-open

Gate 異常 / 資料缺失 / lookup table 不存在 → 預設 pass + WARN，不可預設 block。

```python
# ❌ 禁止
try:
    is_dup = check_arc_overlap(article)
except Exception:
    return "blocked"  # 8-day black hole 從這來

# ✅ 允許
try:
    is_dup = check_arc_overlap(article)
    decision = "block" if is_dup else "pass"
except Exception as e:
    log_gate_decision("arc_overlap", article.id, "pass", f"gate_error_fail_open: {e}")
    return "pass"  # fail-open，記 log
```

### 4. 每週 audit 一次

`scripts/audit_dedup_gate_decisions.py`（待建）每週掃 `dedup_decisions.jsonl`：
- block rate > 30% → 寄 alert（可能 gate 過鬆變過嚴）
- 連續 N hours 無 pass → critical（black hole 復發）
- 同一 narrative arc block ≥3 次 → review 是否該人工 unlock

## Why

- 2026-06-23 dedup-gate 8 天無新文（feed pool 缺貨）— 老闆抓到才發現 silent block
- 內容 pipeline 是 reader retention + monetization funnel 上游 — 黑洞 = 直接流量損失
- Fail-open + audit trail 是「研究誠實 + 觀察性」的 ops 等價物

## How to apply

- 新建 publish gate → 必含 `log_gate_decision()` 呼叫
- 既有 gate 若不符合此規則 → 補 audit trail（不必一次性改完，逐步補）
- Code review checklist 加一條「gate 決策是否 logged」

歷史 incident: `docs/error_log.md` line 43-49（arc-dedup default-block）；governance_error_log_review_200 sweep Pattern E（2026-06-23）。
