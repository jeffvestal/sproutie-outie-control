#!/usr/bin/env python3
"""Check the HA device identity map in config/site.yaml.

Credentials are intentionally supplied only via HA_URL and HA_ACCESS_TOKEN (or CLI options),
never through site.yaml.  This script is read-only: it does not actuate any switch.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import yaml


UNAVAILABLE = {"unknown", "unavailable", "none", ""}


class SiteConfigError(ValueError):
    """Raised when site.yaml cannot describe the device map."""


@dataclass(frozen=True)
class StateResult:
    exists: bool
    available: bool
    value: str | None
    error: str | None = None


def load_site(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as source:
        config = yaml.safe_load(source)
    if not isinstance(config, dict) or config.get("schema_version") != 1:
        raise SiteConfigError("site config must declare schema_version: 1")
    site = config.get("site")
    if not isinstance(site, dict) or not isinstance(site.get("zones"), dict):
        raise SiteConfigError("site config must contain site.zones")
    for zone_id, zone in site["zones"].items():
        if not isinstance(zone, dict):
            raise SiteConfigError(f"zone {zone_id!r} must be a mapping")
        ha = zone.get("ha")
        if not isinstance(ha, dict):
            raise SiteConfigError(f"zone {zone_id!r} must contain an ha mapping")
        devices = ha.get("devices")
        if not isinstance(devices, dict) or not devices:
            raise SiteConfigError(f"zone {zone_id!r} must contain ha.devices")
        for role, device in devices.items():
            if not isinstance(device, dict) or not device.get("switch") or not device.get("power"):
                raise SiteConfigError(f"zone {zone_id!r}, role {role!r} needs switch and power")
    return config


def fetch_state(ha_url: str, token: str | None, entity_id: str, timeout: float) -> StateResult:
    headers = {"Accept": "application/json"}
    if token:
<redacted>
        headers["Authorization"] = f"Bearer {token}"
    request = Request(f"{ha_url.rstrip('/')}/api/states/{entity_id}", headers=headers)
    try:
        with urlopen(request, timeout=timeout) as response:  # nosec B310 -- HA URL is operator supplied
            payload = json.load(response)
    except HTTPError as error:
        if error.code == 404:
            return StateResult(False, False, None, "not found")
        return StateResult(False, False, None, f"HTTP {error.code}")
    except (URLError, TimeoutError, OSError) as error:
        return StateResult(False, False, None, str(error.reason if isinstance(error, URLError) else error))
    value = str(payload.get("state", ""))
    return StateResult(True, value.lower() not in UNAVAILABLE, value)


def is_numeric_power(result: StateResult) -> bool:
    if not result.available or result.value is None:
        return False
    try:
        return math.isfinite(float(result.value))
    except ValueError:
        return False


def verify_site(config: dict[str, Any], ha_url: str, token: str | None, timeout: float) -> tuple[list[dict[str, Any]], bool]:
    reports: list[dict[str, Any]] = []
    all_required_online = True
    for zone_id, zone in config["site"]["zones"].items():
        role_reports: list[dict[str, Any]] = []
        for role, device in zone["ha"]["devices"].items():
            switch = fetch_state(ha_url, token, device["switch"], timeout)
            power = fetch_state(ha_url, token, device["power"], timeout)
            resolved = switch.exists and switch.available and power.exists and is_numeric_power(power)
            role_reports.append(
                {
                    "role": role,
                    "switch": device["switch"],
                    "switch_exists": switch.exists,
                    "switch_available": switch.available,
                    "switch_state": switch.value,
                    "power": device["power"],
                    "power_exists": power.exists,
                    "power_available": power.available,
                    "power_reporting": is_numeric_power(power),
                    "watts": power.value,
                    "online": resolved,
                    "errors": [message for message in (switch.error, power.error) if message],
                }
            )
        online = all(role["online"] for role in role_reports)
        reports.append({"zone": zone_id, "label": zone.get("label", zone_id), "online": online, "roles": role_reports})
        if zone.get("enabled", True):
            all_required_online = all_required_online and online
    return reports, all_required_online


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--site", type=Path, default=Path("config/site.yaml"), help="path to site.yaml")
    parser.add_argument("--ha-url", default=os.environ.get("HA_URL"), help="HA base URL (or HA_URL)")
    parser.add_argument("--token", default=os.environ.get("HA_ACCESS_TOKEN"), help="long-lived HA token (or HA_ACCESS_TOKEN)")
    parser.add_argument("--timeout", type=float, default=10, help="per-request timeout seconds")
    args = parser.parse_args(argv)
    if not args.ha_url:
        parser.error("--ha-url or HA_URL is required")
    try:
        config = load_site(args.site)
        reports, all_online = verify_site(config, args.ha_url, args.token, args.timeout)
    except (OSError, SiteConfigError, yaml.YAMLError) as error:
        print(f"configuration error: {error}", file=sys.stderr)
        return 2

    for zone in reports:
        print(f"{zone['zone']} ({zone['label']}): online={str(zone['online']).lower()}")
        for role in zone["roles"]:
            print(
                "  {role}: switch exists={switch_exists} available={switch_available} state={switch_state}; "
                "power exists={power_exists} available={power_available} "
                "reporting={power_reporting} watts={watts}".format(**role)
            )
            for error in role["errors"]:
                print(f"    error: {error}")
    return 0 if all_online else 1


if __name__ == "__main__":
    raise SystemExit(main())
