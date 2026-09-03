import ast
import copy
import importlib.util
import re
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

import yaml


REPO = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "publish_tent_status", REPO / "scripts" / "publish_tent_status.py"
)
publish_tent_status = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.path.insert(0, str(REPO / "scripts"))
sys.modules[SPEC.name] = publish_tent_status
SPEC.loader.exec_module(publish_tent_status)


StateResult = publish_tent_status.StateResult
FIXED_NOW = datetime(2026, 9, 1, 2, 3, 4, tzinfo=timezone.utc)


def sample_config():
    return {
        "schema_version": 1,
        "site": {
            "status_dir": "status",
            "state_dir": "state",
            "bridge": {"remote": "origin", "branch": "main"},
            "zones": {
                "tent-1": {
                    "label": "Tent 1 · Test",
                    "enabled": True,
                    "status": {
                        "env_bands": {
                            "temp_f": [65, 75],
                            "rh": [50, 70],
                            "vpd_kpa": [0.8, 1.2],
                        }
                    },
                    "fallback": {
                        "photo_cadence_s": 3600,
                        "device_verification": {
                            "settle_s": 60,
                            "poll_timeout_s": 120,
                            "off_threshold_w": 0.5,
                        },
                    },
                    "ha": {
                        "devices": {
                            "top_lights": {
                                "switch": "switch.test_top_lights",
                                "power": "sensor.test_top_lights_power",
                                "expected_watts_on": [28, 32],
                            },
                            "exhaust": {
                                "switch": "switch.test_exhaust",
                                "power": "sensor.test_exhaust_power",
                                "expected_watts_on": [23, 29],
                            },
                        },
                        "telemetry": {
                            "temp_f": "sensor.test_temperature",
                            "rh": "sensor.test_humidity",
                        },
                        "cameras": {
                            "top-eyes": {
                                "entity": "camera.test_top_eyes",
                                "covers": ["rack-top"],
                            }
                        },
                    },
                    "layout": {
                        "racks": [
                            {"id": "rack-top", "label": "Rack Top", "slots": ["a1", "a2"]}
                        ],
                        "sidecars": [{"id": "sidecar-tf", "label": "Sidecar top front"}],
                    },
                },
                "tent-2-sim": {
                    "label": "Tent 2 · Simulation",
                    "enabled": False,
                    "fallback": {"photo_cadence_s": 1800},
                    "ha": {
                        "devices": {
                            "top_lights": {
                                "switch": "switch.test_sim_lights",
                                "power": "sensor.test_sim_lights_power",
                            }
                        },
                        "telemetry": {
                            "temp_f": "sensor.test_sim_temperature",
                            "rh": "sensor.test_sim_humidity",
                        },
                        "cameras": {
                            "top-eyes": {
                                "entity": "camera.test_sim_top_eyes",
                                "covers": ["rack-top"],
                            }
                        },
                    },
                    "layout": {
                        "racks": [{"id": "rack-top", "label": "Rack Top", "slots": ["a1"]}],
                        "sidecars": [],
                    },
                },
            },
        },
    }


class StateFeed:
    def __init__(self, values):
        self.values = {entity: list(results) for entity, results in values.items()}
        self.calls = []

    def __call__(self, ha_url, token, entity, timeout):
        self.calls.append((ha_url, token, entity, timeout))
        try:
            return self.values[entity].pop(0)
        except (KeyError, IndexError) as error:
            raise AssertionError(f"unexpected HA fetch: {entity}") from error


def available(value):
    return StateResult(True, True, str(value))


def unavailable(value="unavailable"):
    return StateResult(True, False, value)


def successful_feed(light_initial="on", light_final="on", light_watts="30.0"):
    return StateFeed(
        {
            "switch.test_top_lights": [available(light_initial), available(light_final), available(light_final)],
            "sensor.test_top_lights_power": [available(light_watts), available(light_watts)],
            "switch.test_exhaust": [available("off"), available("off"), available("off")],
            "sensor.test_exhaust_power": [available("0.1"), available("0.1")],
            "sensor.test_temperature": [available("80.0")],
            "sensor.test_humidity": [available("50.0")],
            "camera.test_top_eyes": [available("idle")],
        }
    )


class PublishTentStatusTests(unittest.TestCase):
    def build(self, feed=None, sleeps=None, now=FIXED_NOW):
        feed = feed or successful_feed()
        sleeps = sleeps if sleeps is not None else []
        with mock.patch.object(publish_tent_status, "fetch_state", side_effect=feed):
            status = publish_tent_status.build_status(
                sample_config(),
                [],
                "http://ha.test",
                "not-a-real-token",
                2,
                now=now,
                sleeper=sleeps.append,
            )
        return status, feed, sleeps

    def test_output_matches_frozen_contract_and_nat_decoder_shape(self):
        status, feed, sleeps = self.build()
        self.assertEqual(status["schema_version"], 1)
        self.assertEqual(status["generated_at"], "2026-09-01T02:03:04Z")
        self.assertEqual(set(status), {"schema_version", "generated_at", "brain", "zones"})
        self.assertEqual(sleeps, [60.0, 2.0])

        live = status["zones"]["tent-1"]
        self.assertEqual(
            set(live),
            {"label", "online", "env", "devices", "layout", "cameras", "alerts", "grows"},
        )
        self.assertTrue(live["online"])
        self.assertEqual(live["env"]["temp_f"], {"value": 80.0, "band": [65.0, 75.0], "status": "above"})
        self.assertEqual(live["env"]["rh"], {"value": 50.0, "band": [50.0, 70.0], "status": "in"})
        self.assertEqual(live["env"]["vpd_kpa"]["status"], "above")
        self.assertIsNone(live["env"]["outside"])
        self.assertEqual(live["devices"]["top_lights"], {"state": "on", "verified": True, "watts": 30.0})
        self.assertEqual(live["devices"]["exhaust"], {"state": "off", "verified": True, "watts": 0.1})
        self.assertEqual(live["alerts"], [])
        self.assertEqual(live["grows"], [])
        self.assertEqual(
            live["cameras"][0],
            {
                "id": "top-eyes",
                "label": "Top Eyes",
                "covers": ["rack-top"],
                "snapshot": None,
                "captured_at": None,
                "interval_s": 3600,
                "online": True,
                "stream": None,
            },
        )

        disabled = status["zones"]["tent-2-sim"]
        self.assertFalse(disabled["online"])
        self.assertEqual(disabled["devices"]["top_lights"], {"state": None, "verified": False, "watts": None})
        self.assertIsNone(disabled["env"]["temp_f"]["value"])

        rendered = publish_tent_status.render_status(status)
        self.assertNotIn("not-a-real-token", rendered)
        for _, _, entity, _ in feed.calls:
            self.assertNotIn(entity, rendered)
        # TentStatus.swift requires these three values and makes §2.1 nested fields nullable.
        decoded = yaml.safe_load(rendered)
        self.assertEqual(decoded["schema_version"], 1)
        self.assertIsNotNone(decoded["generated_at"])
        self.assertIsInstance(decoded["zones"], dict)

        with_snapshot = copy.deepcopy(status)
        with_snapshot["zones"]["tent-1"]["cameras"][0]["snapshot"] = "status/latest/top-eyes.jpg"
        with_snapshot["zones"]["tent-1"]["cameras"][0]["captured_at"] = "2026-09-01T02:00:00Z"
        publish_tent_status.validate_status(with_snapshot)
        publish_tent_status.assert_public_safe(with_snapshot)

    def test_changed_switch_is_never_verified_from_post_settle_power_alone(self):
        status, _, sleeps = self.build(successful_feed("on", "off", "0.0"))
        self.assertEqual(sleeps, [60.0, 2.0])
        self.assertEqual(
            status["zones"]["tent-1"]["devices"]["top_lights"],
            {"state": "off", "verified": False, "watts": 0.0},
        )

    def test_ha_unavailable_is_explicit_null_not_a_fabricated_zero(self):
        feed = StateFeed(
            {
                "switch.test_top_lights": [available("on"), unavailable()],
                "sensor.test_top_lights_power": [unavailable()],
                "switch.test_exhaust": [available("off"), available("off"), available("off")],
                "sensor.test_exhaust_power": [available("0.1"), available("0.1")],
                "sensor.test_temperature": [unavailable()],
                "sensor.test_humidity": [available("50")],
                "camera.test_top_eyes": [unavailable()],
            }
        )
        status, _, _ = self.build(feed)
        zone = status["zones"]["tent-1"]
        self.assertFalse(zone["online"])
        self.assertEqual(zone["devices"]["top_lights"], {"state": None, "verified": False, "watts": None})
        self.assertIsNone(zone["env"]["temp_f"]["value"])
        self.assertIsNone(zone["env"]["vpd_kpa"]["value"])
        self.assertFalse(zone["cameras"][0]["online"])

    def test_power_polling_waits_for_two_confirming_post_settle_samples(self):
        feed = StateFeed(
            {
                "switch.test_top_lights": [
                    available("on"), available("on"), available("on"), available("on")
                ],
                "sensor.test_top_lights_power": [
                    available("0.0"), available("29.5"), available("30.0")
                ],
                "switch.test_exhaust": [available("off"), available("off"), available("off")],
                "sensor.test_exhaust_power": [available("0.1"), available("0.1")],
                "sensor.test_temperature": [available("80.0")],
                "sensor.test_humidity": [available("50.0")],
                "camera.test_top_eyes": [available("idle")],
            }
        )
        status, _, sleeps = self.build(feed)
        self.assertEqual(sleeps, [60.0, 2.0, 2.0])
        self.assertEqual(
            status["zones"]["tent-1"]["devices"]["top_lights"],
            {"state": "on", "verified": True, "watts": 30.0},
        )

    def test_failed_ha_fetch_preserves_existing_file(self):
        config = sample_config()
        failed = StateResult(False, False, None, "HTTP 500")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            site = root / "config" / "site.yaml"
            grows = root / "state" / "grows.yaml"
            output = root / "status" / "tent.yaml"
            site.parent.mkdir()
            grows.parent.mkdir()
            output.parent.mkdir()
            site.write_text(yaml.safe_dump(config), encoding="utf-8")
            grows.write_text("[]\n", encoding="utf-8")
            output.write_text("last-good\n", encoding="utf-8")
            with mock.patch.object(publish_tent_status, "fetch_state", return_value=failed):
                with self.assertRaisesRegex(publish_tent_status.StatusPublishError, "HA fetch failed"):
                    publish_tent_status.publish_once(
                        site, grows, output, "http://ha.test", None, 1
                    )
            self.assertEqual(output.read_text(encoding="utf-8"), "last-good\n")

    def test_generated_at_rewrites_an_otherwise_equal_snapshot(self):
        first, _, _ = self.build(now=datetime(2026, 9, 1, 2, 0, tzinfo=timezone.utc))
        second, _, _ = self.build(now=datetime(2026, 9, 1, 2, 5, tzinfo=timezone.utc))
        first["brain"]["uptime_s"] = 0
        second["brain"]["uptime_s"] = 0
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "status" / "tent.yaml"
            publish_tent_status.atomic_write(output, publish_tent_status.render_status(first))
            before = output.read_text(encoding="utf-8")
            publish_tent_status.atomic_write(output, publish_tent_status.render_status(second))
            after = output.read_text(encoding="utf-8")
        self.assertNotEqual(before, after)
        self.assertIn("2026-09-01T02:05:00Z", after)

    def test_public_safety_rejects_urls_addresses_entities_and_credentials(self):
        status, _, _ = self.build()
        unsafe_values = (
            "http://private.example/camera",
            "192.168.1.232",
            "sensor.hidden_temperature",
            "checked sensor.hidden_temperature during inspection",
            "Bearer definitely-secret",
        )
        for unsafe in unsafe_values:
            with self.subTest(unsafe=unsafe):
                candidate = copy.deepcopy(status)
                candidate["brain"]["version"] = unsafe
                with self.assertRaises(publish_tent_status.StatusPublishError):
                    publish_tent_status.assert_public_safe(candidate)

        entity_key = copy.deepcopy(status)
        device = entity_key["zones"]["tent-1"]["devices"].pop("top_lights")
        entity_key["zones"]["tent-1"]["devices"]["switch.hidden_relay"] = device
        with self.assertRaisesRegex(publish_tent_status.StatusPublishError, "role key"):
            publish_tent_status.validate_status(entity_key)
        with self.assertRaisesRegex(publish_tent_status.StatusPublishError, "entity identifier"):
            publish_tent_status.assert_public_safe(entity_key)

    def test_schema_validation_rejects_missing_or_unknown_fields(self):
        status, _, _ = self.build()
        missing = copy.deepcopy(status)
        missing["zones"]["tent-1"]["devices"]["top_lights"].pop("verified")
        with self.assertRaisesRegex(publish_tent_status.StatusPublishError, "verified"):
            publish_tent_status.validate_status(missing)
        unknown = copy.deepcopy(status)
        unknown["zones"]["tent-1"]["lan_host"] = "hidden"
        with self.assertRaisesRegex(publish_tent_status.StatusPublishError, "outside §2.1"):
            publish_tent_status.validate_status(unknown)

    def test_grows_are_empty_or_contract_records_never_invented(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "grows.yaml"
            path.write_text("[]\n", encoding="utf-8")
            self.assertEqual(publish_tent_status.load_grows(path), [])
            path.write_text("- id: grow-1\n  token: do-not-publish\n", encoding="utf-8")
            with self.assertRaisesRegex(publish_tent_status.StatusPublishError, "outside §2.1"):
                publish_tent_status.load_grows(path)

    def test_hand_maintained_grow_is_copied_without_plant_arithmetic(self):
        source = """\
- id: grow-20260215-peppermint-sidecar-tf
  crop: peppermint
  recipe: peppermint@1.0.0
  owner: null
  tracking: milestone
  slots: [sidecar-tf]
  sown_at: 2026-02-15T12:00:00Z
  phase: established
  phase_index: null
  phases: null
  day: 195
  expected_days: null
  eta: null
  gdd: null
  coverage: null
  weight: null
  photo: status/latest/peppermint.jpg
  last_event: null
"""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "grows.yaml"
            path.write_text(source, encoding="utf-8")
            grows = publish_tent_status.load_grows(path)
        with mock.patch.object(
            publish_tent_status, "fetch_state", side_effect=successful_feed()
        ):
            status = publish_tent_status.build_status(
                sample_config(),
                grows,
                "http://ha.test",
                None,
                1,
                now=FIXED_NOW,
                sleeper=lambda _: None,
            )
        published = status["zones"]["tent-1"]["grows"]
        self.assertEqual(len(published), 1)
        self.assertEqual(published[0]["day"], 195)
        self.assertEqual(published[0]["sown_at"], "2026-02-15T12:00:00Z")
        self.assertEqual(published[0]["photo"], "status/latest/peppermint.jpg")
        self.assertEqual(set(published[0]), publish_tent_status.GROW_KEYS)
        publish_tent_status.assert_public_safe(status)

    def test_script_has_no_hard_coded_ha_entity_identifier(self):
        source = (REPO / "scripts" / "publish_tent_status.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        entity_id = re.compile(r"\b(?:switch|sensor|camera)\.[a-z0-9_]+", re.IGNORECASE)
        string_literals = [
            node.value for node in ast.walk(tree) if isinstance(node, ast.Constant) and isinstance(node.value, str)
        ]
        self.assertFalse([value for value in string_literals if entity_id.search(value)])

    def test_real_site_resolves_every_enabled_device_by_role(self):
        config = publish_tent_status.load_site(REPO / "config" / "site.yaml")
        zone = config["site"]["zones"]["tent-1"]
        values = {}
        for device in zone["ha"]["devices"].values():
            values[device["switch"]] = [available("on"), available("on"), available("on")]
            values[device["power"]] = [
                available(device["measured_watts_on"]), available(device["measured_watts_on"])
            ]
        values[zone["ha"]["telemetry"]["temp_f"]] = [available("72.4")]
        values[zone["ha"]["telemetry"]["rh"]] = [available("61.2")]
        for camera in zone["ha"]["cameras"].values():
            values[camera["entity"]] = [available("idle")]
        feed = StateFeed(values)
        sleeps = []
        with mock.patch.object(publish_tent_status, "fetch_state", side_effect=feed):
            status = publish_tent_status.build_status(
                config,
                [],
                "http://ha.test",
                None,
                1,
                now=FIXED_NOW,
                sleeper=sleeps.append,
            )
        output_devices = status["zones"]["tent-1"]["devices"]
        self.assertEqual(set(output_devices), set(zone["ha"]["devices"]))
        self.assertTrue(all(device["verified"] for device in output_devices.values()))
        self.assertEqual(sleeps, [60.0, 2.0])
        rendered = publish_tent_status.render_status(status)
        for device in zone["ha"]["devices"].values():
            self.assertNotIn(device["switch"], rendered)
            self.assertNotIn(device["power"], rendered)

    def test_git_publication_is_only_called_when_explicitly_enabled(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            site = root / "config" / "site.yaml"
            grows = root / "state" / "grows.yaml"
            output = root / "status" / "tent.yaml"
            site.parent.mkdir()
            grows.parent.mkdir()
            site.write_text("placeholder", encoding="utf-8")
            grows.write_text("[]\n", encoding="utf-8")
            status, _, _ = self.build()
            with mock.patch.object(publish_tent_status, "load_site", return_value=sample_config()), \
                 mock.patch.object(publish_tent_status, "load_grows", return_value=[]), \
                 mock.patch.object(publish_tent_status, "build_status", return_value=status), \
                 mock.patch.object(publish_tent_status, "atomic_write"), \
                 mock.patch.object(publish_tent_status, "publish_git") as git_publish:
                publish_tent_status.publish_once(site, grows, output, "http://ha.test", None, 1)
                git_publish.assert_not_called()
                publish_tent_status.publish_once(
                    site, grows, output, "http://ha.test", None, 1, git_publish=True
                )
                git_publish.assert_called_once()

    def test_git_publication_drains_only_a_status_only_commit_backlog(self):
        commands = []

        def fake_run(args, **kwargs):
            commands.append(args)
            if args[:3] == ["git", "branch", "--show-current"]:
                return subprocess.CompletedProcess(args, 0, stdout="main\n", stderr="")
            if args[:4] == ["git", "diff", "--cached", "--quiet"]:
                return subprocess.CompletedProcess(args, 0, stdout="", stderr="")
            if args[:3] == ["git", "rev-parse", "--verify"]:
                return subprocess.CompletedProcess(args, 0, stdout="abc\n", stderr="")
            if args[:3] == ["git", "rev-list", "--reverse"]:
                return subprocess.CompletedProcess(args, 0, stdout="abc\n", stderr="")
            if args[:2] == ["git", "diff-tree"]:
                return subprocess.CompletedProcess(args, 0, stdout="status/tent.yaml\n", stderr="")
            return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "status" / "tent.yaml"
            with mock.patch.object(publish_tent_status.subprocess, "run", side_effect=fake_run):
                committed = publish_tent_status.publish_git(
                    root,
                    output,
                    sample_config(),
                    "2026-09-01T02:03:04Z",
                )
        self.assertFalse(committed)
        self.assertIn(["git", "push", "origin", "main"], commands)

    def test_git_publication_rejects_an_unrelated_pending_commit(self):
        commands = []

        def fake_run(args, **kwargs):
            commands.append(args)
            if args[:3] == ["git", "branch", "--show-current"]:
                return subprocess.CompletedProcess(args, 0, stdout="main\n", stderr="")
            if args[:4] == ["git", "diff", "--cached", "--quiet"]:
                return subprocess.CompletedProcess(args, 0, stdout="", stderr="")
            if args[:3] == ["git", "rev-parse", "--verify"]:
                return subprocess.CompletedProcess(args, 0, stdout="abc\n", stderr="")
            if args[:3] == ["git", "rev-list", "--reverse"]:
                return subprocess.CompletedProcess(args, 0, stdout="abc\n", stderr="")
            if args[:2] == ["git", "diff-tree"]:
                return subprocess.CompletedProcess(args, 0, stdout="unrelated.txt\n", stderr="")
            return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "status" / "tent.yaml"
            with mock.patch.object(publish_tent_status.subprocess, "run", side_effect=fake_run):
                with self.assertRaisesRegex(
                    publish_tent_status.StatusPublishError, "not limited to status/tent.yaml"
                ):
                    publish_tent_status.publish_git(
                        root,
                        output,
                        sample_config(),
                        "2026-09-01T02:03:04Z",
                    )
        self.assertNotIn(["git", "push", "origin", "main"], commands)


if __name__ == "__main__":
    unittest.main()
