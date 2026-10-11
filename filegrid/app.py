"""FileGrid: a borderless desktop panel that expands to a folder's contents
and collapses back into a single draggable folder puck."""

from __future__ import annotations

import os
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, simpledialog

from . import theme, winutil
from .gridview import GridView, round_rect
from .store import Store
from .theme import px

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD

    HAVE_DND = True
except Exception:  # pragma: no cover - optional dependency
    HAVE_DND = False

MIN_W, MIN_H = 560, 380
PUCK_SIZE = 110
PUCK_COMPACT_BELOW = 140  # below this only a one-line caption fits, no hint text
ANIM_STEPS = 12
ANIM_DELAY = 10


class HoverButton(tk.Label):
    def __init__(self, master, glyph, command, tooltip="", font="glyph", hover_fg=None):
        super().__init__(master, text=glyph, font=theme.FONTS[font],
                         fg=theme.TEXT_MUTED, bg=theme.PANEL,
                         padx=px(9), pady=px(5), cursor="hand2")
        self._base_fg = theme.TEXT_MUTED
        self._hover_fg = hover_fg or theme.TEXT
        self._command = command
        self._tip = Tooltip(self, tooltip) if tooltip else None
        self.bind("<Enter>", self._enter)
        self.bind("<Leave>", self._leave)
        self.bind("<Button-1>", lambda _e: self._command())

    def _enter(self, _event) -> None:
        self.configure(bg=theme.CARD, fg=self._hover_fg)

    def _leave(self, _event) -> None:
        self.configure(bg=theme.PANEL, fg=self._base_fg)

    def set_active(self, active: bool) -> None:
        self._base_fg = theme.ACCENT if active else theme.TEXT_MUTED
        self.configure(fg=self._base_fg)


class Tooltip:
    def __init__(self, widget, text: str):
        self.widget = widget
        self.text = text
        self.window = None
        self.job = None
        widget.bind("<Enter>", self._schedule, add="+")
        widget.bind("<Leave>", self._hide, add="+")
        widget.bind("<Button-1>", self._hide, add="+")

    def _schedule(self, _event=None) -> None:
        self._cancel()
        self.job = self.widget.after(450, self._show)

    def _cancel(self) -> None:
        if self.job:
            self.widget.after_cancel(self.job)
            self.job = None

    def _show(self) -> None:
        if self.window:
            return
        self.window = tk.Toplevel(self.widget)
        self.window.overrideredirect(True)
        self.window.attributes("-topmost", True)
        tk.Label(self.window, text=self.text, bg=theme.CARD, fg=theme.TEXT,
                 font=theme.FONTS["small"], padx=px(8), pady=px(4),
                 bd=1, relief="solid").pack()
        x = self.widget.winfo_rootx() + self.widget.winfo_width() // 2 - px(40)
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + px(6)
        self.window.geometry(f"+{x}+{y}")

    def _hide(self, _event=None) -> None:
        self._cancel()
        if self.window:
            self.window.destroy()
            self.window = None


class FileGridApp:
    def __init__(self):
        winutil.enable_dpi_awareness()
        self.root = TkinterDnD.Tk() if HAVE_DND else tk.Tk()
        self.root.withdraw()
        theme.init(self.root, winutil.system_scale())

        self.store = Store()
        self.store.bind(self.root)
        self.settings = self.store.instance
        self.collapsed = bool(self.settings.get("collapsed"))
        self.animating = False

        self.root.title("FileGrid")
        self.root.overrideredirect(True)
        self.root.configure(bg=theme.BORDER)
        self.root.minsize(px(MIN_W), px(MIN_H))

        self.shell = tk.Frame(self.root, bg=theme.BG)
        self.shell.pack(fill="both", expand=True, padx=1, pady=1)

        self._build_expanded()
        self._build_puck()
        self._bind_keys()

        directory = self.settings.get("directory") or str(Path.home())
        if not os.path.isdir(directory):
            directory = str(Path.home())
        self.grid.set_directory(directory)
        if HAVE_DND:
            self.grid.accept_drops(DND_FILES)
            self._accept_puck_drops()

        window = self.settings["window"]
        self.root.geometry(f"{px(window['w'])}x{px(window['h'])}+{window['x']}+{window['y']}")
        self._apply_topmost()
        if self.collapsed:
            self.expanded.pack_forget()
            self.puck.pack(fill="both", expand=True)
            self.root.minsize(1, 1)
            self.root.attributes("-topmost", True)
            self.root.geometry(self._puck_geometry())
        self.root.deiconify()
        self.root.after(60, lambda: winutil.show_in_taskbar(self.root))
        self.root.bind("<Configure>", self._on_configure)

    # ------------------------------------------------------------ expanded UI

    def _build_expanded(self) -> None:
        self.expanded = tk.Frame(self.shell, bg=theme.BG)
        self.expanded.pack(fill="both", expand=True)

        bar = tk.Frame(self.expanded, bg=theme.PANEL)
        bar.pack(fill="x")
        self.titlebar = bar

        tk.Label(bar, text=theme.GLYPH["folder"], font=theme.FONTS["glyph_big"],
                 fg=theme.FOLDER, bg=theme.PANEL, padx=px(12)).pack(side="left")

        heading = tk.Frame(bar, bg=theme.PANEL)
        heading.pack(side="left", pady=px(7))
        self.name_label = tk.Label(heading, text="", font=theme.FONTS["title"],
                                   fg=theme.TEXT, bg=theme.PANEL, anchor="w")
        self.name_label.pack(anchor="w")
        self.path_label = tk.Label(heading, text="", font=theme.FONTS["small"],
                                   fg=theme.TEXT_DIM, bg=theme.PANEL, anchor="w")
        self.path_label.pack(anchor="w")

        self._add_button(bar, "close", self.quit_app, "Close", hover_fg=theme.DANGER)
        self._add_button(bar, "collapse", self.collapse, "Minimize to folder")
        self.pin_button = self._add_button(bar, "pin", self.toggle_topmost, "Always on top")
        self._add_button(bar, "sort", lambda: self.grid.arrange(), "Auto-arrange tiles")
        self._add_button(bar, "refresh", lambda: self.grid.refresh(), "Rescan folder (F5)")
        self._add_button(bar, "folder_open", self.browse, "Open another folder (Ctrl+O)")
        self._add_button(bar, "up", self.go_up, "Parent folder")
        self._build_search(bar)

        self.grid = GridView(self.expanded, self.store, on_status=self._set_status,
                             on_navigate=self.open_directory, on_changed=self._on_folder_changed,
                             folder_actions=(("Rename puck label\u2026", self.edit_label),))
        self.grid.pack(fill="both", expand=True)

        status = tk.Frame(self.expanded, bg=theme.PANEL)
        status.pack(fill="x")
        self.status_label = tk.Label(status, text="", font=theme.FONTS["small"],
                                     fg=theme.TEXT_DIM, bg=theme.PANEL, anchor="w",
                                     padx=px(14), pady=px(5))
        self.status_label.pack(side="left")

        self.grip = tk.Canvas(status, width=px(16), height=px(16), bg=theme.PANEL,
                              highlightthickness=0, cursor="size_nw_se")
        self.grip.pack(side="right", padx=px(4), pady=px(4))
        for offset in (0, px(4), px(8)):
            self.grip.create_line(px(14) - offset, px(14), px(14), px(14) - offset,
                                  fill=theme.TEXT_DIM)
        self.grip.bind("<B1-Motion>", self._on_resize_drag)

        for widget in (bar, heading, self.name_label, self.path_label):
            widget.bind("<Button-1>", self._start_move)
            widget.bind("<B1-Motion>", self._on_move)
            widget.bind("<Double-Button-1>", lambda _e: self.collapse())

    def _add_button(self, bar, glyph_key, command, tooltip, hover_fg=None) -> HoverButton:
        button = HoverButton(bar, theme.GLYPH[glyph_key], command, tooltip, hover_fg=hover_fg)
        button.pack(side="right", padx=px(1), pady=px(8))
        return button

    def _build_search(self, bar) -> None:
        box = tk.Frame(bar, bg=theme.CARD)
        box.pack(side="right", padx=px(10), pady=px(9))
        tk.Label(box, text=theme.GLYPH["search"], font=theme.FONTS["glyph"],
                 fg=theme.TEXT_DIM, bg=theme.CARD, padx=px(6)).pack(side="left")
        self.search = tk.Entry(box, width=16, bd=0, bg=theme.CARD, fg=theme.TEXT,
                               font=theme.FONTS["body"], insertbackground=theme.ACCENT,
                               highlightthickness=0, relief="flat")
        self.search.pack(side="left", ipady=px(4), padx=(0, px(8)))
        self.search.bind("<KeyRelease>", lambda _e: self.grid.set_filter(self.search.get()))
        self.search.bind("<Escape>", self._on_search_escape)
        self.search.bind("<FocusIn>", lambda _e: self._placeholder(False))
        self.search.bind("<FocusOut>", lambda _e: self._placeholder(True))
        self._placeholder(True)

    def _placeholder(self, show: bool) -> None:
        if show and not self.search.get():
            self.search.configure(fg=theme.TEXT_DIM)
            self.search.insert(0, "Search")
            self._showing_placeholder = True
        elif not show and getattr(self, "_showing_placeholder", False):
            self.search.delete(0, "end")
            self.search.configure(fg=theme.TEXT)
            self._showing_placeholder = False

    def _on_search_escape(self, _event=None) -> str:
        self._clear_search()
        return "break"  # keep Escape from also collapsing the window

    def _clear_search(self) -> None:
        self._showing_placeholder = False
        self.search.delete(0, "end")
        self.grid.set_filter("")
        self.root.focus_set()
        self._placeholder(True)

    # ---------------------------------------------------------------- puck UI

    def _build_puck(self) -> None:
        self.puck = tk.Canvas(self.shell, bg=theme.BG, highlightthickness=0, bd=0,
                              cursor="hand2")
        self.puck_tip = Tooltip(self.puck, "")  # carries the name the puck is too small to show
        self.puck.bind("<Configure>", lambda _e: self._draw_puck())
        self.puck.bind("<Button-1>", self._start_move)
        self.puck.bind("<B1-Motion>", self._on_move)
        self.puck.bind("<Double-Button-1>", lambda _e: self.expand())
        self.puck.bind("<Button-3>", self._puck_menu)
        self.puck.bind("<Enter>", lambda _e: self._draw_puck(hover=True))
        self.puck.bind("<Leave>", lambda _e: self._draw_puck(hover=False))

    def _draw_puck(self, hover: bool = False) -> None:
        canvas = self.puck
        size = min(canvas.winfo_width(), canvas.winfo_height())
        if size <= 1:
            return
        compact = size < px(PUCK_COMPACT_BELOW)
        canvas.delete("all")
        pad = max(px(2), size // 24)
        round_rect(canvas, pad, pad, size - pad, size - pad, size // 5,
                   fill=theme.CARD_HOVER if hover else theme.CARD,
                   outline=theme.ACCENT if hover else theme.BORDER, width=1)

        cx = size // 2
        caption_font = theme.FONTS["tiny"]
        caption_h = caption_font.metrics("linespace")
        caption_cy = size - pad - px(3) - caption_h // 2
        if compact:
            # Centre the folder in whatever is left above the caption.
            top, bottom = pad + px(4), caption_cy - caption_h // 2 - px(3)
            cy = (top + bottom) // 2
            half_h = max(px(6), min(int(size * 0.24), (bottom - top) // 2))
            half_w = int(half_h * 1.45)
        else:
            cy = int(size * 0.40)
            half_w, half_h = int(size * 0.26), int(size * 0.19)
        tab_h = max(px(2), size // 14)
        lip = max(px(2), size // 12)
        corner = max(px(2), size // 14)

        round_rect(canvas, cx - half_w, cy - half_h - tab_h, cx - half_w + int(size * 0.20),
                   cy - half_h + lip, max(1, corner // 2), fill="#c9931f", outline="")
        round_rect(canvas, cx - half_w, cy - half_h, cx + half_w, cy + half_h, corner,
                   fill="#d9a326", outline="")
        inset = max(px(2), size // 22)
        round_rect(canvas, cx - half_w + inset, cy - half_h + lip, cx + half_w - inset,
                   cy + half_h, corner, fill=theme.FOLDER, outline="")

        count = self.grid.count()
        limit = 99 if compact else 999
        radius = max(px(7), size // 12)
        badge_x, badge_y = cx + half_w - max(px(1), size // 30), cy - half_h
        canvas.create_oval(badge_x - radius, badge_y - radius, badge_x + radius,
                           badge_y + radius, fill=theme.ACCENT, outline=theme.CARD,
                           width=max(1, px(2)))
        canvas.create_text(badge_x, badge_y, fill="#ffffff",
                           text=str(count) if count <= limit else f"{limit}+",
                           font=theme.FONTS["small" if compact else "badge"])

        label = self.puck_label()
        folder = self.folder_name()
        detail = label if label == folder else f"{label} \u2014 {folder}"
        self.puck_tip.text = f"{detail}, {count} items. Double-click to expand."

        if compact:
            canvas.create_text(cx, caption_cy, fill=theme.TEXT, font=caption_font,
                               text=self._ellipsize(label, size - 2 * pad - px(6), caption_font))
            return
        canvas.create_text(cx, size - px(44), text=self._ellipsize(label, size - px(28)),
                           fill=theme.TEXT, font=theme.FONTS["body"])
        canvas.create_text(cx, size - px(26), text="double-click to expand",
                           fill=theme.TEXT_DIM, font=theme.FONTS["small"])

    @staticmethod
    def _ellipsize(text: str, width: int, font=None) -> str:
        font = font or theme.FONTS["body"]
        if font.measure(text) <= width:
            return text
        while text and font.measure(text + "\u2026") > width:
            text = text[:-1]
        return text + "\u2026"

    def folder_name(self) -> str:
        directory = self.grid.directory
        return os.path.basename(directory.rstrip("\\/")) or directory

    def puck_label(self) -> str:
        """The custom label if set, otherwise the folder name."""
        return self.settings.get("label") or self.folder_name()

    def edit_label(self) -> None:
        current = self.settings.get("label", "")
        answer = simpledialog.askstring(
            "Puck label", "Label shown on the collapsed folder:",
            initialvalue=current or self.folder_name(), parent=self.root)
        if answer is None:
            return
        answer = answer.strip()
        self.settings["label"] = "" if answer == self.folder_name() else answer
        self.store.save_soon()
        self._refresh_label()

    def clear_label(self) -> None:
        self.settings["label"] = ""
        self.store.save_soon()
        self._refresh_label()

    def _refresh_label(self) -> None:
        self.root.title(f"FileGrid \u2014 {self.puck_label()}")
        self.name_label.configure(text=self.puck_label())
        if self.collapsed:
            self._draw_puck()

    def _puck_menu(self, event) -> None:
        menu = tk.Menu(self.root, tearoff=0, bg=theme.CARD, fg=theme.TEXT,
                       activebackground=theme.ACCENT, activeforeground="#ffffff",
                       bd=0, font=theme.FONTS["body"])
        menu.add_command(label="Expand", command=self.expand)
        menu.add_command(label="Rename label\u2026", command=self.edit_label)
        if self.settings.get("label"):
            menu.add_command(label=f"Use folder name ({self.folder_name()})",
                             command=self.clear_label)
        menu.add_command(label="Open in Explorer",
                         command=lambda: winutil.open_path(self.grid.directory))
        menu.add_separator()
        menu.add_command(label="Quit FileGrid", command=self.quit_app)
        menu.tk_popup(event.x_root, event.y_root)

    def _accept_puck_drops(self) -> None:
        try:
            self.puck.drop_target_register(DND_FILES)
            self.puck.dnd_bind("<<Drop>>", self._on_puck_drop)
        except Exception:
            pass

    def _on_puck_drop(self, event) -> None:
        self.expand()
        self.root.after(220, lambda: self.grid.handle_external_drop(event))

    # --------------------------------------------------------- mode switching

    def collapse(self) -> None:
        if self.collapsed or self.animating:
            return
        self._remember_window()
        self.collapsed = True
        self.settings["collapsed"] = True
        self.expanded.pack_forget()
        self.puck.pack(fill="both", expand=True)
        self.root.attributes("-topmost", True)
        self.root.minsize(1, 1)  # the puck is far smaller than the panel minimum
        self._animate_to(self._puck_target(), self._draw_puck)

    def expand(self) -> None:
        if not self.collapsed or self.animating:
            return
        puck = self.settings["puck"]
        puck["x"], puck["y"] = self.root.winfo_x(), self.root.winfo_y()
        self.collapsed = False
        self.settings["collapsed"] = False
        self.store.save_soon()
        window = self.settings["window"]
        target = (window["x"], window["y"], px(window["w"]), px(window["h"]))

        def finish() -> None:
            self.puck.pack_forget()
            self.expanded.pack(fill="both", expand=True)
            self.root.minsize(px(MIN_W), px(MIN_H))
            self._apply_topmost()
            self.root.update_idletasks()
            self.grid.refresh()
            self.root.after(10, lambda: winutil.round_corners(self.root, px(14)))

        self._animate_to(target, finish)

    def _puck_target(self) -> tuple[int, int, int, int]:
        size = px(PUCK_SIZE)
        puck = self.settings["puck"]
        x = puck.get("x", self.root.winfo_x())
        y = puck.get("y", self.root.winfo_y())
        max_x = self.root.winfo_screenwidth() - size
        max_y = self.root.winfo_screenheight() - size
        return max(0, min(x, max_x)), max(0, min(y, max_y)), size, size

    def _puck_geometry(self) -> str:
        x, y, w, h = self._puck_target()
        return f"{w}x{h}+{x}+{y}"

    def _animate_to(self, target, done=None) -> None:
        self.animating = True
        start = (self.root.winfo_x(), self.root.winfo_y(),
                 self.root.winfo_width(), self.root.winfo_height())

        def step(index: int) -> None:
            t = index / ANIM_STEPS
            ease = 1 - (1 - t) ** 3
            x, y, w, h = (int(a + (b - a) * ease) for a, b in zip(start, target))
            self.root.geometry(f"{max(1, w)}x{max(1, h)}+{x}+{y}")
            winutil.round_corners(self.root, px(22) if self.collapsed else px(14))
            if index < ANIM_STEPS:
                self.root.after(ANIM_DELAY, step, index + 1)
            else:
                self.animating = False
                if done:
                    done()

        step(1)

    # ----------------------------------------------------------- window chrome

    def _start_move(self, event) -> None:
        self._move_origin = (event.x_root - self.root.winfo_x(),
                             event.y_root - self.root.winfo_y())

    def _on_move(self, event) -> None:
        origin = getattr(self, "_move_origin", None)
        if not origin or self.animating:
            return
        self.root.geometry(f"+{event.x_root - origin[0]}+{event.y_root - origin[1]}")

    def _on_resize_drag(self, event) -> None:
        width = max(px(MIN_W), event.x_root - self.root.winfo_rootx())
        height = max(px(MIN_H), event.y_root - self.root.winfo_rooty())
        self.root.geometry(f"{width}x{height}")

    def _on_configure(self, event) -> None:
        if event.widget is not self.root:
            return
        winutil.round_corners(self.root, px(22) if self.collapsed else px(14))
        if not self.collapsed and not self.animating:
            self._remember_window()

    def _remember_window(self) -> None:
        if self.collapsed or self.animating:  # would record the puck's geometry
            return
        self.settings["window"] = {
            "x": self.root.winfo_x(), "y": self.root.winfo_y(),
            "w": round(self.root.winfo_width() / theme.SCALE),
            "h": round(self.root.winfo_height() / theme.SCALE),
        }
        self.store.save_soon()

    def _apply_topmost(self) -> None:
        pinned = bool(self.settings.get("topmost"))
        self.root.attributes("-topmost", pinned)
        self.pin_button.set_active(pinned)

    def toggle_topmost(self) -> None:
        self.settings["topmost"] = not self.settings.get("topmost")
        self.store.save_soon()
        self._apply_topmost()

    # -------------------------------------------------------------- commands

    def open_directory(self, directory: str) -> None:
        self.grid.set_directory(directory)
        self._clear_search()
        self._update_heading()

    def browse(self) -> None:
        directory = filedialog.askdirectory(parent=self.root, title="Choose a folder",
                                            initialdir=self.grid.directory)
        if directory:
            self.open_directory(directory)

    def go_up(self) -> None:
        parent = os.path.dirname(self.grid.directory.rstrip("\\/"))
        if parent and os.path.isdir(parent) and parent != self.grid.directory:
            self.open_directory(parent)

    def _update_heading(self) -> None:
        self.name_label.configure(text=self.puck_label())
        self.path_label.configure(text=self.grid.directory)
        self.root.title(f"FileGrid \u2014 {self.puck_label()}")

    def _on_folder_changed(self) -> None:
        if self.collapsed:
            self._draw_puck()

    def _set_status(self, text: str) -> None:
        self.status_label.configure(text=text)
        self._update_heading()

    def _bind_keys(self) -> None:
        self.root.bind("<F5>", lambda _e: self.grid.refresh())
        self.root.bind("<Control-o>", lambda _e: self.browse())
        self.root.bind("<Control-f>", lambda _e: self.search.focus_set())
        self.root.bind("<Control-h>", lambda _e: self.grid.toggle_hidden())
        self.root.bind("<Escape>", lambda _e: self.collapse())
        self.root.bind("<Delete>", self._delete_selected)
        self.root.bind("<Return>", self._open_selected)

    def _delete_selected(self, _event=None) -> None:
        if self.grid.selected and self.root.focus_get() is not self.search:
            self.grid.delete_item(self.grid.selected)

    def _open_selected(self, _event=None) -> None:
        if self.grid.selected and self.root.focus_get() is not self.search:
            self.grid.open_item(self.grid.selected)

    def quit_app(self) -> None:
        if self.collapsed:
            puck = self.settings["puck"]
            puck["x"], puck["y"] = self.root.winfo_x(), self.root.winfo_y()
        else:
            self._remember_window()
        self.store.save()
        self.store.release()
        self.root.destroy()

    def run(self) -> None:
        self.root.mainloop()


def main() -> None:
    FileGridApp().run()
