""" The experiment registry (data/experiments.db).

    pixi run registry sync               # index data/research (configs, lineage, artifacts)
    pixi run registry show               # summary: configs per stage, artifacts, runs
    pixi run registry runs [STRATEGY]    # runs with status and trial counts
    pixi run registry run RUN_ID         # one run: configs used, metrics
"""
from __future__ import annotations

import click
import polars as pl
from rich.console import Console
from rich.table import Table

from fxt.services import get_registry, get_research

console = Console()


@click.group()
def main() -> None:
    """ Experiment registry. """


@main.command()
def sync() -> None:
    """ Index data/research into the registry. """
    with get_registry() as reg:
        rep = reg.sync(get_research())
        console.print(f"[bold]{reg.path}[/]")
    console.print(f"artifacts on disk: {rep.artifacts_seen:,} ({rep.artifacts_added:,} new)")
    console.print(f"configs added:     {rep.configs_added:,}")
    if rep.artifacts_missing:
        console.print(f"[yellow]missing from disk: {rep.artifacts_missing:,} (kept, marked present=0)[/]")
    for p in rep.problems:
        console.print(f"[red]problem[/] {p}")
    if rep.problems:
        raise SystemExit(1)


@main.command()
def show() -> None:
    """ Configs and artifacts per stage, and run counts. """
    with get_registry() as reg:
        df = reg.query("""
            SELECT c.stage, COUNT(DISTINCT c.config_hash) AS configs,
                   COUNT(a.path) FILTER (WHERE a.present = 1) AS files,
                   COUNT(a.path) FILTER (WHERE a.present = 0) AS missing,
                   COALESCE(SUM(a.rows) FILTER (WHERE a.present = 1), 0) AS rows,
                   COUNT(a.path) FILTER (WHERE a.present = 1 AND a.passed = 0) AS failed_checks
            FROM configs c LEFT JOIN artifacts a USING (config_hash)
            GROUP BY c.stage ORDER BY c.stage""")
        runs = reg.query("SELECT status, COUNT(*) AS n FROM runs GROUP BY status ORDER BY status")
        console.print(f"[bold]{reg.path}[/]")
    t = Table(title="configs", title_justify="left")
    for c in df.columns:
        t.add_column(c, justify="left" if c == "stage" else "right")
    for r in df.iter_rows():
        t.add_row(*(f"{v:,}" if isinstance(v, int) else str(v) for v in r))
    console.print(t)
    if runs.is_empty():
        console.print("runs: none yet")
    else:
        console.print("runs: " + ", ".join(f"{s} {n}" for s, n in runs.iter_rows()))


@main.command()
@click.argument("strategy", required=False)
def runs(strategy: str | None) -> None:
    """ List runs (optionally one strategy). """
    with get_registry() as reg:
        df = reg.runs(strategy)
        trials = reg.trial_count(strategy)
    if df.is_empty():
        console.print("no runs")
        return
    t = Table(title=f"runs ({trials} trial(s) excl. lockbox)", title_justify="left")
    cols = ("run_id", "strategy_id", "status", "cv_scheme", "data_start", "data_end", "is_lockbox", "notes")
    for c in cols:
        t.add_column(c, overflow="fold")
    for r in df.select(cols).iter_rows():
        t.add_row(*("" if v is None else str(v) for v in r))
    console.print(t)


@main.command()
@click.argument("run_id")
def run(run_id: str) -> None:
    """ One run: configs and metrics. """
    with get_registry() as reg:
        info = reg.query("SELECT * FROM runs WHERE run_id = ?", (run_id,))
        if info.is_empty():
            raise click.ClickException(f"no run {run_id}")
        cfgs = reg.run_configs(run_id)
        mets = reg.metrics(run_id)
    for k, v in info.row(0, named=True).items():
        console.print(f"[bold]{k:<12}[/] {v}")
    console.print("[bold]configs[/]      " + ", ".join(f"{r}={h}" for r, h in cfgs.items()))
    if not mets.is_empty():
        t = Table(title="metrics", title_justify="left")
        names = sorted(set(mets["name"]))
        t.add_column("fold")
        for n in names:
            t.add_column(n, justify="right")
        for fold in mets["fold"].unique(maintain_order=True):
            sub = mets.filter(pl.col("fold").is_null() if fold is None else pl.col("fold") == fold)
            vals = dict(zip(sub["name"], sub["value"], strict=True))
            t.add_row("all" if fold is None else str(fold), *(f"{vals[n]:.4g}" if n in vals else "" for n in names))
        console.print(t)


if __name__ == "__main__":
    main()
