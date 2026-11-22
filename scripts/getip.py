
import requests
from requests.utils import get_environ_proxies

#import os
#os.environ["HTTPS_PROXY"] = "http://127.0.0.1:8001"
#os.environ["HTTP_PROXY"] = "http://127.0.0.1:8001"


GEO_URL = "https://geo.fxt.dev/api/geo"
#HOST    = "127.0.0.1"
#PORTS   = [8001, 8002, 8003]
#TIMEOUT = 15


def where_am_i(timeout: float = 10) -> dict:
    """ Geo info for the IP this process exits through (respects HTTP(S)_PROXY). """
    r = requests.get(GEO_URL, timeout=timeout)
    r.raise_for_status()
    return r.json()

def where_am_i_verbose() -> dict:
    proxy = get_environ_proxies(GEO_URL).get("https", "direct")
    geo = where_am_i()
    print(f"{proxy}  ->  {geo['ip']}  {geo['city']}, {geo['countryRegion']}")
    return geo
#


if __name__ == "__main__":
    from rich import print
    from rich.pretty import pprint
    
    #print(f"Fetching: {GEO_URL}")
    pprint(where_am_i_verbose())
