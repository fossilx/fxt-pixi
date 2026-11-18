#=================================================================================(80)
#
#   fxt ;D
#
#=================================================================================(80)
#stop pylance from being annoying by adding this to end of line:  # type: ignore

#!================================================================================(80)
#! imports/exports
#!--------------------------------------------------------------------------------(80)
import logging
import re
from io import StringIO

from rich.console import Console
from rich.text import Text
from rich.logging import RichHandler

from fxt import is_notebook


#!================================================================================(80)
#! jupyter formatter
#!--------------------------------------------------------------------------------(80)
class JupyterRichColorFormatter1(logging.Formatter):
    """ Converts Rich markup into ANSI escape sequences for compact Jupyter output.
    """
    def __init__(self, fmt=None, datefmt=None):
        super().__init__(fmt, datefmt)
        # Create a private buffer and console that forces ANSI code generation
        self.buffer = StringIO()
        self.console = Console(file=self.buffer, color_system="truecolor", force_terminal=True)

    def format(self, record):
        # Let Python logging build the base string (e.g., "INFO: Processing [green]done[/green]")
        formatted_msg = super().format(record)
        
        try:
            # Clear buffer, render Rich markup into ANSI-colored text, and grab it
            self.buffer.seek(0)
            self.buffer.truncate(0)
            
            text_obj = Text.from_markup(formatted_msg)
            self.console.print(text_obj, end="")
            
            return self.buffer.getvalue()
        except Exception:
            # Fallback if unclosed brackets or edge cases break markup parsing
            return formatted_msg
#

class JupyterRichColorFormatter(logging.Formatter):
    """Renders Rich markup in the message only, as ANSI; the rest of fmt stays literal."""
    _console = Console(
        file=StringIO(),
        force_terminal=True,
        color_system="truecolor",
        force_jupyter=False
    )

    def format(self, record):
        original_msg, original_args = record.msg, record.args
        try:
            msg = record.getMessage()
            try:
                with self._console.capture() as cap:
                    self._console.print(Text.from_markup(msg), end="", soft_wrap=True)
                msg = cap.get()
            except Exception:  # noqa: S110
                pass  # malformed markup: fall back to the raw message
            record.msg, record.args = msg, None
            return super().format(record)
        finally:
            record.msg, record.args = original_msg, original_args
#



#!================================================================================(80)
#! example of stripping all rich markup
#!--------------------------------------------------------------------------------(80)
RICH_TAG_PATTERN = re.compile(r"\[/?[a-zA-Z0-9_ -]+(?:=.*?)?\]")
def strip_rich_markup(text: str) -> str:
    """Removes Rich markup tags from a string for plain text handlers."""
    return RICH_TAG_PATTERN.sub("", text)

class StripMarkupFormatter(logging.Formatter):
    """Custom formatter that strips Rich markup for plain-text terminals/Jupyter."""
    def format(self, record):
        # Create a copy or modify the message string to avoid mutating it for other handlers
        record.msg = strip_rich_markup(str(record.msg))
        record.msg = record.msg.replace("[/]", "")
        return super().format(record)
#


#!================================================================================(80)
#! example of stripping all rich markup
#!--------------------------------------------------------------------------------(80)
def create_logger(
        id:str,
        level:int=logging.DEBUG,
        force_notebook=False
    ):
    """ For testing differnt loggers without using basicConfig
    """
    logger = logging.getLogger(id)
    logger.setLevel(level)
    logger.handlers.clear()
    logger.propagate = False

    in_nb = is_notebook() or force_notebook
    handler = RichHandler(
        console=Console(force_jupyter=False) if in_nb else None,
        show_path=not in_nb, #False if in_nb else True,
        show_time=True,
        rich_tracebacks=True, 
        markup=True
    )
    handler.setFormatter(logging.Formatter(
        fmt="[grey62][[/][underline][deep_sky_blue1]%(name)s[/][/][grey62]][/] | %(message)s",
        datefmt="[%X]"
    ))
    logger.addHandler(handler)
    return logger
#


    #! BASIC ONE FOR JUPYTER CUZ RICH OUTPUT THERE SUCKS
    if(is_notebook() or force_notebook):
        #handler = logging.StreamHandler()
        # formatter = JupyterRichColorFormatter(
        #     fmt="%(asctime)s %(levelname)-8s %(name)s | %(message)s",
        #     datefmt="[%X]"
        # )
        handler:RichHandler = RichHandler(
            console=Console(force_jupyter=False),
            show_time=True,
            show_path=False,
            rich_tracebacks=True, 
            markup=True
        )
        formatter = logging.Formatter(
            fmt="[grey62][[/][underline][deep_sky_blue1]%(name)s[/][/][grey62]][/] | %(message)s",
            datefmt="[%X]"
        )
        
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        logger.propagate = False


    #! RICH TERM FOR NORNAL TERMINAL
    else:
        handler:RichHandler = RichHandler(
            #console=console,
            rich_tracebacks=True, 
            markup=True
        )
        formatter = logging.Formatter(
            fmt="[grey62][[/][underline][deep_sky_blue1]%(name)s[/][/][grey62]][/] | %(message)s",
            datefmt="[%X]"
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        logger.propagate = False
    
    return logger
#




#LOGGER_ID="[green]derived-apps[/]"

# rh:RichHandler = RichHandler(rich_tracebacks=True, markup=True)
# # logging.basicConfig(
# #     level=logging.WARNING,
# #     handlers=[rh]
# # )
# prefix = ""
# logging.basicConfig(
#     level="WARNING",
#     format=(
#         "[grey62][[/]"
#         f"[underline]{prefix}[deep_sky_blue1]%(name)s[/][/]"
#         f"[grey62]][/] | %(message)s"
#     ),
#     #datefmt="[%X]",
#     handlers=[
#         RichHandler(rich_tracebacks=True, markup=True)
#     ]
# )

#https://www.toptal.com/designers/htmlarrows/arrows/
#  ↿ ↾⇉  ⇒
#  ⟶  ⟹  ⤇   ⤑ 
# ➝  ➤ 



__all__ = [
    'create_logger'
]


#!================================================================================(80)
#! gogogogog
#!--------------------------------------------------------------------------------(80)
if(__name__ == "__main__"):
    from rich import print
    #from rich.logging import RichHandler

    # handler = RichHandler(rich_tracebacks=True, markup=True)
    # formatter = handler.formatter
    # format_str = formatter._fmt if(formatter) else "<empty>"
    
    # print(f"Current log handler:    {handler}")
    # print(f"Current log formatter:  {formatter}")
    # print(f"Current log format str: {format_str}")
    
    print("TESET #1")
    logger = create_logger(id="normal")
    logger.debug("Debugging [bold cyan]variable[/bold cyan] values...")
    logger.info("Processing complete! Everything looks [bold green]good[/bold green].")
    logger.warning("High memory usage: [yellow]85%[/yellow]")
    logger.error("Failed to connect to [red underline]database[/red underline].")
    logger.critical("System crash imminent!")

    print()
    print()
    print("TESET JUPYTER")
    logger = create_logger(id="jupyter", force_notebook=True)
    #logger.setLevel(logging.DEBUG)
    logger.debug("Debugging [bold cyan]variable[/bold cyan] values...")
    logger.info("Processing complete! Everything looks [bold green]good[/bold green].")
    logger.warning("High memory usage: [yellow]85%[/yellow]")
    logger.error("Failed to connect to [red underline]database[/red underline].")
    logger.critical("System crash imminent!")

    #logger.warning("Example use of [bold]app logger.[/]")
    #logger.error("Example [pink1]error message.[/]")
    

    # def test_local():
    #     from rich.console import Console
    #     import time

    #     console = Console()

    #     # Log text with style markup
    #     console.log("Starting script...", style="bold magenta")

    #     # Log complex data structures directly (they render with syntax highlighting)
    #     sample_data = {
    #         "user_id": 42,
    #         "active": True,
    #         "roles": ["admin", "developer"],
    #         "meta": {"ip": "127.0.0.1", "attempts": 3}
    #     }
    #     console.log("Current state:", sample_data)

    #     # Log with custom time formats or log local scope
    #     console.log("[bold yellow]Warning:[/bold yellow] Low disk space", log_locals=True)
    # #
    # #test_local()
    