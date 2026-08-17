#!/usr/bin/env python3
"""Small, non-destructive watchdog for the durable media services."""

from __future__ import annotations

import json
import os
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import urlopen

import requests


LABELS = (
    "kyiv-estate-media.service",
    "kyiv-estate-block1.service",
    "kyiv-estate-guard.service",
)
PROJECT = Path(os.environ["KYIV_ESTATE_HOME"])
REPORT = PROJECT / "logs" / "operations_watchdog.json"


def service_state(label: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["systemctl", "is-active", label], text=True, capture_output=True, check=False)


def check_media() -> str:
    try:
        with urlopen("http://127.0.0.1:8787/healthz", timeout=8) as response:
            payload = json.loads(response.read().decode())
        if payload.get("ok"):
            return "ok"
    except Exception as error:
        return f"error:{type(error).__name__}"
    return "invalid_response"


def check_socket() -> str:
    path = os.getenv("TAILSCALE_SOCKET", "/var/run/tailscale/tailscaled.sock")
    if not Path(path).exists():
        return "service_unavailable"
    result = subprocess.run(
        ["tailscale", f"--socket={path}", "status", "--json"],
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        return "waiting_for_login"
    try:
        return "ready" if json.loads(result.stdout).get("BackendState") == "Running" else "waiting_for_login"
    except json.JSONDecodeError:
        return "waiting_for_login"


def check_duckdns() -> str:
    response = requests.get(
        "https://dns.google/resolve",
        params={"name": "kyivestate-media.duckdns.org", "type": "A"},
        timeout=10,
    )
    response.raise_for_status()
    answers = response.json().get("Answer", [])
    return next((str(item["data"]) for item in answers if item.get("type") == 1), "unresolved")


def ensure_funnel() -> str:
    """Enable the HTTPS media endpoint as soon as its one-time account approval exists."""
    socket_path = os.getenv("TAILSCALE_SOCKET", "/var/run/tailscale/tailscaled.sock")
    result = subprocess.run(
        ["tailscale", f"--socket={socket_path}", "funnel", "--bg", "--yes", "8787"],
        text=True,
        capture_output=True,
        check=False,
        timeout=30,
    )
    if result.returncode == 0:
        return "enabled"
    message = (result.stdout + result.stderr).lower()
    return "awaiting_account_approval" if "not enabled on your tailnet" in message else "unavailable"


def main() -> int:
    report: dict[str, object] = {"checked_at": datetime.now(timezone.utc).isoformat(), "services": {}}
    services: dict[str, str] = {}
    for label in LABELS:
        result = service_state(label)
        services[label] = result.stdout.strip() if result.returncode == 0 else "missing"
    report["services"] = services
    report["media_server"] = check_media()
    report["tailscale"] = check_socket()



    report["funnel"] = "pending_account_approval" if report["tailscale"] == "ready" else "waiting_for_login"
    report["duckdns_hostname"] = check_duckdns()
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    if report["media_server"] != "ok" and services["kyiv-estate-media.service"] == "active":
        subprocess.run(["systemctl", "restart", "kyiv-estate-media.service"], check=False)
        time.sleep(2)
        report["media_server_after_restart"] = check_media()
        REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(report, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
