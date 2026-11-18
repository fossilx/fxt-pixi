Checks you might want to do for data integrity in the future:
   
- make sure it has appropriate metadata
  - aka for the source time series, it needs:
      symbol
      interval
      start
      end
     
      not sure on rest.

- check for missing periods/days in the manifests!

- for downloaded tick data
  - check for missing days
    * aka each day of year needs to either have a file associated 
      with it, OR it needs to have an "empty" entry in the manifest
    


- when I had Claude look at the data, it did a few things:
  - checked for periods with missing data
    this seemed to always flag Dec 25th though
    