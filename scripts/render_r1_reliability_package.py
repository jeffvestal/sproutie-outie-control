#!/usr/bin/env python3
"""Render the issue #8 Home Assistant reliability configuration from config/site.yaml."""

from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


SAFE_SNAPSHOT_PATH = re.compile(r"^/[A-Za-z0-9_./-]+$")


def slug(value: str) -> str:
    return value.replace("-", "_")


def cooldown_entity(key: str) -> str:
    return f"input_datetime.r1_last_alert_{key.removeprefix('r1_')}"


def active_entity(key: str) -> str:
    return f"input_boolean.r1_alert_active_{key.removeprefix('r1_')}"


def visible_entity(key: str) -> str:
    return f"input_boolean.r1_alert_visible_{key.removeprefix('r1_')}"


def snapshot_mtime_entity(camera_role: str) -> str:
    return f"sensor.r1_{slug(camera_role)}_snapshot_mtime"


@dataclass(frozen=True)
class Fault:
    key: str
    sensor: str
    name: str
    state_template: list[str]
    delay_on_s: int | None
    title: str
    message: str

    @property
    def cooldown_entity(self) -> str:
        return cooldown_entity(self.key)

    @property
    def active_entity(self) -> str:
        return active_entity(self.key)

    @property
    def visible_entity(self) -> str:
        return visible_entity(self.key)


def load_contract(site_path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    with site_path.open(encoding="utf-8") as source:
        payload = yaml.safe_load(source)
    site = payload["site"]
    active = next(zone for zone in site["zones"].values() if zone.get("enabled", True))
    return site, active


def build_faults(zone: dict[str, Any]) -> list[Fault]:
    watchdogs = zone["fallback"]["watchdogs"]
    devices = zone["ha"]["devices"]
    telemetry = zone["ha"]["telemetry"]
    cameras = zone["ha"]["cameras"]
    photo_cadence_s = int(zone["fallback"]["photo_cadence_s"])
    camera_stale_s = photo_cadence_s * int(watchdogs["camera_stale_multiplier"])
    faults: list[Fault] = []

    for role, device in devices.items():
        label = role.replace("_", " ")
        switch = device["switch"]
        power = device["power"]
        faults.append(
            Fault(
                key=f"r1_watchdog_switch_{role}",
                sensor=f"binary_sensor.r1_watchdog_switch_{role}",
                name=f"R1 watchdog switch {label}",
                state_template=[f"{{{{ states('{switch}') not in ['on', 'off'] }}}}"],
                delay_on_s=int(watchdogs["switch_unavailable_s"]),
                title=f"R1 switch watchdog · {label}",
                message=(
                    f"{label} expects {switch}, but the entity is missing, unknown, or unavailable "
                    f"for {int(watchdogs['switch_unavailable_s']) // 60} minutes. This is an "
                    "integration/entity-ID failure."
                ),
            )
        )
        faults.append(
            Fault(
                key=f"r1_watchdog_power_{role}",
                sensor=f"binary_sensor.r1_watchdog_power_{role}",
                name=f"R1 watchdog power {label}",
                state_template=[f"{{{{ states('{power}') | float(none) is none }}}}"],
                delay_on_s=int(watchdogs["power_invalid_s"]),
                title=f"R1 power watchdog · {label}",
                message=(
                    f"{label} power telemetry {power} has reported N/A, unavailable, or another "
                    f"non-numeric value for {int(watchdogs['power_invalid_s']) // 60} minutes."
                ),
            )
        )

    for kind, entity in (("temperature", telemetry["temp_f"]), ("humidity", telemetry["rh"])):
        faults.append(
            Fault(
                key=f"r1_watchdog_climate_{kind}_silent",
                sensor=f"binary_sensor.r1_watchdog_climate_{kind}_silent",
                name=f"R1 watchdog climate {kind} silent",
                state_template=[f"{{{{ states('{entity}') | float(none) is none }}}}"],
                delay_on_s=int(watchdogs["climate_silence_s"]),
                title=f"R1 Govee watchdog · {kind} silent",
                message=(
                    f"Govee tent {kind} {entity} has been missing or non-numeric for "
                    f"{int(watchdogs['climate_silence_s']) // 60} minutes."
                ),
            )
        )
        faults.append(
            Fault(
                key=f"r1_watchdog_climate_{kind}_frozen",
                sensor=f"binary_sensor.r1_watchdog_climate_{kind}_frozen",
                name=f"R1 watchdog climate {kind} frozen",
                state_template=[
                    f"{{% set source = expand('{entity}') | first | default(none) %}}",
                    "{{ source is not none and source.state | float(none) is not none and",
                    "   as_timestamp(now()) - as_timestamp(source.last_changed, 0) > "
                    f"{int(watchdogs['frozen_value_s'])} }}}}",
                ],
                delay_on_s=None,
                title=f"R1 Govee watchdog · {kind} frozen",
                message=(
                    f"Govee tent {kind} {entity} has reported exactly the same value for more "
                    f"than {int(watchdogs['frozen_value_s']) // 3600} hours."
                ),
            )
        )

    for camera_role, camera in cameras.items():
        camera_slug = slug(camera_role)
        entity = camera["entity"]
        mtime_entity = snapshot_mtime_entity(camera_role)
        faults.append(
            Fault(
                key=f"r1_watchdog_camera_{camera_slug}_stale",
                sensor=f"binary_sensor.r1_watchdog_camera_{camera_slug}_stale",
                name=f"R1 watchdog camera {camera_role} stale",
                state_template=[
                    f"{{% set modified = states('{mtime_entity}') | int(0) %}}",
                    "{{ modified <= 0 or",
                    f"   as_timestamp(now()) - modified > {camera_stale_s} }}}}",
                ],
                delay_on_s=None,
                title=f"R1 camera watchdog · {camera_role}",
                message=(
                    f"{camera_role} ({entity}) has no `_latest.jpg` modification within "
                    f"{camera_stale_s // 60} minutes (2× the configured photo interval)."
                ),
            )
        )
    return faults


def _append_template_sensor(output: list[str], fault: Fault, indent: str = "      ") -> None:
    output.extend(
        [
            f"{indent}- name: {fault.name}",
            f"{indent}  default_entity_id: {fault.sensor}",
            f"{indent}  unique_id: {fault.sensor.removeprefix('binary_sensor.')}",
            f"{indent}  device_class: problem",
            f"{indent}  state: >-",
            *[f"{indent}    {line}" for line in fault.state_template],
        ]
    )
    if fault.delay_on_s is not None:
        output.extend([f"{indent}  delay_on:", f"{indent}    seconds: {fault.delay_on_s}"])


def render(site: dict[str, Any], zone: dict[str, Any]) -> str:
    alerts = site["alerts"]
    watchdogs = zone["fallback"]["watchdogs"]
    devices = zone["ha"]["devices"]
    cameras = zone["ha"]["cameras"]
    faults = build_faults(zone)
    phone = alerts["ha_notify_service"]
    cooldown_s = int(alerts["cooldown_s"])
    reconcile_s = int(watchdogs["reconcile_interval_s"])
    if reconcile_s % 60:
        raise ValueError("HA time-pattern reconciliation must be a whole number of minutes")

    command_keys = [f"r1_command_{role}" for role in devices]
    alert_keys = [fault.key for fault in faults] + command_keys
    immediate_faults = [fault for fault in faults if fault.delay_on_s is not None]
    periodic_faults = [fault for fault in faults if fault.delay_on_s is None]
    verified_entities = [f"input_boolean.r1_{role}_verified" for role in devices]
    fault_entities = [fault.sensor for fault in faults]

    output = [
        "# Generated by scripts/render_r1_reliability_package.py from config/site.yaml. Do not edit.",
        "",
        "input_boolean:",
    ]
    for role in devices:
        output.extend(
            [
                f"  r1_{role}_verified:",
                f"    name: R1 {role.replace('_', ' ')} verified",
                "    icon: mdi:check-decagram-outline",
            ]
        )
    for key in alert_keys:
        for entity, icon in (
            (active_entity(key), "mdi:alert-circle-check-outline"),
            (visible_entity(key), "mdi:message-alert-outline"),
        ):
            helper = entity.removeprefix("input_boolean.")
            output.extend(
                [
                    f"  {helper}:",
                    f"    name: {helper.replace('_', ' ')}",
                    f"    icon: {icon}",
                    *(["    initial: false"] if entity == visible_entity(key) else []),
                ]
            )

    output.extend(["", "input_datetime:"])
    for key in alert_keys:
        helper = cooldown_entity(key).removeprefix("input_datetime.")
        output.extend(
            [
                f"  {helper}:",
                f"    name: {helper.replace('_', ' ')}",
                "    has_date: true",
                "    has_time: true",
            ]
        )

    output.extend(["", "command_line:"])
    for camera_role, camera in cameras.items():
        latest_path = camera["latest_snapshot_path"]
        if not SAFE_SNAPSHOT_PATH.fullmatch(latest_path):
            raise ValueError(f"unsafe latest_snapshot_path for {camera_role}: {latest_path!r}")
        mtime_entity = snapshot_mtime_entity(camera_role)
        output.extend(
            [
                "  - sensor:",
                f"      name: R1 {camera_role} snapshot mtime",
                f"      unique_id: {mtime_entity.removeprefix('sensor.')}",
                f"      command: 'if [ -f {latest_path} ]; then stat -c %Y {latest_path}; else echo 0; fi'",
                f"      scan_interval: {reconcile_s}",
                '      value_template: "{{ value | int(0) }}"',
            ]
        )

    output.extend(["", "template:", "  - binary_sensor:"])
    for fault in immediate_faults:
        _append_template_sensor(output, fault)
    output.extend(
        [
            "  - triggers:",
            "      - trigger: homeassistant",
            "        event: start",
            "      - trigger: time_pattern",
            f'        minutes: "/{reconcile_s // 60}"',
            "    binary_sensor:",
        ]
    )
    for fault in periodic_faults:
        _append_template_sensor(output, fault)

    output.extend(
        [
            "",
            "script:",
            "  r1_raise_alert:",
            "    alias: R1 raise keyed reliability alert",
            "    mode: queued",
            "    max: 50",
            "    fields:",
            "      key: {required: true}",
            "      cooldown_entity: {required: true}",
            "      active_entity: {required: true}",
            "      visible_entity: {required: true}",
            "      title: {required: true}",
            "      message: {required: true}",
            "    sequence:",
            "      - condition: template",
            "        value_template: >-",
            "          {{ is_state(visible_entity, 'off') and",
            "             as_timestamp(now()) - as_timestamp(states(cooldown_entity), 0) >= "
            f"{cooldown_s} }}}}",
            "      - action: persistent_notification.create",
            "        continue_on_error: true",
            "        data:",
            "          notification_id: \"{{ key }}\"",
            "          title: \"{{ title }}\"",
            "          message: \"{{ message }}\"",
            "      - action: input_datetime.set_datetime",
            "        continue_on_error: true",
            "        target:",
            "          entity_id: \"{{ cooldown_entity }}\"",
            "        data:",
            "          timestamp: \"{{ now().timestamp() }}\"",
            "      - action: input_boolean.turn_on",
            "        continue_on_error: true",
            "        target:",
            "          entity_id: \"{{ active_entity }}\"",
            "      - action: input_boolean.turn_on",
            "        continue_on_error: true",
            "        target:",
            "          entity_id: \"{{ visible_entity }}\"",
            f"      - action: {phone}",
            "        continue_on_error: true",
            "        data:",
            "          title: \"{{ title }}\"",
            "          message: \"{{ message }}\"",
            "          data:",
            "            tag: \"{{ key }}\"",
            "            group: r1_reliability",
            "",
            "  r1_resolve_alert:",
            "    alias: R1 resolve keyed reliability alert",
            "    mode: queued",
            "    max: 50",
            "    fields:",
            "      key: {required: true}",
            "      active_entity: {required: true}",
            "      visible_entity: {required: true}",
            "      title: {required: true}",
            "      message: {required: true}",
            "    sequence:",
            "      - condition: template",
            "        value_template: \"{{ is_state(active_entity, 'on') }}\"",
            "      - action: input_boolean.turn_off",
            "        target:",
            "          entity_id: \"{{ active_entity }}\"",
            "      - action: input_boolean.turn_off",
            "        continue_on_error: true",
            "        target:",
            "          entity_id: \"{{ visible_entity }}\"",
            "      - action: persistent_notification.dismiss",
            "        continue_on_error: true",
            "        data:",
            "          notification_id: \"{{ key }}\"",
            f"      - action: {phone}",
            "        continue_on_error: true",
            "        data:",
            "          title: \"{{ title }}\"",
            "          message: \"{{ message }}\"",
            "          data:",
            "            tag: \"{{ key }}\"",
            "            group: r1_reliability",
            "",
            "automation:",
            "  - id: r1_persistent_alert_dismissed",
            "    alias: R1 track dismissed keyed reliability alerts",
            "    mode: queued",
            "    max: 50",
            "    triggers:",
            "      - trigger: persistent_notification",
            "        update_type: removed",
            "    actions:",
            "      - choose:",
        ]
    )
    for key in alert_keys:
        output.extend(
            [
                f"          - conditions: \"{{{{ trigger.notification.notification_id == '{key}' }}}}\"",
                "            sequence:",
                "              - action: input_boolean.turn_off",
                "                target:",
                f"                  entity_id: {visible_entity(key)}",
            ]
        )
    output.extend(
        [
            "",
            "  - id: r1_reliability_alert_reconcile",
            "    alias: R1 reconcile keyed reliability alerts",
            "    mode: single",
            "    triggers:",
            "      - trigger: time_pattern",
            f'        minutes: "/{reconcile_s // 60}"',
            "      - trigger: state",
            "        entity_id:",
            *[f"          - {entity}" for entity in fault_entities],
            "    actions:",
            "      - repeat:",
            "          for_each:",
        ]
    )
    for fault in faults:
        output.extend(
            [
                f"            - key: {fault.key}",
                f"              sensor: {fault.sensor}",
                f"              cooldown_entity: {fault.cooldown_entity}",
                f"              active_entity: {fault.active_entity}",
                f"              visible_entity: {fault.visible_entity}",
                f"              title: \"{fault.title}\"",
                "              message: >-",
                f"                {fault.message}",
            ]
        )
    output.extend(
        [
            "          sequence:",
            "            - choose:",
            "                - conditions: \"{{ is_state(repeat.item.sensor, 'on') }}\"",
            "                  sequence:",
            "                    - action: script.r1_raise_alert",
            "                      data:",
            "                        key: \"{{ repeat.item.key }}\"",
            "                        cooldown_entity: \"{{ repeat.item.cooldown_entity }}\"",
            "                        active_entity: \"{{ repeat.item.active_entity }}\"",
            "                        visible_entity: \"{{ repeat.item.visible_entity }}\"",
            "                        title: \"{{ repeat.item.title }}\"",
            "                        message: \"{{ repeat.item.message }}\"",
            "                - conditions: \"{{ is_state(repeat.item.sensor, 'off') }}\"",
            "                  sequence:",
            "                    - action: script.r1_resolve_alert",
            "                      data:",
            "                        key: \"{{ repeat.item.key }}\"",
            "                        active_entity: \"{{ repeat.item.active_entity }}\"",
            "                        visible_entity: \"{{ repeat.item.visible_entity }}\"",
            "                        title: \"R1 watchdog resolved\"",
            "                        message: \"{{ repeat.item.title }} has cleared.\"",
            "",
            "  - id: r1_daily_reliability_heartbeat",
            "    alias: R1 daily reliability heartbeat",
            "    mode: single",
            "    triggers:",
            "      - trigger: time",
            f"        at: \"{alerts['daily_heartbeat_at']}\"",
            "    actions:",
            f"      - action: {phone}",
            "        continue_on_error: true",
            "        data:",
            "          title: R1 daily tent heartbeat",
            "          message: >-",
            "            {% set verified_entities = " + repr(verified_entities) + " %}",
            "            {% set fault_entities = " + repr(fault_entities) + " %}",
            "            {% set fault_objects = expand(fault_entities) | list %}",
            "            {% set verified = expand(verified_entities) | selectattr('state', 'eq', 'on') | list | count %}",
            "            {% set faults = fault_objects | selectattr('state', 'eq', 'on') | list | count %}",
            "            {% set healthy = fault_objects | selectattr('state', 'eq', 'off') | list | count %}",
            f"            {{% set unknown = {len(fault_entities)} - healthy - faults %}}",
            f"            {{% if verified == {len(verified_entities)} and healthy == {len(fault_entities)} %}}",
            f"              Tent nominal, {len(verified_entities)}/{len(verified_entities)} devices verified.",
            "            {% else %}",
            f"              Tent attention required: {{{{ verified }}}}/{len(verified_entities)} devices verified; {{{{ faults }}}} watchdog fault(s) active; {{{{ unknown }}}} watchdog signal(s) unknown, unavailable, or missing.",
            "            {% endif %}",
            "          data:",
            "            tag: r1_daily_heartbeat",
            "            group: r1_reliability",
            "",
        ]
    )
    return "\n".join(output)


def render_safety(site: dict[str, Any], zone: dict[str, Any]) -> str:
    devices = zone["ha"]["devices"]
    required = ("top_lights", "bottom_lights", "exhaust")
    missing = [role for role in required if role not in devices]
    if missing:
        raise ValueError(f"thermal safety roles missing from site contract: {missing}")
    phone = site["alerts"]["ha_notify_service"]
    return "\n".join(
        [
            "# Generated by scripts/render_r1_reliability_package.py from config/site.yaml. Do not edit.",
            "",
            "r1_apply_thermal_safety:",
            "  alias: R1 apply thermal safety",
            "  mode: single",
            "  max_exceeded: silent",
            "  sequence:",
            "    # This background run owns the complete initial-command-plus-one-retry",
            "    # lifecycle. mode: single rejects unsafe retriggers until it finishes.",
            "    - action: input_boolean.turn_off",
            "      continue_on_error: true",
            "      target:",
            "        entity_id:",
            "          - input_boolean.r1_top_lights_verified",
            "          - input_boolean.r1_bottom_lights_verified",
            "          - input_boolean.r1_exhaust_verified",
            "    - action: switch.turn_off",
            "      continue_on_error: true",
            "      target:",
            "        entity_id:",
            f"          - {devices['top_lights']['switch']}",
            f"          - {devices['bottom_lights']['switch']}",
            "    - action: switch.turn_on",
            "      continue_on_error: true",
            "      target:",
            f"        entity_id: {devices['exhaust']['switch']}",
            "    - action: script.r1_set_top_lights",
            '      data: {desired: "off", initial_command_sent: true}',
            "    - action: script.r1_set_bottom_lights",
            '      data: {desired: "off", initial_command_sent: true}',
            "    - action: script.r1_set_exhaust",
            '      data: {desired: "on", initial_command_sent: true}',
            "",
            "r1_notify_safety:",
            "  alias: R1 safety notification",
            "  mode: queued",
            "  fields:",
            "    title: {required: true}",
            "    message: {required: true}",
            "  sequence:",
            "    - action: persistent_notification.create",
            "      data:",
            '        title: "{{ title }}"',
            '        message: "{{ message }}"',
            f"    - action: {phone}",
            "      data:",
            '        title: "{{ title }}"',
            '        message: "{{ message }}"',
            "",
        ]
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--site", type=Path, default=Path("config/site.yaml"))
    parser.add_argument("--output", type=Path, default=Path("ha/packages/r1_reliability.yaml"))
    parser.add_argument("--safety-output", type=Path, default=Path("ha/scripts/10_safety.yaml"))
    args = parser.parse_args()
    site, zone = load_contract(args.site)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.safety_output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(render(site, zone), encoding="utf-8")
    args.safety_output.write_text(render_safety(site, zone), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
