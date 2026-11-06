"""
Removes DesktopTasks: its shortcuts, the installed copy, and itself.

    Uninstall.exe                 the copy setup leaves beside the app
    DesktopTasks.exe --uninstall  from anywhere

Reached three ways, all the same code: that file, the Uninstall button in
Settings > Apps, and the flag.

The order matters more than it looks. The widget is asked to quit before
anything is deleted, because it holds DesktopTasks.exe open as a running
image and can still write config.json on its way out. Removing files
under a live widget would leave the exe undeletable and let it rewrite a
file that was just removed. The exes go last and from outside the
process, since Windows will not delete a running one.

Nothing here needs administrator. Everything the app installs is
per-user: shortcuts in %APPDATA%, the app and its data under
%LOCALAPPDATA%, the Add/Remove entry in HKCU.

What it never touches: your Google account. The refresh token is only a
local file, so removing it signs this computer out and nothing else. The
tasks themselves live in your Google account and are never written by
this app at all.
"""

import glob
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

from paths import (
    APPEARANCE_PATH,
    CACHE_DIR,
    CONFIG_PATH,
    DATA_DIR,
    FROZEN,
    INSTALLED_EXE_PATH,
    LOG_PATH,
    LOOPBACK,
    TASKS_PATH,
    UNINSTALL_EXE_PATH,
    USER_LOGO_PATH,
)

APP_NAME = "DesktopTasks"


def native():
    import platform_win

    return platform_win


def keepable_paths():
    """What the tick box protects: everything a reinstall would
    otherwise make someone set up again.

    config.json carries the Google account and the refresh token,
    appearance.json the look, and logo.png a replaced mark.

    Deliberately not tasks.json or the per-account task files: those are
    the last fetch, rebuilt within a minute of the next launch, and a
    stale task list is the one thing nobody wants kept.

    USER_LOGO_PATH is always the copy in DATA_DIR, never the bundled
    mark, so it is safe to list: a user who dropped their own logo.png in
    the data folder put it there, and a reinstall should find it again."""
    found = [CONFIG_PATH, APPEARANCE_PATH, USER_LOGO_PATH]
    return [p for p in found if os.path.exists(p)]


def read_port():
    """The widget's port, read before anything is deleted."""
    try:
        with open(CONFIG_PATH, "r") as f:
            return json.load(f).get("port", 5100)
    except (OSError, ValueError):
        return 5100


def widget_answers(port):
    """Whether something is still serving the page. The same test
    setup_app.widget_is_running uses, for the same reason: the server is
    a thread inside the widget, so an answer means a live process."""
    try:
        urllib.request.urlopen(f"http://{LOOPBACK}:{port}/settings.json", timeout=1)
        return True
    except urllib.error.HTTPError:
        return True
    except Exception:
        return False


def stop_running_app(port):
    """Asks the widget to quit, then makes sure.

    Asked first, not killed first: the widget's own quit path stops the
    tray icon, releases the single-instance lock and lets its pending
    writes finish, where a kill leaves a stale lock behind that would
    block the next install.

    taskkill is the backstop, and only for a widget still answering
    after being asked. All three names are covered because the installed
    copy, the setup copy and the uninstaller are the same binary under
    different names, and any of them can be the one holding the folder."""
    if not widget_answers(port):
        return False

    req = urllib.request.Request(f"http://{LOOPBACK}:{port}/quit", method="POST")
    try:
        urllib.request.urlopen(req, timeout=5)
        print("[uninstall] asked the widget to quit")
    except Exception as e:
        print(f"[uninstall] the widget would not take a quit: {e}")
    # Long enough for force_exit_soon's backstop to fire, which is the
    # slower of the widget's two exit paths.
    for _ in range(8):
        time.sleep(0.5)
        if not widget_answers(port):
            return True

    print("[uninstall] still running; killing it")
    me = os.path.basename(sys.executable) if FROZEN else ""
    for name in (f"{APP_NAME}.exe", f"{APP_NAME}-Setup.exe", "Uninstall.exe"):
        if name.lower() == me.lower():
            continue  # that is this process
        subprocess.run(
            ["taskkill", "/f", "/im", name],
            capture_output=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    time.sleep(1)
    return True


def remove_shortcuts():
    """The Start-menu entry, the Startup one and the desktop one. All
    three are files, and all three are optional: only the ones actually
    there get removed.

    Reported by which one it was rather than by filename. All three are
    called DesktopTasks.lnk, so a list of basenames reads as the same
    name twice and says nothing about what was removed."""
    n = native()
    gone = []
    for label, path in (("Start menu", n.start_menu_path(APP_NAME)),
                        ("Startup", n.autostart_path(APP_NAME)),
                        ("Desktop", n.desktop_path(APP_NAME))):
        if os.path.exists(path) and n.remove_shortcut(path):
            gone.append(label)
    print(f"[uninstall] shortcuts removed: {gone or 'none found'}")
    return gone


def remove_data(keep_settings):
    """Everything under DATA_DIR except the exes, which have to outlive
    this process by a few seconds.

    Returns (kept, deferred): the files kept on purpose, and the ones
    Windows would not let go of, which the caller hands to
    delete_after_exit along with the exes. Nothing is simply abandoned,
    because a file left behind here is the difference between an
    uninstall that removed the folder and one that left an account
    sitting in it."""
    deferred = []

    def drop(path):
        if not _unlink(path) and os.path.exists(path):
            deferred.append(path)

    # The last fetch and the log go either way. Both are rebuilt, and
    # neither is anything anyone would want back.
    #
    # The log is always deferred, never retried: this process writes its
    # own progress into it (see desktoptasks.redirect_output_to_log), so
    # the handle holding it open is ours and cannot be waited out.
    drop(TASKS_PATH)
    for path in sorted(glob.glob(os.path.join(DATA_DIR, "tasks.*.json"))):
        drop(path)
    # The cached .ico and tray png, which are derived from logo.png.
    for path in sorted(glob.glob(os.path.join(CACHE_DIR, "*"))):
        drop(path)

    kept = [os.path.basename(p) for p in keepable_paths()]
    if keep_settings:
        print(f"[uninstall] keeping {kept}")
    else:
        for path in keepable_paths():
            drop(path)
        kept = []

    if os.path.exists(LOG_PATH):
        deferred.append(LOG_PATH)

    # Last, so it only goes once whatever was in it has. Plain rmdir, so
    # a folder still holding something stays.
    try:
        os.rmdir(CACHE_DIR)
    except OSError:
        pass

    if deferred:
        print(f"[uninstall] deferred to after exit: "
              f"{[os.path.basename(p) for p in deferred]}")
    return kept, deferred


def _unlink(path, attempts=6, delay=0.5):
    """Deletes a file, retrying while something still holds it open.

    The retry is the whole point. The widget is asked to quit before any
    of this runs, but it stops answering on its port before the process
    is actually gone, and on the way out it can still write config.json.
    A single attempt lost that race and left the account file behind on
    an uninstall that was told not to keep it."""
    last = None
    for attempt in range(attempts):
        try:
            os.remove(path)
            print(f"[uninstall] removed {path}")
            return True
        except FileNotFoundError:
            return True
        except OSError as e:
            last = e
            if attempt < attempts - 1:
                time.sleep(delay)
    print(f"[uninstall] still locked, deferring {path}: {last}")
    return False


def main(argv=None):
    if os.name != "nt":
        sys.exit("Uninstalling is Windows-only.")

    n = native()
    port = read_port()

    # Said plainly and before anything happens, because this is the only
    # chance to say it: what goes, and what the tick box protects.
    yes, keep_settings = n.confirm_with_checkbox(
        "Uninstall DesktopTasks?",
        "This closes the widget, removes it and its shortcuts, and takes "
        "DesktopTasks out of Settings > Apps.\n\n"
        "Your tasks are not touched. They live in your Google account, "
        "and this app only ever read them.",
        "Keep my settings and my signed-in account",
        title=APP_NAME,
        checked=True,
    )
    if not yes:
        print("[uninstall] cancelled")
        return 0

    print(f"[uninstall] starting; keep_settings={keep_settings}")
    # Before anything is deleted: the widget fetches on a timer and can
    # write config.json when it does, so a file removed under a live
    # widget can come back.
    stop_running_app(port)
    remove_shortcuts()
    n.unregister_uninstaller(APP_NAME)
    kept, deferred = remove_data(keep_settings)

    # The exes last, and from outside: this process *is* one of them when
    # run as the installed Uninstall.exe. DATA_DIR goes too, but only
    # through a plain rmdir, which refuses a folder that still holds the
    # kept settings. That is exactly the right answer.
    if FROZEN:
        doomed = [p for p in (INSTALLED_EXE_PATH, UNINSTALL_EXE_PATH)
                  if os.path.exists(p)]
        n.delete_after_exit(deferred + (doomed or [os.path.abspath(sys.executable)]),
                            directories=[DATA_DIR])
    elif deferred:
        # From source there are no exes to remove, but the log is still
        # ours and still open, so the same deferred delete applies.
        n.delete_after_exit(deferred)
    else:
        # From source there is nothing installed to delete, and deleting
        # the checkout would be absurd. The shortcuts, the registry entry
        # and the data are real and have already been dealt with.
        print("[uninstall] running from source; no installed files to remove")

    n.message_box(
        "DesktopTasks has been removed."
        + (f"\n\nKept: {', '.join(kept)}\nin {DATA_DIR}" if kept else ""),
        APP_NAME,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
