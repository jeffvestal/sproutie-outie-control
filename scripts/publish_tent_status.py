#!/usr/bin/env python3
"""Publish the frozen §2.1 tent status contract from read-only HA state.

Home Assistant credentials come only from HA_URL and HA_ACCESS_TOKEN.  The default
operation reads HA and atomically writes status/tent.yaml.  Git publication is a separate,
explicit --git-publish operation so local validation cannot push accidentally.
"""

from __future__ import annotations

import argparse
import math
import os
import re
import subprocess
import sys
import tempfile
import time
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

import yaml

if __package__:
    from .verify_devices import SiteConfigError, StateResult, fetch_state, load_site
else:
    from verify_devices import SiteConfigError, StateResult, fetch_state, load_site


REPO = Path(__file__).resolve().parents[1]
SCHEMA_VERSION = 1
PUBLISHER_VERSION = "0.1.0"
POWER_POLL_INTERVAL_S = 2.0
METRIC_NAMES = ("temp_f", "rh", "vpd_kpa", "co2_ppm")
METRIC_KEYS = {"value", "band", "status"}
ZONE_KEYS = {"label", "online", "env", "devices", "layout", "cameras", "alerts", "grows"}
GROW_KEYS = {
    "id", "crop", "recipe", "owner", "tracking", "slots", "sown_at", "phase",
    "phase_index", "phases", "day", "expected_days", "eta", "gdd", "coverage",
    "weight", "photo", "last_event",
}
ENTITY_LIKE = re.compile(
    r"(?<![A-Za-z0-9_])(?:"
    r"alarm_control_panel|assist_satellite|automation|binary_sensor|button|calendar|camera|"
    r"climate|conversation|cover|device_tracker|event|fan|humidifier|image|input_boolean|"
    r"input_datetime|input_number|input_select|input_text|light|lock|media_player|notify|"
    r"number|person|remote|scene|script|select|sensor|sun|switch|timer|update|vacuum|"
    r"water_heater|weather|zone"
    r")\.[a-z0-9_]+(?![A-Za-z0-9_])",
    re.IGNORECASE,
)
ROLE_NAME = re.compile(r"^[a-z][a-z0-9_]*$")
IPV4_LIKE = re.compile(r"(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?![\d.])")
PRIVATE_HOST_LIKE = re.compile(r"\b[a-z0-9-]+\.(?:lan|local)\b", re.IGNORECASE)
SECRET_LIKE = re.compile(r"(?:\bBearer\s+|github_pat_|gh[oprsu]_[A-Za-z0-9_]{12,})", re.IGNORECASE)
SAFE_REF = re.compile(r"^[A-Za-z0-9._/-]+$")


class StatusPublishError(RuntimeError):
    """Raised when a complete, public-safe status snapshot cannot be produced."""


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _is_number(value: Any) -> bool:
    return not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(float(value))


def _utc_timestamp(value: datetime) -> str:
    if value.tzinfo is None:
        raise StatusPublishError("generated_at must be timezone-aware")
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _parse_utc_timestamp(value: Any, field: str) -> None:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise StatusPublishError(f"{field} must be a UTC ISO8601 timestamp ending in Z")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as error:
        raise StatusPublishError(f"{field} must be a UTC ISO8601 timestamp") from error
    if parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise StatusPublishError(f"{field} must be UTC")


def _parse_iso_date(value: Any, field: str) -> None:
    if value is None:
        return
    if not isinstance(value, str):
        raise StatusPublishError(f"{field} must be an ISO8601 date or null")
    try:
        date.fromisoformat(value)
    except ValueError as error:
        raise StatusPublishError(f"{field} must be an ISO8601 date") from error


def _exact_keys(mapping: Any, required: set[str], field: str, optional: set[str] | None = None) -> None:
    if not isinstance(mapping, dict):
        raise StatusPublishError(f"{field} must be a mapping")
    optional = optional or set()
    missing = required - set(mapping)
    unknown = set(mapping) - required - optional
    if missing:
        raise StatusPublishError(f"{field} is missing required fields: {', '.join(sorted(missing))}")
    if unknown:
        raise StatusPublishError(f"{field} contains fields outside §2.1: {', '.join(sorted(unknown))}")


def _validate_band(value: Any, field: str) -> None:
    if value is None:
        return
    if not isinstance(value, list) or len(value) != 2 or not all(_is_number(item) for item in value):
        raise StatusPublishError(f"{field} must be a two-number band or null")
    if float(value[0]) > float(value[1]):
        raise StatusPublishError(f"{field} lower bound must not exceed its upper bound")


def _metric(value: float | None, band: list[float] | None) -> dict[str, Any]:
    status = None
    if value is not None and band is not None:
        if value < band[0]:
            status = "below"
        elif value > band[1]:
            status = "above"
        else:
            status = "in"
    return {"value": value, "band": band, "status": status}


def _band_for(zone: dict[str, Any], metric: str) -> list[float] | None:
    status_config = zone.get("status", {})
    bands = status_config.get("env_bands", {}) if isinstance(status_config, dict) else {}
    raw = bands.get(metric) if isinstance(bands, dict) else None
    if raw is None:
        return None
    _validate_band(raw, f"status.env_bands.{metric}")
    return [float(raw[0]), float(raw[1])]


def _vpd_kpa(temp_f: float, relative_humidity: float) -> float:
    temp_c = (temp_f - 32.0) * 5.0 / 9.0
    saturation_kpa = 0.6108 * math.exp((17.27 * temp_c) / (temp_c + 237.3))
    return round(saturation_kpa * (1.0 - relative_humidity / 100.0), 2)


def _fetch_required(
    ha_url: str,
    access_credential: str | None,
    entity: str,
    timeout: float,
    description: str,
) -> StateResult:
    result = fetch_state(ha_url, access_credential, entity, timeout)
    if not result.exists:
        suffix = f": {result.error}" if result.error else ""
        raise StatusPublishError(f"HA fetch failed for {description}{suffix}")
    return result


def _state_value(result: StateResult) -> str | None:
    if not result.available or result.value is None:
        return None
    state = result.value.strip().lower()
    return state if state in {"on", "off"} else None


def _device_verified(
    initial: StateResult,
    final: StateResult,
    watts: float | None,
    device: dict[str, Any],
    off_threshold_w: float,
) -> bool:
    initial_state = _state_value(initial)
    final_state = _state_value(final)
    if initial_state is None or final_state is None or initial_state != final_state or watts is None:
        return False
    if final_state == "off":
        return watts <= off_threshold_w
    expected = device.get("expected_watts_on")
    if not isinstance(expected, list) or len(expected) != 2:
        return False
    low, high = (_number(expected[0]), _number(expected[1]))
    return low is not None and high is not None and low <= watts <= high


def _layout(zone: dict[str, Any], zone_id: str) -> dict[str, Any]:
    layout = zone.get("layout")
    if not isinstance(layout, dict):
        raise StatusPublishError(f"zone {zone_id} needs layout")
    racks: list[dict[str, Any]] = []
    for rack in layout.get("racks", []):
        if not isinstance(rack, dict):
            raise StatusPublishError(f"zone {zone_id} has an invalid rack")
        racks.append({"id": rack.get("id"), "label": rack.get("label"), "slots": rack.get("slots")})
    sidecars: list[dict[str, Any]] = []
    for sidecar in layout.get("sidecars", []):
        if not isinstance(sidecar, dict):
            raise StatusPublishError(f"zone {zone_id} has an invalid sidecar")
        sidecars.append({"id": sidecar.get("id"), "label": sidecar.get("label")})
    return {"racks": racks, "sidecars": sidecars}


def _camera_label(camera_id: str) -> str:
    return camera_id.replace("_", " ").replace("-", " ").title()


def _contract_scalar(value: Any) -> Any:
    """Convert PyYAML timestamp objects back to the strings the public contract carries."""
    if isinstance(value, datetime):
        return _utc_timestamp(value)
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: _contract_scalar(child) for key, child in value.items()}
    if isinstance(value, list):
        return [_contract_scalar(child) for child in value]
    return value


def _offline_zone(zone_id: str, zone: dict[str, Any], grows: list[dict[str, Any]]) -> dict[str, Any]:
    ha = zone["ha"]
    bands = {metric: _band_for(zone, metric) for metric in METRIC_NAMES}
    cameras = [
        {
            "id": camera_id,
            "label": camera.get("label", _camera_label(camera_id)),
            "covers": list(camera.get("covers", [])),
            "snapshot": None,
            "captured_at": None,
            "interval_s": int(zone.get("fallback", {}).get("photo_cadence_s", 3600)),
            "online": False,
            "stream": None,
        }
        for camera_id, camera in ha.get("cameras", {}).items()
    ]
    return {
        "label": zone.get("label", zone_id),
        "online": False,
        "env": {
            "temp_f": _metric(None, bands["temp_f"]),
            "rh": _metric(None, bands["rh"]),
            "vpd_kpa": _metric(None, bands["vpd_kpa"]),
            "co2_ppm": _metric(None, bands["co2_ppm"]),
            "outside": None,
        },
        "devices": {
            role: {"state": None, "verified": False, "watts": None}
            for role in ha["devices"]
        },
        "layout": _layout(zone, zone_id),
        "cameras": cameras,
        "alerts": [],
        "grows": grows,
    }


def _live_zone(
    zone_id: str,
    zone: dict[str, Any],
    ha_url: str,
    access_credential: str | None,
    timeout: float,
    grows: list[dict[str, Any]],
    sleeper: Callable[[float], None],
) -> dict[str, Any]:
    ha = zone["ha"]
    devices_config = ha["devices"]
    verification = zone.get("fallback", {}).get("device_verification")
    if not isinstance(verification, dict):
        raise StatusPublishError(f"enabled zone {zone_id} needs fallback.device_verification")
    settle_s = _number(verification.get("settle_s"))
    poll_timeout_s = _number(verification.get("poll_timeout_s"))
    off_threshold_w = _number(verification.get("off_threshold_w"))
    if (
        settle_s is None or settle_s < 0
        or poll_timeout_s is None or poll_timeout_s < 0
        or off_threshold_w is None or off_threshold_w < 0
    ):
        raise StatusPublishError(f"enabled zone {zone_id} has invalid device verification settings")

    initial_switches = {
        role: _fetch_required(ha_url, access_credential, device["switch"], timeout, f"{zone_id}/{role} initial switch")
        for role, device in devices_config.items()
    }
    sleeper(settle_s)

    observations: dict[str, tuple[str | None, float | None]] = {}
    confirmation_streak = {role: 0 for role in devices_config}
    verified = {role: False for role in devices_config}
    terminal_roles: set[str] = set()
    poll_elapsed_s = 0.0
    while True:
        for role, device in devices_config.items():
            if role in terminal_roles:
                continue
            final_switch = _fetch_required(
                ha_url, access_credential, device["switch"], timeout, f"{zone_id}/{role} final switch"
            )
            power = _fetch_required(
                ha_url, access_credential, device["power"], timeout, f"{zone_id}/{role} power"
            )
            state = _state_value(final_switch)
            watts = _number(power.value) if power.available else None
            observations[role] = (state, watts)

            initial_state = _state_value(initial_switches[role])
            if state is None or initial_state is None or state != initial_state:
                # A relay transition invalidates this run's settle window.  Publish the observed
                # state, but never call it verified until a future run sees a full stable window.
                terminal_roles.add(role)
                continue
            if _device_verified(initial_switches[role], final_switch, watts, device, off_threshold_w):
                confirmation_streak[role] += 1
                if confirmation_streak[role] >= 2:
                    verified[role] = True
                    terminal_roles.add(role)
            else:
                confirmation_streak[role] = 0

        if len(terminal_roles) == len(devices_config) or poll_elapsed_s >= poll_timeout_s:
            break
        delay = min(POWER_POLL_INTERVAL_S, poll_timeout_s - poll_elapsed_s)
        if delay <= 0:
            break
        sleeper(delay)
        poll_elapsed_s += delay

    devices = {
        role: {
            "state": observations[role][0],
            "verified": verified[role],
            "watts": observations[role][1],
        }
        for role in devices_config
    }
    online = all(device["state"] is not None and device["watts"] is not None for device in devices.values())

    telemetry = ha.get("telemetry")
    if not isinstance(telemetry, dict) or "temp_f" not in telemetry or "rh" not in telemetry:
        raise StatusPublishError(f"enabled zone {zone_id} needs temp_f and rh telemetry roles")
    values: dict[str, float | None] = {}
    for role in ("temp_f", "rh", "co2_ppm", "outside_temp_f", "outside_rh"):
        if role not in telemetry:
            continue
        result = _fetch_required(ha_url, access_credential, telemetry[role], timeout, f"{zone_id}/{role} telemetry")
        values[role] = _number(result.value) if result.available else None
        online = online and values[role] is not None

    temp_f = values.get("temp_f")
    relative_humidity = values.get("rh")
    vpd = None
    if temp_f is not None and relative_humidity is not None and 0 <= relative_humidity <= 100:
        vpd = _vpd_kpa(temp_f, relative_humidity)
    elif relative_humidity is not None:
        online = False
    outside = None
    if "outside_temp_f" in telemetry or "outside_rh" in telemetry:
        outside = {"temp_f": values.get("outside_temp_f"), "rh": values.get("outside_rh")}

    cameras: list[dict[str, Any]] = []
    for camera_id, camera in ha.get("cameras", {}).items():
        result = _fetch_required(ha_url, access_credential, camera["entity"], timeout, f"{zone_id}/{camera_id} camera")
        camera_online = result.available
        online = online and camera_online
        cameras.append(
            {
                "id": camera_id,
                "label": camera.get("label", _camera_label(camera_id)),
                "covers": list(camera.get("covers", [])),
                "snapshot": None,
                "captured_at": None,
                "interval_s": int(zone.get("fallback", {}).get("photo_cadence_s", 3600)),
                "online": camera_online,
                "stream": None,
            }
        )

    return {
        "label": zone.get("label", zone_id),
        "online": online,
        "env": {
            "temp_f": _metric(temp_f, _band_for(zone, "temp_f")),
            "rh": _metric(relative_humidity, _band_for(zone, "rh")),
            "vpd_kpa": _metric(vpd, _band_for(zone, "vpd_kpa")),
            "co2_ppm": _metric(values.get("co2_ppm"), _band_for(zone, "co2_ppm")),
            "outside": outside,
        },
        "devices": devices,
        "layout": _layout(zone, zone_id),
        "cameras": cameras,
        "alerts": [],
        "grows": grows,
    }


def load_grows(path: Path) -> list[dict[str, Any]]:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as error:
        raise StatusPublishError(f"cannot read grows state: {error}") from error
    if not isinstance(raw, list):
        raise StatusPublishError("state/grows.yaml must be a top-level array")
    normalized: list[dict[str, Any]] = []
    for index, grow in enumerate(raw):
        if not isinstance(grow, dict):
            raise StatusPublishError(f"grows[{index}] must be a mapping")
        unknown = set(grow) - GROW_KEYS
        if unknown:
            raise StatusPublishError(
                f"grows[{index}] contains fields outside §2.1: {', '.join(sorted(unknown))}"
            )
        required_source = {"id", "crop", "recipe", "tracking", "slots", "sown_at", "phase", "day"}
        missing = required_source - set(grow)
        if missing:
            raise StatusPublishError(f"grows[{index}] is missing: {', '.join(sorted(missing))}")
        normalized.append({key: _contract_scalar(grow.get(key)) for key in GROW_KEYS})
    return normalized


def build_status(
    config: dict[str, Any],
    grows: list[dict[str, Any]],
    ha_url: str,
    access_credential: str | None,
    timeout: float,
    *,
    now: datetime | None = None,
    sleeper: Callable[[float], None] = time.sleep,
    monotonic: Callable[[], float] = time.monotonic,
) -> dict[str, Any]:
    started_at = monotonic()
    zones_config = config["site"]["zones"]
    enabled = [zone_id for zone_id, zone in zones_config.items() if zone.get("enabled", True)]
    if grows and len(enabled) != 1:
        raise StatusPublishError("non-empty grows require exactly one enabled zone in this slice")
    grow_zone = enabled[0] if grows else None

    zones: dict[str, dict[str, Any]] = {}
    for zone_id, zone in zones_config.items():
        zone_grows = grows if zone_id == grow_zone else []
        if zone.get("enabled", True):
            zones[zone_id] = _live_zone(zone_id, zone, ha_url, access_credential, timeout, zone_grows, sleeper)
        else:
            zones[zone_id] = _offline_zone(zone_id, zone, zone_grows)

    generated_at = _utc_timestamp(now or datetime.now(timezone.utc))
    status = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at,
        "brain": {
            "version": PUBLISHER_VERSION,
            "uptime_s": int(max(0, monotonic() - started_at)),
            "queues": {"spool": 0, "git_pending": 0},
        },
        "zones": zones,
    }
    validate_status(status)
    assert_public_safe(status)
    return status


def _validate_metric(metric: Any, field: str) -> None:
    _exact_keys(metric, METRIC_KEYS, field)
    if metric["value"] is not None and not _is_number(metric["value"]):
        raise StatusPublishError(f"{field}.value must be a finite number or null")
    _validate_band(metric["band"], f"{field}.band")
    if metric["status"] not in {None, "below", "in", "above"}:
        raise StatusPublishError(f"{field}.status is not a §2.1 status")
    expected = _metric(metric["value"], metric["band"])["status"]
    if metric["status"] != expected:
        raise StatusPublishError(f"{field}.status does not match its value and band")


def _validate_layout(layout: Any, field: str) -> tuple[set[str], set[str]]:
    _exact_keys(layout, {"racks", "sidecars"}, field)
    if not isinstance(layout["racks"], list) or not isinstance(layout["sidecars"], list):
        raise StatusPublishError(f"{field} racks and sidecars must be arrays")
    slots: set[str] = set()
    ids: set[str] = set()
    for index, rack in enumerate(layout["racks"]):
        rack_field = f"{field}.racks[{index}]"
        _exact_keys(rack, {"id", "label", "slots"}, rack_field)
        if not isinstance(rack["id"], str) or not isinstance(rack["label"], str):
            raise StatusPublishError(f"{rack_field} id and label must be strings")
        if not isinstance(rack["slots"], list) or not all(isinstance(slot, str) for slot in rack["slots"]):
            raise StatusPublishError(f"{rack_field}.slots must be a string array")
        if rack["id"] in ids or rack["id"] in slots or slots.intersection(rack["slots"]):
            raise StatusPublishError(f"{rack_field} duplicates a layout id or slot")
        ids.add(rack["id"])
        slots.update(rack["slots"])
    for index, sidecar in enumerate(layout["sidecars"]):
        sidecar_field = f"{field}.sidecars[{index}]"
        _exact_keys(sidecar, {"id", "label"}, sidecar_field)
        if not isinstance(sidecar["id"], str) or not isinstance(sidecar["label"], str):
            raise StatusPublishError(f"{sidecar_field} id and label must be strings")
        if sidecar["id"] in ids or sidecar["id"] in slots:
            raise StatusPublishError(f"{sidecar_field} duplicates a layout id")
        ids.add(sidecar["id"])
        slots.add(sidecar["id"])
    return slots, ids


def _validate_optional_path(value: Any, field: str) -> None:
    if value is None:
        return
    if not isinstance(value, str) or not value.startswith("status/latest/") or ".." in Path(value).parts:
        raise StatusPublishError(f"{field} must be a repo-relative status/latest path or null")


def _validate_grow(grow: Any, field: str, layout_slots: set[str]) -> None:
    _exact_keys(grow, GROW_KEYS, field)
    for key in ("id", "crop", "recipe", "tracking", "phase"):
        if not isinstance(grow[key], str) or not grow[key]:
            raise StatusPublishError(f"{field}.{key} must be a non-empty string")
    if grow["owner"] is not None and not isinstance(grow["owner"], str):
        raise StatusPublishError(f"{field}.owner must be a string or null")
    if grow["tracking"] not in {"cycle", "milestone"}:
        raise StatusPublishError(f"{field}.tracking is not a §2.1 tracking mode")
    if not isinstance(grow["slots"], list) or not grow["slots"] or not all(isinstance(slot, str) for slot in grow["slots"]):
        raise StatusPublishError(f"{field}.slots must be a non-empty string array")
    if not set(grow["slots"]).issubset(layout_slots):
        raise StatusPublishError(f"{field}.slots references a slot absent from layout")
    _parse_utc_timestamp(grow["sown_at"], f"{field}.sown_at")
    for key in ("phase_index", "day", "expected_days"):
        if grow[key] is not None and (not isinstance(grow[key], int) or isinstance(grow[key], bool) or grow[key] < 0):
            raise StatusPublishError(f"{field}.{key} must be a non-negative integer or null")
    if grow["day"] is None:
        raise StatusPublishError(f"{field}.day is required")
    if grow["phases"] is not None:
        if not isinstance(grow["phases"], list):
            raise StatusPublishError(f"{field}.phases must be an array or null")
        for index, phase in enumerate(grow["phases"]):
            _exact_keys(phase, {"name", "days"}, f"{field}.phases[{index}]")
            if not isinstance(phase["name"], str) or not isinstance(phase["days"], int) or phase["days"] < 0:
                raise StatusPublishError(f"{field}.phases[{index}] is invalid")
    if grow["eta"] is not None:
        _exact_keys(grow["eta"], {"date", "plus_minus_d", "gdd_says", "camera_says", "agreement"}, f"{field}.eta")
        for key in ("date", "gdd_says", "camera_says"):
            _parse_iso_date(grow["eta"][key], f"{field}.eta.{key}")
        plus_minus = grow["eta"]["plus_minus_d"]
        if plus_minus is not None and (not isinstance(plus_minus, int) or isinstance(plus_minus, bool) or plus_minus < 0):
            raise StatusPublishError(f"{field}.eta.plus_minus_d must be a non-negative integer or null")
        if grow["eta"]["agreement"] not in {None, "agree", "disagree", "single"}:
            raise StatusPublishError(f"{field}.eta.agreement is invalid")
    if grow["gdd"] is not None:
        _exact_keys(grow["gdd"], {"accum", "target"}, f"{field}.gdd")
        if not all(value is None or _is_number(value) for value in grow["gdd"].values()):
            raise StatusPublishError(f"{field}.gdd values must be finite numbers or null")
    if grow["coverage"] is not None and (not _is_number(grow["coverage"]) or not 0 <= grow["coverage"] <= 1):
        raise StatusPublishError(f"{field}.coverage must be between 0 and 1 or null")
    if grow["weight"] is not None:
        _exact_keys(grow["weight"], {"g", "trend", "water_needed", "deficit_g"}, f"{field}.weight")
        if not all(grow["weight"][key] is None or _is_number(grow["weight"][key]) for key in ("g", "deficit_g")):
            raise StatusPublishError(f"{field}.weight measurements must be finite numbers or null")
        if grow["weight"]["trend"] is not None and not isinstance(grow["weight"]["trend"], str):
            raise StatusPublishError(f"{field}.weight.trend must be a string or null")
        if grow["weight"]["water_needed"] is not None and not isinstance(grow["weight"]["water_needed"], bool):
            raise StatusPublishError(f"{field}.weight.water_needed must be boolean or null")
    _validate_optional_path(grow["photo"], f"{field}.photo")
    if grow["last_event"] is not None:
        _exact_keys(grow["last_event"], {"kind", "at", "detail"}, f"{field}.last_event")
        if not all(isinstance(grow["last_event"][key], str) for key in ("kind", "detail")):
            raise StatusPublishError(f"{field}.last_event kind and detail must be strings")
        _parse_utc_timestamp(grow["last_event"]["at"], f"{field}.last_event.at")
    if grow["tracking"] == "milestone":
        for key in ("phase_index", "phases", "expected_days", "eta"):
            if grow[key] is not None:
                raise StatusPublishError(f"{field}.{key} must be null for milestone tracking")


def validate_status(status: Any) -> None:
    _exact_keys(status, {"schema_version", "generated_at", "brain", "zones"}, "status")
    if status["schema_version"] != SCHEMA_VERSION:
        raise StatusPublishError(f"unsupported schema_version: {status['schema_version']!r}")
    _parse_utc_timestamp(status["generated_at"], "generated_at")
    _exact_keys(status["brain"], {"version", "uptime_s", "queues"}, "brain")
    if not isinstance(status["brain"]["version"], str):
        raise StatusPublishError("brain.version must be a string")
    if not isinstance(status["brain"]["uptime_s"], int) or status["brain"]["uptime_s"] < 0:
        raise StatusPublishError("brain.uptime_s must be a non-negative integer")
    _exact_keys(status["brain"]["queues"], {"spool", "git_pending"}, "brain.queues")
    if not all(isinstance(value, int) and not isinstance(value, bool) and value >= 0 for value in status["brain"]["queues"].values()):
        raise StatusPublishError("brain queues must be non-negative integers")
    if not isinstance(status["zones"], dict) or not status["zones"]:
        raise StatusPublishError("zones must be a non-empty mapping")

    for zone_id, zone in status["zones"].items():
        field = f"zones.{zone_id}"
        if not isinstance(zone_id, str) or not zone_id:
            raise StatusPublishError("zone ids must be non-empty strings")
        _exact_keys(zone, ZONE_KEYS, field)
        if not isinstance(zone["label"], str) or not isinstance(zone["online"], bool):
            raise StatusPublishError(f"{field} label/online are invalid")
        _exact_keys(zone["env"], set(METRIC_NAMES) | {"outside"}, f"{field}.env")
        for metric_name in METRIC_NAMES:
            _validate_metric(zone["env"][metric_name], f"{field}.env.{metric_name}")
        outside = zone["env"]["outside"]
        if outside is not None:
            _exact_keys(outside, {"temp_f", "rh"}, f"{field}.env.outside")
            if not all(value is None or _is_number(value) for value in outside.values()):
                raise StatusPublishError(f"{field}.env.outside values must be finite numbers or null")
        if not isinstance(zone["devices"], dict):
            raise StatusPublishError(f"{field}.devices must be role-keyed mapping")
        for role, device in zone["devices"].items():
            device_field = f"{field}.devices.{role}"
            if not isinstance(role, str) or not ROLE_NAME.fullmatch(role):
                raise StatusPublishError(f"{field}.devices has an invalid role key")
            _exact_keys(device, {"state", "verified", "watts"}, device_field, {"mode", "duty_1h"})
            if device["state"] not in {None, "on", "off"}:
                raise StatusPublishError(f"{device_field}.state must be on, off, or null")
            if not isinstance(device["verified"], bool):
                raise StatusPublishError(f"{device_field}.verified must always be boolean")
            if device["watts"] is not None and not _is_number(device["watts"]):
                raise StatusPublishError(f"{device_field}.watts must be a finite number or null")
            if "mode" in device and device["mode"] is not None and not isinstance(device["mode"], str):
                raise StatusPublishError(f"{device_field}.mode must be a string or null")
            if "duty_1h" in device and device["duty_1h"] is not None and not _is_number(device["duty_1h"]):
                raise StatusPublishError(f"{device_field}.duty_1h must be a finite number or null")
        layout_slots, layout_ids = _validate_layout(zone["layout"], f"{field}.layout")
        if not isinstance(zone["cameras"], list):
            raise StatusPublishError(f"{field}.cameras must be an array")
        for index, camera in enumerate(zone["cameras"]):
            camera_field = f"{field}.cameras[{index}]"
            _exact_keys(camera, {"id", "label", "covers", "snapshot", "captured_at", "interval_s", "online", "stream"}, camera_field)
            if not isinstance(camera["id"], str) or not isinstance(camera["label"], str):
                raise StatusPublishError(f"{camera_field} id and label must be strings")
            if not isinstance(camera["covers"], list) or not all(isinstance(value, str) for value in camera["covers"]):
                raise StatusPublishError(f"{camera_field}.covers must be a string array")
            if not set(camera["covers"]).issubset(layout_ids):
                raise StatusPublishError(f"{camera_field}.covers references an id absent from layout")
            _validate_optional_path(camera["snapshot"], f"{camera_field}.snapshot")
            if camera["captured_at"] is not None:
                _parse_utc_timestamp(camera["captured_at"], f"{camera_field}.captured_at")
            if not isinstance(camera["interval_s"], int) or isinstance(camera["interval_s"], bool) or camera["interval_s"] <= 0:
                raise StatusPublishError(f"{camera_field}.interval_s must be a positive integer")
            if not isinstance(camera["online"], bool) or camera["stream"] is not None:
                raise StatusPublishError(f"{camera_field} online/stream are invalid for the public publisher")
        if not isinstance(zone["alerts"], list):
            raise StatusPublishError(f"{field}.alerts must be an array")
        for index, alert in enumerate(zone["alerts"]):
            alert_field = f"{field}.alerts[{index}]"
            _exact_keys(alert, {"id", "kind", "severity", "title", "detail", "score", "grow", "since", "actions"}, alert_field)
            if not all(isinstance(alert[key], str) for key in ("id", "kind", "severity", "title", "detail")):
                raise StatusPublishError(f"{alert_field} identity and copy fields must be strings")
            if alert["severity"] not in {"info", "warn", "urgent"}:
                raise StatusPublishError(f"{alert_field}.severity is invalid")
            if alert["score"] is not None:
                _exact_keys(alert["score"], {"value", "max"}, f"{alert_field}.score")
                if not all(_is_number(value) for value in alert["score"].values()):
                    raise StatusPublishError(f"{alert_field}.score values must be finite numbers")
            if alert["grow"] is not None and not isinstance(alert["grow"], str):
                raise StatusPublishError(f"{alert_field}.grow must be a string or null")
            _parse_utc_timestamp(alert["since"], f"{alert_field}.since")
            if not isinstance(alert["actions"], list) or not all(isinstance(action, str) for action in alert["actions"]):
                raise StatusPublishError(f"{alert_field}.actions must be a string array")
        if not isinstance(zone["grows"], list):
            raise StatusPublishError(f"{field}.grows must be an array")
        for index, grow in enumerate(zone["grows"]):
            _validate_grow(grow, f"{field}.grows[{index}]", layout_slots)


def _walk_strings(value: Any) -> Iterable[tuple[str, str]]:
    if isinstance(value, dict):
        for key, child in value.items():
            if isinstance(key, str):
                yield "key", key
            yield from _walk_strings(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_strings(child)
    elif isinstance(value, str):
        yield "value", value


def assert_public_safe(status: dict[str, Any]) -> None:
    for kind, value in _walk_strings(status):
        if ENTITY_LIKE.search(value):
            raise StatusPublishError("public status contains a Home Assistant-like entity identifier")
        if "://" in value or PRIVATE_HOST_LIKE.search(value):
            raise StatusPublishError("public status contains a URL or private hostname")
        for match in IPV4_LIKE.finditer(value):
            octets = [int(part) for part in match.group().split(".")]
            if all(0 <= part <= 255 for part in octets):
                raise StatusPublishError("public status contains an IP address")
        if SECRET_LIKE.search(value):
            raise StatusPublishError("public status contains credential-like text")
    rendered = yaml.safe_dump(status, sort_keys=False, allow_unicode=True)
    lowered = rendered.lower()
    for forbidden in ("ha_access_token", "authorization:", "password:", "api_key:", "camera_url:"):
        if forbidden in lowered:
            raise StatusPublishError("public status contains a forbidden credential or URL field")


def render_status(status: dict[str, Any]) -> str:
    validate_status(status)
    assert_public_safe(status)
    return yaml.safe_dump(status, sort_keys=False, allow_unicode=True, default_flow_style=False)


def atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", suffix=".tmp", delete=False
        ) as output:
            temporary = Path(output.name)
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
        os.chmod(temporary, 0o644)
        os.replace(temporary, path)
    except Exception:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        raise


def _status_only_push_range(
    run: Callable[..., subprocess.CompletedProcess[str]],
    remote: str,
    branch: str,
    relative_status: Path,
) -> bool:
    """Prove every local commit about to cross the remote boundary is status-only."""
    tracking_ref = f"{remote}/{branch}"
    tracking = run(["git", "rev-parse", "--verify", "--quiet", tracking_ref], check=False)
    if tracking.returncode != 0:
        raise StatusPublishError(f"cannot prove push range without local tracking ref {tracking_ref!r}")
    commits = run(["git", "rev-list", "--reverse", f"{tracking_ref}..HEAD"]).stdout.splitlines()
    expected = str(relative_status)
    for commit in commits:
        paths = {
            path for path in run(
                ["git", "diff-tree", "--root", "--no-commit-id", "--name-only", "-r", commit]
            ).stdout.splitlines()
            if path
        }
        if not paths or paths != {expected}:
            raise StatusPublishError(
                f"refusing to push commit {commit[:12]} because it is not limited to {expected}"
            )
    return bool(commits)


def publish_git(repo: Path, status_path: Path, config: dict[str, Any], generated_at: str) -> bool:
    bridge = config["site"].get("bridge")
    if not isinstance(bridge, dict):
        raise StatusPublishError("site.bridge is required for --git-publish")
    remote, branch = bridge.get("remote"), bridge.get("branch")
    if not isinstance(remote, str) or not isinstance(branch, str) or not SAFE_REF.fullmatch(remote) or not SAFE_REF.fullmatch(branch):
        raise StatusPublishError("site.bridge remote or branch is unsafe")
    try:
        relative = status_path.resolve().relative_to(repo.resolve())
    except ValueError as error:
        raise StatusPublishError("status output must be inside the repository for --git-publish") from error

    def run(args: list[str], check: bool = True) -> subprocess.CompletedProcess[str]:
        return subprocess.run(args, cwd=repo, check=check, text=True, capture_output=True)

    try:
        current_branch = run(["git", "branch", "--show-current"]).stdout.strip()
        if current_branch != branch:
            raise StatusPublishError(f"refusing git publish from branch {current_branch!r}; expected {branch!r}")
        run(["git", "add", "--", str(relative)])
        diff = run(["git", "diff", "--cached", "--quiet", "--", str(relative)], check=False)
        committed = False
        if diff.returncode == 0:
            pass
        elif diff.returncode == 1:
            run(["git", "commit", "-m", f"status: publish tent snapshot {generated_at}", "--", str(relative)])
            committed = True
        else:
            raise StatusPublishError("git could not inspect the staged status change")
        if _status_only_push_range(run, remote, branch, relative):
            run(["git", "push", remote, branch])
    except subprocess.CalledProcessError as error:
        detail = (error.stderr or error.stdout or str(error)).strip()
        raise StatusPublishError(f"git publication failed: {detail}") from error
    return committed


def publish_once(
    site_path: Path,
    grows_path: Path,
    output_path: Path,
    ha_url: str,
    access_credential: str | None,
    timeout: float,
    *,
    git_publish: bool = False,
) -> dict[str, Any]:
    config = load_site(site_path)
    grows = load_grows(grows_path)
    status = build_status(config, grows, ha_url, access_credential, timeout)
    atomic_write(output_path, render_status(status))
    if git_publish:
        repo = site_path.resolve().parents[1]
        publish_git(repo, output_path, config, status["generated_at"])
    return status


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--site", type=Path, default=REPO / "config" / "site.yaml")
    parser.add_argument("--grows", type=Path, default=REPO / "state" / "grows.yaml")
    parser.add_argument("--output", type=Path, default=REPO / "status" / "tent.yaml")
    parser.add_argument("--ha-url", default=os.environ.get("HA_URL"), help="HA base URL (or HA_URL)")
    parser.add_argument("--timeout", type=float, default=10, help="per-request timeout seconds")
    parser.add_argument(
        "--git-publish", action="store_true",
        help="after the atomic write, commit the status path and push site.bridge.branch",
    )
    args = parser.parse_args(argv)
    if not args.ha_url:
        parser.error("--ha-url or HA_URL is required")
    try:
        status = publish_once(
            args.site,
            args.grows,
            args.output,
            args.ha_url,
            os.environ.get("HA_ACCESS_TOKEN"),
            args.timeout,
            git_publish=args.git_publish,
        )
    except (OSError, SiteConfigError, StatusPublishError, yaml.YAMLError) as error:
        print(f"status publish failed: {error}", file=sys.stderr)
        return 1
    print(f"wrote schema v{status['schema_version']} status at {status['generated_at']} to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
