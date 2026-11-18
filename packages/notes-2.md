

Module setup:

/fxt
    /data
        #files
        /__init__.py
            exports DataRegistry
        /registry.py  #creates instance of the registry
            depends: fxt.registry.Registry
            exports: DataRegistry
            
        #dirs
        /downloaders
            /__init__.py
                export BaseDownloader (from base.py)
                export DukascopyDownloader (from dukascopy.py)
            /base.py       #contains BaseDownloader
                depends on: BaseSource
            /dukascopy.py  #contains DukascopyDownloader
                depends on: BaseDownloader
                depends on: DukascopySource
        /sources
            /__init__.py
                export BaseSource (from base.py)
                export DukascopySource (from dukascopy.py)
            /base.py       #contains BaseSource
            /dukascopy.Py  #contains DukascopySource
        /models
            __init__.py
                exports DownloadedMeta
            DownloadedMeta.Py  #contains DownloadedMeta
                depends on: fxt.registry.RegisteredModel

    /schema.py
        contains: BaseSchema
            depends on: DownloadedMeta
        contains: Tick (subclass of BaseSchema)
        contains: Bar (subclass of BaseSchema)
        
    /registry.py
        contains: Registry
        contains: RegisteredModel
        




