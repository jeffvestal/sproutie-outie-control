import importlib.util
import tempfile
import unittest
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("archive_ha_config", REPO / "scripts" / "archive_ha_config.py")
archive_ha_config = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(archive_ha_config)


class ArchiveHaConfigTests(unittest.TestCase):
    def test_scrubs_json_yaml_and_sensitive_files(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "raw"
            destination = Path(directory) / "archive"
            (source / ".storage").mkdir(parents=True)
            (source / "configuration.yaml").write_text("eufy:\n  password: leaked\n  username: owner@example.com\n")
            (source / ".storage" / "core.config_entries").write_text(
                '{"data":{"access_token":"abc","host":"ha.local","stream_url":"rtsp://camera:password@ha.local/live"}}'
            )
            (source / ".storage" / "auth").write_text("must not be copied")
            (source / "secrets.yaml").write_text("must not be copied")
            (source / "home-assistant_v2.db").write_text("state data")

            copied, skipped = archive_ha_config.copy_scrubbed(source, destination)

            self.assertEqual(copied, 2)
            self.assertEqual(skipped, 3)
            self.assertIn("password: <redacted>", (destination / "configuration.yaml").read_text())
            self.assertIn("username: <redacted>", (destination / "configuration.yaml").read_text())
            entries = (destination / ".storage" / "core.config_entries").read_text()
            self.assertIn('"access_token": "<redacted>"', entries)
            self.assertIn('"host": "ha.local"', entries)
            self.assertIn('"stream_url": "rtsp://<redacted>@ha.local/live"', entries)
            self.assertFalse((destination / ".storage" / "auth").exists())
            self.assertFalse((destination / "secrets.yaml").exists())
            self.assertFalse((destination / "home-assistant_v2.db").exists())


if __name__ == "__main__":
    unittest.main()
