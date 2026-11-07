import os
import subprocess
import sys
from pathlib import Path

from fxt.term import pause
from rich import print


def get_project_root() -> Path:
    root = os.environ.get("PIXI_PROJECT_ROOT")
    if not root:
        sys.exit(
            "This launcher must be run inside a pixi environment.\n"
            "Try: pixi run python <this_script>.py  (or run it from `pixi shell`)"
        )
    return Path(root)


if __name__ == "__main__":
    project_root: Path = get_project_root()
    #jupyter_root: Path = project_root / "jupyter"

    #config = jupyter_root / ".jupyter/.jupyter-conf.py"

    cmd: list[str] = [
        "jupyter", "lab",
        "--no-browser",
        "--custom-css",
        #f"--notebook-dir={jupyter_root}",
        #f"--config={config}",
    ]

    print("Jupyter command:", " ".join(cmd))

    #! send a modified env
    env:dict[str,str] = os.environ.copy()
    #this forces it to only usd the config file we specify, and not any other config files that may exist in the environment
    #env["JUPYTER_NO_CONFIG"] = "1"

    #pass a str
    env["JUPYTER_CONFIG_DIR"] = str(project_root / "jupyter" / ".jupyter")

    try:
        sys.exit(subprocess.run(
            cmd, 
            cwd=project_root,
            env=env
        ).returncode)
    except KeyboardInterrupt:
        sys.exit(0)