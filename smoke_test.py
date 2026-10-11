"""Headless-ish smoke test: builds the real window, exercises the main paths, exits."""

import faulthandler
import json
import os
import tempfile
import time
import traceback

from filegrid import theme
from filegrid.app import PUCK_SIZE, FileGridApp
from filegrid.theme import px


def main() -> int:
    faulthandler.dump_traceback_later(45, exit=True)
    os.environ["FILEGRID_STATE_DIR"] = tempfile.mkdtemp(prefix="filegrid_state_")
    workdir = tempfile.mkdtemp(prefix="filegrid_test_")
    for name in ("notes.txt", "report.pdf", "photo.png", "script.py", "archive.zip"):
        open(os.path.join(workdir, name), "wb").write(b"x" * 64)
    os.mkdir(os.path.join(workdir, "subfolder"))

    app = FileGridApp()
    root = app.root
    print("scale:", theme.SCALE, "px(65):", px(65), "slot:", app.store.slot)
    root.geometry("940x640+80+60")
    root.update()
    app.open_directory(workdir)
    root.update()

    grid = app.grid
    assert len(grid.entries) == 6, grid.entries
    assert len(grid.pos) == 6, grid.pos
    print("tiles:", {n: grid.pos[n] for n in sorted(grid.pos)})
    print("icons resolved:", sum(1 for n in grid.entries if grid.icons.get(grid.entries[n].path,
                                                                           grid.entries[n].is_dir)))

    grid._move_tile("notes.txt", (3, 2))
    grid._redraw()
    root.update()
    assert grid.pos["notes.txt"] == (3, 2)

    occupant = next(n for n, p in grid.pos.items() if p == (0, 0))
    grid._move_tile("notes.txt", (0, 0))
    assert grid.pos[occupant] == (3, 2), "swap failed"

    grid.set_filter("pdf")
    root.update()
    assert set(grid._visible()) == {"report.pdf"}, grid._visible()
    grid.set_filter("")

    grid.arrange()
    root.update()
    assert grid.pos["subfolder"] == (0, 0), grid.pos

    def pump(seconds: float) -> None:
        deadline = time.time() + seconds
        while time.time() < deadline:
            root.update()
            time.sleep(0.005)

    app.collapse()
    pump(1.0)
    assert app.collapsed and app.puck.winfo_ismapped()
    assert not app.animating, "collapse animation never finished"
    print("puck size:", root.winfo_width(), "x", root.winfo_height())
    wanted = px(PUCK_SIZE)
    assert abs(root.winfo_width() - wanted) <= 2, f"puck is {root.winfo_width()}, wanted {wanted}"

    app.settings["label"] = "Inbox"
    app._draw_puck()
    root.update()
    canvas, side = app.puck, app.puck.winfo_width()
    boxes = {canvas.type(i): canvas.bbox(i) for i in canvas.find_all()}
    print("puck items:", {k: v for k, v in boxes.items()})
    for kind, box in boxes.items():
        assert box[0] >= -2 and box[1] >= -2, f"{kind} spills off the puck: {box}"
        assert box[2] <= side + 2 and box[3] <= side + 2, f"{kind} spills off the puck: {box}"
    assert boxes["text"][1] > boxes["polygon"][3], "caption overlaps the folder graphic"
    assert app.puck_label() == "Inbox"

    app.expand()
    pump(1.0)
    assert not app.collapsed and app.expanded.winfo_ismapped()
    first = (root.winfo_width(), root.winfo_height())
    print("expanded size:", first)

    app.collapse()
    pump(1.0)
    app.expand()
    pump(1.0)
    assert (root.winfo_width(), root.winfo_height()) == first, "window size drifts across cycles"

    app.go_up()
    root.update()
    assert grid.directory == os.path.dirname(workdir)

    app.open_directory(workdir)
    root.update()
    grid._move_tile("notes.txt", (2, 3))
    expected = dict(grid.pos)
    app.toggle_topmost()
    root.update()
    print("state file:", app.store.path)
    slot = app.store.slot
    app.quit_app()

    restarted = FileGridApp()
    restarted.root.update()
    restarted.open_directory(workdir)
    restarted.root.update()
    assert restarted.grid.pos == expected, f"layout not restored\n{restarted.grid.pos}\n{expected}"
    assert restarted.store.slot == slot, "a quit panel should free its slot for the next one"

    # A second panel must claim its own slot and keep its own window state.
    second = FileGridApp()
    second.root.update()
    assert second.store.slot != restarted.store.slot, "both panels claimed the same slot"
    second.open_directory(os.path.dirname(workdir))
    second.settings["label"] = "Scratch"
    second.root.geometry("1000x600+400+300")
    second.root.update()
    second._remember_window()
    second.store.save()
    restarted.store.save()
    second.root.update()

    on_disk = json.loads(restarted.store.path.read_text(encoding="utf-8"))
    instances = on_disk["instances"]
    assert restarted.store.slot in instances and second.store.slot in instances, instances
    assert instances[second.store.slot]["label"] == "Scratch"
    assert instances[restarted.store.slot]["directory"] == workdir, "panel 1 state was clobbered"
    assert instances[second.store.slot]["window"]["w"] == round(1000 / theme.SCALE)
    assert on_disk["layouts"], "shared layouts survived the merge"
    print("slots on disk:", sorted(instances))

    assert second.puck_label() == "Scratch"
    second.clear_label()
    assert second.puck_label() == os.path.basename(os.path.dirname(workdir))

    second.quit_app()
    restarted.root.destroy()

    print("OK")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:
        traceback.print_exc()
        raise SystemExit(1)
