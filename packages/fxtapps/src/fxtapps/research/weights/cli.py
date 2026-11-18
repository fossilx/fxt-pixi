""" Sample weights: concurrency-based uniqueness of each label over business
    time. Writes data/research/weights, one file per symbol per labels config
    (ML pipeline spec §7).

    pixi run weights EURJPY                        # follow and fade labels on the default touches
    pixi run weights EURJPY --labels 3b896dab2027  # a specific labels config (repeatable)
    pixi run weights EURJPY --dry-run
"""
from __future__ import annotations

import click
from rich.console import Console
from rich.table import Table

from fxt.research.events import InputBarsError
from fxt.research.models import (
    CusumEventsConfig, SampleWeightsConfig, SideLabelsConfig, TripleBarrierTouchConfig,
)
from fxt.research.weights import InputLabelsError, build_weights

console = Console()


@click.command(help=__doc__)
@click.argument("symbols", nargs=-1, required=True)
@click.option("--source", default="dukascopy", show_default=True)
@click.option("--market", default="forex", show_default=True)
@click.option("--labels", "labels_hashes", multiple=True,
              help="labels config hash(es) (default: follow + fade on the default touches)")
@click.option("--dry-run", is_flag=True)
def main(symbols, source, market, labels_hashes, dry_run) -> None:
    if not labels_hashes:
        th = TripleBarrierTouchConfig(events_hash=CusumEventsConfig().config_hash()).config_hash()
        labels_hashes = tuple(SideLabelsConfig(touches_hash=th, side_rule=s).config_hash()
                              for s in ("follow", "fade"))

    for symbol in symbols:
        t = Table(title=f"{symbol}: sample weights{' (dry run)' if dry_run else ''}", title_justify="left")
        for col in ("strategy", "labels", "config", "weighted", "mean uniqueness", "mean / max concurrency",
                    "independent samples ~", "weight share vs event share (pt / sl / timeout)"):
            t.add_column(col)
        try:
            for lh in labels_hashes:
                res = build_weights(SampleWeightsConfig(labels_hash=lh), source=source, market=market,
                                    symbol=symbol, write=not dry_run, log=lambda m: console.print(f"[dim]{m}[/]"))
                s = res.stats
                if not s.get("weighted"):
                    t.add_row(res.strategy_id, lh, res.config_hash, f"0/{s['labels']}", "-", "-", "-", "-")
                    continue
                share = s["weight_share_by_outcome"]
                t.add_row(res.strategy_id, lh, res.config_hash, f"{s['weighted']}/{s['labels']}",
                          f"{s['mean_uniqueness']:.2f}", f"{s['mean_concurrency']:.1f} / {s['max_concurrency']:.1f}",
                          f"{s['independent_samples']:.0f}",
                          " / ".join(f"{share[o][0]:.0%} vs {share[o][1]:.0%}" if o in share else "-"
                                     for o in ("pt", "sl", "timeout")))
        except (InputLabelsError, InputBarsError) as e:
            console.print(f"[red]{symbol}: {e}[/]")
            continue
        console.print(t)


if __name__ == "__main__":
    main()
