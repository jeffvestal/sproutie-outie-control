import importlib.util
import sys
import unittest
from pathlib import Path

import yaml
from jinja2 import Environment


REPO = Path(__file__).resolve().parents[1]


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


role_renderer = load_module(
    "issue8_role_renderer", REPO / "scripts" / "render_r1_role_scripts.py"
)
reliability_renderer = load_module(
    "issue8_reliability_renderer", REPO / "scripts" / "render_r1_reliability_package.py"
)


class R1ReliabilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.site, cls.zone = reliability_renderer.load_contract(REPO / "config" / "site.yaml")
        cls.devices = cls.zone["ha"]["devices"]
        cls.cameras = cls.zone["ha"]["cameras"]
        cls.watchdogs = cls.zone["fallback"]["watchdogs"]
        cls.faults = reliability_renderer.build_faults(cls.zone)
        cls.package_text = (REPO / "ha" / "packages" / "r1_reliability.yaml").read_text(
            encoding="utf-8"
        )
        cls.package = yaml.safe_load(cls.package_text)
        cls.roles_text = (REPO / "ha" / "scripts" / "20_device_roles.yaml").read_text(
            encoding="utf-8"
        )
        cls.roles = yaml.safe_load(cls.roles_text)
        cls.safety_text = (REPO / "ha" / "scripts" / "10_safety.yaml").read_text(
            encoding="utf-8"
        )
        cls.safety = yaml.safe_load(cls.safety_text)

    def test_reliability_package_is_current_with_site_contract(self):
        expected = reliability_renderer.render(self.site, self.zone)
        self.assertEqual(self.package_text, expected)

    def test_thresholds_and_routes_are_canonical(self):
        self.assertEqual(
            self.watchdogs,
            {
                "switch_unavailable_s": 300,
                "power_invalid_s": 600,
                "climate_silence_s": 900,
                "frozen_value_s": 7200,
                "camera_stale_multiplier": 2,
                "reconcile_interval_s": 60,
            },
        )
        self.assertEqual(self.site["alerts"]["cooldown_s"], 1800)
        self.assertEqual(
            self.site["alerts"]["ha_notify_service"],
            "notify.mobile_app_sergeant_bosco",
        )
        self.assertIn("seconds: 300", self.package_text)
        self.assertIn("seconds: 600", self.package_text)
        self.assertIn("seconds: 900", self.package_text)
        self.assertIn("> 7200", self.package_text)
        self.assertIn("> 7200 }}", self.package_text)

    def test_every_device_has_switch_and_power_watchdogs(self):
        by_key = {fault.key: fault for fault in self.faults}
        for role, device in self.devices.items():
            with self.subTest(role=role):
                switch_fault = by_key[f"r1_watchdog_switch_{role}"]
                power_fault = by_key[f"r1_watchdog_power_{role}"]
                self.assertEqual(switch_fault.delay_on_s, 300)
                self.assertEqual(power_fault.delay_on_s, 600)
                self.assertIn(device["switch"], switch_fault.message)
                self.assertIn(device["power"], power_fault.message)
                self.assertIn("integration/entity-ID failure", switch_fault.message)

    def test_govee_silent_and_frozen_watchdogs_cover_temp_and_rh(self):
        keys = {fault.key for fault in self.faults}
        for kind in ("temperature", "humidity"):
            self.assertIn(f"r1_watchdog_climate_{kind}_silent", keys)
            self.assertIn(f"r1_watchdog_climate_{kind}_frozen", keys)
        self.assertIn("source.last_changed", self.package_text)
        self.assertIn("exactly the same value for more than 2 hours", self.package_text)

    def test_camera_age_reads_actual_latest_file_mtime_at_twice_cadence(self):
        camera_stale_s = (
            self.zone["fallback"]["photo_cadence_s"]
            * self.watchdogs["camera_stale_multiplier"]
        )
        self.assertEqual(camera_stale_s, 7200)
        command_sensors = self.package["command_line"]
        for camera_role, camera in self.cameras.items():
            camera_slug = reliability_renderer.slug(camera_role)
            with self.subTest(camera=camera_role):
                mtime_entity = reliability_renderer.snapshot_mtime_entity(camera_role)
                self.assertIn(camera["entity"], self.package_text)
                self.assertIn(camera["latest_snapshot_path"], self.package_text)
                self.assertIn(mtime_entity, self.package_text)
                self.assertTrue(
                    any(
                        camera["latest_snapshot_path"] in item["sensor"]["command"]
                        for item in command_sensors
                    )
                )
                self.assertIn(
                    f"binary_sensor.r1_watchdog_camera_{camera_slug}_stale", self.package_text
                )
        self.assertNotIn("r1_record_successful_snapshot", self.package["script"])
        self.assertNotIn("camera.top_eyes_snapshot.last_updated", self.package_text)

    def test_keyed_alerts_have_cooldown_phone_and_recovery(self):
        scripts = self.package["script"]
        raise_script = scripts["r1_raise_alert"]
        resolve_script = scripts["r1_resolve_alert"]
        self.assertIn("persistent_notification.", str(raise_script))
        self.assertIn(">= 1800", str(raise_script))
        self.assertIn("notify.mobile_app_sergeant_bosco", str(raise_script))
        self.assertIn("tag", str(raise_script))
        self.assertIn("persistent_notification.dismiss", str(resolve_script))
        self.assertIn("notify.mobile_app_sergeant_bosco", str(resolve_script))
        self.assertIn("is_state(active_entity, 'on')", str(resolve_script))
        self.assertIn("is_state(visible_entity, 'off')", str(raise_script))
        self.assertNotIn("states('persistent_notification.", str(raise_script))

        cooldown_helpers = self.package["input_datetime"]
        expected_keys = {fault.key for fault in self.faults}
        expected_keys.update(f"r1_command_{role}" for role in self.devices)
        for key in expected_keys:
            helper = f"r1_last_alert_{key.removeprefix('r1_')}"
            self.assertIn(helper, cooldown_helpers)
            active_helper = f"r1_alert_active_{key.removeprefix('r1_')}"
            self.assertIn(active_helper, self.package["input_boolean"])
            visible_helper = f"r1_alert_visible_{key.removeprefix('r1_')}"
            self.assertIn(visible_helper, self.package["input_boolean"])
            self.assertNotIn("initial", self.package["input_boolean"][active_helper])
            self.assertFalse(self.package["input_boolean"][visible_helper]["initial"])

    def test_dismissed_persistent_alert_still_has_a_recovery_marker(self):
        resolve = self.package["script"]["r1_resolve_alert"]["sequence"]
        self.assertIn("active_entity", str(resolve[0]))
        self.assertEqual(resolve[1]["action"], "input_boolean.turn_off")
        self.assertEqual(resolve[2]["action"], "input_boolean.turn_off")
        self.assertEqual(resolve[3]["action"], "persistent_notification.dismiss")
        self.assertEqual(resolve[4]["action"], "notify.mobile_app_sergeant_bosco")

        dismissal = next(
            item
            for item in self.package["automation"]
            if item["id"] == "r1_persistent_alert_dismissed"
        )
        self.assertEqual(
            dismissal["triggers"],
            [{"trigger": "persistent_notification", "update_type": "removed"}],
        )
        expected_keys = {fault.key for fault in self.faults}
        expected_keys.update(f"r1_command_{role}" for role in self.devices)
        choices = dismissal["actions"][0]["choose"]
        self.assertEqual(len(choices), len(expected_keys))
        for choice in choices:
            self.assertIn("trigger.notification.notification_id", choice["conditions"])
            self.assertIn("r1_alert_visible_", str(choice["sequence"]))

    def test_commands_retry_once_after_the_measured_settle_window(self):
        verification = self.zone["fallback"]["device_verification"]
        self.assertEqual(verification["attempts"], 2)
        self.assertEqual(verification["settle_s"], 60)
        self.assertEqual(verification["off_threshold_w"], 0.5)
        for role, device in self.devices.items():
            with self.subTest(role=role):
                command = self.roles[f"r1_set_{role}"]
                repeat = command["sequence"][2]["repeat"]
                command_step = repeat["sequence"][0]
                action = command_step["then"][0]
                self.assertEqual(action["action"], "switch.turn_{{ desired }}")
                self.assertTrue(action["continue_on_error"])
                self.assertEqual(action["target"]["entity_id"], device["switch"])
                self.assertEqual(repeat["sequence"][1]["delay"]["seconds"], 60)
                self.assertIn("initial_command_sent", str(command_step["if"]))
                self.assertIn("repeat.first", str(command_step["if"]))
                self.assertIn("repeat.index >= 2", str(repeat["until"]))
                self.assertIn(device["power"], str(repeat["until"]))
                self.assertIn(str(device["expected_watts_on"][0]), str(repeat["until"]))

    def test_commands_persist_verified_state_and_classify_failure(self):
        for role in self.devices:
            with self.subTest(role=role):
                text = str(self.roles[f"r1_set_{role}"])
                self.assertIn(f"input_boolean.r1_{role}_verified", text)
                self.assertIn(f"r1_command_{role}", text)
                self.assertIn(f"input_boolean.r1_alert_active_command_{role}", text)
                self.assertIn(f"input_boolean.r1_alert_visible_command_{role}", text)
                self.assertIn("integration/entity-ID failure", text)
                self.assertIn("physical/load failure", text)
                self.assertIn("power telemetry", text)

    def test_configured_switch_paths_are_verified_and_thermal_actuation_is_immediate(self):
        dashboard = (REPO / "ha" / "dashboards" / "r1.yaml").read_text(encoding="utf-8")
        automations = (REPO / "ha" / "automations.yaml").read_text(encoding="utf-8")
        self.assertNotIn("action: switch.", automations)
        self.assertNotIn("tap_action: {action: toggle}", dashboard)
        self.assertEqual(
            self.safety_text,
            reliability_renderer.render_safety(self.site, self.zone),
        )
        sequence = self.safety["r1_apply_thermal_safety"]["sequence"]
        marker_action = sequence[0]
        self.assertEqual(marker_action["action"], "input_boolean.turn_off")
        self.assertTrue(marker_action["continue_on_error"])
        self.assertEqual(
            marker_action["target"]["entity_id"],
            [
                "input_boolean.r1_top_lights_verified",
                "input_boolean.r1_bottom_lights_verified",
                "input_boolean.r1_exhaust_verified",
            ],
        )
        self.assertEqual(sequence[1]["action"], "switch.turn_off")
        self.assertEqual(
            sequence[1]["target"]["entity_id"],
            [
                self.devices["top_lights"]["switch"],
                self.devices["bottom_lights"]["switch"],
            ],
        )
        self.assertEqual(sequence[2]["action"], "switch.turn_on")
        self.assertEqual(
            sequence[2]["target"]["entity_id"], self.devices["exhaust"]["switch"]
        )
        self.assertEqual(
            [step["action"] for step in sequence[3:]],
            [
                "script.r1_set_top_lights",
                "script.r1_set_bottom_lights",
                "script.r1_set_exhaust",
            ],
        )
        self.assertEqual(self.safety_text.count("initial_command_sent: true"), 3)
        for role in self.devices:
            self.assertIn(f"r1_toggle_{role}", self.roles)
            self.assertIn(f"perform_action: script.r1_toggle_{role}", dashboard)

    def test_thermal_retrigger_does_not_restart_active_verification(self):
        automations = yaml.safe_load(
            (REPO / "ha" / "automations.yaml").read_text(encoding="utf-8")
        )
        thermal = next(
            item for item in automations if item["id"] == "r1_thermal_priority_latch"
        )
        unsafe_sequence = thermal["actions"][0]["choose"][0]["sequence"]
        launch_gate = unsafe_sequence[0]
        self.assertIn("start_safety_run", str(launch_gate["if"]))
        apply_action = launch_gate["then"][0]
        self.assertEqual(apply_action["action"], "script.turn_on")
        self.assertEqual(
            apply_action["target"]["entity_id"], "script.r1_apply_thermal_safety"
        )
        self.assertEqual(unsafe_sequence[1]["action"], "input_boolean.turn_on")
        self.assertEqual(
            unsafe_sequence[1]["target"]["entity_id"],
            "input_boolean.r1_thermal_latch",
        )
        apply_script = self.safety["r1_apply_thermal_safety"]
        self.assertEqual(apply_script["mode"], "single")
        self.assertEqual(apply_script["max_exceeded"], "silent")
        self.assertIn(
            "not is_state('input_boolean.r1_thermal_latch', 'on')",
            thermal["variables"]["start_safety_run"],
        )
        self.assertIn("trigger.id == 'startup'", thermal["variables"]["start_safety_run"])
        self.assertEqual(self.safety_text.count("action: switch.turn_off"), 1)
        self.assertEqual(self.safety_text.count("action: switch.turn_on"), 1)

        recovery_sequence = thermal["actions"][0]["choose"][1]["sequence"]
        cancel = recovery_sequence[0]
        self.assertEqual(cancel["action"], "script.turn_off")
        self.assertTrue(cancel["continue_on_error"])
        self.assertEqual(
            cancel["target"]["entity_id"],
            [
                "script.r1_apply_thermal_safety",
                "script.r1_set_top_lights",
                "script.r1_set_bottom_lights",
                "script.r1_set_exhaust",
            ],
        )
        self.assertEqual(recovery_sequence[1]["action"], "input_boolean.turn_off")

    def test_daily_heartbeat_is_nominal_only_at_six_of_six_and_no_faults(self):
        heartbeat = next(
            item
            for item in self.package["automation"]
            if item["id"] == "r1_daily_reliability_heartbeat"
        )
        text = str(heartbeat)
        self.assertIn("Tent nominal, 6/6 devices verified", text)
        self.assertIn(f"healthy == {len(self.faults)}", text)
        self.assertIn("Tent attention required", text)
        self.assertIn("unknown, unavailable, or missing", text)
        self.assertIn("notify.mobile_app_sergeant_bosco", text)
        self.assertIn("r1_daily_heartbeat", text)

    def test_generated_templates_are_syntactically_valid_jinja(self):
        environment = Environment()

        def walk(value):
            if isinstance(value, dict):
                for item in value.values():
                    walk(item)
            elif isinstance(value, list):
                for item in value:
                    walk(item)
            elif isinstance(value, str) and ("{{" in value or "{%" in value):
                environment.parse(value)

        walk(self.package)
        walk(self.roles)


if __name__ == "__main__":
    unittest.main()
