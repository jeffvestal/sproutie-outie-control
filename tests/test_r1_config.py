import importlib.util
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import yaml


REPO = Path(__file__).resolve().parents[1]


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


renderer = load_module("render_r1_role_scripts", REPO / "scripts" / "render_r1_role_scripts.py")
scanner = load_module("secret_scan", REPO / "scripts" / "secret_scan.py")
deployer = load_module("deploy_r1_config", REPO / "scripts" / "deploy_r1_config.py")


class HAConfigLoader(yaml.SafeLoader):
    """Parse HA's include tags as scalar placeholders for syntax-only tests."""


def construct_ha_tag(loader, tag_suffix, node):
    return loader.construct_scalar(node)


HAConfigLoader.add_multi_constructor("!", construct_ha_tag)


class R1ConfigTests(unittest.TestCase):
    def test_all_r1_yaml_files_parse(self):
        for path in (REPO / "ha").rglob("*.yaml"):
            with self.subTest(path=path):
                yaml.load(path.read_text(encoding="utf-8"), Loader=HAConfigLoader)

    def test_role_scripts_are_current_with_site_contract(self):
        devices = renderer.load_devices(REPO / "config" / "site.yaml")
        expected = renderer.render(devices)
        actual = (REPO / "ha" / "scripts" / "20_device_roles.yaml").read_text(encoding="utf-8")
        self.assertEqual(actual, expected)

    def test_role_scripts_keep_the_verified_power_mapping(self):
        scripts = (REPO / "ha" / "scripts" / "20_device_roles.yaml").read_text(encoding="utf-8")
        self.assertIn('options: ["on", "off"]', scripts)
        self.assertIn("sensor.exhaust_fan_current_consumption", scripts)
        self.assertIn("sensor.bottom_shelf_fan_current_consumption", scripts)
        self.assertIn("sensor.bottom_shelf_lights_current_consumption", scripts)
        self.assertIn("sensor.top_shelf_fan_current_consumption", scripts)
        self.assertIn("sensor.top_shelf_lights_current_consumption", scripts)
        self.assertIn("23 <= watts <= 29", scripts)

    def test_secret_scan_rejects_inline_credential(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bad.yaml"
            path.write_text("password: definitely-not-a-secret-placeholder\n", encoding="utf-8")
            self.assertEqual(scanner.main([str(path)]), 1)

    def test_secret_scan_accepts_r1_source(self):
        self.assertEqual(scanner.main([str(REPO / "ha")]), 0)

    def test_deployer_dry_run_is_local_only(self):
        self.assertEqual(deployer.main([]), 0)

    def test_deployer_creates_an_empty_active_secrets_file(self):
        source = (REPO / "scripts" / "deploy_r1_config.py").read_text(encoding="utf-8")
        self.assertIn("secrets.yaml && chmod 600", source)

    def test_deployer_replaces_all_top_level_includes(self):
        source = (REPO / "scripts" / "deploy_r1_config.py").read_text(encoding="utf-8")
        self.assertIn('"template.yaml"', source)

    def test_deployer_treats_core_validation_errors_as_a_stop(self):
        source = (REPO / "scripts" / "deploy_r1_config.py").read_text(encoding="utf-8")
        self.assertIn('if "ERROR:" in report:', source)

    def test_deployer_waits_for_core_before_post_activation_check(self):
        source = (REPO / "scripts" / "deploy_r1_config.py").read_text(encoding="utf-8")
        self.assertIn("Home Assistant did not become ready after Core restart", source)

    def test_sensor_fault_test_mode_is_wired_to_the_thermal_guard(self):
        automations = (REPO / "ha" / "automations.yaml").read_text(encoding="utf-8")
        self.assertIn("input_boolean.r1_sensor_fault_test_mode", automations)

    def test_schedule_control_center_exposes_all_fallback_settings(self):
        dashboard = (REPO / "ha" / "dashboards" / "r1.yaml").read_text(encoding="utf-8")
        self.assertIn("Schedule Control Center", dashboard)
        self.assertIn("input_number.r1_exhaust_cycle_minutes", dashboard)

    def test_exhaust_controller_supports_humidity_and_or_logic(self):
        automations = (REPO / "ha" / "automations.yaml").read_text(encoding="utf-8")
        dashboard = (REPO / "ha" / "dashboards" / "r1.yaml").read_text(encoding="utf-8")

        self.assertIn("binary_sensor.r1_tent_humidity_high", automations)
        self.assertIn("Both (cycle AND humidity)", automations)
        self.assertIn("input_select.r1_exhaust_trigger_logic", dashboard)
        self.assertIn("input_number.r1_exhaust_humidity_threshold", dashboard)


if __name__ == "__main__":
    unittest.main()
