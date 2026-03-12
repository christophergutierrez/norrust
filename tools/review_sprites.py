#!/usr/bin/env python3
"""review_sprites.py — Sprite review tool with scrollable unit list.

Browse all unit sprites, click to select, arrow keys to navigate.
Shows idle, attack-melee, attack-ranged, defend, and portrait side by side.
Scroll wheel over sprites to zoom in/out.

Usage:
    python3 tools/review_sprites.py
    python3 tools/review_sprites.py --missing   # only show units missing any pose
"""

import argparse
import os
import tkinter as tk
from tkinter import ttk
from PIL import Image, ImageTk

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.join(SCRIPT_DIR, "..")
DATA_UNITS_DIR = os.path.join(PROJECT_ROOT, "data", "units")

POSES = ["idle", "attack-melee", "attack-ranged", "defend", "portrait"]
DEFAULT_ZOOM = 128
MIN_ZOOM = 48
MAX_ZOOM = 512
ZOOM_STEP = 16

BG_COLOR = "#2b2b2b"
SELECTED_COLOR = "#4a6fa5"
TEXT_COLOR = "#e0e0e0"
MISSING_COLOR = "#cc4444"
OK_COLOR = "#44aa44"
WARN_COLOR = "#ccaa44"


def find_units():
    """Find all unit directories containing a .toml file."""
    units = []
    for root, dirs, files in os.walk(DATA_UNITS_DIR):
        if any(f.endswith(".toml") for f in files):
            rel = os.path.relpath(root, DATA_UNITS_DIR)
            units.append(rel)
    units.sort()
    return units


def unit_status(unit_path):
    """Return (found_poses, missing_poses) for a unit directory."""
    full = os.path.join(DATA_UNITS_DIR, unit_path)
    found = []
    missing = []
    for pose in POSES:
        if os.path.exists(os.path.join(full, f"{pose}.png")):
            found.append(pose)
        else:
            missing.append(pose)
    return found, missing


class SpriteReviewer:
    def __init__(self, root, units, missing_only=False):
        self.root = root
        self.all_units = units
        self.missing_only = missing_only
        self.current_idx = 0
        self.photo_refs = []  # prevent GC
        self.zoom = DEFAULT_ZOOM
        self.raw_images = {}  # pose -> PIL Image (loaded at full res)
        self.current_unit = None

        # Filter if --missing
        if missing_only:
            self.units = [u for u in units if unit_status(u)[1]]
        else:
            self.units = units

        self.root.title("Sprite Reviewer")
        self.root.configure(bg=BG_COLOR)
        self.root.geometry("1200x750")

        # Layout: left panel (unit list) + right panel (sprite display)
        self.paned = ttk.PanedWindow(root, orient=tk.HORIZONTAL)
        self.paned.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # Left panel - scrollable unit list
        left_frame = tk.Frame(self.paned, bg=BG_COLOR)
        self.paned.add(left_frame, weight=1)

        # Search box
        search_frame = tk.Frame(left_frame, bg=BG_COLOR)
        search_frame.pack(fill=tk.X, padx=2, pady=2)
        tk.Label(search_frame, text="Filter:", bg=BG_COLOR, fg=TEXT_COLOR).pack(side=tk.LEFT)
        self.search_var = tk.StringVar()
        self.search_var.trace_add("write", self._on_search)
        search_entry = tk.Entry(search_frame, textvariable=self.search_var, bg="#3b3b3b", fg=TEXT_COLOR,
                                insertbackground=TEXT_COLOR)
        search_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=4)

        # Counter
        self.counter_label = tk.Label(left_frame, text="", bg=BG_COLOR, fg=TEXT_COLOR, anchor="w")
        self.counter_label.pack(fill=tk.X, padx=4)

        # Listbox with scrollbar
        list_frame = tk.Frame(left_frame, bg=BG_COLOR)
        list_frame.pack(fill=tk.BOTH, expand=True)

        self.scrollbar = tk.Scrollbar(list_frame)
        self.scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self.listbox = tk.Listbox(
            list_frame, bg="#1e1e1e", fg=TEXT_COLOR, selectbackground=SELECTED_COLOR,
            selectforeground="white", font=("monospace", 10), activestyle="none",
            yscrollcommand=self.scrollbar.set
        )
        self.listbox.pack(fill=tk.BOTH, expand=True)
        self.scrollbar.config(command=self.listbox.yview)

        self.listbox.bind("<<ListboxSelect>>", self._on_select)
        self.listbox.bind("<Button-4>", lambda e: self.listbox.yview_scroll(-3, "units"))
        self.listbox.bind("<Button-5>", lambda e: self.listbox.yview_scroll(3, "units"))

        # Right panel - sprite display
        right_frame = tk.Frame(self.paned, bg=BG_COLOR)
        self.paned.add(right_frame, weight=3)

        # Unit name header
        self.header_label = tk.Label(right_frame, text="", bg=BG_COLOR, fg=TEXT_COLOR,
                                     font=("monospace", 14, "bold"), anchor="w")
        self.header_label.pack(fill=tk.X, padx=10, pady=(10, 2))

        # Status line (includes zoom level)
        self.status_label = tk.Label(right_frame, text="", bg=BG_COLOR, fg=TEXT_COLOR,
                                     font=("monospace", 10), anchor="w")
        self.status_label.pack(fill=tk.X, padx=10, pady=(0, 2))

        self.zoom_label = tk.Label(right_frame, text=f"Zoom: {self.zoom}px", bg=BG_COLOR, fg="#888888",
                                   font=("monospace", 9), anchor="w")
        self.zoom_label.pack(fill=tk.X, padx=10, pady=(0, 6))

        # Sprite canvas area — scrollable for large zoom
        sprite_outer = tk.Frame(right_frame, bg=BG_COLOR)
        sprite_outer.pack(fill=tk.BOTH, expand=True, padx=10)

        self.sprite_canvas = tk.Canvas(sprite_outer, bg=BG_COLOR, highlightthickness=0)
        self.sprite_canvas.pack(fill=tk.BOTH, expand=True)

        self.sprite_frame = tk.Frame(self.sprite_canvas, bg=BG_COLOR)
        self.sprite_canvas.create_window((0, 0), window=self.sprite_frame, anchor="nw")

        # Zoom via scroll wheel on sprite area
        self.sprite_canvas.bind("<Button-4>", self._zoom_in)
        self.sprite_canvas.bind("<Button-5>", self._zoom_out)
        self.sprite_canvas.bind("<MouseWheel>", self._zoom_mousewheel)
        self.sprite_frame.bind("<Button-4>", self._zoom_in)
        self.sprite_frame.bind("<Button-5>", self._zoom_out)
        self.sprite_frame.bind("<MouseWheel>", self._zoom_mousewheel)

        # Create sprite display slots
        self.sprite_labels = {}
        self.pose_name_labels = {}
        self.size_labels = {}
        self.col_frames = {}

        for i, pose in enumerate(POSES):
            col_frame = tk.Frame(self.sprite_frame, bg=BG_COLOR)
            col_frame.grid(row=0, column=i, padx=8, pady=5, sticky="n")
            self.col_frames[pose] = col_frame

            name_lbl = tk.Label(col_frame, text=pose, bg=BG_COLOR, fg=TEXT_COLOR,
                                font=("monospace", 9, "bold"))
            name_lbl.pack()

            img_lbl = tk.Label(col_frame, bg="#1a1a1a", relief="sunken", borderwidth=1)
            img_lbl.pack(pady=2)

            size_lbl = tk.Label(col_frame, text="", bg=BG_COLOR, fg=TEXT_COLOR,
                                font=("monospace", 8))
            size_lbl.pack()

            self.sprite_labels[pose] = img_lbl
            self.pose_name_labels[pose] = name_lbl
            self.size_labels[pose] = size_lbl

            # Bind zoom on each label too
            img_lbl.bind("<Button-4>", self._zoom_in)
            img_lbl.bind("<Button-5>", self._zoom_out)
            img_lbl.bind("<MouseWheel>", self._zoom_mousewheel)

        # Keyboard hints
        hint_text = "Up/Down: navigate | Scroll list: browse | Scroll sprites: zoom | Type: filter"
        tk.Label(right_frame, text=hint_text, bg=BG_COLOR, fg="#888888",
                 font=("monospace", 9)).pack(side=tk.BOTTOM, pady=5)

        # Populate list
        self._populate_list()

        # Key bindings on root
        self.root.bind("<Up>", self._key_up)
        self.root.bind("<Down>", self._key_down)
        self.root.bind("<Return>", lambda e: self.listbox.focus_set())
        self.root.bind("<plus>", self._zoom_in)
        self.root.bind("<equal>", self._zoom_in)
        self.root.bind("<minus>", self._zoom_out)
        self.root.bind("<0>", self._zoom_reset)

        # Select first
        if self.filtered_units:
            self.listbox.selection_set(0)
            self.listbox.see(0)
            self._show_unit(0)

    def _populate_list(self):
        self.listbox.delete(0, tk.END)
        filter_text = self.search_var.get().lower().strip()

        if filter_text:
            self.filtered_units = [u for u in self.units if filter_text in u.lower()]
        else:
            self.filtered_units = list(self.units)

        for unit in self.filtered_units:
            found, missing = unit_status(unit)
            if not missing:
                prefix = "  "
            elif len(missing) <= 1:
                prefix = "~ "
            else:
                prefix = "! "
            self.listbox.insert(tk.END, f"{prefix}{unit}")

        # Color the entries
        for i, unit in enumerate(self.filtered_units):
            found, missing = unit_status(unit)
            if not missing:
                self.listbox.itemconfig(i, fg=OK_COLOR)
            elif len(missing) <= 1:
                self.listbox.itemconfig(i, fg=WARN_COLOR)
            else:
                self.listbox.itemconfig(i, fg=MISSING_COLOR)

        self.counter_label.config(text=f"{len(self.filtered_units)} / {len(self.units)} units")

    def _on_search(self, *args):
        self._populate_list()
        if self.filtered_units:
            self.listbox.selection_set(0)
            self._show_unit(0)

    def _on_select(self, event):
        sel = self.listbox.curselection()
        if sel:
            self._show_unit(sel[0])

    def _key_up(self, event):
        sel = self.listbox.curselection()
        if sel and sel[0] > 0:
            new_idx = sel[0] - 1
            self.listbox.selection_clear(0, tk.END)
            self.listbox.selection_set(new_idx)
            self.listbox.see(new_idx)
            self._show_unit(new_idx)

    def _key_down(self, event):
        sel = self.listbox.curselection()
        if sel and sel[0] < len(self.filtered_units) - 1:
            new_idx = sel[0] + 1
            self.listbox.selection_clear(0, tk.END)
            self.listbox.selection_set(new_idx)
            self.listbox.see(new_idx)
            self._show_unit(new_idx)

    def _zoom_in(self, event=None):
        if self.zoom < MAX_ZOOM:
            self.zoom = min(self.zoom + ZOOM_STEP, MAX_ZOOM)
            self._refresh_sprites()
        return "break"

    def _zoom_out(self, event=None):
        if self.zoom > MIN_ZOOM:
            self.zoom = max(self.zoom - ZOOM_STEP, MIN_ZOOM)
            self._refresh_sprites()
        return "break"

    def _zoom_mousewheel(self, event):
        # Windows/macOS style
        if event.delta > 0:
            self._zoom_in()
        elif event.delta < 0:
            self._zoom_out()
        return "break"

    def _zoom_reset(self, event=None):
        self.zoom = DEFAULT_ZOOM
        self._refresh_sprites()

    def _refresh_sprites(self):
        """Re-render sprites at current zoom level from cached raw images."""
        self.zoom_label.config(text=f"Zoom: {self.zoom}px")
        self.photo_refs.clear()

        for pose in POSES:
            lbl = self.sprite_labels[pose]
            raw = self.raw_images.get(pose)

            if raw is not None:
                display_size = self.zoom
                img = raw.resize((display_size, display_size), Image.NEAREST)
                photo = ImageTk.PhotoImage(img)
                lbl.config(image=photo, width=display_size, height=display_size)
                self.photo_refs.append(photo)
            else:
                lbl.config(image="", text="--", width=self.zoom // 8, height=self.zoom // 16)
                self.photo_refs.append(None)

        # Update scroll region
        self.sprite_frame.update_idletasks()
        self.sprite_canvas.config(scrollregion=self.sprite_canvas.bbox("all"))

    def _show_unit(self, idx):
        if idx < 0 or idx >= len(self.filtered_units):
            return

        unit = self.filtered_units[idx]
        unit_dir = os.path.join(DATA_UNITS_DIR, unit)
        found, missing = unit_status(unit)
        self.current_unit = unit

        self.header_label.config(text=unit)

        if not missing:
            status = "All poses present"
            color = OK_COLOR
        else:
            status = f"Missing: {', '.join(missing)}"
            color = MISSING_COLOR
        self.status_label.config(text=status, fg=color)

        # Load raw images at full resolution
        self.raw_images.clear()

        for pose in POSES:
            img_path = os.path.join(unit_dir, f"{pose}.png")
            name_lbl = self.pose_name_labels[pose]
            size_lbl = self.size_labels[pose]

            if os.path.exists(img_path):
                try:
                    self.raw_images[pose] = Image.open(img_path).copy()
                    file_size = os.path.getsize(img_path)
                    size_kb = file_size / 1024
                    size_text = f"{size_kb:.1f} KB"
                    if pose != "portrait" and file_size > 30720:
                        size_lbl.config(text=size_text, fg=WARN_COLOR)
                    else:
                        size_lbl.config(text=size_text, fg=TEXT_COLOR)
                    name_lbl.config(fg=OK_COLOR)
                except Exception:
                    self.raw_images[pose] = None
                    size_lbl.config(text="error", fg=MISSING_COLOR)
                    name_lbl.config(fg=MISSING_COLOR)
            else:
                self.raw_images[pose] = None
                size_lbl.config(text="missing", fg=MISSING_COLOR)
                name_lbl.config(fg=MISSING_COLOR)

        self._refresh_sprites()


def main():
    parser = argparse.ArgumentParser(description="Review unit sprites")
    parser.add_argument("--missing", action="store_true", help="Only show units with missing poses")
    args = parser.parse_args()

    units = find_units()
    root = tk.Tk()
    SpriteReviewer(root, units, missing_only=args.missing)
    root.mainloop()


if __name__ == "__main__":
    main()
