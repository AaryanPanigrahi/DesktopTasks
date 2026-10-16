r"""
Where everything lives, in one place.

The repo is laid out by what a file is for, and a frozen build flattens
most of that away, so nothing derives its own paths from __file__ -- under
PyInstaller that lands in a temp directory and makes every launch look like
a fresh install.

  From source                      Frozen
  --------------------------       ------------------------------------
  source/   code and the page      inside the exe, unpacked per launch
  config/   your data + examples   %LOCALAPPDATA%\DesktopTasks (data),
                                   the example bundled in the exe
  Docs/     documentation          not shipped
  logo.png  at the repo root       bundled flat in the exe
  dist/     the built app          n/a

The four constants that matter:

  ASSET_DIR     read-only, ships with the app: dashboard.html,
                dashboard.js. source/ from source, sys._MEIPASS frozen.
                Nothing writable can live here -- under a onefile build it
                is deleted when the process exits.

  DATA_DIR      writable, per-user, survives upgrades and the exe being
                moved: config.json (the Google refresh token and your
                settings), tasks.json, cache/.

  EXAMPLES_DIR  where config.example.json is read from. config/ from
                source, and the bundle frozen, because a frozen first run
                has no repo folder to copy it out of.

  REPO_ROOT     the checkout itself. Only meaningful from source, and only
                for things that genuinely live at the top: the generated
                icon, dist/.

Ported from DesktopCards/source/paths.py. Its appearance.json and
Plaid-item paths are left out; appearance.json was deliberately not
adopted here.
"""

import os
import subprocess
import sys

FROZEN = getattr(sys, "frozen", False)

_HERE = os.path.dirname(os.path.abspath(__file__))

# _MEIPASS only exists under a PyInstaller onefile build; onedir and source
# runs both fall back to this file's own folder, which is source/.
ASSET_DIR = getattr(sys, "_MEIPASS", None) or _HERE

# One level up from source/. Frozen there is no checkout, and ASSET_DIR is
# the flattened bundle, so it stands in for the root as well.
REPO_ROOT = ASSET_DIR if FROZEN else os.path.dirname(_HERE)

if FROZEN:
    # LOCALAPPDATA rather than a folder beside the exe: the exe may well end
    # up somewhere unwritable (Program Files) or get moved, and neither
    # should cost someone the Google account they linked.
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    DATA_DIR = os.path.join(base, "DesktopTasks")
    # Bundled flat by the spec, so it sits alongside the rest of the assets.
    EXAMPLES_DIR = ASSET_DIR
else:
    DATA_DIR = os.path.join(REPO_ROOT, "config")
    # The same folder from source: the example is committed next to the
    # live file it is a template for, which is the clearest place to find
    # it when you want to copy it by hand.
    EXAMPLES_DIR = DATA_DIR

# The old name for DATA_DIR, from when paths were resolved inline in
# google_tasks.py and "config/" was literally the only answer. Kept because
# google_tasks_setup.py imports it, and because "the directory config.json
# is in" is still a thing callers legitimately want to say.
CONFIG_DIR = DATA_DIR

CONFIG_EXAMPLE_PATH = os.path.join(EXAMPLES_DIR, "config.example.json")

CONFIG_PATH = os.path.join(DATA_DIR, "config.json")
TASKS_PATH = os.path.join(DATA_DIR, "tasks.json")
CACHE_DIR = os.path.join(DATA_DIR, "cache")

# Written whenever there is no console to print to, which includes a source
# run under pythonw. In DATA_DIR rather than beside the exe for the same
# reason config.json is: the exe's folder may not be writable.
LOG_PATH = os.path.join(DATA_DIR, "desktoptasks.log")

# Bundled, read-only. The page lives with the code; the mark lives at the
# top of the checkout, since it is the project's own identity rather than
# part of the dashboard. Frozen, the spec bundles it flat, and REPO_ROOT is
# the bundle -- so this one constant covers both cases.
DASHBOARD_PATH = os.path.join(ASSET_DIR, "dashboard.html")
BUNDLED_LOGO_PATH = os.path.join(REPO_ROOT, "logo.png")

# Build output, and only ever written from source: the exe's embedded icon,
# regenerated from logo.png on every build.
ICON_PATH = os.path.join(REPO_ROOT, "DesktopTasks.ico")
DIST_DIR = os.path.join(REPO_ROOT, "dist")

# A logo dropped in DATA_DIR wins over the bundled one. From source these
# are the same file, so editing logo.png in the repo just works. Frozen,
# the bundled copy is sealed inside the exe, and this is what makes the
# mark changeable without a rebuild: drop a logo.png next to config.json.
USER_LOGO_PATH = os.path.join(DATA_DIR, "logo.png")


# Address loopback the same way every server here binds it. Not "localhost":
# that name resolves to ::1 before 127.0.0.1 on Windows, and since these
# servers are IPv4-only every client using the name pays a dead IPv6
# connection attempt first -- measured in DesktopCards at 2.08s against
# 0.02s for the literal. net_guard accepts either spelling, so this is
# purely about who we dial, never about what we accept.
LOOPBACK = "127.0.0.1"


# Popen keyword arguments for starting a process that must outlive this
# one. Without this the replacement inherits our standard handles and
# stays tied to our console/process group, and under a onefile build that
# keeps the old bootloader process alive after its own child has exited --
# an orphan holding a ~35MB unpack directory, one per restart.
#
# DETACHED_PROCESS gives it no console (it's a windowed app and shouldn't
# borrow ours), CREATE_NEW_PROCESS_GROUP keeps a Ctrl-C aimed at us from
# reaching it, and close_fds stops handle inheritance.
DETACHED = {
    "close_fds": True,
    "creationflags": (
        getattr(subprocess, "DETACHED_PROCESS", 0)
        | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    ),
}


def clean_child_env():
    """The environment to hand a spawned copy of a frozen app.

    PyInstaller's onefile bootloader tells child processes where it
    unpacked itself, through environment variables (_PYI_* on current
    versions, _MEIPASS2 historically). That's right for a child that's
    part of the same run -- it saves re-extracting tens of megabytes --
    and badly wrong for a replacement process meant to outlive us: the
    child skips extraction, uses our temp directory, and then we exit and
    the bootloader deletes it. The new process is left running against a
    directory being erased, and the first thing to go missing is the
    WebView2 interop layer, so it dies with 'Cannot find
    Microsoft.Web.WebView2.Core.dll' -- a message that points nowhere
    near the actual cause.

    Stripping them makes the replacement unpack its own copy, which is
    what an independent instance needs. Returns None when not frozen, to
    inherit the environment unchanged."""
    if not FROZEN:
        return None
    env = os.environ.copy()
    for key in list(env):
        if key.startswith("_PYI") or key.startswith("_MEIPASS"):
            del env[key]
    return env


def logo_path():
    """The logo to use, preferring a user-supplied one.

    Resolved on each call rather than at import, so replacing the file
    takes effect without restarting anything that re-reads it."""
    if USER_LOGO_PATH != BUNDLED_LOGO_PATH and os.path.exists(USER_LOGO_PATH):
        return USER_LOGO_PATH
    return BUNDLED_LOGO_PATH


def ensure_data_dir():
    """Create DATA_DIR if it isn't there yet. A no-op from source, where it's
    the repo folder, and the first thing a frozen first run needs."""
    os.makedirs(DATA_DIR, exist_ok=True)
    return DATA_DIR
