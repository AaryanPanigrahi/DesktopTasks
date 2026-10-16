"""
Generates DesktopTasks.ico from logo.png, for the exe's embedded icon.

A build step rather than a committed .ico, so logo.png stays the single
source of truth for the mark -- replace the PNG, rebuild, and the exe icon
follows. That is also why DesktopTasks.ico is gitignored: it is output.

PyInstaller's --icon needs a real multi-size .ico and will not take a PNG,
so something has to do the conversion. The conversion itself lives in
logo_cache.write_ico, which the running app also uses for the shortcut
icon, so there is one definition of what a DesktopTasks icon looks like
rather than two that can drift.

An earlier version of this file drew the icon with Pillow, because the
project had no mark of its own. It has one now, so the drawing is gone.
The tray still has a drawn fallback in widget.build_tray_image, for the
different case of a logo that cannot be read at runtime.
"""

import os
import sys

from logo_cache import write_ico
from paths import ICON_PATH, logo_path


def main():
    source = logo_path()
    if not os.path.exists(source):
        sys.exit(f"{source} not found -- nothing to build an icon from.")

    write_ico(source, ICON_PATH)
    print(f"Wrote {ICON_PATH} from {source}")
    return ICON_PATH


if __name__ == "__main__":
    main()
