"""The visual grid: one draggable tile per file, positions remembered per folder."""

from __future__ import annotations

import os
import shutil
import tkinter as tk
from dataclasses import dataclass
from tkinter import messagebox, simpledialog

from . import theme, winutil
from .icons import IconProvider
from .theme import px

POLL_MS = 2000
DRAG_THRESHOLD = 4
ROW_BUFFER = 6


@dataclass
class Entry:
    name: str
    path: str
    is_dir: bool
    size: int
    mtime: float


def round_rect(canvas: tk.Canvas, x1, y1, x2, y2, r, **kw):
    points = [
        x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r,
        x2, y2 - r, x2, y2, x2 - r, y2, x1 + r, y2,
        x1, y2, x1, y2 - r, x1, y1 + r, x1, y1,
    ]
    return canvas.create_polygon(points, smooth=True, **kw)


class GridView(tk.Frame):
    def __init__(self, master, store, on_status=None, on_navigate=None, on_changed=None,
                 folder_actions=()):
        super().__init__(master, bg=theme.PANEL)
        self.store = store
        self.on_status = on_status
        self.on_navigate = on_navigate
        self.on_changed = on_changed
        self.folder_actions = folder_actions

        self.cell_w = px(112)
        self.cell_h = px(118)
        self.pad = px(16)
        self.radius = px(10)
        self.icon_size = px(52)

        self.directory = ""
        self.entries: dict[str, Entry] = {}
        self.pos: dict[str, tuple[int, int]] = {}
        self.items: dict[str, dict] = {}
        self.tags: dict[str, str] = {}
        self._labels: dict[str, str] = {}
        self._drawn_rows: range | None = None
        self._wheel_delta = 0
        self._wheel_job = None
        self.cols = 1
        self.filter_text = ""
        self.show_hidden = bool(store.data.get("show_hidden"))
        self.selected: str | None = None
        self.hovered: str | None = None
        self.drag: dict | None = None
        self._signature = None
        self._poll_job = None

        self.canvas = tk.Canvas(self, bg=theme.PANEL, highlightthickness=0, bd=0,
                                yscrollincrement=px(18))
        self.canvas.pack(side="left", fill="both", expand=True)
        self.track = tk.Canvas(self, bg=theme.PANEL, highlightthickness=0, bd=0, width=px(10))
        self.track.pack(side="right", fill="y")

        self.icons = IconProvider(self.canvas, self.icon_size)
        self._image_refs: dict[str, object] = {}

        self.canvas.bind("<Configure>", self._on_resize)
        self.canvas.bind("<Motion>", self._on_motion)
        self.canvas.bind("<Leave>", lambda _e: self._set_hover(None))
        self.canvas.bind("<Button-1>", self._on_press)
        self.canvas.bind("<B1-Motion>", self._on_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_release)
        self.canvas.bind("<Double-Button-1>", self._on_double)
        self.canvas.bind("<Button-3>", self._on_right_click)
        self.canvas.bind("<MouseWheel>", self._on_wheel)
        self.canvas.configure(yscrollcommand=self._on_yscroll)

        self.track.bind("<Button-1>", self._on_thumb_press)
        self.track.bind("<B1-Motion>", self._on_thumb_drag)
        self.bind("<Destroy>", self._on_destroy)

        self.menu = tk.Menu(self, tearoff=0, bg=theme.CARD, fg=theme.TEXT,
                            activebackground=theme.ACCENT, activeforeground="#ffffff",
                            bd=0, font=theme.FONTS["body"])

    # ---------------------------------------------------------------- loading

    def set_directory(self, directory: str) -> None:
        directory = os.path.abspath(directory)
        if not os.path.isdir(directory):
            messagebox.showerror("FileGrid", f"Folder not found:\n{directory}", parent=self)
            return
        self.directory = directory
        self.store.instance["directory"] = directory
        self.selected = None
        self.hovered = None
        self.canvas.yview_moveto(0)
        self.refresh()
        self.store.save_soon()

    def refresh(self) -> None:
        self._scan()
        self._assign_positions()
        self._redraw()
        self._emit_status()
        self._schedule_poll()

    def _scan(self) -> None:
        entries: dict[str, Entry] = {}
        try:
            with os.scandir(self.directory) as it:
                for item in it:
                    if not self.show_hidden and self._is_hidden(item):
                        continue
                    try:
                        stat = item.stat()
                        size, mtime = stat.st_size, stat.st_mtime
                    except OSError:
                        size, mtime = 0, 0.0
                    entries[item.name] = Entry(item.name, item.path, item.is_dir(), size, mtime)
        except OSError as exc:
            messagebox.showerror("FileGrid", f"Cannot read folder:\n{exc}", parent=self)
        self.entries = entries
        self._signature = self._make_signature()

    @staticmethod
    def _is_hidden(item) -> bool:
        if item.name.startswith("."):
            return True
        try:
            return bool(item.stat().st_file_attributes & 0x2)  # FILE_ATTRIBUTE_HIDDEN
        except (OSError, AttributeError):
            return False

    def _make_signature(self):
        return frozenset((e.name, e.mtime, e.size, e.is_dir) for e in self.entries.values())

    # ------------------------------------------------------------- placement

    def _saved(self) -> dict:
        return self.store.layout(self.directory)

    def _assign_positions(self) -> None:
        self.cols = self._column_count()
        saved = self._saved()["tiles"]
        placed: dict[str, tuple[int, int]] = {}
        taken: set[tuple[int, int]] = set()

        for name in self.entries:
            spot = saved.get(name)
            if spot and 0 <= spot[0] < self.cols and tuple(spot) not in taken:
                placed[name] = (int(spot[0]), int(spot[1]))
                taken.add(placed[name])

        for name in self._sorted_names():
            if name in placed:
                continue
            placed[name] = self._first_free(taken)
            taken.add(placed[name])
            # A tile displaced by a narrow window keeps its saved spot and
            # returns to it once there is room again.
            if name not in saved:
                saved[name] = list(placed[name])

        self.pos = placed
        if len(saved) > 500:  # forget positions of files that are long gone
            for name in [n for n in saved if n not in self.entries]:
                saved.pop(name, None)
        self.store.save_soon()

    def _sorted_names(self) -> list[str]:
        return sorted(self.entries, key=lambda n: (not self.entries[n].is_dir, n.lower()))

    def _column_count(self) -> int:
        width = self.canvas.winfo_width()
        if width <= 1:  # not laid out yet: at startup, or while collapsed
            width = px(self.store.instance["window"]["w"]) - px(24)
        return max(1, (width - 2 * self.pad) // self.cell_w)

    def _first_free(self, taken: set[tuple[int, int]]) -> tuple[int, int]:
        row = 0
        while True:
            for col in range(self.cols):
                if (col, row) not in taken:
                    return (col, row)
            row += 1

    def arrange(self) -> None:
        """Reflow every tile into sorted, gap-free order."""
        saved = self._saved()["tiles"]
        for index, name in enumerate(self._sorted_names()):
            spot = (index % self.cols, index // self.cols)
            self.pos[name] = spot
            saved[name] = list(spot)
        self.store.save_soon()
        self._redraw()

    def _move_tile(self, name: str, target: tuple[int, int]) -> None:
        occupant = next((n for n, p in self.pos.items() if p == target and n != name), None)
        origin = self.pos[name]
        self.pos[name] = target
        if occupant:
            self.pos[occupant] = origin
        saved = self._saved()["tiles"]
        saved[name] = list(target)
        if occupant:
            saved[occupant] = list(origin)
        self.store.save_soon()

    # ---------------------------------------------------------------- drawing

    def _cell_xy(self, col: int, row: int) -> tuple[int, int]:
        return self.pad + col * self.cell_w, self.pad + row * self.cell_h

    def _cell_at(self, x: float, y: float) -> tuple[int, int] | None:
        col = int((x - self.pad) // self.cell_w)
        row = int((y - self.pad) // self.cell_h)
        if col < 0 or row < 0 or col >= self.cols:
            return None
        return col, row

    def _tile_at(self, x: float, y: float) -> str | None:
        cell = self._cell_at(x, y)
        if cell is None:
            return None
        for name in self._visible():
            if self.pos.get(name) == cell:
                return name
        return None

    def _visible(self) -> list[str]:
        if not self.filter_text:
            return list(self.entries)
        needle = self.filter_text.lower()
        return [n for n in self.entries if needle in n.lower()]

    def _rows_needed(self) -> int:
        rows = max((p[1] for p in self.pos.values()), default=-1) + 1
        viewport = max(1, self.canvas.winfo_height() // self.cell_h)
        return max(rows + 1, viewport)

    def _row_window(self, rows: int, buffer: int) -> range:
        """Rows near the viewport; a buffer keeps scrolling free of redraws."""
        top = self.canvas.canvasy(0)
        bottom = top + max(self.canvas.winfo_height(), self.cell_h)
        first = max(0, int((top - self.pad) // self.cell_h) - buffer)
        last = min(rows, int((bottom - self.pad) // self.cell_h) + 1 + buffer)
        return range(first, max(first, last))

    def _maybe_redraw(self) -> None:
        """Repaint only once the viewport scrolls past the drawn band."""
        needed = self._row_window(self._rows_needed(), 0)
        drawn = self._drawn_rows
        if drawn and needed.start >= drawn.start and needed.stop <= drawn.stop:
            self._draw_thumb()
        else:
            self._redraw()

    def _redraw(self) -> None:
        canvas = self.canvas
        canvas.delete("all")
        self.items.clear()
        self._image_refs.clear()

        rows = self._rows_needed()
        window = self._row_window(rows, ROW_BUFFER)
        self._drawn_rows = window
        names = [n for n in sorted(self._visible(), key=lambda n: self.pos.get(n, (0, 0))[::-1])
                 if self.pos[n][1] in window]
        occupied = {self.pos[n] for n in names}

        for row in window:
            for col in range(self.cols):
                if (col, row) in occupied:
                    continue
                x, y = self._cell_xy(col, row)
                round_rect(canvas, x + px(3), y + px(3), x + self.cell_w - px(3),
                           y + self.cell_h - px(3), self.radius,
                           fill=theme.CELL_EMPTY, outline=theme.BORDER_SOFT, width=1)

        for name in names:
            self._draw_tile(name)

        height = self.pad * 2 + rows * self.cell_h
        canvas.configure(scrollregion=(0, 0, self.pad * 2 + self.cols * self.cell_w, height))
        self._draw_thumb()

    def _draw_tile(self, name: str) -> None:
        canvas = self.canvas
        entry = self.entries[name]
        col, row = self.pos[name]
        x, y = self._cell_xy(col, row)
        tag = self.tags.setdefault(name, f"tile{len(self.tags)}")
        cx = x + self.cell_w // 2

        selected = name == self.selected
        fill = theme.CARD_SELECTED if selected else theme.CARD
        outline = theme.ACCENT if selected else theme.BORDER

        bg = round_rect(canvas, x + px(3), y + px(3), x + self.cell_w - px(3),
                        y + self.cell_h - px(3), self.radius,
                        fill=fill, outline=outline, width=1, tags=(tag, "tile"))

        icon_cy = y + px(12) + self.icon_size // 2
        image = self.icons.get(entry.path, entry.is_dir)
        if image is not None:
            self._image_refs[name] = image
            canvas.create_image(cx, icon_cy, image=image, tags=(tag, "tile"))
        else:
            self._draw_fallback_icon(cx, icon_cy, entry, tag)

        label = self._label(name)
        canvas.create_text(cx, y + px(16) + self.icon_size + px(6), text=label, anchor="n",
                           justify="center", fill=theme.TEXT if selected else theme.TEXT_MUTED,
                           font=theme.FONTS["tile"], tags=(tag, "tile"))

        self.items[name] = {"tag": tag, "bg": bg}

    def _draw_fallback_icon(self, cx: int, cy: int, entry: Entry, tag: str) -> None:
        canvas = self.canvas
        half_w, half_h = self.icon_size // 2 - px(6), self.icon_size // 2
        if entry.is_dir:
            round_rect(canvas, cx - half_w, cy - half_h + px(6), cx + half_w, cy + half_h,
                       px(5), fill=theme.FOLDER, outline="", tags=(tag, "tile"))
            round_rect(canvas, cx - half_w, cy - half_h, cx - px(2), cy - half_h + px(12),
                       px(3), fill=theme.FOLDER, outline="", tags=(tag, "tile"))
            return
        ext = os.path.splitext(entry.name)[1]
        color = theme.color_for(ext)
        round_rect(canvas, cx - half_w, cy - half_h, cx + half_w, cy + half_h, px(5),
                   fill=theme.CARD_HOVER, outline=color, width=px(2), tags=(tag, "tile"))
        canvas.create_text(cx, cy + px(4), text=(ext[1:5] or "file").upper(),
                           fill=color, font=theme.FONTS["small"], tags=(tag, "tile"))

    def _label(self, name: str) -> str:
        """Wrapping costs one Tcl round trip per character, so results are cached."""
        label = self._labels.get(name)
        if label is None:
            if len(self._labels) > 4000:
                self._labels.clear()
            label = "\n".join(self._wrap(name, self.cell_w - px(16)))
            self._labels[name] = label
        return label

    def _wrap(self, text: str, width: int, max_lines: int = 2) -> list[str]:
        font = theme.FONTS["tile"]
        if font.measure(text) <= width:
            return [text]
        lines: list[str] = []
        current = ""
        overflow = False
        for char in text:
            if font.measure(current + char) <= width:
                current += char
                continue
            lines.append(current)
            current = char
            if len(lines) == max_lines:
                overflow = True
                break
        if not overflow:
            if current:
                lines.append(current)
            return lines or [text]

        tail = "\u2026" + os.path.splitext(text)[1][:6]
        last = lines[-1]
        while last and font.measure(last + tail) > width:
            last = last[:-1]
        lines[-1] = last + tail
        return lines

    def _restyle(self, name: str, hovered: bool) -> None:
        item = self.items.get(name)
        if not item:
            return
        selected = name == self.selected
        fill = theme.CARD_SELECTED if selected else theme.CARD_HOVER if hovered else theme.CARD
        self.canvas.itemconfigure(item["bg"], fill=fill,
                                  outline=theme.ACCENT if selected else theme.BORDER)

    # -------------------------------------------------------------- scrollbar

    def _on_yscroll(self, first, last) -> None:
        self._scroll_fraction = (float(first), float(last))
        self._draw_thumb()

    def _draw_thumb(self) -> None:
        first, last = getattr(self, "_scroll_fraction", (0.0, 1.0))
        self.track.delete("all")
        height = self.track.winfo_height()
        if height <= 1 or last - first >= 0.999:
            return
        top = first * height
        bottom = max(last * height, top + px(24))
        round_rect(self.track, px(3), top + px(2), px(7), bottom - px(2), px(2),
                   fill=theme.BORDER, outline="")

    def _on_thumb_press(self, event) -> None:
        self._on_thumb_drag(event)

    def _on_thumb_drag(self, event) -> None:
        self.canvas.yview_moveto(max(0.0, event.y / max(1, self.track.winfo_height()) - 0.1))
        self._maybe_redraw()

    def _on_wheel(self, event) -> None:
        """Wheel notches are merged into one scroll per frame; a canvas repaint
        costs more than the notches arrive."""
        self._wheel_delta += event.delta
        if self._wheel_job is None:
            self._wheel_job = self.after(16, self._flush_wheel)

    def _flush_wheel(self) -> None:
        self._wheel_job = None
        delta, self._wheel_delta = self._wheel_delta, 0
        if not delta:
            return
        self.canvas.yview_scroll(-int(delta / 40) or (-1 if delta > 0 else 1), "units")
        self._maybe_redraw()

    # ----------------------------------------------------------------- events

    def _canvas_xy(self, event) -> tuple[float, float]:
        return self.canvas.canvasx(event.x), self.canvas.canvasy(event.y)

    def _on_resize(self, _event) -> None:
        cols = self._column_count()
        if cols != self.cols:
            self.cols = cols
            self._assign_positions()
        self._redraw()

    def _set_hover(self, name: str | None) -> None:
        if name == self.hovered:
            return
        if self.hovered:
            self._restyle(self.hovered, False)
        self.hovered = name
        if name:
            self._restyle(name, True)
        self.canvas.configure(cursor="hand2" if name else "")

    def _on_motion(self, event) -> None:
        if self.drag:
            return
        self._set_hover(self._tile_at(*self._canvas_xy(event)))

    def _on_press(self, event) -> None:
        x, y = self._canvas_xy(event)
        name = self._tile_at(x, y)
        previous, self.selected = self.selected, name
        for other in {previous, name} - {None}:
            self._restyle(other, other == self.hovered)
        self._emit_status()
        if not name:
            self.drag = None
            return
        col, row = self.pos[name]
        cell_x, cell_y = self._cell_xy(col, row)
        self.drag = {"name": name, "dx": x - cell_x, "dy": y - cell_y,
                     "x": x, "y": y, "active": False}

    def _on_drag(self, event) -> None:
        if not self.drag:
            return
        x, y = self._canvas_xy(event)
        name = self.drag["name"]
        if not self.drag["active"]:
            if abs(x - self.drag["x"]) < DRAG_THRESHOLD and abs(y - self.drag["y"]) < DRAG_THRESHOLD:
                return
            self.drag["active"] = True
            self.canvas.configure(cursor="fleur")
            self.canvas.tag_raise(self.items[name]["tag"])
        self.canvas.move(self.items[name]["tag"], x - self.drag["x"], y - self.drag["y"])
        self.drag["x"], self.drag["y"] = x, y
        self._show_dropzone(self._cell_at(x - self.drag["dx"] + self.cell_w / 2,
                                          y - self.drag["dy"] + self.cell_h / 2))

    def _on_release(self, event) -> None:
        drag, self.drag = self.drag, None
        self.canvas.delete("dropzone")
        self.canvas.configure(cursor="hand2")
        if not drag or not drag["active"]:
            return
        x, y = self._canvas_xy(event)
        target = self._cell_at(x - drag["dx"] + self.cell_w / 2, y - drag["dy"] + self.cell_h / 2)
        if target:
            self._move_tile(drag["name"], target)
        self._redraw()

    def _show_dropzone(self, cell) -> None:
        self.canvas.delete("dropzone")
        if not cell:
            return
        x, y = self._cell_xy(*cell)
        item = round_rect(self.canvas, x + px(3), y + px(3), x + self.cell_w - px(3),
                          y + self.cell_h - px(3), self.radius, fill=theme.DROPZONE,
                          outline=theme.ACCENT, width=1, tags="dropzone")
        self.canvas.tag_lower(item, "tile")

    def _on_double(self, event) -> None:
        name = self._tile_at(*self._canvas_xy(event))
        if not name:
            return
        entry = self.entries[name]
        if entry.is_dir and self.on_navigate:
            self.on_navigate(entry.path)
        else:
            self.open_item(name)

    def _on_right_click(self, event) -> None:
        name = self._tile_at(*self._canvas_xy(event))
        self.selected = name
        self._redraw()
        self.menu.delete(0, "end")
        if name:
            entry = self.entries[name]
            self.menu.add_command(label="Open", command=lambda: self.open_item(name))
            if entry.is_dir and self.on_navigate:
                self.menu.add_command(label="Open in grid",
                                      command=lambda: self.on_navigate(entry.path))
            self.menu.add_command(label="Show in Explorer", command=lambda: winutil.reveal(entry.path))
            self.menu.add_separator()
            self.menu.add_command(label="Copy path", command=lambda: self._copy_path(name))
            self.menu.add_command(label="Rename\u2026", command=lambda: self._rename(name))
            self.menu.add_command(label="Delete", command=lambda: self.delete_item(name))
        else:
            self.menu.add_command(label="Auto-arrange tiles", command=self.arrange)
            self.menu.add_command(label="Refresh", command=self.refresh)
            self.menu.add_command(label="Open folder in Explorer",
                                  command=lambda: winutil.open_path(self.directory))
            if self.folder_actions:
                self.menu.add_separator()
            for label, action in self.folder_actions:
                self.menu.add_command(label=label, command=action)
        self.menu.tk_popup(event.x_root, event.y_root)

    # ---------------------------------------------------------------- actions

    def open_item(self, name: str) -> None:
        try:
            winutil.open_path(self.entries[name].path)
        except OSError as exc:
            messagebox.showerror("FileGrid", str(exc), parent=self)

    def _copy_path(self, name: str) -> None:
        self.clipboard_clear()
        self.clipboard_append(self.entries[name].path)

    def _rename(self, name: str) -> None:
        new_name = simpledialog.askstring("Rename", "New name:", initialvalue=name, parent=self)
        if not new_name or new_name == name:
            return
        target = os.path.join(self.directory, new_name)
        try:
            os.rename(self.entries[name].path, target)
        except OSError as exc:
            messagebox.showerror("FileGrid", str(exc), parent=self)
            return
        saved = self._saved()["tiles"]
        if name in saved:
            saved[new_name] = saved.pop(name)
        self.selected = new_name
        self.refresh()

    def delete_item(self, name: str) -> None:
        if not messagebox.askyesno("FileGrid", f"Move to Recycle Bin?\n\n{name}", parent=self):
            return
        if not winutil.recycle(self.entries[name].path):
            messagebox.showerror("FileGrid", f"Could not delete {name}.", parent=self)
        self._saved()["tiles"].pop(name, None)
        self.selected = None
        self.refresh()

    def set_filter(self, text: str) -> None:
        self.filter_text = text.strip()
        self._redraw()
        self._emit_status()

    def toggle_hidden(self) -> bool:
        self.show_hidden = not self.show_hidden
        self.store.data["show_hidden"] = self.show_hidden
        self.refresh()
        return self.show_hidden

    # ----------------------------------------------------------- drop targets

    def accept_drops(self, dnd_files) -> None:
        try:
            self.canvas.drop_target_register(dnd_files)
            self.canvas.dnd_bind("<<Drop>>", self.handle_external_drop)
        except Exception:
            pass

    def handle_external_drop(self, event) -> None:
        try:
            paths = self.tk.splitlist(event.data)
        except Exception:
            return
        cell = self._cell_at(self.canvas.canvasx(event.x_root - self.canvas.winfo_rootx()),
                             self.canvas.canvasy(event.y_root - self.canvas.winfo_rooty()))
        incoming = [p for p in paths if os.path.exists(p)]
        outside = [p for p in incoming
                   if os.path.normcase(os.path.dirname(p)) != os.path.normcase(self.directory)]
        if outside:
            names = "\n".join(os.path.basename(p) for p in outside[:8])
            if not messagebox.askyesno(
                "FileGrid", f"Move {len(outside)} item(s) into\n{self.directory}?\n\n{names}",
                parent=self,
            ):
                return
            for path in outside:
                try:
                    shutil.move(path, os.path.join(self.directory, os.path.basename(path)))
                except OSError as exc:
                    messagebox.showerror("FileGrid", str(exc), parent=self)
        self.refresh()
        if cell and incoming:
            name = os.path.basename(incoming[0])
            if name in self.pos:
                self._move_tile(name, cell)
                self.selected = name
                self._redraw()

    # ----------------------------------------------------------------- status

    def _emit_status(self) -> None:
        if not self.on_status:
            return
        files = sum(1 for e in self.entries.values() if not e.is_dir)
        folders = len(self.entries) - files
        total = sum(e.size for e in self.entries.values() if not e.is_dir)
        parts = [f"{files} files", f"{folders} folders", _human(total)]
        if self.filter_text:
            parts.append(f"{len(self._visible())} matching \u201c{self.filter_text}\u201d")
        if self.selected:
            entry = self.entries.get(self.selected)
            if entry:
                parts.append(entry.name if entry.is_dir else f"{entry.name} \u2014 {_human(entry.size)}")
        self.on_status("   \u00b7   ".join(parts))

    def count(self) -> int:
        return len(self.entries)

    # ------------------------------------------------------------- background

    def _on_destroy(self, event) -> None:
        if event.widget is not self:
            return
        for job in (self._poll_job, self._wheel_job):
            if job:
                try:
                    self.after_cancel(job)
                except Exception:
                    pass
        self._poll_job = self._wheel_job = None

    def _schedule_poll(self) -> None:
        if self._poll_job:
            self.after_cancel(self._poll_job)
        self._poll_job = self.after(POLL_MS, self._poll)

    def _poll(self) -> None:
        self._poll_job = None
        if self.drag:
            self._schedule_poll()
            return
        try:
            previous = self._signature
            self._scan()
            if self._signature == previous:
                return
            # While collapsed the canvas has no usable width, so leave placement
            # alone and let the next expand lay tiles out.
            if self.winfo_ismapped():
                self._assign_positions()
                self._redraw()
                self._emit_status()
            if self.on_changed:
                self.on_changed()
        finally:
            self._schedule_poll()


def _human(size: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return ""
