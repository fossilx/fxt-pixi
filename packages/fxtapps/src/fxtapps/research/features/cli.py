""" Feature table: per-bar features in long format, shared by every strategy.
    Writes data/research/features (ML pipeline spec §4).

    pixi run features EURJPY                 # the default sets: baseline (24h / 120h), trend, flow
    pixi run features EURJPY EURUSD USDJPY --set cross                      # cross-pair set, EUR/USD/JPY basket
    pixi run features GBPJPY --set cross --basket EURJPY,EURUSD,GBPJPY,GBPUSD,USDJPY
    pixi run features EURJPY --set flow      # one set (flow reads the 1MIN bars)
    pixi run features EURJPY --set baseline --short 12 --long 72
    pixi run features EURJPY --dry-run       # coverage and distributions only
"""
from __future__ import annotations

import click
from rich.console import Console
from rich.table import Table

from fxt.research.events import InputBarsError
from fxt.research.features import build_features
from fxt.research.models import BarFeaturesConfig, CrossFeaturesConfig, FlowFeaturesConfig, TrendFeaturesConfig

console = Console()


@click.command(help=__doc__)
@click.argument("symbols", nargs=-1, required=True)
@click.option("--source", default="dukascopy", show_default=True)
@click.option("--market", default="forex", show_default=True)
@click.option("--short", "short", type=int, default=None, help="short window in bars (default 24)")
@click.option("--long", "long_", type=int, default=None, help="long window in bars (default 120)")
@click.option("--set", "sets", default="baseline,trend,flow", show_default=True,
              help="comma-separated feature sets: baseline, trend, flow, cross")
@click.option("--basket", default=None, help="cross set: comma-separated basket pairs (default EURJPY,EURUSD,USDJPY)")
@click.option("--dry-run", is_flag=True)
def main(symbols, source, market, short, long_, sets, basket, dry_run) -> None:
    kw = {k: v for k, v in (("short", short), ("long", long_)) if v is not None}
    configs = []
    for name in (x.strip() for x in sets.split(",") if x.strip()):
        if name == "baseline":
            configs.append(BarFeaturesConfig(**kw))
        elif name == "trend":
            configs.append(TrendFeaturesConfig())
        elif name == "flow":
            configs.append(FlowFeaturesConfig())
        elif name == "cross":
            ckw = {"basket": tuple(sorted({b.strip().upper() for b in basket.split(",") if b.strip()}))} if basket else {}
            configs.append(CrossFeaturesConfig(**ckw))
        else:
            raise click.BadParameter(f"unknown feature set {name!r}", param_hint="--set")
    for cfg in configs:
        _build(cfg, symbols, source, market, dry_run)


def _build(cfg, symbols, source, market, dry_run) -> None:
    for symbol in symbols:
        try:
            res = build_features(cfg, source=source, market=market, symbol=symbol, write=not dry_run,
                                 log=lambda m: console.print(f"[dim]{m}[/]"))
        except InputBarsError as e:
            console.print(f"[red]{symbol}: {e}[/]")
            continue
        t = Table(title=f"{symbol}: {cfg.label} ({res.config_hash}){' (dry run)' if dry_run else ''}",
                  title_justify="left")
        for col in ("name", "coverage", "mean", "std", "p01", "median", "p99"):
            t.add_column(col, justify="left" if col == "name" else "right")
        for r in res.stats.iter_rows(named=True):
            vals = ["-" if r[k] is None else f"{r[k]:.4g}" for k in ("mean", "std", "p01", "median", "p99")]
            t.add_row(r["name"], "-" if r["coverage"] is None else f"{r['coverage']:.1%}", *vals)
        console.print(t)


if __name__ == "__main__":
    main()
