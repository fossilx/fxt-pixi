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
from pathlib import Path
from pydantic import BaseModel, field_validator, Field


#!================================================================================(80)
#! setup
#!--------------------------------------------------------------------------------(80)
logger = logging.getLogger(__name__)


'''
THIS ISN'T DONE

I'm not sure how I want to handle this. I want to create a series of classes that
make the downloader app easier, but....i dont know if i care that much since the
ghetto version in place works for now.



'''



#!================================================================================(80)
#! main
#!--------------------------------------------------------------------------------(80)
class Manifest(BaseModel):
    """ This let's you specify a manifest path, and gives you an easy way 
        to update it. It is supposed to isolate the rest of the library from
        the storage details. It simply stores the record/dict you provide
        
        When you create this, it needs to do the following:
        - check if the path/file exists
          - if needed, create dirs
          - if needed, create file
        - needs to sync up the internal state of this class to the file, so
          adding a record to this updates state + writes it 
        
    """
    dir: Path
    filename: str

    state: dict[str,str] = {} 
    #make it validate defaults! that way you can get it to 
    #run a validation func when it is created (which should
    #run AFTER src is figured out....which means, if it gets 
    #to that point, the src file should be rdy to go
    
    
    # @field_validator("src", mode="before")
    # def validate_src(cls, value:Path|str) -> Path:
    #     """ 
    #     """
    #     value = Path(value)
        
    #     #make sure parent dir exists
    #     parent = value.parent
    #     parent.mkdir(parents=True, exist_ok=True)
        
    #     #see if the file exists - it must exist or die here
    #     #is there a touch method that only creates the file if it doesn't exist?
    #     value.touch(exist_ok=True)
        
    #     if(not value.exists()):
    #         raise RuntimeError(f"failed to create manifest at: {value}")
        
    #     return value
    # #
    
    def append(self, entry:dict):
        """
        """
        import json
        with self.src.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
    #
    
    def search(self, key, value):
        """ maybe a func to search the rows for a given key to match 
            a specified value
        """
        
#
    
#!================================================================================(80)
#! gogogog
#!--------------------------------------------------------------------------------(80)
if(__name__ == "__main__"):    
    from datetime import datetime
    from rich import print

    print("[red]NOT DONE --- not using at the moment[/]")