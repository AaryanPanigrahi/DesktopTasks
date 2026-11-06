"""
Setup: installs DesktopTasks, writes its shortcuts, and starts it.

    DesktopTasks-Setup.exe        the download, by name
    DesktopTasks.exe --setup      the same thing from an installed copy

Reached by filename or by the flag, both the same code. See
desktoptasks.looks_like_setup_build: the one binary is copied under a
second name, and the name is what selects this mode, so there is nothing
extra to build and nothing that can fall out of step with the app it
installs.

What it does, in order: copy the binary into place, seed the config files
from the bundled examples, write the shortcuts, install the uninstaller
and list it in Settings > Apps, then launch the widget.

Deliberately not a wizard. DesktopCards asks for Plaid credentials and
links banks before its widget can show anything, so setup there is a
five-step page with a server behind it. Here the only thing to set up is
a Google sign-in, and the tray and the settings page already own that --
so this is one native dialog with one tick box, and the widget takes it
from there. Nothing here imports pywebview, Flask or PIL.

Nothing needs administrator. The app and its data go under
%LOCALAPPDATA%, the shortcuts under %APPDATA%, and the Add/Remove entry
in HKCU.
"""

import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request

import shortcuts

from paths import (
    APPEARANCE_EXAMPLE_PATH,
    APPEARANCE_PATH,
    ASSET_DIR,
    CONFIG_EXAMPLE_PATH,
    CONFIG_PATH,
    DATA_DIR,
    DETACHED,
    FROZEN,
    INSTALLED_EXE_PATH,
    LOOPBACK,
    UNINSTALL_EXE_PATH,
    clean_child_env,
    ensure_data_dir,
)

APP_NAME = "DesktopTasks"


def native():
    """platform_win, imported late and only when it is needed.

    Setup is the one mode that can usefully say "this is Windows only"
    out loud, so the import failing has to be reachable rather than fatal
    at module level."""
    import platform_win

    return platform_win


def read_port():
    """The widget's port, read the way serve.py reads it.

    serve.py is not imported for this: it pulls in google_tasks and the
    whole fetch path, which setup has no use for."""
    import json

    try:
        with open(CONFIG_PATH, "r") as f:
            return json.load(f).get("port", 5100)
    except (OSError, ValueError):
        return 5100


def widget_is_running(port):
    """Whether a widget is up, judged by its server answering.

    The server is a thread inside the widget process, so an answer on
    that port means a live widget. Cheap, and needs no handle to
    anything."""
    try:
        urllib.request.urlopen(f"http://{LOOPBACK}:{port}/settings.json", timeout=1)
        return True
    except urllib.error.HTTPError:
        return True  # something replied, which is the question
    except Exception:
        return False


def stop_running_widget(port):
    """Asks a running widget to quit, and waits for it to actually go.

    Windows holds a running exe open, so a reinstall over a live widget
    cannot replace the binary. Asked rather than killed: the widget's own
    quit path stops the tray icon and releases the single-instance lock,
    where a kill leaves that lock held until the handle is reaped and the
    next launch can exit silently."""
    if not widget_is_running(port):
        return False
    req = urllib.request.Request(f"http://{LOOPBACK}:{port}/quit", method="POST")
    try:
        urllib.request.urlopen(req, timeout=5)
    except Exception as e:
        print(f"[setup] the running widget would not take a quit: {e}")
    # Long enough for the widget's own force_exit_soon backstop to fire,
    # which is the slower of its two exit paths.
    for _ in range(12):
        time.sleep(0.5)
        if not widget_is_running(port):
            break
    print("[setup] asked the running widget to quit")
    return True


def install_binary():
    """Puts the widget-named copy of this exe in DATA_DIR.

    A copy, not a generated file: a program that writes a new .exe is
    doing what droppers do, and antivirus treats it accordingly. It is
    the same binary, only the filename differs, and the filename is what
    selects widget mode over setup mode.

    Returns (path, copied). A no-op when not frozen, where there is no
    single file to install."""
    if not FROZEN:
        return None, False
    if os.path.abspath(sys.executable) == os.path.abspath(INSTALLED_EXE_PATH):
        return INSTALLED_EXE_PATH, False
    try:
        shutil.copy2(sys.executable, INSTALLED_EXE_PATH)
        return INSTALLED_EXE_PATH, True
    except OSError:
        # In use means a widget is still holding it. The binary is
        # demonstrably already installed, so keep it and carry on to the
        # shortcuts, which is what the caller actually came for. Only a
        # missing target makes this fatal.
        if os.path.exists(INSTALLED_EXE_PATH):
            print(f"[setup] {INSTALLED_EXE_PATH} is in use; keeping it")
            return INSTALLED_EXE_PATH, False
        raise


def seed_data_dir():
    """Writes config.json and appearance.json from the bundled examples.

    Only the ones that are missing. An install over an existing one must
    not reset the look or, worse, overwrite the file holding the Google
    refresh token.

    The examples are what the README tells a source user to copy by hand,
    so this is the same first run either way. Both files are optional at
    runtime -- the app defaults every key it reads -- but seeding them
    means there is something to open and edit, and that config.json
    carries the port the settings page is served on."""
    ensure_data_dir()
    seeded = []
    for example, real in ((CONFIG_EXAMPLE_PATH, CONFIG_PATH),
                          (APPEARANCE_EXAMPLE_PATH, APPEARANCE_PATH)):
        if os.path.exists(real) or not os.path.exists(example):
            continue
        try:
            shutil.copy2(example, real)
            seeded.append(os.path.basename(real))
        except OSError as e:
            print(f"[setup] could not seed {real}: {e}")
    if seeded:
        print(f"[setup] seeded {', '.join(seeded)}")
    return seeded


def install_uninstaller():
    """Puts Uninstall.exe beside the app and lists it in Settings > Apps.

    A third copy of the same binary, like the setup one. Returns the
    path, or None when there is nothing to install: from source there is
    no single file to copy, and the uninstaller is reached with
    --uninstall instead.

    Failures here are reported, never fatal. An app that refused to
    finish installing because its uninstaller could not be written would
    be worse than one you remove by hand."""
    if not FROZEN:
        return None
    try:
        if os.path.abspath(sys.executable) != os.path.abspath(UNINSTALL_EXE_PATH):
            shutil.copy2(sys.executable, UNINSTALL_EXE_PATH)
    except OSError as e:
        # In use means an uninstall is mid-flight, in which case the copy
        # already there is the one we would have written.
        if not os.path.exists(UNINSTALL_EXE_PATH):
            print(f"[setup] could not write {UNINSTALL_EXE_PATH}: {e}")
            return None
        print(f"[setup] {UNINSTALL_EXE_PATH} is in use; keeping it")

    size_kb = None
    try:
        # The app and the uninstaller, which are the same size.
        size_kb = int(os.path.getsize(UNINSTALL_EXE_PATH) / 1024) * 2
    except OSError:
        pass

    icon = None
    try:
        import logo_cache

        icon = logo_cache.icon_file()
    except Exception as e:
        print(f"[setup] no icon for the Add/Remove entry: {e}")

    native().register_uninstaller(
        UNINSTALL_EXE_PATH,
        name=APP_NAME,
        display_name=APP_NAME,
        icon=icon or INSTALLED_EXE_PATH,
        install_location=DATA_DIR,
        size_kb=size_kb,
    )
    return UNINSTALL_EXE_PATH


def launch_widget():
    """Starts the widget and leaves it running after setup exits.

    clean_child_env matters for the same reason it does in
    widget.spawn_self: setup exits moments later, and a widget that
    inherited setup's onefile unpack directory would have it deleted from
    under it."""
    if FROZEN:
        cmd = [INSTALLED_EXE_PATH]
        cwd = os.path.dirname(INSTALLED_EXE_PATH)
    else:
        pythonw = sys.executable.replace("python.exe", "pythonw.exe")
        cmd = [pythonw, "desktoptasks.py"]
        cwd = ASSET_DIR
    if not os.path.exists(cmd[0]):
        print(f"[setup] nothing to launch at {cmd[0]}")
        return False
    subprocess.Popen(cmd, cwd=cwd, env=clean_child_env(), **DETACHED)
    print(f"[setup] launched {cmd[0]}")
    return True


def install(autostart, desktop=False):
    """The whole install, in the order the pieces depend on each other.

    Returns a dict describing what happened, which is what the closing
    dialog reads. Nothing in here raises except a binary that cannot be
    written at all, which is the one failure that leaves nothing to
    install."""
    port = read_port()
    stopped = stop_running_widget(port)

    result = {"stopped": stopped}
    result["app"], result["copied"] = install_binary()
    result["seeded"] = seed_data_dir()

    # After the binary: launch_target points shortcuts at the installed
    # copy, so writing them first would point every one of them back at
    # whatever is running now, which during setup is the setup exe.
    #
    # The Start-menu entry is not a choice. It is how an installed app is
    # found again, and an install that left none would be an app with no
    # way back to it once the window is closed.
    result["shortcuts"] = shortcuts.apply({
        "start_menu": True,
        "startup": bool(autostart),
        "desktop": bool(desktop),
    })

    # Last, and after the shortcuts: what the app is registered to remove
    # has to exist before it is advertised as the way to remove it.
    result["uninstaller"] = install_uninstaller()
    result["launched"] = launch_widget()
    print(f"[setup] done: {result}")
    return result


def describe(result):
    """The closing dialog's text, saying only what actually happened."""
    lines = []
    if result.get("app"):
        lines.append(f"Installed to {result['app']}.")
    else:
        lines.append("Running from source, so nothing was copied.")
    where = result.get("shortcuts") or {}
    if where.get("start_menu"):
        lines.append("It is in your Start menu.")
    if where.get("startup"):
        lines.append("It will start with Windows.")
    if where.get("desktop"):
        lines.append("There is a shortcut on your desktop.")
    if result.get("uninstaller"):
        lines.append("Remove it from Settings > Apps whenever you like.")
    if result.get("launched"):
        lines.append("")
        lines.append("The widget is starting now. Right-click its tray icon "
                     "and choose Modify to connect your Google account.")
    return "\n".join(lines)


def main(argv=None):
    if os.name != "nt":
        sys.exit("Installing is Windows-only.")

    n = native()
    again = FROZEN and os.path.exists(INSTALLED_EXE_PATH)

    # One dialog, before anything happens, saying where it goes and what
    # the tick box does. The tick is the only thing setup asks: the other
    # two shortcuts are on the settings page, which is a better place for
    # a choice someone may want to change later.
    yes, autostart = n.confirm_with_checkbox(
        "Reinstall DesktopTasks?" if again else "Install DesktopTasks?",
        f"It goes in {DATA_DIR}, with a Start-menu entry.\n\n"
        "Nothing needs administrator, and nothing is sent anywhere. Your "
        "tasks and your Google sign-in stay in files on this computer.\n\n"
        "A running widget is closed and started again.",
        "Start DesktopTasks when I sign in to Windows",
        title=APP_NAME,
        checked=True,
    )
    if not yes:
        print("[setup] cancelled")
        return 0

    try:
        result = install(autostart)
    except OSError as e:
        n.message_box(
            f"Could not install to {INSTALLED_EXE_PATH}.\n\n{e}",
            APP_NAME, kind="error",
        )
        return 1

    n.message_box(describe(result), APP_NAME)
    return 0


if __name__ == "__main__":
    sys.exit(main())
