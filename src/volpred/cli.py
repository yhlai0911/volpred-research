from __future__ import annotations

import json
import sys
from pathlib import Path

import click
import yaml
from rich.console import Console
from rich.table import Table

console = Console()
OPS_ACTION_CHOICES = (
    "cleanup_test_post",
    "daily_update",
    "health_check",
    "paper_migrate_storage",
    "paper_upload_pdf",
    "paper_upsert",
    "platform_cycle_summary",
    "publish_milestone",
    "question_rerank",
    "question_ranking_summary",
    "question_ranking_workflow",
    "release_article_pool",
    "release_article_pool_by_settings",
    "send_article_notification",
    "send_daily_digest",
    "question_answer",
    "recalc_metrics",
    "strategy_set_active",
    "strategy_upsert",
    "sync_all",
    "unpublish_article",
)


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
    return [tag.strip() for tag in raw.split(",") if tag.strip()]


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
    """Publish experiment results to the feed."""
    from volpred.memory.system import MemorySystem
    from volpred.publisher.publisher import Publisher

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
@click.option("--storage-dir", default="storage", show_default=True, help="Storage directory")
def ops_publish_milestone(
    title: str,
    description: str,
    phase: str,
    details_json: str | None,
    tags: str | None,
    status_name: str,
    publish_at: str | None,
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
@click.option("--title", required=True, help="Paper title")
@click.option("--authors", required=True, help="Authors string")
@click.option("--abstract", default=None, help="Abstract")
@click.option("--status", default="working", show_default=True, help="Paper status")
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

    paper = upsert_paper_metadata(
        paper_id=paper_id,
        title=title,
        authors=authors,
        abstract=abstract,
        status=status,
        target_journal=target_journal,
        pdf_url=pdf_url,
        pages=_parse_optional_number(pages),
        figures=_parse_optional_number(figures),
        tables=_parse_optional_number(tables),
        citations=_parse_optional_number(citations),
        score=_parse_optional_float(score),
        tags=_parse_tags(tags),
        display_order=int(display_order),
    )
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


@ops.command("question-answer")
@click.argument("question_id")
@click.option("--answer", required=True, help="Answer content")
@click.option("--storage-dir", default="storage", show_default=True, help="Storage directory")
def ops_question_answer(question_id: str, answer: str, storage_dir: str) -> None:
    """Answer a local internal research question and sync it."""
    from volpred.ops import answer_internal_question

    result = answer_internal_question(question_id, answer, storage_dir=storage_dir)
    if not result["found"]:
        raise click.ClickException(f"Question not found: {question_id}")
    console.print(f"[green]Answered question[/green] {question_id}")
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
