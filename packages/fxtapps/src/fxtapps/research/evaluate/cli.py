""" Evaluate a strategy through the harness: purged walk-forward CV, a meta-model, a sizer,
    the cost-aware backtest (ML pipeline spec §9). Every run is recorded in the registry
    (data/experiments.db) and counts as a trial; predictions go to
    data/research/predictions/run=<run_id>/.

    pixi run evaluate EURJPY                                  # take_all on cusum_h3_follow (the baseline)
    pixi run evaluate EURJPY --model logistic
    pixi run evaluate EURJPY --model logistic --sizer threshold --threshold 0.45
    pixi run evaluate EURJPY --side fade
    pixi run evaluate EURJPY --labels 3b896dab2027 --features ret_24h_z,vol_ratio_24h_120h
    pixi run evaluate EURJPY --lockbox                        # ONE look per strategy, ever
"""
from __future__ import annotations

import click
from rich.console import Console
from rich.table import Table

from fxt.research.events import InputBarsError
from fxt.research.harness import InputDatasetError, evaluate, load_dataset
from fxt.research.models import (
    BacktestConfig, CusumEventsConfig, LogisticModelConfig, SideLabelsConfig, SizerConfig, TakeAllModelConfig,
    TripleBarrierTouchConfig, WalkForwardConfig,
)
from fxt.research.registry import LockboxAlreadyUsed
from fxt.services import get_lake, get_registry, get_research

console = Console()

FOLD_COLUMNS = (("test_year", "year", "{}"), ("n_train", "train", "{:,}"), ("n_test", "test", "{:,}"),
                ("clf_auc", "auc", "{:.3f}"), ("clf_log_loss_skill", "ll skill", "{:+.3f}"),
                ("n_trades", "trades", "{:,.0f}"), ("gross_bp", "gross bp", "{:+.2f}"),
                ("cost_bp", "cost bp", "{:.2f}"), ("net_bp", "net bp", "{:+.2f}"),
                ("hit_rate", "hit", "{:.1%}"), ("sharpe_ann", "sharpe", "{:+.2f}"),
                ("max_dd_bp", "max dd bp", "{:,.0f}"))


def _fmt(fmt: str, v) -> str:
    if v is None or (isinstance(v, float) and v != v):     # noqa: PLR0124
        return "-"
    return fmt.format(v)


@click.command(help=__doc__)
@click.argument("symbol")
@click.option("--source", default="dukascopy", show_default=True)
@click.option("--market", default="forex", show_default=True)
@click.option("--labels", "labels_hash", help="labels config hash (default: --side on the default touches)")
@click.option("--side", type=click.Choice(["follow", "fade"]), default="follow", show_default=True)
@click.option("--weights", "weights_hash", help="weights config hash (default: the default for the labels)")
@click.option("--features", "features_hash", help="features config hash (default: baseline)")
@click.option("--model", type=click.Choice(["take_all", "logistic"]), default="take_all", show_default=True)
@click.option("--use", "use_features", default="", help="comma-separated feature names (logistic; default all)")
@click.option("--l2", type=float, default=1e-2, show_default=True)
@click.option("--sample-weight", type=click.Choice(["weight", "weight_uniq", "none"]), default="weight",
              show_default=True)
@click.option("--sizer", type=click.Choice(["take_all", "threshold", "linear"]), default="take_all",
              show_default=True)
@click.option("--threshold", type=float, default=0.5, show_default=True)
@click.option("--slippage", type=float, default=0.2, show_default=True, help="pips per side")
@click.option("--commission", type=float, default=0.0, show_default=True, help="bp per round trip")
@click.option("--cap", type=float, default=None, help="position cap (total open size)")
@click.option("--lockbox", is_flag=True, help="evaluate on the lockbox year (one look per strategy)")
@click.option("--notes", default=None)
def main(symbol, source, market, labels_hash, side, weights_hash, features_hash, model, use_features, l2,
         sample_weight, sizer, threshold, slippage, commission, cap, lockbox, notes) -> None:
    if labels_hash is None:
        th = TripleBarrierTouchConfig(events_hash=CusumEventsConfig().config_hash()).config_hash()
        labels_hash = SideLabelsConfig(touches_hash=th, side_rule=side).config_hash()
    feats = tuple(f.strip() for f in use_features.split(",") if f.strip())
    mcfg = (TakeAllModelConfig(sample_weight=sample_weight) if model == "take_all"
            else LogisticModelConfig(features=feats, l2=l2, sample_weight=sample_weight))
    scfg = SizerConfig(rule=sizer, threshold=threshold)
    bcfg = BacktestConfig(slippage_pips=slippage, commission_bp=commission, position_cap=cap)
    cv = WalkForwardConfig()

    if lockbox and not click.confirm(f"Lockbox run on {cv.lockbox_year}: one look per strategy, ever. Continue?"):
        raise SystemExit(1)
    try:
        research = get_research()
        ds = load_dataset(research, get_lake(), labels_hash=labels_hash, source=source, market=market,
                          symbol=symbol, weights_hash=weights_hash, features_hash=features_hash)
        with get_registry() as reg:
            res = evaluate(ds, model=mcfg, sizer=scfg, backtest=bcfg, cv=cv, lockbox=lockbox, registry=reg,
                           research=research, notes=notes, log=lambda m: console.print(f"[dim]{m}[/]"))
            trials = reg.trial_count(ds.strategy_id)
    except (InputDatasetError, InputBarsError, LockboxAlreadyUsed, ValueError) as e:
        raise click.ClickException(str(e)) from e

    t = Table(title=f"{symbol} {res.strategy_id} / {mcfg.label} / {scfg.label}  run {res.run_id}",
              title_justify="left")
    for _, head, _ in FOLD_COLUMNS:
        t.add_column(head, justify="right")
    for row in res.folds.iter_rows(named=True):
        t.add_row(*(_fmt(fmt, row.get(col)) for col, _, fmt in FOLD_COLUMNS))
    a = res.aggregate
    t.add_row("all", "", _fmt("{:,.0f}", a.get("clf_n")),
              *(_fmt(fmt, a.get(col)) for col, _, fmt in FOLD_COLUMNS[3:]), style="bold")
    console.print(t)
    console.print(f"t (effective n {a.get('n_eff', 0):,.0f}): {_fmt('{:+.2f}', a.get('t_eff'))}   "
                  f"folds net positive: {a['folds_net_positive']:.0f}/{a['n_folds']:.0f}   "
                  f"calibration error: {_fmt('{:.3f}', a.get('clf_ece'))}")
    console.print(f"PSR (P[Sharpe > 0]): {_fmt('{:.3f}', a.get('psr'))}   "
                  f"DSR (vs best of {a.get('n_trials', 0):.0f} trials): {_fmt('{:.3f}', a.get('dsr'))}   "
                  f"trials for {res.strategy_id}: {trials}")


if __name__ == "__main__":
    main()
