"""Thin ctypes wrappers around the Win32 bits the UI needs."""

from __future__ import annotations

import ctypes
import os
import subprocess
from ctypes import wintypes

user32 = ctypes.WinDLL("user32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
shell32 = ctypes.WinDLL("shell32", use_last_error=True)

user32.GetParent.restype = ctypes.c_void_p
user32.GetParent.argtypes = [ctypes.c_void_p]
user32.GetWindowLongW.restype = ctypes.c_long
user32.GetWindowLongW.argtypes = [ctypes.c_void_p, ctypes.c_int]
user32.SetWindowLongW.restype = ctypes.c_long
user32.SetWindowLongW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_long]
user32.SetWindowRgn.restype = ctypes.c_int
user32.SetWindowRgn.argtypes = [ctypes.c_void_p, ctypes.c_void_p, wintypes.BOOL]
gdi32.CreateRoundRectRgn.restype = ctypes.c_void_p
gdi32.CreateRoundRectRgn.argtypes = [ctypes.c_int] * 6

GWL_EXSTYLE = -20
WS_EX_APPWINDOW = 0x00040000
WS_EX_TOOLWINDOW = 0x00000080


def enable_dpi_awareness() -> None:
    """Must run before the Tk root exists so Windows does not bitmap-stretch us."""
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        try:
            user32.SetProcessDPIAware()
        except Exception:
            pass


def system_scale() -> float:
    try:
        return max(1.0, user32.GetDpiForSystem() / 96.0)
    except Exception:
        return 1.0


def hwnd_of(widget) -> int:
    hwnd = user32.GetParent(widget.winfo_id())
    return hwnd or widget.winfo_id()


_applied_regions: dict[int, tuple[int, int, int]] = {}


def round_corners(widget, radius: int) -> None:
    """Clip a borderless window to a rounded rectangle.

    SetWindowRgn emits another WM_WINDOWPOSCHANGED, so reapplying it for an
    unchanged size would spin the Tk event loop.
    """
    try:
        w, h = widget.winfo_width(), widget.winfo_height()
        if w <= 1 or h <= 1:
            return
        hwnd = hwnd_of(widget)
        if _applied_regions.get(hwnd) == (w, h, radius):
            return
        _applied_regions[hwnd] = (w, h, radius)
        region = gdi32.CreateRoundRectRgn(0, 0, w + 1, h + 1, radius, radius)
        user32.SetWindowRgn(hwnd, region, True)
    except Exception:
        pass


def show_in_taskbar(widget) -> None:
    """Borderless windows are tool windows by default, which hides them from the taskbar."""
    try:
        hwnd = hwnd_of(widget)
        style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        style = (style & ~WS_EX_TOOLWINDOW) | WS_EX_APPWINDOW
        user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style)
        widget.withdraw()
        widget.after(10, widget.deiconify)
    except Exception:
        pass


class _SHFILEOPSTRUCT(ctypes.Structure):
    _fields_ = [
        ("hwnd", ctypes.c_void_p),
        ("wFunc", wintypes.UINT),
        ("pFrom", wintypes.LPCWSTR),
        ("pTo", wintypes.LPCWSTR),
        ("fFlags", ctypes.c_uint16),
        ("fAnyOperationsAborted", wintypes.BOOL),
        ("hNameMappings", ctypes.c_void_p),
        ("lpszProgressTitle", wintypes.LPCWSTR),
    ]


FO_DELETE = 0x0003
FOF_ALLOWUNDO = 0x0040
FOF_NOCONFIRMATION = 0x0010
FOF_SILENT = 0x0004


def recycle(path: str) -> bool:
    """Delete via the shell so the file lands in the Recycle Bin."""
    op = _SHFILEOPSTRUCT(
        hwnd=None,
        wFunc=FO_DELETE,
        pFrom=path + "\0\0",
        pTo=None,
        fFlags=FOF_ALLOWUNDO | FOF_NOCONFIRMATION | FOF_SILENT,
        fAnyOperationsAborted=False,
        hNameMappings=None,
        lpszProgressTitle=None,
    )
    shell32.SHFileOperationW.argtypes = [ctypes.POINTER(_SHFILEOPSTRUCT)]
    return shell32.SHFileOperationW(ctypes.byref(op)) == 0 and not op.fAnyOperationsAborted


def reveal(path: str) -> None:
    subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])


def open_path(path: str) -> None:
    os.startfile(path)  # noqa: S606 - intentional shell-verb launch
