#!/usr/bin/env bash
# Backward-compatible deploy wrapper.
# Source of truth for the active frontend target lives in config/project_targets.json.

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
CONFIG_PATH="${PROJECT_DIR}/config/project_targets.json"

ACTIVE_FRONTEND="$(
  python3 - <<'PY' "${CONFIG_PATH}"
import json
import sys
from pathlib import Path

config_path = Path(sys.argv[1])
payload = json.loads(config_path.read_text())
active = payload.get("active_frontend")
frontends = payload.get("frontends") or {}
entry = frontends.get(active) or {}
path = entry.get("path")
if not isinstance(path, str) or not path.strip():
    raise SystemExit("Invalid active frontend target in config/project_targets.json")
print(path)
PY
)"

TARGET_SCRIPT="${PROJECT_DIR}/${ACTIVE_FRONTEND}/scripts/deploy-zeabur-safe.sh"

if [ ! -x "${TARGET_SCRIPT}" ]; then
  echo "Active frontend deploy script not found or not executable: ${TARGET_SCRIPT}" >&2
  exit 1
fi

echo "Delegating deploy to active frontend target: ${ACTIVE_FRONTEND}"
exec bash "${TARGET_SCRIPT}"
