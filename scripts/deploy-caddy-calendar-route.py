from __future__ import annotations

import fcntl
import json
import os
import shutil
import stat
import subprocess
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

CONFIG = Path("/etc/caddy/caddy.json")
LOCK = Path("/run/lock/flagwatch-calendar-caddy.lock")
HOST = "calendar.kitsunetechnologies.org"
UPSTREAM = "proud-coast-093b70910.7.azurestaticapps.net"


def calendar_route() -> dict[str, Any]:
    return {
        "match": [{"host": [HOST]}],
        "handle": [
            {
                "handler": "reverse_proxy",
                "headers": {"request": {"set": {"Host": [UPSTREAM]}}},
                "transport": {
                    "protocol": "http",
                    "tls": {"server_name": UPSTREAM},
                },
                "upstreams": [{"dial": f"{UPSTREAM}:443"}],
            }
        ],
        "terminal": True,
    }


def route_hosts(route: dict[str, Any]) -> set[str]:
    hosts: set[str] = set()
    for matcher in route.get("match", []):
        hosts.update(matcher.get("host", []))
    return hosts


def find_https_routes(document: dict[str, Any]) -> list[dict[str, Any]]:
    servers = document.get("apps", {}).get("http", {}).get("servers", {})
    for server in servers.values():
        routes = server.get("routes", [])
        if any(
            "kitsunetechnologies.org" in host for route in routes for host in route_hosts(route)
        ):
            return routes
    raise RuntimeError("Could not find the Kitsune HTTPS route table.")


def route_is_expected(route: dict[str, Any]) -> bool:
    if route_hosts(route) != {HOST}:
        return False
    body = json.dumps(route, sort_keys=True)
    return (
        f'"dial": "{UPSTREAM}:443"' in body
        and f'"server_name": "{UPSTREAM}"' in body
        and f'"Host": ["{UPSTREAM}"]' in body
    )


def run() -> None:
    LOCK.parent.mkdir(parents=True, exist_ok=True)
    with LOCK.open("w", encoding="utf-8") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        document = json.loads(CONFIG.read_text(encoding="utf-8"))
        routes = find_https_routes(document)
        existing = [route for route in routes if HOST in route_hosts(route)]
        if existing:
            if len(existing) != 1 or not route_is_expected(existing[0]):
                raise RuntimeError("An unexpected calendar host route already exists.")
            print(json.dumps({"ok": True, "changed": False, "host": HOST}))
            return

        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        backup = CONFIG.with_name(f"caddy.json.bak-flagwatch-calendar-{stamp}")
        config_metadata = CONFIG.stat()
        shutil.copy2(CONFIG, backup)
        routes.insert(0, calendar_route())

        descriptor, candidate_name = tempfile.mkstemp(
            prefix="caddy.json.flagwatch-calendar-", dir=CONFIG.parent
        )
        candidate = Path(candidate_name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(document, handle, indent=2)
                handle.write("\n")
            validation = subprocess.run(
                ["caddy", "validate", "--config", str(candidate)],
                capture_output=True,
                check=False,
                text=True,
            )
            if validation.returncode != 0:
                raise RuntimeError("Caddy rejected the candidate configuration.")
            os.chmod(candidate, stat.S_IMODE(config_metadata.st_mode))
            os.chown(candidate, config_metadata.st_uid, config_metadata.st_gid)
            os.replace(candidate, CONFIG)
            reload_result = subprocess.run(
                ["systemctl", "reload", "caddy"],
                capture_output=True,
                check=False,
                text=True,
            )
            if reload_result.returncode != 0:
                shutil.copy2(backup, CONFIG)
                subprocess.run(["systemctl", "reload", "caddy"], check=False)
                raise RuntimeError("Caddy reload failed and the backup was restored.")
        finally:
            candidate.unlink(missing_ok=True)

        print(
            json.dumps(
                {
                    "ok": True,
                    "changed": True,
                    "host": HOST,
                    "backup": str(backup),
                }
            )
        )


if __name__ == "__main__":
    run()
