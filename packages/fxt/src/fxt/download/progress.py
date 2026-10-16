#=================================================================================(80)
#   fxt.download.progress ~ reporters (the engine only knows the Reporter protocol)
#=================================================================================(80)
from __future__ import annotations

from contextlib import ExitStack
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from fxt.download.engine import ChunkResult


class Reporter(Protocol):
    def start(self, total: int, skipped: int) -> None: ...
    def chunk_done(self, result: ChunkResult) -> None: ...
    def close(self) -> None: ...
#


class NullReporter:
    """ Does nothing. Handy for tests and scripted runs.
    """
    def start(self, total: int, skipped: int) -> None: ...
    def chunk_done(self, result: ChunkResult) -> None: ...
    def close(self) -> None: ...
#


class TqdmReporter:
    """ Progress bar via `tqdm.auto`: a widget bar in Jupyter (needs ipywidgets),
    a text bar in a terminal. One day = one tick of the bar.
    """
    def __init__(self, desc: str | None = None, redirect_logging: bool = True):
        self._desc = desc
        self._redirect = redirect_logging
        self._bar = None
        self._stack = ExitStack()
        self._rows = 0
        self._failed = 0
    #

    def start(self, total: int, skipped: int) -> None:
        from tqdm.auto import tqdm

        if self._redirect:
            #keeps stdlib log lines from tearing the bar in a terminal
            from tqdm.contrib.logging import logging_redirect_tqdm
            self._stack.enter_context(logging_redirect_tqdm(tqdm_class=tqdm))

        self._bar = tqdm(total=total, initial=skipped, desc=self._desc, unit="day")
    #

    def chunk_done(self, result: ChunkResult) -> None:
        if self._bar is None:
            return
        self._rows += result.rows
        if result.status == "failed":
            self._failed += 1

        postfix = {"day": result.chunk.day.isoformat(), "rows": f"{self._rows:,}"}
        if self._failed:
            postfix["failed"] = self._failed
        self._bar.update(1)
        self._bar.set_postfix(postfix)
    #

    def close(self) -> None:
        if self._bar is not None:
            self._bar.close()
            self._bar = None
        self._stack.close()
    #
#