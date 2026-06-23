---
paths:
  - ".claude/hooks/**"
  - "scripts/cron_*.sh"
  - "scripts/launchagent_wrapper_*.sh"
---

# Hooks / Wrapper Exit-Code Rule

**THREE-STRIKE TRIGGER**：2026-06-23 同一 session 3 次發現 hook / wrapper 把 shell pipeline exit code 當作 tool outcome（pytest false-green），詳見 `docs/error_log.md` line 23-41。

## 規則本體

**Shell pipeline / `; echo` chain / tee 的 exit code ≠ tool 本身的成功失敗。**

任何 hook 或 wrapper 若 summarize 另一個 tool 的 outcome（pytest / mypy / eslint / xelatex / npm test 等），**必須 parse tool 自己的 summary 或 exit marker**，不可只看 `$?`：

```bash
# ❌ 禁止：pipeline 尾端 exit code 不代表 pytest 結果
uv run pytest tests/ | tee /tmp/out.log
if [ $? -eq 0 ]; then echo "PASS"; fi  # tee 成功 → 永遠 PASS

# ❌ 禁止：grep 結尾接管 exit code
uv run pytest tests/ | grep -E "passed|failed"
# 上面 exit = grep 的 exit，不是 pytest 的

# ✅ 允許：PIPESTATUS（bash）
set -o pipefail
uv run pytest tests/ | tee /tmp/out.log
rc=${PIPESTATUS[0]}
if [ "$rc" -eq 0 ]; then echo "PASS"; fi

# ✅ 允許：parse tool summary
uv run pytest tests/ --tb=no -q > /tmp/out.log 2>&1
rc=$?
if grep -qE "^[0-9]+ passed" /tmp/out.log && [ "$rc" -eq 0 ]; then
  echo "PASS"
fi

# ✅ 允許：tool 提供的 JUnit XML / JSON 報告
uv run pytest tests/ --junit-xml=/tmp/junit.xml
python -c "import xml.etree.ElementTree as ET; ..." /tmp/junit.xml
```

## LaunchAgent / cron wrapper 強制 banner

任何 LaunchAgent 包的 shell script，**必須**在 stdout（會被 `StandardOutPath` 收）emit：

```bash
echo "[wrapper $(date '+%H:%M:%S')] STARTED label=$LABEL pid=$$"
trap 'echo "[wrapper $(date +%H:%M:%S)] EXIT rc=$?"' EXIT

# 主流程
do_work
```

理由：2026-06-22 gmail-poll incident — script-internal log 顯示「last run 成功」但實際 SIGALRM kill；運營者讀 internal log 誤判「scheduler 沒 fire」。launchd 的 `StandardOutPath` 是唯一可信來源 — wrapper banner 讓它可讀。

## Gate / CI

- 新 hook PR：reviewer 必看「exit code 來源是否為 tool 本身」
- 新 LaunchAgent wrapper：必含 STARTED / EXIT banner（grep `\[wrapper.*STARTED` 為 self-test）

## Why

Hook 騙過 review = 紀律失效。`run-compact-bash.sh` 把 SyntaxError 當 PASS、`pretooluse-bash-optimizer.sh` 同類問題、dedup-gate session 也同類 — 3 次都在同一週發生。`docs/error_log.md` 已留教訓。

## How to apply

- 任何 hook 處理 pytest / lint / build / compile tool → 不可只看 `$?`
- 用 `set -o pipefail` + `PIPESTATUS` 或解析 tool 自己的 summary
- LaunchAgent wrapper 永遠先 emit banner，最後 trap EXIT 記 rc

歷史 incident: `docs/error_log.md` line 23-41（hook exit-code masking），line 539-559（gmail-poll 雙 log 診斷）。
