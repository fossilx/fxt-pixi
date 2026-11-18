""" CUSUM events: detect on every year of a symbol's 1HOUR bars and write them to
    data/research/events (ML pipeline spec §5.1).

    pixi run events-cusum EURJPY                     # build with the default config (h=3)
    pixi run events-cusum EURJPY GBPJPY --h 2.5      # several symbols, another threshold
    pixi run events-cusum EURJPY --sweep 2,3,4,5     # compare thresholds; writes nothing
    pixi run events-cusum EURJPY --dry-run           # stats only
"""
from __future__ import annotations

import click
from rich.console import Console
from rich.table import Table

from fxt.research.events import InputBarsError, build_events
from fxt.research.models import CusumEventsConfig

console = Console()


def _stats_row(table: Table, label: str, s: dict) -> None:
    per_year = ", ".join(f"{y}: {n}" for y, n in s["per_year"].items())
    table.add_row(label, str(s["events"]), f"{s['per_active_day']:.2f}", f"{s['up']}/{s['down']}",
                  f"{s['gap_hours_p10']:.1f} / {s['gap_hours_median']:.1f} / {s['gap_hours_p90']:.1f}",
                  per_year)


def _table(title: str) -> Table:
    t = Table(title=title, title_justify="left")
    for col in ("config", "events", "per day", "up/down", "hours between p10/med/p90", "per year"):
        t.add_column(col)
    return t


@click.command(help=__doc__)
@click.argument("symbols", nargs=-1, required=True)
@click.option("--source", default="dukascopy", show_default=True)
@click.option("--market", default="forex", show_default=True)
@click.option("--h", "h", type=float, default=None, help="CUSUM threshold (default: config default, 3.0)")
@click.option("--sweep", default=None, help="comma-separated h values to compare; writes nothing")
@click.option("--dry-run", is_flag=True, help="detect and report, but don't write")
def main(symbols: tuple[str, ...], source: str, market: str, h: float | None,
         sweep: str | None, dry_run: bool) -> None:
    base = CusumEventsConfig() if h is None else CusumEventsConfig(h=h)

    for symbol in symbols:
        try:
            if sweep:
                table = _table(f"{symbol}: h sweep (nothing written)")
                for hv in (float(x) for x in sweep.split(",")):
                    cfg = CusumEventsConfig(**{**base.model_dump(), "h": hv})
                    res = build_events(cfg, source=source, market=market, symbol=symbol, write=False)
                    _stats_row(table, f"{cfg.label} ({res.config_hash})", res.stats)
                console.print(table)
                continue

            res = build_events(base, source=source, market=market, symbol=symbol,
                               write=not dry_run, log=lambda m: console.print(f"[dim]{m}[/]"))
        except InputBarsError as e:
            console.print(f"[red]{symbol}: {e}[/]")
            continue

        table = _table(f"{symbol}: {'dry run' if dry_run else 'written'}")
        _stats_row(table, f"{base.label} ({res.config_hash})", res.stats)
        console.print(table)
        for p in res.paths:
            console.print(f"  [green]✓[/] {p}")


if __name__ == "__main__":
    main()
