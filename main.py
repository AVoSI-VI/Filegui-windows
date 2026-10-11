"""Entry point: python main.py [folder]"""

import os
import sys

from filegrid.app import FileGridApp


def run() -> None:
    app = FileGridApp()
    if len(sys.argv) > 1 and os.path.isdir(sys.argv[1]):
        app.open_directory(os.path.abspath(sys.argv[1]))
    app.run()


if __name__ == "__main__":
    run()
