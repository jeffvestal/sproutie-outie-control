import importlib.util
import unittest
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "capture_ha_helper_states", REPO / "scripts" / "capture_ha_helper_states.py"
)
capture = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(capture)


class CaptureHaHelperStatesTests(unittest.TestCase):
    def test_keeps_only_input_helper_values(self):
        result = capture.helper_states(
            [
                {"entity_id": "input_boolean.production_mode", "state": "on", "attributes": {"friendly_name": "Production"}},
                {"entity_id": "input_datetime.lights_on_time", "state": "18:00:00"},
                {"entity_id": "switch.top_shelf_lights", "state": "off"},
                {"entity_id": "input_text.slot_a1_data"},
            ]
        )
        self.assertEqual(
            result,
            {
                "input_boolean.production_mode": "on",
                "input_datetime.lights_on_time": "18:00:00",
            },
        )


if __name__ == "__main__":
    unittest.main()
