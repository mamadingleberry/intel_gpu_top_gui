"""Runs ``intel_gpu_top -J`` and turns its JSON stream into Python dicts.

intel_gpu_top writes one JSON object per refresh period, wrapped in a never
terminated JSON array::

    [
    { "period": {...}, "engines": {...}, ... },
    { ... },

so the output is never valid JSON as a whole.  :class:`JsonStreamParser`
decodes the objects one by one as they arrive.
"""

from __future__ import annotations

import json
import math
import os
import random
import shutil
import signal
import subprocess
import threading
import time
from typing import Callable, Optional

from gi.repository import GLib

INTEL_GPU_TOP = "intel_gpu_top"


class JsonStreamParser:
    """Incrementally decode a stream of concatenated JSON values."""

    _SEPARATORS = " \t\r\n,[]"

    def __init__(self) -> None:
        self._buf = ""
        self._decoder = json.JSONDecoder()

    def feed(self, text: str) -> list:
        self._buf += text
        out = []
        while True:
            # Drop array punctuation / whitespace between objects.
            i = 0
            n = len(self._buf)
            while i < n and self._buf[i] in self._SEPARATORS:
                i += 1
            self._buf = self._buf[i:]
            if not self._buf:
                break
            try:
                obj, end = self._decoder.raw_decode(self._buf)
            except json.JSONDecodeError:
                # Incomplete object; wait for more data.  If the buffer
                # starts with garbage that can never decode, skip to the
                # next '{' so that we do not stall forever.
                if self._buf[0] != "{":
                    nxt = self._buf.find("{")
                    self._buf = self._buf[nxt:] if nxt >= 0 else ""
                    continue
                break
            self._buf = self._buf[end:]
            if isinstance(obj, dict):
                out.append(obj)
        return out


def intel_gpu_top_path() -> Optional[str]:
    return shutil.which(INTEL_GPU_TOP)


def list_devices() -> list[tuple[str, str]]:
    """Return ``[(filter, description), ...]`` from ``intel_gpu_top -L``."""
    exe = intel_gpu_top_path()
    if not exe:
        return []
    try:
        res = subprocess.run([exe, "-L"], capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        return []
    devices = []
    for line in res.stdout.splitlines():
        if not line.startswith("card"):
            continue
        parts = line.split()
        flt = next((p for p in parts if ":" in p and "=" in p), None)
        if not flt:
            continue
        desc = line.replace(flt, "").strip()
        desc = " ".join(desc.split())
        devices.append((flt, desc))
    return devices


class Sampler:
    """Owns the intel_gpu_top child process.

    Callbacks are always invoked on the GLib main loop:

    * ``on_sample(dict)`` for every decoded sample
    * ``on_exit(returncode, stderr_text, sample_count)`` when the process ends
      (not called when the process is stopped via :meth:`stop`)
    """

    def __init__(
        self,
        on_sample: Callable[[dict], None],
        on_exit: Callable[[int, str, int], None],
    ) -> None:
        self._on_sample = on_sample
        self._on_exit = on_exit
        self._proc: Optional[subprocess.Popen] = None
        self._thread: Optional[threading.Thread] = None
        self._generation = 0
        self._stopping = False

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(
        self,
        interval_ms: int = 1000,
        device: Optional[str] = None,
        elevate: bool = False,
        demo: bool = False,
    ) -> None:
        self.stop()
        self._generation += 1
        gen = self._generation
        self._stopping = False

        if demo:
            target = self._run_demo
            args = (gen, interval_ms)
        else:
            exe = intel_gpu_top_path()
            if exe is None:
                GLib.idle_add(
                    self._on_exit, 127,
                    "intel_gpu_top was not found. Install the "
                    "'intel-gpu-tools' package.", 0,
                )
                return
            cmd = [exe, "-J", "-s", str(int(interval_ms))]
            if device:
                cmd += ["-d", device]
            if elevate:
                cmd = ["pkexec", *cmd]
            try:
                self._proc = subprocess.Popen(
                    cmd,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    # Own session so Ctrl+C in a terminal does not hit it twice.
                    start_new_session=True,
                )
            except OSError as exc:
                GLib.idle_add(self._on_exit, 127, str(exc), 0)
                return
            target = self._run_process
            args = (gen, self._proc)

        self._thread = threading.Thread(target=target, args=args, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stopping = True
        self._generation += 1
        proc, self._proc = self._proc, None
        if proc is None:
            return
        # The reader thread notices the generation change after its next
        # read and closes the pipe, so intel_gpu_top dies of SIGPIPE on its
        # following write.  That matters when it runs as root via pkexec,
        # where we are not allowed to signal it.  (Closing the fd from here
        # would race with the blocked os.read() in the reader thread.)
        try:
            proc.send_signal(signal.SIGTERM)
        except (PermissionError, ProcessLookupError, OSError):
            pass

    # -- worker threads ---------------------------------------------------

    def _deliver(self, gen: int, sample: dict) -> bool:
        if gen == self._generation:
            self._on_sample(sample)
        return False

    def _finish(self, gen: int, rc: int, err: str, count: int) -> bool:
        if gen == self._generation and not self._stopping:
            self._on_exit(rc, err, count)
        return False

    def _run_process(self, gen: int, proc: subprocess.Popen) -> None:
        parser = JsonStreamParser()
        count = 0
        err_chunks: list[bytes] = []

        def read_stderr() -> None:
            try:
                for chunk in iter(lambda: proc.stderr.read1(4096), b""):
                    err_chunks.append(chunk)
            except (ValueError, OSError):
                pass
            finally:
                proc.stderr.close()

        err_thread = threading.Thread(target=read_stderr, daemon=True)
        err_thread.start()
        fd = proc.stdout.fileno()
        try:
            while True:
                data = os.read(fd, 65536)
                if not data or gen != self._generation:
                    break
                for sample in parser.feed(data.decode("utf-8", "replace")):
                    count += 1
                    GLib.idle_add(self._deliver, gen, sample)
        except (ValueError, OSError):
            pass
        proc.stdout.close()
        if gen != self._generation:
            # Stopped; do not wait for a process we may not be able to kill.
            threading.Thread(target=proc.wait, daemon=True).start()
            return
        try:
            rc = proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            rc = -1
        err_thread.join(timeout=1)
        err = b"".join(err_chunks).decode("utf-8", "replace")
        GLib.idle_add(self._finish, gen, rc, err, count)

    def _run_demo(self, gen: int, interval_ms: int) -> None:
        """Synthetic data in intel_gpu_top's format, for trying the UI."""
        t0 = time.monotonic()
        dt = interval_ms / 1000.0
        rnd = random.Random(1)
        clients = {
            "1": ("gnome-shell", "2190"),
            "2": ("firefox", "4410"),
            "3": ("ffmpeg", "9120"),
        }
        while gen == self._generation:
            t = time.monotonic() - t0
            render = max(0.0, 35 + 30 * math.sin(t / 7) + rnd.uniform(-8, 8))
            video = max(0.0, 50 + 45 * math.sin(t / 13 + 1)) if (t // 20) % 2 else 0.0
            blit = max(0.0, rnd.uniform(0, 6))
            ve = video * 0.4
            busy = max(render, video)
            req = 300 + busy * 11
            sample = {
                "period": {"duration": interval_ms, "unit": "ms"},
                "frequency": {"requested": req, "actual": req * rnd.uniform(0.85, 1.0), "unit": "MHz"},
                "interrupts": {"count": busy * 12 + rnd.uniform(0, 40), "unit": "irq/s"},
                "rc6": {"value": max(0.0, 100 - busy * 1.1), "unit": "%"},
                "power": {"GPU": 0.3 + busy * 0.09, "Package": 3.0 + busy * 0.18, "unit": "W"},
                "imc-bandwidth": {"reads": 800 + busy * 40, "writes": 200 + busy * 15, "unit": "MiB/s"},
                "engines": {
                    "Render/3D": {"busy": min(render, 100), "sema": 0.0, "wait": 0.0, "unit": "%"},
                    "Blitter": {"busy": blit, "sema": 0.0, "wait": 0.0, "unit": "%"},
                    "Video": {"busy": min(video, 100), "sema": 0.0, "wait": 0.0, "unit": "%"},
                    "VideoEnhance": {"busy": ve, "sema": 0.0, "wait": 0.0, "unit": "%"},
                },
                "clients": {
                    cid: {
                        "name": name,
                        "pid": pid,
                        "engine-classes": {
                            "Render/3D": {"busy": f"{render * share:.2f}", "unit": "%"},
                            "Blitter": {"busy": f"{blit * share:.2f}", "unit": "%"},
                            "Video": {"busy": f"{(video if name == 'ffmpeg' else 0):.2f}", "unit": "%"},
                            "VideoEnhance": {"busy": f"{(ve if name == 'ffmpeg' else 0):.2f}", "unit": "%"},
                        },
                    }
                    for (cid, (name, pid)), share in zip(clients.items(), (0.2, 0.7, 0.1))
                },
            }
            GLib.idle_add(self._deliver, gen, sample)
            time.sleep(dt)
