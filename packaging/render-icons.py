#!/usr/bin/python3
"""Render the scalable app icon to PNGs for docks/launchers without SVG support.

Run after editing data/io.github.IntelGpuTopGui.svg; the PNGs are committed.
"""
import os

import gi

gi.require_version("GdkPixbuf", "2.0")
from gi.repository import GdkPixbuf  # noqa: E402

APP_ID = "io.github.IntelGpuTopGui"
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data")
SVG = os.path.join(ROOT, f"{APP_ID}.svg")

for size in (16, 24, 32, 48, 64, 128, 256, 512):
    out_dir = os.path.join(ROOT, "icons", f"{size}x{size}")
    os.makedirs(out_dir, exist_ok=True)
    pix = GdkPixbuf.Pixbuf.new_from_file_at_size(SVG, size, size)
    pix.savev(os.path.join(out_dir, f"{APP_ID}.png"), "png", [], [])
    print(f"{size}x{size}")
