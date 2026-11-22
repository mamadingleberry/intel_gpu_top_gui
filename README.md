# Intel GPU Monitor (intel-gpu-top-gui)

A GTK 4 / libadwaita front-end for `intel_gpu_top`, laid out like GNOME's
System Monitor. It shows the GPU's statistics as scrolling time-series graphs
instead of a terminal table.

**Resources tab:** one graph per metric, each with a legend that shows the current value:

| Graph              | Series                                              |
|--------------------|-----------------------------------------------------|
| Engine Utilization | Render/3D, Blitter, Video, VideoEnhance, Compute… (busy %) |
| Frequency          | requested and actual clock (MHz)                    |
| Power              | GPU and package power (W)                           |
| RC6 Residency      | time spent in the low-power idle state (%)          |
| Memory Bandwidth   | IMC reads and writes (when your GPU reports them)   |
| Interrupts         | IRQs per second                                     |

Any other metric group that your version of `intel_gpu_top` reports, such as
per-GT groups on multi-tile GPUs, gets a graph of its own automatically.

- Hover a graph to see a crosshair and the values at that moment.
- Click a legend entry to hide or show that series.
- The layout adapts to the window size, so snapped/tiled halves and quarters,
  small laptop screens and maximised windows on large displays all work. The
  graphs shrink to keep everything in view, without scrolling, and grow to fill
  a large window. The number of columns is picked from the space available. In
  small windows the legends switch to a single line and the subtitles are
  hidden, and narrow windows move the Resources/Processes switcher to the
  bottom. The page only scrolls when the window is too small for even the most
  compact layout. Axis margins follow your text size, and grid lines stay
  sharp at any display scale, including fractional scaling.

**Processes tab:** a sortable table of the processes using the GPU, with
per-engine-class utilisation (the `clients` part of `intel_gpu_top`).

**Main menu (☰):**
- Update interval (0.25–5 s)
- History length (1–30 min)
- Device selection (only shown with more than one GPU)
- Run as Administrator
- Export the recorded history to CSV (`Ctrl+E`)
- Clear the history (`Ctrl+L`)

**Pause button:** freezes the graphs (`Ctrl+Space`).

**Light and dark mode:** the app follows the system style (*Settings →
Appearance*) and switches immediately when it changes, graph colours included.
Each mode has its own colour-blind-friendly graph palette.

**Dock icon:** the app installs a scalable icon and PNGs from 16 to 512 px. The
running window is matched to its launcher (app ID `io.github.IntelGpuTopGui`,
and `StartupWMClass` on X11), so the dock shows the right icon and "Add to
Favorites" works.

## Requirements

- Debian 13 (trixie) or newer, Ubuntu 24.04 or newer, or a derivative
- An Intel GPU supported by `intel_gpu_top`

### Why Python 3 from the system, without pip?

The app uses the system interpreter (`/usr/bin/python3`, version 3.10 or newer;
Ubuntu 24.04 ships 3.12) together with the distribution's PyGObject. GTK 4 and
libadwaita bindings come from apt, not pip, so a virtualenv would only get in
the way. The app has no third-party Python dependencies.

Runtime packages (the `.deb` pulls these in automatically):

```
python3 python3-gi python3-gi-cairo gir1.2-gtk-4.0 gir1.2-adw-1 intel-gpu-tools pkexec
```

## Installation

### Option 1: build and install a .deb (recommended)

```sh
packaging/build-deb.sh                                     # needs only dpkg-deb
sudo apt install ./dist/intel-gpu-top-gui_1.0.0_all.deb    # resolves dependencies
```

"Intel GPU Monitor" then appears in your application menu. You can also start
it from a terminal with `intel-gpu-top-gui`.

To remove it: `sudo apt remove intel-gpu-top-gui`.

If you prefer the standard Debian toolchain, the `debian/` directory supports
a regular source-package build:

```sh
sudo apt install build-essential debhelper devscripts
dpkg-buildpackage -us -uc -b
sudo apt install ../intel-gpu-top-gui_1.0.0_all.deb
```

### Option 2: install without packaging

```sh
sudo apt install python3-gi python3-gi-cairo gir1.2-gtk-4.0 gir1.2-adw-1 intel-gpu-tools pkexec
sudo packaging/install.sh                  # installs into /usr/local
sudo packaging/install.sh --uninstall      # removes it again
```

For a per-user install without root, which also gives you the launcher and
dock icon, run:

```sh
PREFIX=~/.local packaging/install.sh            # ~/.local/bin must be on your PATH
PREFIX=~/.local packaging/install.sh --uninstall
```

If you have `make`, `make install`, `make uninstall`, `make deb`, `make test`
and `make demo` do the same things.

### Option 3: run from the source tree

```sh
PYTHONPATH=src python3 -m intel_gpu_top_gui          # real data
PYTHONPATH=src python3 -m intel_gpu_top_gui --demo   # synthetic data, no GPU or root needed
```

Run this way, the window and About dialog show the icon, but the dock shows a
generic one, because GNOME's dock looks up icons through an installed
`.desktop` file. A per-user install (above) fixes that.

## Permissions: intel_gpu_top needs privileges

`intel_gpu_top` reads the i915 performance counters (PMU), and the kernel only
allows that for privileged processes. Run as a normal user, it fails, often
with an unhelpful message such as
``get_num_gts: Assertion `!errno || errno == ENOENT' failed``.
The app detects this and shows a page offering these choices:

1. **Run as Administrator** (default, nothing to configure). The app runs
   `pkexec intel_gpu_top …` and you enter your password once each time the app
   starts monitoring. The choice is remembered: you can toggle it in
   *☰ → Run as Administrator* or start with `intel-gpu-top-gui --pkexec`. The
   package installs a polkit action so that the prompt says what it is for.
   Credentials are deliberately not cached, because `intel_gpu_top -o FILE`
   could otherwise be used to write files as root without a password.

2. **Give intel_gpu_top the perfmon capability** (no password prompt):

   ```sh
   sudo setcap cap_perfmon=+ep /usr/bin/intel_gpu_top
   ```

   Any user can then run `intel_gpu_top`, and so can this app. Two caveats:
   - When the `intel-gpu-tools` package is upgraded, the capability is lost,
     so you have to run the command again.
   - The Processes tab may not list processes that belong to other users,
     because reading their `/proc/<pid>/fdinfo` needs more privileges.

   To undo it: `sudo setcap -r /usr/bin/intel_gpu_top`.

3. **Lower the kernel's perf restriction for the whole system**, for example
   `sudo sysctl kernel.perf_event_paranoid=0`. This lets every program on the
   machine use system-wide perf events, so prefer option 2.

## Command-line options

```
intel-gpu-top-gui [--demo] [--pkexec] [-s MS] [-d FILTER]

  --demo              show synthetic data (no GPU or privileges needed)
  --pkexec            run intel_gpu_top through pkexec
  -s, --interval MS   sampling interval in milliseconds
  -d, --device FILTER intel_gpu_top device filter (see `intel_gpu_top -L`)
```

Settings are stored in `~/.config/intel-gpu-top-gui/settings.json`.

## How it works

The app starts `intel_gpu_top -J -s <interval>` as a child process.
`intel_gpu_top` writes one JSON object per period inside a JSON array that is
never closed, so the app decodes the objects incrementally as they arrive
(`sampler.py`).

Each sample is flattened into metric groups (`history.py`), kept in ring
buffers sized to the history length, and drawn with Cairo (`graph.py`).

When the app stops monitoring, it terminates `intel_gpu_top`. If
`intel_gpu_top` runs as root through pkexec, the app is not allowed to signal
it; it closes the pipe instead, and `intel_gpu_top` exits on its next write.

```
src/intel_gpu_top_gui/
  app.py       Adw.Application, command line, About dialog
  window.py    main window, menus, error and "waiting" pages
  graph.py     graph widget (grid, lines, hover tooltip) and legend
  clients.py   Processes table (Gtk.ColumnView)
  history.py   sample flattening, ring buffers, CSV export
  sampler.py   intel_gpu_top process, JSON stream parser, demo generator
  config.py    settings file
packaging/
  install.sh   installs or uninstalls the app (used by everything else)
  build-deb.sh builds a .deb with dpkg-deb only
  render-icons.py  regenerates data/icons/*/ PNGs from the SVG icon
debian/        standard Debian packaging (dpkg-buildpackage)
data/          .desktop file, icons (SVG + PNGs), AppStream metainfo, polkit policy
tests/         unit tests: python3 -m unittest discover -s tests
```

## Troubleshooting

- **"Cannot Read GPU Statistics"**: see [Permissions](#permissions-intel_gpu_top-needs-privileges).
  Open *Details* on that page to see what `intel_gpu_top` printed.
- **The graphs are empty and the terminal shows errors about
  `cairo.Context`**: install `python3-gi-cairo`.
- **No supported GPU / the newer `xe` kernel driver**: older `intel_gpu_top`
  releases (such as 1.28 in Ubuntu 24.04) support only the `i915` driver. Run
  `intel_gpu_top -L` to check that your GPU is listed.
- **Interrupts, power or memory bandwidth graphs are missing**: some GPUs and
  kernels do not report these values, and the app shows only what
  `intel_gpu_top` provides.

## Disclaimer

This application was created with the help of
[Claude](https://claude.com/claude-code), an AI assistant made by Anthropic.
It is an independent project and is not affiliated with or endorsed by Intel.

## License

MIT, see [LICENSE](LICENSE).
