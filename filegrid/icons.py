"""Real Windows shell icons and image thumbnails, cached per extension/file.

Everything degrades to ``None`` when Pillow is unavailable or the shell call
fails; the grid then paints its own vector tile instead.
"""

from __future__ import annotations

import ctypes
import os
from ctypes import wintypes

try:
    from PIL import Image, ImageTk

    HAVE_PIL = True
except Exception:  # pragma: no cover - optional dependency
    HAVE_PIL = False

user32 = ctypes.WinDLL("user32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
shell32 = ctypes.WinDLL("shell32", use_last_error=True)

user32.GetDC.restype = ctypes.c_void_p
user32.GetDC.argtypes = [ctypes.c_void_p]
user32.ReleaseDC.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
user32.DrawIconEx.argtypes = [
    ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_void_p,
    ctypes.c_int, ctypes.c_int, ctypes.c_uint, ctypes.c_void_p, ctypes.c_uint,
]
user32.DestroyIcon.argtypes = [ctypes.c_void_p]
gdi32.CreateCompatibleDC.restype = ctypes.c_void_p
gdi32.CreateCompatibleDC.argtypes = [ctypes.c_void_p]
gdi32.CreateDIBSection.restype = ctypes.c_void_p
gdi32.CreateDIBSection.argtypes = [
    ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint,
    ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p, ctypes.c_uint,
]
gdi32.SelectObject.restype = ctypes.c_void_p
gdi32.SelectObject.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
gdi32.DeleteObject.argtypes = [ctypes.c_void_p]
gdi32.DeleteDC.argtypes = [ctypes.c_void_p]


class _SHFILEINFO(ctypes.Structure):
    _fields_ = [
        ("hIcon", ctypes.c_void_p),
        ("iIcon", ctypes.c_int),
        ("dwAttributes", wintypes.DWORD),
        ("szDisplayName", ctypes.c_wchar * 260),
        ("szTypeName", ctypes.c_wchar * 80),
    ]


class _GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", ctypes.c_ulong),
        ("Data2", ctypes.c_ushort),
        ("Data3", ctypes.c_ushort),
        ("Data4", ctypes.c_ubyte * 8),
    ]


class _BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD),
        ("biWidth", ctypes.c_long),
        ("biHeight", ctypes.c_long),
        ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD),
        ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD),
        ("biXPelsPerMeter", ctypes.c_long),
        ("biYPelsPerMeter", ctypes.c_long),
        ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
    ]


class _BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", _BITMAPINFOHEADER), ("bmiColors", wintypes.DWORD * 3)]


shell32.SHGetFileInfoW.restype = ctypes.c_void_p
shell32.SHGetFileInfoW.argtypes = [
    wintypes.LPCWSTR, wintypes.DWORD, ctypes.POINTER(_SHFILEINFO), wintypes.UINT, wintypes.UINT,
]

shell32.SHGetImageList.restype = ctypes.c_long
shell32.SHGetImageList.argtypes = [ctypes.c_int, ctypes.POINTER(_GUID), ctypes.POINTER(ctypes.c_void_p)]

SHGFI_ICON = 0x000000100
SHGFI_LARGEICON = 0x000000000
SHGFI_SYSICONINDEX = 0x000004000
SHGFI_USEFILEATTRIBUTES = 0x000000010
FILE_ATTRIBUTE_NORMAL = 0x80
FILE_ATTRIBUTE_DIRECTORY = 0x10

SHIL_EXTRALARGE = 0x2
SHIL_JUMBO = 0x4
IID_IIMAGELIST = _GUID(
    0x46EB5926, 0x582E, 0x4017, (ctypes.c_ubyte * 8)(0x9F, 0xDF, 0xE8, 0x99, 0x8D, 0xAA, 0x09, 0x50)
)

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".tif", ".tiff"}
PER_FILE_EXTS = {".exe", ".lnk", ".ico", ".msi", ".cur", ".scr", ".url"}
THUMB_MAX_BYTES = 24 * 1024 * 1024

_imagelists: dict[int, ctypes.c_void_p] = {}


def _image_list(shil: int):
    if shil not in _imagelists:
        ptr = ctypes.c_void_p()
        hr = shell32.SHGetImageList(shil, ctypes.byref(IID_IIMAGELIST), ctypes.byref(ptr))
        _imagelists[shil] = ptr if hr == 0 and ptr else None
    return _imagelists[shil]


def _imagelist_icon(shil: int, index: int):
    plist = _image_list(shil)
    if not plist:
        return None
    vtable = ctypes.cast(plist, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
    proto = ctypes.WINFUNCTYPE(
        ctypes.c_long, ctypes.c_void_p, ctypes.c_int, ctypes.c_uint, ctypes.POINTER(ctypes.c_void_p)
    )
    get_icon = proto(vtable[10])  # IImageList::GetIcon
    hicon = ctypes.c_void_p()
    if get_icon(plist, index, 1, ctypes.byref(hicon)) != 0:
        return None
    return hicon.value


def _hicon_to_image(hicon: int, size: int):
    screen = user32.GetDC(None)
    dc = gdi32.CreateCompatibleDC(screen)
    info = _BITMAPINFO()
    head = info.bmiHeader
    head.biSize = ctypes.sizeof(_BITMAPINFOHEADER)
    head.biWidth = size
    head.biHeight = -size  # top-down
    head.biPlanes = 1
    head.biBitCount = 32
    head.biCompression = 0
    bits = ctypes.c_void_p()
    bitmap = gdi32.CreateDIBSection(dc, ctypes.byref(info), 0, ctypes.byref(bits), None, 0)
    try:
        if not bitmap:
            return None
        previous = gdi32.SelectObject(dc, bitmap)
        user32.DrawIconEx(dc, 0, 0, hicon, size, size, 0, None, 0x0003)  # DI_NORMAL
        raw = ctypes.string_at(bits, size * size * 4)
        gdi32.SelectObject(dc, previous)
    finally:
        if bitmap:
            gdi32.DeleteObject(bitmap)
        gdi32.DeleteDC(dc)
        user32.ReleaseDC(None, screen)

    image = Image.frombuffer("RGBA", (size, size), raw, "raw", "BGRA", 0, 1).copy()
    if image.getchannel("A").getextrema()[1] == 0:  # legacy icon without an alpha channel
        image.putalpha(255)
    return image


def _shell_image(path: str, is_dir: bool, use_generic: bool):
    info = _SHFILEINFO()
    attrs = FILE_ATTRIBUTE_DIRECTORY if is_dir else FILE_ATTRIBUTE_NORMAL
    flags = SHGFI_SYSICONINDEX | (SHGFI_USEFILEATTRIBUTES if use_generic else 0)
    if not shell32.SHGetFileInfoW(path, attrs, ctypes.byref(info), ctypes.sizeof(info), flags):
        return None

    for shil, native in ((SHIL_JUMBO, 256), (SHIL_EXTRALARGE, 48)):
        hicon = _imagelist_icon(shil, info.iIcon)
        if not hicon:
            continue
        try:
            image = _hicon_to_image(hicon, native)
        finally:
            user32.DestroyIcon(ctypes.c_void_p(hicon))
        if image is None:
            continue
        box = image.getbbox()
        # Jumbo slots hold small legacy icons in the top-left corner; prefer the crisp 48px list.
        if shil == SHIL_JUMBO and box and (box[2] - box[0]) <= 64:
            continue
        return image.crop(box) if box else image

    # Last resort: the plain 32px icon handle.
    info = _SHFILEINFO()
    if shell32.SHGetFileInfoW(
        path, attrs, ctypes.byref(info), ctypes.sizeof(info),
        SHGFI_ICON | SHGFI_LARGEICON | (SHGFI_USEFILEATTRIBUTES if use_generic else 0),
    ) and info.hIcon:
        try:
            return _hicon_to_image(info.hIcon, 32)
        finally:
            user32.DestroyIcon(info.hIcon)
    return None


def _fit(image, size: int):
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    copy = image.copy()
    copy.thumbnail((size, size), Image.LANCZOS)
    canvas.paste(copy, ((size - copy.width) // 2, (size - copy.height) // 2))
    return canvas


class IconProvider:
    """Returns Tk images for files, caching by extension where icons are shared."""

    def __init__(self, master, size: int):
        self.master = master
        self.size = size
        self._cache: dict[tuple, object] = {}

    def get(self, path: str, is_dir: bool):
        if not HAVE_PIL:
            return None
        key = self._key(path, is_dir)
        if len(self._cache) > 800:
            self._cache.clear()
        if key not in self._cache:
            try:
                self._cache[key] = self._build(path, is_dir, key[0])
            except Exception:
                self._cache[key] = None
        return self._cache[key]

    def _key(self, path: str, is_dir: bool) -> tuple:
        if is_dir:
            return ("dir",)
        ext = os.path.splitext(path)[1].lower()
        if ext in IMAGE_EXTS or ext in PER_FILE_EXTS:
            try:
                stat = os.stat(path)
                return ("thumb" if ext in IMAGE_EXTS else "file", path.lower(), stat.st_mtime_ns, stat.st_size)
            except OSError:
                return ("ext", ext)
        return ("ext", ext)

    def _build(self, path: str, is_dir: bool, kind: str):
        image = None
        if kind == "thumb":
            image = self._thumbnail(path)
        if image is None:
            image = _shell_image(path, is_dir, use_generic=kind == "ext")
        if image is None:
            return None
        return ImageTk.PhotoImage(_fit(image, self.size), master=self.master)

    def _thumbnail(self, path: str):
        try:
            if os.path.getsize(path) > THUMB_MAX_BYTES:
                return None
            with Image.open(path) as src:
                src.draft("RGB", (self.size * 2, self.size * 2))
                return src.convert("RGBA")
        except Exception:
            return None
