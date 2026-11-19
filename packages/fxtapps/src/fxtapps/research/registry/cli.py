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


RUN_METRICS = ("n_trades", "net_bp", "sharpe_ann", "psr", "dsr")


def _config_label(reg, config_hash: str | None) -> str:
    """ A config's short label (e.g. "logistic", "threshold0.45"), else its class name. """
    if not config_hash:
        return ""
    from fxt.research.models import registry as config_registry
    c = reg.config(config_hash)
    if c is None:
        return config_hash
    typeid = f"{c['model_type']}@{c['model_version']}"
    try:
        return str(config_registry.get_model(typeid).model_validate(c["config"]).label)
    except Exception:                                   # unknown or changed class: show what's stored
        return c["model_type"]


def _kind(r: dict) -> str:
    """ trial / control / lockbox, plus the status unless the run finished normally. """
    kind = "lockbox" if r["is_lockbox"] else r.get("purpose", "trial")
    return kind if r["status"] == "done" else f"{kind} ({r['status']})"


@main.command()
@click.argument("strategy", required=False)
@click.option("--controls/--no-controls", default=True, show_default=True, help="include baseline (control) runs")
@click.option("--wide", is_flag=True, help="also show the data span and notes")
def runs(strategy: str | None, controls: bool, wide: bool) -> None:
    """ List runs (optionally one strategy): model, sizer, headline results. """
    with get_registry() as reg:
        df = reg.runs(strategy)
        if not controls:
            df = df.filter(pl.col("purpose") != "control")
        trials = reg.trial_count(strategy)
        rows = []
        for r in df.iter_rows(named=True):
            cfgs = reg.run_configs(r["run_id"])
            mets = reg.metrics(r["run_id"]).filter(pl.col("fold").is_null())
            agg = dict(zip(mets["name"], mets["value"], strict=True))
            rows.append({**r, "kind": _kind(r), "model": _config_label(reg, cfgs.get("model")),
                         "sizer": _config_label(reg, cfgs.get("sizer")), **{k: agg.get(k) for k in RUN_METRICS}})
    if not rows:
        console.print("no runs")
        return
    t = Table(title=f"runs ({trials} trial(s) excl. lockbox; controls don't count)", title_justify="left")
    spec = [("run_id", "run_id", None), ("strategy_id", "strategy", None), ("model", "model", None),
            ("sizer", "sizer", None), ("kind", "kind", None), ("n_trades", "trades", "{:,.0f}"),
            ("net_bp", "net bp", "{:+.2f}"), ("sharpe_ann", "sharpe", "{:+.2f}"), ("psr", "psr", "{:.3f}"),
            ("dsr", "dsr*", "{:.3f}")]
    if wide:
        spec += [("data_start", "from", None), ("data_end", "to", None), ("notes", "notes", None)]
    for key, head, fmt in spec:
        if key == "run_id":                              # never shortened: it's what you copy
            t.add_column(head, no_wrap=True, min_width=22)
        elif key == "notes":
            t.add_column(head, overflow="fold")
        else:
            t.add_column(head, no_wrap=True, justify="right" if fmt else "left")
    for r in rows:
        cells = []
        for key, _, fmt in spec:
            v = r.get(key)
            if v is None or (isinstance(v, float) and v != v):        # noqa: PLR0124
                cells.append("")
            else:
                cells.append(fmt.format(v) if fmt else str(v))
        t.add_row(*cells)
    console.print(t)
    console.print("[dim]* dsr as of when the run finished; `registry run RUN_ID` recomputes it against today's "
                  "trials. --wide adds the data span and notes.[/]")


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
        dsr_now = _dsr_now(reg, run_id, info.row(0, named=True), mets)
    for k, v in info.row(0, named=True).items():
        console.print(f"[bold]{k:<12}[/] {v}")
    console.print("[bold]configs[/]      " + ", ".join(f"{r}={h}" for r, h in cfgs.items()))
    if dsr_now is not None:
        console.print(f"[bold]DSR now[/]      {dsr_now.dsr:.3f} against {dsr_now.n_trials} trials "
                      f"(expected best daily Sharpe {dsr_now.sr0:.4f}); PSR {dsr_now.psr:.3f}")
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


def _dsr_now(reg, run_id: str, info: dict, mets: pl.DataFrame):
    """ The run's deflated Sharpe against every trial recorded so far (it changes as trials accrue). """
    from fxt.research.harness import deflated_sharpe
    if info.get("purpose", "trial") != "trial" or info["status"] != "done":
        return None
    agg = {r["name"]: r["value"] for r in mets.filter(pl.col("fold").is_null()).iter_rows(named=True)}
    if not all(k in agg for k in ("sharpe_daily", "skew_daily", "kurt_daily", "n_days")):
        return None
    return deflated_sharpe(agg["sharpe_daily"], int(agg["n_days"]), agg["skew_daily"], agg["kurt_daily"],
                           reg.trial_count(include_lockbox=True),
                           [*reg.trial_metric("sharpe_daily", exclude_run=run_id), agg["sharpe_daily"]])


if __name__ == "__main__":
    main()
