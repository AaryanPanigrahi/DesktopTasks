"""
The three Windows shortcuts the settings page can tick: start with
Windows, Start menu, Desktop.

Ported from DesktopCards, where the same three live in its separate
setup app behind /api/install. This is only the .lnk half of that: what a
shortcut should point at, which ones exist, and writing or removing them.
Copying the binary into place and registering it with Add/Remove Programs
is setup_app's job, and it calls straight into here for the shortcuts
rather than keeping a second copy of this.

platform_win owns the actual .lnk writing (create_shortcut, driven by
PowerShell and WScript.Shell); this module only decides the target and
the three paths. It is the one place that knows a shortcut's target is
the exe when frozen and `pythonw.exe desktoptasks.py` from source, which
is the same split spawn_self makes in widget.py -- there is only ever one
entry point, so a shortcut needs no flags.

The Startup folder rather than the HKCU\\...\\Run registry key: see
platform_win.install_autostart for why. Deleting the shortcut is the
whole of turning it off, which is also why uninstall.py removes all three
by hand rather than coming through here.

Imported by serve.py, which is also run on its own for page work, so a
platform without these calls degrades to `available: False` and a page
that draws the card disabled rather than failing the whole state read.
"""

import os
import sys

from paths import ASSET_DIR, FROZEN, INSTALLED_EXE_PATH

APP_NAME = "DesktopTasks"
DESCRIPTION = "DesktopTasks widget"

try:
    import platform_win as native
except Exception as e:  # not Windows, or a stripped-down environment
    native = None
    print(f"[shortcuts] no platform support: {e}")


def available():
    return native is not None


def launch_target():
    """(target, arguments, icon, working_dir) for a shortcut.

    Frozen, that is the installed copy with no arguments -- the one
    binary takes no script argument, and the filename is what selects
    widget mode. The installed path rather than sys.executable, because
    setup is a copy of the same binary under another name: a shortcut
    written from it must point at the widget, not back at setup. Falls
    back to the running exe when nothing is installed, which is someone
    running the download without installing it.

    From source it is pythonw.exe (not python.exe, or the shortcut opens
    a console window) plus the entry script, whose folder has to be the
    working directory or the script argument resolves to nothing.

    The icon is the cached .ico built from the current logo.png, so
    replacing the logo reaches the shortcuts without a rebuild. None
    falls back to the target's own icon inside create_shortcut."""
    try:
        import logo_cache
        icon = logo_cache.icon_file()
    except Exception as e:
        # A shortcut with the wrong icon is worth having; one that was
        # never written because Pillow was unhappy is not.
        print(f"[shortcuts] no icon: {e}")
        icon = None

    if FROZEN:
        exe = (INSTALLED_EXE_PATH if os.path.exists(INSTALLED_EXE_PATH)
               else sys.executable)
        return exe, "", icon, os.path.dirname(exe)
    pythonw = sys.executable.replace("python.exe", "pythonw.exe")
    return pythonw, "desktoptasks.py", icon, ASSET_DIR


def paths():
    """The three .lnk paths, by the key the page uses for each."""
    return {
        "startup": native.autostart_path(APP_NAME),
        "start_menu": native.start_menu_path(APP_NAME),
        "desktop": native.desktop_path(APP_NAME),
    }


def state():
    """Which shortcuts exist, and the folder each one lives in.

    Judged by the file being there rather than by anything remembered in
    config.json: the shortcuts are files on disk, and someone who
    deletes one from the Startup folder has turned autostart off whether
    or not this app was running at the time. A remembered flag would
    then disagree with the only thing that actually matters."""
    if not available():
        return {"available": False, "startup": False, "start_menu": False,
                "desktop": False, "dirs": {}}

    try:
        where = paths()
        return {
            "available": True,
            "startup": os.path.exists(where["startup"]),
            "start_menu": os.path.exists(where["start_menu"]),
            "desktop": os.path.exists(where["desktop"]),
            "dirs": {key: os.path.dirname(path) for key, path in where.items()},
        }
    except Exception as e:
        print(f"[shortcuts] could not read the shortcut state: {e}")
        return {"available": False, "startup": False, "start_menu": False,
                "desktop": False, "dirs": {}}


def apply(wanted):
    """Writes, removes or leaves each of the three shortcuts.

    `wanted` maps "startup" / "start_menu" / "desktop" to a bool. A key
    that is absent or None leaves that shortcut exactly as it is --
    absent is not the same as false, and a caller that only has an
    opinion about autostart must not be able to delete the other two by
    saying nothing about them.

    Returns the same three keys, each the path written or None, so the
    caller can report what actually landed. A shortcut that would not
    write is reported as missing rather than raised: the other two still
    did their job, and the page re-reads the real state afterwards."""
    if not available():
        return {"ok": False, "error": "Shortcuts need Windows.",
                "startup": None, "start_menu": None, "desktop": None}

    target, args, icon, working_dir = launch_target()
    where = paths()
    result = {"ok": True}

    for key, path in where.items():
        choice = wanted.get(key)
        if choice is None:
            result[key] = path if os.path.exists(path) else None
            continue
        if not choice:
            native.remove_shortcut(path)
            result[key] = None
            continue
        result[key] = native.create_shortcut(
            path,
            target=target,
            arguments=args,
            icon=icon,
            working_dir=working_dir,
            description=DESCRIPTION,
        )
        if result[key] is None:
            result["ok"] = False
            result["error"] = f"Could not write {path}."

    print(f"[shortcuts] {result}")
    return result
