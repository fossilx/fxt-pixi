#=================================================================================(80)
#
#   fxt ;D
#
#=================================================================================(80)
#stop pylance from being annoying by adding this to end of line:  # type: ignore

#!================================================================================(80)
#! imports
#!--------------------------------------------------------------------------------(80)
#core
import logging
from pathlib import Path
from datetime import datetime
from calendar import monthrange
from dateutil.relativedelta import relativedelta

#date
import pyarrow.parquet as pq
import polars as pl

#local
from fxt import is_notebook
from fxt.data.dukascopy import DukascopyDownloader

#output
from rich import print
from rich.panel import Panel
if is_notebook():
    from tqdm.notebook import tqdm
else:
    from tqdm import tqdm


#!================================================================================(80)
#! setup
#!--------------------------------------------------------------------------------(80)
logger = logging.getLogger(__name__)


#!================================================================================(80)
#! downloader
#!--------------------------------------------------------------------------------(80)
class Downloader:
    """ Download and save historical data in Parquet format.

        A downloader is defined by the source, and destination.
    """
    NODATA_EXTENSION = "nodata"
    ROOT_DIR = Path("download/")

    def __init__(self, symbol:str, root_dir:str|Path = ROOT_DIR):
        """
        Initialize the Downloader.

        Args:
            symbol (str): The trading symbol.
            root_dir (str | Path): The root directory for downloads.
        """
        self.symbol = symbol
        self.root_dir = Path(root_dir)
        self.root_dir.mkdir(parents=True, exist_ok=True)
    #

    def downloader_wrapper(self, start: datetime, end: datetime, symbol: str | None = None) -> pl.DataFrame:
        """ Invokes the core downloader backend.
            Returns a polars.DataFrame containing the range's data.
        """
        if symbol is None:
            symbol = self.symbol
            
        downloader = DukascopyDownloader(symbol=symbol, start=start, end=end)
        df = downloader.download()
        return df
    #
    
    def download(self,
        symbol:str,
        start:datetime,
        end:datetime, 
        root_dir: str | None = None) -> dict:
        """ Loops through the specified date range month-by-month, downloads day-by-day
            for a highly responsive progress bar, and saves monthly aggregated Parquet files.
        """
        status = {
            "downloaded-files": [],
            "skipped-files": [],
            "intervals-nodata": [], 
            "errors": []
        }

        if root_dir is None:
            root_dir = self.root_dir
        if symbol is None:
            symbol = self.symbol     

        # 1. Sanitize symbol name
        safe_symbol = symbol.replace("/", "").replace("\\", "").strip()
        base_path = Path(root_dir) / safe_symbol
        
        # 2. Normalize tracking boundaries explicitly to days
        current_month_start = datetime(start.year, start.month, 1, 0, 0, 0)
        final_date = datetime(end.year, end.month, 1, 0, 0, 0) + relativedelta(months=1) - relativedelta(days=1)
        final_date = min(final_date, end)
        #if final_date > end:
        #    final_date = end

        total_days = (final_date.date() - current_month_start.date()).days + 1
        
        # =====================================================================
        # 🚀 FAST PRE-FLIGHT CHECK
        # =====================================================================
        check_cursor = current_month_start
        active_months = [] # List of (month_start, month_end, file_name, target_path)

        while check_cursor <= final_date:
            y, m = check_cursor.year, check_cursor.month
            last_day = monthrange(y, m)[1]
            c_end = datetime(y, m, last_day, 23, 59, 59, 999999)

            c_end = min(c_end, final_date)  # Ensure we don't go past the final date
            #if c_end > final_date:
            #    c_end = final_date

            f_name = f"{safe_symbol}-{y}-{m:02d}.parquet"
            t_parquet = base_path / f_name

            #no-data version
            nodata_path = t_parquet.with_name(t_parquet.name + f".{self.NODATA_EXTENSION}")
            #f"{safe_symbol}-{y}-{m:02d}.parquet"
            #nodata_path = base_path / nodata_fname

            if t_parquet.exists() or nodata_path.exists():
                # Instantly drop these days from our progress tracker total
                days_to_skip = (c_end.date() - check_cursor.date()).days + 1
                total_days -= days_to_skip
                status["skipped-files"].append(str(t_parquet))
            else:
                # Queue up only the months that actually need downloading
                active_months.append((check_cursor, c_end, f_name, t_parquet))

            check_cursor += relativedelta(months=1)

        # Early exit if everything is completely cached
        if not active_months:
            print(f"# All historical data for {symbol} is already cached locally.")
            return status
        
        #~======================================================================(70)
        #~ start the download process
        #~----------------------------------------------------------------------(70)
        print("#" + "-" * 78)
        # print(textwrap.dedent(
        #     """
        #     """
        # ))
        print(f"# Starting pipeline for {symbol} ({safe_symbol})")
        print(f"- Target Directory: {base_path.resolve()}")
        print(f"- Processing: {len(active_months)} months missing out of total range.")
        print("#" + "-" * 78 + "\n")

        #* wrapped in try block to handle keyboard interrupts nicely
        try:
            with tqdm(total=total_days, desc=f"Downloading {safe_symbol}") as pbar:
                for c_start, c_end, file_name, target_parquet in active_months:
                    year, month = c_start.year, c_start.month
                    
                    # Day-by-Day data fetch loops
                    month_dfs = []
                    day_cursor = datetime(c_start.year, c_start.month, c_start.day, 0, 0, 0)
                    
                    while day_cursor <= c_end:
                        day_start = datetime(day_cursor.year, day_cursor.month, day_cursor.day, 0, 0, 0)
                        day_end = datetime(day_cursor.year, day_cursor.month, day_cursor.day, 23, 59, 59, 999999)
                        day_end = min(day_end, c_end)

                        pbar.set_postfix_str(f"Fetching {day_start.strftime('%Y-%m-%d')}")
                        
                        try:
                            day_df = self.downloader_wrapper(symbol=symbol, start=day_start, end=day_end)
                            if(day_df is not None and not day_df.is_empty()):
                                month_dfs.append(day_df)

                        except Exception as e:
                            err_msg = f"Error downloading day {day_start.strftime('%Y-%m-%d')}: {str(e)}"
                            print("\n"+err_msg)
                            print("ending...")
                            import sys
                            sys.exit()

                            status["errors"].append(err_msg)
                            pbar.write(err_msg)

                        day_cursor += relativedelta(days=1)
                        pbar.update(1)

                    #----------------------------------------(40)

                    # Assemble chunks into single monthly file block
                    nodata = target_parquet.with_name(target_parquet.name + f".{self.NODATA_EXTENSION}")
                    
                    #! this list only has values if there was at least 1 df with data
                    if(month_dfs): 
                        try:
                            ##~ merge into one big df for the month
                            pbar.set_postfix_str(f"Merging {file_name}...")
                            final_month_df = pl.concat(month_dfs)
                            
                            #! if the resulting file has no values
                            # if(final_month_df.is_empty()):
                            #     #nodata = target_parquet.with_name(target_parquet.name + ".nodata")
                            #     nodata.touch()

                            # else:
                                
                            target_parquet.parent.mkdir(parents=True, exist_ok=True)
                            final_month_df.write_parquet(target_parquet, compression="zstd", compression_level=3)
                            
                            meta = {
                                "symbol": str(symbol),
                                "downloaded-date": datetime.now().isoformat()
                            }
                            ParquetMetadataUtils.add_metadata(str(target_parquet), meta, inplace=True)
                            
                            pbar.set_postfix_str(f"Saved {file_name}")
                            status["downloaded-files"].append(str(target_parquet.resolve()))
                        
                        except Exception as e:
                            err_msg = f"Failed to save assembled month {file_name}: {str(e)}"
                            status["errors"].append(err_msg)
                            pbar.write(err_msg)

                    else:
                        #write no-data flag file
                        nodata.parent.mkdir(parents=True, exist_ok=True)
                        nodata.touch()

                        status["intervals-nodata"].append(str(target_parquet.resolve()))
                        pbar.set_postfix_str(f"No data found for {year}-{month:02d}")

                        logger.debug(f"No data found for {year}-{month:02d}")
                #
            #
        except KeyboardInterrupt:
            # Clean up code goes here (e.g., closing files, releasing locks)
            import sys
            from pprint import pprint
            print("\nProcess interrupted by user. Exiting cleanly.")
            print("Final status:")
            pprint(status)
            sys.exit(0)
        #

        return status


#!================================================================================(80)
#! gogogogog
#!--------------------------------------------------------------------------------(80)
if(__name__ == "__main__"):
    from datetime import datetime
    from rich import print

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s"
    )


