#=================================================================================(80)
#
#   fxt ;D
#
#=================================================================================(80)
#stop pylance from being annoying by adding this to end of line:  # type: ignore

#!================================================================================(80)
#! helpers
#!--------------------------------------------------------------------------------(80)
# def disable_dukascopy_python_logging():
#     """
#     """
#     import logging
#     logging.getLogger("DUKASCRIPT").disabled = True
# #


#!================================================================================(80)
#! gogogog
#!--------------------------------------------------------------------------------(80)
if(__name__ == "__main__"):    
    from datetime import datetime
    from rich import print
    from fxt.data.downloader import DukascopyDownloader
    from fxt.download import download_range

    DukascopyDownloader.disable_dukascopy_python_logging()

    #normal
    #start = datetime(2015, 1, 1)
    #end = datetime(2025, 12, 31)

    #short for testing
    start = datetime(2015, 1, 1)
    end = datetime(2021, 1, 1)

    
    summary = download_range("GBP/JPY", "tick", start=start, end=end)
    print(summary)