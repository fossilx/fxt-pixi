""" Touch pass (triple-barrier labeling, step 1): which barrier price hit first
    after each event. Writes data/research/touches (ML pipeline spec §6.1).

    pixi run touches EURJPY                          # default events (CUSUM h=3), k=1.0, N=48
    pixi run touches EURJPY --k 0.5 --n 24
    pixi run touches EURJPY --sweep 0.5x24,1x48,1x120   # compare barrier setups; writes nothing
    pixi run touches EURJPY --events 6faf936c570f    # label a specific event set
    pixi run touches EURJPY --ambiguity ohlc         # no raw ticks needed for same-minute ties
"""
from __future__ import annotations

import click
from rich.console import Console
from rich.table import Table

from fxt.research.events import InputBarsError
from fxt.research.labels import EventsBarsMismatch, InputEventsError, build_touches
from fxt.research.models import CusumEventsConfig, TripleBarrierTouchConfig

console = Console()


def _table(title: str) -> Table:
    t = Table(title=title, title_justify="left")
    for col in ("config", "placed", "upper", "lower", "timeout", "median hours up/down/all",
                "insufficient", "same-minute ties", "gap exits"):
        t.add_column(col)
    return t


def _row(t: Table, label: str, s: dict) -> None:
    sh, mh = s["share"], s["median_hours"]
    fmt = lambda x: "-" if x is None else f"{x:.1f}"
    ties = {k: v for k, v in s["resolution"].items() if k != "bar"}
    t.add_row(label, f"{s['placed']}/{s['events']}", f"{sh['upper']:.0%}", f"{sh['lower']:.0%}",
              f"{sh['vertical']:.0%}", f"{fmt(mh['upper'])} / {fmt(mh['lower'])} / {fmt(s['median_hours_all'])}",
              ", ".join(f"{k}: {v}" for k, v in s["insufficient"].items()) or "—",
              ", ".join(f"{k}: {v}" for k, v in ties.items()) or "none", str(s["gap_exits"]))


@click.command(help=__doc__)
@click.argument("symbols", nargs=-1, required=True)
@click.option("--source", default="dukascopy", show_default=True)
@click.option("--market", default="forex", show_default=True)
@click.option("--events", "events_hash", default=None, help="events config hash (default: CUSUM defaults)")
@click.option("--k", type=float, default=None, help="barrier half-width in horizon-sigmas (default 1.0)")
@click.option("--n", "n_bars", type=int, default=None, help="vertical barrier in hourly bars (default 48)")
@click.option("--ambiguity", type=click.Choice(["ticks", "ohlc"]), default=None)
@click.option("--sweep", default=None, help="comma-separated KxN pairs, e.g. 0.5x24,1x48; writes nothing")
@click.option("--dry-run", is_flag=True)
def main(symbols, source, market, events_hash, k, n_bars, ambiguity, sweep, dry_run) -> None:
    base = {"events_hash": events_hash or CusumEventsConfig().config_hash()}
    for key, v in (("k", k), ("vertical_bars", n_bars), ("ambiguity", ambiguity)):
        if v is not None:
            base[key] = v
    configs = [TripleBarrierTouchConfig(**base)]
    if sweep:
        configs = []
        for pair in sweep.split(","):
            kk, nn = pair.lower().split("x")
            configs.append(TripleBarrierTouchConfig(**{**base, "k": float(kk), "vertical_bars": int(nn)}))

    for symbol in symbols:
        table = _table(f"{symbol}: {'sweep (nothing written)' if sweep else 'dry run' if dry_run else 'written'}")
        try:
            for cfg in configs:
                write = not (sweep or dry_run)
                res = build_touches(cfg, source=source, market=market, symbol=symbol, write=write,
                                    log=(lambda m: None) if sweep else (lambda m: console.print(f"[dim]{m}[/]")))
                _row(table, f"{cfg.label} ({res.config_hash})", res.stats)
                for p in res.paths:
                    console.print(f"  [green]✓[/] {p}")
        except (InputBarsError, InputEventsError, EventsBarsMismatch) as e:
            console.print(f"[red]{symbol}: {e}[/]")
            continue
        console.print(table)


if __name__ == "__main__":
    main()
