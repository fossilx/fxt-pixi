import os
from pathlib import Path
#import questionary

from fxt.descriptors import classproperty

#can access paths two ways:
from fxt import get_path #then: get_path('ROOT')
#or if you want code completion..
from fxt.settings import PATHS #-> PATHS.ROOT






class DIRS:
    @classproperty
    def ROOT(cls) -> Path|None:
        #return Path(os.getenv("PIXI_PROJECT_ROOT"))
        #return get_path('ROOT')
        return PATHS.ROOT
    #
    @classproperty
    def DOWNLOADS(cls):
        return cls.ROOT / "downloads"
    @classproperty
    def DATALAKE(cls):
        return cls.ROOT / "datalake"
    #
#-


if __name__ == "__main__":
    import sys
    from rich import print
    
    if(not DIRS.ROOT):
        print("[red]This must be executed within a pixi environment![/]")
        sys.exit()
    
    #else
    print("[bold green]ENV INFO[/]")
    print(f"  - [cyan]root:[/]      {DIRS.ROOT}")
    print(f"  - [cyan]downloads:[/] {DIRS.DOWNLOADS}")
    print(f"  - [cyan]datalake:[/]  {DIRS.DATALAKE}")
    
    

    