"""
`fxt.term.click`: utils for working with click CLIs
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

import click

#!================================================================================(80)
#! custom year range type
#!--------------------------------------------------------------------------------(80)
class _YearRangeType(click.ParamType):
    """ Represents a range of years as a click param. 
        Supports
        - single years:
            2024
        - range of years:
            2020-2024 
            2020..2024
        - list of years:
            2020,2021,2022,2023
        
    """
    name = "year_range"

    def convert(self, value, param, ctx):
        # If it's already a list (e.g., passed via python code directly)
        if isinstance(value, list):
            return value

        years = set()
        # Support splitting by comma to allow multiple ranges or single years (e.g., "2018,2020-2022")
        parts = [p.strip() for p in str(value).split(",") if p.strip()]

        for part in parts:
            # Handle range syntax (supports both '-' and '..')
            if "-" in part or ".." in part:
                sep = ".." if ".." in part else "-"
                try:
                    start_str, end_str = part.split(sep, 1)
                    start, end = int(start_str.strip()), int(end_str.strip())
                    if start > end:
                        self.fail(
                            f"Invalid range '{part}': start year ({start}) cannot be after end year ({end}).",
                            param,
                            ctx,
                        )
                    years.update(range(start, end + 1))
                except ValueError:
                    self.fail(
                        f"Invalid range format '{part}'. Expected format YYYY-YYYY or YYYY..YYYY.",
                        param,
                        ctx,
                    )
            else:
                # Handle single year
                try:
                    year = int(part)
                    years.add(year)
                except ValueError:
                    self.fail(
                        f"'{part}' is not a valid 4-digit year.", param, ctx
                    )

        if not years:
            self.fail("No valid years provided.", param, ctx)

        #return sorted(list(years))
        return sorted(years)
#-
YearRangeType = _YearRangeType()


#!================================================================================(80)
#! gogogogog
#!--------------------------------------------------------------------------------(80)
if __name__ == "__main__":
    from rich import print
    from rich.panel import Panel
    from rich.pretty import pprint, Pretty
    from rich.console import Group
    from fxt.term import hr

    defaults = {
        "single": "2024",
        "range1": "2000-2003",
        "range2": "2010..2023",
        "list": "2018,2022,2023,2026"
    }
    colors = [
        "green",
        "cyan",
        "blue",
        "yellow"
    ]


    #~ click handler
    @click.command()
    #help="Accepts a single year: 2024, a range: 2020-2024 or 2020..2024 (i think), or a list: 2020,2023,2024"
    @click.option("--years1", "-y1", default=defaults["single"], type=YearRangeType,
        prompt=click.style("\nExample of a single year", fg=colors[0], underline=True)
    )
    @click.option("--years2", "-y2", default=defaults["range1"], type=YearRangeType,
        prompt=click.style("\nExample of a range using a dash", fg=colors[1], underline=True)
    )
    @click.option("--years3", "-y3", default=defaults["range2"], type=YearRangeType,
        prompt=click.style("\nRange via the .. syntax", fg=colors[2], underline=True)
    )
    @click.option("--years4", "-y4", default=defaults["list"], type=YearRangeType,
        prompt=click.style("\nAnd a comma-delimited list...", fg=colors[3], underline=True)
    )
    @click.pass_context  
    def cli(ctx:click.Context, years1, years2, years3, years4):
        """
        """
        #print("[bold]Try entering a [green]single year[/], a [cyan]range[/], or a [yellow1]list[/]![/]")
        #print()
        #print(hr())
        print()
        
        print(Panel(
            Group(
                "The years you entered were converted parsed into the following lists:\n",
                Pretty(years1),
                Pretty(years2),
                Pretty(years3),
                Pretty(years4)
            ),
            title="Resulting lists..."
        ))

        # print(years1)
        # print(years2)
        # print(years3)
        # print(years4)
    #
        


    print(Panel(
        "[bold]Try entering[/]..."
        f"\n - a [{colors[0]} u]single year[/], ie: "
        f"\n   [{colors[0]}]{defaults["single"]}[/]"
        f"\n - a [{colors[1]} u]range[/], there are two ways! the following are equivalent:"
        f"\n   [{colors[1]}]{defaults["range1"]}[/]"
        f"\n   [{colors[2]}]{defaults["range2"]}[/]"
        f"\n - or a [{colors[3]} u]list[/], comma delimited, ie: "
        f"\n   [{colors[3]}]{defaults["list"]}[/]"
        "\n\n[bold] Use the defaults (just hit enter) below to see the above values tested[/]",
        title="[orchid2 bold]instructions[/]", title_align="left"
    ))

    cli()
