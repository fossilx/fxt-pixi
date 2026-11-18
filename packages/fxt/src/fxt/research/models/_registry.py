'''
The registry for research metadata models AND stage config models.

Configs live here too: a config's hash includes its type id, so every config
class must be registered (and a file's stored config can be traced back to
its class by that id).

This module must not import any model modules (avoids circular imports).
Models import `registry` from here; the package __init__ imports the models.
'''
#=================================================================================(80)
#
#   fxt ;D
#
#=================================================================================(80)
from fxt.core.versioned import VersionedModelRegistry

registry: VersionedModelRegistry[int] = VersionedModelRegistry(default_version=1)
