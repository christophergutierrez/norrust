#!/usr/bin/env python3
"""review_sprites.py — Standalone sprite review and generation tool.

Browse unit sprites, edit prompts, regenerate with live preview.
No Love2D or Rust dependencies — just Python + PIL + Gemini API key.

Usage:
    python3 tools/review_sprites.py
    python3 tools/review_sprites.py --missing   # only show units with missing poses

Keyboard:
    Up/Down     Navigate unit list
    +/-/0       Zoom in/out/reset
    Escape      Clear selection
    Scroll      Zoom over sprites, scroll over list
"""

import argparse
import base64
import io
import json
import os
import shutil
import sys
import threading
import time
import tkinter as tk
from tkinter import ttk
import urllib.request
from PIL import Image, ImageTk

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.join(SCRIPT_DIR, "..")
DATA_UNITS_DIR = os.path.join(PROJECT_ROOT, "data", "units")

# Import unit definitions and processing from generate_sprites
sys.path.insert(0, SCRIPT_DIR)
from generate_sprites import (
    UNITS as SPRITE_UNITS,
    STYLE_PROMPT,
    FRAME_SIZE,
    PORTRAIT_SIZE,
    process_single_image,
    process_portrait,
)

# In-memory prompt overrides: (unit_path, pose) -> edited text
# These take priority over SPRITE_UNITS when generating.
PROMPT_OVERRIDES = {}

POSES = ["idle", "attack-melee", "attack-ranged", "defend", "portrait"]
DEFAULT_ZOOM = 128
MIN_ZOOM = 48
MAX_ZOOM = 512
ZOOM_STEP = 16
SIZE_LIMIT = 30720  # 30KB

BG_COLOR = "#2b2b2b"
SELECTED_COLOR = "#4a6fa5"
TEXT_COLOR = "#e0e0e0"
MISSING_COLOR = "#cc4444"
OK_COLOR = "#44aa44"
WARN_COLOR = "#ccaa44"
BASE_HIGHLIGHT = "#2266bb"
TARGET_HIGHLIGHT = "#bb6622"
DIM_COLOR = "#555555"
PANEL_BG = "#333333"

GEMINI_MODEL = "gemini-2.5-flash-image"
GEMINI_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"


# ── Standalone Gemini API call ──────────────────────────────────────────

def call_gemini(api_key, prompt, reference_image_path=None):
    """Call Gemini image generation API. Returns raw PNG bytes or None."""
    parts = []

    if reference_image_path and os.path.exists(reference_image_path):
        with open(reference_image_path, "rb") as f:
            img_b64 = base64.b64encode(f.read()).decode("ascii")
        parts.append({
            "inlineData": {"mimeType": "image/png", "data": img_b64}
        })

    parts.append({"text": prompt})

    body = json.dumps({
        "contents": [{"parts": parts}],
        "generationConfig": {"responseModalities": ["IMAGE", "TEXT"]},
    }).encode()

    for attempt in range(3):
        if attempt > 0:
            time.sleep(15 * attempt)
        try:
            req = urllib.request.Request(
                GEMINI_URL, data=body,
                headers={
                    "Content-Type": "application/json",
                    "x-goog-api-key": api_key,
                },
            )
            with urllib.request.urlopen(req, timeout=120) as resp:
                data = json.loads(resp.read())
        except Exception:
            continue

        candidates = data.get("candidates", [])
        if not candidates:
            continue
        for p in candidates[0].get("content", {}).get("parts", []):
            if "inlineData" in p:
                return base64.b64decode(p["inlineData"]["data"])

    return None


# ── Prompt building ─────────────────────────────────────────────────────

def build_full_prompt(unit_path, pose, has_reference=False):
    """Build the complete prompt for a unit+pose. Returns (prompt_text, editable_part).
    editable_part is the character/pose description the user can modify.
    """
    entry = SPRITE_UNITS.get(unit_path)
    if entry is None:
        return None, None
    desc, melee_weapon, ranged_weapon, defend_desc = entry

    if pose == "portrait":
        editable = (
            f"A painterly close-up portrait of a {desc}. "
            f"Show the face and upper body only, slightly angled, with dramatic lighting. "
            f"Rich detail, oil painting style, fantasy RPG character portrait."
        )
        full = (
            f"{editable} "
            f"Background: solid, uniform black (#000000). "
            f"No environment, no props, no text. Just the character portrait on black."
        )
        return full, editable

    pose_descriptions = {
        "idle": "standing idle, weapon at rest, relaxed stance.",
        "attack-melee": f"mid-swing {melee_weapon} melee attack, dynamic action pose.",
        "attack-ranged": f"aiming {ranged_weapon or melee_weapon} ranged attack, ready to fire.",
        "defend": defend_desc,
    }
    pose_desc = pose_descriptions.get(pose, pose)

    editable = f"A {desc}.\nPose: {pose_desc}"

    if has_reference:
        full = (
            f"This is a reference image of the character. "
            f"Generate the SAME character in a new pose.\n\n"
            f"{STYLE_PROMPT}\n\n"
            f"A single character in a single pose: {pose_desc}\n\n"
            f"CRITICAL: Only ONE character. No duplicates. No multiple views. "
            f"SAME character as the reference — same colors, same proportions, "
            f"same outfit, same style. Facing right. "
            f"Do NOT add equipment the character does not have."
        )
    else:
        full = (
            f"{STYLE_PROMPT}\n\n"
            f"Make a {desc}.\n\n"
            f"A single character in a single pose: {pose_desc}\n\n"
            f"CRITICAL: Only ONE character. No duplicates. No multiple views. "
            f"Just one character, facing right, centered on the magenta background."
        )

    return full, editable


def rebuild_prompt_from_edit(edited_text, unit_path, pose, has_reference=False):
    """Rebuild the full prompt using user-edited character/pose description."""
    if pose == "portrait":
        return (
            f"{edited_text} "
            f"Background: solid, uniform black (#000000). "
            f"No environment, no props, no text. Just the character portrait on black."
        )

    # Extract pose line if present
    lines = edited_text.strip().split("\n")
    char_desc = lines[0].strip()
    pose_desc = ""
    for line in lines[1:]:
        if line.strip().startswith("Pose:"):
            pose_desc = line.strip()[5:].strip()

    if not pose_desc:
        # Fall back to the entry's pose description
        entry = SPRITE_UNITS.get(unit_path)
        if entry:
            _, melee_weapon, ranged_weapon, defend_desc = entry
            pose_map = {
                "idle": "standing idle, weapon at rest, relaxed stance.",
                "attack-melee": f"mid-swing {melee_weapon} melee attack, dynamic action pose.",
                "attack-ranged": f"aiming {ranged_weapon or melee_weapon} ranged attack, ready to fire.",
                "defend": defend_desc,
            }
            pose_desc = pose_map.get(pose, pose)

    # Remove leading "A " if present for embedding
    if char_desc.startswith("A "):
        char_desc_bare = char_desc[2:]
    else:
        char_desc_bare = char_desc

    if has_reference:
        return (
            f"This is a reference image of the character. "
            f"Generate the SAME character in a new pose.\n\n"
            f"{STYLE_PROMPT}\n\n"
            f"A single character in a single pose: {pose_desc}\n\n"
            f"CRITICAL: Only ONE character. No duplicates. No multiple views. "
            f"SAME character as the reference — same colors, same proportions, "
            f"same outfit, same style. Facing right. "
            f"Do NOT add equipment the character does not have."
        )
    else:
        return (
            f"{STYLE_PROMPT}\n\n"
            f"Make a {char_desc_bare}.\n\n"
            f"A single character in a single pose: {pose_desc}\n\n"
            f"CRITICAL: Only ONE character. No duplicates. No multiple views. "
            f"Just one character, facing right, centered on the magenta background."
        )


# ── Save prompt back to generate_sprites.py ─────────────────────────────

def save_prompt_to_source(unit_path, new_desc=None, new_defend=None):
    """Update the UNITS entry in generate_sprites.py for a unit.
    Updates desc and/or defend_desc, both on disk and in memory.
    Returns (success, message).
    """
    src_path = os.path.join(SCRIPT_DIR, "generate_sprites.py")
    entry = SPRITE_UNITS.get(unit_path)
    if entry is None:
        return False, "unit not in UNITS dict"

    old_desc, melee, ranged, old_defend = entry
    changed = False

    with open(src_path, "r") as f:
        content = f.read()

    if new_desc and new_desc != old_desc:
        # Use repr-style quoting to match Python source
        old_quoted = json.dumps(old_desc)
        new_quoted = json.dumps(new_desc)
        if old_quoted in content:
            content = content.replace(old_quoted, new_quoted, 1)
            changed = True
        else:
            return False, f"could not find desc in source"

    if new_defend and new_defend != old_defend:
        old_quoted = json.dumps(old_defend)
        new_quoted = json.dumps(new_defend)
        if old_quoted in content:
            content = content.replace(old_quoted, new_quoted, 1)
            changed = True
        else:
            return False, f"could not find defend_desc in source"

    if changed:
        with open(src_path, "w") as f:
            f.write(content)
        # Update in-memory dict
        cur = SPRITE_UNITS[unit_path]
        SPRITE_UNITS[unit_path] = (
            new_desc if new_desc else cur[0],
            cur[1],
            cur[2],
            new_defend if new_defend else cur[3],
        )
        return True, "saved"
    else:
        return True, "no changes"


# ── Utility functions ───────────────────────────────────────────────────

def find_units():
    units = []
    for root, dirs, files in os.walk(DATA_UNITS_DIR):
        if any(f.endswith(".toml") for f in files):
            rel = os.path.relpath(root, DATA_UNITS_DIR)
            units.append(rel)
    units.sort()
    return units


def unit_has_ranged(unit_path):
    entry = SPRITE_UNITS.get(unit_path)
    if entry is None:
        return True
    return entry[2] is not None


def expected_poses(unit_path):
    if unit_has_ranged(unit_path):
        return POSES
    return [p for p in POSES if p != "attack-ranged"]


def unit_status(unit_path):
    full = os.path.join(DATA_UNITS_DIR, unit_path)
    exp = expected_poses(unit_path)
    found, missing = [], []
    for pose in exp:
        (found if os.path.exists(os.path.join(full, f"{pose}.png")) else missing).append(pose)
    return found, missing


def get_sprite_info(img_path):
    info = {}
    if not os.path.exists(img_path):
        return info
    info["file_size"] = os.path.getsize(img_path)
    info["size_kb"] = info["file_size"] / 1024
    try:
        with open(img_path, "rb") as fh:
            img = Image.open(io.BytesIO(fh.read()))
        info["dimensions"] = f"{img.width}x{img.height}"
    except Exception:
        pass
    return info


def resize_sprite(img_path, target_bytes=SIZE_LIMIT):
    with open(img_path, "rb") as fh:
        img = Image.open(io.BytesIO(fh.read())).convert("RGBA")
    orig_w, orig_h = img.size
    lo, hi = 0.3, 1.0
    best_buf = None
    for _ in range(12):
        mid = (lo + hi) / 2
        small = img.resize((max(1, int(orig_w * mid)), max(1, int(orig_h * mid))), Image.LANCZOS)
        back = small.resize((orig_w, orig_h), Image.NEAREST)
        buf = io.BytesIO()
        back.save(buf, format="PNG", optimize=True)
        if buf.tell() <= target_bytes:
            best_buf = buf
            lo = mid
        else:
            hi = mid
    if best_buf is None:
        buf = io.BytesIO()
        img.save(buf, format="PNG", optimize=True)
        best_buf = buf
    best_buf.seek(0)
    Image.open(best_buf).save(img_path, optimize=True)
    return os.path.getsize(img_path)


def flop_sprite(img_path):
    with open(img_path, "rb") as fh:
        img = Image.open(io.BytesIO(fh.read()))
    img.transpose(Image.FLIP_LEFT_RIGHT).save(img_path)
    return os.path.getsize(img_path)


def trim_edges(img_path, border_px=4):
    with open(img_path, "rb") as fh:
        img = Image.open(io.BytesIO(fh.read())).convert("RGBA")
    w, h = img.size
    pixels = img.load()
    for y in range(h):
        for x in range(w):
            if x < border_px or x >= w - border_px or y < border_px or y >= h - border_px:
                pixels[x, y] = (0, 0, 0, 0)
    img.save(img_path, optimize=True)
    return os.path.getsize(img_path)


# ── Main UI ─────────────────────────────────────────────────────────────

class SpriteReviewer:
    def __init__(self, root, units, missing_only=False):
        self.root = root
        self.missing_only = missing_only
        self.photo_refs = []
        self.zoom = DEFAULT_ZOOM
        self.raw_images = {}
        self.current_unit = None
        self.generating = False
        self.regen_base = None
        self.regen_target = None
        self.undo_stack = []
        self.api_key = os.environ.get("GEMINI_API_KEY", "")

        if missing_only:
            self.units = [u for u in units if unit_status(u)[1]]
        else:
            self.units = units

        self.root.title("Sprite Reviewer")
        self.root.configure(bg=BG_COLOR)
        self.root.geometry("1400x900")

        # ── Layout ──
        self.paned = ttk.PanedWindow(root, orient=tk.HORIZONTAL)
        self.paned.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # Left: unit list
        left = tk.Frame(self.paned, bg=BG_COLOR)
        self.paned.add(left, weight=1)

        sf = tk.Frame(left, bg=BG_COLOR)
        sf.pack(fill=tk.X, padx=2, pady=2)
        tk.Label(sf, text="Filter:", bg=BG_COLOR, fg=TEXT_COLOR).pack(side=tk.LEFT)
        self.search_var = tk.StringVar()
        self.search_var.trace_add("write", self._on_search)
        tk.Entry(sf, textvariable=self.search_var, bg="#3b3b3b", fg=TEXT_COLOR,
                 insertbackground=TEXT_COLOR).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=4)

        self.counter_label = tk.Label(left, text="", bg=BG_COLOR, fg=TEXT_COLOR, anchor="w")
        self.counter_label.pack(fill=tk.X, padx=4)

        lf = tk.Frame(left, bg=BG_COLOR)
        lf.pack(fill=tk.BOTH, expand=True)
        self.scrollbar = tk.Scrollbar(lf)
        self.scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.listbox = tk.Listbox(
            lf, bg="#1e1e1e", fg=TEXT_COLOR, selectbackground=SELECTED_COLOR,
            selectforeground="white", font=("monospace", 10), activestyle="none",
            yscrollcommand=self.scrollbar.set
        )
        self.listbox.pack(fill=tk.BOTH, expand=True)
        self.scrollbar.config(command=self.listbox.yview)
        self.listbox.bind("<<ListboxSelect>>", self._on_select)
        self.listbox.bind("<Button-4>", lambda e: self.listbox.yview_scroll(-3, "units"))
        self.listbox.bind("<Button-5>", lambda e: self.listbox.yview_scroll(3, "units"))

        # Right: sprites + controls
        right = tk.Frame(self.paned, bg=BG_COLOR)
        self.paned.add(right, weight=3)

        # Header
        self.header_label = tk.Label(right, text="", bg=BG_COLOR, fg=TEXT_COLOR,
                                     font=("monospace", 14, "bold"), anchor="w")
        self.header_label.pack(fill=tk.X, padx=10, pady=(8, 1))

        self.status_label = tk.Label(right, text="", bg=BG_COLOR, fg=TEXT_COLOR,
                                     font=("monospace", 10), anchor="w")
        self.status_label.pack(fill=tk.X, padx=10, pady=(0, 1))

        self.zoom_label = tk.Label(right, text=f"Zoom: {self.zoom}px", bg=BG_COLOR,
                                   fg="#888888", font=("monospace", 9), anchor="w")
        self.zoom_label.pack(fill=tk.X, padx=10, pady=(0, 3))

        # Sprite display
        sprite_outer = tk.Frame(right, bg=BG_COLOR)
        sprite_outer.pack(fill=tk.BOTH, expand=True, padx=10)

        self.sprite_canvas = tk.Canvas(sprite_outer, bg=BG_COLOR, highlightthickness=0)
        self.sprite_canvas.pack(fill=tk.BOTH, expand=True)
        self.sprite_frame = tk.Frame(self.sprite_canvas, bg=BG_COLOR)
        self.sprite_canvas.create_window((0, 0), window=self.sprite_frame, anchor="nw")

        for w in (self.sprite_canvas, self.sprite_frame):
            w.bind("<Button-4>", self._zoom_in)
            w.bind("<Button-5>", self._zoom_out)
            w.bind("<MouseWheel>", self._zoom_mousewheel)

        self.sprite_labels = {}
        self.pose_name_labels = {}
        self.size_labels = {}
        self.pose_borders = {}

        for i, pose in enumerate(POSES):
            cf = tk.Frame(self.sprite_frame, bg=BG_COLOR)
            cf.grid(row=0, column=i, padx=6, pady=5, sticky="n")

            nl = tk.Label(cf, text=pose, bg=BG_COLOR, fg=TEXT_COLOR, font=("monospace", 9, "bold"))
            nl.pack()

            bf = tk.Frame(cf, bg="#1a1a1a", bd=3, relief="flat")
            bf.pack(pady=2)
            self.pose_borders[pose] = bf

            il = tk.Label(bf, bg="#1a1a1a")
            il.pack()

            sl = tk.Label(cf, text="", bg=BG_COLOR, fg=TEXT_COLOR, font=("monospace", 8))
            sl.pack()

            self.sprite_labels[pose] = il
            self.pose_name_labels[pose] = nl
            self.size_labels[pose] = sl

            il.bind("<Button-1>", lambda e, p=pose: self._on_sprite_click(p))
            bf.bind("<Button-1>", lambda e, p=pose: self._on_sprite_click(p))
            il.bind("<Button-4>", self._zoom_in)
            il.bind("<Button-5>", self._zoom_out)
            il.bind("<MouseWheel>", self._zoom_mousewheel)

        # ── Prompt editor ──
        prompt_frame = tk.Frame(right, bg=PANEL_BG, relief="groove", bd=1)
        prompt_frame.pack(fill=tk.X, padx=10, pady=(4, 2))

        prompt_header = tk.Frame(prompt_frame, bg=PANEL_BG)
        prompt_header.pack(fill=tk.X, padx=4, pady=(4, 0))

        tk.Label(prompt_header, text="Prompt", bg=PANEL_BG, fg=TEXT_COLOR,
                 font=("monospace", 10, "bold")).pack(side=tk.LEFT)

        self.save_prompt_btn = tk.Button(
            prompt_header, text="Save Prompt", command=self._on_save_prompt,
            bg="#555555", fg=TEXT_COLOR, font=("monospace", 8), padx=6, state=tk.DISABLED
        )
        self.save_prompt_btn.pack(side=tk.RIGHT, padx=4)

        self.prompt_info = tk.Label(prompt_header, text="", bg=PANEL_BG, fg="#888888",
                                    font=("monospace", 8))
        self.prompt_info.pack(side=tk.RIGHT, padx=4)

        self.prompt_text = tk.Text(
            prompt_frame, bg="#1e1e1e", fg=TEXT_COLOR, insertbackground=TEXT_COLOR,
            font=("monospace", 9), height=3, wrap=tk.WORD, relief="flat", padx=6, pady=4
        )
        self.prompt_text.pack(fill=tk.X, padx=4, pady=(2, 4))
        self.prompt_text.bind("<<Modified>>", self._on_prompt_modified)

        # ── Generate controls ──
        gen_frame = tk.Frame(right, bg=PANEL_BG, relief="groove", bd=1)
        gen_frame.pack(fill=tk.X, padx=10, pady=(2, 2))

        tk.Label(gen_frame, text="Generate", bg=PANEL_BG, fg=TEXT_COLOR,
                 font=("monospace", 10, "bold")).pack(side=tk.LEFT, padx=(8, 4))

        self.base_label = tk.Label(gen_frame, text="Base: --", bg=PANEL_BG,
                                   fg="#888888", font=("monospace", 9))
        self.base_label.pack(side=tk.LEFT, padx=6)

        self.target_label = tk.Label(gen_frame, text="Target: --", bg=PANEL_BG,
                                     fg="#888888", font=("monospace", 9))
        self.target_label.pack(side=tk.LEFT, padx=6)

        self.submit_btn = tk.Button(gen_frame, text="Submit", command=self._on_submit,
                                    bg="#4a6fa5", fg="white", font=("monospace", 9, "bold"),
                                    state=tk.DISABLED, padx=10)
        self.submit_btn.pack(side=tk.LEFT, padx=6, pady=4)

        self.clear_btn = tk.Button(gen_frame, text="Clear", command=self._clear_regen,
                                   bg="#555555", fg=TEXT_COLOR, font=("monospace", 9), padx=6)
        self.clear_btn.pack(side=tk.LEFT, padx=4, pady=4)

        self.gen_status = tk.Label(gen_frame, text="", bg=PANEL_BG, fg=TEXT_COLOR,
                                   font=("monospace", 9))
        self.gen_status.pack(side=tk.LEFT, padx=6)

        # ── Fix tools ──
        fix_frame = tk.Frame(right, bg=PANEL_BG, relief="groove", bd=1)
        fix_frame.pack(fill=tk.X, padx=10, pady=(2, 2))

        tk.Label(fix_frame, text="Fix", bg=PANEL_BG, fg=TEXT_COLOR,
                 font=("monospace", 10, "bold")).pack(side=tk.LEFT, padx=(8, 4))

        self.fix_pose_var = tk.StringVar(value="idle")
        ttk.Combobox(fix_frame, textvariable=self.fix_pose_var,
                     values=POSES, width=14, state="readonly").pack(side=tk.LEFT, padx=4, pady=4)

        for label, cmd in [
            ("Flop", self._on_flop),
            ("Resize", self._on_resize),
            ("Trim Edges", self._on_trim),
            ("Undo", None),
        ]:
            if label == "Undo":
                self.undo_btn = tk.Button(fix_frame, text=label, command=self._on_undo,
                                          bg="#555555", fg=TEXT_COLOR, font=("monospace", 9),
                                          state=tk.DISABLED, padx=8)
                self.undo_btn.pack(side=tk.LEFT, padx=4, pady=4)
            else:
                tk.Button(fix_frame, text=label, command=cmd,
                          bg="#555555", fg=TEXT_COLOR, font=("monospace", 9),
                          padx=8).pack(side=tk.LEFT, padx=4, pady=4)

        self.fix_status = tk.Label(fix_frame, text="", bg=PANEL_BG, fg=TEXT_COLOR,
                                   font=("monospace", 9))
        self.fix_status.pack(side=tk.LEFT, padx=6)

        # Hints
        api_hint = "GEMINI_API_KEY set" if self.api_key else "GEMINI_API_KEY not set (generate disabled)"
        api_color = "#666666" if self.api_key else MISSING_COLOR
        tk.Label(right, text=api_hint, bg=BG_COLOR, fg=api_color,
                 font=("monospace", 8)).pack(side=tk.BOTTOM, pady=(0, 2))
        tk.Label(right, text="Up/Down: nav | Scroll sprites: zoom | Click: base then target | Esc: clear",
                 bg=BG_COLOR, fg="#666666", font=("monospace", 8)).pack(side=tk.BOTTOM, pady=(0, 0))

        # Bindings — bind on listbox directly to override its default Up/Down
        self._populate_list()
        self.listbox.bind("<Up>", self._key_up)
        self.listbox.bind("<Down>", self._key_down)
        self.root.bind("<Up>", self._key_up)
        self.root.bind("<Down>", self._key_down)
        self.root.bind("<plus>", self._zoom_in)
        self.root.bind("<equal>", self._zoom_in)
        self.root.bind("<minus>", self._zoom_out)
        self.root.bind("<0>", self._zoom_reset)
        self.root.bind("<Escape>", lambda e: self._clear_regen())

        if self.filtered_units:
            self.listbox.selection_set(0)
            self.listbox.see(0)
            self._show_unit(0)

    # ── List ──

    def _populate_list(self):
        self.listbox.delete(0, tk.END)
        ft = self.search_var.get().lower().strip()
        self.filtered_units = [u for u in self.units if ft in u.lower()] if ft else list(self.units)

        for unit in self.filtered_units:
            _, missing = unit_status(unit)
            prefix = "  " if not missing else ("~ " if len(missing) <= 1 else "! ")
            self.listbox.insert(tk.END, f"{prefix}{unit}")

        self._refresh_list_colors()
        self.counter_label.config(text=f"{len(self.filtered_units)} / {len(self.units)} units")

    def _refresh_list_colors(self):
        for i, unit in enumerate(self.filtered_units):
            _, missing = unit_status(unit)
            color = OK_COLOR if not missing else (WARN_COLOR if len(missing) <= 1 else MISSING_COLOR)
            self.listbox.itemconfig(i, fg=color)

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
            idx = sel[0] - 1
            self.listbox.selection_clear(0, tk.END)
            self.listbox.selection_set(idx)
            self.listbox.see(idx)
            self._show_unit(idx)
        return "break"

    def _key_down(self, event):
        sel = self.listbox.curselection()
        if sel and sel[0] < len(self.filtered_units) - 1:
            idx = sel[0] + 1
            self.listbox.selection_clear(0, tk.END)
            self.listbox.selection_set(idx)
            self.listbox.see(idx)
            self._show_unit(idx)
        return "break"

    # ── Zoom ──

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
        (self._zoom_in if event.delta > 0 else self._zoom_out)()
        return "break"

    def _zoom_reset(self, event=None):
        self.zoom = DEFAULT_ZOOM
        self._refresh_sprites()

    # ── Sprite display ──

    def _refresh_sprites(self):
        self.zoom_label.config(text=f"Zoom: {self.zoom}px")
        self.photo_refs.clear()
        has_ranged = self.current_unit and unit_has_ranged(self.current_unit)

        for pose in POSES:
            lbl = self.sprite_labels[pose]
            raw = self.raw_images.get(pose)
            is_na = (pose == "attack-ranged" and not has_ranged)

            if raw is not None:
                img = raw.resize((self.zoom, self.zoom), Image.NEAREST)
                photo = ImageTk.PhotoImage(img)
                lbl.config(image=photo, width=self.zoom, height=self.zoom, text="")
                self.photo_refs.append(photo)
            elif is_na:
                sz = max(24, self.zoom // 4)
                lbl.config(image="", text="n/a", fg=DIM_COLOR, width=sz // 8, height=sz // 16,
                           font=("monospace", 8))
                self.photo_refs.append(None)
            else:
                lbl.config(image="", text="--", fg=MISSING_COLOR, width=self.zoom // 8,
                           height=self.zoom // 16, font=("monospace", 10))
                self.photo_refs.append(None)

        self.sprite_frame.update_idletasks()
        self.sprite_canvas.config(scrollregion=self.sprite_canvas.bbox("all"))

    def _show_unit(self, idx):
        if idx < 0 or idx >= len(self.filtered_units):
            return

        unit = self.filtered_units[idx]
        unit_dir = os.path.join(DATA_UNITS_DIR, unit)
        found, missing = unit_status(unit)
        self.current_unit = unit
        self._clear_regen()
        self.fix_status.config(text="")

        self.header_label.config(text=unit)
        if not missing:
            self.status_label.config(text="All poses present", fg=OK_COLOR)
        else:
            self.status_label.config(text=f"Missing: {', '.join(missing)}", fg=MISSING_COLOR)

        # Show default prompt (idle or first available)
        self._update_prompt_for_pose("idle")

        self.raw_images.clear()
        has_ranged = unit_has_ranged(unit)

        for pose in POSES:
            img_path = os.path.join(unit_dir, f"{pose}.png")
            nl = self.pose_name_labels[pose]
            sl = self.size_labels[pose]

            if pose == "attack-ranged" and not has_ranged:
                nl.config(fg=DIM_COLOR)
                sl.config(text="n/a", fg=DIM_COLOR)
                self.raw_images[pose] = None
                continue

            if os.path.exists(img_path):
                try:
                    with open(img_path, "rb") as fh:
                        self.raw_images[pose] = Image.open(io.BytesIO(fh.read())).copy()
                    info = get_sprite_info(img_path)
                    size_text = f"{info.get('size_kb', 0):.1f}KB {info.get('dimensions', '?')}"
                    over = pose != "portrait" and info.get("file_size", 0) > SIZE_LIMIT
                    sl.config(text=size_text, fg=WARN_COLOR if over else TEXT_COLOR)
                    nl.config(fg=OK_COLOR)
                except Exception:
                    self.raw_images[pose] = None
                    sl.config(text="error", fg=MISSING_COLOR)
                    nl.config(fg=MISSING_COLOR)
            else:
                self.raw_images[pose] = None
                sl.config(text="missing", fg=MISSING_COLOR)
                nl.config(fg=MISSING_COLOR)

        if found:
            self.fix_pose_var.set(found[0])

        self._refresh_sprites()

    def _update_prompt_for_pose(self, pose):
        """Update the prompt editor for the given pose."""
        if not self.current_unit:
            return
        # Check for saved override first
        key = (self.current_unit, pose)
        override = PROMPT_OVERRIDES.get(key)
        if override:
            editable = override
        else:
            _, editable = build_full_prompt(self.current_unit, pose, has_reference=False)

        self.prompt_text.delete("1.0", tk.END)
        if editable:
            self.prompt_text.insert("1.0", editable)
        else:
            self.prompt_text.insert("1.0", "(unit not in generator)")
        self.prompt_text.edit_modified(False)
        self.save_prompt_btn.config(state=tk.DISABLED)
        has_override = key in PROMPT_OVERRIDES
        tag = " (edited)" if has_override else ""
        self.prompt_info.config(text=f"[{pose}]{tag}", fg=OK_COLOR if has_override else "#888888")
        self._active_prompt_pose = pose

    # ── Prompt editing ──

    def _on_prompt_modified(self, event=None):
        if self.prompt_text.edit_modified():
            self.save_prompt_btn.config(state=tk.NORMAL)
            self.prompt_text.edit_modified(False)

    def _on_save_prompt(self):
        """Save edited prompt — stores override and tries to update source file."""
        if not self.current_unit:
            return
        edited = self.prompt_text.get("1.0", tk.END).strip()
        pose = getattr(self, "_active_prompt_pose", "idle")
        key = (self.current_unit, pose)

        # Always save the verbatim edited text as an override
        PROMPT_OVERRIDES[key] = edited

        # Also try to update the source file for the desc/defend fields
        lines = edited.split("\n")
        char_line = lines[0].strip()
        if char_line.startswith("A "):
            new_desc = char_line[2:]
        else:
            new_desc = char_line
        if new_desc.endswith("."):
            new_desc = new_desc[:-1]
        new_desc = new_desc.rstrip(",").strip()

        new_defend = None
        for line in lines[1:]:
            stripped = line.strip()
            if stripped.startswith("Pose:"):
                pose_text = stripped[5:].strip()
                if pose == "defend":
                    new_defend = pose_text

        save_prompt_to_source(self.current_unit, new_desc=new_desc, new_defend=new_defend)

        self.prompt_info.config(text=f"[{pose}] saved (edited)", fg=OK_COLOR)
        self.save_prompt_btn.config(state=tk.DISABLED)

    # ── Sprite click ──

    def _on_sprite_click(self, pose):
        if self.generating:
            return
        if pose == "attack-ranged" and self.current_unit and not unit_has_ranged(self.current_unit):
            return

        # Update prompt editor to show this pose's prompt
        self._update_prompt_for_pose(pose)
        self.fix_pose_var.set(pose)

        # Regen selection
        if self.regen_base is None:
            if self.raw_images.get(pose) is not None:
                self.regen_base = pose
                self.base_label.config(text=f"Base: {pose}", fg=BASE_HIGHLIGHT)
                self.pose_borders[pose].config(bg=BASE_HIGHLIGHT)
                self.gen_status.config(text="Click target pose", fg=WARN_COLOR)
            else:
                self.gen_status.config(text="Base needs existing image", fg=MISSING_COLOR)
        elif self.regen_target is None:
            if pose == self.regen_base:
                self._clear_regen()
                return
            self.regen_target = pose
            self.target_label.config(text=f"Target: {pose}", fg=TARGET_HIGHLIGHT)
            self.pose_borders[pose].config(bg=TARGET_HIGHLIGHT)
            self.submit_btn.config(state=tk.NORMAL if self.api_key else tk.DISABLED)
            tag = "redo" if self.raw_images.get(pose) is not None else "new"
            self.gen_status.config(text=f"Ready ({tag})", fg=OK_COLOR)
        else:
            self._clear_regen()
            self._on_sprite_click(pose)

    def _clear_regen(self, event=None):
        self.regen_base = None
        self.regen_target = None
        self.base_label.config(text="Base: --", fg="#888888")
        self.target_label.config(text="Target: --", fg="#888888")
        self.submit_btn.config(state=tk.DISABLED)
        self.gen_status.config(text="")
        for pose in POSES:
            self.pose_borders[pose].config(bg="#1a1a1a")

    # ── Generation (direct API call with edited prompt) ──

    def _backup(self, path):
        if not os.path.exists(path):
            return None
        rel = os.path.relpath(os.path.dirname(path), DATA_UNITS_DIR)
        tmp_dir = os.path.join(PROJECT_ROOT, "tmp", "sprite_backups", rel.replace("/", "_"))
        os.makedirs(tmp_dir, exist_ok=True)
        backup = os.path.join(tmp_dir, os.path.basename(path))
        shutil.copy2(path, backup)
        self.undo_stack.append((path, backup))
        self.undo_btn.config(state=tk.NORMAL)
        return backup

    def _on_submit(self):
        if not self.current_unit or not self.regen_base or not self.regen_target or not self.api_key:
            return
        if self.generating:
            return

        unit = self.current_unit
        base_pose = self.regen_base
        target_pose = self.regen_target
        unit_dir = os.path.join(DATA_UNITS_DIR, unit)
        base_path = os.path.join(unit_dir, f"{base_pose}.png")
        target_path = os.path.join(unit_dir, f"{target_pose}.png")

        self._backup(target_path)

        # Build prompt from editor content
        edited = self.prompt_text.get("1.0", tk.END).strip()
        has_ref = (target_pose != "portrait")  # portraits don't use reference
        prompt = rebuild_prompt_from_edit(edited, unit, target_pose, has_reference=has_ref)

        ref_path = base_path if has_ref else None

        self.generating = True
        self.submit_btn.config(state=tk.DISABLED)
        self.gen_status.config(text=f"Generating {target_pose}...", fg=WARN_COLOR)

        def _run():
            try:
                raw_data = call_gemini(self.api_key, prompt, reference_image_path=ref_path)
                if raw_data is None:
                    self.root.after(0, lambda: self._on_gen_done(False, "API returned no image"))
                    return

                # Process the raw image
                os.makedirs(unit_dir, exist_ok=True)
                if target_pose == "portrait":
                    process_portrait(raw_data, target_path)
                else:
                    process_single_image(raw_data, target_path)

                # Small delay to ensure file is flushed to disk
                time.sleep(0.2)
                self.root.after(0, lambda: self._on_gen_done(True, ""))
            except Exception as e:
                self.root.after(0, lambda: self._on_gen_done(False, str(e)))

        threading.Thread(target=_run, daemon=True).start()

    def _on_gen_done(self, success, error):
        self.generating = False
        target_pose = self.regen_target

        if success and self.current_unit and target_pose:
            target_path = os.path.join(DATA_UNITS_DIR, self.current_unit,
                                       f"{target_pose}.png")
            info = get_sprite_info(target_path)
            size_kb = info.get("size_kb", 0)
            over = info.get("file_size", 0) > SIZE_LIMIT
            status = f"Done! {size_kb:.1f}KB"
            if over:
                status += " (oversized — use Resize)"
            self.gen_status.config(text=status, fg=OK_COLOR if not over else WARN_COLOR)
        elif not success:
            self.gen_status.config(text=f"Failed: {error[:40]}", fg=MISSING_COLOR)

        self._clear_regen()
        self.root.update_idletasks()
        # Reload after a brief delay to ensure filesystem sync
        self.root.after(100, self._reload)

    # ── Fix tools ──

    def _get_fix_path(self):
        if not self.current_unit:
            return None
        return os.path.join(DATA_UNITS_DIR, self.current_unit, f"{self.fix_pose_var.get()}.png")

    def _on_flop(self):
        path = self._get_fix_path()
        if not path or not os.path.exists(path):
            self.fix_status.config(text="No file", fg=MISSING_COLOR)
            return
        self._backup(path)
        new_size = flop_sprite(path)
        self.fix_status.config(text=f"Flopped ({new_size / 1024:.1f}KB)", fg=OK_COLOR)
        self._reload()

    def _on_resize(self):
        path = self._get_fix_path()
        if not path or not os.path.exists(path):
            self.fix_status.config(text="No file", fg=MISSING_COLOR)
            return
        old_size = os.path.getsize(path)
        if old_size <= SIZE_LIMIT:
            self.fix_status.config(text="Already under 30KB", fg=OK_COLOR)
            return
        self._backup(path)
        new_size = resize_sprite(path)
        pct = (1 - new_size / old_size) * 100
        self.fix_status.config(
            text=f"{old_size / 1024:.1f}KB -> {new_size / 1024:.1f}KB (-{pct:.0f}%)", fg=OK_COLOR)
        self._reload()

    def _on_trim(self):
        path = self._get_fix_path()
        if not path or not os.path.exists(path):
            self.fix_status.config(text="No file", fg=MISSING_COLOR)
            return
        self._backup(path)
        new_size = trim_edges(path)
        self.fix_status.config(text=f"Trimmed ({new_size / 1024:.1f}KB)", fg=OK_COLOR)
        self._reload()

    def _on_undo(self):
        if not self.undo_stack:
            return
        target, backup = self.undo_stack.pop()
        if os.path.exists(backup):
            shutil.copy2(backup, target)
            self.fix_status.config(text="Undone", fg=TEXT_COLOR)
            self._reload()
        if not self.undo_stack:
            self.undo_btn.config(state=tk.DISABLED)

    def _reload(self):
        sel = self.listbox.curselection()
        if sel:
            self._show_unit(sel[0])
            self._refresh_list_colors()


def main():
    parser = argparse.ArgumentParser(description="Sprite review and generation tool")
    parser.add_argument("--missing", action="store_true", help="Only show units with missing poses")
    args = parser.parse_args()

    units = find_units()
    root = tk.Tk()
    SpriteReviewer(root, units, missing_only=args.missing)
    root.mainloop()


if __name__ == "__main__":
    main()
