# FileGrid

A borderless Windows desktop panel for one folder at a time. Files sit on a
visual grid where you can drag them into whatever arrangement you like, the
panel collapses into a single folder puck when you want your desktop back, and
expands again to show everything in the folder.

## What it does

- **Place files on a grid.** Every file and subfolder gets a tile. Drag a tile
  to any cell; dropping it on an occupied cell swaps the two. Positions are
  remembered per folder, so a file returns to its spot the next time you open it.
- **Minimize to a single folder.** The collapse button (or `Esc`, or a
  double-click on the title bar) shrinks the whole window into a small folder
  puck with a live file count badge and a caption you can rename. Drag the puck
  anywhere on screen; it stays on top.
- **Run as many panels as you like.** Each panel claims its own slot and
  remembers its own folder, label, window size, puck position and pin state.
  Saves merge under a lock, so panels never overwrite each other. Grid layouts
  are shared per folder, so a folder looks the same in whichever panel opens it.
- **Expand to the whole directory.** Double-click the puck and the panel grows
  back, rescans the folder, and lays out every item — including files added
  while it was collapsed.

Tiles use real Windows shell icons, and images get actual thumbnails.

## Install and run

Requires Windows and Python 3.10+ with tkinter (included in the python.org
installer).

```bash
pip install -r requirements.txt
python main.py
```

Both dependencies are optional: without Pillow, tiles fall back to colored
vector icons; without tkinterdnd2, you simply can't drag files in from Explorer.

Open a specific folder on launch:

```bash
python main.py "C:\Users\you\Downloads"
```

Double-click `FileGrid.bat` to start it without a console window.

## Controls

| Action | How |
| --- | --- |
| Move a tile | Drag it to another cell (swaps if occupied) |
| Open a file | Double-click, or `Enter` |
| Enter a subfolder | Double-click its tile |
| Collapse to folder puck | Collapse button, `Esc`, or double-click the title bar |
| Expand | Double-click the puck |
| Move the window/puck | Drag the title bar or the puck |
| Resize | Drag the grip in the bottom-right corner |
| Search | `Ctrl+F`, `Esc` clears |
| Rescan folder | `F5` |
| Open another folder | `Ctrl+O` |
| Show hidden files | `Ctrl+H` |
| Auto-arrange tiles | Sort button, or right-click empty space |
| Delete to Recycle Bin | `Delete`, or right-click a tile |
| Rename the puck label | Right-click the puck, or right-click empty grid space |
| Pin above other windows | Pin button |
| Open another panel | Launch `main.py` again |
| Add files from Explorer | Drag them onto the grid or the puck (moves them into the folder) |

The folder is polled every two seconds, so tiles appear and disappear as the
directory changes.

## Layout

```
main.py              entry point
filegrid/app.py      window chrome, collapse/expand animation, puck
filegrid/gridview.py the tile grid: placement, dragging, context menu
filegrid/icons.py    Windows shell icon extraction and thumbnails
filegrid/store.py    per-panel state in %APPDATA%\FileGrid\state.json, slot locking
filegrid/winutil.py  DPI, rounded window corners, Recycle Bin, Explorer
filegrid/theme.py    colors, fonts, DPI scaling
smoke_test.py        builds the real window and exercises the main paths
```

Delete `%APPDATA%\FileGrid\state.json` to reset every saved layout. Set
`FILEGRID_STATE_DIR` to keep state somewhere else — `smoke_test.py` uses it so
tests never touch your real panels.
