#!/bin/bash
# Migrate volpred cron entries to user-level launchd LaunchAgents.
#
# Single source of truth: `config/runtime_schedules.json` (canonical).
# This script reads cron expressions from canonical config, converts each
# to a StartCalendarInterval, writes plists, bootstraps into launchd.
# No hardcoded times in this script.
#
# Why launchd over crontab: macOS `com.vix.cron` daemon is silently
# unloaded from launchd's active list periodically, causing crontab
# entries to silent-miss. user-level launchd LaunchAgents stay active
# by design.
#
# Logging layout: each cron_*.sh has `exec >> <repo>/storage/logs/cron/*.log
# 2>&1` injected at top; plist StandardOut/StandardErr go to ~/.volpred/logs/.
# (Historical note: repo lived in ~/Desktop/ until 2026-07-02 — a TCC-protected
# dir that launchd jobs could not log into. Repo now at ~/volpred-research,
# outside TCC; never install it back under Desktop/Documents/Downloads.)

set -euo pipefail

USER_UID="$(id -u)"
LAUNCH_AGENTS_DIR="${VOLPRED_LAUNCH_AGENTS_DIR:-$HOME/Library/LaunchAgents}"
PROJECT_ROOT="${VOLPRED_PROJECT_ROOT:-$HOME/volpred-research}"
SCHEDULE_JSON="${VOLPRED_SCHEDULE_JSON:-$PROJECT_ROOT/config/runtime_schedules.json}"
LAUNCHD_LOG_DIR="${VOLPRED_LAUNCHD_LOG_DIR:-$HOME/.volpred/logs}"

TARGET_ID=""
RENDER_ONLY=0
while [[ $# -gt 0 ]]; do
    case "$1" in
        --id)
            [[ $# -ge 2 ]] || { echo "[ERROR] --id requires a job id" >&2; exit 2; }
            TARGET_ID="$2"
            shift 2
            ;;
        --render-only)
            RENDER_ONLY=1
            shift
            ;;
        -h|--help)
            echo "Usage: $0 [--id JOB_ID] [--render-only]"
            echo "  --id selects one explicit LaunchAgent job without touching other labels."
            echo "  --render-only writes plist(s) but does not call launchctl."
            exit 0
            ;;
        *)
            echo "[ERROR] unknown argument: $1" >&2
            exit 2
            ;;
    esac
done

mkdir -p "$LAUNCH_AGENTS_DIR" "$LAUNCHD_LOG_DIR"

# Convert cron expression to StartCalendarInterval XML.
# Supports patterns we use:
#   "M H * * *"       single daily fire (single dict)
#   "M H * * D"       weekly on weekday
#   "M H * * D1-D2"   weekly on weekday range
#   "M */N * * *"     every N hours at minute M (multi-dict array)
#   "*/N * * * *"     every N minutes (multi-dict array, all hours)
#   "M * * * *"       every hour at minute M (multi-dict array, all hours)
cron_to_calendar_xml() {
    local cron="$1"
    local interval_minutes="${2:-}"  # If non-empty, override cron with N-minute cadence
    local m h dom mon dow
    read -r m h dom mon dow <<< "$cron"

    # launchd_interval_minutes override (handles non-60-divisor cadences like 50)
    if [[ -n "$interval_minutes" ]] && [[ "$interval_minutes" =~ ^[0-9]+$ ]]; then
        local out="<key>StartCalendarInterval</key>\n    <array>"
        local cum=0
        while [[ $cum -lt 1440 ]]; do  # 1440 = 24*60 minutes per day
            local hh=$((cum / 60))
            local mm=$((cum % 60))
            out+="\n        <dict><key>Minute</key><integer>$mm</integer><key>Hour</key><integer>$hh</integer></dict>"
            cum=$((cum + interval_minutes))
        done
        out+="\n    </array>"
        printf '%b' "$out"
        return
    fi

    # Special case: "*/N * * * *" — every N minutes
    if [[ "$m" == "*/"* ]] && [[ "$h" == "*" ]]; then
        local step="${m#*/}"
        local out="<key>StartCalendarInterval</key>\n    <array>"
        local mm hh
        for ((hh=0; hh<24; hh++)); do
            for ((mm=0; mm<60; mm+=step)); do
                out+="\n        <dict><key>Minute</key><integer>$mm</integer><key>Hour</key><integer>$hh</integer></dict>"
            done
        done
        out+="\n    </array>"
        printf '%b' "$out"
        return
    fi

    # "M * * * *" — every hour at fixed minute
    if [[ "$h" == "*" ]] && [[ "$m" =~ ^[0-9]+$ ]]; then
        local out="<key>StartCalendarInterval</key>\n    <array>"
        local hh
        for ((hh=0; hh<24; hh++)); do
            out+="\n        <dict><key>Minute</key><integer>$m</integer><key>Hour</key><integer>$hh</integer></dict>"
        done
        out+="\n    </array>"
        printf '%b' "$out"
        return
    fi

    # "M */N * * *" — every N hours at minute M
    if [[ "$h" == "*/"* ]] && [[ "$m" =~ ^[0-9]+$ ]]; then
        local step="${h#*/}"
        local out="<key>StartCalendarInterval</key>\n    <array>"
        local hh
        for ((hh=0; hh<24; hh+=step)); do
            out+="\n        <dict><key>Minute</key><integer>$m</integer><key>Hour</key><integer>$hh</integer></dict>"
        done
        out+="\n    </array>"
        printf '%b' "$out"
        return
    fi

    # "M H * * *" — single daily fire
    if [[ "$dow" == "*" ]] && [[ "$m" =~ ^[0-9]+$ ]] && [[ "$h" =~ ^[0-9]+$ ]]; then
        printf '<key>StartCalendarInterval</key>\n    <dict>\n        <key>Minute</key><integer>%s</integer>\n        <key>Hour</key><integer>%s</integer>\n    </dict>' "$m" "$h"
        return
    fi

    # "M H * * D" or "M H * * D1-D2" — weekly fire(s)
    if [[ "$m" =~ ^[0-9]+$ ]] && [[ "$h" =~ ^[0-9]+$ ]]; then
        local out="<key>StartCalendarInterval</key>\n    <array>"
        # Expand weekday spec: "1-5" → "1 2 3 4 5", "2,4" → "2 4", "3" → "3"
        local days=""
        if [[ "$dow" =~ ^([0-9]+)-([0-9]+)$ ]]; then
            local d1="${BASH_REMATCH[1]}" d2="${BASH_REMATCH[2]}"
            for ((d=d1; d<=d2; d++)); do days+=" $d"; done
        elif [[ "$dow" =~ , ]]; then
            days="${dow//,/ }"
        else
            days="$dow"
        fi
        for d in $days; do
            out+="\n        <dict><key>Minute</key><integer>$m</integer><key>Hour</key><integer>$h</integer><key>Weekday</key><integer>$d</integer></dict>"
        done
        out+="\n    </array>"
        printf '%b' "$out"
        return
    fi

    echo "[ERROR] cron pattern not handled: $cron" >&2
    return 1
}

write_plist() {
    local label="$1"
    local script="$2"
    local schedule_xml="$3"
    local logbase="$4"
    local plist_path="$LAUNCH_AGENTS_DIR/${label}.plist"

    cat > "$plist_path" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>${label}</string>
    <key>ProgramArguments</key>
    <array>
        <string>/bin/bash</string>
        <string>-c</string>
        <string>${script}</string>
    </array>
    ${schedule_xml}
    <key>RunAtLoad</key>
    <false/>
    <key>StandardOutPath</key>
    <string>${LAUNCHD_LOG_DIR}/${logbase}_launchd.log</string>
    <key>StandardErrorPath</key>
    <string>${LAUNCHD_LOG_DIR}/${logbase}_launchd.err.log</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin</string>
    </dict>
</dict>
</plist>
EOF
    echo "[plist] wrote $plist_path"
}

# Iterate canonical items
echo "[derive] reading $SCHEDULE_JSON ..."

# Use jq to enumerate items, filter to host_crontab_managed != false
LABELS=()
DECOMMISSION_LABELS=()
LABEL_COUNT=0
DECOMMISSION_COUNT=0
MATCHED=0
while IFS= read -r item; do
    id=$(echo "$item" | jq -r '.id')
    if [[ -n "$TARGET_ID" && "$id" != "$TARGET_ID" ]]; then
        continue
    fi
    cron=$(echo "$item" | jq -r '.cron')
    wrapper=$(echo "$item" | jq -r '.wrapper_script')
    log_path=$(echo "$item" | jq -r '.log_path')
    # jq quirk: `false // true` returns true (false is falsy in alternative op).
    # Use has() to distinguish absent-key (default true) from explicit false.
    host_managed=$(echo "$item" | jq -r 'if has("host_crontab_managed") then .host_crontab_managed else true end')

    configured_label=$(echo "$item" | jq -r '.launchagent_label // .launchd_label // empty')
    mechanism=$(echo "$item" | jq -r '.mechanism // empty')
    operations_core_owned=$(echo "$item" | jq -r '._operations_core_owned')

    if [[ "$operations_core_owned" == "true" ]]; then
        label="${configured_label:-com.volpred.${id//_/-}}"
        DECOMMISSION_LABELS+=("$label")
        DECOMMISSION_COUNT=$((DECOMMISSION_COUNT + 1))
        MATCHED=$((MATCHED + 1))
        echo "[decommission] $id (operations-core owner; legacy label=$label)"
        continue
    fi

    # Default mode preserves the historical bulk migration behavior. Targeted
    # mode is the safe path for an explicit LaunchAgent owner: it may (and
    # normally should) be host_crontab_managed=false to guarantee single fire.
    if [[ -z "$TARGET_ID" && "$host_managed" == "false" ]]; then
        echo "[skip] $id (host_crontab_managed=false)"
        continue
    fi
    if [[ -n "$TARGET_ID" && "$mechanism" != "launchd" && -z "$configured_label" ]]; then
        echo "[ERROR] $id is not declared as an explicit LaunchAgent owner" >&2
        exit 1
    fi
    if [[ -z "$cron" || "$cron" == "null" ]]; then
        echo "[ERROR] $id has no calendar cron; daemon-style jobs need their dedicated installer" >&2
        exit 1
    fi

    # Explicit config label wins; legacy bulk jobs retain deterministic derivation.
    label="${configured_label:-com.volpred.${id//_/-}}"
    logbase=$(basename "$log_path" .log)

    interval_minutes=$(echo "$item" | jq -r '.launchd_interval_minutes // empty')
    schedule_xml=$(cron_to_calendar_xml "$cron" "$interval_minutes")
    if [[ -z "$schedule_xml" ]]; then
        echo "[ERROR] could not parse cron '$cron' for $id" >&2
        continue
    fi

    write_plist "$label" "$wrapper" "$schedule_xml" "$logbase"
    LABELS+=("$label")
    LABEL_COUNT=$((LABEL_COUNT + 1))
    MATCHED=$((MATCHED + 1))
    echo "  $id  cron='$cron'  wrapper=$(basename "$wrapper")"
done < <(jq -c '
    def operations_core_owns($root; $id):
      (($root.schedule_materialization.mode // "disabled") == "active")
      or (
        (($root.schedule_materialization.mode // "disabled") == "canary")
        and (($root.schedule_materialization.active_jobs[$id] // null) != null)
      );
    . as $root
    | .system_crontab.items[]
    | . + {"_operations_core_owned": operations_core_owns($root; .id)}
  ' "$SCHEDULE_JSON")

if [[ -n "$TARGET_ID" && "$MATCHED" -ne 1 ]]; then
    echo "[ERROR] targeted job not found exactly once: $TARGET_ID (matched=$MATCHED)" >&2
    exit 1
fi

if [[ "$RENDER_ONLY" -eq 1 ]]; then
    echo "[render-only] wrote ${LABEL_COUNT} plist(s); would decommission ${DECOMMISSION_COUNT} label(s); launchctl unchanged"
    exit 0
fi

echo ""
echo "[bootstrap] (re)loading ${LABEL_COUNT} plists into launchd gui/$USER_UID domain..."
echo ""

for label in "${DECOMMISSION_LABELS[@]-}"; do
    [[ -z "$label" ]] && continue
    if launchctl bootout "gui/$USER_UID/$label" 2>/dev/null; then
        echo "[bootout] $label OK (operations-core owner)"
    else
        echo "[bootout] $label already absent (operations-core owner)"
    fi
done

for label in "${LABELS[@]-}"; do
    [[ -z "$label" ]] && continue
    plist="$LAUNCH_AGENTS_DIR/${label}.plist"
    launchctl bootout "gui/$USER_UID/$label" 2>/dev/null || true
    if launchctl bootstrap "gui/$USER_UID" "$plist" 2>&1; then
        echo "[bootstrap] $label OK"
    else
        echo "[bootstrap] $label FAILED — see error above"
    fi
done

echo ""
echo "[verify] launchctl list | grep volpred:"
launchctl list | grep volpred || echo "[WARN] no volpred jobs in active list"

echo ""
echo "Done. Verify natural fires by tailing logs after the next scheduled time."
echo "Single source of truth: $SCHEDULE_JSON  →  edit there, re-run this script to sync."
