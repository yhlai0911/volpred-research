#!/usr/bin/env python3
"""Comprehensive strategy listing automation.

Automates the ENTIRE process of listing a new strategy on the platform,
ensuring no steps are missed. This is a PROCESS FIX following the
"修流程不修資料" principle.

Usage:
  # Full listing (all steps)
  uv run python scripts/list_new_strategy.py \
    --key vix_cond_leverage \
    --name "VIX 條件槓桿（月頻）" \
    --howto "【交易標的】SPY/GLD ..." \
    --description "VIX 條件槓桿策略完整說明..." \
    --assets '{"SPY": 50, "GLD": 50}' \
    --order 9 \
    --freq monthly \
    --type 動態配置 \
    --type-color "#3B82F6"

  # Verify-only mode (check if strategy is properly listed)
  uv run python scripts/list_new_strategy.py \
    --key vix_cond_leverage \
    --verify-only

  # Skip backfill (strategy already has paper_trading data)
  uv run python scripts/list_new_strategy.py \
    --key vix_cond_leverage \
    --name "VIX 條件槓桿（月頻）" \
    --howto "【交易標的】..." --description "..." \
    --assets '{"SPY": 50, "GLD": 50}' \
    --order 9 \
    --freq monthly --type 動態配置 --type-color "#3B82F6" \
    --skip-backfill

  # List all strategies with their status
  uv run python scripts/list_new_strategy.py --list-all
"""
import argparse
import json
import math
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen

PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT / "src"))
sys.path.insert(0, str(PROJECT / "scripts"))

# ---------------------------------------------------------------------------
# Supabase helpers (self-contained to avoid import chain issues)
# ---------------------------------------------------------------------------
_SUPABASE_URL = None
_SUPABASE_KEY = None


def _warn_strategy_listing(message: str, exc: Exception) -> None:
    print(f"  WARN {message}: {type(exc).__name__}: {exc}")


def _init_supabase():
    global _SUPABASE_URL, _SUPABASE_KEY
    if _SUPABASE_URL and _SUPABASE_KEY:
        return
    _SUPABASE_URL = os.environ.get("SUPABASE_URL")
    _SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    if not _SUPABASE_URL or not _SUPABASE_KEY:
        env_file = PROJECT / ".env.local"
        if env_file.exists():
            for line in env_file.read_text().splitlines():
                if line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                k, v = k.strip(), v.strip()
                if k == "SUPABASE_URL" and not _SUPABASE_URL:
                    _SUPABASE_URL = v
                elif k == "SUPABASE_SERVICE_ROLE_KEY" and not _SUPABASE_KEY:
                    _SUPABASE_KEY = v
    if not _SUPABASE_URL or not _SUPABASE_KEY:
        raise RuntimeError("Missing SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY")


def _headers():
    return {
        "apikey": _SUPABASE_KEY,
        "Authorization": f"Bearer {_SUPABASE_KEY}",
        "Content-Type": "application/json",
    }


def _sb_select(table: str, *, select: str = "*", **filters) -> list[dict]:
    _init_supabase()
    parts = [f"{k}=eq.{quote(str(v), safe='')}" for k, v in filters.items() if v is not None]
    url = f"{_SUPABASE_URL}/rest/v1/{table}?select={quote(select, safe=',*')}"
    if parts:
        url += "&" + "&".join(parts)
    req = Request(url, headers={**_headers(), "Prefer": ""}, method="GET")
    with urlopen(req, timeout=15) as resp:
        body = resp.read()
        return json.loads(body) if body else []


def _sb_upsert(table: str, data: list | dict, on_conflict: str | None = None) -> bool:
    _init_supabase()
    url = f"{_SUPABASE_URL}/rest/v1/{table}"
    if on_conflict:
        url += f"?on_conflict={on_conflict}"
    headers = {**_headers(), "Prefer": "resolution=merge-duplicates,return=minimal"}
    payload = json.dumps(data if isinstance(data, list) else [data], ensure_ascii=False).encode()
    req = Request(url, data=payload, headers=headers, method="POST")
    try:
        urlopen(req, timeout=15)
        return True
    except HTTPError as e:
        body = e.read().decode()
        print(f"  ERROR {table} upsert (HTTP {e.code}): {body[:200]}")
        return False
    except Exception as e:
        print(f"  ERROR {table} upsert: {e}")
        return False


def _sb_patch(table: str, filters: dict, row: dict) -> bool:
    _init_supabase()
    parts = [f"{k}=eq.{quote(str(v), safe='')}" for k, v in filters.items()]
    url = f"{_SUPABASE_URL}/rest/v1/{table}?{'&'.join(parts)}"
    headers = {**_headers(), "Prefer": "return=minimal"}
    payload = json.dumps(row, ensure_ascii=False).encode()
    req = Request(url, data=payload, headers=headers, method="PATCH")
    try:
        urlopen(req, timeout=15)
        return True
    except Exception as e:
        print(f"  ERROR {table} patch: {e}")
        return False


def _sb_delete(table: str, **filters) -> bool:
    _init_supabase()
    parts = [f"{k}=eq.{quote(str(v), safe='')}" for k, v in filters.items()]
    url = f"{_SUPABASE_URL}/rest/v1/{table}?{'&'.join(parts)}"
    req = Request(url, headers={**_headers(), "Prefer": "return=minimal"}, method="DELETE")
    try:
        urlopen(req, timeout=15)
        return True
    except Exception as e:
        print(f"  ERROR {table} delete: {e}")
        return False


def _sb_count(table: str, **filters) -> int:
    """Count rows in a table matching filters."""
    _init_supabase()
    parts = [f"{k}=eq.{quote(str(v), safe='')}" for k, v in filters.items()]
    url = f"{_SUPABASE_URL}/rest/v1/{table}?select=count"
    if parts:
        url += "&" + "&".join(parts)
    headers = {**_headers(), "Prefer": "count=exact"}
    req = Request(url, headers=headers, method="HEAD")
    try:
        with urlopen(req, timeout=15) as resp:
            cr = resp.headers.get("content-range", "")
            # content-range: 0-N/TOTAL or */TOTAL
            if "/" in cr:
                return int(cr.split("/")[-1])
    except Exception as exc:
        _warn_strategy_listing(f"{table} count HEAD failed; falling back to GET count", exc)
    # Fallback: count via GET
    rows = _sb_select(table, select="count", **filters)
    if rows and isinstance(rows, list):
        return len(rows)
    return 0


# ---------------------------------------------------------------------------
# Step implementations
# ---------------------------------------------------------------------------

class StrategyLister:
    def __init__(self, key: str, name: str = "", howto: str = "",
                 description: str = "", assets_json: str = "{}",
                 order: int = 99, color: str = "#6B7280",
                 articles_json: str = "[]",
                 rebalance_freq: str = "", strategy_type: str = "",
                 strategy_type_color: str = ""):
        self.key = key
        self.name = name
        self.howto = howto
        self.description = description
        self.assets = json.loads(assets_json) if isinstance(assets_json, str) else assets_json
        self.order = order
        self.color = color
        self.articles = json.loads(articles_json) if isinstance(articles_json, str) else articles_json
        self.rebalance_freq = rebalance_freq
        self.strategy_type = strategy_type
        self.strategy_type_color = strategy_type_color
        self.results: dict[str, str] = {}  # step -> status

    # -- Step A: Check STRATEGY_REGISTRY in daily_update.py --
    def check_registry(self) -> bool:
        """Check if strategy is in STRATEGY_REGISTRY."""
        du_path = PROJECT / "scripts" / "daily_update.py"
        content = du_path.read_text()
        in_registry = f'"{self.key}"' in content and "STRATEGY_REGISTRY" in content
        # More precise check: look for the key in the REGISTRY block
        import re
        pattern = rf'^\s*"{re.escape(self.key)}"\s*:'
        match = re.search(pattern, content, re.MULTILINE)
        return match is not None

    def step_a_check_registry(self) -> bool:
        """Step A: Verify strategy is in STRATEGY_REGISTRY."""
        print("\n--- Step A: Check STRATEGY_REGISTRY ---")
        if self.check_registry():
            print(f"  OK: '{self.key}' found in STRATEGY_REGISTRY")
            self.results["A_registry"] = "OK"
            return True
        else:
            print(f"  MISSING: '{self.key}' NOT in STRATEGY_REGISTRY")
            print(f"  ACTION REQUIRED: Add to daily_update.py STRATEGY_REGISTRY:")
            print(f'    "{self.key}": ("{self.name}", True, {self.order}),')
            self.results["A_registry"] = "MISSING (manual edit required)"
            return False

    # -- Step B: Write to Supabase strategy_signals --
    def step_b_strategy_signal(self) -> bool:
        """Step B: Upsert strategy_signals in Supabase."""
        print("\n--- Step B: Upsert strategy_signals ---")
        try:
            # Check if already exists
            existing = _sb_select("strategy_signals", strategy_key=self.key)
            row = {
                "strategy_key": self.key,
                "strategy_name": self.name,
                "weights": self.assets,
                "display_order": self.order,
                "is_active": True,
                "howto": self.howto,
                "description": self.description,
                "color": self.color,
                "articles": self.articles,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
            # Badge fields (migration 020) — only include if provided
            if self.assets:
                row["assets"] = self.assets
            if self.rebalance_freq:
                row["rebalance_freq"] = self.rebalance_freq
            if self.strategy_type:
                row["strategy_type"] = self.strategy_type
            if self.strategy_type_color:
                row["strategy_type_color"] = self.strategy_type_color
            if existing:
                # PATCH existing
                ok = _sb_patch("strategy_signals", {"strategy_key": self.key}, row)
                action = "updated"
            else:
                ok = _sb_upsert("strategy_signals", row, on_conflict="strategy_name")
                action = "created"

            if ok:
                print(f"  OK: strategy_signals {action}")
                self.results["B_signal"] = "OK"
                return True
            else:
                print(f"  FAILED: strategy_signals upsert")
                self.results["B_signal"] = "FAILED"
                return False
        except Exception as e:
            print(f"  ERROR: {e}")
            self.results["B_signal"] = f"ERROR: {e}"
            return False

    # -- Step C: Set display_order --
    def step_c_display_order(self) -> bool:
        """Step C: Ensure display_order is set correctly."""
        print("\n--- Step C: Verify display_order ---")
        try:
            rows = _sb_select("strategy_signals", strategy_key=self.key)
            if not rows:
                print(f"  SKIP: strategy not in strategy_signals yet")
                self.results["C_display_order"] = "SKIP"
                return False
            current_order = rows[0].get("display_order")
            if current_order == self.order:
                print(f"  OK: display_order = {self.order}")
                self.results["C_display_order"] = "OK"
                return True
            else:
                ok = _sb_patch("strategy_signals", {"strategy_key": self.key},
                               {"display_order": self.order})
                if ok:
                    print(f"  FIXED: display_order {current_order} -> {self.order}")
                    self.results["C_display_order"] = f"FIXED ({current_order} -> {self.order})"
                    return True
                else:
                    print(f"  FAILED: could not set display_order")
                    self.results["C_display_order"] = "FAILED"
                    return False
        except Exception as e:
            print(f"  ERROR: {e}")
            self.results["C_display_order"] = f"ERROR: {e}"
            return False

    # -- Step D: Check/generate paper_trading.json backfill --
    def step_d_check_backfill(self) -> bool:
        """Step D: Check if paper_trading.json has entries for this strategy."""
        print("\n--- Step D: Check paper_trading.json backfill ---")
        pt_path = PROJECT / "storage" / "paper_trading.json"
        if not pt_path.exists():
            print(f"  ERROR: paper_trading.json not found")
            self.results["D_backfill"] = "ERROR: file missing"
            return False

        pt = json.loads(pt_path.read_text())
        if self.key not in pt:
            print(f"  MISSING: '{self.key}' not in paper_trading.json")
            print(f"  ACTION: Run backfill script or add entries manually")
            print(f"  HINT: uv run python scripts/backfill_paper_trading.py --strategy {self.key}")
            self.results["D_backfill"] = "MISSING"
            return False

        entries = pt[self.key].get("entries", [])
        if not entries:
            print(f"  EMPTY: '{self.key}' has 0 entries")
            self.results["D_backfill"] = "EMPTY"
            return False

        # Check for entries with portfolio_return
        with_return = sum(1 for e in entries if e.get("portfolio_return") is not None)
        first_date = entries[0].get("data_date", entries[0].get("date", "?"))
        last_date = entries[-1].get("data_date", entries[-1].get("date", "?"))
        print(f"  OK: {len(entries)} entries ({first_date} to {last_date})")
        print(f"      {with_return}/{len(entries)} have portfolio_return")
        if with_return < len(entries) * 0.9:
            print(f"  WARNING: {len(entries) - with_return} entries missing portfolio_return")
        self.results["D_backfill"] = f"OK ({len(entries)} entries, {first_date} to {last_date})"
        return True

    # -- Step E: Recalculate strategy_metrics.json --
    def step_e_recalc_metrics(self) -> bool:
        """Step E: Recalculate strategy_metrics.json."""
        print("\n--- Step E: Recalculate strategy_metrics.json ---")
        try:
            from recalc_metrics import recalc_all
            metrics = recalc_all()
            if metrics and self.key in metrics:
                m = metrics[self.key]
                print(f"  OK: Sharpe={m.get('sharpe')}, MDD={m.get('max_drawdown')}%, "
                      f"Ret={m.get('cumulative_return')}%")
                self.results["E_metrics"] = (
                    f"OK (Sharpe={m.get('sharpe')}, "
                    f"MDD={m.get('max_drawdown')}%)"
                )
                return True
            else:
                print(f"  MISSING: '{self.key}' not in recalculated metrics")
                print(f"  (Likely because paper_trading.json has too few entries)")
                self.results["E_metrics"] = "MISSING in output"
                return False
        except Exception as e:
            print(f"  ERROR: {e}")
            self.results["E_metrics"] = f"ERROR: {e}"
            return False

    # -- Step F: Upsert strategy_metrics_cache to Supabase --
    def step_f_metrics_cache(self) -> bool:
        """Step F: Upsert strategy_metrics_cache to Supabase (with sparkline)."""
        print("\n--- Step F: Upsert strategy_metrics_cache ---")
        try:
            # Read local metrics
            metrics_path = PROJECT / "storage" / "strategy_metrics.json"
            if not metrics_path.exists():
                print(f"  ERROR: strategy_metrics.json not found")
                self.results["F_metrics_cache"] = "ERROR: file missing"
                return False

            all_metrics = json.loads(metrics_path.read_text())
            if self.key not in all_metrics:
                print(f"  SKIP: '{self.key}' not in strategy_metrics.json")
                self.results["F_metrics_cache"] = "SKIP (no local metrics)"
                return False

            metrics = all_metrics[self.key]

            # Build sparkline from paper_trading.json
            sparkline = self._build_sparkline()

            # Get display name from STRATEGY_REGISTRY or fallback
            display_name = self.name or self.key

            # Read from daily_update.py STRATEGY_REGISTRY for canonical name
            du_path = PROJECT / "scripts" / "daily_update.py"
            if du_path.exists():
                import re
                content = du_path.read_text()
                pattern = rf'"{re.escape(self.key)}"\s*:\s*\(\s*"([^"]+)"'
                match = re.search(pattern, content)
                if match:
                    display_name = match.group(1)

            row = {
                "strategy": self.key,
                "display_name": display_name,
                "metrics": {**metrics, "cache_version": 2, "display_name": display_name},
                "sparkline": sparkline,
                "latest_trade_date": self._get_latest_trade_date(),
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }

            ok = _sb_upsert("strategy_metrics_cache", row, on_conflict="strategy")
            if ok:
                print(f"  OK: strategy_metrics_cache upserted")
                print(f"      sparkline: {len(sparkline)} points")
                self.results["F_metrics_cache"] = f"OK ({len(sparkline)} sparkline points)"
                return True
            else:
                print(f"  FAILED: upsert to strategy_metrics_cache")
                self.results["F_metrics_cache"] = "FAILED"
                return False
        except Exception as e:
            print(f"  ERROR: {e}")
            self.results["F_metrics_cache"] = f"ERROR: {e}"
            return False

    def _build_sparkline(self, max_points: int = 90) -> list[float]:
        """Build sparkline (cumulative return series) from paper_trading.json."""
        pt_path = PROJECT / "storage" / "paper_trading.json"
        if not pt_path.exists():
            return []
        pt = json.loads(pt_path.read_text())
        if self.key not in pt:
            return []

        entries = pt[self.key].get("entries", [])
        # Filter to entries with portfolio_return, after COMMON_START_DATE
        COMMON_START = "2023-01-04"
        valid = [e for e in entries
                 if (e.get("data_date") or e.get("date", "")) >= COMMON_START
                 and e.get("portfolio_return") is not None]

        if len(valid) < 10:
            return []

        # Compute cumulative return series
        cum = 1.0
        cum_series = []
        for e in valid:
            cum *= (1 + e["portfolio_return"])
            cum_series.append(round((cum - 1) * 100, 2))

        # Downsample to max_points for sparkline
        if len(cum_series) <= max_points:
            return cum_series

        step = len(cum_series) / max_points
        result = []
        for i in range(max_points):
            idx = min(int(i * step), len(cum_series) - 1)
            result.append(cum_series[idx])
        # Always include the last point
        result[-1] = cum_series[-1]
        return result

    def _get_latest_trade_date(self) -> str | None:
        """Get the latest trade date from paper_trading.json."""
        pt_path = PROJECT / "storage" / "paper_trading.json"
        if not pt_path.exists():
            return None
        pt = json.loads(pt_path.read_text())
        if self.key not in pt:
            return None
        entries = pt[self.key].get("entries", [])
        if not entries:
            return None
        last = entries[-1]
        return last.get("data_date") or last.get("date")

    # -- Step G: Sync paper_trades to Supabase --
    def step_g_sync_paper_trades(self, last_n: int = 30) -> bool:
        """Step G: Sync recent paper_trades to Supabase.

        Uses DELETE + INSERT approach because paper_trades has no unique
        constraint on (strategy, trade_date).
        """
        print(f"\n--- Step G: Sync paper_trades (last {last_n} days) ---")
        try:
            pt_path = PROJECT / "storage" / "paper_trading.json"
            if not pt_path.exists():
                print(f"  ERROR: paper_trading.json not found")
                self.results["G_paper_trades"] = "ERROR: file missing"
                return False

            pt = json.loads(pt_path.read_text())
            if self.key not in pt:
                print(f"  SKIP: '{self.key}' not in paper_trading.json")
                self.results["G_paper_trades"] = "SKIP"
                return False

            entries = pt[self.key].get("entries", [])
            recent = entries[-last_n:] if len(entries) > last_n else entries

            if not recent:
                print(f"  SKIP: no entries to sync")
                self.results["G_paper_trades"] = "SKIP (0 entries)"
                return True

            # Get trade dates for deletion (avoid duplicates)
            trade_dates = set()
            rows = []
            for entry in recent:
                td = entry.get("data_date") or entry.get("trade_date") or entry.get("date", "")
                if not td:
                    continue
                trade_dates.add(td)
                rows.append({
                    "strategy": self.key,
                    "entry": entry,
                    "trade_date": td,
                })

            # Delete existing paper_trades for this strategy in the date range
            # to avoid duplicates (since no unique constraint exists)
            if trade_dates:
                min_date = min(trade_dates)
                max_date = max(trade_dates)
                _init_supabase()
                del_url = (
                    f"{_SUPABASE_URL}/rest/v1/paper_trades"
                    f"?strategy=eq.{quote(self.key, safe='')}"
                    f"&trade_date=gte.{min_date}"
                    f"&trade_date=lte.{max_date}"
                )
                del_req = Request(del_url,
                                  headers={**_headers(), "Prefer": "return=minimal"},
                                  method="DELETE")
                try:
                    urlopen(del_req, timeout=15)
                except Exception as e:
                    print(f"  WARNING: delete old paper_trades: {e}")

            # Insert in batches of 50
            ok_count = 0
            for i in range(0, len(rows), 50):
                batch = rows[i:i + 50]
                ok = _sb_upsert("paper_trades", batch)
                if ok:
                    ok_count += len(batch)

            print(f"  OK: {ok_count}/{len(rows)} paper_trades synced")
            self.results["G_paper_trades"] = f"OK ({ok_count} entries)"
            return ok_count > 0
        except Exception as e:
            print(f"  ERROR: {e}")
            self.results["G_paper_trades"] = f"ERROR: {e}"
            return False

    # -- Step 8: Verify strategy has linked articles --
    def step_8_check_articles(self) -> bool:
        """Step 8: Check that the strategy has at least one article linked.

        Checks both the local articles list passed via --articles and
        the strategy_signals.articles column in Supabase.
        """
        print("\n--- Step 8: Check linked articles ---")
        passed = False

        # Check in-memory articles (from --articles arg)
        if self.articles:
            print(f"  OK: {len(self.articles)} article(s) provided via --articles")
            self.results["8_articles"] = f"OK ({len(self.articles)} articles)"
            passed = True
        else:
            # Fall back to querying Supabase
            try:
                rows = _sb_select("strategy_signals",
                                  select="strategy_key,articles",
                                  strategy_key=self.key)
                if rows:
                    sb_articles = rows[0].get("articles") or []
                    if sb_articles:
                        print(f"  OK: {len(sb_articles)} article(s) in Supabase strategy_signals.articles")
                        self.results["8_articles"] = f"OK ({len(sb_articles)} articles in Supabase)"
                        passed = True
                    else:
                        print(f"  MISSING: strategy_signals.articles is empty")
                        print(f"  ACTION: Add at least one feed article about this strategy,")
                        print(f"          then pass --articles '[\"article_id\"]' when listing.")
                        self.results["8_articles"] = "MISSING (articles empty)"
                else:
                    print(f"  SKIP: strategy not yet in Supabase (run Step B first)")
                    self.results["8_articles"] = "SKIP (not in Supabase yet)"
                    passed = True  # non-fatal until after Step B
            except Exception as e:
                print(f"  ERROR: {e}")
                self.results["8_articles"] = f"ERROR: {e}"

        return passed

    # -- Step 9: Verify howto quality --
    def step_9_check_howto(self) -> bool:
        """Step 9: Check howto meets the quality standard.

        Standard: starts with 【 and contains 交易標的 OR 操作.
        Format: 【交易標的】... 【查詢工具】... 【操作】... 【範例】...
        """
        print("\n--- Step 9: Check howto quality ---")
        howto = self.howto

        # If no howto locally, try to fetch from Supabase
        if not howto:
            try:
                rows = _sb_select("strategy_signals",
                                  select="strategy_key,howto",
                                  strategy_key=self.key)
                if rows:
                    howto = rows[0].get("howto") or ""
            except Exception as exc:
                _warn_strategy_listing("howto fetch failed during Step 9", exc)

        if not howto:
            print(f"  MISSING: howto is empty")
            print(f"  ACTION: Provide --howto with format: 【交易標的】...【查詢工具】...【操作】...【範例】...")
            self.results["9_howto"] = "MISSING"
            return False

        starts_with_bracket = howto.strip().startswith("【")
        has_target = "交易標的" in howto
        has_operation = "操作" in howto
        has_tool = "查詢工具" in howto
        has_example = "範例" in howto

        issues = []
        if not starts_with_bracket:
            issues.append("must start with 【")
        if not has_target:
            issues.append("missing 交易標的")
        if not has_operation:
            issues.append("missing 操作")

        if not issues:
            sections = sum([has_target, has_tool, has_operation, has_example])
            print(f"  OK: howto quality check passed ({sections}/4 sections present)")
            if not has_tool:
                print(f"  HINT: consider adding 【查詢工具】section")
            if not has_example:
                print(f"  HINT: consider adding 【範例】section")
            self.results["9_howto"] = f"OK ({sections}/4 sections)"
            return True
        else:
            print(f"  FAIL: howto quality issues: {'; '.join(issues)}")
            print(f"  Current howto: {howto[:120]}{'...' if len(howto) > 120 else ''}")
            print(f"  Expected format: 【交易標的】...【查詢工具】...【操作】...【範例】...")
            self.results["9_howto"] = f"FAIL ({', '.join(issues)})"
            return False

    # -- Step H: Verification --
    def step_h_verify(self) -> dict:
        """Step H: Verify all Supabase tables have the strategy."""
        print("\n" + "=" * 60)
        print("--- Step H: VERIFICATION ---")
        print("=" * 60)
        checks = {}

        # 1. strategy_signals
        try:
            rows = _sb_select("strategy_signals",
                              select="strategy_key,strategy_name,display_order,is_active",
                              strategy_key=self.key)
            if rows:
                r = rows[0]
                checks["strategy_signals"] = {
                    "status": "OK",
                    "name": r.get("strategy_name"),
                    "order": r.get("display_order"),
                    "active": r.get("is_active"),
                }
            else:
                checks["strategy_signals"] = {"status": "MISSING"}
        except Exception as e:
            checks["strategy_signals"] = {"status": f"ERROR: {e}"}

        # 2. strategy_metrics_cache
        try:
            rows = _sb_select("strategy_metrics_cache",
                              select="strategy,display_name,latest_trade_date,updated_at",
                              strategy=self.key)
            if rows:
                r = rows[0]
                checks["strategy_metrics_cache"] = {
                    "status": "OK",
                    "display_name": r.get("display_name"),
                    "latest_trade_date": r.get("latest_trade_date"),
                    "updated_at": r.get("updated_at"),
                }
            else:
                checks["strategy_metrics_cache"] = {"status": "MISSING"}
        except Exception as e:
            checks["strategy_metrics_cache"] = {"status": f"ERROR: {e}"}

        # 3. paper_trades count
        try:
            rows = _sb_select("paper_trades",
                              select="trade_date",
                              strategy=self.key)
            count = len(rows)
            if count > 0:
                dates = sorted([r.get("trade_date", "") for r in rows])
                checks["paper_trades"] = {
                    "status": "OK",
                    "count": count,
                    "date_range": f"{dates[0]} to {dates[-1]}",
                }
            else:
                checks["paper_trades"] = {"status": "MISSING", "count": 0}
        except Exception as e:
            checks["paper_trades"] = {"status": f"ERROR: {e}"}

        # 4. STRATEGY_REGISTRY
        checks["strategy_registry"] = {
            "status": "OK" if self.check_registry() else "MISSING",
        }

        # 5. paper_trading.json local
        pt_path = PROJECT / "storage" / "paper_trading.json"
        if pt_path.exists():
            pt = json.loads(pt_path.read_text())
            if self.key in pt:
                entries = pt[self.key].get("entries", [])
                checks["paper_trading_json"] = {
                    "status": "OK",
                    "entries": len(entries),
                }
            else:
                checks["paper_trading_json"] = {"status": "MISSING"}
        else:
            checks["paper_trading_json"] = {"status": "FILE NOT FOUND"}

        # 6. strategy_metrics.json local
        met_path = PROJECT / "storage" / "strategy_metrics.json"
        if met_path.exists():
            met = json.loads(met_path.read_text())
            if self.key in met:
                m = met[self.key]
                checks["strategy_metrics_json"] = {
                    "status": "OK",
                    "sharpe": m.get("sharpe"),
                    "cumulative_return": m.get("cumulative_return"),
                }
            else:
                checks["strategy_metrics_json"] = {"status": "MISSING"}
        else:
            checks["strategy_metrics_json"] = {"status": "FILE NOT FOUND"}

        # 7. Badge fields (migration 020)
        try:
            rows = _sb_select(
                "strategy_signals",
                select="strategy_key,assets,rebalance_freq,strategy_type,strategy_type_color",
                strategy_key=self.key,
            )
            if rows:
                r = rows[0]
                badge_issues = []
                if not r.get("assets"):
                    badge_issues.append("assets empty")
                if not r.get("rebalance_freq"):
                    badge_issues.append("rebalance_freq empty")
                if not r.get("strategy_type"):
                    badge_issues.append("strategy_type empty")
                if not r.get("strategy_type_color"):
                    badge_issues.append("strategy_type_color empty")
                if badge_issues:
                    checks["badge_fields"] = {
                        "status": "INCOMPLETE",
                        "missing": ", ".join(badge_issues),
                    }
                else:
                    checks["badge_fields"] = {
                        "status": "OK",
                        "type": r.get("strategy_type"),
                        "freq": r.get("rebalance_freq"),
                    }
            else:
                checks["badge_fields"] = {"status": "SKIP (not in Supabase yet)"}
        except Exception as e:
            checks["badge_fields"] = {"status": f"ERROR: {e}"}

        # 8. Articles linked
        try:
            rows = _sb_select("strategy_signals",
                              select="strategy_key,articles",
                              strategy_key=self.key)
            if rows:
                sb_articles = rows[0].get("articles") or []
                local_articles = self.articles or []
                articles = sb_articles or local_articles
                if articles:
                    checks["articles_linked"] = {
                        "status": "OK",
                        "count": len(articles),
                    }
                else:
                    checks["articles_linked"] = {
                        "status": "MISSING",
                        "note": "Add articles via --articles or feed-publisher",
                    }
            else:
                checks["articles_linked"] = {"status": "SKIP (not in Supabase yet)"}
        except Exception as e:
            checks["articles_linked"] = {"status": f"ERROR: {e}"}

        # 9. Howto quality
        howto_to_check = self.howto
        if not howto_to_check:
            try:
                rows = _sb_select("strategy_signals",
                                  select="strategy_key,howto",
                                  strategy_key=self.key)
                if rows:
                    howto_to_check = rows[0].get("howto") or ""
            except Exception as exc:
                _warn_strategy_listing("howto fetch failed during verify", exc)
        if howto_to_check:
            starts_bracket = howto_to_check.strip().startswith("【")
            has_target = "交易標的" in howto_to_check
            has_op = "操作" in howto_to_check
            issues = []
            if not starts_bracket:
                issues.append("must start with 【")
            if not has_target:
                issues.append("missing 交易標的")
            if not has_op:
                issues.append("missing 操作")
            if issues:
                checks["howto_quality"] = {
                    "status": "FAIL",
                    "issues": ", ".join(issues),
                }
            else:
                checks["howto_quality"] = {"status": "OK"}
        else:
            checks["howto_quality"] = {"status": "MISSING (no howto)"}

        # Print summary
        print()
        all_ok = True
        for component, info in checks.items():
            status = info.get("status", "UNKNOWN")
            icon = "OK" if status == "OK" else "FAIL"
            details = ""
            if status == "OK":
                detail_parts = [f"{k}={v}" for k, v in info.items() if k != "status"]
                details = f" ({', '.join(detail_parts)})" if detail_parts else ""
            else:
                details = f" [{status}]"
                all_ok = False
            print(f"  {'[OK]' if icon == 'OK' else '[!!]'} {component:30s}{details}")

        print()
        if all_ok:
            print("  ALL CHECKS PASSED")
        else:
            failed = [k for k, v in checks.items() if v.get("status") != "OK"]
            print(f"  FAILED CHECKS: {', '.join(failed)}")
            print(f"  Run without --verify-only to fix, or address manually.")

        self.results["H_verify"] = checks
        return checks


def list_all_strategies():
    """List all strategies and their status across all systems."""
    print("=" * 80)
    print("STRATEGY LISTING STATUS")
    print("=" * 80)

    # Read STRATEGY_REGISTRY
    du_path = PROJECT / "scripts" / "daily_update.py"
    import re
    content = du_path.read_text()
    # Extract registry entries
    registry = {}
    pattern = r'"([^"]+)"\s*:\s*\(\s*"([^"]+)"\s*,\s*(True|False)\s*,\s*(\d+)\s*\)'
    for match in re.finditer(pattern, content):
        key, name, active, order = match.groups()
        registry[key] = {"name": name, "active": active == "True", "order": int(order)}

    # Read paper_trading.json
    pt_path = PROJECT / "storage" / "paper_trading.json"
    pt = json.loads(pt_path.read_text()) if pt_path.exists() else {}

    # Read strategy_metrics.json
    met_path = PROJECT / "storage" / "strategy_metrics.json"
    met = json.loads(met_path.read_text()) if met_path.exists() else {}

    # Read Supabase
    try:
        _init_supabase()
        sb_signals = _sb_select(
            "strategy_signals",
            select="strategy_key,strategy_name,display_order,is_active,"
                   "strategy_type,rebalance_freq,articles",
        )
        sb_signals_map = {r["strategy_key"]: r for r in sb_signals if r.get("strategy_key")}
    except Exception as e:
        print(f"  Supabase connection error: {e}")
        sb_signals_map = {}

    try:
        sb_cache = _sb_select("strategy_metrics_cache", select="strategy,updated_at")
        sb_cache_map = {r["strategy"]: r for r in sb_cache if r.get("strategy")}
    except Exception:
        sb_cache_map = {}

    # All known keys
    all_keys = sorted(set(list(registry.keys()) + list(pt.keys()) + list(met.keys()) + list(sb_signals_map.keys())))

    print(f"\n{'Key':30s} {'Registry':10s} {'PT':6s} {'Metrics':12s} {'SB':4s} {'Cache':6s} {'Type':14s} {'Freq':10s} {'Art':4s}")
    print("-" * 100)

    for key in all_keys:
        reg_status = "OK" if key in registry else "--"
        if key in registry and not registry[key]["active"]:
            reg_status = "inactive"

        pt_count = len(pt.get(key, {}).get("entries", []))
        pt_status = f"{pt_count}" if pt_count > 0 else "--"

        met_status = f"S={met[key].get('sharpe', '?')}" if key in met else "--"

        sb_status = "OK" if key in sb_signals_map else "--"
        cache_status = "OK" if key in sb_cache_map else "--"

        # Badge fields
        sig = sb_signals_map.get(key, {})
        strat_type = sig.get("strategy_type") or "--"
        freq = sig.get("rebalance_freq") or "--"
        articles = sig.get("articles") or []
        art_count = str(len(articles)) if articles else "--"

        # Truncate type label for display
        if len(strat_type) > 12:
            strat_type = strat_type[:11] + "…"

        # Overall health (core checks only)
        all_ok = (key in registry and pt_count > 0 and key in met
                  and key in sb_signals_map and key in sb_cache_map)
        icon = "[OK]" if all_ok else "[!!]"

        print(f"  {icon} {key:27s} {reg_status:10s} {pt_status:6s} {met_status:12s} "
              f"{sb_status:4s} {cache_status:6s} {strat_type:14s} {freq:10s} {art_count:4s}")

    print(f"\nTotal: {len(all_keys)} strategies")
    print("\nBadge legend: Type = strategy_type, Freq = rebalance_freq, Art = #articles linked")


def run_full_listing(args):
    """Run all listing steps."""
    lister = StrategyLister(
        key=args.key,
        name=args.name or "",
        howto=args.howto or "",
        description=args.description or "",
        assets_json=args.assets or "{}",
        order=args.order,
        color=args.color or "#6B7280",
        articles_json=args.articles or "[]",
        rebalance_freq=args.freq or "",
        strategy_type=args.type or "",
        strategy_type_color=args.type_color or "",
    )

    print("=" * 60)
    print(f"LISTING STRATEGY: {args.key}")
    print(f"  Name: {args.name}")
    print(f"  Order: {args.order}")
    if args.freq:
        print(f"  Freq: {args.freq}")
    if args.type:
        print(f"  Type: {args.type}  Color: {args.type_color or '(default)'}")
    print("=" * 60)

    # Step A: Check STRATEGY_REGISTRY
    lister.step_a_check_registry()

    # Step B: Write to Supabase strategy_signals
    if args.name:
        lister.step_b_strategy_signal()
    else:
        print("\n--- Step B: SKIP (no --name provided) ---")
        lister.results["B_signal"] = "SKIP"

    # Step C: Set display_order
    lister.step_c_display_order()

    # Step D: Check backfill
    has_backfill = lister.step_d_check_backfill()

    # Step E: Recalculate metrics
    if has_backfill and not args.skip_metrics:
        lister.step_e_recalc_metrics()
    else:
        print("\n--- Step E: SKIP (no backfill data or --skip-metrics) ---")
        lister.results["E_metrics"] = "SKIP"

    # Step F: Upsert strategy_metrics_cache
    if has_backfill and not args.skip_metrics:
        lister.step_f_metrics_cache()
    else:
        print("\n--- Step F: SKIP (no metrics) ---")
        lister.results["F_metrics_cache"] = "SKIP"

    # Step G: Sync paper_trades
    if has_backfill and not args.skip_sync:
        lister.step_g_sync_paper_trades(last_n=args.sync_days)
    else:
        print(f"\n--- Step G: SKIP (no backfill or --skip-sync) ---")
        lister.results["G_paper_trades"] = "SKIP"

    # Step 8: Check linked articles (SOP requirement)
    lister.step_8_check_articles()

    # Step 9: Check howto quality (SOP requirement)
    lister.step_9_check_howto()

    # Step H: Verification (comprehensive check of all components)
    checks = lister.step_h_verify()

    # Final summary
    print("\n" + "=" * 60)
    print("STEP RESULTS SUMMARY")
    print("=" * 60)
    for step, status in lister.results.items():
        if step == "H_verify":
            continue  # already printed
        icon = "[OK]" if "OK" in str(status) else "[!!]"
        print(f"  {icon} {step:25s} {status}")

    # Return exit code
    failed = [k for k, v in checks.items() if v.get("status") != "OK"]
    return 0 if not failed else 1


def main():
    parser = argparse.ArgumentParser(
        description="Comprehensive strategy listing automation",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Verify a strategy is properly listed
  uv run python scripts/list_new_strategy.py --key slow_vt --verify-only

  # Full listing with all metadata
  uv run python scripts/list_new_strategy.py \\
    --key my_strategy --name "My Strategy" \\
    --howto "One-line instruction" \\
    --description "Full description" \\
    --assets '{"SPY": 50, "GLD": 50}' \\
    --order 15

  # List all strategies and their status
  uv run python scripts/list_new_strategy.py --list-all

  # Fix specific components (skip backfill/metrics)
  uv run python scripts/list_new_strategy.py \\
    --key my_strategy --name "My Strategy" \\
    --howto "【交易標的】..." --description "..." \\
    --assets '{"SPY": 50}' --order 15 \\
    --freq monthly --type 動態配置 --type-color "#3B82F6" \\
    --skip-backfill --skip-metrics
        """
    )
    parser.add_argument("--key", help="Strategy key (snake_case)")
    parser.add_argument("--name", help="Display name")
    parser.add_argument("--howto", help="Operation instruction (start with 【交易標的】...)")
    parser.add_argument("--description", help="Full operation description")
    parser.add_argument("--assets", help="Asset weights as JSON, e.g. '{\"SPY\": 50}'")
    parser.add_argument("--order", type=int, default=99, help="Display order")
    parser.add_argument("--color", default="#6B7280", help="Chart color (hex)")
    parser.add_argument("--articles", default="[]", help="Related articles JSON array")
    # Badge fields (migration 020)
    parser.add_argument("--freq", dest="freq", default="",
                        help="Rebalance frequency badge, e.g. daily / weekly / monthly")
    parser.add_argument("--type", dest="type", default="",
                        help="Strategy type badge label, e.g. 動態配置 / 動量 / 避險")
    parser.add_argument("--type-color", dest="type_color", default="",
                        help="Strategy type badge color (hex), e.g. #3B82F6")
    parser.add_argument("--verify-only", action="store_true",
                        help="Only verify, do not modify anything")
    parser.add_argument("--list-all", action="store_true",
                        help="List all strategies and their status")
    parser.add_argument("--skip-backfill", action="store_true",
                        help="Skip backfill check (use existing data)")
    parser.add_argument("--skip-metrics", action="store_true",
                        help="Skip metrics recalculation")
    parser.add_argument("--skip-sync", action="store_true",
                        help="Skip Supabase paper_trades sync")
    parser.add_argument("--sync-days", type=int, default=30,
                        help="Number of days to sync to paper_trades (default: 30)")

    args = parser.parse_args()

    if args.list_all:
        list_all_strategies()
        return

    if not args.key:
        parser.error("--key is required (or use --list-all)")

    if args.verify_only:
        lister = StrategyLister(
            key=args.key,
            name=args.name or args.key,
            howto=args.howto or "",
            articles_json=args.articles or "[]",
            rebalance_freq=args.freq or "",
            strategy_type=args.type or "",
            strategy_type_color=args.type_color or "",
        )
        checks = lister.step_h_verify()
        failed = [k for k, v in checks.items() if v.get("status") != "OK"]
        sys.exit(0 if not failed else 1)

    # Full listing requires name + howto + description + assets
    if not args.name:
        # Try to infer from STRATEGY_REGISTRY
        import re
        du_path = PROJECT / "scripts" / "daily_update.py"
        content = du_path.read_text()
        pattern = rf'"{re.escape(args.key)}"\s*:\s*\(\s*"([^"]+)"\s*,\s*(True|False)\s*,\s*(\d+)\s*\)'
        match = re.search(pattern, content)
        if match:
            args.name = match.group(1)
            inferred_order = int(match.group(3))
            if args.order == 99:
                args.order = inferred_order
            print(f"  Inferred from STRATEGY_REGISTRY: name='{args.name}', order={args.order}")
        else:
            parser.error("--name is required for full listing (could not infer from STRATEGY_REGISTRY)")

    exit_code = run_full_listing(args)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
