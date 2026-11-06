"""
The one entry point. Everything the app can do is a flag on this file.

Frozen, there is only ever one executable: sys.executable *is* the app, it
takes no script argument, and there are no .py files on disk to point at.
Spawning Python by name instead -- `pythonw.exe widget.py`, a Task
Scheduler command line -- breaks under a build. A single entry point with
subcommands means `sys.executable` plus a flag covers every case, from
source and frozen alike.

    DesktopTasks.exe              the widget (default)
    DesktopTasks.exe --serve      just the HTTP server, for debugging
    DesktopTasks.exe --fetch      one Google Tasks pull, then exit
    DesktopTasks.exe --connect    sign in to Google (first run, reconnect)
    DesktopTasks.exe --setup      install it, with shortcuts
    DesktopTasks.exe --uninstall  remove it, its shortcuts and its data

The last two are also selected by the exe's own filename, which is what
makes a single downloaded file land in setup rather than in a widget
nobody installed. DesktopTasks-Setup.exe runs setup, Uninstall.exe runs
the uninstaller, and both are copies of this same binary under another
name. See looks_like_setup_build.

Imports are deliberately inside each branch. The widget pulls in pywebview,
pythonnet and the whole .NET interop layer; nothing else here needs any of
it. From source that's a slower start, and frozen it's wasted unpacking.

--connect is the one every user meets. While the Cloud project's publishing
status is Testing, Google expires the refresh token every 7 days, so this
is a weekly errand rather than a one-off. The tray has a menu item for it
(widget.connect_google), because the widget is pinned to the desktop layer
and cannot offer a button of its own.
"""

import os
import sys

LOG_NAME = "desktoptasks.log"
MAX_LOG_BYTES = 512 * 1024

# A name containing either of these means the setup build, so a
# first-time user who downloads one file and double-clicks it lands in
# setup rather than in a widget that was never installed.
SETUP_NAMES = ("setup", "install")

# Checked before SETUP_NAMES, and the reason that check is a function
# rather than one `in` test: "uninstall" contains "install", so a plain
# membership test would send the uninstaller into setup.
UNINSTALL_NAMES = ("uninstall",)


def _exe_name():
    """This program's filename, lowercased. Frozen that is the exe; from
    source it is this script, which never matches either list, so a
    checkout only ever reaches these modes through the flags."""
    return os.path.basename(sys.executable if getattr(sys, "frozen", False)
                            else __file__).lower()


def looks_like_uninstall_build():
    return any(token in _exe_name() for token in UNINSTALL_NAMES)


def looks_like_setup_build():
    if looks_like_uninstall_build():
        return False
    return any(token in _exe_name() for token in SETUP_NAMES)


def redirect_output_to_log():
    """Points stdout/stderr at a file when there's no console to print to.

    A windowed build has no console, and PyInstaller sets sys.stdout and
    sys.stderr to None rather than to something inert -- so every print()
    in the codebase would raise AttributeError on None.write. That turns
    harmless progress messages into crashes, in the build where they're
    hardest to see. It applies to a source run under pythonw too, which is
    how the tray's Restart relaunches this.

    Pointing them at a file fixes that and buys the thing this app
    otherwise has no way to produce: a record of what went wrong. The
    known-worst failure mode is pywebview coming up as a blank window with
    no traceback anywhere, and the tray -- the only control surface, since
    the window itself takes no mouse input -- not appearing either. A log
    is the difference between diagnosing that and guessing.

    Truncated rather than rotated: this is a debug aid, and the last run is
    the one anyone ever wants."""
    if sys.stdout is not None and sys.stderr is not None:
        return None

    from paths import DATA_DIR, ensure_data_dir

    try:
        ensure_data_dir()
        path = os.path.join(DATA_DIR, LOG_NAME)
        if os.path.exists(path) and os.path.getsize(path) > MAX_LOG_BYTES:
            os.remove(path)
        stream = open(path, "a", buffering=1, encoding="utf-8", errors="replace")
    except OSError:
        # Nowhere writable. Swallow output rather than die for the sake of
        # logging -- os.devnull always opens, and the app still runs.
        stream = open(os.devnull, "w")
        path = os.devnull

    sys.stdout = stream
    sys.stderr = stream
    return path


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    mode = argv[0] if argv else None

    log_path = redirect_output_to_log()
    if log_path:
        import datetime

        if mode:
            label = mode
        elif looks_like_uninstall_build():
            label = "uninstall"
        else:
            label = "setup" if looks_like_setup_build() else "widget"
        print(f"\n=== DesktopTasks {label} "
              f"{datetime.datetime.now().isoformat(timespec='seconds')} ===")

    if mode in ("-h", "--help"):
        print(__doc__.strip())
        return 0

    if mode == "--serve":
        import serve

        serve.main()
    elif mode == "--fetch":
        import google_tasks

        google_tasks.main()
    elif mode == "--connect":
        import google_tasks_setup

        # Takes the optional client_secret.json a clone needs, so
        # `DesktopTasks.exe --connect client_secret.json` works the same
        # way the script does. A release build bundles its own client and
        # needs no argument.
        google_tasks_setup.main(argv[1:])
    elif mode == "--setup":
        import setup_app

        return setup_app.main(argv[1:])
    elif mode == "--uninstall":
        import uninstall

        return uninstall.main(argv[1:])
    elif mode is None:
        # No flag, so the filename decides. Uninstall is tested first for
        # the same reason looks_like_setup_build tests it: one name
        # contains the other.
        if looks_like_uninstall_build():
            import uninstall

            return uninstall.main()
        if looks_like_setup_build():
            import setup_app

            return setup_app.main()

        import widget

        widget.main()
    else:
        print(f"Unknown option {mode!r}. Try --help.", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
