import contextlib
import io
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from intel_gpu_top_gui import app  # noqa: E402


class CommandLineTest(unittest.TestCase):
    def _main(self, argv):
        err = io.StringIO()
        with mock.patch.object(app, "Application") as cls, \
             contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
            try:
                app.main(argv)
            except SystemExit as exc:
                return cls, exc.code, err.getvalue()
        return cls, None, err.getvalue()

    def test_interval_too_small(self):
        cls, code, err = self._main(["-s", "50"])
        self.assertEqual(code, 2)
        self.assertIn("at least 100 ms", err)
        cls.assert_not_called()

    def test_parses_options(self):
        with mock.patch.object(app.GLib, "set_prgname"), \
             mock.patch.object(app.GLib, "set_application_name"), \
             mock.patch.object(app.GLib, "unix_signal_add"):
            cls, code, _ = self._main(["--demo", "--pkexec", "-s", "250", "-d", "pci:card=1"])
        self.assertIsNone(code)
        args = cls.call_args.args[0]
        self.assertTrue(args.demo and args.pkexec)
        self.assertEqual((args.interval, args.device), (250, "pci:card=1"))
        cls.return_value.run.assert_called_once()

    def test_version(self):
        _, code, _ = self._main(["--version"])
        self.assertEqual(code, 0)


if __name__ == "__main__":
    unittest.main()
