from __future__ import annotations

import json
import sys
from pathlib import Path

import click
import yaml
from pydantic import ValidationError
from rich.console import Console
from rich.table import Table

console = Console()
OPS_ACTION_CHOICES = (
    "article_local_backups",
    "check_alerts",
    "cleanup_test_post",
    "daily_update",
    "health_check",
    "paper_migrate_storage",
    "paper_upload_pdf",
    "paper_upsert",
    "platform_cycle_summary",
    "publish_milestone",
    "question_claim",
    "question_rerank",
    "question_ranking_summary",
    "question_ranking_workflow",
    "release_article_pool",
    "release_article_pool_by_settings",
    "send_article_notification",
    "send_alert",
    "send_daily_digest",
    "question_answer",
    "recalc_metrics",
    "strategy_set_active",
    "strategy_upsert",
    "sync_all",
    "unpublish_article",
)
LOCAL_TASK_SOURCE_CHOICES = ("user", "schedule", "agent")
LOCAL_TASK_FAMILY_CHOICES = ("research", "ops", "content", "code", "review", "member", "strategy")
LOCAL_TASK_AGENT_CHOICES = ("claude", "codex", "auto")
LOCAL_APPROVAL_MODE_CHOICES = ("auto", "needs_approval")
LOCAL_RISK_LEVEL_CHOICES = ("safe", "elevated", "destructive")
LOCAL_PUBLIC_EFFECT_CHOICES = ("none", "draft_only", "published", "member_visible", "prod_runtime")
LOCAL_AGENT_CHOICES = ("claude", "codex")
LOCAL_SESSION_KEY_CHOICES = ("claude-supervisor", "claude-worker", "codex-worker")
LOCAL_AGENT_ROLE_CHOICES = ("supervisor", "worker")
LOCAL_GOVERNANCE_AREA_CHOICES = ("schedule",)


def _resolve_agent_session_cli(
    agent_name: str | None,
    session_key: str | None,
    role: str | None,
) -> tuple[str, str, str]:
    """Resolve (session_key, agent_name, role) from CLI options.

    At least one of --agent or --session-key must be provided. --role is
    optional and defaults to 'worker' when only --agent is given.
    """
    from volpred.ops import resolve_session_key

    if not agent_name and not session_key:
        raise click.ClickException(
            "must supply either --agent or --session-key"
        )
    try:
        return resolve_session_key(
            session_key=session_key, agent_name=agent_name, role=role
        )
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc


def _parse_signal_payload(raw: str | None) -> dict | None:
    if raw is None:
        return None
    parsed = _parse_json_input(raw, default=None)
    if parsed is None:
        return None
    if not isinstance(parsed, dict):
        raise click.ClickException("--signals-json must decode to a JSON object")
    return parsed


def _print_json(payload: object) -> None:
    console.print(f"[dim]JSON: {json.dumps(payload, ensure_ascii=False, default=str)}[/dim]")


def _parse_json_input(raw: str | None, *, default: object) -> object:
    if raw is None:
        return default
    candidate = Path(raw)
    if candidate.exists():
        return json.loads(candidate.read_text())
    return json.loads(raw)


def _parse_tags(raw: str | None) -> list[str]:
    if not raw:
        return []
    trimmed = raw.strip()
    # Accept JSON array form: '["a", "b"]' — prevents split-by-comma mangling JSON strings.
    if trimmed.startswith("[") and trimmed.endswith("]"):
        try:
            decoded = json.loads(trimmed)
            if isinstance(decoded, list):
                return [str(t).strip() for t in decoded if str(t).strip()]
        except json.JSONDecodeError:
            pass
    return [tag.strip() for tag in trimmed.split(",") if tag.strip()]


def _parse_optional_number(raw: str | None) -> int | None:
    if raw is None:
        return None
    trimmed = raw.strip()
    if not trimmed:
        return None
    return int(trimmed)


def _parse_optional_float(raw: str | None) -> float | None:
    if raw is None:
        return None
    trimmed = raw.strip()
    if not trimmed:
        return None
    return float(trimmed)


def _parse_string_list_input(raw: str | None) -> list[str]:
    payload = _parse_json_input(raw, default=[])
    if isinstance(payload, list):
        return [str(item) for item in payload if str(item).strip()]
    if isinstance(payload, str):
        return [item.strip() for item in payload.split(",") if item.strip()]
    raise click.ClickException("Input must decode to a JSON array or a comma-separated string")


def _print_completed_process(result, *, action: str) -> None:
    status = "ok" if result.returncode == 0 else "failed"
    payload = {
        "action": action,
        "status": status,
        "returncode": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
    }
    if result.stdout.strip():
        console.print(result.stdout.rstrip())
    if result.stderr.strip():
        console.print(f"[yellow]{result.stderr.rstrip()}[/yellow]")
    _print_json(payload)
    if result.returncode != 0:
        raise SystemExit(result.returncode)


@click.group()
@click.version_option(version="0.1.0")
def cli():
    """Volpred -- Autonomous Volatility Prediction Research System"""
    pass


@cli.command()
@click.option("--asset", required=True, help="Ticker symbol (e.g., SPY)")
@click.option("--model", required=True, help="Model name (e.g., garch_arch, garch_custom)")
@click.option("--window", default=252, help="Rolling window size")
@click.option("--oos-start", required=True, help="OOS start date (YYYY-MM-DD)")
@click.option("--oos-end", required=True, help="OOS end date (YYYY-MM-DD)")
@click.option("--config", type=click.Path(exists=True), help="YAML config file (overrides other options)")
@click.option("--workers", default=None, type=int, help="Number of parallel workers")
@click.option("--dist", default="normal", help="Distribution: normal, studentt, skewt")
def run_experiment(
    asset: str,
    model: str,
    window: int,
    oos_start: str,
    oos_end: str,
    config: str | None,
    workers: int | None,
    dist: str,
) -> None:
    """Run a rolling forecast experiment."""
    import pandas as pd

    import volpred.models.garch  # noqa: F401 — trigger registration
    from volpred.core.types import ExperimentConfig
    from volpred.data.manager import DataManager
    from volpred.engine.rolling_forecast import RollingForecastEngine
    from volpred.evaluation.evaluator import Evaluator
    from volpred.memory.system import MemorySystem

    if config:
        with open(config) as f:
            cfg = yaml.safe_load(f)
        asset = cfg.get("asset", asset)
        model = cfg.get("model", model)
        window = cfg.get("window_size", window)
        oos_start = cfg.get("oos_start", oos_start)
        oos_end = cfg.get("oos_end", oos_end)
        dist = cfg.get("dist", dist)
        workers = cfg.get("workers", workers)

    # Build experiment config
    model_params = {"dist": dist}
    exp_config = ExperimentConfig(
        model_name=model,
        model_params=model_params,
        asset=asset,
        window_size=window,
        oos_start=oos_start,
        oos_end=oos_end,
    )

    console.print(f"[bold blue]Running experiment {exp_config.experiment_id}[/bold blue]")
    console.print(f"  Asset: {asset}, Model: {model}, Window: {window}")
    console.print(f"  OOS: {oos_start} -> {oos_end}, Dist: {dist}")

    # Get data (with buffer before OOS for the rolling window)
    dm = DataManager()
    buffer_start = (pd.Timestamp(oos_start) - pd.DateOffset(days=int(window * 1.5))).strftime(
        "%Y-%m-%d"
    )
    data = dm.get_model_data(asset, buffer_start, oos_end)
    console.print(f"  Data: {len(data)} rows, {data.index[0].date()} -> {data.index[-1].date()}")

    # Run rolling forecast
    engine = RollingForecastEngine(n_workers=workers)
    with console.status("[bold green]Running rolling forecast..."):
        result = engine.run(exp_config, data)

    console.print(f"  [green]Done: {len(result.forecasts)} forecasts in {result.fit_time:.1f}s[/green]")

    # Evaluate
    evaluator = Evaluator()
    metrics = evaluator.evaluate(result, data)
    result.metrics = metrics

    # Save to memory
    memory = MemorySystem()
    memory.save_experiment(result, metrics)
    memory.save_forecasts(result.experiment_id, result.forecasts)

    # Display statistical metrics
    table = Table(title=f"Experiment {exp_config.experiment_id} — Statistical Metrics")
    table.add_column("Metric", style="cyan")
    table.add_column("Value", style="green")
    for k, v in metrics.items():
        if k == "var_es":
            continue  # show separately
        table.add_row(k, f"{v:.6f}" if isinstance(v, float) else str(v))
    console.print(table)

    # Display VaR/ES backtest results
    var_es = metrics.get("var_es", {})
    if var_es:
        vt = Table(title="VaR/ES Backtest Results")
        vt.add_column("Alpha", style="cyan")
        vt.add_column("Violations", style="yellow")
        vt.add_column("Rate", style="yellow")
        vt.add_column("Expected", style="dim")
        vt.add_column("Kupiec", style="green")
        vt.add_column("Christoffersen", style="green")
        vt.add_column("ES Ratio", style="blue")
        for key, val in var_es.items():
            if isinstance(val, dict):
                kupiec_status = "✓ PASS" if val["kupiec"]["conclusion"] == "fail_to_reject" else "✗ FAIL"
                christo_status = "✓ PASS" if val["christoffersen"]["conclusion"] == "independent" else "✗ FAIL"
                vt.add_row(
                    f"{val['alpha']:.2f}",
                    str(val["n_violations"]),
                    f"{val['violation_rate']:.4f}",
                    f"{val['expected_rate']:.4f}",
                    kupiec_status,
                    christo_status,
                    f"{val['es_ratio']:.3f}" if not (val["es_ratio"] != val["es_ratio"]) else "N/A",
                )
        console.print(vt)

    # Output as JSON for Claude Code to parse
    output = {
        "experiment_id": exp_config.experiment_id,
        "model": model,
        "asset": asset,
        "metrics": metrics,
        "n_forecasts": len(result.forecasts),
        "fit_time": result.fit_time,
    }
    console.print(f"\n[dim]JSON: {json.dumps(output, default=str)}[/dim]")


@cli.command()
@click.option("--asset", required=True, help="Ticker symbol")
@click.option("--start", default=None, help="Start date")
@click.option("--end", default=None, help="End date")
def analyze_data(asset: str, start: str | None, end: str | None) -> None:
    """Analyze data characteristics of an asset."""
    import numpy as np
    from scipy import stats

    from volpred.data.manager import DataManager

    dm = DataManager()
    start = start or "2010-01-01"
    end = end or "2025-12-31"

    data = dm.get_model_data(asset, start, end)
    returns = data["returns"].dropna()

    console.print(f"[bold blue]Data Analysis: {asset}[/bold blue]")
    console.print(f"  Period: {data.index[0].date()} -> {data.index[-1].date()}")
    console.print(f"  Observations: {len(returns)}")

    analysis: dict = {
        "asset": asset,
        "n_obs": len(returns),
        "start": str(data.index[0].date()),
        "end": str(data.index[-1].date()),
        "mean_return": float(returns.mean()),
        "std_return": float(returns.std()),
        "annualized_vol": float(returns.std() * np.sqrt(252)),
        "skewness": float(stats.skew(returns)),
        "kurtosis": float(stats.kurtosis(returns)),
        "jarque_bera_stat": float(stats.jarque_bera(returns).statistic),
        "jarque_bera_pval": float(stats.jarque_bera(returns).pvalue),
        "min_return": float(returns.min()),
        "max_return": float(returns.max()),
    }

    # ARCH effect test (Engle's ARCH LM test)
    try:
        from statsmodels.stats.diagnostic import het_arch

        resid = returns - returns.mean()
        arch_test = het_arch(resid.values, nlags=5)
        analysis["arch_lm_stat"] = float(arch_test[0])
        analysis["arch_lm_pval"] = float(arch_test[1])
    except ImportError:
        pass

    table = Table(title=f"{asset} Data Characteristics")
    table.add_column("Property", style="cyan")
    table.add_column("Value", style="green")
    for k, v in analysis.items():
        if isinstance(v, float):
            table.add_row(k, f"{v:.6f}")
        else:
            table.add_row(k, str(v))
    console.print(table)

    console.print(f"\n[dim]JSON: {json.dumps(analysis, default=str)}[/dim]")


@cli.command()
@click.option("--ids", required=True, help="Comma-separated experiment IDs")
@click.option("--metric", default="qlike", help="Primary metric for ranking")
def compare(ids: str, metric: str) -> None:
    """Compare multiple experiments."""
    from volpred.memory.system import MemorySystem

    memory = MemorySystem()
    exp_ids = [i.strip() for i in ids.split(",")]

    results: list[dict] = []
    for eid in exp_ids:
        exp = memory.load_experiment(eid)
        if exp:
            results.append(exp)
        else:
            console.print(f"[yellow]Warning: Experiment {eid} not found[/yellow]")

    if not results:
        console.print("[red]No experiments found[/red]")
        return

    # Sort by metric
    results.sort(key=lambda x: x.get("metrics", {}).get(metric, float("inf")))

    table = Table(title=f"Experiment Comparison (ranked by {metric})")
    table.add_column("Rank", style="bold")
    table.add_column("ID", style="cyan")
    table.add_column("Model", style="blue")
    table.add_column(metric.upper(), style="green")
    table.add_column("MSE", style="yellow")
    table.add_column("MAE", style="yellow")
    table.add_column("Forecasts", style="dim")
    table.add_column("Time(s)", style="dim")

    for i, r in enumerate(results, 1):
        m = r.get("metrics", {})
        table.add_row(
            str(i),
            r["experiment_id"],
            r["model_name"],
            f"{m.get(metric, 'N/A'):.6f}" if isinstance(m.get(metric), (int, float)) else "N/A",
            f"{m.get('mse', 'N/A'):.6f}" if isinstance(m.get("mse"), (int, float)) else "N/A",
            f"{m.get('mae', 'N/A'):.6f}" if isinstance(m.get("mae"), (int, float)) else "N/A",
            str(m.get("n_forecasts", "N/A")),
            f"{r.get('fit_time', 0):.1f}",
        )

    console.print(table)

    comparison = {
        "ranking": [
            {
                "rank": i + 1,
                "experiment_id": r["experiment_id"],
                "model_name": r["model_name"],
                "metrics": r.get("metrics", {}),
            }
            for i, r in enumerate(results)
        ]
    }
    console.print(f"\n[dim]JSON: {json.dumps(comparison, default=str)}[/dim]")


@cli.command()
def list_models() -> None:
    """List all registered models."""
    import volpred.models.garch  # noqa: F401 — trigger registration

    from volpred.models.registry import ModelRegistry

    models = ModelRegistry.list_models()
    console.print("[bold blue]Registered Models:[/bold blue]")
    for m in models:
        console.print(f"  - {m}")


@cli.command()
def summary() -> None:
    """Show research summary."""
    from volpred.memory.system import MemorySystem

    memory = MemorySystem()
    s = memory.get_summary()

    console.print("[bold blue]Research Summary[/bold blue]")
    console.print(f"  Experiments: {s['n_experiments']}")
    console.print(f"  Log entries: {s['n_log_entries']}")
    console.print(f"  Knowledge items: {s['n_knowledge_items']}")
    console.print(f"  Assets studied: {s['assets_studied']}")

    if s["best_models"]:
        console.print("\n[bold]Top models (by QLIKE):[/bold]")
        for m in s["best_models"]:
            console.print(
                f"  {m['experiment_id']}: {m['model_name']} -> QLIKE={m.get('qlike', 'N/A'):.6f}"
            )

    console.print(f"\n[dim]JSON: {json.dumps(s, default=str)}[/dim]")


@cli.command()
@click.option("--experiment-id", required=True, help="Experiment ID to publish")
@click.option("--title", default=None, help="Publication title (auto-generated if not provided)")
def publish(experiment_id: str, title: str | None) -> None:
    """[DEPRECATED] Publish experiment results to the feed.

    ⚠️ This is a legacy path. It hard-codes status='published' and lacks
    --status / --audience / --tags options. For the standard flow use:
      uv run volpred ops publish-milestone --status draft \\
          --audience research --title '...' --description '...' --phase '...'
    Or the one-stop: scripts/record_and_publish.py
    """
    import sys

    from volpred.memory.system import MemorySystem
    from volpred.publisher.publisher import Publisher

    console.print(
        "[yellow]⚠️  'volpred publish' is legacy — status is hard-coded to 'published'.\n"
        "   For drafts, tags, or audience control, use:\n"
        "     volpred ops publish-milestone --status draft --audience research ...\n"
        "   Or the one-stop: scripts/record_and_publish.py[/yellow]",
        file=sys.stderr,
    )

    memory = MemorySystem()
    exp = memory.load_experiment(experiment_id)
    if not exp:
        console.print(f"[red]Experiment {experiment_id} not found[/red]")
        return

    if title is None:
        model_name = exp.get("model_name", "unknown")
        asset = exp.get("asset", "unknown")
        title = f"{model_name} on {asset} — {experiment_id}"

    metrics = exp.get("metrics", {})
    summary_text = ", ".join(f"{k}={v:.6f}" if isinstance(v, float) else f"{k}={v}"
                             for k, v in metrics.items() if k != "var_es")

    publisher = Publisher()
    pub_id = publisher.publish_experiment(
        experiment_id=experiment_id,
        title=title,
        summary=summary_text,
        metrics=metrics,
        tags=[exp.get("model_name", ""), exp.get("asset", "")],
    )

    console.print(f"[green]Published![/green] ID: {pub_id}")
    console.print(f"  Title: {title}")
    console.print(f"  Feed: storage/reports/feed.json")


@cli.command()
@click.option("--subject", required=True, help="Notification subject")
@click.option("--body", required=True, help="Notification body")
@click.option("--level", default="info", help="Level: info, milestone, alert, error")
def notify(subject: str, body: str, level: str) -> None:
    """Send a notification."""
    from volpred.publisher.email_notifier import EmailNotifier

    notifier = EmailNotifier()
    notif_id = notifier.notify(subject=subject, body=body, level=level)

    console.print(f"[green]Notification sent![/green] ID: {notif_id}")
    console.print(f"  Subject: {subject}")
    console.print(f"  Level: {level}")
    console.print(f"  Log: storage/notifications/notification_log.json")


@cli.group()
def ops() -> None:
    """Agent-first operations for publishing, sync, strategy, and health."""
    pass


@ops.group("agent-spec")
def ops_agent_spec() -> None:
    """Provider-neutral canonical specs for CLAUDE/AGENTS and shared skills."""
    pass


@ops_agent_spec.command("import")
@click.option("--from", "source_name", required=True, type=click.Choice(["claude", "codex"]), help="Source provider tree to import into agent-specs/")
@click.option("--skip-guide", is_flag=True, help="Import only skills")
@click.option("--skip-skills", is_flag=True, help="Import only the top-level guide")
def ops_agent_spec_import(source_name: str, skip_guide: bool, skip_skills: bool) -> None:
    """Import provider-native guide/skills into the canonical agent-specs tree."""
    from volpred.ops import import_agent_specs

    result = import_agent_specs(
        source=source_name,
        include_guide=not skip_guide,
        include_skills=not skip_skills,
    )
    console.print(f"[green]Imported agent specs[/green] from {source_name}")
    _print_json(result)


@ops_agent_spec.command("render")
@click.option("--target", "target_name", default="all", show_default=True, type=click.Choice(["all", "claude", "codex"]), help="Render one provider or both")
def ops_agent_spec_render(target_name: str) -> None:
    """Render canonical agent-specs back into CLAUDE/AGENTS outputs."""
    from volpred.ops import render_agent_specs

    result = render_agent_specs(target_key=None if target_name == "all" else target_name)
    console.print(f"[green]Rendered agent specs[/green] target={target_name}")
    _print_json(result)


@ops_agent_spec.command("check")
@click.option("--target", "target_name", default="all", show_default=True, type=click.Choice(["all", "claude", "codex"]), help="Check one provider or both")
def ops_agent_spec_check(target_name: str) -> None:
    """Fail when rendered CLAUDE/AGENTS outputs drift away from canonical agent-specs."""
    from volpred.ops import check_agent_specs

    result = check_agent_specs(target_key=None if target_name == "all" else target_name)
    if result["clean"]:
        console.print(f"[green]Agent spec outputs are clean[/green] target={target_name}")
    else:
        console.print(f"[red]Agent spec drift detected[/red] target={target_name}")
        for issue in result["issues"]:
            console.print(f"  - {issue}")
    _print_json(result)
    if not result["clean"]:
        raise SystemExit(1)


@ops_agent_spec.command("sync")
@click.option("--from", "source_name", required=True, type=click.Choice(["claude", "codex"]), help="Source provider tree to import into agent-specs/")
def ops_agent_spec_sync(source_name: str) -> None:
    """Import, render, and verify canonical agent specs in one step."""
    from volpred.ops import sync_agent_specs

    result = sync_agent_specs(source=source_name)
    clean = bool(result["check"]["clean"])
    if clean:
        console.print(f"[green]Synced agent specs[/green] from {source_name}")
    else:
        console.print(f"[red]Agent spec sync drift detected[/red] from {source_name}")
        for issue in result["check"]["issues"]:
            console.print(f"  - {issue}")
    _print_json(result)
    if not clean:
        raise SystemExit(1)


@ops.group("rollback")
def ops_rollback() -> None:
    """Rollback points for local repo + storage + config recovery."""
    pass


@ops_rollback.command("create")
@click.option("--point-id", default=None, help="Optional stable rollback point id")
@click.option("--storage-dir", default="storage", show_default=True, help="Storage directory")
def ops_rollback_create(point_id: str | None, storage_dir: str) -> None:
    """Create a rollback point covering tracked diff, untracked files, storage, and config."""
    from volpred.ops import create_rollback_point

    result = create_rollback_point(point_id=point_id, storage_dir=storage_dir)
    console.print(f"[green]Created rollback point[/green] {result['point_id']}")
    _print_json(result)


@ops_rollback.command("list")
@click.option("--storage-dir", default="storage", show_default=True, help="Storage directory")
def ops_rollback_list(storage_dir: str) -> None:
    """List local rollback points."""
    from volpred.ops import list_rollback_points

    points = list_rollback_points(storage_dir=storage_dir)
    table = Table(title="Rollback Points")
    table.add_column("ID", style="cyan")
    table.add_column("Created", style="green")
    table.add_column("Branch", style="white")
    table.add_column("Head", style="magenta")
    for point in points:
        table.add_row(
            str(point.get("point_id", "")),
            str(point.get("created_at", "")),
            str(point.get("branch", "")),
            str(point.get("head_sha", ""))[:12],
        )
    console.print(table)
    _print_json({"points": points})


@ops_rollback.command("restore")
@click.argument("point_id")
@click.option("--storage-dir", default="storage", show_default=True, help="Storage directory")
@click.option("--force", is_flag=True, help="Allow restore even when current HEAD differs from the rollback baseline")
@click.option("--dry-run", is_flag=True, help="Only show what would be removed/restored")
def ops_rollback_restore(point_id: str, storage_dir: str, force: bool, dry_run: bool) -> None:
    """Restore the repo working tree + local state to a named rollback point."""
    from volpred.ops import restore_rollback_point

    result = restore_rollback_point(point_id, storage_dir=storage_dir, force=force, dry_run=dry_run)
    if dry_run:
        console.print(f"[yellow]Dry run[/yellow] rollback restore {point_id}")
    else:
        console.print(f"[green]Restored rollback point[/green] {point_id}")
    _print_json(result)


@ops.command("hygiene-report")
def ops_hygiene_report() -> None:
    """Report repo clutter hotspots and worktree hygiene candidates."""
    from volpred.ops import build_hygiene_report

    report = build_hygiene_report()
    console.print("[green]Repo hygiene snapshot[/green]")
    console.print(f"  root_clutter={len(report['root_clutter'])}")
    console.print(f"  experiments_loose_files={report['experiments_loose_files']}")
    console.print(f"  orphan_worktree_dirs={len(report['orphan_worktree_dirs'])}")
    _print_json(report)


@ops.group("experiments")
def ops_experiments() -> None:
    """Inspect and gradually normalize experiments/ structure."""


@ops_experiments.command("report")
@click.option("--limit", default=20, show_default=True, type=int, help="Max candidate groups to include")
def ops_experiments_report(limit: int) -> None:
    """Report loose top-level experiment files and migration candidates."""
    from volpred.ops import build_experiments_report

    report = build_experiments_report(limit=limit)
    console.print("[green]Experiments hygiene snapshot[/green]")
    console.print(f"  loose_files={report['loose_file_count']}")
    console.print(f"  top_level_dirs={report['top_level_dir_count']}")
    console.print(f"  candidate_groups={report['candidate_count']}")
    if report["grouped_candidates"]:
        table = Table(title="Top migration candidates")
        table.add_column("Experiment", style="cyan")
        table.add_column("Loose", style="yellow")
        table.add_column("Dir", style="magenta")
        table.add_column("Script", style="green")
        table.add_column("Results", style="green")
        table.add_column("Action", style="white")
        for item in report["grouped_candidates"]:
            table.add_row(
                str(item["experiment_id"]),
                str(item["loose_count"]),
                "yes" if item["has_experiment_dir"] else "no",
                "yes" if item["has_canonical_script"] else "no",
                "yes" if item["has_canonical_results"] else "no",
                str(item["recommended_action"]),
            )
        console.print(table)
    _print_json(report)


@ops_experiments.command("scaffold")
@click.option("--experiment-id", required=True, help="Canonical experiment id, e.g. k1121")
@click.option("--title", default=None, help="Optional README/results title")
@click.option("--no-script", is_flag=True, help="Skip creating the canonical script file")
@click.option("--no-results", is_flag=True, help="Skip creating the canonical results JSON")
@click.option("--overwrite", is_flag=True, help="Overwrite existing scaffold files")
def ops_experiments_scaffold(
    experiment_id: str,
    title: str | None,
    no_script: bool,
    no_results: bool,
    overwrite: bool,
) -> None:
    """Create the canonical experiments/<id>/ scaffold for a touched experiment."""
    from volpred.ops import scaffold_experiment

    result = scaffold_experiment(
        experiment_id,
        title=title,
        create_script=not no_script,
        create_results=not no_results,
        overwrite=overwrite,
    )
    console.print(f"[green]Prepared experiment scaffold[/green] {result['target_dir']}")
    _print_json(result)


@ops_experiments.command("migrate")
@click.option("--experiment-id", required=True, help="Experiment id to migrate from loose top-level files")
@click.option("--title", default=None, help="Optional title for scaffolded README")
@click.option("--apply", "apply_changes", is_flag=True, help="Actually move files into experiments/<id>/")
@click.option("--rewrite-references", is_flag=True, help="Rewrite repo text references from old loose paths to new canonical paths")
@click.option("--overwrite", is_flag=True, help="Allow overwriting canonical targets during apply")
@click.option("--no-scaffold", is_flag=True, help="Do not ensure README/references/data exist first")
def ops_experiments_migrate(
    experiment_id: str,
    title: str | None,
    apply_changes: bool,
    rewrite_references: bool,
    overwrite: bool,
    no_scaffold: bool,
) -> None:
    """Plan or apply a touched-file migration into experiments/<id>/."""
    from volpred.ops import migrate_experiment_files

    result = migrate_experiment_files(
        experiment_id,
        apply_changes=apply_changes,
        ensure_scaffold=not no_scaffold,
        rewrite_references=rewrite_references,
        overwrite=overwrite,
        title=title,
    )
    mode = "Applied migration" if apply_changes else "Dry-run migration plan"
    console.print(f"[green]{mode}[/green] for {experiment_id}")
    _print_json(result)


@ops_experiments.command("adopt")
@click.option("--experiment-id", required=True, help="Canonical experiment id for the target directory")
@click.option("--source", "source_files", multiple=True, required=True, help="Repo-relative source file to move into experiments/<id>/")
@click.option("--title", default=None, help="Optional title for scaffolded README")
@click.option("--apply", "apply_changes", is_flag=True, help="Actually move files into experiments/<id>/")
@click.option("--rewrite-references", is_flag=True, help="Rewrite repo text references from old paths to new canonical paths")
@click.option("--overwrite", is_flag=True, help="Allow overwriting canonical targets during apply")
@click.option("--no-scaffold", is_flag=True, help="Do not ensure README/references/data exist first")
@click.option("--no-placeholder-script", is_flag=True, help="Skip creating a placeholder canonical script when no .py source is provided")
@click.option("--no-placeholder-results", is_flag=True, help="Skip creating a placeholder canonical results JSON when no .json source is provided")
def ops_experiments_adopt(
    experiment_id: str,
    source_files: tuple[str, ...],
    title: str | None,
    apply_changes: bool,
    rewrite_references: bool,
    overwrite: bool,
    no_scaffold: bool,
    no_placeholder_script: bool,
    no_placeholder_results: bool,
) -> None:
    """Adopt arbitrary loose files into experiments/<id>/."""
    from volpred.ops import adopt_experiment_files

    result = adopt_experiment_files(
        experiment_id,
        source_files=list(source_files),
        apply_changes=apply_changes,
        ensure_scaffold=not no_scaffold,
        rewrite_references=rewrite_references,
        overwrite=overwrite,
        title=title,
        create_placeholder_script=False if no_placeholder_script else None,
        create_placeholder_results=False if no_placeholder_results else None,
    )
    mode = "Applied arbitrary adoption" if apply_changes else "Dry-run arbitrary adoption"
    console.print(f"[green]{mode}[/green] for {experiment_id}")
    _print_json(result)


@ops.command("assign")
@click.option("--title", required=True, help="Task title")
@click.option("--description", required=True, help="Task description")
@click.option("--source", default="user", show_default=True, type=click.Choice(LOCAL_TASK_SOURCE_CHOICES), help="Task source")
@click.option("--task-family", default="ops", show_default=True, type=click.Choice(LOCAL_TASK_FAMILY_CHOICES), help="Task family")
@click.option("--priority", default=100, show_default=True, type=int, help="Lower runs earlier within the same source")
@click.option("--preferred-agent", default="auto", show_default=True, type=click.Choice(LOCAL_TASK_AGENT_CHOICES), help="Preferred agent")
@click.option("--fallback-allowed/--no-fallback", default=False, show_default=True, help="Allow the other agent to take over")
@click.option("--approval-mode", default="auto", show_default=True, type=click.Choice(LOCAL_APPROVAL_MODE_CHOICES), help="Approval policy")
@click.option("--risk-level", default="safe", show_default=True, type=click.Choice(LOCAL_RISK_LEVEL_CHOICES), help="Risk level")
@click.option("--public-effect", default="none", show_default=True, type=click.Choice(LOCAL_PUBLIC_EFFECT_CHOICES), help="User-visible impact level")
@click.option("--governance-area", default=None, type=click.Choice(LOCAL_GOVERNANCE_AREA_CHOICES), help="Optional governance lane, e.g. schedule")
@click.option("--schedule-proposal-json", default=None, help="JSON object or file path describing a proposed schedule change")
@click.option("--payload-json", default=None, help="JSON object or file path for structured payload")
@click.option("--parent-task-id", default=None, help="Optional parent task id")
@click.option("--created-by", default=None, help="Actor label")
@click.option("--storage-dir", default="storage", show_default=True, help="Storage directory")
def ops_assign(
    title: str,
    description: str,
    source: str,
    task_family: str,
    priority: int,
    preferred_agent: str,
    fallback_allowed: bool,
    approval_mode: str,
    risk_level: str,
    public_effect: str,
    governance_area: str | None,
    schedule_proposal_json: str | None,
    payload_json: str | None,
    parent_task_id: str | None,
    created_by: str | None,
    storage_dir: str,
) -> None:
    """Create a task in the local file-backed control plane."""
    from volpred.ops import create_task

    payload = _parse_json_input(payload_json, default={})
    if not isinstance(payload, dict):
        raise click.ClickException("--payload-json must decode to an object")
    payload = dict(payload)
    if governance_area:
        payload["governance_area"] = governance_area
    if schedule_proposal_json is not None:
        schedule_proposal = _parse_json_input(schedule_proposal_json, default={})
        if not isinstance(schedule_proposal, dict):
            raise click.ClickException("--schedule-proposal-json must decode to an object")
        payload["schedule_proposal"] = schedule_proposal
        payload.setdefault("governance_area", "schedule")
    task = create_task(
        title=title,
        description=description,
        source=source,
        task_family=task_family,
        priority=priority,
        preferred_agent=preferred_agent,
        fallback_allowed=fallback_allowed,
        approval_mode=approval_mode,
        risk_level=risk_level,
        public_effect=public_effect,
        payload=payload,
        parent_task_id=parent_task_id,
        created_by=created_by,
        storage_dir=storage_dir,
    )
    console.print(f"[green]Queued local task[/green] {task['id']} ({task['status']})")
    _print_json(task)


@ops.command("propose-schedule")
@click.option("--title", required=True, help="Proposal title")
@click.option("--description", required=True, help="Why the schedule change is needed")
@click.option("--proposal-json", required=True, help="JSON object or file path describing the schedule proposal")
@click.option("--source", default="agent", show_default=True, type=click.Choice(LOCAL_TASK_SOURCE_CHOICES), help="Task source")
@click.option("--priority", default=80, show_default=True, type=int, help="Lower runs earlier within the same source")
@click.option("--approval-mode", default="auto", show_default=True, type=click.Choice(LOCAL_APPROVAL_MODE_CHOICES), help="Approval policy")
@click.option("--risk-level", default="safe", show_default=True, type=click.Choice(LOCAL_RISK_LEVEL_CHOICES), help="Risk level")
@click.option("--public-effect", default="none", show_default=True, type=click.Choice(LOCAL_PUBLIC_EFFECT_CHOICES), help="User-visible impact level")
@click.option("--created-by", default=None, help="Actor label")
@click.option("--storage-dir", default="storage", show_default=True, help="Storage directory")
def ops_propose_schedule(
    title: str,
    description: str,
    proposal_json: str,
    source: str,
    priority: int,
    approval_mode: str,
    risk_level: str,
    public_effect: str,
    created_by: str | None,
    storage_dir: str,
) -> None:
    """Create a schedule-governance task that is always routed to Claude."""
    from volpred.ops import create_task

    proposal = _parse_json_input(proposal_json, default={})
    if not isinstance(proposal, dict):
        raise click.ClickException("--proposal-json must decode to an object")
    payload = {
        "governance_area": "schedule",
        "schedule_proposal": proposal,
    }
    task = create_task(
        title=title,
        description=description,
        source=source,
        task_family="ops",
        priority=priority,
        preferred_agent="auto",
        fallback_allowed=False,
        approval_mode=approval_mode,
        risk_level=risk_level,
        public_effect=public_effect,
        payload=payload,
        created_by=created_by,
        storage_dir=storage_dir,
    )
    console.print(f"[green]Queued schedule proposal[/green] {task['id']} ({task['status']})")
    _print_json(task)


@ops.command("tasks")
@click.option("--status", default=None, help="Filter by task status")
@click.option("--source", default=None, type=click.Choice(LOCAL_TASK_SOURCE_CHOICES), help="Filter by task source")
@click.option("--limit", default=20, show_default=True, type=int, help="Max tasks to show")
@click.option("--storage-dir", default="storage", show_default=True, help="Storage directory")
def ops_tasks(status: str | None, source: str | None, limit: int, storage_dir: str) -> None:
    """List local control-plane tasks."""
    from volpred.ops import list_local_tasks

    tasks = list_local_tasks(status=status, source=source, limit=limit, storage_dir=storage_dir)
    table = Table(title="Local Tasks")
    table.add_column("ID", style="cyan")
    table.add_column("Source", style="yellow")
    table.add_column("Family", style="magenta")
    table.add_column("Status", style="green")
    table.add_column("Preferred", style="white")
    table.add_column("Priority", style="white")
    table.add_column("Title", style="white")
    for task in tasks:
        table.add_row(
            str(task.get("id", ""))[:16],
            str(task.get("source", "")),
            str(task.get("task_family", "")),
            str(task.get("status", "")),
            str(task.get("preferred_agent", "")),
            str(task.get("priority", "")),
            str(task.get("title", "")),
        )
    console.print(table)
    _print_json({"tasks": tasks})


@ops.command("task-show")
@click.argument("task_id")
@click.option("--storage-dir", default="storage", show_default=True, help="Storage directory")
def ops_task_show(task_id: str, storage_dir: str) -> None:
    """Show one local control-plane task with approvals and execution receipts."""
    from volpred.ops import get_local_task

    task = get_local_task(task_id, storage_dir=storage_dir)
    if task is None:
        raise click.ClickException(f"Task not found: {task_id}")
    _print_json(task)


@ops.command("brief-show")
@click.argument("task_id")
@click.option("--storage-dir", default="storage", show_default=True, help="Storage directory")
def ops_brief_show(task_id: str, storage_dir: str) -> None:
    """Show the current brief, template-derived brief, or supervisor skeleton for one task."""
    from volpred.ops import preview_execution_brief

    try:
        result = preview_execution_brief(task_id, storage_dir=storage_dir)
    except RuntimeError as exc:
        raise click.ClickException(str(exc)) from exc
    _print_json(result)


@ops.command("brief-set")
@click.argument("task_id")
@click.option("--brief-json", required=True, help="JSON object or file path describing the execution brief")
@click.option("--actor", required=True, help="Supervisor actor label")
@click.option("--storage-dir", default="storage", show_default=True, help="Storage directory")
def ops_brief_set(task_id: str, brief_json: str, actor: str, storage_dir: str) -> None:
    """Validate and store a supervisor-authored execution brief."""
    from volpred.ops import set_execution_brief

    payload = _parse_json_input(brief_json, default={})
    if not isinstance(payload, dict):
        raise click.ClickException("--brief-json must decode to an object")
    try:
        task = set_execution_brief(task_id, brief_payload=payload, actor=actor, storage_dir=storage_dir)
    except RuntimeError as exc:
        raise click.ClickException(str(exc)) from exc
    except ValidationError as exc:
        raise click.ClickException(str(exc)) from exc
    console.print(f"[green]Stored execution brief[/green] {task_id}")
    _print_json(task)


@ops.command("agents")
@click.option("--storage-dir", default="storage", show_default=True, help="Storage directory")
def ops_agents(storage_dir: str) -> None:
    """List agent sessions in the local control plane."""
    from volpred.ops import list_agent_sessions

    agents = list_agent_sessions(storage_dir=storage_dir)
    table = Table(title="Agent Sessions")
    table.add_column("Session Key", style="cyan")
    table.add_column("Agent", style="cyan")
    table.add_column("Role", style="white")
    table.add_column("Status", style="green")
    table.add_column("Claimed Task", style="magenta")
    table.add_column("Terminal", style="white")
    table.add_column("Heartbeat", style="dim")
    for agent in agents:
        table.add_row(
            str(agent.get("session_key", "")),
            str(agent.get("agent_name", "")),
            str(agent.get("role", "worker")),
            str(agent.get("status", "")),
            str(agent.get("claimed_task_id", "")),
            str(agent.get("terminal_label") or ""),
            str(agent.get("heartbeat_at", "")),
        )
    console.print(table)
    _print_json({"agents": agents})


@ops.command("heartbeat")
@click.option("--agent", "agent_name", default=None, type=click.Choice(LOCAL_AGENT_CHOICES), help="Agent name (legacy; use --session-key for canonical identity)")
@click.option("--session-key", default=None, type=click.Choice(LOCAL_SESSION_KEY_CHOICES), help="Canonical session key (claude-supervisor / claude-worker / codex-worker)")
@click.option("--role", default=None, type=click.Choice(LOCAL_AGENT_ROLE_CHOICES), help="Agent role (supervisor or worker); defaults to worker when only --agent is supplied")
@click.option("--terminal-label", default=None, help="Human-readable terminal label (e.g. 'VSCode T2')")
@click.option("--status", default="idle", show_default=True, type=click.Choice(["online", "idle", "busy", "offline"]), help="Agent status")
@click.option("--provider", default=None, help="Provider/runtime label")
@click.option("--claimed-task-id", default=None, help="Currently claimed task id")
@click.option("--capabilities-json", default=None, help="JSON array or comma-separated capability list")
@click.option("--role-profile", default=None, help="Role profile label")
@click.option("--session-id", default=None, help="Stable session id")
@click.option("--subagent-budget", default=None, type=int, help="Max concurrent subagents inside one top-level task")
@click.option("--storage-dir", default="storage", show_default=True, help="Storage directory")
def ops_heartbeat(
    agent_name: str | None,
    session_key: str | None,
    role: str | None,
    terminal_label: str | None,
    status: str,
    provider: str | None,
    claimed_task_id: str | None,
    capabilities_json: str | None,
    role_profile: str | None,
    session_id: str | None,
    subagent_budget: int | None,
    storage_dir: str,
) -> None:
    """Create/update an agent heartbeat in the local control plane."""
    from volpred.ops import heartbeat_agent

    resolved_key, resolved_agent, resolved_role = _resolve_agent_session_cli(
        agent_name, session_key, role
    )
    capabilities = _parse_string_list_input(capabilities_json) if capabilities_json else None
    session = heartbeat_agent(
        session_key=resolved_key,
        role=resolved_role,
        terminal_label=terminal_label,
        status=status,
        provider=provider,
        claimed_task_id=claimed_task_id,
        capabilities=capabilities,
        role_profile=role_profile,
        session_id=session_id,
        subagent_budget=subagent_budget,
        storage_dir=storage_dir,
    )
    console.print(f"[green]Heartbeat updated[/green] {resolved_key}")
    _print_json(session)


@ops.command("session-bootstrap")
@click.option("--agent", "agent_name", default=None, type=click.Choice(LOCAL_AGENT_CHOICES), help="Agent name (legacy)")
@click.option("--session-key", default=None, type=click.Choice(LOCAL_SESSION_KEY_CHOICES), help="Canonical session key")
@click.option("--role", default=None, type=click.Choice(LOCAL_AGENT_ROLE_CHOICES), help="Agent role (defaults to worker)")
@click.option("--terminal-label", default=None, help="Human-readable terminal label")
@click.option("--session-id", default=None, help="Stable session id")
@click.option("--rollback-point-id", default=None, help="Optional stable rollback point id")
@click.option("--agent-spec-path", default=None, help="Legacy optional agent-spec guide path or agent-specs directory")
@click.option("--no-guide", is_flag=True, help="Skip loading bootstrap guide metadata")
@click.option("--storage-dir", default="storage", show_default=True, help="Storage directory")
def ops_session_bootstrap(
    agent_name: str | None,
    session_key: str | None,
    role: str | None,
    terminal_label: str | None,
    session_id: str | None,
    rollback_point_id: str | None,
    agent_spec_path: str | None,
    no_guide: bool,
    storage_dir: str,
) -> None:
    """Bootstrap a Claude/Codex session with rollback, optional guide metadata, and heartbeat."""
    from volpred.ops import session_bootstrap

    resolved_key, resolved_agent, resolved_role = _resolve_agent_session_cli(
        agent_name, session_key, role
    )
    try:
        result = session_bootstrap(
            session_key=resolved_key,
            role=resolved_role,
            terminal_label=terminal_label,
            session_id=session_id,
            rollback_point_id=rollback_point_id,
            agent_spec_path=agent_spec_path,
            no_guide=no_guide,
            storage_dir=storage_dir,
        )
    except RuntimeError as exc:
        raise click.ClickException(str(exc)) from exc
    console.print(f"[green]Bootstrapped session[/green] {resolved_key}")
    _print_json(result)


@ops.command("claim-next")
@click.option("--agent", "agent_name", default=None, type=click.Choice(LOCAL_AGENT_CHOICES), help="Agent name (legacy)")
@click.option("--session-key", default=None, type=click.Choice(LOCAL_SESSION_KEY_CHOICES), help="Canonical session key")
@click.option("--role", default=None, type=click.Choice(LOCAL_AGENT_ROLE_CHOICES), help="Agent role")
@click.option("--storage-dir", default="storage", show_default=True, help="Storage directory")
def ops_claim_next(
    agent_name: str | None,
    session_key: str | None,
    role: str | None,
    storage_dir: str,
) -> None:
    """Claim the next eligible task for Claude or Codex."""
    from volpred.ops import claim_next_task

    resolved_key, resolved_agent, resolved_role = _resolve_agent_session_cli(
        agent_name, session_key, role
    )
    task = claim_next_task(session_key=resolved_key, storage_dir=storage_dir)
    if task is None:
        console.print(f"[yellow]No claimable task[/yellow] for {resolved_key}")
        _print_json({"session_key": resolved_key, "agent": resolved_agent, "task": None})
        return
    console.print(f"[green]Claimed task[/green] {task['id']} for {resolved_key}")
    _print_json(task)


@ops.command("next-task")
@click.option("--agent", "agent_name", default=None, type=click.Choice(LOCAL_AGENT_CHOICES), help="Agent name (legacy)")
@click.option("--session-key", default=None, type=click.Choice(LOCAL_SESSION_KEY_CHOICES), help="Canonical session key")
@click.option("--role", default=None, type=click.Choice(LOCAL_AGENT_ROLE_CHOICES), help="Agent role")
@click.option("--emit-brief", is_flag=True, help="Emit execution-brief payload when available")
@click.option("--storage-dir", default="storage", show_default=True, help="Storage directory")
def ops_next_task(
    agent_name: str | None,
    session_key: str | None,
    role: str | None,
    emit_brief: bool,
    storage_dir: str,
) -> None:
    """Thin wrapper around heartbeat + claim-next for a bootstrapped session."""
    from volpred.ops import session_next_task

    resolved_key, resolved_agent, resolved_role = _resolve_agent_session_cli(
        agent_name, session_key, role
    )
    try:
        result = session_next_task(
            session_key=resolved_key,
            role=resolved_role,
            emit_brief=emit_brief,
            storage_dir=storage_dir,
        )
    except RuntimeError as exc:
        raise click.ClickException(str(exc)) from exc
    task = result["task"]
    if task is None:
        console.print(f"[yellow]No claimable task[/yellow] for {resolved_key}")
    else:
        console.print(f"[green]Next task ready[/green] {task['id']} for {resolved_key}")
    _print_json(result)


@ops.command("approve")
@click.argument("task_id")
@click.option("--actor", required=True, help="Approver label")
@click.option("--reason", default=None, help="Approval note")
@click.option("--storage-dir", default="storage", show_default=True, help="Storage directory")
def ops_approve(task_id: str, actor: str, reason: str | None, storage_dir: str) -> None:
    """Approve a queued local task that was waiting for approval."""
    from volpred.ops import approve_task

    task = approve_task(task_id, actor=actor, reason=reason, storage_dir=storage_dir)
    console.print(f"[green]Approved task[/green] {task_id}")
    _print_json(task)


@ops.command("reject")
@click.argument("task_id")
@click.option("--actor", required=True, help="Rejector label")
@click.option("--reason", default=None, help="Rejection note")
@click.option("--storage-dir", default="storage", show_default=True, help="Storage directory")
def ops_reject(task_id: str, actor: str, reason: str | None, storage_dir: str) -> None:
    """Reject a queued local task that was waiting for approval."""
    from volpred.ops import reject_task

    task = reject_task(task_id, actor=actor, reason=reason, storage_dir=storage_dir)
    console.print(f"[green]Rejected task[/green] {task_id}")
    _print_json(task)


@ops.command("requeue-task")
@click.argument("task_id")
@click.option("--actor", required=True, help="Operator label")
@click.option("--reason", required=True, help="Why the blocked task is being requeued")
@click.option("--storage-dir", default="storage", show_default=True, help="Storage directory")
def ops_requeue_task(task_id: str, actor: str, reason: str, storage_dir: str) -> None:
    """Move a blocked task back to queued and record an audit receipt."""
    from volpred.ops import requeue_task

    try:
        result = requeue_task(task_id, actor=actor, reason=reason, storage_dir=storage_dir)
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc
    console.print(f"[green]Requeued task[/green] {task_id}")
    _print_json(result)


@ops.command("complete")
@click.argument("task_id")
@click.option("--agent", "agent_name", default=None, type=click.Choice(LOCAL_AGENT_CHOICES), help="Agent name (legacy)")
@click.option("--session-key", default=None, type=click.Choice(LOCAL_SESSION_KEY_CHOICES), help="Canonical session key")
@click.option("--role", default=None, type=click.Choice(LOCAL_AGENT_ROLE_CHOICES), help="Agent role")
@click.option("--summary", default=None, help="Short result summary")
@click.option("--signals-json", default=None, help="JSON object or file path describing structured signal payload for supervisor curate step")
@click.option("--commands-json", default=None, help="JSON array or comma-separated command list")
@click.option("--files-json", default=None, help="JSON array or comma-separated touched-file list")
@click.option("--subagent-count", default=0, show_default=True, type=int, help="Number of internal subagents used")
@click.option("--storage-dir", default="storage", show_default=True, help="Storage directory")
def ops_complete(
    task_id: str,
    agent_name: str | None,
    session_key: str | None,
    role: str | None,
    summary: str | None,
    signals_json: str | None,
    commands_json: str | None,
    files_json: str | None,
    subagent_count: int,
    storage_dir: str,
) -> None:
    """Mark a local control-plane task as succeeded and store an execution receipt."""
    from volpred.ops import complete_task

    resolved_key, resolved_agent, resolved_role = _resolve_agent_session_cli(
        agent_name, session_key, role
    )
    signal_payload = _parse_signal_payload(signals_json)
    result = complete_task(
        task_id,
        session_key=resolved_key,
        role=resolved_role,
        summary=summary,
        signal_payload=signal_payload,
        commands_run=_parse_string_list_input(commands_json) if commands_json else None,
        files_touched=_parse_string_list_input(files_json) if files_json else None,
        subagent_count=subagent_count,
        storage_dir=storage_dir,
    )
    console.print(f"[green]Completed task[/green] {task_id}")
    _print_json(result)


@ops.command("finish-task")
@click.argument("task_id")
@click.option("--agent", "agent_name", default=None, type=click.Choice(LOCAL_AGENT_CHOICES), help="Agent name (legacy)")
@click.option("--session-key", default=None, type=click.Choice(LOCAL_SESSION_KEY_CHOICES), help="Canonical session key")
@click.option("--role", default=None, type=click.Choice(LOCAL_AGENT_ROLE_CHOICES), help="Agent role")
@click.option("--summary", default=None, help="Short result summary")
@click.option("--signals-json", default=None, help="JSON object or file path describing structured signal payload")
@click.option("--error", default=None, help="Optional error message; when set this records a failed finish")
@click.option("--commands-json", default=None, help="JSON array or comma-separated command list")
@click.option("--files-json", default=None, help="JSON array or comma-separated touched-file list")
@click.option("--subagent-count", default=0, show_default=True, type=int, help="Number of internal subagents used")
@click.option("--storage-dir", default="storage", show_default=True, help="Storage directory")
def ops_finish_task(
    task_id: str,
    agent_name: str | None,
    session_key: str | None,
    role: str | None,
    summary: str | None,
    signals_json: str | None,
    error: str | None,
    commands_json: str | None,
    files_json: str | None,
    subagent_count: int,
    storage_dir: str,
) -> None:
    """Complete or fail a task through the bootstrapped session wrapper."""
    from volpred.ops import session_finish_task

    resolved_key, resolved_agent, resolved_role = _resolve_agent_session_cli(
        agent_name, session_key, role
    )
    signal_payload = _parse_signal_payload(signals_json)
    try:
        result = session_finish_task(
            task_id,
            session_key=resolved_key,
            role=resolved_role,
            summary=summary,
            error=error,
            signal_payload=signal_payload,
            commands_run=_parse_string_list_input(commands_json) if commands_json else None,
            files_touched=_parse_string_list_input(files_json) if files_json else None,
            subagent_count=subagent_count,
            storage_dir=storage_dir,
        )
    except RuntimeError as exc:
        raise click.ClickException(str(exc)) from exc
    if error:
        console.print(f"[green]Finished task as failed[/green] {task_id}")
    else:
        console.print(f"[green]Finished task[/green] {task_id}")
    _print_json(result)


@ops.command("fail")
@click.argument("task_id")
@click.option("--agent", "agent_name", default=None, type=click.Choice(LOCAL_AGENT_CHOICES), help="Agent name (legacy)")
@click.option("--session-key", default=None, type=click.Choice(LOCAL_SESSION_KEY_CHOICES), help="Canonical session key")
@click.option("--role", default=None, type=click.Choice(LOCAL_AGENT_ROLE_CHOICES), help="Agent role")
@click.option("--error", required=True, help="Error message")
@click.option("--summary", default=None, help="Short summary")
@click.option("--signals-json", default=None, help="JSON object or file path describing structured signal payload")
@click.option("--commands-json", default=None, help="JSON array or comma-separated command list")
@click.option("--files-json", default=None, help="JSON array or comma-separated touched-file list")
@click.option("--subagent-count", default=0, show_default=True, type=int, help="Number of internal subagents used")
@click.option("--storage-dir", default="storage", show_default=True, help="Storage directory")
def ops_fail(
    task_id: str,
    agent_name: str | None,
    session_key: str | None,
    role: str | None,
    error: str,
    summary: str | None,
    signals_json: str | None,
    commands_json: str | None,
    files_json: str | None,
    subagent_count: int,
    storage_dir: str,
) -> None:
    """Mark a local control-plane task as failed and store an execution receipt."""
    from volpred.ops import fail_task

    resolved_key, resolved_agent, resolved_role = _resolve_agent_session_cli(
        agent_name, session_key, role
    )
    signal_payload = _parse_signal_payload(signals_json)
    result = fail_task(
        task_id,
        session_key=resolved_key,
        role=resolved_role,
        error=error,
        summary=summary,
        signal_payload=signal_payload,
        commands_run=_parse_string_list_input(commands_json) if commands_json else None,
        files_touched=_parse_string_list_input(files_json) if files_json else None,
        subagent_count=subagent_count,
        storage_dir=storage_dir,
    )
    console.print(f"[green]Marked task failed[/green] {task_id}")
    _print_json(result)


@ops.command("release-task")
@click.argument("task_id")
@click.option("--reason", required=True, help="Why this task is being released back to the queue (logged in last_error + writer log).")
@click.option("--actor", default=None, help="Who is releasing the task (default 'supervisor').")
@click.option("--storage-dir", default="storage", show_default=True, help="Storage directory")
def ops_release_task(
    task_id: str,
    reason: str,
    actor: str | None,
    storage_dir: str,
) -> None:
    """Release a claimed/running task back to queued without writing a fail receipt.

    Use when claim-next pulled the wrong task or the assigned agent is
    blocked (e.g. external CLI broken). Preserves priority and original
    brief so the next claim-next picks it up cleanly. Avoids the
    finish-task --status=failed anti-pattern that pollutes execution
    receipts with false-fails.
    """
    from volpred.ops import release_task

    result = release_task(
        task_id,
        reason=reason,
        actor=actor,
        storage_dir=storage_dir,
    )
    console.print(f"[green]Released task[/green] {task_id} -> queued")
    _print_json({"action": "release_task", "task": result})


@ops.command("session-shutdown")
@click.option("--agent", "agent_name", default=None, type=click.Choice(LOCAL_AGENT_CHOICES), help="Agent name (legacy)")
@click.option("--session-key", default=None, type=click.Choice(LOCAL_SESSION_KEY_CHOICES), help="Canonical session key")
@click.option("--role", default=None, type=click.Choice(LOCAL_AGENT_ROLE_CHOICES), help="Agent role")
@click.option("--storage-dir", default="storage", show_default=True, help="Storage directory")
def ops_session_shutdown(
    agent_name: str | None,
    session_key: str | None,
    role: str | None,
    storage_dir: str,
) -> None:
    """Mark a bootstrapped Claude/Codex session offline."""
    from volpred.ops import session_shutdown

    resolved_key, resolved_agent, resolved_role = _resolve_agent_session_cli(
        agent_name, session_key, role
    )
    try:
        result = session_shutdown(
            session_key=resolved_key, role=resolved_role, storage_dir=storage_dir
        )
    except RuntimeError as exc:
        raise click.ClickException(str(exc)) from exc
    console.print(f"[green]Session offline[/green] {resolved_key}")
    _print_json(result)


@ops.command("pending-curations")
@click.option("--limit", default=None, type=int, help="Limit the number of results")
@click.option("--storage-dir", default="storage", show_default=True, help="Storage directory")
def ops_pending_curations(limit: int | None, storage_dir: str) -> None:
    """List succeeded tasks awaiting supervisor curation (Phase B)."""
    from volpred.ops import list_pending_curations

    pending = list_pending_curations(limit=limit, storage_dir=storage_dir)
    table = Table(title="Pending Curations")
    table.add_column("Task ID", style="cyan")
    table.add_column("Title", style="white")
    table.add_column("Family", style="magenta")
    table.add_column("Finished", style="dim")
    table.add_column("Claimed By", style="green")
    for task in pending:
        table.add_row(
            str(task.get("id", "")),
            str(task.get("title", ""))[:60],
            str(task.get("task_family", "")),
            str(task.get("finished_at", "")),
            str(task.get("claimed_by_session_key") or task.get("claimed_by") or ""),
        )
    console.print(table)
    _print_json({"pending": pending, "count": len(pending)})


@ops.command("curate")
@click.argument("task_id")
@click.option("--actor", required=True, help="Supervisor actor label (e.g. claude-supervisor)")
@click.option("--promoted", default=None, help="JSON array or comma-separated list of canonical destinations promoted to (e.g. knowledge.json,research_program.md)")
@click.option("--notes", default=None, help="Free-text curation notes")
@click.option("--storage-dir", default="storage", show_default=True, help="Storage directory")
def ops_curate(
    task_id: str,
    actor: str,
    promoted: str | None,
    notes: str | None,
    storage_dir: str,
) -> None:
    """Mark a succeeded task as curated and record promotion targets (Phase B)."""
    from volpred.ops import curate_task

    promoted_list = _parse_string_list_input(promoted) if promoted else None
    try:
        task = curate_task(
            task_id,
            actor=actor,
            promoted=promoted_list,
            notes=notes,
            storage_dir=storage_dir,
        )
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc
    console.print(f"[green]Curated task[/green] {task_id}")
    _print_json(task)


@ops.command("control-plane-summary")
@click.option("--storage-dir", default="storage", show_default=True, help="Storage directory")
def ops_control_plane_summary(storage_dir: str) -> None:
    """Summarize local queue/agent state and whether discovery is currently allowed."""
    from volpred.ops import build_control_plane_snapshot

    summary = build_control_plane_snapshot(storage_dir=storage_dir)
    console.print("[green]Local control plane summary[/green]")
    _print_json(summary)


@ops.command("queue-summary")
@click.option("--storage-dir", default="storage", show_default=True, help="Storage directory")
def ops_queue_summary(storage_dir: str) -> None:
    """Show a compact queue summary for token-light routine checks."""
    from volpred.ops import build_queue_summary

    summary = build_queue_summary(storage_dir=storage_dir)
    console.print("[green]Queue summary[/green]")
    _print_json(summary)


@ops.command("continue-task-maintain")
@click.option("--storage-dir", default="storage", show_default=True, help="Storage directory")
@click.option("--stub-if-no-work", is_flag=True, help="Emit a tiny JSON stub when there is no runnable continuation work")
def ops_continue_task_maintain(storage_dir: str, stub_if_no_work: bool) -> None:
    """Run the canonical continuation gate before opening queue/alert detail."""
    from volpred.ops import build_continue_task_maintenance
    from volpred.ops.pending_replay import mark_self_replayed
    mark_self_replayed("continue_task")

    result = build_continue_task_maintenance(storage_dir=storage_dir)
    if stub_if_no_work and result.get("skip"):
        _print_json(
            {
                "skip": True,
                "reason": result.get("reason"),
                "busy": f"{result.get('busy_agent_count', 0)}/{result.get('max_concurrent_agents', 0)}",
            }
        )
        return

    console.print("[green]Continue task maintenance[/green]")
    console.print(
        "  mode={mode} action={action} reason={reason} busy={busy} queued={queued}".format(
            mode=result.get("mode", "unknown"),
            action=result.get("action", "unknown"),
            reason=result.get("reason", "unknown"),
            busy=f"{result.get('busy_agent_count', 0)}/{result.get('max_concurrent_agents', 0)}",
            queued=result.get("queued_count", 0),
        )
    )
    _print_json(result)


@ops.command("daily-planning-maintain")
@click.option("--storage-dir", default="storage", show_default=True, help="Storage directory")
@click.option("--source", default="user", show_default=True, help="Question source to inspect")
@click.option("--limit", default=5, show_default=True, type=int, help="Max rows per compact platform section")
@click.option("--stub-if-no-work", is_flag=True, help="Emit a tiny JSON stub when there are no planning gaps to review")
def ops_daily_planning_maintain(storage_dir: str, source: str, limit: int, stub_if_no_work: bool) -> None:
    """Run the canonical daily-planning gate before opening queue/scheduler/platform detail."""
    from volpred.ops import build_daily_planning_maintenance
    from volpred.ops.pending_replay import mark_self_replayed
    mark_self_replayed("daily_planning")

    result = build_daily_planning_maintenance(storage_dir=storage_dir, source=source, limit=limit)
    if stub_if_no_work and result.get("skip"):
        _print_json(
            {
                "skip": True,
                "action": result.get("action"),
                "reasons": result.get("trigger_reasons", []),
            }
        )
        return

    console.print("[green]Daily planning maintenance[/green]")
    console.print(
        "  mode={mode} action={action} reasons={reasons} queued={queued} missing={missing}".format(
            mode=result.get("mode", "unknown"),
            action=result.get("action", "unknown"),
            reasons=len(result.get("trigger_reasons") or []),
            queued=((result.get("queue") or {}).get("queued") or 0),
            missing=((result.get("scheduler") or {}).get("missing_system_task_count") or 0),
        )
    )
    _print_json(result)


@ops.command("scheduler-summary")
@click.option("--storage-dir", default="storage", show_default=True, help="Storage directory")
def ops_scheduler_summary(storage_dir: str) -> None:
    """Show a compact scheduler + canonical schedule snapshot."""
    from volpred.ops import build_scheduler_summary

    summary = build_scheduler_summary(storage_dir=storage_dir)
    console.print("[green]Scheduler summary[/green]")
    _print_json(summary)


@ops.command("token-summary")
@click.option("--storage-dir", default="storage", show_default=True, help="Storage directory")
@click.option("--days", default=7, show_default=True, type=int, help="Rolling daily-report window")
def ops_token_summary(storage_dir: str, days: int) -> None:
    """Show a compact token/cost summary from stored daily reports."""
    from volpred.ops import build_token_summary

    summary = build_token_summary(storage_dir=storage_dir, days=days)
    console.print("[green]Token summary[/green]")
    _print_json(summary)


@ops.command("token-usage-maintain")
@click.option("--storage-dir", default="storage", show_default=True, help="Storage directory")
@click.option("--days", default=7, show_default=True, type=int, help="Rolling daily-report window")
@click.option("--tail-lines", default=6, show_default=True, type=int, help="Tail lines to keep from generated report commands")
@click.option("--check-only", is_flag=True, help="Plan the maintenance action without generating missing reports")
@click.option("--stub-if-no-work", is_flag=True, help="Emit a tiny JSON stub when daily/weekly token reports are already fresh")
def ops_token_usage_maintain(storage_dir: str, days: int, tail_lines: int, check_only: bool, stub_if_no_work: bool) -> None:
    """Run the canonical token-usage daily/weekly report maintenance loop with optional no-work stub output."""
    from volpred.ops import run_token_usage_maintenance
    from volpred.ops.pending_replay import mark_self_replayed
    mark_self_replayed("token_usage_daily")

    result = run_token_usage_maintenance(
        storage_dir=storage_dir,
        days=days,
        execute=not check_only,
        tail_lines=tail_lines,
    )
    if stub_if_no_work and result.get("skip"):
        _print_json(
            {
                "skip": True,
                "action": result.get("action"),
                "target_date": ((result.get("before") or {}).get("target_date")),
            }
        )
        return

    console.print("[green]Token usage maintenance[/green]")
    console.print(
        "  mode={mode} action={action} before={before} after={after} runs={runs}".format(
            mode=result.get("mode", "unknown"),
            action=result.get("action", "unknown"),
            before=((result.get("before") or {}).get("action") or "unknown"),
            after=result.get("after_action", "unknown"),
            runs=len(result.get("runs") or []),
        )
    )
    _print_json(result)


@ops.command("token-policy-summary")
@click.option("--policy-path", default="config/token_policy.json", show_default=True, help="Token/context policy config")
def ops_token_policy_summary(policy_path: str) -> None:
    """Show the canonical token/context threshold policy used by active workflow guides."""
    from volpred.ops import build_token_policy_summary

    summary = build_token_policy_summary(policy_path=policy_path)
    console.print("[green]Token policy summary[/green]")
    if summary.get("available"):
        digest = summary.get("policy_digest") or {}
        console.print(
            "  direct<{direct} compact>={compact} clear>={clear} statusline={colors}".format(
                direct=digest.get("direct_start_below_pct"),
                compact=digest.get("compact_at_or_above_pct"),
                clear=digest.get("clear_at_or_above_pct"),
                colors="/".join(str(item) for item in digest.get("statusline_colors") or []),
            )
        )
    _print_json(summary)


@ops.command("git-sync-maintain")
@click.option("--stub-if-no-work", is_flag=True, help="Emit a tiny JSON stub when the branch is already clean and synced")
def ops_git_sync_maintain(stub_if_no_work: bool) -> None:
    """Run the canonical git-sync preflight gate before opening full status/diff output."""
    from volpred.ops import build_git_sync_maintenance
    from volpred.ops.pending_replay import mark_self_replayed
    mark_self_replayed("git_sync")

    result = build_git_sync_maintenance()
    if stub_if_no_work and result.get("skip"):
        _print_json(
            {
                "skip": True,
                "action": result.get("action"),
                "branch": result.get("branch"),
            }
        )
        return

    console.print("[green]Git sync maintenance[/green]")
    console.print(
        "  mode={mode} action={action} branch={branch} changes={changes} ahead={ahead} behind={behind}".format(
            mode=result.get("mode", "unknown"),
            action=result.get("action", "unknown"),
            branch=result.get("branch") or "unknown",
            changes=result.get("working_tree_changes", 0),
            ahead=result.get("ahead", 0),
            behind=result.get("behind", 0),
        )
    )
    _print_json(result)


@ops.command("ndc-indicator-maintain")
@click.option("--storage-dir", default="storage", show_default=True, help="Storage directory")
@click.option("--stub-if-no-work", is_flag=True, help="Emit a tiny JSON stub when the NDC canonical CSV is already fresh")
def ops_ndc_indicator_maintain(storage_dir: str, stub_if_no_work: bool) -> None:
    """Run the canonical NDC business-cycle freshness gate before manual update work."""
    from volpred.ops import build_ndc_indicator_maintenance
    from volpred.ops.pending_replay import mark_self_replayed
    mark_self_replayed("ndc_indicator_refresh")

    result = build_ndc_indicator_maintenance(storage_dir=storage_dir)
    if stub_if_no_work and result.get("skip"):
        _print_json(
            {
                "skip": True,
                "action": result.get("action"),
                "expected_period": result.get("expected_period"),
            }
        )
        return

    console.print("[green]NDC indicator maintenance[/green]")
    console.print(
        "  mode={mode} action={action} expected={expected} stale={stale}".format(
            mode=result.get("mode", "unknown"),
            action=result.get("action", "unknown"),
            expected=result.get("expected_period", "unknown"),
            stale=result.get("stale_series_count", 0),
        )
    )
    _print_json(result)


@ops.command("log-summary")
@click.option("--storage-dir", default="storage", show_default=True, help="Storage directory")
@click.option("--limit", default=3, show_default=True, type=int, help="Max recent logs per group")
@click.option("--tail-lines", default=3, show_default=True, type=int, help="Tail lines per log entry")
def ops_log_summary(storage_dir: str, limit: int, tail_lines: int) -> None:
    """Show a compact snapshot of the latest cron/hook logs."""
    from volpred.ops import build_log_summary

    summary = build_log_summary(storage_dir=storage_dir, limit=limit, tail_lines=tail_lines)
    console.print("[green]Log summary[/green]")
    _print_json(summary)


@ops.command("knowledge-index-summary")
@click.option("--storage-dir", default="storage", show_default=True, help="Storage directory")
def ops_knowledge_index_summary(storage_dir: str) -> None:
    """Show a compact knowledge-index freshness/drift snapshot before opening update tooling."""
    from volpred.ops import build_knowledge_index_summary

    summary = build_knowledge_index_summary(storage_dir=storage_dir)
    console.print("[green]Knowledge index summary[/green]")
    console.print(
        "  status={status} entries={entries} changed={changed} action={action}".format(
            status=summary.get("status", "unknown"),
            entries=summary.get("total_entries", 0),
            changed=summary.get("changed_files_count", 0),
            action=summary.get("recommended_action", "unknown"),
        )
    )
    _print_json(summary)


@ops.command("knowledge-index-maintain")
@click.option("--storage-dir", default="storage", show_default=True, help="Storage directory")
@click.option("--tail-lines", default=6, show_default=True, type=int, help="Tail lines to keep from executed command output")
@click.option("--check-only", is_flag=True, help="Plan the maintenance action without executing auto/build")
@click.option("--stub-if-no-work", is_flag=True, help="Emit a tiny JSON stub when the recommended action is skip")
def ops_knowledge_index_maintain(storage_dir: str, tail_lines: int, check_only: bool, stub_if_no_work: bool) -> None:
    """Run the canonical knowledge-index maintenance decision loop with optional no-work stub output."""
    from volpred.ops import run_knowledge_index_maintenance
    from volpred.ops.pending_replay import mark_self_replayed
    mark_self_replayed("knowledge_index_check")

    result = run_knowledge_index_maintenance(
        storage_dir=storage_dir,
        execute=not check_only,
        tail_lines=tail_lines,
    )
    if stub_if_no_work and result.get("skip"):
        _print_json(
            {
                "skip": True,
                "status": result.get("before_status"),
                "action": result.get("action"),
            }
        )
        return

    console.print("[green]Knowledge index maintenance[/green]")
    console.print(
        "  mode={mode} action={action} before={before} after={after} followup={followup}".format(
            mode=result.get("mode", "unknown"),
            action=result.get("action", "unknown"),
            before=result.get("before_status", "unknown"),
            after=result.get("after_status", "unknown"),
            followup="yes" if result.get("needs_followup") else "no",
        )
    )
    _print_json(result)


@ops.command("publication-candidates-summary")
@click.option("--storage-dir", default="storage", show_default=True, help="Storage directory")
@click.option("--limit", default=5, show_default=True, type=int, help="Max rows per candidate bucket")
def ops_publication_candidates_summary(storage_dir: str, limit: int) -> None:
    """Show a compact publication-candidates snapshot for topic selection checks."""
    from volpred.ops import build_publication_candidates_summary

    summary = build_publication_candidates_summary(storage_dir=storage_dir, limit=limit)
    console.print("[green]Publication candidates summary[/green]")
    _print_json(summary)


@ops.command("platform-patrol-summary")
@click.option("--storage-dir", default="storage", show_default=True, help="Storage directory")
@click.option("--source", default="user", show_default=True, help="Question source to inspect")
@click.option("--limit", default=5, show_default=True, type=int, help="Max rows per compact section")
def ops_platform_patrol_summary(storage_dir: str, source: str, limit: int) -> None:
    """Show a compact platform patrol snapshot before opening detailed ops tooling."""
    from volpred.ops import build_platform_patrol_summary

    summary = build_platform_patrol_summary(storage_dir=storage_dir, source=source, limit=limit)
    console.print("[green]Platform patrol summary[/green]")
    console.print(
        "  release_due={release_due} alert_breaches={breaches} pending_questions={pending}".format(
            release_due="yes" if summary.get("release_due") else "no",
            breaches=summary.get("alert_breach_count", 0),
            pending=summary.get("pending_questions", 0),
        )
    )
    _print_json(summary)


@ops.command("platform-patrol-maintain")
@click.option("--storage-dir", default="storage", show_default=True, help="Storage directory")
@click.option("--source", default="user", show_default=True, help="Question source to inspect")
@click.option("--limit", default=5, show_default=True, type=int, help="Max rows per compact section")
@click.option("--stub-if-no-work", is_flag=True, help="Emit a tiny JSON stub when no follow-up inspection is needed")
def ops_platform_patrol_maintain(storage_dir: str, source: str, limit: int, stub_if_no_work: bool) -> None:
    """Run the canonical platform patrol gate with optional no-work stub output."""
    from volpred.ops import build_platform_patrol_maintenance
    from volpred.ops.pending_replay import mark_self_replayed
    mark_self_replayed("platform_patrol")

    result = build_platform_patrol_maintenance(storage_dir=storage_dir, source=source, limit=limit)
    if stub_if_no_work and result.get("skip"):
        _print_json(
            {
                "skip": True,
                "action": result.get("action"),
                "reasons": result.get("trigger_reasons", []),
            }
        )
        return

    console.print("[green]Platform patrol maintenance[/green]")
    console.print(
        "  mode={mode} action={action} release_due={release_due} breaches={breaches} pending={pending}".format(
            mode=result.get("mode", "unknown"),
            action=result.get("action", "unknown"),
            release_due="yes" if result.get("release_due") else "no",
            breaches=result.get("alert_breach_count", 0),
            pending=result.get("pending_questions", 0),
        )
    )
    _print_json(result)


@ops.command("question-ops-summary")
@click.option("--source", default="user", show_default=True, help="Question source to inspect")
@click.option("--limit", default=5, show_default=True, type=int, help="Max rows per compact section")
def ops_question_ops_summary(source: str, limit: int) -> None:
    """Show a compact question-ops snapshot before loading the full rerank workflow."""
    from volpred.ops import build_question_ops_summary

    summary = build_question_ops_summary(source=source, limit=limit)
    console.print("[green]Question ops summary[/green]")
    console.print(
        "  pending={pending} ranked={ranked} candidates={candidates}".format(
            pending=summary.get("pending_questions", 0),
            ranked=summary.get("active_ranked_questions", 0),
            candidates=summary.get("candidate_pool", 0),
        )
    )
    _print_json(summary)


@ops.command("question-ops-maintain")
@click.option("--source", default="user", show_default=True, help="Question source to inspect")
@click.option("--limit", default=5, show_default=True, type=int, help="Max rows per compact section")
@click.option("--stub-if-no-work", is_flag=True, help="Emit a tiny JSON stub when there are no pending questions")
def ops_question_ops_maintain(source: str, limit: int, stub_if_no_work: bool) -> None:
    """Run the canonical member-question gate with optional no-work stub output."""
    from volpred.ops import build_question_ops_maintenance
    from volpred.ops.pending_replay import mark_self_replayed
    mark_self_replayed("question_research")

    result = build_question_ops_maintenance(source=source, limit=limit)
    if stub_if_no_work and result.get("skip"):
        _print_json(
            {
                "skip": True,
                "action": result.get("action"),
                "pending_questions": result.get("pending_questions", 0),
            }
        )
        return

    console.print("[green]Question ops maintenance[/green]")
    console.print(
        "  mode={mode} action={action} pending={pending} ranked={ranked} candidates={candidates}".format(
            mode=result.get("mode", "unknown"),
            action=result.get("action", "unknown"),
            pending=result.get("pending_questions", 0),
            ranked=result.get("active_ranked_questions", 0),
            candidates=result.get("candidate_pool", 0),
        )
    )
    _print_json(result)


@ops.command("memory-health-summary")
@click.option("--storage-dir", default="storage", show_default=True, help="Storage directory")
def ops_memory_health_summary(storage_dir: str) -> None:
    """Show a compact memory-health snapshot before opening the full maintenance workflow."""
    from volpred.ops import build_memory_health_summary

    summary = build_memory_health_summary(storage_dir=storage_dir)
    console.print("[green]Memory health summary[/green]")
    console.print(
        "  overall={overall} knowledge={knowledge} duplicates={duplicates} orphan_worktrees={orphans}".format(
            overall=summary.get("overall_status", "unknown"),
            knowledge=((summary.get("highlights") or {}).get("knowledge") or {}).get("status"),
            duplicates=((summary.get("knowledge_duplicates") or {}).get("duplicates") or 0),
            orphans=((summary.get("worktrees") or {}).get("orphan_count") or 0),
        )
    )
    _print_json(summary)


@ops.command("supervisor-report")
@click.option("--days", default=7, show_default=True, type=int, help="Rolling window in days")
@click.option("--storage-dir", default="storage", show_default=True, help="Storage directory")
@click.option("--rules-path", default="config/supervisor_rules.json", show_default=True, help="Supervisor rules config")
@click.option("--format", "output_format", default="both", type=click.Choice(["table", "json", "both"]), show_default=True)
def ops_supervisor_report(days: int, storage_dir: str, rules_path: str, output_format: str) -> None:
    """Aggregated historical view for T1 supervisor — task activity, curation,
    followup backlog, feed cadence, token usage, family coverage deficit.
    Reads config/supervisor_rules.json at runtime (no restart needed)."""
    from volpred.ops import build_supervisor_snapshot

    snapshot = build_supervisor_snapshot(days=days, storage_dir=storage_dir, rules_path=rules_path)

    if output_format in ("table", "both"):
        activity = snapshot["task_activity"]
        table = Table(title=f"Supervisor Report (window={days}d)")
        table.add_column("Section", style="cyan")
        table.add_column("Value", style="green")
        table.add_row("Total tasks in window", str(activity["total_tasks_in_window"]))
        table.add_row("By family", json.dumps(activity["by_family"], ensure_ascii=False))
        table.add_row("By source", json.dumps(activity["by_source"], ensure_ascii=False))
        table.add_row("By status", json.dumps(activity["by_status"], ensure_ascii=False))
        table.add_row("Avg cycle (hours)", str(activity["avg_cycle_hours"]))
        table.add_row("Pending curations", str(snapshot["curation"]["pending_curations_count"]))
        table.add_row("Curated in window", str(snapshot["curation"]["recently_curated_in_window"]))
        table.add_row("Followup backlog", str(snapshot["followup_backlog"]["unmaterialized_count"]))
        if snapshot["feed_rhythm"].get("available"):
            fr = snapshot["feed_rhythm"]
            table.add_row("Feed published (window)", str(fr["published_in_window"]))
            table.add_row("Feed drafts pending", str(fr["draft_count"]))
            table.add_row("Days since last publish", str(fr["days_since_last_publish"]))
        if snapshot["token_usage"].get("available"):
            tu = snapshot["token_usage"]
            table.add_row(f"Token cost (last {tu['window_days']}d, USD)", str(tu["total_cost_usd"]))
        deficit_rows = snapshot["family_coverage_deficit"]["families_below_floor"]
        if deficit_rows:
            table.add_row("Families below floor", json.dumps(deficit_rows, ensure_ascii=False))
        next_prio = snapshot["supervisor_next_actions"]["prioritize_families"]
        if next_prio:
            table.add_row("Next-tick prioritize", ", ".join(next_prio))
        console.print(table)

    if output_format in ("json", "both"):
        _print_json(snapshot)


@ops.command("pacing-autotune")
@click.option("--days", default=7, show_default=True, type=int)
@click.option("--storage-dir", default="storage", show_default=True)
@click.option("--rules-path", default="config/supervisor_rules.json", show_default=True)
@click.option("--dry-run", is_flag=True, help="Show what would change without writing")
@click.option("--aggressiveness", default=0.3, show_default=True, type=float, help="Change rate 0-1")
def ops_pacing_autotune(
    days: int,
    storage_dir: str,
    rules_path: str,
    dry_run: bool,
    aggressiveness: float,
) -> None:
    """Let supervisor adjust family floors/caps in supervisor_rules.json based on
    actual throughput from the last N days. Self-improvement loop — changes
    apply on next supervisor tick without session restart."""
    from volpred.ops import autotune_supervisor_rules

    result = autotune_supervisor_rules(
        days=days,
        storage_dir=storage_dir,
        rules_path=rules_path,
        dry_run=dry_run,
        aggressiveness=aggressiveness,
    )
    if result.get("ok"):
        tag = "[yellow]DRY RUN[/yellow]" if dry_run else "[green]applied[/green]"
        console.print(f"Pacing autotune {tag}")
    else:
        console.print(f"[red]Autotune failed[/red]: {result.get('error')}")
    _print_json(result)


@ops.command("health")
@click.option("--storage-dir", default="storage", show_default=True, help="Storage directory")
def ops_health(storage_dir: str) -> None:
    """Show a lightweight local health snapshot."""
    from volpred.ops import health_snapshot

    snapshot = health_snapshot(storage_dir=storage_dir)
    table = Table(title="Ops Health Snapshot")
    table.add_column("Metric", style="cyan")
    table.add_column("Value", style="green")
    for key, value in snapshot.items():
        table.add_row(key, str(value))
    console.print(table)
    _print_json(snapshot)


@ops.command("schedule-report")
def ops_schedule_report() -> None:
    """Show canonical schedule spec coverage vs live system crontab."""
    from volpred.ops import build_schedule_report

    report = build_schedule_report()
    console.print("[green]Schedule report[/green]")
    console.print(f"  canonical_path={report['canonical_path']}")
    console.print(f"  session_crons={report['session_cron_count']}")
    console.print(f"  remote_triggers={report['remote_trigger_count']}")
    console.print(
        "  system_tasks="
        f"{len(report['matched_system_tasks'])}/{report['expected_system_task_count']}"
    )
    console.print(f"  live_system_crontab={report['live_system_crontab_count']}")
    _print_json(report)


@ops.command("event-preview")
@click.option("--storage-dir", default="storage", show_default=True, help="Storage directory")
def ops_event_preview(storage_dir: str) -> None:
    """Preview canonical event jobs and whether they have already been materialized."""
    from volpred.ops import preview_event_jobs

    result = preview_event_jobs(storage_dir=storage_dir)
    console.print("[green]Event jobs preview[/green]")
    _print_json(result)


@ops.command("scheduler-preview")
@click.option("--storage-dir", default="storage", show_default=True, help="Storage directory")
def ops_scheduler_preview(storage_dir: str) -> None:
    """Preview what the shared scheduler would do on the next tick."""
    from volpred.ops import scheduler_preview

    result = scheduler_preview(storage_dir=storage_dir)
    console.print("[green]Scheduler preview[/green]")
    _print_json(result)


@ops.command("scheduler-tick")
@click.option("--storage-dir", default="storage", show_default=True, help="Storage directory")
def ops_scheduler_tick(storage_dir: str) -> None:
    """Run one shared-scheduler orchestration tick."""
    from volpred.ops import scheduler_tick

    result = scheduler_tick(storage_dir=storage_dir)
    if result.get("status") == "skipped":
        console.print(f"[yellow]Scheduler skipped[/yellow] {result.get('reason')}")
    else:
        console.print("[green]Scheduler tick complete[/green]")
    _print_json(result)


@ops.command("scheduler-smoke")
@click.option(
    "--mode",
    type=click.Choice(["coordinator", "executor", "both"], case_sensitive=False),
    default="both",
    show_default=True,
    help="Which isolated smoke path to exercise",
)
@click.option("--base-dir", default=None, help="Optional artifact root for isolated smoke outputs")
@click.option("--keep-artifacts/--cleanup", default=True, show_default=True, help="Keep or delete smoke artifacts")
def ops_scheduler_smoke(mode: str, base_dir: str | None, keep_artifacts: bool) -> None:
    """Run an isolated scheduler smoke without touching live storage or real agent CLIs."""
    from volpred.ops import run_scheduler_smoke

    result = run_scheduler_smoke(mode=mode, base_dir=base_dir, keep_artifacts=keep_artifacts)
    console.print("[green]Scheduler smoke complete[/green]")
    _print_json(result)


@ops.command("scheduler-live-smoke")
@click.option(
    "--mode",
    type=click.Choice(["coordinator", "claude-executor", "codex-executor", "all"], case_sensitive=False),
    default="all",
    show_default=True,
    help="Which live path to exercise with the installed Claude/Codex CLIs",
)
@click.option("--base-dir", default=None, help="Optional artifact root for isolated smoke outputs")
@click.option("--keep-artifacts/--cleanup", default=True, show_default=True, help="Keep or delete smoke artifacts")
@click.option(
    "--snapshot-storage-dir",
    default="storage",
    show_default=True,
    help="Optional storage dir for writing the latest agent_cli_health snapshot",
)
def ops_scheduler_live_smoke(
    mode: str,
    base_dir: str | None,
    keep_artifacts: bool,
    snapshot_storage_dir: str | None,
) -> None:
    """Run a live scheduler smoke against installed agent CLIs using isolated storage."""
    from volpred.ops import run_scheduler_live_smoke

    result = run_scheduler_live_smoke(
        mode=mode,
        base_dir=base_dir,
        keep_artifacts=keep_artifacts,
        snapshot_storage_dir=snapshot_storage_dir,
    )
    console.print("[green]Scheduler live smoke complete[/green]")
    _print_json(result)


@ops.command("sync-all")
@click.option("--storage-dir", default="storage", show_default=True, help="Storage directory")
def ops_sync_all(storage_dir: str) -> None:
    """Run the incremental Supabase sync used by the local research flow."""
    from volpred.ops import sync_all

    result = sync_all(storage_dir=storage_dir)
    console.print("[green]Sync complete[/green]")
    for key, value in result.items():
        console.print(f"  {key}: {value}")
    _print_json({"action": "sync_all", "counts": result})


@ops.command("feed-sync")
@click.option("--storage-dir", default="storage", show_default=True)
@click.option("--dry-run/--apply", default=True, show_default=True,
              help="Dry-run shows diff only; --apply writes to Supabase")
@click.option("--allow-delete/--no-delete", default=False, show_default=True,
              help="Allow DELETE of Supabase rows missing from feed.json")
def ops_feed_sync(storage_dir: str, dry_run: bool, allow_delete: bool) -> None:
    """One-way reconcile feed.json (canonical) -> Supabase articles projection.

    Contentlayer pattern: feed.json is the single source of truth; this
    command pushes diffs to the DB projection. Never reads from DB as truth.
    """
    from volpred.ops.feed_sync import sync_feed_to_supabase

    result = sync_feed_to_supabase(
        storage_dir=storage_dir,
        dry_run=dry_run,
        allow_delete=allow_delete,
        verbose=True,
    )
    _print_json({"action": "feed_sync", "result": result})


@ops.command("daily-update")
def ops_daily_update() -> None:
    """Run the full local daily update workflow."""
    from volpred.ops import run_daily_update

    _print_completed_process(run_daily_update(), action="daily_update")


@ops.command("recalc-metrics")
def ops_recalc_metrics() -> None:
    """Recalculate local strategy metrics from paper_trading.json."""
    from volpred.ops import run_recalc_metrics

    _print_completed_process(run_recalc_metrics(), action="recalc_metrics")


@ops.command("publish-milestone")
@click.option("--title", required=True, help="Article title")
@click.option("--description", required=True, help="Markdown body/description")
@click.option("--phase", required=True, help="Research phase")
@click.option("--details-json", default=None, help="JSON string or path for details payload")
@click.option("--tags", default=None, help="Comma-separated tags")
@click.option("--status", "status_name", default="published", type=click.Choice(["published", "draft", "scheduled"]), show_default=True, help="Initial publish status")
@click.option("--publish-at", default=None, help="Scheduled publish time (ISO datetime) when status=scheduled")
@click.option("--audience", default=None, help="Target audience: general, research, daily, member_qa")
@click.option("--proposer", default=None, help="Who proposed/asked this (member name for Q&A)")
@click.option("--storage-dir", default="storage", show_default=True, help="Storage directory")
def ops_publish_milestone(
    title: str,
    description: str,
    phase: str,
    details_json: str | None,
    tags: str | None,
    status_name: str,
    publish_at: str | None,
    audience: str | None,
    proposer: str | None,
    storage_dir: str,
) -> None:
    """Publish a milestone article through the unified publisher path."""
    from volpred.ops import publish_milestone_article

    details = _parse_json_input(details_json, default={})
    if not isinstance(details, dict):
        raise click.ClickException("--details-json must decode to an object")

    pub_id = publish_milestone_article(
        title=title,
        description=description,
        phase=phase,
        details=details,
        tags=_parse_tags(tags),
        status=status_name,
        publish_at=publish_at,
        audience=audience,
        proposer=proposer,
        storage_dir=storage_dir,
    )
    console.print(f"[green]Stored milestone[/green] {pub_id}")
    _print_json({"action": "publish_milestone", "id": pub_id, "phase": phase, "status": status_name, "publish_at": publish_at})


@ops.command("release-pool")
@click.option("--pub-id", default=None, help="Optional specific article id to release")
@click.option("--limit", default=1, show_default=True, type=int, help="Max number of queued articles to release")
@click.option("--due-only/--include-drafts", default=True, show_default=True, help="Only release scheduled items that are due; disable to include drafts/manual release")
@click.option("--storage-dir", default="storage", show_default=True, help="Storage directory")
def ops_release_pool(pub_id: str | None, limit: int, due_only: bool, storage_dir: str) -> None:
    """Release one or more queued articles from the local content pool."""
    from volpred.ops import release_pool_articles

    result = release_pool_articles(pub_id=pub_id, limit=limit, due_only=due_only, storage_dir=storage_dir)
    console.print(f"[green]Released[/green] {result['released_count']} article(s) from pool")
    _print_json({"action": "release_article_pool", **result})


@ops.command("release-pool-by-settings")
@click.option("--force", is_flag=True, help="Ignore manual mode / interval gate and run once anyway")
@click.option("--storage-dir", default="storage", show_default=True, help="Storage directory")
def ops_release_pool_by_settings(force: bool, storage_dir: str) -> None:
    """Release queued articles according to the shared content cadence settings."""
    from volpred.ops import release_pool_by_settings

    result = release_pool_by_settings(force=force, storage_dir=storage_dir)
    if result.get("skipped"):
        console.print("[yellow]Skipped[/yellow] release run")
    else:
        console.print(f"[green]Released[/green] {result['released_count']} article(s) by cadence settings")
    _print_json({"action": "release_article_pool_by_settings", **result})


@ops.command("send-article-notification")
@click.argument("pub_id")
@click.option("--force-send", is_flag=True, help="Ignore duplicate guard and resend once")
@click.option("--storage-dir", default="storage", show_default=True, help="Storage directory")
def ops_send_article_notification(pub_id: str, force_send: bool, storage_dir: str) -> None:
    """Send or resend the admin notification email for a published article."""
    from volpred.ops import send_article_notification

    result = send_article_notification(pub_id, force_send=force_send, storage_dir=storage_dir)
    if not result["found"]:
        raise click.ClickException(f"Publication not found: {pub_id}")
    console.print(f"[green]Article notification prepared[/green] {pub_id}")
    _print_json({"action": "send_article_notification", **result})


@ops.command("send-daily-digest")
@click.option("--target-date", default=None, help="Digest date (YYYY-MM-DD). Defaults to today.")
@click.option("--force-send", is_flag=True, help="Ignore duplicate guard and resend once")
@click.option("--storage-dir", default="storage", show_default=True, help="Storage directory")
def ops_send_daily_digest(target_date: str | None, force_send: bool, storage_dir: str) -> None:
    """Send the daily admin digest email for articles published on a given day."""
    from volpred.ops import send_daily_digest

    result = send_daily_digest(target_date=target_date, force_send=force_send, storage_dir=storage_dir)
    if result.get("skipped"):
        console.print("[yellow]Skipped[/yellow] daily digest")
    else:
        console.print(f"[green]Daily digest prepared[/green] {result['date']} ({result['count']} articles)")
    _print_json({"action": "send_daily_digest", **result})


@ops.command("send-alert")
@click.option(
    "--level",
    required=True,
    type=click.Choice(["info", "warn", "critical"], case_sensitive=False),
    help="Alert level",
)
@click.option("--title", required=True, help="Alert title")
@click.option("--body", required=True, help="Alert body")
@click.option("--force", "force_send", is_flag=True, help="Bypass 24h dedup and resend once")
@click.option("--storage-dir", default="storage", show_default=True, help="Storage directory")
def ops_send_alert(level: str, title: str, body: str, force_send: bool, storage_dir: str) -> None:
    """Send a general-purpose ops alert email to the fixed admin recipient."""
    from volpred.ops import ALERT_RECIPIENT, send_alert

    result = send_alert(
        level,
        title,
        body,
        recipient=ALERT_RECIPIENT,
        storage_dir=storage_dir,
        force_send=force_send,
    )
    if result.get("skipped"):
        console.print("[yellow]Alert skipped[/yellow] duplicate within 24h window")
    elif result.get("sent"):
        console.print(f"[green]Alert sent[/green] {result['notification_id']}")
    else:
        console.print("[red]Alert not delivered[/red]")
    _print_json({"action": "send_alert", **result})


@ops.command("check-alerts")
@click.option("--storage-dir", default="storage", show_default=True, help="Storage directory")
def ops_check_alerts(storage_dir: str) -> None:
    """Evaluate alert conditions and send deduped email notifications for breaches."""
    from volpred.ops import check_alert_conditions

    result = check_alert_conditions(storage_dir=storage_dir)
    console.print(
        "[green]Alert conditions checked[/green] "
        f"breaches={result['breach_count']} sent={result['sent_count']} skipped={result['skipped_count']}"
    )
    _print_json({"action": "check_alerts", **result})


@ops.command("paper-list")
def ops_paper_list() -> None:
    """List DB-driven papers and whether their PDFs are already storage-backed."""
    from volpred.ops import list_papers

    papers = list_papers()
    table = Table(title="Papers")
    table.add_column("ID", style="cyan")
    table.add_column("Status", style="green")
    table.add_column("Storage", style="magenta")
    table.add_column("Title", style="white")
    for paper in papers:
        table.add_row(
            str(paper.get("id", "")),
            str(paper.get("status", "")),
            "yes" if paper.get("storage_bucket") == "papers" else "no",
            str(paper.get("title", "")),
        )
    console.print(table)
    _print_json({"action": "paper_list", "items": papers})


@ops.command("paper-upsert")
@click.option("--paper-id", required=True, help="Stable paper id")
@click.option("--title", default=None, help="Paper title (omit to keep existing)")
@click.option("--authors", default=None, help="Authors string (omit to keep existing)")
@click.option("--abstract", default=None, help="Abstract")
@click.option("--status", default=None, help="Paper status (omit to keep existing)")
@click.option("--target-journal", default=None, help="Target journal")
@click.option("--pdf-url", default=None, help="PDF URL")
@click.option("--pages", default=None, help="Pages")
@click.option("--figures", default=None, help="Figures")
@click.option("--tables", default=None, help="Tables")
@click.option("--citations", default=None, help="Citations")
@click.option("--score", default=None, help="Score")
@click.option("--tags", default=None, help="Comma-separated tags")
@click.option("--display-order", default="0", show_default=True, help="Display order")
def ops_paper_upsert(
    paper_id: str,
    title: str,
    authors: str,
    abstract: str | None,
    status: str,
    target_journal: str | None,
    pdf_url: str | None,
    pages: str | None,
    figures: str | None,
    tables: str | None,
    citations: str | None,
    score: str | None,
    tags: str | None,
    display_order: str,
) -> None:
    """Upsert a paper row in the DB-driven papers table."""
    from volpred.ops import upsert_paper_metadata

    # Only pass explicitly provided fields to enable merge mode
    kwargs: dict = {"paper_id": paper_id}
    if title is not None:
        kwargs["title"] = title
    if authors is not None:
        kwargs["authors"] = authors
    if abstract is not None:
        kwargs["abstract"] = abstract
    if status is not None:  # explicit --status (incl. downgrade to "working")
        kwargs["status"] = status
    if target_journal is not None:
        kwargs["target_journal"] = target_journal
    if pdf_url is not None:
        kwargs["pdf_url"] = pdf_url
    if pages is not None:
        kwargs["pages"] = _parse_optional_number(pages)
    if figures is not None:
        kwargs["figures"] = _parse_optional_number(figures)
    if tables is not None:
        kwargs["tables"] = _parse_optional_number(tables)
    if citations is not None:
        kwargs["citations"] = _parse_optional_number(citations)
    if score is not None:
        kwargs["score"] = _parse_optional_float(score)
    if tags is not None:
        kwargs["tags"] = _parse_tags(tags)
    if display_order != "0":  # only override if explicitly changed
        kwargs["display_order"] = int(display_order)
    paper = upsert_paper_metadata(**kwargs)
    console.print(f"[green]Upserted paper[/green] {paper_id}")
    _print_json({"action": "paper_upsert", "item": paper})


@ops.command("paper-upload-pdf")
@click.option("--paper-id", required=True, help="Stable paper id")
@click.option("--file", "file_path", required=True, type=click.Path(exists=True), help="Path to PDF file")
def ops_paper_upload_pdf(paper_id: str, file_path: str) -> None:
    """Upload a paper PDF to Supabase Storage and update the row."""
    from volpred.ops import upload_paper_pdf

    paper = upload_paper_pdf(paper_id=paper_id, file_path=file_path)
    console.print(f"[green]Uploaded paper PDF[/green] {paper_id}")
    _print_json({"action": "paper_upload_pdf", "item": paper})


@ops.command("paper-update")
@click.option("--paper-id", required=True, help="Stable paper id")
@click.option("--paper-dir", default=None, help="Paper directory (default: paper/<paper-id>)")
def ops_paper_update(paper_id: str, paper_dir: str | None) -> None:
    """One-command paper update: auto-count pages/citations from .tex → upload PDF → sync metadata → copy to frontend."""
    from volpred.ops.papers import update_paper_full

    paper = update_paper_full(paper_id=paper_id, paper_dir=paper_dir)
    console.print(f"[green]Paper fully updated[/green] {paper_id}")
    console.print(f"  pages={paper.get('pages')} citations={paper.get('citations')} pdf_url={'✅' if paper.get('pdf_url') else '❌'}")
    _print_json({"action": "paper_update", "item": paper})


@ops.command("paper-sync-all")
@click.option("--dry-run", is_flag=True, help="Show what would be synced without invoking Supabase")
@click.option("--force", is_flag=True, help="Sync every paper even if Supabase updated_at is already newer than local files")
def ops_paper_sync_all(dry_run: bool, force: bool) -> None:
    """Auto-sync every paper/ directory to Supabase when local .tex/.pdf is newer.

    Fixes the recurring drift where main-thread edits update local .tex but the
    website still shows old dates because paper-update CLI is per-paper and
    manual. Designed for cron schedule (idempotent: skips papers where Supabase
    updated_at is newer than local files).
    """
    from volpred.ops.papers import sync_all_papers

    results = sync_all_papers(only_stale=not force, dry_run=dry_run)
    actions: dict[str, int] = {}
    for r in results:
        actions[r["action"]] = actions.get(r["action"], 0) + 1
        console.print(f"  {r['paper_id']:<25} {r['action']:<16} {r.get('reason') or r.get('updated_at', '')}")
    console.print(f"[green]Sync complete[/green] {actions}")
    _print_json({"action": "paper_sync_all", "summary": actions, "results": results})


@ops.command("paper-migrate-storage")
@click.option("--paper-id", required=True, help="Stable paper id")
@click.option("--file", "file_path", default=None, type=click.Path(exists=True), help="Optional local PDF path; defaults to current static paper URL")
def ops_paper_migrate_storage(paper_id: str, file_path: str | None) -> None:
    """Migrate a paper from static /paper/*.pdf delivery to Supabase Storage."""
    from volpred.ops import migrate_paper_pdf_to_storage

    paper = migrate_paper_pdf_to_storage(paper_id=paper_id, file_path=file_path)
    console.print(f"[green]Migrated paper PDF to storage[/green] {paper_id}")
    _print_json({"action": "paper_migrate_storage", "item": paper})


@ops.command("unpublish")
@click.argument("pub_id")
@click.option("--storage-dir", default="storage", show_default=True, help="Storage directory")
def ops_unpublish(pub_id: str, storage_dir: str) -> None:
    """Soft-unpublish an article locally and sync the status remotely."""
    from volpred.ops import unpublish_article

    result = unpublish_article(pub_id, storage_dir=storage_dir)
    if not result["found"]:
        raise click.ClickException(f"Publication not found: {pub_id}")
    console.print(f"[green]Unpublished[/green] {pub_id}")
    _print_json(result)


@ops.command("cleanup-post")
@click.argument("pub_id")
@click.option("--hard-delete", is_flag=True, help="Also remove the local report/feed entry and delete the DB row")
@click.option("--storage-dir", default="storage", show_default=True, help="Storage directory")
def ops_cleanup_post(pub_id: str, hard_delete: bool, storage_dir: str) -> None:
    """Cleanup a test post after publish-flow validation."""
    from volpred.ops import cleanup_test_post

    result = cleanup_test_post(pub_id, hard_delete=hard_delete, storage_dir=storage_dir)
    if not result["found"]:
        raise click.ClickException(f"Publication not found: {pub_id}")
    console.print(f"[green]Cleaned up[/green] {pub_id}")
    _print_json(result)


@ops.command("article-backups")
@click.option("--repair", is_flag=True, help="Create missing local report JSON files from feed.json when recoverable")
@click.option("--include-non-published", is_flag=True, help="Also audit drafts/scheduled/unpublished items")
@click.option("--storage-dir", default="storage", show_default=True, help="Storage directory")
def ops_article_backups(repair: bool, include_non_published: bool, storage_dir: str) -> None:
    """Audit or repair local article backups for disaster recovery."""
    from volpred.ops import ensure_article_local_backups

    result = ensure_article_local_backups(
        repair=repair,
        include_non_published=include_non_published,
        storage_dir=storage_dir,
    )
    targeted_label = "tracked items" if include_non_published else "published articles"
    if result["recoverable"] and result["fully_materialized"]:
        console.print(f"[green]Healthy[/green] all {targeted_label} have standalone local backups")
    elif result["recoverable"]:
        console.print(f"[yellow]Recoverable[/yellow] all {targeted_label} exist locally, but some were feed-only")
    else:
        console.print(f"[red]Incomplete[/red] some {targeted_label} are missing local body content")
    console.print(f"  Tracked: {result['tracked_items']}")
    console.print(f"  Missing report files: {len(result['missing_report_ids'])}")
    console.print(f"  Bodyless: {len(result['bodyless_ids'])}")
    if repair:
        console.print(f"  Repaired this run: {result.get('created_count', 0)}")
    _print_json({"action": "article_local_backups", **result})
    if result["bodyless_ids"]:
        raise click.ClickException("Some tracked articles are missing local body content")


@ops.command("strategy-upsert")
@click.option("--strategy-key", required=True, help="Stable strategy key used by the website")
@click.option("--strategy-name", required=True, help="Display name")
@click.option("--weights-json", required=True, help="JSON string or path for current weights")
@click.option("--display-order", default=0, show_default=True, type=int, help="Homepage sort order")
@click.option("--active/--inactive", default=True, show_default=True, help="Whether the strategy is active")
@click.option("--howto", default=None, help="Short allocation rule description")
@click.option("--description", default=None, help="Longer strategy description")
@click.option("--color", default=None, help="Card accent color")
@click.option("--articles-json", default=None, help="JSON string or path for related article links")
@click.option("--vix-level", default=None, type=float, help="Latest VIX level")
@click.option("--sigma-ann", default=None, type=float, help="Latest annualized sigma")
def ops_strategy_upsert(
    strategy_key: str,
    strategy_name: str,
    weights_json: str,
    display_order: int,
    active: bool,
    howto: str | None,
    description: str | None,
    color: str | None,
    articles_json: str | None,
    vix_level: float | None,
    sigma_ann: float | None,
) -> None:
    """Upsert strategy metadata/signals through the unified sync path."""
    from volpred.ops import upsert_strategy_metadata

    weights = _parse_json_input(weights_json, default={})
    articles = _parse_json_input(articles_json, default=[])
    if not isinstance(weights, dict):
        raise click.ClickException("--weights-json must decode to an object")
    if not isinstance(articles, list):
        raise click.ClickException("--articles-json must decode to an array")

    success = upsert_strategy_metadata(
        strategy_key=strategy_key,
        strategy_name=strategy_name,
        weights=weights,
        display_order=display_order,
        is_active=active,
        howto=howto,
        description=description,
        color=color,
        articles=articles,
        vix_level=vix_level,
        sigma_ann=sigma_ann,
    )
    if not success:
        raise click.ClickException(f"Failed to upsert strategy: {strategy_key}")
    console.print(f"[green]Upserted strategy[/green] {strategy_key}")
    _print_json({"action": "strategy_upsert", "strategy_key": strategy_key, "active": active})


@ops.command("strategy-set-active")
@click.argument("identifier")
@click.option("--active/--inactive", default=True, show_default=True, help="Target active state")
def ops_strategy_set_active(identifier: str, active: bool) -> None:
    """Toggle strategy visibility by key or display name."""
    from volpred.ops import activate_strategy, deactivate_strategy

    success = activate_strategy(identifier) if active else deactivate_strategy(identifier)
    if not success:
        raise click.ClickException(f"Failed to update strategy active state: {identifier}")
    console.print(f"[green]Updated strategy state[/green] {identifier} -> {'active' if active else 'inactive'}")
    _print_json({"action": "strategy_set_active", "identifier": identifier, "active": active})


@ops.command("question-claim")
@click.argument("question_id")
def ops_question_claim(question_id: str) -> None:
    """Atomically claim a ranked question for research (cross-session race protection).

    Uses status='ranked' → 'researching' transition as the lock. If another
    session already claimed this question, the command reports claimed=False
    with the current status. Exit code 0 on success, 2 on claim lost.
    """
    from volpred.ops import claim_question_for_research

    result = claim_question_for_research(question_id)
    _print_json({"action": "question_claim", **result})
    if not result.get("claimed"):
        reason = result.get("reason", "unknown")
        console.print(f"[yellow]Claim lost:[/yellow] {question_id} — {reason}")
        raise SystemExit(2)
    console.print(f"[green]Claimed[/green] {question_id}")


@ops.command("question-archive")
@click.argument("question_id")
@click.option("--reason", default="manual", show_default=True, help="Archive reason (audit)")
def ops_question_archive(question_id: str, reason: str) -> None:
    """Archive a question (force status → 'archived').

    Use to remove test inputs / spam / accidental submissions from the
    ranking pool. Unlike question-claim this is unconditional on current
    status. Exit code 0 on success, 2 if not found.
    """
    from volpred.ops import archive_question

    result = archive_question(question_id, reason=reason)
    _print_json({"action": "question_archive", **result})
    if not result.get("archived"):
        console.print(f"[yellow]Archive failed:[/yellow] {question_id} — {result.get('reason','unknown')}")
        raise SystemExit(2)
    console.print(f"[green]Archived[/green] {question_id}")


@ops.command("question-answer")
@click.argument("question_id")
@click.option("--answer", required=True, help="Answer content")
@click.option("--article-id", default=None, help="Article slug to link as an answer in question_articles")
@click.option("--storage-dir", default="storage", show_default=True, help="Storage directory")
def ops_question_answer(question_id: str, answer: str, article_id: str | None, storage_dir: str) -> None:
    """Answer a local internal research question and sync it."""
    from volpred.ops import answer_internal_question

    result = answer_internal_question(question_id, answer, storage_dir=storage_dir, article_id=article_id)
    if not result.get("found", True) and result.get("status") is None:
        raise click.ClickException(f"Question not found: {question_id}")
    status = result.get("status", "unknown")
    console.print(f"[green]Question {question_id}[/green] → status: {status}")
    if result.get("linked_article"):
        console.print(f"[green]Linked article[/green] {result['linked_article']}")
    if result.get("note"):
        console.print(f"[yellow]⚠ {result['note']}[/yellow]")
    _print_json(result)


@ops.command("question-rerank")
@click.option("--evaluations-json", required=True, help="JSON string or path for evaluated pending questions")
@click.option("--source", default="user", show_default=True, help="Question source to rerank")
def ops_question_rerank(evaluations_json: str, source: str) -> None:
    """Apply stable insertion ranking for member questions using evaluated pending items."""
    from volpred.ops import rerank_member_questions

    evaluations = _parse_json_input(evaluations_json, default=[])
    if not isinstance(evaluations, list):
        raise click.ClickException("--evaluations-json must decode to an array")

    result = rerank_member_questions(evaluations, source=source)
    console.print(
        f"[green]Reranked questions[/green] evaluated={result['evaluated_count']} updated={result['updated_count']}"
    )
    _print_json({"action": "question_rerank", **result})


@ops.command("question-ranking-summary")
@click.option("--source", default="user", show_default=True, help="Question source to inspect")
@click.option("--limit", default=20, show_default=True, type=int, help="Max ranked/pending items to include")
def ops_question_ranking_summary(source: str, limit: int) -> None:
    """Show the member-question ranking summary before the 6-hour rerank cycle."""
    from volpred.ops import get_member_question_ranking_summary

    result = get_member_question_ranking_summary(source=source, limit=limit)
    health = result.get("health", {})
    console.print("[green]Loaded question ranking summary[/green]")
    console.print(
        "  pending={pending} ranked={ranked} candidates={candidates}".format(
            pending=health.get("pending_evaluation", 0),
            ranked=health.get("active_ranked", 0),
            candidates=health.get("candidate_pool", 0),
        )
    )
    _print_json({"action": "question_ranking_summary", **result})


@ops.command("question-ranking-workflow")
@click.option("--source", default="user", show_default=True, help="Question source to inspect")
@click.option("--limit", default=20, show_default=True, type=int, help="Max ranked/pending items to include")
@click.option("--output-json", default=None, help="Optional path to write workflow JSON")
def ops_question_ranking_workflow(source: str, limit: int, output_json: str | None) -> None:
    """Build a Claude-friendly rerank workflow package for the 6-hour member-question cycle."""
    from volpred.ops import build_question_rerank_workflow

    write_latest = output_json is None
    result = build_question_rerank_workflow(
        source=source,
        limit=limit,
        storage_dir="storage",
        write_latest=write_latest,
    )
    health = result.get("health", {})
    console.print("[green]Prepared question ranking workflow[/green]")
    console.print(
        "  pending={pending} ranked={ranked} candidates={candidates}".format(
            pending=health.get("pending_evaluation", 0),
            ranked=health.get("active_ranked", 0),
            candidates=health.get("candidate_pool", 0),
        )
    )
    if output_json:
        target = Path(output_json)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(result, ensure_ascii=False, indent=2))
        console.print(f"[cyan]Wrote workflow package[/cyan] {target}")
    _print_json({"action": "question_ranking_workflow", **result})


@ops.command("platform-cycle-summary")
@click.option("--storage-dir", default="storage", show_default=True, help="Storage directory")
@click.option("--source", default="user", show_default=True, help="Question source to inspect")
@click.option("--limit", default=20, show_default=True, type=int, help="Max ranked/pending items to include")
@click.option("--output-json", default=None, help="Optional path to write summary JSON")
def ops_platform_cycle_summary(
    storage_dir: str,
    source: str,
    limit: int,
    output_json: str | None,
) -> None:
    """Summarize content-release cadence and question rerank state for session-cron use."""
    from volpred.ops import build_platform_cycle_summary

    write_latest = output_json is None
    summary = build_platform_cycle_summary(
        storage_dir=storage_dir,
        source=source,
        limit=limit,
        write_latest=write_latest,
    )

    console.print("[green]Loaded platform cycle summary[/green]")
    release_preview = summary.get("release_preview", {})
    pending = (summary.get("question_ranking", {}).get("health", {}) or {}).get("pending_evaluation", 0)
    console.print(
        "  release_due={release_due} pending_questions={pending}".format(
            release_due="yes" if release_preview.get("due_now") else "no",
            pending=pending,
        )
    )
    if output_json:
        target = Path(output_json)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(summary, ensure_ascii=False, indent=2))
        console.print(f"[cyan]Wrote platform cycle summary[/cyan] {target}")
    _print_json({"action": "platform_cycle_summary", **summary})


@ops.command("jobs")
@click.option("--status", default=None, help="Filter by job status")
@click.option("--scope", default=None, help="Filter by job scope")
@click.option("--limit", default=20, show_default=True, type=int, help="Max jobs to show")
def ops_jobs(status: str | None, scope: str | None, limit: int) -> None:
    """List recent ops jobs from Supabase."""
    from volpred.ops import list_jobs

    jobs = list_jobs(status=status, scope=scope, limit=limit)
    table = Table(title="Ops Jobs")
    table.add_column("ID", style="cyan")
    table.add_column("Action", style="white")
    table.add_column("Status", style="green")
    table.add_column("Scope", style="magenta")
    table.add_column("Source", style="yellow")
    table.add_column("Created", style="dim")
    for job in jobs:
        table.add_row(
            str(job.get("id", ""))[:8],
            str(job.get("action", "")),
            str(job.get("status", "")),
            str(job.get("scope", "")),
            str(job.get("source", "")),
            str(job.get("created_at", "")),
        )
    console.print(table)
    _print_json({"jobs": jobs})


@ops.command("job-show")
@click.argument("job_id")
def ops_job_show(job_id: str) -> None:
    """Show a single ops job with logs."""
    from volpred.ops import get_job

    job = get_job(job_id)
    if not job:
        raise click.ClickException(f"Job not found: {job_id}")

    console.print(f"[bold]Job[/bold] {job['id']}")
    meta = Table(show_header=False, box=None)
    meta.add_column("Key", style="cyan")
    meta.add_column("Value", style="white")
    for key in [
        "action",
        "status",
        "scope",
        "source",
        "requested_by",
        "worker_id",
        "created_at",
        "started_at",
        "finished_at",
    ]:
        meta.add_row(key, str(job.get(key)))
    console.print(meta)

    logs = job.get("logs") or []
    if logs:
        table = Table(title="Job Logs")
        table.add_column("Time", style="dim")
        table.add_column("Level", style="cyan")
        table.add_column("Message", style="white")
        for row in logs:
            table.add_row(
                str(row.get("created_at", "")),
                str(row.get("level", "")),
                str(row.get("message", "")),
            )
        console.print(table)

    _print_json(job)


@ops.command("enqueue")
@click.option("--action", "action_name", required=True, type=click.Choice(OPS_ACTION_CHOICES), help="Ops job action")
@click.option("--payload-json", default=None, help="JSON string or path for payload")
@click.option("--scope", default="local", show_default=True, type=click.Choice(["local", "remote"]), help="Job scope")
@click.option("--source", default="agent", show_default=True, type=click.Choice(["human", "agent", "system"]), help="Job source")
@click.option("--requested-by", default=None, help="Requester label")
@click.option("--dry-run", is_flag=True, help="Queue as dry-run")
@click.option("--priority", default=100, show_default=True, type=int, help="Job priority (lower runs earlier)")
@click.option("--dedupe-key", default=None, help="Optional dedupe key for active jobs")
def ops_enqueue(
    action_name: str,
    payload_json: str | None,
    scope: str,
    source: str,
    requested_by: str | None,
    dry_run: bool,
    priority: int,
    dedupe_key: str | None,
) -> None:
    """Queue an ops job in the shared control plane."""
    from volpred.ops import enqueue_job

    payload = _parse_json_input(payload_json, default={})
    if not isinstance(payload, dict):
        raise click.ClickException("--payload-json must decode to an object")

    job = enqueue_job(
        action=action_name,
        payload=payload,
        scope=scope,
        source=source,
        requested_by=requested_by,
        dry_run=dry_run,
        priority=priority,
        dedupe_key=dedupe_key,
    )
    console.print(f"[green]Queued job[/green] {job['id']}")
    _print_json(job)


@ops.command("worker")
@click.option("--scope", default="local", show_default=True, help="Job scope to consume")
@click.option("--worker-id", default=None, help="Explicit worker id")
@click.option("--poll-interval", default=10.0, show_default=True, type=float, help="Polling interval in seconds")
@click.option("--once", is_flag=True, help="Process at most one available job")
@click.option("--max-jobs", default=None, type=int, help="Stop after processing N jobs")
def ops_worker(
    scope: str,
    worker_id: str | None,
    poll_interval: float,
    once: bool,
    max_jobs: int | None,
) -> None:
    """Run the local ops job worker."""
    from volpred.ops import work_loop

    processed = work_loop(
        scope=scope,
        worker_id=worker_id,
        poll_interval=poll_interval,
        once=once,
        max_jobs=max_jobs,
    )
    console.print(f"[green]Worker processed[/green] {processed} job(s)")
    _print_json(
        {
            "action": "worker",
            "scope": scope,
            "processed": processed,
            "once": once,
            "max_jobs": max_jobs,
        }
    )


if __name__ == "__main__":
    cli()
