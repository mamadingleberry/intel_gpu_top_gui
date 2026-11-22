"""Application entry point."""

from __future__ import annotations

import argparse
import os
import signal
import sys

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gio, GLib, Gtk  # noqa: E402

from . import APP_ID, APP_NAME, __version__  # noqa: E402
from .config import Config  # noqa: E402


class Application(Adw.Application):
    def __init__(self, args: argparse.Namespace) -> None:
        super().__init__(application_id=APP_ID,
                         flags=Gio.ApplicationFlags.DEFAULT_FLAGS)
        self.args = args
        self.config = Config()
        if args.interval:
            self.config["interval_ms"] = args.interval
        if args.device is not None:
            self.config["device"] = args.device
        if args.pkexec:
            self.config["elevate"] = True

        for name, cb, accels in (("quit", lambda *_: self.quit(), ["<Control>q"]),
                                 ("about", self._on_about, [])):
            act = Gio.SimpleAction.new(name, None)
            act.connect("activate", cb)
            self.add_action(act)
            if accels:
                self.set_accels_for_action(f"app.{name}", accels)

    def do_startup(self) -> None:
        Adw.Application.do_startup(self)
        # Running from a source checkout: make the app icon findable even
        # though it is not installed into an icon theme yet.
        data_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "..", "data")
        display = Gdk.Display.get_default()
        if display is not None and os.path.isdir(data_dir):
            Gtk.IconTheme.get_for_display(display).add_search_path(
                os.path.normpath(data_dir))
        Gtk.Window.set_default_icon_name(APP_ID)

    def do_activate(self) -> None:
        from .window import MainWindow

        win = self.get_active_window()
        if win is None:
            win = MainWindow(self, self.config, demo=self.args.demo)
        win.present()

    def do_shutdown(self) -> None:
        for win in self.get_windows():
            if hasattr(win, "sampler"):
                win.sampler.stop()
        Adw.Application.do_shutdown(self)

    def _on_about(self, *_a) -> None:
        kwargs = dict(
            application_name=APP_NAME,
            application_icon=APP_ID,
            version=__version__,
            developer_name="intel-gpu-top-gui contributors",
            license_type=Gtk.License.MIT_X11,
            comments="Graphs of Intel GPU engine utilisation, frequency, power "
                     "and more, powered by intel_gpu_top.\n\n"
                     "Created with the help of Claude, an AI assistant made "
                     "by Anthropic.",
        )
        win = self.get_active_window()
        if hasattr(Adw, "AboutDialog"):  # libadwaita >= 1.5
            Adw.AboutDialog(**kwargs).present(win)
        else:
            Adw.AboutWindow(transient_for=win, **kwargs).present()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="intel-gpu-top-gui",
        description="Graphical time-series front-end for intel_gpu_top.")
    parser.add_argument("--demo", action="store_true",
                        help="show synthetic data (no GPU or privileges needed)")
    parser.add_argument("--pkexec", action="store_true",
                        help="run intel_gpu_top through pkexec (administrator)")
    parser.add_argument("-s", "--interval", type=int, metavar="MS",
                        help="sampling interval in milliseconds")
    parser.add_argument("-d", "--device", metavar="FILTER",
                        help="intel_gpu_top device filter, see 'intel_gpu_top -L'")
    parser.add_argument("--version", action="version", version=__version__)
    args = parser.parse_args(argv)
    if args.interval is not None and args.interval < 100:
        parser.error("interval must be at least 100 ms")

    # The program name becomes the X11 WM_CLASS; matching it to the app ID
    # (and to StartupWMClass in the .desktop file) lets docks pair the
    # window with its launcher and icon.  On Wayland the app ID does this.
    GLib.set_prgname(APP_ID)
    GLib.set_application_name(APP_NAME)

    app = Application(args)
    GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGINT, app.quit)
    return app.run(sys.argv[:1])
