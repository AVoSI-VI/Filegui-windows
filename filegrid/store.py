"""Persisted app state, shared safely by several running panels.

Each panel claims a numbered slot (held with a lock file for as long as the
process lives) and owns only its own entry in %APPDATA%\\FileGrid\\state.json.
Saves re-read the file under a lock and merge, so two panels cannot clobber
each other. Grid layouts stay keyed by folder, which is what makes a folder
look the same in whichever panel opens it.
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path

try:
    import msvcrt
except ImportError:  # pragma: no cover - non-Windows fallback
    msvcrt = None

APP_NAME = "FileGrid"
SAVE_DELAY_MS = 500
MAX_SLOTS = 16
CASCADE = 34
LOCK_TIMEOUT = 2.0


def config_dir() -> Path:
    """%APPDATA%\\FileGrid, or FILEGRID_STATE_DIR so tests stay out of real state."""
    override = os.environ.get("FILEGRID_STATE_DIR")
    if override:
        folder = Path(override)
    else:
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
        folder = Path(base) / APP_NAME
    (folder / "locks").mkdir(parents=True, exist_ok=True)
    return folder


def default_instance(slot: int) -> dict:
    step = (slot - 1) * CASCADE
    return {
        "directory": str(Path.home() / "Downloads"),
        "label": "",
        "window": {"x": 220 + step, "y": 140 + step, "w": 940, "h": 640},
        "puck": {"x": 220 + step, "y": 140 + step},
        "collapsed": False,
        "topmost": False,
    }


def _default_state() -> dict:
    return {"version": 2, "instances": {}, "layouts": {}, "show_hidden": False}


def _try_lock(fd: int) -> bool:
    if msvcrt is None:
        return True
    try:
        msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        return True
    except OSError:
        return False


def _unlock(fd: int) -> None:
    if msvcrt is None:
        return
    try:
        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
    except OSError:
        pass


@contextmanager
def _exclusive(path: Path, timeout: float = LOCK_TIMEOUT):
    """Cross-process lock. Falls back to proceeding unlocked rather than hanging."""
    fd = os.open(str(path), os.O_CREAT | os.O_RDWR)
    locked = False
    deadline = time.monotonic() + timeout
    try:
        while not (locked := _try_lock(fd)) and time.monotonic() < deadline:
            time.sleep(0.02)
        yield
    finally:
        if locked:
            _unlock(fd)
        os.close(fd)


def _read(path: Path) -> dict:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return _default_state()
    return _migrate(raw) if isinstance(raw, dict) else _default_state()


def _migrate(raw: dict) -> dict:
    state = _default_state()
    state["layouts"] = raw.get("layouts") or {}
    state["show_hidden"] = bool(raw.get("show_hidden"))
    if isinstance(raw.get("instances"), dict):
        state["instances"] = raw["instances"]
        return state
    if any(key in raw for key in ("directory", "window", "puck")):  # v1 single-panel file
        first = default_instance(1)
        for key in ("directory", "window", "puck", "collapsed", "topmost"):
            if key in raw:
                first[key] = raw[key]
        state["instances"]["1"] = first
    return state


class Store:
    def __init__(self):
        self.dir = config_dir()
        self.path = self.dir / "state.json"
        self.lock_path = self.dir / "state.lock"
        self._slot_fd: int | None = None
        self.slot = self._claim_slot()
        self.data = _read(self.path)
        self._widget = None
        self._pending = None
        self._dirty: set[str] = set()

    def _claim_slot(self) -> str:
        for slot in range(1, MAX_SLOTS + 1):
            fd = os.open(str(self.dir / "locks" / f"slot{slot}.lock"), os.O_CREAT | os.O_RDWR)
            if _try_lock(fd):
                self._slot_fd = fd
                return str(slot)
            os.close(fd)
        return str(MAX_SLOTS)  # more panels than slots: share the last one

    @property
    def instance(self) -> dict:
        instances = self.data.setdefault("instances", {})
        entry = instances.get(self.slot)
        if entry is None:
            entry = instances[self.slot] = default_instance(int(self.slot))
        for key, value in default_instance(int(self.slot)).items():
            entry.setdefault(key, value)
        return entry

    def bind(self, widget) -> None:
        """Give the store a Tk widget so saves can be debounced on the event loop."""
        self._widget = widget

    def layout(self, directory: str) -> dict:
        key = os.path.normcase(os.path.abspath(directory))
        entry = self.data.setdefault("layouts", {}).setdefault(key, {})
        entry.setdefault("tiles", {})
        self._dirty.add(key)
        return entry

    def save_soon(self) -> None:
        if self._widget is None:
            self.save()
            return
        self._cancel_pending()
        self._pending = self._widget.after(SAVE_DELAY_MS, self.save)

    def _cancel_pending(self) -> None:
        if self._pending is not None and self._widget is not None:
            try:
                self._widget.after_cancel(self._pending)
            except Exception:
                pass
        self._pending = None

    def save(self) -> None:
        self._cancel_pending()
        try:
            with _exclusive(self.lock_path):
                merged = _read(self.path)
                merged.setdefault("instances", {})[self.slot] = self.instance
                layouts = merged.setdefault("layouts", {})
                for key in self._dirty:
                    if key in self.data.get("layouts", {}):
                        layouts[key] = self.data["layouts"][key]
                merged["show_hidden"] = self.data.get("show_hidden", False)
                _prune(merged)
                self._write(merged)
            self.data = merged
            self._dirty.clear()
        except Exception:
            pass

    def _write(self, state: dict) -> None:
        handle, tmp = tempfile.mkstemp(dir=str(self.path.parent), suffix=".tmp")
        with os.fdopen(handle, "w", encoding="utf-8") as fh:
            json.dump(state, fh, indent=1)
        os.replace(tmp, self.path)

    def release(self) -> None:
        if self._slot_fd is not None:
            _unlock(self._slot_fd)
            os.close(self._slot_fd)
            self._slot_fd = None


def _prune(state: dict, keep: int = 60) -> None:
    layouts = state.get("layouts", {})
    in_use = {os.path.normcase(os.path.abspath(i.get("directory", "")))
              for i in state.get("instances", {}).values()}
    for key in [k for k, v in layouts.items() if not v.get("tiles")]:
        layouts.pop(key, None)
    for key in list(layouts):
        if len(layouts) <= keep:
            break
        if key not in in_use:
            layouts.pop(key)
