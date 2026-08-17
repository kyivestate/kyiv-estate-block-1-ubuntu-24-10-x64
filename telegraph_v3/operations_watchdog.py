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


UID = os.getuid()
LABELS = (
    "com.kyivestate.media-server",
    "com.kyivestate.media-archive",
    "com.kyivestate.duckdns",
    "com.kyivestate.tailscaled",
)
PROJECT = Path("/Users/admin/Projects/real-estate-platform/telegram-bot")
REPORT = PROJECT / "logs" / "operations_watchdog.json"


def launchctl(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["launchctl", *args], text=True, capture_output=True, check=False)


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
    path = "/Users/admin/Library/Application Support/KyivEstate/tailscaled.sock"
    if not Path(path).exists():
        return "service_unavailable"
    result = subprocess.run(
        ["/opt/homebrew/bin/tailscale", f"--socket={path}", "status", "--json"],
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
    socket_path = "/Users/admin/Library/Application Support/KyivEstate/tailscaled.sock"
    result = subprocess.run(
        ["/opt/homebrew/bin/tailscale", f"--socket={socket_path}", "funnel", "--bg", "--yes", "8787"],
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
        result = launchctl("print", f"gui/{UID}/{label}")
        services[label] = "loaded" if result.returncode == 0 else "missing"
    report["services"] = services
    report["media_server"] = check_media()
    report["tailscale"] = check_socket()
    # Funnel authorization is account-level and must be approved in Tailscale once.
    # A pending `tailscale funnel` command remains active independently until that
    # approval arrives; the watchdog must never block a later audit on it.
    report["funnel"] = "pending_account_approval" if report["tailscale"] == "ready" else "waiting_for_login"
    report["duckdns_hostname"] = check_duckdns()
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    if report["media_server"] != "ok" and services["com.kyivestate.media-server"] == "loaded":
        launchctl("kickstart", "-k", f"gui/{UID}/com.kyivestate.media-server")
        time.sleep(2)
        report["media_server_after_restart"] = check_media()
        REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(report, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
