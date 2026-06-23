---
paths:
  - "scripts/**/*.py"
  - "src/volpred/**/*.py"
  - ".claude/hooks/**/*.py"
---

# No-Silent-Fallback Rule

**THREE-STRIKE TRIGGER**：2026-06-23 governance sweep 發現 127 個 silent fallback instances 跨 68 個 file（audit: `scripts/audit_silent_fallbacks.py --json`），相關 incident 散見 `docs/error_log.md` 2026-06-22/23 entries 35+ 條。屬於「同類 root cause 重複出現」結構性缺陷。

## 規則本體

**Fail-open（保持運作）和 silent（不記錄）是兩個正交維度**。Fail-open 是合法的 ops 策略，silent 不是。

任何 `except` block 若 swallow exception 並 return 一個 default（含 `continue` / `pass` / `return None` / `return []` / `return False` / sentinel），**必須**在 return / continue / pass 之前留下可觀測 trace：

```python
# ❌ 禁止：silent fallback
try:
    parsed = json.loads(raw)
except Exception:
    continue  # 沒人知道 raw 壞了

# ❌ 禁止：bare pass
try:
    do_thing()
except Exception:
    pass

# ✅ 允許：log + fallback
try:
    parsed = json.loads(raw)
except Exception as e:
    logging.warning("parse_raw_failed: %s | raw_head=%s", e, raw[:80])
    continue

# ✅ 允許：用共用 helper（推薦）
from volpred.ops.diagnostics import warn
try:
    parsed = json.loads(raw)
except Exception as e:
    warn("parse_raw", "json decode failed", err=str(e), head=raw[:80])
    continue
```

## 例外（合法 silent，必須註解）

只有以下情境可以 silent，且**必須**有 `# silent-ok: <reason>` inline comment 標記，否則 audit 視為違規：

1. **Best-effort cleanup**（finally / context exit）— 清理失敗不影響主流程
   ```python
   try:
       os.unlink(tmp_path)
   except FileNotFoundError:
       pass  # silent-ok: cleanup race-safe
   ```

2. **Defensive imports**（optional dependency probing）
   ```python
   try:
       import optional_module
   except ImportError:
       optional_module = None  # silent-ok: optional dep
   ```

3. **Test fixtures / mocks**（test code only）

## Gate / CI

- **Audit script**: `scripts/audit_silent_fallbacks.py --json`
- **Lint enforcement**: 新增 `scripts/audit_silent_fallbacks.py --strict --baseline storage/qa/silent_fallback_baseline.json`，CI 跑；超過 baseline = exit 1。
- **Baseline 機制**：既有 127 instances 凍結為 baseline（不強制即時清理，避免 big-bang）；新增 silent fallback 必 fail。
- **Baseline 縮減 SOP**：每月 governance task 排一次 `audit --strict --reduce-by 20`，把 baseline 從 127 → 107 → 87 → ... 漸進降到 0。

## 共用 helper

統一使用 `src/volpred/ops/diagnostics.py`（**待建**，governance_error_log_review_200 followup task）的 `warn(tag, msg, **ctx)`：
- 自動 timestamp + level + tag prefix
- 寫 stderr + 可選 `storage/logs/diagnostics/<tag>.jsonl` 持久化
- 各 script 不要自己寫 `_warn_<module>()` helper（散落 30+ 處，格式不一）

## Why（不要刪除這段）

Silent fallback 在開發階段看似「ops 友善」，運營階段是**最大的 invisible failure source**：
- 2026-06-22 gmail-poll IMAP hang 4 天 — 100% failure 但無 alert（task pipeline 被動 status terminal set 漏 awaiting_*，per `feedback_audit_no_passive_terminal`）
- 2026-06-23 dedup gate 8-day 內容黑洞 — fail-closed default + 無 audit trail
- 2026-06-22/23 35+ entries 都來自「except 沒 log」這一類

「先 log 再 fallback」是極低成本的 invariant — 一行 `logging.warning(...)`。沒有理由不做。

## How to apply

- 任何 `except` block 寫之前先想：「caller 怎麼知道我 swallow 了 exception？」答不出來 = 必須 log
- Code review / Codex review 加 checklist 一條「bare except 是否有 log」
- 新建 ops script 預設 `from volpred.ops.diagnostics import warn`（待 module 建好後加入 cookiecutter template）

歷史 incident: `docs/error_log.md` 2026-06-22 ~ 2026-06-23 silent fallback batch fix entries（line 59-598 多筆）；governance_error_log_review_200 sweep report (2026-06-23)。
