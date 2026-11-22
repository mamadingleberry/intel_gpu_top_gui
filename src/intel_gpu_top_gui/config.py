"""Tiny JSON settings store in $XDG_CONFIG_HOME/intel-gpu-top-gui/."""

from __future__ import annotations

import json
import os

from gi.repository import GLib

DEFAULTS = {
    "interval_ms": 1000,
    "history_s": 120,
    "device": "",        # intel_gpu_top -d filter; "" = first/auto
    "elevate": False,    # run intel_gpu_top through pkexec
}


class Config(dict):
    def __init__(self) -> None:
        super().__init__(DEFAULTS)
        self.path = os.path.join(GLib.get_user_config_dir(),
                                 "intel-gpu-top-gui", "settings.json")
        try:
            with open(self.path) as fh:
                data = json.load(fh)
            if isinstance(data, dict):
                for k, v in data.items():
                    if k in DEFAULTS and isinstance(v, type(DEFAULTS[k])):
                        self[k] = v
        except (OSError, ValueError):
            pass

    def save(self) -> None:
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            tmp = self.path + ".tmp"
            with open(tmp, "w") as fh:
                json.dump(dict(self), fh, indent=2)
            os.replace(tmp, self.path)
        except OSError:
            pass
