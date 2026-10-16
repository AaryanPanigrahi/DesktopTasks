"""
Launches the pinned tasks dashboard as a genuinely frameless window using
pywebview (Windows' built-in WebView2 engine) instead of a Chrome --app
window -- Chrome paints its own minimal titlebar on --app windows
regardless of native window styles, so it can't be made truly frameless.

Hosts the HTTP server on a daemon thread, opens the frameless webview
window pinned to the configured position/size, exposes a resize API the
page calls to self-fit its height, runs the interval Google Tasks fetch,
and reparents the window onto the desktop's own WorkerW layer so it
survives Win+D.

Not the entry point -- desktoptasks.py is. The server and the fetch both
live in this process rather than as separate ones, so there's a single
process to launch, a single one to kill, and nothing that can outlive the
widget holding its port.

That WorkerW layer doesn't receive normal mouse input (the same reason
Rainmeter/Wallpaper Engine skins need a system-wide hook to be clickable),
so there is no way to make anything inside the page clickable while
pinned. That is a decision here rather than a limitation worked around,
which is why there are no checkboxes and why the only control surface is
the system tray icon, a normal interactive window regardless of where the
main widget is parented.

Differences from DesktopCards' widget.py, which this is ported from:

  * No appearance.json. Window geometry and the few look-and-feel values
    live in config.json's "window" block, and the page-safe ones reach
    the browser through serve.py's /settings.json. If appearance.json is
    ever adopted, they move there and the snapshot-diffing that
    DesktopCards does in refresh_now comes with them -- there is nothing
    to diff yet, so Reload simply re-applies the two cheap native calls.
  * No logo_cache / logo.png. The tray icon is drawn from the accent
    colour. DesktopCards caches a resized logo.png; there is no mark for
    this project yet, and a drawn dot is not a placeholder for one -- it
    is what the tray showed originally and it tracks the accent, which a
    bitmap cannot.
  * No "Modify" menu item. That opened DesktopCards' Flask setup app.
    The equivalent here is "Reconnect Google" (connect_google), which
    needs no Flask and no second process.
"""

import json
import os
import subprocess
import sys
import threading
import time
import urllib.request

import webview
from PIL import Image, ImageDraw
import pystray

import google_tasks
import google_tasks_setup
import platform_win as native
import serve
from paths import (
    ASSET_DIR,
    CONFIG_PATH,
    DETACHED,
    FROZEN,
    LOOPBACK,
    TASKS_PATH,
    clean_child_env,
)

# The folder the sibling scripts are spawned from. That's the asset side, not
# the data side: it's where serve.py and widget.py themselves live.
PROJECT_DIR = ASSET_DIR

WINDOW_TITLE = "Tasks"
PAGE = "dashboard.html"

# Not config: these are only the size before the page's first layout pass
# corrects it (dashboard.js fitWindowToContent immediately resizes to the
# real, scale-aware size -- keep WINDOW_WIDTH in sync with dashboard.html's
# #shell { width: ... }, the actual design-width source of truth). The real
# height always comes from the page measuring its own content, and is not
# capped: a long task list is a reason for a taller window, not a reason to
# hide the last task.
WINDOW_WIDTH = 325
INITIAL_HEIGHT = 700

# Defaults for config.json's "window" block, so a config.json that predates
# the widget still launches. Position is fixed rather than draggable --
# easy_drag is off, see create_window.
WINDOW_DEFAULTS = {
    "x": 100,
    "y": 100,
    "corner_radius": 16,
    "survive_show_desktop": True,
    "dark_theme": True,
    "accent": None,  # None means ask Windows -- see resolve_accent
}


def force_exit_soon(delay=2.5):
    """A watchdog that ends this process if a clean shutdown doesn't.

    window.destroy() is supposed to end webview.start() and let main()
    return, and from source it does. Frozen it reliably leaves the
    process alive with its window handle still registered -- pywebview's
    WinForms/pythonnet loop doesn't fully unwind -- and every such
    leftover pins a ~35MB onefile unpack directory that its bootloader
    can't clean up. Three restarts, three orphans.

    So the clean path gets a head start and this is the backstop. Nothing
    is lost by it: config.json and tasks.json are written synchronously
    and complete long before here, the tray is already stopped, and the
    replacement process waits out the port on its own. os._exit rather
    than sys.exit because the point is to skip an interpreter shutdown
    that is demonstrably capable of hanging."""
    def bail():
        print("[exit] clean shutdown did not finish; exiting.")
        os._exit(0)

    t = threading.Timer(delay, bail)
    t.daemon = True
    t.start()


def spawn_self(*args):
    """Starts another copy of this app, with optional subcommand flags.

    Frozen, sys.executable *is* the app and takes no script argument.
    From source it's the interpreter and needs one -- and specifically
    needs pythonw.exe, or the new process gets a console window this one
    didn't have."""
    if FROZEN:
        cmd = [sys.executable, *args]
        # NOT PROJECT_DIR. Frozen, that's ASSET_DIR, which is this
        # process's own _MEIPASS unpack directory -- and a process's
        # current directory is locked against deletion for as long as it
        # lives. Starting the replacement there means our bootloader can
        # never remove its temp folder when we exit, so it lingers
        # forever trying: one orphaned process and one undeletable ~35MB
        # directory per restart. The exe's own folder is stable and
        # outlives everybody.
        cwd = os.path.dirname(sys.executable)
    else:
        pythonw = sys.executable.replace("python.exe", "pythonw.exe")
        cmd = [pythonw, "desktoptasks.py", *args]
        cwd = PROJECT_DIR  # where desktoptasks.py actually is
    return subprocess.Popen(
        cmd, cwd=cwd, env=clean_child_env(), **DETACHED
    )


def load_config():
    """config.json, or {} if it isn't there yet.

    Unlike google_tasks.load_config this does not fill in the OAuth
    client, because nothing here needs it -- the window has to come up
    whether or not an account is connected, and the page renders the
    not-connected state out of tasks.json like any other."""
    try:
        with open(CONFIG_PATH, "r") as f:
            return json.load(f)
    except (OSError, ValueError) as e:
        print(f"[widget] config.json unreadable ({e}); using defaults")
        return {}


def window_settings(config):
    """config.json's "window" block over WINDOW_DEFAULTS."""
    win = dict(WINDOW_DEFAULTS)
    win.update(config.get("window") or {})
    return win


def resolve_accent(win):
    """The accent colour for the tray dot.

    Defaults to the user's own Windows accent rather than a hardcoded
    blue, so the tray icon matches the rest of their desktop without
    anyone configuring it. The registry read can fail (the value is
    absent on some installs), and a tray icon is not worth failing a
    launch over."""
    accent = win.get("accent")
    if accent:
        return accent
    try:
        return native.system_accent()
    except OSError as e:
        print(f"[widget] could not read the Windows accent ({e}); using default")
        return "#0078d4"


class Api:
    """The JS-callable bridge. One method: the page fitting its own height.

    The page is the only thing that knows how tall its content is, and it
    knows it in CSS pixels after layout. Nothing on this side can compute
    that -- hence a call in rather than a measurement out."""

    def __init__(self, window, corner_radius):
        self._window = window
        self._corner_radius = corner_radius

    def resize_window(self, width, height):
        # Neither dimension is capped -- a long task list is expected to
        # grow the window as tall as it needs. The page has already
        # measured its own content; second-guessing that here only ever
        # showed up in DesktopCards as a card cut off at the bottom.
        width = max(1, int(width))
        height = max(1, int(height))
        self._window.resize(width, height)
        # Re-clipped after every resize: SetWindowRgn is in device pixels
        # against the window's current size, so a region from the old size
        # would clip a slice off the new one.
        native.round_corners(self._window, self._corner_radius)


def build_tray_image(accent):
    """The tray icon: a dot in the accent colour.

    DesktopCards resizes and caches a logo.png here. There is no mark for
    this project, and the drawn circle is not a stand-in for one -- it
    tracks the accent colour, which a bitmap cannot, so the tray dot
    always matches the widget.

    This icon matters more here than it does there. The window is pinned
    to WorkerW and receives no mouse input at all, so the tray is not a
    convenience -- it is the only way to reload, restart or quit."""
    size = 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.ellipse((4, 4, size - 4, size - 4), fill=accent)
    return img


def refresh_now(port, window, corner_radius):
    """Tray 'Reload': re-pulls from Google and tells the page to re-render.

    The fetch goes through the server's own /refresh rather than calling
    google_tasks.main() directly, so both routes share one code path and
    one lock. An expired refresh token is not a failure here -- the
    fetcher writes AUTH_EXPIRED into tasks.json, keeps the previous
    tasks, and the page renders the reconnect prompt. That is the common
    case once a week while the Cloud project is in Testing, so Reload has
    to stay quiet about it.

    survive_show_desktop is deliberately never touched here -- re-pinning
    (or un-pinning) onto the WorkerW layer is a bigger, more disruptive
    operation than this quick action should trigger; use 'Restart' for
    changes that need that."""
    try:
        req = urllib.request.Request(f"http://{LOOPBACK}:{port}/refresh", method="POST")
        urllib.request.urlopen(req, timeout=60)
    except Exception as e:
        # A 500 from /refresh lands here too, which is the no-account-
        # connected case. Still worth reloading the page below: tasks.json
        # is what carries that state to the user.
        print(f"[widget] reload failed: {e}")
    try:
        window.evaluate_js("reloadAll()")
    except Exception as e:
        print(f"[widget] page would not reload: {e}")
    # Cheap and unconditional. DesktopCards gates the native calls behind
    # an appearance.json diff because it has one to diff; here there is no
    # second source of geometry, so re-applying the clip costs one
    # SetWindowRgn and keeps this simple.
    native.round_corners(window, corner_radius)


# How long the tray's Reconnect waits for the consent callback before
# giving up. Generous, because the user is picking an account, clicking
# past the unverified-app warning and possibly doing two-factor in that
# window -- but bounded, unlike the command line's wait, which has Ctrl-C
# as its cancel and this does not. See google_tasks_setup.main's timeout.
CONNECT_TIMEOUT_SECONDS = 300

# Single-flight. Two hazards, both real with a tray menu that can be
# clicked twice in a second: google_tasks_setup.Callback keeps its
# expected_state and result as CLASS attributes, so a second run
# overwrites the first's CSRF state and its result; and each run binds its
# own loopback listener and opens its own browser tab, so the user would
# be consenting twice to decide which half-finished flow wins.
_connect_lock = threading.Lock()


def connect_google(window):
    """Tray 'Reconnect Google': runs the OAuth consent flow in-process.

    This is the one thing a user has to do on a schedule, because Google
    expires the refresh token every 7 days while the Cloud project's
    publishing status is Testing. It has to live in the tray:
    the window is reparented onto the desktop layer and receives no mouse
    input, so the page can describe the problem but can never offer the
    button that fixes it. dashboard.js's AUTH_EXPIRED notice points here
    by name.

    In-process rather than spawning `--connect`, for the reason serve.py
    keeps /refresh in-process: a frozen onefile child would re-extract the
    whole ~35MB bundle to run a few seconds of stdlib, and a detached
    child would then have to signal its result back. A daemon thread
    needs neither.

    Feedback goes through a native message box because there is nowhere
    else to put it -- the page cannot be clicked and the tray has no
    notification surface of its own. google_tasks_setup reports every
    failure by sys.exit with a message, which is why SystemExit is caught
    as the ordinary path rather than as a bug."""
    if not _connect_lock.acquire(blocking=False):
        native.message_box(
            "A Google sign-in is already in progress. Finish it in your "
            "browser, or wait for it to time out.",
            kind="warn",
        )
        return

    try:
        # No argv: a release build signs in with the bundled client. A
        # clone has no oauth_client.py, and credentials() exits with
        # instructions, which lands in the message box below.
        google_tasks_setup.main([], timeout=CONNECT_TIMEOUT_SECONDS)
    except SystemExit as e:
        # e.code is the message string sys.exit was given -- cancelled,
        # timed out, no refresh token returned, no client configured.
        message = str(e.code) if e.code else "Sign-in did not complete."
        print(f"[connect] {message}")
        native.message_box(message, kind="warn")
        return
    except Exception as e:
        print(f"[connect] failed: {e}")
        native.message_box(f"Could not connect to Google:\n\n{e}", kind="error")
        return
    finally:
        _connect_lock.release()

    # google_tasks_setup.main ends by calling google_tasks.main(), so
    # tasks.json is already fresh and carries no AUTH_EXPIRED error by the
    # time we get here. Only the page needs telling.
    print("[connect] connected; reloading the page")
    try:
        window.evaluate_js("reloadAll()")
    except Exception as e:
        print(f"[connect] connected, but the page would not reload: {e}")
    native.message_box("Google Tasks connected.")


def explain_webview_failure(exc):
    """Turns a WebView2 load failure into something actionable.

    Two different causes produce almost the same message, and the fix
    differs:

      * An incomplete unpack. A onefile exe extracts itself to a temp
        directory on every launch, and if that's interrupted -- killed
        mid-launch, overwritten while running, a temp cleaner, antivirus
        quarantining a DLL -- the interop assemblies are missing from an
        otherwise working app. Relaunching fixes it, because the next run
        extracts again.
      * A genuinely absent WebView2 runtime. It's a built-in Edge
        component on Windows 11, so this is rare, but it's the one case
        that needs a download.
    """
    message = str(exc)
    if "WebView2" not in message and "Core.dll" not in message:
        return
    print(
        "\n[webview] Could not load the WebView2 interop layer.\n"
        f"[webview] {message}\n"
        "[webview] Try launching DesktopTasks again -- an interrupted\n"
        "[webview]   unpack is the usual cause and a fresh start fixes it.\n"
        "[webview] If it keeps happening, install the WebView2 runtime:\n"
        "[webview]   https://developer.microsoft.com/microsoft-edge/webview2/\n"
    )


def data_age_seconds():
    """How long ago tasks.json was last written, or None if it never was."""
    try:
        return time.time() - os.path.getmtime(TASKS_PATH)
    except OSError:
        return None


def fetch_loop(interval_minutes, window):
    """Re-pulls from Google on an interval, for the life of the widget.

    The schedule lives here rather than in a Windows Task Scheduler job:
    the widget is already a long-lived process that knows the interval,
    and a registered job would outlive any particular install and fire
    into a widget that might not be running -- writing a tasks.json
    nobody was reading.

    The trade: tasks only refresh while the widget runs. The catch-up
    below is what makes that acceptable -- if tasks.json is already older
    than one interval, because the machine was off or the widget was
    closed, this fetches immediately on launch instead of waiting out a
    full interval while showing stale tasks."""
    interval = max(1, int(interval_minutes or 15)) * 60

    age = data_age_seconds()
    wait = 0 if age is None or age >= interval else interval - age

    while True:
        time.sleep(wait)
        wait = interval
        try:
            google_tasks.main()
        except (Exception, SystemExit) as e:
            # SystemExit too: google_tasks.main() exits outright when no
            # account is connected, and that must not kill this thread --
            # someone may connect one while the widget is running.
            #
            # A failed fetch is otherwise normal and temporary (no network,
            # an expired token). Never fatal: the loop has to survive to
            # try again at the next interval.
            print(f"[fetch] scheduled refresh failed: {e}")
            continue
        try:
            window.evaluate_js("reloadAll()")
        except Exception as e:
            print(f"[fetch] refreshed, but the page would not reload: {e}")


def restart_now(icon, window):
    """Tray 'Restart': a full process relaunch, for the settings 'Reload'
    deliberately doesn't touch (survive_show_desktop, the window position,
    anything else read once at startup).

    There's no server to shut down first -- it's a daemon thread inside
    this process, so it stops when the process does. That removes the
    hazard this used to have to work around: a serve.py subprocess
    outliving the widget that spawned it, holding the port as an orphan
    and surviving every later restart.

    The replacement still has to wait out TIME_WAIT on the port, but that
    waiting happens where it can be seen and retried, in
    serve.build_server, rather than being assumed away by a sleep."""
    icon.stop()
    # Released before spawning, not after: the replacement checks the lock
    # on startup, and this process is still alive at that moment.
    native.release_single_instance()
    spawn_self()
    window.destroy()
    force_exit_soon()


def quit_now(icon, window):
    """The tray's Quit, also reachable from outside the process.

    The lock is released explicitly because nothing is replacing this
    widget, and a lock left held would outlive the files it was
    guarding."""
    icon.stop()
    native.release_single_instance()
    window.destroy()
    force_exit_soon()


def make_tray_icon(port, window, accent, corner_radius):
    """The tray icon and its menu -- the widget's only control surface.

    Not a convenience: the window is pinned to the desktop layer and
    receives no mouse input, so every action the widget can perform has to
    be reachable from here or not at all. Reconnect Google in particular
    is a weekly errand while the Cloud project is in Testing, and it is
    the action a pinned page most obviously cannot offer itself.

    Every item runs on its own daemon thread. pystray dispatches menu
    callbacks on the thread running the icon's own message loop, so doing
    the work inline would freeze the menu -- and for Reconnect, which
    waits minutes for a human, it would wedge the tray for the duration
    of the consent screen."""
    image = build_tray_image(accent)

    def on_reload(icon, item):
        threading.Thread(
            target=refresh_now, args=(port, window, corner_radius), daemon=True
        ).start()

    def on_connect(icon, item):
        threading.Thread(target=connect_google, args=(window,), daemon=True).start()

    def on_restart(icon, item):
        restart_now(icon, window)

    def on_quit(icon, item):
        quit_now(icon, window)

    menu = pystray.Menu(
        pystray.MenuItem("Reload", on_reload),
        pystray.MenuItem("Reconnect Google", on_connect),
        pystray.MenuItem("Restart", on_restart),
        pystray.MenuItem("Quit", on_quit),
    )
    return pystray.Icon("DesktopTasks", image, "DesktopTasks", menu)


def main():
    # Before anything else, and before the port is touched. The app is
    # launched from a Start-menu shortcut and a Startup shortcut, so a
    # second instance is an ordinary event rather than a mistake -- it
    # should step aside quietly, not race for the port and die with a
    # traceback in a popup.
    if not native.claim_single_instance():
        print("Already running -- leaving the existing widget alone.")
        return

    config = load_config()
    win = window_settings(config)
    port = config.get("port", serve.DEFAULT_PORT)
    corner_radius = win.get("corner_radius", 0)
    accent = resolve_accent(win)

    # The window's own fill, shown for the moment before the page paints
    # and in the sliver between body's rounded box and the window's
    # (clipped) square one. pywebview's default is white, which flashes as
    # a bright frame on every launch and Restart under a dark page. Step 3
    # has to keep these in step with dashboard.html's --surface-0.
    page_background = "#1d2128" if win.get("dark_theme", True) else "#f3f4f6"

    # Bound before the window exists, deliberately: if the port can't be
    # had this raises here, where it's a reportable failure, instead of
    # letting a window come up pointed at nothing.
    serve.serve_in_thread(port)

    window = webview.create_window(
        WINDOW_TITLE,
        url=f"http://{LOOPBACK}:{port}/{PAGE}",
        width=WINDOW_WIDTH,
        height=INITIAL_HEIGHT,
        x=win.get("x", 100),
        y=win.get("y", 100),
        frameless=True,
        easy_drag=False,  # no drag region -- it swallowed clicks meant for
                          # the page underneath, since drag-region hit-
                          # testing runs before the page's own pointer
                          # events. Position is fixed via config.json's
                          # window.x/y instead. Moot while pinned, and it
                          # matters the moment anyone turns pinning off.
        on_top=False,
        background_color=page_background,
    )
    api = Api(window, corner_radius)
    window.expose(api.resize_window)

    window.events.shown += lambda: native.hide_from_taskbar(window)
    window.events.shown += lambda: native.round_corners(window, corner_radius)

    if win.get("survive_show_desktop", True):
        window.events.shown += lambda: native.pin_to_desktop(window)

    tray = make_tray_icon(port, window, accent, corner_radius)
    threading.Thread(target=tray.run, daemon=True).start()
    window.events.closing += lambda: tray.stop()

    # Lets another process ask this widget to restart or quit. Registered
    # here rather than earlier because they close over the tray and the
    # window, which have to exist before either can be called.
    serve.restart_hook = lambda: restart_now(tray, window)
    serve.quit_hook = lambda: quit_now(tray, window)

    # Started on 'shown' rather than here: the catch-up fetch can fire
    # immediately, and it calls evaluate_js when it finishes, which needs a
    # window that actually exists. Daemon, so it can't hold the process open.
    window.events.shown += lambda: threading.Thread(
        target=fetch_loop,
        args=(config.get("fetch_interval_minutes"), window),
        daemon=True,
    ).start()

    try:
        webview.start()
    except Exception as e:
        # pywebview resolves and loads its WebView2 interop assemblies here,
        # on the way to showing the window -- the one part of a frozen build
        # most likely to fail, and the one that fails worst. Unhandled, it
        # reaches the user as a bare traceback in a popup naming a DLL,
        # which says nothing about what to do. Catch it to say something
        # useful, then re-raise so the traceback still lands in the log.
        explain_webview_failure(e)
        raise
    # No server teardown needed -- it's a daemon thread, so returning from
    # here is all it takes.


if __name__ == "__main__":
    main()
