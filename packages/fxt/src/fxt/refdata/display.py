"""
Human-readable summary of the meta data, built from the registries.
"""
#=================================================================================(80)
#
#   fxt ;D
#
#=================================================================================(80)
#stop pylance from being annoying by adding this to end of line:  # type: ignore

#!================================================================================(80)
#! imports/exports
#!--------------------------------------------------------------------------------(80)
from __future__ import annotations
from collections.abc import Sequence

#from rich.table import Table

#local
from .loader import intervals, markets, sources, symbols


#!================================================================================(80)
#! private
#!--------------------------------------------------------------------------------(80)
def _table(rows: Sequence[Sequence[str]], indent: int = 4) -> list[str]:
    """Left-aligned columns, widths fitted to the content."""
    if not rows:
        return [" " * indent + "(none)"]
    widths = [max(len(row[i]) for row in rows) for i in range(len(rows[0]))]
    pad = " " * indent
    return [
        pad + "  ".join(cell.ljust(w) for cell, w in zip(row, widths)).rstrip()
        for row in rows
    ]
#

def _heading(title: str) -> list[str]:
    return ["", title, "=" * len(title)]



#!================================================================================(80)
#! main
#!--------------------------------------------------------------------------------(80)
def format_meta() -> str:
    """Return the meta data as a readable multi-line string."""
    lines: list[str] = []
    #tables: dict[str,Table] = {}

    # Markets and their symbols
    #tables["markets"] = Table(title="Markets")
    lines += _heading("Markets")
    for market in markets():
        syms = sorted(symbols().in_market(market.name), key=lambda s: s.name)
        lines.append(f"  {market.name} ({len(syms)} symbols)")
        lines += _table(
            [(s.name, f"aka {', '.join(s.aliases)}" if s.aliases else "") for s in syms]
        )

    # Intervals
    lines += _heading("Intervals")
    lines += _table(
        [
            (i.name, "tick" if i.is_tick else f"{i.seconds:,} s")
            for i in intervals()
        ],
        indent=2,
    )

    # Sources and their mappings
    lines += _heading("Sources")
    for source in sources():
        lines.append(f"  {source.name}  {source.website or ''}".rstrip())

        lines.append(f"   intervals ({len(source.intervals)}):  ours -> theirs")
        lines += _table(
            [(i.interval_name, "->", i.source_interval) for i in source.intervals]
        )

        lines.append(f"   symbols ({len(source.symbols)}):  market  ours -> theirs")
        lines += _table(
            [(s.market, s.name, "->", s.source_symbol) for s in source.symbols]
        )

    return "\n".join(lines).lstrip("\n")


def print_meta() -> None:
    """Print the meta data in a readable layout."""
    print(format_meta())
#


#!================================================================================(80)
#! gogogogog
#!--------------------------------------------------------------------------------(80)
if(__name__ == "__main__"):
    from rich import print

    print()
    print("# [bold green]gogogogogo[/]")

    print_meta()
