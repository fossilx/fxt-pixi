""" Random-entry baseline (ML pipeline spec §9.6): SEEDS random strategies with the same
    event rate, barriers, side-label settings, costs and folds as a candidate's labels,
    each evaluated with take_all. Recorded in the registry as controls (not trials).
    Builds only what's missing, and reuses finished control runs.

    pixi run random-baseline EURJPY                          # 20 seeds, like the default cusum_h3_follow labels
    pixi run random-baseline EURJPY --seeds 50 --compare RUN_ID
    pixi run random-baseline EURJPY EURUSD USDJPY --compare RUN_ID   # pooled, for a pooled run
    pixi run random-baseline EURJPY --like 3b896dab2027 --fire-prob 0.0935
"""
from __future__ import annotations

import click
from rich.console import Console
from rich.table import Table

from fxt.research.events import InputBarsError
from fxt.research.harness import InputDatasetError, compare, random_baseline
from fxt.research.models import CusumEventsConfig, SideLabelsConfig, TripleBarrierTouchConfig
from fxt.services import get_lake, get_registry, get_research

console = Console()


def _f(v, fmt="{:+.2f}") -> str:
    return "-" if v is None or v != v else fmt.format(v)     # noqa: PLR0124


@click.command(help=__doc__)
@click.argument("symbols", nargs=-1, required=True)
@click.option("--source", default="dukascopy", show_default=True)
@click.option("--market", default="forex", show_default=True)
@click.option("--like", "like_labels", help="candidate labels hash (default: cusum_h3_follow defaults)")
@click.option("--seeds", type=int, default=20, show_default=True, help="number of seeds")
@click.option("--first-seed", type=int, default=0, show_default=True)
@click.option("--fire-prob", type=float, default=0.0935, show_default=True, help="per-bar fire probability")
@click.option("--compare", "compare_run", help="a run to place within the baseline distribution")
def main(symbols, source, market, like_labels, seeds, first_seed, fire_prob, compare_run) -> None:
    if like_labels is None:
        th = TripleBarrierTouchConfig(events_hash=CusumEventsConfig().config_hash()).config_hash()
        like_labels = SideLabelsConfig(touches_hash=th).config_hash()
    try:
        with get_registry() as reg:
            base = random_baseline(get_research(), get_lake(), reg, like_labels=like_labels, source=source,
                                   market=market, symbol=list(dict.fromkeys(symbols)), seeds=range(first_seed, first_seed + seeds),
                                   fire_prob=fire_prob, log=lambda m: console.print(f"[dim]{m}[/]"))
            cmp = compare(base, reg, compare_run) if compare_run else None
    except (InputDatasetError, InputBarsError, KeyError) as e:
        raise click.ClickException(str(e)) from e

    r = base.runs
    t = Table(title=f"{'+'.join(sorted(set(symbols)))} random entry ({r.height} seeds, p={fire_prob:g}) like labels {like_labels}",
              title_justify="left")
    for c in ("", "trades", "gross bp", "cost bp", "net bp", "hit", "sharpe"):
        t.add_column(c, justify="right")
    cols = ("n_trades", "gross_bp", "cost_bp", "net_bp", "hit_rate", "sharpe_ann")
    fmts = ("{:,.0f}", "{:+.2f}", "{:.2f}", "{:+.2f}", "{:.1%}", "{:+.2f}")
    for name, q in (("mean", None), ("5%", 0.05), ("50%", 0.5), ("95%", 0.95)):
        vals = [r[c].mean() if q is None else r[c].quantile(q) for c in cols]
        t.add_row(name, *(_f(v, f) for v, f in zip(vals, fmts, strict=True)))
    console.print(t)
    if cmp is not None:
        c = Table(title=f"run {compare_run} vs the baseline", title_justify="left")
        for h in ("metric", "run", "baseline mean", "5%", "95%", "share of seeds ≥ run"):
            c.add_column(h, justify="right")
        for row in cmp.iter_rows(named=True):
            c.add_row(row["metric"], _f(row["candidate"], "{:+.3f}"), _f(row["mean"], "{:+.3f}"),
                      _f(row["p05"], "{:+.3f}"), _f(row["p95"], "{:+.3f}"), _f(row["p_value"], "{:.3f}"))
        console.print(c)


if __name__ == "__main__":
    main()
