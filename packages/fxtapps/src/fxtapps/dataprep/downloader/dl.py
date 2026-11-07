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
import sys
import datetime as dtime
from datetime import date, datetime, timedelta, timezone
from typing import TYPE_CHECKING, Literal, Annotated
from pathlib import Path

from pydantic import BaseModel, Field, ConfigDict, field_validator, BeforeValidator, field_serializer, computed_field
import polars as pl
from rich import print
from rich.panel import Panel
from alive_progress import alive_bar

#fxt
from fxt.data.sources import BaseSource
from fxt.data.markets import BaseMarket
from fxt.data.models import DownloadedDataMeta
from fxt.data.downloaders import BaseDownloader, DownloaderRegistry


#apps->shared
from fxtapps.dataprep.storage import StorageManager
from fxtapps.settings import get_settings
#from fxtapps.dataprep.logger import logger
#apps->local


#!================================================================================(80)
#! setup (logging, exceptions, types)
#!--------------------------------------------------------------------------------(80)
from . import logger
#import logging
#logger.setLevel(logging.WARNING)




#!================================================================================(80)
#! helpers
#!--------------------------------------------------------------------------------(80)
def _to_utc(value: datetime) -> datetime:
    """ Naive datetimes are assumed to be UTC; aware ones are converted to UTC.
    """
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
#

def _floor_day(value: datetime) -> datetime:
    return value.replace(hour=0, minute=0, second=0, microsecond=0)
#

#!================================================================================(80)
#! utility constants/classes
#!--------------------------------------------------------------------------------(80)
DAY = timedelta(days=1)
UTC = dtime.UTC #not realllly needed, but so I remember where it is defined

class Chunk(BaseModel):
    """ One whole UTC day: [start, end).
    """
    #! pydantic config
    model_config = ConfigDict(frozen=True)

    #! fields
    start: datetime = Field()
    end: datetime = Field()

    @property
    def day(self) -> date:
        return self.start.date()
#
# class ChunkResult(BaseModel):
#     """
#     """
#     #! pydantic config
#     model_config = ConfigDict(frozen=True)

#     #! fields
#     chunk: Chunk
#     status: Literal["success", "empty", "failed"]
#     rows: int = 0
#     error: str | None = None
# #
# class Summary(BaseModel):
#     """
#     """
#     #! pydantic config
#     #model_config = ConfigDict(frozen=True)

#     #! fields
#     total: int = 0          #days in the requested range
#     skipped: int = 0        #already on disk before this run
#     downloaded: int = 0     #days with data written this run
#     empty: int = 0          #days with no data (weekends/holidays)
#     rows: int = 0
#     failed: list[ChunkResult] = Field(default_factory=list)
#     interrupted: bool = False

#     def add(self, r: ChunkResult) -> None:
#         if r.status == "success":
#             self.downloaded += 1
#             self.rows += r.rows
#         elif r.status == "empty":
#             self.empty += 1
#         else:
#             self.failed.append(r)
#     #

#     def __str__(self) -> str:
#         s = (
#             f"{self.downloaded} downloaded ({self.rows:,} rows), {self.empty} empty, "
#             f"{self.skipped} skipped, {len(self.failed)} failed, of {self.total} days"
#         )
#         return s + (" [interrupted]" if self.interrupted else "")
#     #
# #


def _resolve_downloader(v):
    """ So you can specify a string (id) when creating the app instance 
    """
    if isinstance(v, str):
        #logger.debug(f"Looking for downloader in registry: {v}")
        return DownloaderRegistry[v]
    return v
#

#!================================================================================(80)
#! main downloader class
#!--------------------------------------------------------------------------------(80)
class DailyDownloaderApp(BaseModel):
    """ 
    """
    #! FIELDS
    #downloader:str = Field()
    downloader:Annotated[BaseDownloader, BeforeValidator(_resolve_downloader)]
    symbol:str = Field()
    interval:str = Field()
    start:datetime = Field(description="start of the entire period")
    end:datetime = Field(description="end of the entire period")
    root:Path = Field(default=get_settings("DOWNLOADS_DIR"))

    @field_serializer("downloader")
    def _ser_downloader(self, d: BaseDownloader) -> str:
        return d.id


    #! PROPERTIES
    @property #use @cached_property if creating this gets expensive
    def Storage(self) -> StorageManager:
        """ Creates a storage manager instance.
        """
        return StorageManager(
            root=self.root,
            symbol=self.symbol,
            interval=self.interval
        )
    #
    


    #~======================================================================(70)
    #~ main api
    #~----------------------------------------------------------------------(70)
    def run(self, *, auto=False, dry=True, echo=False):
        """ Main run method. Assume all values are valid

            if `auto` is true, it will automatically start (aka it won't pause)
            if `echo` is true, certain pretty debug msgs will be displayed
        """
        #! plan the chunks
        chunks = self.plan()
        #print(Panel(f"# chunks: {len(chunks)}"))

        #! determine which chunks need done
        pending = [
            c for c in chunks
            if not self.Storage.is_done(c.day)
        ]

        #print(chunks)
        #print(pending)
        print(
            Panel(
                (
                    f" - [cyan]downloader (id)[/]:    {self.downloader.id}"
                    f"\n - [cyan]symbol[/]:             {self.symbol}"
                    f"\n - [cyan]interval[/]:           {self.interval}"
                    f"\n - [cyan]start[/]:              {self.start}"
                    f"\n - [cyan]end[/]:                {self.end}"
                    "\n ------------------------------------------------"
                    f"\n - [cyan]# chunks (total)[/]:   {len(chunks)}"
                    f"\n - [cyan]# chunks (pending)[/]: {len(pending)}"
                ),
                title=f"[bold]{self.__class__.__name__}[/]::run(dry={dry}, auto={auto}, echo={echo})",
                title_align="left"
            )
        )

        if(not auto):
            from fxt import term
            term.pause()
            
        #~----------------------------------------(40)
        
        #! setup progress bar
        ntotal:int = len(chunks)
        nfinished:int = ntotal - len(pending)
        completed:list[Path] = []

        with alive_bar(total=ntotal) as bar:
            if(nfinished):
                bar(nfinished)

            #~ loop through each chunk
            for chk in pending:
                #* downloader params
                df: pl.DataFrame
                meta: DownloadedDataMeta

                #! send to downloader
                df, meta = self.downloader.download(
                    symbol=self.symbol,
                    interval=self.interval,
                    start=chk.start,
                    end=chk.end
                )

                if(df.is_empty()):
                    #! no rows, add to manifest as empty
                    #self.Storage.record_to_manifest(chk.start, status="empty")
                    manifest, record = self.Storage.record(
                        dataset=self.symbol,
                        id=chk.day,
                        status="empty",
                        echo=echo
                    )
                    

                else:
                    #! send to storage writer
                    fpath:Path = self.Storage.write_day(
                        day=chk.day, 
                        df=df,
                        dfmeta=meta,
                        dry=dry
                    )

                    #this is best for a lazy frame
                    first, last = df.select(
                        pl.col("dtime").min().alias("first"),
                        pl.col("dtime").max().alias("last")
                    ).row(0)

                    #and for some reason it says status is being sent twice?

                    #! write to manifest
                    manifest, record = self.Storage.record(
                        id=chk.day,
                        fpath=fpath,
                        status="success",
                        rows=len(df),
                        
                        #specific to finance
                        first_ts=first,
                        last_ts=last,

                        echo=echo
                    )
                    # #self.Storage.record_to_manifest(
                    #     chk.start,
                    #     status="success",
                    #     file=str(fpath),
                    #     rows=len(df),
                    #     overwrite=True
                    # )

                    #fname.name

                    logger.debug(
                        f"{self.__class__.__name__}->run(dry={dry}): created file: `{fpath}` (#rows: {len(df)})"
                    )

                    completed.append(fpath)

                #status report
                logger.debug(f"{self.__class__.__name__}->run(dry={dry}): added record:\n{record}")
                
                #* advance bar
                bar()

        #!
        print(f"Successfully downloaded/saved: {len(completed)} files")
        return completed
    #
    
    
    #~======================================================================(70)
    #~ planning
    #~----------------------------------------------------------------------(70)
    def plan(
            self, 
            start: datetime|None = None,
            end:   datetime|None = None, 
            now:   datetime|None = None #if you want to tell it to act like today is a specific day
        ) -> list[Chunk]:
        """ Expand [start, end) to whole UTC days, oldest first.

            The current (still-incomplete) UTC day is never planned, so a day on disk
            is always a finished day.
        """
        #! prepare start/end
        #use instance vars if any are missing
        if(start is None):
            start = self.start
        if(end is None):
            end = self.end
        
        #make sure they are UTC        
        start, end = _to_utc(start), _to_utc(end)
        if start >= end:
            raise ValueError(f"start ({start}) must be before end ({end})")
        
        #! get the bounds using start/end
        #determine the value of "today" to use
        today = _floor_day(_to_utc(now) if now else datetime.now(UTC))
        #get first day
        first = _floor_day(start)
        #determine last day (make sure it's not in the future!)
        last = _floor_day(end)
        if last < end:
            #end falls mid-day -> include the rest of that last day
            last += DAY
        #restrict the end time to the start of today
        last = min(last, today)

        #! create chunks, one day at a time
        chunks: list[Chunk] = []
        d = first
        while d < last:
            chunks.append(Chunk(
                start=d,
                end=d+DAY
            ))
            d += DAY
        return chunks
    #
#-



#!================================================================================(80)
#! gogogogog
#!--------------------------------------------------------------------------------(80)
if(__name__ == "__main__"):
    import sys
    from fxt.term import hr, clear, pause
    from rich import print
    from rich.panel import Panel
    from collections.abc import Iterable
    from InquirerPy import inquirer
    from fxt.data.downloaders import FakeDownloader

    #! helpers
    def _scan_dir(
        directory: Path | str,
        patterns: str | Iterable[str] = "*",
        *,
        recursive: bool = False
    ) -> list[str]:
        """ List the files in a directory, optionally printing a short preview.

            Returns the full list of names (relative to `directory`, sorted).
        """
        directory = Path(directory)

        if(not directory.exists()):
            return {}, []

        if(directory.exists() and not directory.is_dir()):
            raise NotADirectoryError(directory)
        

        if isinstance(patterns, str):
            patterns = [patterns]

        walk = directory.rglob if recursive else directory.glob
        paths = {p for pat in patterns for p in walk(pat)}
        names = sorted(p.relative_to(directory).as_posix() for p in paths if p.is_file())

        return paths, names
    #
    def _reset(root:Path):
        #root = Path("downloads/EURJPY/TICK/2023/01/")
        patterns = ["*.parquet", "*.db"]
        preview = 5

        paths, fnames = _scan_dir(root, patterns)        

        s = f"{len(fnames)} file(s) matching [cyan]{patterns!r}[/]"

        if(not len(fnames)):
            print()
            print(
                Panel(
                    s,
                    title=f"[bold]Target environment[/] is already reset~! : [green]{root}[/]",
                    title_align="left"
                )
            )
        else:
            for name in fnames[:preview]:
                s += f"\n - {name}"
            if len(fnames) > preview:
                s += f"  ... and {len(fnames) - preview} more"

            print()
            print(
                Panel(
                    s,
                    title=f"Resetting [bold]target environment[/] in: [green]{root}[/]",
                    title_align="left"
                )
            )

            proceed:bool = inquirer.confirm("Delete these files?", default=True).execute()
            if(proceed):
                print("[red bold]Deleting them now...[/]")
                for p in paths:
                    print(f"Deleting: [orchid2]{p}[/]")
                    Path(p).unlink()
    #
    
    def run_downloader_test(source:str, symbol:str, start:datetime, end:datetime, interval:str="TICK"):
        """ Meant to allow running within the same month, so start/end need to
            be in same month.

            I could make it smarter..so that it clears all dirs related to a given 
            test range, but I'm not sure I care enough
        """
        if(start.month != end.month):
            raise ValueError(f"start and end need to be in same month! start={start.month}, end={end.month}")


        try:
            #create downloader
            dl = DailyDownloaderApp(
                downloader=source,
                symbol=symbol,
                interval=interval,
                start=start,
                end=end
            )
            #determine output dir
            year = start.year
            month = start.month
            market = dl.downloader.which_market(symbol=symbol)
            safe_sym = market.sanitize(symbol=symbol)
            output = Path(f"downloads/{safe_sym}/{interval}/{year}/{month:02d}/")
            #print(f"output dir: {output}")
            #sys.exit()

            #reset test env if needed
            _reset(output)
            pause("Press any key to continue with the downloader..")

            #run downloader
            dl.run(dry=False)

        except KeyboardInterrupt:
            print("APP::[bold orchid2]KeyboardInterrupt[/]: Operation canceled.")
    #

    #! tests
    def test_fake():
        """ Uses the fake downloader/source.
        """
        #january 1 = sunday, jan 7 = saturday
        year = 2023
        month = 1

        run_downloader_test(
            source="fake",
            symbol = "FAK/USD",
            start=datetime(year, month, 6),
            end=datetime(year, month, 9)
        )
    #
    #test_fake()

    def test_LIVE():
        dl = DailyDownloaderApp(
            downloader="dukascopy", #DukascopyDownloader(),
            symbol="EUR/JPY",
            interval="TICK",
            start=datetime(2023,1,1),
            end=datetime(2023,1,2)
        )
        
        try:
            #print(hr(title="# [bold][orchid2]starting up...[/][/]"))
            _reset(root=Path("downloads/EURJPY/TICK/2023/01/"))
            #sys.exit()
            #pause()

            clear()
            dl.run(dry=False)

        except KeyboardInterrupt:
            print("APP::[bold orchid2]KeyboardInterrupt[/]: Operation canceled.")
    #

    def download():
        """
        """
        dl = DailyDownloaderApp(
            downloader="dukascopy", #DukascopyDownloader(),
            symbol="GBP/JPY",
            interval="TICK",
            start=datetime(2020,1,1),
            end=datetime(2024,1,1)
        )

        try:
            dl.run(dry=False)
        except KeyboardInterrupt:
            print("APP::[bold orchid2]KeyboardInterrupt[/]: Operation canceled.")
    #
    download()
    

