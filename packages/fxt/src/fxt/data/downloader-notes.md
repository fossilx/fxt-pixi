

# Basic progression

1. receive request to download:
    symbol:str
    interval:str (do I also want to support timedelta?)
         - maybe create a class that takes in either a timedelta or str
           and stores both
         - the string version will have to represent the values used by
           brokers 
         - i could create a base class with a default representation that
           does dukascopy....and then, if needed, add subclasses later
    start
    emd







