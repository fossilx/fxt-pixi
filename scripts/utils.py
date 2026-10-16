from pathlib import Path

def get_pixi_root(start_path: Path = Path(__file__)) -> Path | None:
    # Check PIXI_PROJECT_ROOT environment variable first
    import os
    if "PIXI_PROJECT_ROOT" in os.environ:
        return Path(os.environ["PIXI_PROJECT_ROOT"])
    
    # Search parent directories for pixi.toml
    for parent in start_path.resolve().parents:
        if (parent / "pixi.toml").exists():
            return parent
            
    return None
#


