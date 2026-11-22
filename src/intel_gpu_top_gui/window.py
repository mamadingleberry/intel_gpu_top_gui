"""Main application window."""

from __future__ import annotations

import os
import time

from gi.repository import Adw, Gio, GLib, Gtk

from . import APP_NAME
from .clients import ClientsView
from .graph import AxisGroup, GraphSection
from .grid import GraphGrid, split_columns  # noqa: F401  (re-exported)
from .history import History
from .sampler import Sampler, intel_gpu_top_path, list_devices

INTERVALS_MS = [(250, "0.25 seconds"), (500, "0.5 seconds"), (1000, "1 second"),
                (2000, "2 seconds"), (5000, "5 seconds")]
HISTORY_S = [(60, "1 minute"), (120, "2 minutes"), (300, "5 minutes"),
             (600, "10 minutes"), (1800, "30 minutes")]

# group key -> (title, subtitle, minimum graph height, fixed y max or None).
# Graphs grow beyond their minimum height to fill a taller window.
GROUPS = {
    "engines": ("Engine Utilization", "Busy time of each GPU engine", 200, 100.0),
    "frequency": ("Frequency", "Requested and actual GPU clock", 140, None),
    "power": ("Power", "GPU and package power draw", 140, None),
    "rc6": ("RC6 Residency", "Share of time the GPU spent in its idle power state", 110, 100.0),
    "imc-bandwidth": ("Memory Bandwidth", "Integrated memory controller traffic", 140, None),
    "interrupts": ("Interrupts", "GPU interrupts per second", 110, None),
}
GROUP_ORDER = list(GROUPS)

CSS = b"""
.graph-section { padding: 12px 6px 6px 6px; }
.legend-item { padding: 2px 8px; min-height: 0; }
.legend-off { opacity: 0.45; }
.device-caption { padding: 0 12px; }
.compact .graph-section { padding: 4px 0 0 0; }
.compact .legend-item { padding: 0 6px; }
"""

# Window-size breakpoints (in sp, so they follow the text scaling setting).
# The number of graph columns is not a breakpoint: GraphGrid picks it from
# the space it gets.
NARROW_MAX_WIDTH = 600   # half of a small screen: switcher moves to the bottom
SHORT_MAX_HEIGHT = 720   # tiles, small laptops: denser sections


def _group_meta(group: str, unit: str):
    base = group.split("-gt")[0] if "-gt" in group else group
    if base in GROUPS:
        title, sub, h, fixed = GROUPS[base]
        if base != group:
            title = f"{title} ({group[len(base) + 1:].upper()})"
        return title, sub, h, fixed
    title = group.replace("-", " ").replace("_", " ").title()
    return title, "", 130, (100.0 if unit == "%" else None)


class MainWindow(Adw.ApplicationWindow):
    def __init__(self, app: Adw.Application, config, demo: bool = False) -> None:
        super().__init__(application=app, title=APP_NAME)
        self.config = config
        self.demo = demo
        self.paused = False
        self.devices = [] if demo else list_devices()
        self.history = History(self._max_points())
        self.sections: dict[str, GraphSection] = {}
        self.axis_group = AxisGroup()
        self.sampler = Sampler(self._on_sample, self._on_exit)

        self.compact = False

        self.set_default_size(960, 820)
        self.set_size_request(360, 360)

        provider = Gtk.CssProvider()
        provider.load_from_data(CSS)
        Gtk.StyleContext.add_provider_for_display(
            self.get_display(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

        self._build_ui()
        self._install_breakpoints()
        self._install_actions()
        Adw.StyleManager.get_default().connect("notify::dark", self._on_dark_changed)
        self.connect("close-request", self._on_close)
        self.start_sampling()

    # -- UI -----------------------------------------------------------------

    def _build_ui(self) -> None:
        self.view_stack = Adw.ViewStack()

        # Resources page.
        self.sections_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.sections_box.set_margin_top(6)
        self.sections_box.set_margin_bottom(18)
        self.sections_box.set_margin_start(12)
        self.sections_box.set_margin_end(18)
        self.device_label = Gtk.Label(xalign=0)
        self.device_label.add_css_class("dim-label")
        self.device_label.add_css_class("caption")
        self.device_label.add_css_class("device-caption")
        self.device_label.set_margin_top(6)
        self.sections_box.append(self.device_label)
        # Fits the graphs into the available space; see grid.py.
        self.grid = GraphGrid()
        self.sections_box.append(self.grid)
        scroller = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER)
        scroller.set_child(self.sections_box)
        self.view_stack.add_titled_with_icon(
            scroller, "resources", "Resources", "utilities-system-monitor-symbolic")

        # Clients page.
        self.clients_view = ClientsView()
        self.view_stack.add_titled_with_icon(
            self.clients_view, "clients", "Processes", "view-list-symbolic")

        # Waiting / error pages.
        spinner = Gtk.Spinner(spinning=True, width_request=32, height_request=32)
        self.waiting_page = Adw.StatusPage(
            title="Waiting for intel_gpu_top…", child=spinner)
        self.error_page = Adw.StatusPage(icon_name="dialog-warning-symbolic")
        self.error_page.set_child(self._build_error_actions())

        self.main_stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE)
        self.main_stack.add_named(self.waiting_page, "waiting")
        self.main_stack.add_named(self.error_page, "error")
        self.main_stack.add_named(self.view_stack, "main")

        header = Adw.HeaderBar()
        self.switcher = Adw.ViewSwitcher(stack=self.view_stack,
                                         policy=Adw.ViewSwitcherPolicy.WIDE)
        header.set_title_widget(self.switcher)
        # Shown instead of the header switcher when the window is narrow.
        self.switcher_bar = Adw.ViewSwitcherBar(stack=self.view_stack)

        self.pause_button = Gtk.ToggleButton(icon_name="media-playback-pause-symbolic")
        self.pause_button.set_tooltip_text("Pause (Ctrl+Space)")
        self.pause_button.connect("toggled", self._on_pause_toggled)
        header.pack_start(self.pause_button)

        menu_button = Gtk.MenuButton(icon_name="open-menu-symbolic",
                                     menu_model=self._build_menu(),
                                     tooltip_text="Main Menu", primary=True)
        header.pack_end(menu_button)

        toolbar = Adw.ToolbarView()
        toolbar.add_top_bar(header)
        toolbar.add_bottom_bar(self.switcher_bar)
        toolbar.set_content(self.main_stack)
        self.toast_overlay = Adw.ToastOverlay(child=toolbar)
        self.set_content(self.toast_overlay)

    def _install_breakpoints(self) -> None:
        """Adapt the chrome to the window size (snapped/tiled windows, small
        screens).  Only the last matching breakpoint applies, so the narrow one
        carries the compact state as well."""
        narrow = f"max-width: {NARROW_MAX_WIDTH}sp"
        short = f"max-height: {SHORT_MAX_HEIGHT}sp"
        self._compact_bps: set[Adw.Breakpoint] = set()
        # Narrow windows are usually snapped halves of a small screen, where
        # the sections only fit when compact too.
        for cond, is_narrow, compact in ((short, False, True),
                                         (narrow, True, True)):
            bp = Adw.Breakpoint.new(Adw.BreakpointCondition.parse(cond))
            if is_narrow:
                bp.add_setter(self.switcher, "visible", False)
                bp.add_setter(self.switcher_bar, "reveal", True)
                bp.add_setter(self.sections_box, "margin-start", 6)
                bp.add_setter(self.sections_box, "margin-end", 6)
            if compact:
                self._compact_bps.add(bp)
            bp.connect("apply", self._on_breakpoint)
            bp.connect("unapply", self._on_breakpoint)
            self.add_breakpoint(bp)

    def _on_breakpoint(self, *_a) -> None:
        # Signals arrive unapply-then-apply; settle on the final state.
        GLib.idle_add(self._apply_breakpoint)

    def _apply_breakpoint(self) -> bool:
        self._set_compact(self.get_current_breakpoint() in self._compact_bps)
        return False

    def _set_compact(self, compact: bool) -> None:
        if compact == self.compact:
            return
        self.compact = compact
        if compact:
            self.sections_box.add_css_class("compact")
        else:
            self.sections_box.remove_css_class("compact")
        self.device_label.set_visible(not compact)
        self.sections_box.set_margin_bottom(6 if compact else 18)
        for sec in self.sections.values():
            sec.set_compact(compact)

    def _ordered_sections(self) -> list[GraphSection]:
        def rank(g):
            base = g.split("-gt")[0]
            return (GROUP_ORDER.index(base) if base in GROUP_ORDER else len(GROUP_ORDER), g)
        return [self.sections[g] for g in sorted(self.sections, key=rank)]

    def _relayout(self) -> None:
        self.grid.set_sections(self._ordered_sections())

    def _build_error_actions(self) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12,
                      halign=Gtk.Align.CENTER)
        self.elevate_button = Gtk.Button(label="Run as Administrator")
        self.elevate_button.add_css_class("pill")
        self.elevate_button.add_css_class("suggested-action")
        self.elevate_button.connect("clicked", lambda _b: self._set_elevate(True))
        retry = Gtk.Button(label="Retry")
        retry.add_css_class("pill")
        retry.connect("clicked", lambda _b: self.start_sampling())
        demo = Gtk.Button(label="Show Demo Data")
        demo.add_css_class("pill")
        demo.connect("clicked", lambda _b: self._start_demo())
        for b in (self.elevate_button, retry, demo):
            box.append(b)

        self.error_details = Gtk.Label(selectable=True, wrap=True, xalign=0)
        self.error_details.add_css_class("monospace")
        self.error_details.add_css_class("dim-label")
        self.error_details.set_max_width_chars(80)
        expander = Gtk.Expander(label="Details", child=self.error_details)
        expander.set_margin_top(12)
        self.error_expander = expander
        box.append(expander)
        return box

    def _build_menu(self) -> Gio.Menu:
        menu = Gio.Menu()

        settings = Gio.Menu()
        interval = Gio.Menu()
        for ms, label in INTERVALS_MS:
            interval.append(label, f"win.interval('{ms}')")
        settings.append_submenu("Update Interval", interval)
        history = Gio.Menu()
        for s, label in HISTORY_S:
            history.append(label, f"win.history('{s}')")
        settings.append_submenu("History Length", history)
        if len(self.devices) > 1:
            dev = Gio.Menu()
            dev.append("Default", "win.device('')")
            for flt, desc in self.devices:
                item = Gio.MenuItem.new(desc, None)
                item.set_action_and_target_value(
                    "win.device", GLib.Variant.new_string(flt))
                dev.append_item(item)
            settings.append_submenu("Device", dev)
        settings.append("Run as Administrator", "win.elevate")
        menu.append_section(None, settings)

        data = Gio.Menu()
        data.append("Export as CSV…", "win.export")
        data.append("Clear History", "win.clear")
        menu.append_section(None, data)

        about = Gio.Menu()
        about.append("Keyboard Shortcuts", "win.show-help-overlay")
        about.append(f"About {APP_NAME}", "app.about")
        menu.append_section(None, about)
        return menu

    def _install_actions(self) -> None:
        def stateful(name, value, cb):
            act = Gio.SimpleAction.new_stateful(
                name, GLib.VariantType.new("s"), GLib.Variant.new_string(str(value)))
            act.connect("change-state", cb)
            self.add_action(act)

        stateful("interval", self.config["interval_ms"], self._on_interval)
        stateful("history", self.config["history_s"], self._on_history)
        stateful("device", self.config["device"], self._on_device)

        elevate = Gio.SimpleAction.new_stateful(
            "elevate", None, GLib.Variant.new_boolean(self.config["elevate"]))
        elevate.connect("change-state",
                        lambda a, v: self._set_elevate(v.get_boolean()))
        self.add_action(elevate)

        for name, cb in (("export", self._on_export), ("clear", self._on_clear),
                         ("toggle-pause", lambda *_: self.pause_button.set_active(
                             not self.pause_button.get_active())),
                         ("show-help-overlay", self._on_shortcuts)):
            act = Gio.SimpleAction.new(name, None)
            act.connect("activate", cb)
            self.add_action(act)

        app = self.get_application()
        app.set_accels_for_action("win.export", ["<Control>e"])
        app.set_accels_for_action("win.clear", ["<Control>l"])
        app.set_accels_for_action("win.toggle-pause", ["<Control>space"])
        app.set_accels_for_action("win.show-help-overlay", ["<Control>question"])
        app.set_accels_for_action("window.close", ["<Control>w"])

    # -- sampling -------------------------------------------------------------

    def _max_points(self) -> int:
        return max(2, int(self.config["history_s"] * 1000 / self.config["interval_ms"]) + 1)

    def start_sampling(self) -> None:
        self.main_stack.set_visible_child_name(
            "main" if self.history.times else "waiting")
        if self.demo:
            self.waiting_page.set_description("Demo mode: generating synthetic data")
        elif self.config["elevate"]:
            self.waiting_page.set_description(
                "Running intel_gpu_top with administrator rights (pkexec)")
        else:
            self.waiting_page.set_description(None)
        self._update_caption()
        for sec in self.sections.values():
            sec.set_interval(self.config["interval_ms"] / 1000)
        self.sampler.start(
            interval_ms=self.config["interval_ms"],
            device=self.config["device"] or None,
            elevate=self.config["elevate"],
            demo=self.demo,
        )

    def _start_demo(self) -> None:
        self.demo = True
        self.history = History(self._max_points())
        self.sections.clear()
        self.axis_group = AxisGroup()
        self._relayout()
        self.start_sampling()

    def _update_caption(self) -> None:
        parts = []
        if self.demo:
            parts.append("Demo data")
        else:
            flt = self.config["device"]
            desc = next((d for f, d in self.devices if f == flt), None)
            if desc is None and self.devices:
                desc = self.devices[0][1]
            if desc:
                parts.append(desc)
        parts.append(f"updated every {self.config['interval_ms'] / 1000:g} s")
        if self.config["elevate"] and not self.demo:
            parts.append("running as administrator")
        self.device_label.set_label(" · ".join(parts))

    def _on_sample(self, sample: dict) -> None:
        if self.paused:
            return
        self.history.add(sample)
        for group in self.history.group_order:
            if group not in self.sections:
                self._add_section(group)
        for sec in self.sections.values():
            sec.refresh()
        self.clients_view.update(sample.get("clients"))
        if self.main_stack.get_visible_child_name() != "main":
            self.main_stack.set_visible_child_name("main")

    def _add_section(self, group: str) -> None:
        series = self.history.group_series(group)
        unit = series[0].unit if series else ""
        title, sub, height, fixed = _group_meta(group, unit)
        sec = GraphSection(self.history, group, title, unit, fixed, height, sub,
                           self.axis_group)
        sec.set_interval(self.config["interval_ms"] / 1000)
        sec.set_compact(self.compact)
        self.sections[group] = sec
        self._relayout()

    def _on_exit(self, rc: int, stderr: str, count: int) -> None:
        stderr = stderr.strip()
        if not intel_gpu_top_path() and not self.demo:
            title = "intel_gpu_top Is Not Installed"
            desc = ("Install it with:\n<tt>sudo apt install intel-gpu-tools</tt>")
            self.elevate_button.set_visible(False)
        elif self.config["elevate"] and rc in (126, 127) and count == 0:
            title = "Authentication Failed"
            desc = ("Administrator rights are needed to read GPU statistics. "
                    "Authentication was cancelled or refused.")
            self.elevate_button.set_visible(False)
        elif count == 0:
            title = "Cannot Read GPU Statistics"
            desc = ("intel_gpu_top could not access the GPU performance counters. "
                    "This usually means it needs more privileges.\n\n"
                    "Run it as administrator, or grant it permanent access with\n"
                    "<tt>sudo setcap cap_perfmon=+ep /usr/bin/intel_gpu_top</tt>\n"
                    "(see the README for details).")
            if "No device filter" in stderr or "No GPU" in stderr or "Failed to detect" in stderr:
                desc = "No supported Intel GPU was found."
            self.elevate_button.set_visible(not self.config["elevate"])
        else:
            title = "intel_gpu_top Stopped"
            desc = f"The monitoring process exited with status {rc}."
            self.elevate_button.set_visible(not self.config["elevate"])
        self.error_page.set_title(title)
        self.error_page.set_description(desc)
        details = f"exit status: {rc}"
        if stderr:
            details += "\n" + "\n".join(stderr.splitlines()[-15:])
        self.error_details.set_label(details)
        self.main_stack.set_visible_child_name("error")

    # -- action handlers ----------------------------------------------------

    def _on_pause_toggled(self, btn: Gtk.ToggleButton) -> None:
        self.paused = btn.get_active()
        btn.set_icon_name("media-playback-start-symbolic" if self.paused
                          else "media-playback-pause-symbolic")
        btn.set_tooltip_text("Resume (Ctrl+Space)" if self.paused else "Pause (Ctrl+Space)")
        if not self.paused:
            self.history.add_gap()

    def _on_interval(self, action, value) -> None:
        action.set_state(value)
        self.config["interval_ms"] = int(value.get_string())
        self.config.save()
        # Samples at a different rate cannot share a time axis.
        self.history.clear()
        self.history.set_max_points(self._max_points())
        self.start_sampling()

    def _on_history(self, action, value) -> None:
        action.set_state(value)
        self.config["history_s"] = int(value.get_string())
        self.config.save()
        self.history.set_max_points(self._max_points())
        for sec in self.sections.values():
            sec.graph.queue_draw()

    def _on_device(self, action, value) -> None:
        action.set_state(value)
        self.config["device"] = value.get_string()
        self.config.save()
        self.history.clear()
        self.clients_view.clear()
        self.start_sampling()

    def _set_elevate(self, on: bool) -> None:
        self.lookup_action("elevate").set_state(GLib.Variant.new_boolean(on))
        self.config["elevate"] = on
        self.config.save()
        self.demo = False
        self.start_sampling()

    def _on_clear(self, *_a) -> None:
        self.history.clear()
        for sec in self.sections.values():
            sec.refresh()

    def _on_export(self, *_a) -> None:
        dialog = Gtk.FileDialog(title="Export History")
        dialog.set_initial_name(time.strftime("intel-gpu-%Y%m%d-%H%M%S.csv"))
        dialog.save(self, None, self._on_export_done)

    def _on_export_done(self, dialog, result) -> None:
        try:
            gfile = dialog.save_finish(result)
        except GLib.Error:
            return  # cancelled
        path = gfile.get_path()
        try:
            self.history.write_csv(path)
        except OSError as exc:
            self.toast_overlay.add_toast(Adw.Toast(title=f"Export failed: {exc}"))
            return
        self.toast_overlay.add_toast(
            Adw.Toast(title=f"Saved {os.path.basename(path)}", timeout=3))

    def _on_shortcuts(self, *_a) -> None:
        builder = Gtk.Builder.new_from_string(SHORTCUTS_UI, -1)
        win = builder.get_object("shortcuts")
        win.set_transient_for(self)
        win.present()

    def _on_dark_changed(self, *_a) -> None:
        for sec in self.sections.values():
            sec.redraw_colors()

    def _on_close(self, *_a) -> bool:
        self.sampler.stop()
        return False


SHORTCUTS_UI = """
<interface>
  <object class="GtkShortcutsWindow" id="shortcuts">
    <property name="modal">1</property>
    <child>
      <object class="GtkShortcutsSection">
        <child>
          <object class="GtkShortcutsGroup">
            <property name="title">General</property>
            <child><object class="GtkShortcutsShortcut">
              <property name="title">Pause / resume</property>
              <property name="accelerator">&lt;Control&gt;space</property></object></child>
            <child><object class="GtkShortcutsShortcut">
              <property name="title">Export history as CSV</property>
              <property name="accelerator">&lt;Control&gt;e</property></object></child>
            <child><object class="GtkShortcutsShortcut">
              <property name="title">Clear history</property>
              <property name="accelerator">&lt;Control&gt;l</property></object></child>
            <child><object class="GtkShortcutsShortcut">
              <property name="title">Keyboard shortcuts</property>
              <property name="accelerator">&lt;Control&gt;question</property></object></child>
            <child><object class="GtkShortcutsShortcut">
              <property name="title">Close window</property>
              <property name="accelerator">&lt;Control&gt;w</property></object></child>
            <child><object class="GtkShortcutsShortcut">
              <property name="title">Quit</property>
              <property name="accelerator">&lt;Control&gt;q</property></object></child>
          </object>
        </child>
      </object>
    </child>
  </object>
</interface>
"""
