I was going to have it check the data as it was putting it into
the data lake, but decided against that. It woukd have required
a lot of extra work early on to verify the datasets were complete..
and that just isnt worth it at this stage.

Some verification csn be done once it is in the data lake:
- look for dead zones that shoukd hsve values
  - figure out how to address those periods



Step 1: download daily files
- creates a manifest that stores details about the process.


Step 2: consolidate to yearly files for datalake
- has to combine parquet files, and hopefully will resukt in
  updated parquet metadata as well as maybe an updated 
  manifest that acts like a combined log of all source 
  files used in its construction
- 


Step 3: derivatives/features (aka indicators)
- need to figure out how i will store this info in the datalake
- this inckudes basic representations like common bars
- it also includes indicators i think


After each stage, talk to claude to make sure you are planning 
your progress appropriately.




