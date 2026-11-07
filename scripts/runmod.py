'''
This was written by claude to make it easier to run a module via a simple
shortcut.

It walks up while __init__.py exists, so 
    .../fxt/data/downloaders/dukascopy.py 
becomes 
    fxt.data.downloaders.dukascopy

    
Make sure to run this with the right interpreter (aka pixi)
'''

import runpy, sys
from pathlib import Path

path = Path(sys.argv[1]).resolve()
parts = [path.stem]
parent = path.parent
while (parent / "__init__.py").exists():
    parts.insert(0, parent.name)
    parent = parent.parent

sys.argv = [str(path), *sys.argv[2:]]
runpy.run_module(".".join(parts), run_name="__main__", alter_sys=True)