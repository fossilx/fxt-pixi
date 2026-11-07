
# Configuration file for lab.
import os
from pathlib import Path

c = get_config()  # noqa

project_root = Path(os.environ["PIXI_PROJECT_ROOT"])
if(not project_root.exists()):
    raise RuntimeError(
        "This launcher must be run inside a pixi environment.\n"
        "PIXI_PROJECT_ROOT does not exist"
    )

#! set the root to /jupyter
c.ServerApp.root_dir = str(project_root / "jupyter")

#tonytony
c.PasswordIdentityProvider.hashed_password = "argon2:$argon2id$v=19$m=10240,t=10,p=8$CbP7qssosP2zgFZ1KngZPw$Xbv5/n8RxOEeriNJ+1WKK2JLoIKZ7Wwktt4qHcaKoXo"



