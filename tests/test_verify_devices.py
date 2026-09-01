import importlib.util
import json
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("verify_devices", REPO / "scripts" / "verify_devices.py")
verify_devices = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = verify_devices
SPEC.loader.exec_module(verify_devices)


class StateHandler(BaseHTTPRequestHandler):
    states = {
        "switch.top_shelf_lights": "on",
        "sensor.top_shelf_lights_current_consumption": "20.0",
        "switch.bottom_shelf_lights": "off",
        "sensor.bottom_shelf_lights_current_consumption": "3.1",
        "switch.top_shelf_fan": "on",
        "sensor.top_shelf_fan_current_consumption": "0.0",
        "switch.bottom_shelf_fan": "off",
        "sensor.bottom_shelf_fan_current_consumption": "0.0",
        "switch.exhaust_fan": "on",
        "sensor.exhaust_fan_current_consumption": "41.2",
        "switch.camera_flash": "off",
        "sensor.camera_flash_current_consumption": "0.0",
    }

    def do_GET(self):
        entity_id = self.path.removeprefix("/api/states/")
        if entity_id not in self.states:
            self.send_response(404)
            self.end_headers()
            return
        body = json.dumps({"entity_id": entity_id, "state": self.states[entity_id]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_):
        pass


class VerifyDevicesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), StateHandler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.ha_url = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.thread.join()

    def test_site_parses_and_live_zone_resolves(self):
        config = verify_devices.load_site(REPO / "config" / "site.yaml")
        devices = config["site"]["zones"]["tent-1"]["ha"]["devices"]
        self.assertEqual(devices["top_lights"]["power"], "sensor.exhaust_fan_current_consumption")
        self.assertEqual(devices["bottom_lights"]["power"], "sensor.bottom_shelf_fan_current_consumption")
        self.assertEqual(devices["top_fan"]["power"], "sensor.bottom_shelf_lights_current_consumption")
        self.assertEqual(devices["bottom_fan"]["power"], "sensor.top_shelf_fan_current_consumption")
        self.assertEqual(devices["exhaust"]["power"], "sensor.top_shelf_lights_current_consumption")
        reports, required_zones_online = verify_devices.verify_site(config, self.ha_url, None, 1)
        self.assertTrue(reports[0]["online"])
        self.assertFalse(reports[1]["online"])
        self.assertTrue(required_zones_online)
        self.assertEqual(reports[0]["roles"][0]["watts"], "41.2")
        self.assertTrue(reports[0]["roles"][0]["power_exists"])
        self.assertEqual(reports[0]["roles"][0]["switch_state"], "on")
        self.assertFalse(reports[1]["roles"][0]["power_available"])

    def test_disabled_simulated_zone_does_not_mask_an_enabled_zone_failure(self):
        original = StateHandler.states["sensor.exhaust_fan_current_consumption"]
        StateHandler.states["sensor.exhaust_fan_current_consumption"] = "unavailable"
        try:
            self.assertEqual(verify_devices.main(["--site", str(REPO / "config" / "site.yaml"), "--ha-url", self.ha_url]), 1)
        finally:
            StateHandler.states["sensor.exhaust_fan_current_consumption"] = original

    def test_non_finite_power_is_not_reporting(self):
        for value in ("NaN", "inf", "-Infinity"):
            with self.subTest(value=value):
                state = verify_devices.StateResult(True, True, value)
                self.assertFalse(verify_devices.is_numeric_power(state))

    def test_invalid_device_config_is_rejected(self):
        with self.assertRaises(verify_devices.SiteConfigError):
            verify_devices.load_site(REPO / "tests" / "fixtures" / "invalid-site.yaml")

    def test_malformed_ha_mapping_is_rejected(self):
        with self.assertRaises(verify_devices.SiteConfigError):
            verify_devices.load_site(REPO / "tests" / "fixtures" / "malformed-ha-site.yaml")


if __name__ == "__main__":
    unittest.main()
