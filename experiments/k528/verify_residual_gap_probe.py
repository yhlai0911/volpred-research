"""My own B2 probe: delete an endpoint month from BOTH raw and selected and
confirm the gate raises. Executes module-level statements one at a time and
skips any that need the parts of the module we deliberately are not loading
(price download, etc.), so what gets exercised is the gate itself."""
import ast, json
from pathlib import Path
import pandas as pd

WT = Path("/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp")
SRC = WT / "experiments/k528/k528_nfp_event_study.py"

tree = ast.parse(SRC.read_text(encoding="utf-8"))
ns, skipped = {}, 0
for node in tree.body:
    if isinstance(node, (ast.Import, ast.ImportFrom, ast.FunctionDef,
                         ast.Assign, ast.AnnAssign, ast.ClassDef)):
        mod = ast.Module(body=[node], type_ignores=[])
        try:
            exec(compile(ast.fix_missing_locations(mod), "<gate>", "exec"), ns)
        except Exception:
            skipped += 1

gate = ns["check_calendar_is_complete"]
print(f"lifted gate from source (skipped {skipped} module-level stmts needing network/other deps)")
print("LATEST_OBSERVED_RELEASE_DAY_OF_MONTH =", ns.get("LATEST_OBSERVED_RELEASE_DAY_OF_MONTH"))
print("MAX_WINDOW_SHORTFALL_DAYS =", ns.get("MAX_WINDOW_SHORTFALL_DAYS"))
print("KNOWN_MISSING_MONTHS =", ns.get("KNOWN_MISSING_MONTHS"))

fixture = json.loads((WT / "experiments/k528/data/nfp_release_feed_fixture.json").read_text())
raw_all = fixture["raw_dates"] if isinstance(fixture, dict) else fixture
if isinstance(raw_all[0], dict):
    raw_all = [d["date"] for d in raw_all]
by_month = {}
for d in raw_all:
    by_month.setdefault(d[:7], []).append(d)
sel_all = sorted(min(v) for v in by_month.values())
START, END = "2005-01-01", "2026-03-27"

def run(label, raw, sel):
    try:
        gate(pd.to_datetime(sorted(sel)), sorted(raw), START, END)
        print(f"  {label:24s} ACCEPTED   <-- gate did NOT fire")
        return "ACCEPTED"
    except RuntimeError as e:
        print(f"  {label:24s} RAISED     {str(e).strip().splitlines()[0][:130]}")
        return "RAISED"

print(f"\nfixture: raw={len(raw_all)} selected={len(sel_all)}")
print("\n--- negative control (honest, untouched calendar) ---")
ctrl = run("honest", raw_all, sel_all)

print("\n--- THE ATTACK (round-5 residual gap): delete an endpoint month from raw AND selected ---")
results = {}
for victim in ("2005-01", "2026-03"):
    raw_cut = [d for d in raw_all if not d.startswith(victim)]
    sel_cut = [d for d in sel_all if not d.startswith(victim)]
    print(f"  [{victim}] raw {len(raw_all)}->{len(raw_cut)}, selected {len(sel_all)}->{len(sel_cut)}")
    results[victim] = run(f"delete {victim}", raw_cut, sel_cut)

print("\n=== VERDICT ===")
ok = ctrl == "ACCEPTED" and all(v == "RAISED" for v in results.values())
print("residual gap CLOSED (honest accepted, both endpoint attacks raised):", ok)
