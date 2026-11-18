""" Side labels (triple-barrier labeling, step 2): apply a side rule to each
    event and read its touch as profit-take / stop-loss / timeout. Writes
    data/research/labels, one config per side rule (ML pipeline spec §6.3).

    pixi run labels EURJPY                        # follow AND fade on the default touch pass
    pixi run labels EURJPY --side fade
    pixi run labels EURJPY --touches 5e8aa6660716 # label a specific touch pass
    pixi run labels EURJPY --timeout-win          # count timeouts with ret > 0 as wins (default: no)
    pixi run labels EURJPY --dry-run              # stats only
"""
from __future__ import annotations

import click
from rich.console import Console
from rich.table import Table

from fxt.research.labels import InputEventsError, InputTouchesError, build_labels
from fxt.research.models import CusumEventsConfig, SideLabelsConfig, TripleBarrierTouchConfig

console = Console()


def _bp(x: float | None) -> str:
    return "-" if x is None else f"{x * 1e4:+.1f}"


@click.command(help=__doc__)
@click.argument("symbols", nargs=-1, required=True)
@click.option("--source", default="dukascopy", show_default=True)
@click.option("--market", default="forex", show_default=True)
@click.option("--touches", "touches_hash", default=None,
              help="touch-pass config hash (default: default touches on the default CUSUM events)")
@click.option("--side", "sides", default="follow,fade", show_default=True, help="comma-separated side rules")
@click.option("--timeout-win", is_flag=True, help="timeouts with a positive side-adjusted return count as wins")
@click.option("--dry-run", is_flag=True)
def main(symbols, source, market, touches_hash, sides, timeout_win, dry_run) -> None:
    th = touches_hash or TripleBarrierTouchConfig(events_hash=CusumEventsConfig().config_hash()).config_hash()
    configs = [SideLabelsConfig(touches_hash=th, side_rule=s.strip(), timeout_positive_is_win=timeout_win)
               for s in sides.split(",")]

    for symbol in symbols:
        t = Table(title=f"{symbol}: labels on touches {th}{' (dry run)' if dry_run else ''}", title_justify="left")
        for col in ("strategy", "config", "labeled", "pt", "sl", "timeout", "win rate (meta_label)",
                    "mean ret bp", "mean ret bp pt / sl / timeout"):
            t.add_column(col)
        try:
            for cfg in configs:
                res = build_labels(cfg, source=source, market=market, symbol=symbol, write=not dry_run,
                                   log=lambda m: console.print(f"[dim]{m}[/]"))
                s = res.stats
                by = s["mean_ret_by_outcome"]
                t.add_row(res.strategy_id, res.config_hash, f"{s['placed']}/{s['events']}",
                          f"{s['share']['pt']:.1%}", f"{s['share']['sl']:.1%}", f"{s['share']['timeout']:.1%}",
                          "-" if s["win_rate"] is None else f"{s['win_rate']:.1%}", _bp(s["mean_ret"]),
                          " / ".join(_bp(by.get(o)) for o in ("pt", "sl", "timeout")))
        except (InputTouchesError, InputEventsError) as e:
            console.print(f"[red]{symbol}: {e}[/]")
            continue
        console.print(t)
        console.print("[dim]returns are mid, gross of spread and costs[/]")


if __name__ == "__main__":
    main()
