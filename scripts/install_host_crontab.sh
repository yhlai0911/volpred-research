#!/bin/bash
# install_host_crontab.sh
#
# Rebuild the host crontab's volpred-managed section from
# config/runtime_schedules.json (system_crontab.items).
#
# Design notes:
# - Single `crontab <file>` call per invocation (minimises macOS TCC prompts).
# - Idempotent: running twice is a no-op if config is unchanged.
# - Preserves all non-volpred crontab entries (anything without "# volpred-").
# - Items with "host_crontab_managed": false are skipped (e.g. scheduler_tick).
# - The generated entry format is:
#     <cron> <wrapper_abs> >> <repo>/<log_path> 2>&1 # volpred-<id>
#   where <wrapper_abs> is the config's `wrapper_script` if absolute, else
#   resolved relative to REPO_ROOT.
#
# FDA / macOS TCC note (2026-04-19):
#   Wrapper scripts MUST live in ~/.volpred/bin/ (non-protected path). Wrappers
#   under Desktop/ are blocked by macOS TCC when cron daemon tries to exec them
#   (Operation not permitted), even though cron can read & write inside Desktop.
#   Config therefore stores absolute `/Users/<u>/.volpred/bin/cron_*.sh` paths.
#
# - Wrapper scripts own all the complex shell setup, so crontab entries never
#   need to be edited just because a command changes.
#
# Usage:
#   bash scripts/install_host_crontab.sh          # install
#   bash scripts/install_host_crontab.sh --dry-run  # print plan only
#   bash scripts/install_host_crontab.sh --diff     # show diff vs current

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONFIG_PATH="${REPO_ROOT}/config/runtime_schedules.json"
HEADER="# volpred canonical system crontab (config/runtime_schedules.json)"

DRY_RUN=0
SHOW_DIFF=0
for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=1 ;;
    --diff)    SHOW_DIFF=1 ;;
    -h|--help)
      sed -n '1,30p' "${BASH_SOURCE[0]}"
      exit 0
      ;;
    *) echo "Unknown arg: $arg" >&2; exit 2 ;;
  esac
done

if [[ ! -f "$CONFIG_PATH" ]]; then
  echo "ERROR: config not found: $CONFIG_PATH" >&2
  exit 1
fi

if ! command -v jq >/dev/null 2>&1; then
  echo "ERROR: jq is required (brew install jq)" >&2
  exit 1
fi

# Build the volpred block (deterministic, sorted by config order).
build_volpred_block() {
  echo "$HEADER"
  jq -r '
    .system_crontab.items[]
    | select(.host_crontab_managed != false)
    | select(.wrapper_script != null)
    | [.cron, .wrapper_script, .log_path, .id] | @tsv
  ' "$CONFIG_PATH" | while IFS=$'\t' read -r cron wrapper log_path id; do
    # Absolute path → use as-is; relative → resolve against REPO_ROOT.
    # (Absolute paths are required for host-cron wrappers to sit in
    # ~/.volpred/bin/ and avoid macOS TCC FDA blocks on Desktop/.)
    if [[ "$wrapper" = /* ]]; then
      wrapper_abs="$wrapper"
    else
      wrapper_abs="${REPO_ROOT}/${wrapper}"
    fi
    if [[ ! -x "$wrapper_abs" ]]; then
      echo "ERROR: wrapper not executable: $wrapper_abs" >&2
      exit 1
    fi
    if [[ -z "$log_path" || "$log_path" == "null" ]]; then
      log_path="storage/logs/cron/${id}.log"
    fi
    log_abs="${REPO_ROOT}/${log_path}"
    mkdir -p "$(dirname "$log_abs")"
    echo "${cron} ${wrapper_abs} >> ${log_abs} 2>&1 # volpred-${id//_/-}"
  done
}

# Capture current crontab (empty string if none).
CURRENT="$(crontab -l 2>/dev/null || true)"

# Strip old volpred section: drop header line + any line ending with "# volpred-*".
STRIPPED="$(printf '%s\n' "$CURRENT" | awk '
  /^# volpred canonical system crontab/ { next }
  /# volpred-[A-Za-z0-9-]+$/            { next }
  { print }
')"

NEW_VOLPRED="$(build_volpred_block)"

# Compose the final crontab: preserved entries, then a blank line (if any), then volpred.
if [[ -n "$STRIPPED" ]]; then
  # Trim trailing blank lines from STRIPPED, then one blank separator.
  STRIPPED_TRIMMED="$(printf '%s\n' "$STRIPPED" | awk 'BEGIN{n=0} {a[n++]=$0} END{while(n>0 && a[n-1]=="") n--; for(i=0;i<n;i++) print a[i]}')"
  if [[ -n "$STRIPPED_TRIMMED" ]]; then
    FINAL="${STRIPPED_TRIMMED}"$'\n\n'"${NEW_VOLPRED}"
  else
    FINAL="$NEW_VOLPRED"
  fi
else
  FINAL="$NEW_VOLPRED"
fi

# Ensure trailing newline.
FINAL="${FINAL}"$'\n'

if [[ "$SHOW_DIFF" -eq 1 ]]; then
  echo "=== diff (current -> proposed) ==="
  diff <(printf '%s' "$CURRENT") <(printf '%s' "$FINAL") || true
  echo "=== end diff ==="
  # --diff is diff-only; never writes crontab.
  exit 0
fi

# Idempotent short-circuit: if nothing would change, skip crontab write.
if [[ "$CURRENT" == "${FINAL%$'\n'}" || "$CURRENT" == "$FINAL" ]]; then
  echo "[install_host_crontab] no changes (crontab already canonical)"
  exit 0
fi

if [[ "$DRY_RUN" -eq 1 ]]; then
  echo "=== DRY RUN: proposed crontab ==="
  printf '%s' "$FINAL"
  echo "=== end DRY RUN ==="
  exit 0
fi

TMP="$(mktemp -t volpred_crontab.XXXXXX)"
trap 'rm -f "$TMP"' EXIT
printf '%s' "$FINAL" > "$TMP"

# Single crontab call to minimise TCC prompts on macOS.
crontab "$TMP"

echo "[install_host_crontab] crontab updated; verifying..."
VERIFY="$(crontab -l 2>/dev/null || true)"
if [[ "$VERIFY" != "${FINAL%$'\n'}" && "$VERIFY" != "$FINAL" ]]; then
  echo "[install_host_crontab] WARNING: post-install crontab differs from intended" >&2
  diff <(printf '%s' "$VERIFY") <(printf '%s' "$FINAL") || true
  exit 1
fi

INSTALLED_COUNT=$(printf '%s\n' "$VERIFY" | grep -c '# volpred-' || true)
echo "[install_host_crontab] done (${INSTALLED_COUNT} volpred entries installed)"
