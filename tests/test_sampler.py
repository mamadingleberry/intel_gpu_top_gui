import os
import stat
import subprocess
import sys
import tempfile
import textwrap
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from intel_gpu_top_gui import sampler  # noqa: E402
from intel_gpu_top_gui.sampler import JsonStreamParser, Sampler, list_devices  # noqa: E402


class ParserEdgeCasesTest(unittest.TestCase):
    def test_object_split_across_feeds(self):
        p = JsonStreamParser()
        self.assertEqual(p.feed('[\n{"a": {"b": '), [])
        self.assertEqual(p.feed('1}}'), [{"a": {"b": 1}}])

    def test_non_dict_values_are_dropped(self):
        self.assertEqual(JsonStreamParser().feed('[1, "x", {"a": 1}, null]'), [{"a": 1}])

    def test_garbage_without_any_object_is_discarded(self):
        p = JsonStreamParser()
        self.assertEqual(p.feed("no json here"), [])
        self.assertEqual(p.feed('{"a": 1}'), [{"a": 1}])

    def test_garbage_between_objects(self):
        self.assertEqual(JsonStreamParser().feed('{"a": 1} oops {"a": 2}'),
                         [{"a": 1}, {"a": 2}])

    def test_braces_inside_strings(self):
        self.assertEqual(JsonStreamParser().feed('{"name": "}{,["}'),
                         [{"name": "}{,["}])

    def test_unicode(self):
        self.assertEqual(JsonStreamParser().feed('{"name": "Résumé ✓"}'),
                         [{"name": "Résumé ✓"}])


L_OUTPUT = """\
card1                    Intel Alderlake_p (Gen12)         pci:vendor=8086,device=46A3,card=0
└─renderD128
card0                    Intel Dg2 (Gen12)                 pci:vendor=8086,device=56A0,card=1
cardX without filter
"""


class ListDevicesTest(unittest.TestCase):
    def test_parses_intel_gpu_top_L(self):
        res = subprocess.CompletedProcess([], 0, stdout=L_OUTPUT, stderr="")
        with mock.patch.object(sampler, "intel_gpu_top_path", return_value="/x"), \
             mock.patch.object(sampler.subprocess, "run", return_value=res) as run:
            devs = list_devices()
        run.assert_called_once()
        self.assertEqual(run.call_args.args[0], ["/x", "-L"])
        self.assertEqual(devs, [
            ("pci:vendor=8086,device=46A3,card=0", "card1 Intel Alderlake_p (Gen12)"),
            ("pci:vendor=8086,device=56A0,card=1", "card0 Intel Dg2 (Gen12)"),
        ])

    def test_not_installed(self):
        with mock.patch.object(sampler, "intel_gpu_top_path", return_value=None):
            self.assertEqual(list_devices(), [])

    def test_errors_give_empty_list(self):
        for exc in (OSError("boom"), subprocess.TimeoutExpired("x", 5)):
            with mock.patch.object(sampler, "intel_gpu_top_path", return_value="/x"), \
                 mock.patch.object(sampler.subprocess, "run", side_effect=exc):
                self.assertEqual(list_devices(), [])


def _sync_idle_add(fn, *args):
    """Stand-in for GLib.idle_add that runs the callback immediately."""
    fn(*args)
    return 0


class SamplerCommandTest(unittest.TestCase):
    def _start(self, **kw):
        s = Sampler(mock.Mock(), mock.Mock())
        with mock.patch.object(sampler, "intel_gpu_top_path", return_value="/bin/igt"), \
             mock.patch.object(sampler.subprocess, "Popen") as popen, \
             mock.patch.object(sampler.threading, "Thread"):
            s.start(**kw)
        return popen.call_args.args[0]

    def test_plain(self):
        self.assertEqual(self._start(interval_ms=500), ["/bin/igt", "-J", "-s", "500"])

    def test_device_and_elevate(self):
        self.assertEqual(
            self._start(interval_ms=1000.7, device="pci:card=1", elevate=True),
            ["pkexec", "/bin/igt", "-J", "-s", "1000", "-d", "pci:card=1"])

    def test_missing_binary_reports_exit_127(self):
        on_exit = mock.Mock()
        s = Sampler(mock.Mock(), on_exit)
        with mock.patch.object(sampler, "intel_gpu_top_path", return_value=None), \
             mock.patch.object(sampler.GLib, "idle_add", side_effect=_sync_idle_add):
            s.start()
        rc, msg, count = on_exit.call_args.args
        self.assertEqual((rc, count), (127, 0))
        self.assertIn("intel-gpu-tools", msg)
        self.assertFalse(s.running)

    def test_popen_failure_reports_exit_127(self):
        on_exit = mock.Mock()
        s = Sampler(mock.Mock(), on_exit)
        with mock.patch.object(sampler, "intel_gpu_top_path", return_value="/bin/igt"), \
             mock.patch.object(sampler.subprocess, "Popen", side_effect=OSError("denied")), \
             mock.patch.object(sampler.GLib, "idle_add", side_effect=_sync_idle_add):
            s.start()
        on_exit.assert_called_once_with(127, "denied", 0)


class SamplerProcessTest(unittest.TestCase):
    """Runs a fake intel_gpu_top script through the real reader thread."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        patcher = mock.patch.object(sampler.GLib, "idle_add", side_effect=_sync_idle_add)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _fake(self, body: str) -> str:
        path = os.path.join(self.tmp.name, "intel_gpu_top")
        with open(path, "w") as fh:
            fh.write(f"#!{sys.executable}\n" + textwrap.dedent(body))
        os.chmod(path, os.stat(path).st_mode | stat.S_IXUSR)
        return path

    def _run(self, exe):
        samples, exits = [], []
        s = Sampler(samples.append, lambda *a: exits.append(a))
        with mock.patch.object(sampler, "intel_gpu_top_path", return_value=exe):
            s.start(interval_ms=100)
            s._thread.join(timeout=10)
        self.assertFalse(s.running)
        return samples, exits

    def test_samples_then_exit(self):
        exe = self._fake("""
            import sys
            sys.stdout.write('[\\n{"rc6": {"value": 1}},\\n')
            sys.stdout.flush()
            sys.stdout.write('{"rc6": {"value": 2}},\\n')
            sys.stderr.write("bye\\n")
            sys.exit(3)
        """)
        samples, exits = self._run(exe)
        self.assertEqual([x["rc6"]["value"] for x in samples], [1, 2])
        self.assertEqual(exits, [(3, "bye\n", 2)])

    def test_permission_failure_without_samples(self):
        exe = self._fake("""
            import sys
            sys.stderr.write("get_num_gts: Assertion failed\\n")
            sys.exit(134)
        """)
        samples, exits = self._run(exe)
        self.assertEqual(samples, [])
        self.assertEqual(exits, [(134, "get_num_gts: Assertion failed\n", 0)])

    def test_stop_suppresses_callbacks(self):
        exe = self._fake("""
            import sys, time
            while True:
                sys.stdout.write('{"rc6": {"value": 1}},\\n')
                sys.stdout.flush()
                time.sleep(0.02)
        """)
        samples, exits = [], []
        s = Sampler(samples.append, lambda *a: exits.append(a))
        with mock.patch.object(sampler, "intel_gpu_top_path", return_value=exe):
            s.start(interval_ms=100)
            thread = s._thread
            s.stop()
            thread.join(timeout=10)
            n = len(samples)
        self.assertFalse(thread.is_alive())
        self.assertEqual(exits, [])
        self.assertEqual(len(samples), n)


class DemoTest(unittest.TestCase):
    def test_demo_produces_well_formed_samples(self):
        from intel_gpu_top_gui.history import flatten_sample

        samples = []
        s = Sampler(None, mock.Mock())

        def on_sample(sample):
            samples.append(sample)
            if len(samples) >= 3:
                s.stop()

        s._on_sample = on_sample
        with mock.patch.object(sampler.GLib, "idle_add", side_effect=_sync_idle_add), \
             mock.patch.object(sampler.time, "sleep"):
            s.start(interval_ms=100, demo=True)
            s._thread.join(timeout=10)
        self.assertEqual(len(samples), 3)
        groups = flatten_sample(samples[0])
        for g in ("engines", "frequency", "power", "rc6", "imc-bandwidth", "interrupts"):
            self.assertIn(g, groups)
        for v in groups["engines"][1].values():
            self.assertTrue(0 <= v <= 100)
        self.assertEqual(len(samples[0]["clients"]), 3)


if __name__ == "__main__":
    unittest.main()
