---
paths:
  - "src/volpred/publisher/**"
  - "scripts/enqueue_daily_digest.py"
  - "scripts/check_arc_dedup.py"
  - "scripts/refill_*.py"
---

# Dedup Gate Audit Rule

**Pattern 觸發**：2026-06-23 dedup-gate 8-day 內容黑洞 incident（`docs/error_log_archive/2026-Q2.md` 2026-06-23 entry；索引見 error_log.md §E） — fail-closed default + 無 audit trail，content pipeline 變 invisible black hole。

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

- **Hard-block** = 確定重複（byte-for-byte / hash collision / canonical exact identity）→ 拒絕 publish
- **Warn-only** = fuzzy 判定（title cosine > 0.85 / narrative arc 重疊 / 主題類似但結論不同）→ 記 log 但 publish 通過

**禁止把 fuzzy 判定當 hard-block** — 寧錯放幾篇可接受重複，不可造成 invisible content gap。

事件文章的 canonical exact identity 是 `event_key + event_series_slot`。同一事件的
T-7／T-2／T+0／T+1 是不同資訊狀態；同標題、同 K、同 narrative arc 或跨期 FOMC
相似都只能 warn。缺少完整事件 identity 的 live publish 應由 metadata contract
fail-closed，而不是退回標題猜測。此 invariant 必須同時存在於 canonical feed append
鎖內與 draft/scheduled → published promotion；只在入口 precheck 驗證不算完成。

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

### 4. 持續 audit（已實作，2026-07-20 WS-F2）

裁決 owner = `src/volpred/ops/dedup_gate_audit.py::audit_dedup_decisions`（7 天窗）：
- block rate > 30%（≥10 筆決策才計）→ warn（可能 gate 過鬆變過嚴）
- 連續 24h 無 pass 且 gate 有在 block → **critical**（black hole 復發特徵；純 idle 不算，交給 publishing_freshness）
- 同一 narrative arc block ≥3 次 → warn（review 是否該人工 unlock）
  - 此處「次數」指 **≥3 個不同 candidate identity** 被擋；同一 `target_id`／
    `candidate_id` 或同一正規化標題的 retry、replay、人工 probe 只算一個候選。
    Raw block rows 仍保留在 verdict 的 `blocks`，告警判定與文案使用
    `distinct_candidates`，不得以去重掩蓋 block-rate 或 no-pass black hole。

Alert 出口 = `volpred.ops.alerts._parse_dedup_gate_health_state`（condition id `dedup_gate_health`，掛在 `build_alert_condition_report` registry，hourly check_alerts 自動掃，單一 alert owner per `.claude/rules/alert.md`）。手動 / cron 檢視：`uv run python scripts/audit_dedup_gate_decisions.py`（healthy → exit 0，任一條 breach → exit 1）。Regression gate：`tests/test_dedup_gate_audit.py`。

### 5. Lock / gate lifecycle（PDCA + loop + graph）

任何曾造成 incident、或在觀察窗內高頻觸發的 hard lock，不能只留一行 error log：

- **Plan**：登記 `gate_id`、owner、保護的 invariant、graph 上被保護的 node/edge、
  block 後會切斷的 downstream edges、預期收益與可接受 false-positive 上限。
- **Do**：新 heuristic 先 shadow／warn；只有 canonical exact identity 可直接 hard-block。
- **Check**：決策紀錄必含 stable candidate identity，並回接下游 outcome（published、
  superseded、missed deadline、sequence coverage gap、人工 waiver／retry）。只統計
  gate 觸發率、不看被切斷的結果，不算 closed loop。
- **Act**：達到 review threshold 時產生單一 review item；結論只能是 retain、
  recalibrate、downgrade-to-warn 或 retire，並附 live read-back。不得讓同一 gate
  永久留在「再觀察」。

全域 lock/gate inventory 與跨 log outcome join 應由單一 Operations Core auditor
擁有；本 dedup audit 是其中已上線的內容子圖，不得另建平行 pending queue。

## Why

- 2026-06-23 dedup-gate 8 天無新文（feed pool 缺貨）— 老闆抓到才發現 silent block
- 內容 pipeline 是 reader retention + monetization funnel 上游 — 黑洞 = 直接流量損失
- Fail-open + audit trail 是「研究誠實 + 觀察性」的 ops 等價物

## How to apply

- 新建 publish gate → 必含 `log_gate_decision()` 呼叫
- 既有 gate 若不符合此規則 → 補 audit trail（不必一次性改完，逐步補）
- Code review checklist 加一條「gate 決策是否 logged」

歷史 incident: `docs/error_log_archive/2026-Q2.md` 2026-06-23（arc-dedup default-block；索引 §E）；governance_error_log_review_200 sweep Pattern E（2026-06-23）。
