import json
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from intel_gpu_top_gui import config  # noqa: E402
from intel_gpu_top_gui.config import DEFAULTS, Config  # noqa: E402


class ConfigTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = tmp.name
        self.path = os.path.join(self.dir, "intel-gpu-top-gui", "settings.json")
        p = mock.patch.object(config.GLib, "get_user_config_dir", return_value=self.dir)
        p.start()
        self.addCleanup(p.stop)

    def _write(self, text):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with open(self.path, "w") as fh:
            fh.write(text)

    def test_defaults_when_missing(self):
        c = Config()
        self.assertEqual(dict(c), DEFAULTS)
        self.assertEqual(c.path, self.path)

    def test_defaults_not_mutated(self):
        c = Config()
        c["interval_ms"] = 5
        self.assertEqual(DEFAULTS["interval_ms"], 1000)

    def test_corrupt_or_non_object_file(self):
        for text in ("{not json", "[1, 2]", ""):
            self._write(text)
            self.assertEqual(dict(Config()), DEFAULTS, text)

    def test_loads_valid_and_ignores_unknown_or_mistyped_keys(self):
        self._write(json.dumps({
            "interval_ms": 500,
            "history_s": "600",      # wrong type
            "device": "pci:card=1",
            "elevate": True,
            "bogus": 1,
        }))
        c = Config()
        self.assertEqual(c["interval_ms"], 500)
        self.assertEqual(c["history_s"], DEFAULTS["history_s"])
        self.assertEqual(c["device"], "pci:card=1")
        self.assertIs(c["elevate"], True)
        self.assertNotIn("bogus", c)

    def test_save_round_trip(self):
        c = Config()
        c["history_s"] = 300
        c["elevate"] = True
        c.save()
        self.assertFalse(os.path.exists(self.path + ".tmp"))
        c2 = Config()
        self.assertEqual(c2["history_s"], 300)
        self.assertIs(c2["elevate"], True)

    def test_save_failure_is_silent(self):
        c = Config()
        c.path = os.path.join(self.dir, "file", "settings.json")
        open(os.path.join(self.dir, "file"), "w").close()  # parent is a file
        c.save()  # must not raise


if __name__ == "__main__":
    unittest.main()
