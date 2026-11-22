#!/usr/bin/env python3
"""
Check the gluetun proxies: each should answer, exit through the VPN (not
your home IP), and use a different IP from the others.

    python test_proxies.py              # ports 8001 8002 8003
    python test_proxies.py 8001 8005    # or pick ports
"""
import sys

import requests

GEO_URL = "https://geo.fxt.dev/api/geo"
HOST    = "127.0.0.1"
PORTS   = [8001, 8002, 8003]
TIMEOUT = 15


def fetch(proxy: str | None) -> dict:
    s = requests.Session()
    s.trust_env = False                       # ignore any HTTP(S)_PROXY already set
    proxies = {"http": proxy, "https": proxy} if proxy else None
    r = s.get(GEO_URL, proxies=proxies, timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()


def describe(d: dict) -> str:
    # "region" is the serving edge (e.g. iad1), "countryRegion" is the state
    place = ", ".join(d[k] for k in ("city", "countryRegion", "country") if d.get(k))
    return f"{d.get('ip', '?'):<16} {place}"


def short(exc: Exception) -> str:
    if isinstance(exc, requests.exceptions.ProxyError):
        return "proxy not reachable (container down or wrong port?)"
    if isinstance(exc, requests.exceptions.Timeout):
        return f"timed out after {TIMEOUT}s (VPN still connecting?)"
    if isinstance(exc, requests.exceptions.ConnectionError):
        return "connection failed (DNS / network)"
    return f"{type(exc).__name__}: {str(exc)[:80]}"


def main() -> int:
    ports = [int(p) for p in sys.argv[1:]] or PORTS
    ok = True

    try:
        home = fetch(None)
        home_ip = home.get("ip")
        print(f"{'direct':<8} {describe(home)}")
    except Exception as exc:
        print(f"{'direct':<8} ✗ {short(exc)}")
        home_ip = None

    seen: dict[str, int] = {}
    for port in ports:
        proxy = f"http://{HOST}:{port}"
        try:
            d = fetch(proxy)
        except Exception as exc:
            print(f"{port:<8} ✗ {short(exc)}")
            ok = False
            continue
        ip = d.get("ip", "?")
        notes = []
        if ip == home_ip:
            notes.append("LEAK: same as direct IP")
            ok = False
        if ip in seen:
            notes.append(f"same IP as {seen[ip]}")
            ok = False
        seen.setdefault(ip, port)
        mark = "✗" if notes else "✓"
        print(f"{port:<8} {mark} {describe(d)}  {'  '.join(notes)}")

    print("all good" if ok else "problems found")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())