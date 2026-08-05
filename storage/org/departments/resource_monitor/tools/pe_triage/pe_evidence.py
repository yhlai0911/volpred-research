#!/usr/bin/env python3
"""(c) already_done 的機器證據：檢查各單宣稱的修復面現況（純讀）。"""
import hashlib
import json
import subprocess
from pathlib import Path

def sh(*a):
    return subprocess.run(a, capture_output=True, text=True).stdout.strip()

print("== 1. provider pin（D28/P0 item 25,27,29,53）==")
reg = json.loads(Path("config/provider_registry.json").read_text())
pin = json.dumps(reg)
cur = hashlib.sha256(Path(".claude/settings.json").read_bytes()).hexdigest()
print("settings.json 現值 sha256:", cur[:16])
print("registry 內含此 sha:", cur[:16] in pin)

print("\n== 2. inbox_archive CLI（D40 item 36, 41, 56）==")
for p in ["scripts/org/inbox_archive.py", "scripts/org/archive_inbox.py"]:
    print(f"{p}: {'存在' if Path(p).exists() else '不存在'}")

print("\n== 3. registry owned_paths（D16/D37 item 11,14,18,31,33,48）==")
r = json.loads(Path("storage/org/registry.json").read_text())
for d in ("platform_eng", "governance", "publications", "content", "research"):
    print(f"  {d}: {r['departments'][d].get('owned_paths')}")

print("\n== 4. manager settings / org_admin 子命令（D30 item 37, D42 item 43）==")
print("manager.settings.json:", Path("storage/org/runtime/manager.settings.json").exists())
oa = Path("scripts/org/org_admin.py").read_text()
for cmd in ("set-paths", "propose"):
    print(f"  org_admin '{cmd}':", cmd in oa)
print("  bulletin CLI (_core.bulletin_append):",
      "bulletin_append" in Path("scripts/org/_core.py").read_text())

print("\n== 5. provider pin 的 CI 測試（item 53 治本那一半）==")
for p in ["tests/test_provider_registry_pins.py", "scripts/tests/test_provider_registry_pins.py"]:
    print(f"  {p}: {Path(p).exists()}")
print("  work/ 底下:", sh("bash", "-lc", "ls work/provider_denial_20260805/ 2>/dev/null | head -5"))

print("\n== 6. paper-workflow.md L62 taiwan-vt（item 09 治理部 request）==")
line = Path(".claude/rules/paper-workflow.md").read_text().splitlines()[61]
print("  L62:", line[:150])
print("  仍含 paper/taiwan-vt/:", "paper/taiwan-vt/" in line)

print("\n== 7. skills 載入（item 54，我自己那則）==")
core = Path("scripts/org/_core.py").read_text()
print("  identity_prompt 提到 skills:", "skills" in core.split("def identity_prompt")[1][:1500])

print("\n== 8. 今天 platform_eng 相關 commit ==")
print(sh("git", "log", "--since=2026-08-05T00:00:00", "--oneline", "--", "scripts/", "config/", "tests/")[:2000])
