#=================================================================================(80)
#
#   fxt ;D
#
#=================================================================================(80)
"""
Where does this process exit to the internet? Asks the geo JSON API
(https://geo.fxt.dev/api/geo by default, override with FXT_GEO_URL).

    from fxt.core.geo import get_geo, require_proxied

    geo = get_geo()                       # respects HTTP(S)_PROXY, like requests does
    geo.ip, geo.city, geo.place           # '149.40.50.197', 'Boston', 'Boston, MA, US'

    get_geo(proxy="http://127.0.0.1:8002")    # through one proxy, ignoring the env
    get_geo(direct=True)                      # bypass every proxy: your home IP

    geo = require_proxied()               # raise GeoError unless a proxy is set AND
                                          # the exit IP differs from the direct one

Nothing here prints; everything returns a GeoInfo or raises GeoError.
"""

#!================================================================================(80)
#! imports/exports
#!--------------------------------------------------------------------------------(80)
from __future__ import annotations

import os
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import requests
from requests.utils import get_environ_proxies

if TYPE_CHECKING:                             # rich is only imported when rendering
    from rich.table import Table

__all__ = [
    "GEO_URL", "GeoError", "GeoInfo",
    "env_proxy", "geo_table", "get_geo", "home_geo", "require_proxied",
]

GEO_URL = os.environ.get("FXT_GEO_URL", "https://geo.fxt.dev/api/geo")
TIMEOUT = 10.0


#!================================================================================(80)
#! types
#!--------------------------------------------------------------------------------(80)
class GeoError(RuntimeError):
    """ The geo lookup failed, or the exit IP isn't what was required. """
#

def _float(v: Any) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None

@dataclass(frozen=True)
class GeoInfo:
    ip:          str
    city:        str | None = None
    region:      str | None = None    # state / province ("MA"); the API's countryRegion
    country:     str | None = None    # ISO code ("US")
    continent:   str | None = None
    latitude:    float | None = None
    longitude:   float | None = None
    timezone:    str | None = None
    postal_code: str | None = None
    edge:        str | None = None    # server edge that answered ("iad1"); the API's region
    proxy:       str | None = None    # proxy the request went through, None if direct
    raw:         dict[str, Any] = field(default_factory=dict, repr=False, compare=False)

    @classmethod
    def from_json(cls, d: dict[str, Any], proxy: str | None = None) -> GeoInfo:
        if not d.get("ip"):
            raise GeoError(f"geo response has no ip: {d!r}")
        return cls(
            ip=d["ip"],
            city=d.get("city"),
            region=d.get("countryRegion"),
            country=d.get("country"),
            continent=d.get("continent"),
            latitude=_float(d.get("latitude")),
            longitude=_float(d.get("longitude")),
            timezone=d.get("timezone"),
            postal_code=d.get("postalCode"),
            edge=d.get("region"),
            proxy=proxy,
            raw=dict(d),
        )

    @property
    def place(self) -> str:
        """ 'Boston, MA, US' (skips missing parts). """
        return ", ".join(p for p in (self.city, self.region, self.country) if p)

    @property
    def via(self) -> str:
        return self.proxy or "direct"

    def __str__(self) -> str:
        return f"{self.ip} ({self.place}) via {self.via}"

    def __rich__(self) -> Table:
        """ rich.print(geo) / console.print(geo): a key/value table. """
        from rich.table import Table
        t = Table(show_header=False, box=None, padding=(0, 1))
        t.add_column(style="dim", justify="right")
        t.add_column()
        rows = [("ip", self.ip), ("place", self.place), ("via", self.via),
                ("timezone", self.timezone), ("postal", self.postal_code),
                ("lat/lon", f"{self.latitude}, {self.longitude}"
                            if self.latitude is not None else None),
                ("edge", self.edge)]
        for k, v in rows:
            if v:
                t.add_row(k, str(v))
        return t
#

COLUMNS = ("ip", "place", "via", "timezone", "edge")

def geo_table(rows: Mapping[str, GeoInfo | Exception] | Iterable[GeoInfo], *,
              title: str | None = "exit IPs",
              columns: Iterable[str] = COLUMNS) -> Table:
    """ One row per lookup. Pass a {label: GeoInfo | GeoError} mapping to get a
        label column and show failures inline, or just an iterable of GeoInfo.
    """
    from rich.table import Table
    from rich.text import Text
    labelled = isinstance(rows, Mapping)
    items = list(rows.items()) if labelled else [(None, g) for g in rows]
    cols = list(columns)
    t = Table(title=title, title_justify="left")
    if labelled:
        t.add_column("", style="bold")
    for c in cols:
        t.add_column(c, style="dim" if c in ("via", "edge") else None,
                     no_wrap=c in ("ip", "via"), ratio=2 if c == "place" else None)
    for label, g in items:
        lead = [label] if labelled else []
        if isinstance(g, Exception):          # short mark in the first column, message in the next
            cells = [Text("✗ failed", style="red"), Text(str(g), style="red")]
            t.add_row(*lead, *(cells + [""] * len(cols))[:len(cols)])
        else:
            t.add_row(*lead, *(str(getattr(g, c) or "") for c in cols))
    return t
#


#!================================================================================(80)
#! lookups
#!--------------------------------------------------------------------------------(80)
def env_proxy(url: str = GEO_URL) -> str | None:
    """ The proxy requests would use for `url` from HTTP(S)_PROXY / NO_PROXY, or None. """
    scheme = url.split("://", 1)[0]
    return get_environ_proxies(url).get(scheme)

def get_geo(url: str = GEO_URL, *,
            proxy: str | None = None,
            direct: bool = False,
            timeout: float = TIMEOUT,
            session: requests.Session | None = None) -> GeoInfo:
    """ Geo info for this process's exit IP.

        proxy=None, direct=False  ->  whatever HTTP(S)_PROXY says (requests' default)
        proxy="http://host:port"  ->  that proxy, ignoring the env
        direct=True               ->  no proxy at all
    """
    if proxy and direct:
        raise ValueError("pass proxy or direct, not both")
    s = session or requests.Session()
    try:
        if direct or proxy:
            s.trust_env = False               # don't let the env override the choice
            used = proxy
            proxies = {"http": proxy, "https": proxy} if proxy else None
        else:
            used = env_proxy(url)
            proxies = None
        try:
            r = s.get(url, proxies=proxies, timeout=timeout)
            r.raise_for_status()
            data = r.json()
        except requests.RequestException as exc:
            raise GeoError(f"geo lookup via {used or 'direct'} failed: {exc}") from exc
        except ValueError as exc:             # body isn't JSON
            raise GeoError(f"geo lookup via {used or 'direct'}: bad JSON") from exc
        return GeoInfo.from_json(data, proxy=used)
    finally:
        if session is None:
            s.close()

def home_geo(url: str = GEO_URL, *, timeout: float = TIMEOUT) -> GeoInfo:
    """ Your real exit IP, bypassing every proxy. """
    return get_geo(url, direct=True, timeout=timeout)

def require_proxied(url: str = GEO_URL, *,
                    city: str | None = None,
                    timeout: float = TIMEOUT) -> GeoInfo:
    """ Guard for jobs that must not run on the home connection. Returns the
        proxied GeoInfo, or raises GeoError if no proxy is configured, the
        exit IP equals the direct one, or (if given) the city doesn't match.
    """
    proxied = get_geo(url, timeout=timeout)
    if proxied.proxy is None:
        raise GeoError("no proxy configured (set HTTPS_PROXY)")
    home = home_geo(url, timeout=timeout)
    if proxied.ip == home.ip:
        raise GeoError(f"proxy {proxied.proxy} exits on the home IP {home.ip}")
    if city is not None and (proxied.city or "").casefold() != city.casefold():
        raise GeoError(f"expected exit in {city}, got {proxied.place}")
    return proxied
#


#!================================================================================(80)
#! demo:  python -m fxt.core.geo [port ...]
#!--------------------------------------------------------------------------------(80)
if __name__ == "__main__":
    import sys
    from rich import print as rprint

    def attempt(fn, *args, **kwargs) -> GeoInfo | GeoError:
        try:
            return fn(*args, **kwargs)
        except GeoError as exc:
            return exc

    ports = [int(p) for p in sys.argv[1:]] or [8001, 8002, 8003]

    rows: dict[str, GeoInfo | GeoError] = {
        "home":      attempt(home_geo),
        "env proxy": attempt(get_geo),         # direct unless HTTPS_PROXY is set
        **{f"port {p}": attempt(get_geo, proxy=f"http://127.0.0.1:{p}") for p in ports},
        "guard":     attempt(require_proxied), # passes only with HTTPS_PROXY set
    }
    rprint(geo_table(rows))

    if isinstance(home := rows["home"], GeoInfo):
        rprint("\n[b]home[/]", home)           # a single GeoInfo renders as key/value