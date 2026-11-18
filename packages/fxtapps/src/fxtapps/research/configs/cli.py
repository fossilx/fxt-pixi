""" What each config hash in data/research means.

    pixi run research-configs                    # every config folder, all stages
    pixi run research-configs --stage events
    pixi run research-configs 6faf936c570f       # full detail for one hash (any stage)
    pixi run research-configs --json             # one JSON object per line, for scripts
"""
from __future__ import annotations

import json
from datetime import UTC

import click
from rich.console import Console
from rich.table import Table

from fxt.research import Stage
from fxt.research.inventory import ConfigEntry, config_inventory

console = Console()


def years_text(years: tuple[int | None, ...]) -> str:
    """ (2020, 2021, 2022, 2024) -> "2020–2022, 2024"; (None,) -> "all". """
    ys = [y for y in years if y is not None]
    if not ys:
        return "all"
    runs: list[list[int]] = []
    for y in ys:
        if runs and y == runs[-1][-1] + 1:
            runs[-1].append(y)
        else:
            runs.append([y])
    return ", ".join(f"{r[0]}–{r[-1]}" if len(r) > 1 else str(r[0]) for r in runs)


def _series_text(e: ConfigEntry) -> str:
    return "\n".join(f"{k.rsplit('/', 1)[-1]}: {years_text(v)}" for k, v in e.series.items())


def _changed_text(e: ConfigEntry) -> str:
    inputs = {f"{role}_hash" for role in e.input_hashes}
    parts = [f"{k}={v}" for k, v in e.changed.items() if k not in inputs]
    return " ".join(parts) or "[dim]defaults[/]"


def _summary(entries: list[ConfigEntry]) -> None:
    t = Table(title="data/research configs", title_justify="left")
    for col in ("stage", "hash", "config", "changed from defaults", "inputs", "series", "rows", "created"):
        t.add_column(col, overflow="fold")
    for e in entries:
        name = e.config_typeid + ("" if e.known_class else " [yellow](unknown class)[/]")
        if e.problems:
            name += f"\n[red]{len(e.problems)} problem(s)[/]"
        t.add_row(str(e.stage), e.config_hash, name, _changed_text(e),
                  "\n".join(f"{r}={h}" for r, h in e.input_hashes.items()) or "—",
                  _series_text(e), f"{e.rows:,}",
                  e.created_last.astimezone(UTC).strftime("%Y-%m-%d %H:%M"))
    console.print(t)


def _detail(e: ConfigEntry) -> None:
    console.rule(f"[bold]{e.stage} / config={e.config_hash}[/]")
    console.print(f"[bold]class[/]     {e.config_typeid}"
                  + ("" if e.known_class else "  [yellow](not registered in this code)[/]"))
    console.print("[bold]config[/]")
    width = max(len(k) for k in e.config) if e.config else 0
    for k, v in sorted(e.config.items()):
        mark = "[cyan]*[/]" if k in e.changed else " "
        console.print(f"  {mark} {k:<{width}}  {json.dumps(v)}")
    console.print("    [dim]* = differs from the class default (or has none)[/]")
    if e.input_hashes:
        console.print("[bold]inputs[/]    " + ", ".join(f"{r}={h}" for r, h in e.input_hashes.items()))
    console.print(f"[bold]files[/]     {e.files} ({e.rows:,} rows)")
    for k, v in e.series.items():
        console.print(f"  {k}: {years_text(v)}")
    console.print(f"[bold]created[/]   {e.created_first:%Y-%m-%d %H:%M} → {e.created_last:%Y-%m-%d %H:%M} UTC")
    if e.code_versions:
        console.print(f"[bold]code[/]      {', '.join(e.code_versions)}")
    for p in e.problems:
        console.print(f"[red]problem[/]   {p}")


def _json(e: ConfigEntry) -> str:
    return json.dumps({
        "stage": str(e.stage), "config_hash": e.config_hash, "config_typeid": e.config_typeid,
        "config": e.config, "changed": e.changed, "input_hashes": e.input_hashes,
        "series": {k: list(v) for k, v in e.series.items()}, "files": e.files, "rows": e.rows,
        "created_first": e.created_first.isoformat(), "created_last": e.created_last.isoformat(),
        "code_versions": list(e.code_versions), "known_class": e.known_class,
        "problems": list(e.problems),
    })


@click.command(help=__doc__)
@click.argument("config_hash", required=False)
@click.option("--stage", type=click.Choice([s.value for s in Stage]), default=None)
@click.option("--json", "as_json", is_flag=True, help="one JSON object per line")
def main(config_hash: str | None, stage: str | None, as_json: bool) -> None:
    try:
        entries = config_inventory(stage=stage, config_hash=config_hash)
    except ValueError as e:
        raise click.BadParameter(str(e), param_hint="CONFIG_HASH") from None

    if as_json:
        for e in entries:
            click.echo(_json(e))
        return
    if not entries:
        console.print("[dim]no matching config folders in data/research[/]")
        return
    if config_hash:
        for e in entries:
            _detail(e)
    else:
        _summary(entries)


if __name__ == "__main__":
    main()
