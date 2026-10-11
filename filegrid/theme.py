"""Colors, fonts and DPI-aware sizing shared by every view."""

from __future__ import annotations

import tkinter.font as tkfont

# Surfaces
BG = "#0f1217"
PANEL = "#151922"
CARD = "#1c2230"
CARD_HOVER = "#242c3d"
CARD_SELECTED = "#2b3a5c"
CELL_EMPTY = "#141821"
DROPZONE = "#243354"
BORDER = "#232b39"
BORDER_SOFT = "#1b212c"

# Ink
TEXT = "#e7ecf5"
TEXT_MUTED = "#8a93a6"
TEXT_DIM = "#5d6577"

# Accents
ACCENT = "#6c8cff"
ACCENT_SOFT = "#3a4a80"
FOLDER = "#f0b429"
DANGER = "#ff6b6b"

# Fallback tile colors by file family
FAMILY_COLORS = {
    "image": "#c084fc",
    "video": "#f472b6",
    "audio": "#2dd4bf",
    "doc": "#60a5fa",
    "sheet": "#4ade80",
    "slide": "#fb923c",
    "pdf": "#f87171",
    "archive": "#fbbf24",
    "code": "#38bdf8",
    "exe": "#a3e635",
    "text": "#94a3b8",
    "other": "#7d8798",
}

FAMILY_BY_EXT = {
    "image": (".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".ico", ".tif", ".tiff", ".svg"),
    "video": (".mp4", ".mkv", ".mov", ".avi", ".webm", ".wmv", ".m4v"),
    "audio": (".mp3", ".wav", ".flac", ".m4a", ".ogg", ".aac", ".wma"),
    "doc": (".doc", ".docx", ".odt", ".rtf"),
    "sheet": (".xls", ".xlsx", ".csv", ".ods"),
    "slide": (".ppt", ".pptx", ".odp"),
    "pdf": (".pdf",),
    "archive": (".zip", ".rar", ".7z", ".tar", ".gz", ".iso", ".cab"),
    "code": (".py", ".js", ".ts", ".tsx", ".jsx", ".c", ".h", ".cpp", ".cs", ".java", ".go",
             ".rs", ".rb", ".php", ".html", ".css", ".json", ".xml", ".yml", ".yaml", ".sh", ".ps1"),
    "exe": (".exe", ".msi", ".bat", ".cmd", ".lnk", ".dll"),
    "text": (".txt", ".md", ".log", ".ini", ".cfg"),
}

_EXT_TO_FAMILY = {ext: fam for fam, exts in FAMILY_BY_EXT.items() for ext in exts}

# Segoe MDL2 Assets glyphs
GLYPH = {
    "folder": "\ue8b7",
    "folder_open": "\ue838",
    "refresh": "\ue72c",
    "close": "\ue8bb",
    "collapse": "\ue921",
    "up": "\ue70e",
    "search": "\ue721",
    "sort": "\ue8cb",
    "pin": "\ue718",
    "expand": "\ue70d",
}

SCALE = 1.0
FONTS: dict[str, tkfont.Font] = {}


def px(value: float) -> int:
    """Scale a design pixel value to the current display DPI."""
    return max(1, int(round(value * SCALE)))


def init(root, scale: float) -> None:
    global SCALE
    SCALE = scale
    root.tk.call("tk", "scaling", scale * 96.0 / 72.0)

    def font(**kw) -> tkfont.Font:
        return tkfont.Font(root=root, **kw)

    FONTS.update(
        title=font(family="Segoe UI Semibold", size=11),
        body=font(family="Segoe UI", size=9),
        small=font(family="Segoe UI", size=8),
        tiny=font(family="Segoe UI", size=7),
        tile=font(family="Segoe UI", size=8),
        badge=font(family="Segoe UI Semibold", size=9),
        big=font(family="Segoe UI Semibold", size=14),
        glyph=font(family="Segoe MDL2 Assets", size=10),
        glyph_big=font(family="Segoe MDL2 Assets", size=16),
    )


def family_for(ext: str) -> str:
    return _EXT_TO_FAMILY.get(ext.lower(), "other")


def color_for(ext: str) -> str:
    return FAMILY_COLORS[family_for(ext)]
