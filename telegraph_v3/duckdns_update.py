#!/usr/bin/env python3
"""Keep the public DuckDNS address aligned with this network's current IPv4."""

from __future__ import annotations

import subprocess
import sys

import requests


DOMAIN = "kyivestate-media"
KEYCHAIN_SERVICE = "KyivEstate DuckDNS"
KEYCHAIN_ACCOUNT = "kyivestate-media"


def token() -> str:
    result = subprocess.run(
        [
            "/usr/bin/security",
            "find-generic-password",
            "-s",
            KEYCHAIN_SERVICE,
            "-a",
            KEYCHAIN_ACCOUNT,
            "-w",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def main() -> int:
    response = requests.get(
        "https://www.duckdns.org/update",
        params={"domains": DOMAIN, "token": token(), "verbose": "true"},
        timeout=20,
    )
    response.raise_for_status()
    if not response.text.startswith("OK"):
        raise RuntimeError(f"DuckDNS rejected update: {response.text.strip()}")
    print(response.text.strip())
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(f"DuckDNS update failed: {error}", file=sys.stderr)
        raise SystemExit(1)
