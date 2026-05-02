#!/bin/bash

set -uo pipefail

MODE="${1:-}"
ORIGINAL_COMMAND="${2:-}"

ROOT="${VOLPRED_HOOK_ROOT:-/Users/yhlai0911/Desktop/volpred-research}"
LOG_DIR="$ROOT/storage/logs/hooks"
mkdir -p "$LOG_DIR"

STAMP="$(date +%Y%m%dT%H%M%S)"
LOG_FILE="$LOG_DIR/${MODE}_${STAMP}_$$.log"

if bash -lc "$ORIGINAL_COMMAND" >"$LOG_FILE" 2>&1; then
  STATUS=0
else
  STATUS=$?
fi

case "$MODE" in
  test)
    if [[ "$STATUS" -eq 0 ]]; then
      echo "Tests passed. Full runner output suppressed to save context."
      echo "Full log: $LOG_FILE"
    else
      echo "Tests failed. Failure-focused excerpt:"
      if ! grep -n -A 5 -B 2 -E '(^FAIL|^FAILED|^ERROR|FAILED|ERROR|Traceback|AssertionError|E[[:space:]]+)' "$LOG_FILE" | head -120; then
        sed -n '1,120p' "$LOG_FILE"
      fi
      echo
      echo "Full log: $LOG_FILE"
    fi
    ;;
  git_status)
    BRANCH_LINE=""
    CHANGE_LINES_FILE="$LOG_FILE.changes"
    if head -n 1 "$LOG_FILE" | grep -q '^## '; then
      BRANCH_LINE="$(head -n 1 "$LOG_FILE" | sed 's/^## //')"
      tail -n +2 "$LOG_FILE" >"$CHANGE_LINES_FILE"
    else
      cp "$LOG_FILE" "$CHANGE_LINES_FILE"
    fi

    TOTAL_CHANGES=0
    STAGED=0
    UNSTAGED=0
    UNTRACKED=0
    DELETED=0
    CONFLICTS=0
    while IFS= read -r line; do
      [[ -z "$line" ]] && continue
      TOTAL_CHANGES=$((TOTAL_CHANGES + 1))
      STATUS_CODE="${line:0:2}"
      X="${STATUS_CODE:0:1}"
      Y="${STATUS_CODE:1:1}"
      if [[ "$STATUS_CODE" == "??" ]]; then
        UNTRACKED=$((UNTRACKED + 1))
      fi
      if [[ "$X" != " " && "$X" != "?" ]]; then
        STAGED=$((STAGED + 1))
      fi
      if [[ "$Y" != " " && "$Y" != "?" ]]; then
        UNSTAGED=$((UNSTAGED + 1))
      fi
      if [[ "$STATUS_CODE" == *D* ]]; then
        DELETED=$((DELETED + 1))
      fi
      if [[ "$STATUS_CODE" == *U* || "$STATUS_CODE" == "AA" || "$STATUS_CODE" == "DD" ]]; then
        CONFLICTS=$((CONFLICTS + 1))
      fi
    done <"$CHANGE_LINES_FILE"

    if [[ -n "$BRANCH_LINE" ]]; then
      echo "Branch: $BRANCH_LINE"
    fi
    if [[ "$TOTAL_CHANGES" -eq 0 ]]; then
      echo "Git working tree clean. Full output suppressed to save context."
      echo "Full log: $LOG_FILE"
      rm -f "$CHANGE_LINES_FILE"
      exit "$STATUS"
    fi

    echo "Git status compacted: ${TOTAL_CHANGES} changed paths."
    echo "Counts: staged=$STAGED unstaged=$UNSTAGED untracked=$UNTRACKED deleted=$DELETED conflicts=$CONFLICTS"
    echo "Preview:"
    sed -n '1,12p' "$CHANGE_LINES_FILE"
    if [[ "$TOTAL_CHANGES" -gt 12 ]]; then
      echo "... (+$((TOTAL_CHANGES - 12)) more paths)"
    fi
    echo "Full log: $LOG_FILE"
    rm -f "$CHANGE_LINES_FILE"
    ;;
  tail_log)
    TOTAL_LINES="$(wc -l < "$LOG_FILE" | tr -d ' ')"
    MAX_LINES=40
    if [[ "${TOTAL_LINES:-0}" -le "$MAX_LINES" ]]; then
      cat "$LOG_FILE"
    else
      echo "Log tail compacted to last $MAX_LINES lines (original ${TOTAL_LINES} lines)."
      tail -n "$MAX_LINES" "$LOG_FILE"
    fi
    echo "Full log: $LOG_FILE"
    ;;
  *)
    cat "$LOG_FILE"
    ;;
esac

exit "$STATUS"
