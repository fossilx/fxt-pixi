""" Break a finished run down by symbol and test year, from its own out-of-fold predictions
    (data/research/predictions/run=<RUN_ID>/). Fits nothing, so it isn't a new trial.

    pixi run run-report RUN_ID             # print symbol x year
    pixi run run-report RUN_ID --save      # also store per-symbol per-fold metrics in the registry
"""
from __future__ import annotations

import click
from rich.console import Console
from rich.table import Table

from fxt.research.harness import breakdown, load_predictions, save_breakdown
from fxt.research.models import BacktestConfig, registry as config_registry
from fxt.services import get_registry, get_research

console = Console()


def _f(v, fmt: str) -> str:
    return "-" if v is None or v != v else fmt.format(v)     # noqa: PLR0124


@click.command(help=__doc__)
@click.argument("run_id")
@click.option("--save", is_flag=True, help="store the per-symbol per-fold rows as registry metrics")
def main(run_id: str, save: bool) -> None:
    with get_registry() as reg:
        info = reg.query("SELECT strategy_id, symbols, status FROM runs WHERE run_id = ?", (run_id,))
        if info.is_empty():
            raise click.ClickException(f"no run {run_id}")
        bt_hash = reg.run_configs(run_id).get("backtest")
        c = reg.config(bt_hash) if bt_hash else None
        bt = (config_registry.get_model(f"{c['model_type']}@{c['model_version']}").model_validate(c["config"])
              if c else BacktestConfig())
        try:
            pred = load_predictions(get_research(), run_id)
        except FileNotFoundError as e:
            raise click.ClickException(str(e)) from e
        by = breakdown(pred, bt)
        n = save_breakdown(reg, run_id, by) if save else 0

    r = info.row(0, named=True)
    t = Table(title=f"run {run_id}  {r['strategy_id']}  {r['symbols']}", title_justify="left")
    cols = (("symbol", "{}"), ("test_year", "{}"), ("n_events", "{:,}"), ("n_trades", "{:,.0f}"),
            ("gross_bp", "{:+.2f}"), ("cost_bp", "{:.2f}"), ("net_bp", "{:+.2f}"), ("hit_rate", "{:.1%}"),
            ("sharpe_ann", "{:+.2f}"), ("dir_auc", "{:.3f}"))
    for name, _ in cols:
        t.add_column(name.replace("_", " "), justify="left" if name == "symbol" else "right")
    prev = None
    for row in by.iter_rows(named=True):
        if prev is not None and row["symbol"] != prev:
            t.add_section()
        prev = row["symbol"]
        cells = [("all" if row["test_year"] is None and k == "test_year" else _f(row[k], fmt)) for k, fmt in cols]
        t.add_row(*cells, style="bold" if row["test_year"] is None else None)
    console.print(t)
    if save:
        console.print(f"saved {n} per-symbol fold metrics to the registry")


if __name__ == "__main__":
    main()
