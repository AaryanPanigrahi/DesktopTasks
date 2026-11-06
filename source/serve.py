"""
Minimal local HTTP server for the dashboard folder. Exists only so
dashboard.html's fetch('tasks.json') works without CORS issues. Idle except
when a request actually comes in -- no polling, no background work.

POST /refresh calls google_tasks.main() directly in this already-running
process -- that's what the system tray icon's "Reload" (widget.py) calls.
Ported from DesktopCards, where the equivalent used to spawn a brand new
`python fetch_data.py` subprocess per click and paid a cold interpreter
start every time. Importing the fetcher as a module here pays that cost
once, at this module's own import. It still re-reads config.json fresh on
every call (main() does that itself), so nothing about *what* gets
refreshed changes, only how fast.

The interval refresh is not a separate process either: it's a timer thread
in widget.py (fetch_loop), and it shares google_tasks._fetch_lock with
/refresh so the two can't overlap.

No /appearance.json endpoint. DesktopCards expands appearance.json
server-side on every request so edits land on the next page load with no
sync step; that trick is worth keeping, but appearance.json itself was not
adopted here -- /settings.json below does the same job for the handful of
values that needed it. A full appearance.json would slot in as another
branch of do_GET.

It also serves the settings page (GET /settings) and its small API:
/api/state to read, POST /api/config to write, POST /api/connect to start
a Google sign-in. That lives here rather than in a separate Flask app the
way DesktopCards does it, because this server already exists, already runs
inside the widget process, and is already behind net_guard -- and because
the fetch and widget paths are deliberately dependency-free, which a Flask
import would end.

This module is normally hosted inside the widget process rather than run
on its own -- see serve_in_thread. Running it as a script still works and
is useful for debugging the page without the window in the way.
"""

import datetime
import fnmatch
import http.server
import json
import os
import threading
import time
import urllib.parse

import appearance
import google_tasks
import net_guard
import shortcuts

from paths import (
    ASSET_DIR,
    CONFIG_PATH,
    DATA_DIR,
    LOOPBACK,
    TASKS_PATH,
    ensure_data_dir,
    logo_path,
)

DEFAULT_PORT = 5100


def read_port():
    """The port, or the default if config.json isn't readable yet.

    Not a bare json.load at import time: that would turn a missing or
    half-written config.json into a traceback before anything else could
    run -- fatal and, under a windowless build, silent. A server that comes
    up on the default port is recoverable; one that can't be imported
    isn't."""
    try:
        with open(CONFIG_PATH, "r") as f:
            return json.load(f).get("port", DEFAULT_PORT)
    except (OSError, ValueError):
        return DEFAULT_PORT


PORT = read_port()

# Allowlist, not denylist: config.json holds the Google refresh token and
# must never be reachable over HTTP, so the rule is what IS served rather
# than what isn't. A new file in these folders is unreachable until someone
# deliberately adds it here.
ALLOWED_PATTERNS = ["dashboard*.html", "dashboard.js", "tasks.json",
                    "settings*.html", "settings.js"]

class SpacingSides:
    """Marker type for the {left, top, right, bottom} spacing block.

    Not a plain dict in WRITABLE because the sides are an allowlist of
    their own: the block comes from a browser like everything else, and
    "every key the page sent, as an int" is not a schema."""

    SIDES = ("left", "top", "right", "bottom")


# The keys the page is allowed to see, with their defaults.
# An allowlist for the same reason ALLOWED_PATTERNS is one: config.json
# holds the Google refresh token, so /settings.json is built by naming the
# safe keys rather than by removing the unsafe ones. A key added to
# config.json is invisible to the browser until it is named here.
#
# The look-and-feel half of this list now comes out of appearance.json
# rather than config.json; build_settings merges the two before reading
# the names below, so this stays one allowlist over one dict. Both files
# are expanded server-side on every request, which is what makes a
# hand-edit land on the next page load with no sync step.
PAGE_SETTINGS = {
    "show_notes": True,
    "group_by_list": True,
    "fetch_interval_minutes": 15,
    "columns": 1,
    "max_tasks": 0,
    # Dimensions. column_width is one column's design width in CSS pixels;
    # max_height caps the window, 0 meaning "as tall as the tasks need".
    # Both are page concerns -- the page owns the real geometry, see
    # dashboard.js fitWindowToContent -- so they live here, not in the
    # "window" block, which is the OS-side position.
    "column_width": 325,
    "max_height": 0,
    "scale": 1.0,
    "spacing": 0,
    # Per-side overrides, used only while custom_spacing is on. Ported
    # from DesktopCards, where one number for all four sides turned out
    # not to be enough: a widget in a screen corner wants room on two
    # sides and none on the others.
    "custom_spacing": False,
    "spacing_sides": {"left": 0, "top": 0, "right": 0, "bottom": 0},
    "opacity": 1.0,
    "translucent_background": False,
    # The page filters by these as well as the fetcher, so a change takes
    # effect on the next render rather than only on the next fetch.
    "tasklist_ids": [],
    "tasklist_order": [],
    # The built-in views -- Due today and the rest. The master switch and
    # which of them are on; see PERSONALISED below.
    "personalised_lists": True,
    "personalised_ids": ["due_today"],
}

# What the settings page is allowed to WRITE, by name and by type. This is
# the most important list in this file. config.json holds the refresh
# token and the OAuth client, and POST /api/config takes a JSON body from
# a browser -- so a key that is not named here cannot be written, however
# the request is shaped. Adding a setting means adding it here on purpose.
#
# The types are enforced too, not just the names: a string where a bool
# belongs would otherwise reach the widget and fail somewhere far from
# here.
WRITABLE = {
    "show_completed": bool,
    "show_notes": bool,
    "group_by_list": bool,
    "fetch_interval_minutes": int,
    "tasklist_ids": list,
    # The order lists are drawn in, as ids. Any list not named here is
    # drawn after the ones that are, in whatever order Google returned.
    "tasklist_order": list,
    "columns": int,
    # How many task rows the widget draws before it stops and says how
    # many were left out. 0 means no limit. The polite way to bound the
    # height: it drops whole tasks and says so, where max_height below
    # just stops drawing mid-task.
    "max_tasks": int,
    # One column's design width, and a hard ceiling on the window height.
    # max_height clips rather than reflowing -- a half-visible task at the
    # bottom edge is the point, it shows there is more below.
    "column_width": int,
    "max_height": int,
    # Ported from DesktopCards' appearance.json.
    "scale": float,
    "spacing": int,
    "custom_spacing": bool,
    "spacing_sides": SpacingSides,
    "opacity": float,
    "translucent_background": bool,
    # The built-in views. Two keys rather than one so that turning them
    # all off and turning the feature off are different states: the
    # second forgets nothing, and ticking the master switch back on
    # brings the same views back.
    "personalised_lists": bool,
    "personalised_ids": list,
}

WRITABLE_WINDOW = {
    "x": int,
    "y": int,
    "corner_radius": int,
    "survive_show_desktop": bool,
    "dark_theme": bool,
    "accent": str,          # or None, handled below
}

# Same, out of config.json's "window" block. The page needs these two:
# dark_theme picks the palette, and accent is the one colour the user can
# set. widget.py reads the rest of that block independently -- window
# geometry is an OS concern the page can do nothing about.
PAGE_WINDOW_SETTINGS = {
    "dark_theme": True,
    "accent": None,
}


def read_spacing_sides(config):
    """The four sides, with every one of them present.

    config.json may hold a partial block -- an older config has none at
    all -- and both the page and the widget want four numbers, not a
    maybe-dict."""
    saved = config.get("spacing_sides") or {}
    out = {}
    for side in SpacingSides.SIDES:
        try:
            out[side] = int(saved.get(side, 0))
        except (TypeError, ValueError):
            out[side] = 0
    return out


# The built-in views: lists the widget assembles out of the tasks already
# fetched, rather than lists Google has. They are defined twice on purpose
# -- here for the settings page's labels and counts, and in dashboard.js
# for the widget's rendering -- because the widget reads tasks.json and
# settings.json directly and never asks this endpoint. The ids and the
# rules must stay in step with PERSONALISED in dashboard.js.
#
# Ids are bare words here and prefixed with "virtual:" wherever they sit
# beside a real Google list id (tasklist_order, the Order card), so the
# two can never be confused for one another.
PERSONALISED = [
    ("due_today", "Due today",
     lambda d, t: d is not None and d <= t),
    ("overdue", "Overdue",
     lambda d, t: d is not None and d < t),
    ("due_week", "Due this week",
     lambda d, t: d is not None and d <= plus_days(t, 6)),
    ("due_order", "Due in order",
     lambda d, t: d is not None),
    ("no_due", "No due date",
     lambda d, t: d is None),
]

VIRTUAL_PREFIX = "virtual:"


def plus_days(key, days):
    """A date key `days` later. String maths would break on month ends."""
    return (datetime.date.fromisoformat(key)
            + datetime.timedelta(days=days)).isoformat()


def personalised_lists(tasks, config):
    """The built-in views, as rows for the settings page.

    Counted off the same tasks the widget draws them from: every list
    the account has, ticked or not, deduplicated by task id, because a
    view gathers across lists and Google ids are unique account-wide.

    Only the count is computed here. Which tasks and in what order is the
    widget's business, and doing it twice would be two answers to drift
    apart.

    Returned whatever personalised_lists is set to: the master switch
    decides whether the widget draws them, and the page still has to
    show the rows, faded, or there would be nothing left to switch back
    on."""
    picked = set(config.get("personalised_ids") or [])
    today = datetime.date.today().isoformat()

    seen = {}
    for lst in (tasks.get("lists") or []):
        for task in (lst.get("tasks") or []):
            seen.setdefault(task.get("id"), task.get("due") or None)

    dues = list(seen.values())
    return [
        {
            "id": VIRTUAL_PREFIX + vid,
            "title": title,
            "count": sum(1 for due in dues if rule(due, today)),
            "selected": True,
            "virtual": True,
            "picked": vid in picked,
        }
        for vid, title, rule in PERSONALISED
    ]


def dedupe_titles(lists):
    """Appends "(1)" to a built-in view whose name a real list already has.

    Two cards with the same heading is the one way these views can be
    actively confusing -- you cannot tell which "Overdue" you are looking
    at. Numbered the way a file manager numbers a name collision, and
    only the view moves: the list you made keeps the name you gave it."""
    taken = {}
    for lst in lists:
        if not lst.get("virtual"):
            taken[(lst.get("title") or "").strip().lower()] = True
    for lst in lists:
        if not lst.get("virtual"):
            continue
        base = (lst.get("title") or "").strip()
        n = 0
        while (base.lower() if n == 0 else
               f"{base} ({n})".lower()) in taken:
            n += 1
        if n:
            lst["title"] = f"{base} ({n})"
        taken[lst["title"].strip().lower()] = True
    return lists


def build_settings():
    """The page-safe subset of config.json, as JSON bytes.

    Re-read per request rather than cached at import: the point is that
    editing config.json takes effect on the next page load. A missing or
    broken file falls back to defaults, because a page that renders with
    default settings is recoverable and one that 500s is not."""
    # Through lift_account, so tasklist_ids and tasklist_order below come
    # from the account that is currently active rather than from a
    # top-level copy that only a pre-switcher config still has.
    config = appearance.merge_into(lift_account(read_config()))

    window = config.get("window") or {}
    config["spacing_sides"] = read_spacing_sides(config)
    payload = {key: config.get(key, default)
               for key, default in PAGE_SETTINGS.items()}
    payload.update({key: window.get(key, default)
                    for key, default in PAGE_WINDOW_SETTINGS.items()})
    # The two file-only blocks. They ride on /settings.json, which only
    # the widget page fetches, and are deliberately absent from
    # /api/state, which is what the settings page reads -- that is the
    # whole of "no UI for these": there is no control because the page is
    # never told they exist.
    payload["colors"] = appearance.colors()
    payload["metrics"] = appearance.metrics()
    return json.dumps(payload).encode("utf-8")

# Which URLs are answered out of DATA_DIR rather than ASSET_DIR. Everything
# the app ships with is an asset; everything it writes is data. Identical
# folders when running from source, so this only matters to a frozen build.
DATA_OWNED = ("tasks.json", "cache/")

# Set by widget.py when it hosts this server, so POST /restart has
# something to call. Left None by a standalone run, which has no widget to
# restart -- see Handler.handle_restart.
restart_hook = None
# Likewise for POST /quit, which the uninstaller uses to close the widget
# before it starts deleting the exe that widget is running from. Asking
# rather than killing matters here: the widget's own quit path releases
# the single-instance lock, and a kill leaves that lock behind.
quit_hook = None
# And POST /api/connect, which the settings page's Reconnect Google button
# calls. Same shape as the two above: registered by widget.py, absent in a
# standalone run, which then correctly reports it has no widget to ask.
connect_hook = None

# Set by widget.py to re-render the page. /refresh fetches into tasks.json,
# which the page's own poll picks up, but the page only re-reads
# /settings.json when told to. Without this a saved layout change sat in
# config.json, unused, until the next interval fetch or a tray Reload --
# which read exactly like the setting not working.
reload_hook = None

# The result of the last sign-in started from the settings page, for
# /api/state to report. A dict so widget.py can write it from its own
# thread without a callback: {"state": idle|running|ok|failed,
# "message": str}.
#
# This exists because a sign-in started from a web page must report back
# through the web page. Popping a native dialog for something the user
# began in a browser tab puts the answer somewhere they are not looking,
# and on a machine where this app is not the foreground window it is just
# an interruption.
connect_status = {"state": "idle", "message": ""}


def read_config():
    """config.json exactly as it sits on disk, or {}.

    Deliberately NOT google_tasks.load_config, which fills in the bundled
    OAuth client. This is the read side of an edit-then-write cycle, and
    writing back a config with the shipped client baked into it is the one
    thing save_config exists to prevent."""
    try:
        with open(CONFIG_PATH, "r") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


# The settings that belong to one Google account rather than to the
# widget. The page edits them as plain top-level settings and knows
# nothing about accounts; lift_account and fold_account are what make
# that true. refresh_token is in google_tasks.ACCOUNT_KEYS too but the
# page can never write it -- it is not in WRITABLE -- so it only ever
# moves during the legacy migration.
ACCOUNT_SETTINGS = ("tasklist_ids", "tasklist_order")


def lift_account(config):
    """Copies the active account's keys up to the top level.

    The same lift google_tasks.load_config does, repeated here because
    read_config deliberately bypasses load_config (it must not bake the
    shipped OAuth client into a config it is about to write back). Every
    reader below wants the active account's values under their plain
    names, and a legacy single-account config is migrated on the way."""
    acc = google_tasks.active_account(config)
    if acc:
        config["active_account"] = acc.get("id")
        config["refresh_token"] = acc.get("refresh_token")
        config["tasklist_ids"] = acc.get("tasklist_ids") or []
        config["tasklist_order"] = acc.get("tasklist_order") or []
    return config


def fold_account(config):
    """Puts those keys back on the account, ready to write to disk.

    Mirrors google_tasks.save_config. Without it a saved task selection
    would sit at the top level where the next lift overwrites it with
    the account's old value, and the setting would look like it had
    simply not saved."""
    accs = [dict(a) for a in google_tasks.accounts(config)]
    if not accs:
        return config
    acc = google_tasks.active_account(config) or accs[0]
    for saved in accs:
        if saved.get("id") == acc.get("id"):
            for key in ACCOUNT_SETTINGS:
                if key in config:
                    saved[key] = config[key]
    config["accounts"] = accs
    config["active_account"] = acc.get("id")
    # One home per key. A leftover top-level copy outranks nothing and
    # is the first thing to go stale.
    for key in google_tasks.ACCOUNT_KEYS:
        config.pop(key, None)
    return config


def coerce(value, kind):
    """A JSON value as the type the setting expects, or raise ValueError.

    JSON gives us real bools and numbers, so this is mostly a check rather
    than a conversion. The exception is accent, which is a string or null,
    and the number fields, which a form can hand over as strings."""
    if kind is bool:
        if isinstance(value, bool):
            return value
        raise ValueError("expected true or false")
    if kind is int:
        if isinstance(value, bool):
            raise ValueError("expected a number")
        return int(value)
    if kind is float:
        if isinstance(value, bool):
            raise ValueError("expected a number")
        return float(value)
    if kind is SpacingSides:
        if not isinstance(value, dict):
            raise ValueError("expected an object")
        # Unknown sides are dropped rather than rejected: there are only
        # four, and the page has no reason to send a fifth.
        return {k: int(value[k]) for k in SpacingSides.SIDES if k in value}
    if kind is list:
        if not isinstance(value, list):
            raise ValueError("expected a list")
        return [str(v) for v in value]
    if kind is str:
        # null is meaningful for accent: it means "use the Windows accent".
        if value is None or value == "":
            return None
        return str(value)
    raise ValueError("unsupported setting")


def apply_settings(patch):
    """Merges a patch into config.json and appearance.json.

    Returns (saved_config, rejected_keys). Unknown keys are reported
    rather than silently dropped, so a typo in the page shows up instead
    of quietly doing nothing.

    Two files, one allowlist. The page sends one flat patch and has no
    idea where any of it lands; everything is validated here exactly as
    before, and only at the very end is the result split -- appearance
    keys to appearance.json, the rest to config.json. Validating first
    and splitting second matters: WRITABLE is what stops a browser
    writing a key nobody allowed, and a split done earlier would mean
    two places that have to get that right."""
    config = appearance.merge_into(lift_account(read_config()))
    window = dict(config.get("window") or {})
    rejected = []

    for key, value in (patch or {}).items():
        if key == "window":
            for wkey, wvalue in (value or {}).items():
                if wkey in WRITABLE_WINDOW:
                    window[wkey] = coerce(wvalue, WRITABLE_WINDOW[wkey])
                else:
                    rejected.append("window." + wkey)
            continue
        if key == "spacing_sides":
            # Merged, not replaced, so a page that sends three sides
            # does not quietly zero the fourth.
            sides = read_spacing_sides(config)
            sides.update(coerce(value, SpacingSides))
            config[key] = sides
            continue
        if key in WRITABLE:
            config[key] = coerce(value, WRITABLE[key])
        else:
            rejected.append(key)

    config["window"] = window

    # The split. Whatever appearance.json owns comes out of the config
    # dict here, so the file holding the refresh token never grows a copy
    # of a setting that has moved.
    look = {key: config.pop(key) for key in appearance.TOP_KEYS
            if key in config}
    look.update({key: window.pop(key) for key in appearance.WINDOW_KEYS
                 if key in window})
    config["window"] = window

    fold_account(config)
    ensure_data_dir()
    with open(CONFIG_PATH, "w") as f:
        json.dump(config, f, indent=2)
    if look:
        appearance.write(look)
    # Merged again on the way out: the caller answers the page with this,
    # and the page expects the settings it just saved to be in it.
    return appearance.merge_into(config), rejected


def tasks_are_stale(tasks, config):
    """Whether tasks.json is older than one fetch interval, or empty.

    Used to decide whether a switch is worth a "Reload recommended"
    notice. Switching to an account that was fetched two minutes ago on
    a fifteen-minute interval needs no notice at all -- the data on
    screen is as fresh as it would be if you had never switched, and a
    warning there is just noise to be trained out of reading.

    An unparseable or missing timestamp counts as stale: that is a
    freshly added account with nothing shelved yet, which is exactly
    when the notice earns its place."""
    stamp = tasks.get("last_updated")
    if not stamp:
        return True
    try:
        age = datetime.datetime.now() - datetime.datetime.fromisoformat(stamp)
    except (TypeError, ValueError):
        return True
    try:
        interval = int(config.get("fetch_interval_minutes", 15))
    except (TypeError, ValueError):
        interval = 15
    return age.total_seconds() > max(1, interval) * 60


def _default_ids(config):
    ids = config.get("personalised_ids", PAGE_SETTINGS["personalised_ids"])
    return list(ids) if isinstance(ids, list) else []


def build_state(viewing=None):
    """Everything the settings page needs to draw itself, as JSON bytes.

    One request rather than four, because the page has nothing useful to
    show until it has all of it, and three of the four come off the same
    two files anyway.

    `viewing` is an account id to describe INSTEAD of the active one,
    and it changes nothing on disk. It is what makes a pending switch
    look like a switch on the settings page while the widget stays put:
    pick an account and the Task lists and Order cards redraw from that
    account's shelf and its saved selection, and only Save moves the
    widget. An unknown id is ignored rather than refused -- the worst
    case is the page drawing the active account, which is what it would
    have drawn anyway.

    Note what is NOT in here: the refresh token itself, and the OAuth
    client. The page needs to know WHETHER an account is connected, never
    the credential that proves it. Nor appearance.json's `colors` and
    `metrics` -- the appearance keys the page has controls for are merged
    in below, those two blocks are not, and that is what keeps them off
    the UI."""
    config = appearance.merge_into(lift_account(read_config()))
    window = config.get("window") or {}
    spacing_sides = read_spacing_sides(config)

    active = config.get("active_account")
    shown = next((a for a in google_tasks.accounts(config)
                  if a.get("id") == viewing), None)
    if shown is not None and viewing != active:
        # The per-account settings come off that account's entry rather
        # than off the lifted top level, which is still the active
        # account's. Everything else in config is shared, so it stays.
        config["tasklist_ids"] = shown.get("tasklist_ids") or []
        config["tasklist_order"] = shown.get("tasklist_order") or []
        tasks = google_tasks.load_json(
            google_tasks.account_tasks_path(viewing), default=None) or {}
        # Which account's tasks these are, for the stamp check below.
        active = viewing
    else:
        viewing = active
        try:
            with open(TASKS_PATH, "r") as f:
                tasks = json.load(f)
        except (OSError, ValueError):
            tasks = {}

    # A tasks.json stamped with another account is not shown at all. It
    # should not happen -- switching swaps the file -- but "should not
    # happen" is how the widget ended up showing one account's lists
    # under another's name, and an empty tab that says so is the honest
    # answer. No stamp at all means a file written before the stamp
    # existed, which belongs to whoever was active then: the active one.
    if tasks.get("account") not in (None, active):
        tasks = {"last_updated": None, "lists": [], "errors": tasks.get("errors") or []}

    # The task lists come from the last fetch rather than from a live API
    # call. It means the Accounts tab works offline and costs nothing to
    # open, and the only thing it can be out of date about is a list
    # created since the last fetch -- which Reload fixes.
    #
    # Deliberately every list, chosen or not. The Accounts tab draws its
    # checkboxes from this, so filtering here would make unticking a list
    # remove it from the page that unticked it.
    lists = [
        {
            "id": lst.get("id"),
            "title": lst.get("title") or "Tasks",
            "count": len(lst.get("tasks") or []),
            "selected": lst.get("selected", True),
        }
        for lst in (tasks.get("lists") or [])
    ]
    # The built-in views go on the end, so they sit under the real lists
    # in the Task lists card and at the tail of an order that has never
    # been arranged. Renamed if one of them collides with a real list.
    lists = dedupe_titles(lists + personalised_lists(tasks, config))

    return json.dumps({
        "connected": bool(config.get("refresh_token")),
        # Whether what is on screen is older than one fetch interval.
        # The page uses it for one thing only: whether a switch was to an
        # account whose tasks are still current, in which case there is
        # nothing to recommend and it says nothing.
        "stale": tasks_are_stale(tasks, config),
        # Id and label only. The refresh token sitting next to them in
        # config.json stays on this side of the wire, exactly as it does
        # for `connected` above -- the page needs to know WHICH accounts
        # exist and which one is live, never what proves them.
        # Which account the page is DESCRIBING, which is the pending one
        # during a switch and the active one otherwise. The page echoes
        # it back so a stale reply cannot repaint the wrong account.
        "viewing": viewing,
        "accounts": [
            {
                "id": acc.get("id"),
                "label": google_tasks.account_label(acc),
                "active": acc.get("id") == config.get("active_account"),
            }
            for acc in google_tasks.accounts(config)
        ],
        "connect": dict(connect_status),
        # Files on disk, not settings: which Windows shortcuts exist and
        # where they would go. Sent with the rest so the Appearance tab
        # draws its Shortcuts card without a second round trip, the way
        # everything else on this page is one read.
        "shortcuts": shortcuts.state(),
        "errors": tasks.get("errors") or [],
        "last_updated": tasks.get("last_updated"),
        "lists": lists,
        "settings": {
            "show_completed": config.get("show_completed", False),
            "show_notes": config.get("show_notes", True),
            "group_by_list": config.get("group_by_list", True),
            "fetch_interval_minutes": config.get("fetch_interval_minutes", 15),
            "tasklist_ids": config.get("tasklist_ids") or [],
            "tasklist_order": config.get("tasklist_order") or [],
            "personalised_lists": config.get("personalised_lists", True),
            # Defaulted through PAGE_SETTINGS, not to [], so a config
            # written before these existed shows the page the same ticks
            # the widget is already drawing from settings.json. An empty
            # list that was actually saved stays empty.
            "personalised_ids": _default_ids(config),
            "columns": config.get("columns", 1),
            "max_tasks": config.get("max_tasks", 0),
            "column_width": config.get("column_width", 325),
            "max_height": config.get("max_height", 0),
            "scale": config.get("scale", 1.0),
            "spacing": config.get("spacing", 0),
            "custom_spacing": config.get("custom_spacing", False),
            "spacing_sides": spacing_sides,
            "opacity": config.get("opacity", 1.0),
            "translucent_background": config.get("translucent_background", False),
            "window": {
                "x": window.get("x", 100),
                "y": window.get("y", 100),
                "corner_radius": window.get("corner_radius", 16),
                "survive_show_desktop": window.get("survive_show_desktop", True),
                "dark_theme": window.get("dark_theme", True),
                "accent": window.get("accent"),
            },
        },
    }).encode("utf-8")


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=ASSET_DIR, **kwargs)

    def translate_path(self, path):
        """Map a URL onto one of the two roots.

        The base class resolves against a single directory, and does the
        work that matters for safety while it's at it -- collapsing `..`,
        dropping drive letters and absolute prefixes. So resolve against
        ASSET_DIR first and let it sanitize, then re-root the handful of
        URLs that belong to the data side. Re-rooting a path that's already
        been reduced to a safe relative one can't reintroduce traversal."""
        full = super().translate_path(path)
        rel = os.path.relpath(full, ASSET_DIR).replace("\\", "/")
        if rel.startswith(".."):
            return full  # outside the root entirely; the allowlist rejects it
        if rel.startswith(DATA_OWNED):
            return os.path.join(DATA_DIR, *rel.split("/"))
        return full

    def local_only(self):
        """403s anything that isn't this machine's own browser.

        Binding to loopback keeps this server off the network; this is the
        other half, against a page in the local browser reaching in by DNS
        rebinding or cross-site POST. See net_guard."""
        reason = net_guard.rejection(
            # The server's real port, not the module-level PORT: build_server
            # can be handed a different one.
            self.server.server_address[1],
            method=self.command,
            host=self.headers.get("Host"),
            origin=self.headers.get("Origin"),
            fetch_site=self.headers.get("Sec-Fetch-Site"),
            fetch_mode=self.headers.get("Sec-Fetch-Mode"),
        )
        if reason is None:
            return True
        print(f"[serve] refused {self.command} {self.path}: {reason}")
        self.send_error(403, "Forbidden")
        return False

    def do_GET(self):
        if not self.local_only():
            return

        if self.path == "/":
            self.path = "/dashboard.html"

        path_only = self.path.split("?", 1)[0]

        # Built, not served off disk -- there is no settings.json file, and
        # deliberately so: it is a filtered view of config.json, and a
        # second file on disk would be one more thing to keep in step.
        # The settings page. A bare path rather than the .html, because
        # this is the URL the tray opens and a person may well read it.
        if path_only in ("/settings", "/settings/"):
            self.path = "/settings.html"
            path_only = "/settings.html"

        # The mark, for the settings page's header and favicon. Served
        # by its own route because it is the one asset that does not live
        # beside the page: from source it is at the repo root, and frozen
        # it is bundled flat, so paths.logo_path is the only thing that
        # knows where it actually is. It also honours a user-supplied
        # logo in the data folder, which a static path would not.
        if path_only == "/logo.png":
            try:
                with open(logo_path(), "rb") as f:
                    self.send_bytes(f.read(), "image/png")
            except OSError:
                self.send_error(404, "Not Found")
            return

        if path_only == "/api/state":
            # ?account=<id> describes that account instead of the active
            # one. Read-only, and GET for the same reason: it is the
            # settings page previewing a switch it has not committed to,
            # so it must not be able to change anything.
            query = urllib.parse.parse_qs(self.path.partition("?")[2])
            self.send_bytes(build_state((query.get("account") or [None])[0]))
            return

        if path_only == "/settings.json":
            self.send_bytes(build_settings())
            return

        name = os.path.basename(path_only)
        if not any(fnmatch.fnmatch(name, pat) for pat in ALLOWED_PATTERNS):
            self.send_error(404, "Not Found")
            return

        super().do_GET()

    def do_POST(self):
        if not self.local_only():
            return
        if self.path == "/restart":
            self.handle_restart()
            return
        if self.path == "/quit":
            self.handle_quit()
            return
        if self.path == "/api/config":
            self.handle_save_config()
            return
        if self.path == "/api/connect":
            self.handle_connect()
            return
        if self.path == "/api/account":
            self.handle_account()
            return
        if self.path == "/api/shortcuts":
            self.handle_shortcuts()
            return
        if self.path != "/refresh":
            self.send_error(404, "Not Found")
            return

        ok = True
        try:
            google_tasks.main()
        except (Exception, SystemExit) as e:
            # SystemExit too -- google_tasks.main() exits the process
            # outright when no account is connected, which would otherwise
            # silently kill just this request thread and leave the client
            # hanging instead of getting a response.
            ok = False
            print(f"[serve] /refresh failed: {e}")

        # After the fetch, not instead of it: re-reading settings is also
        # how a new tasklist selection reaches the page, and that selection
        # is what the fetch above just acted on.
        if reload_hook is not None:
            try:
                reload_hook()
            except Exception as e:
                print(f"[serve] page would not reload: {e}")

        # An expired token is NOT a failed refresh as far as this reply is
        # concerned: main() handled it, wrote AUTH_EXPIRED into tasks.json
        # and kept the previous tasks, so the fetch did its job. The page
        # renders that error out of tasks.json like any other. Reporting
        # 500 here would make the tray's Reload look broken during the
        # weekly reconnect, which is exactly when it needs to look
        # reliable.
        self.send_json({"ok": ok}, 200 if ok else 500)

    def handle_restart(self):
        """Relaunches the widget on request from another process.

        A second instance can't just start -- the single-instance lock stops
        it, and rightly so -- but doing nothing is the wrong answer when
        someone has clicked a button. Asking the running widget to restart
        itself is, and it's the same operation the tray's Restart performs.

        Only reachable when widget.py has registered the hook, so a bare
        standalone run correctly reports that it has no widget to restart
        rather than pretending to do something."""
        if restart_hook is None:
            self.send_json({"ok": False, "error": "no widget in this process"}, 404)
            return
        # Answered before acting: the restart tears down this very server,
        # so a reply sent afterwards would never arrive.
        self.send_json({"ok": True})
        try:
            self.wfile.flush()
        except OSError:
            pass
        threading.Thread(target=restart_hook, daemon=True).start()

    def handle_quit(self):
        """Shuts the widget down on request from another process.

        Needs the answer sent before the shutdown rather than after: the
        server is a thread inside the process being stopped, so a reply
        written afterwards would never leave. Same shape as handle_restart,
        and 404 from a bare standalone run for the same reason -- there is
        no widget in that process to stop."""
        if quit_hook is None:
            self.send_json({"ok": False, "error": "no widget in this process"}, 404)
            return
        self.send_json({"ok": True})
        try:
            self.wfile.flush()
        except OSError:
            pass
        threading.Thread(target=quit_hook, daemon=True).start()

    def read_body(self):
        """The request body as parsed JSON, or None.

        Length-capped: this endpoint is reachable from a page in the local
        browser, and reading an unbounded body on a thread is a way to be
        wedged by a request that never ends."""
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            return None
        if length <= 0 or length > 64 * 1024:
            return None
        try:
            return json.loads(self.rfile.read(length))
        except (OSError, ValueError):
            return None

    def handle_save_config(self):
        """Writes the settings page's changes into config.json.

        Only the keys in WRITABLE and WRITABLE_WINDOW can be written, so
        this cannot touch the refresh token or the OAuth client no matter
        what the body says."""
        patch = self.read_body()
        if patch is None:
            self.send_json({"ok": False, "error": "expected a JSON body"}, 400)
            return
        try:
            _, rejected = apply_settings(patch)
        except ValueError as e:
            self.send_json({"ok": False, "error": str(e)}, 400)
            return
        except OSError as e:
            self.send_json({"ok": False, "error": f"could not save: {e}"}, 500)
            return
        if rejected:
            print(f"[serve] ignored unknown settings: {rejected}")
        self.send_json({"ok": True, "ignored": rejected})

    def handle_account(self):
        """Switches the active account, or removes one.

        Its own route rather than a key in WRITABLE, because the id has
        to be checked against the accounts that actually exist -- the
        type-only coercion in apply_settings cannot do that, and writing
        an unknown id would leave a config that silently falls back to
        the first account. Removal could never be a setting at all.

        The page calls the switch from its Save button, after the
        settings write and before the refresh, so that the task
        selection being saved lands on the account it was edited for and
        the fetch that follows is the new account's. Nothing about a
        switch is applied until then: picking an entry in the dropdown
        only marks the form dirty.

        Deliberately does NOT fetch. Save's own refresh does that."""
        body = self.read_body()
        if body is None:
            self.send_json({"ok": False, "error": "expected a JSON body"}, 400)
            return

        wanted = str((body or {}).get("id") or "")
        config = read_config()
        known = {acc.get("id") for acc in google_tasks.accounts(config)}
        if wanted not in known:
            self.send_json({"ok": False, "error": "no such account"}, 400)
            return

        if (body or {}).get("action") == "remove":
            self.remove_account(config, wanted)
            return

        # Lift-then-fold BEFORE the switch, never after. It migrates a
        # legacy config into the accounts list, and with the old account
        # still active it is otherwise a no-op. Done the other way round
        # it is a data-loss bug: the lifted values belong to the account
        # being switched away from, and folding them once `wanted` is
        # active writes that account's task selection over this one's.
        fold_account(lift_account(config))

        # The tasks follow the account. Without this the widget keeps
        # showing the other account's lists until the next fetch, which
        # on a 15-minute interval is most of the time -- and the Task
        # lists and Order cards, which are drawn from tasks.json, would
        # be the wrong account's too.
        previous = config.get("active_account")
        if previous != wanted:
            google_tasks.stash_tasks(previous)
            google_tasks.restore_tasks(wanted)

        config["active_account"] = wanted
        try:
            ensure_data_dir()
            with open(CONFIG_PATH, "w") as f:
                json.dump(config, f, indent=2)
        except OSError as e:
            self.send_json({"ok": False, "error": f"could not save: {e}"}, 500)
            return
        # The widget is drawing the old account's tasks from a file that
        # has just been swapped under it, so it is told to re-render. No
        # fetch, so this costs nothing and is the whole reason the switch
        # is visible on the desktop immediately.
        if reload_hook is not None:
            try:
                reload_hook()
            except Exception as e:
                print(f"[serve] page would not reload: {e}")

        self.send_json({"ok": True, "active": wanted})

    def remove_account(self, config, wanted):
        """Forgets one account: its token, its settings and its tasks.

        Immediate, not pending like a switch, because it is a button
        with its own confirmation rather than a value in a form -- there
        is nothing to Save and nothing to undo, so leaving it half-done
        until a later click would only make it ambiguous.

        Removing the active account hands the widget to whichever
        account is left, and removing the last one leaves the app signed
        out, which is the honest result of removing your only account
        rather than something to refuse."""
        # Migrate first, for the reason the switch does: a legacy config
        # has no accounts list to remove anything from yet.
        fold_account(lift_account(config))
        accs = [a for a in google_tasks.accounts(config)
                if a.get("id") != wanted]

        was_active = config.get("active_account") == wanted
        config["accounts"] = accs
        if was_active:
            # The departing account's tasks go with it, so the widget is
            # handed the next account's shelf rather than a file that
            # belongs to an account that no longer exists.
            config["active_account"] = accs[0].get("id") if accs else None
            google_tasks.restore_tasks(config["active_account"])

        try:
            os.remove(google_tasks.account_tasks_path(wanted))
        except OSError:
            pass          # never fetched, or already gone

        try:
            ensure_data_dir()
            with open(CONFIG_PATH, "w") as f:
                json.dump(config, f, indent=2)
        except OSError as e:
            self.send_json({"ok": False, "error": f"could not save: {e}"}, 500)
            return

        if was_active and reload_hook is not None:
            try:
                reload_hook()
            except Exception as e:
                print(f"[serve] page would not reload: {e}")

        self.send_json({"ok": True, "removed": wanted,
                        "active": config.get("active_account")})

    def handle_shortcuts(self):
        """Writes the Startup, Start-menu and Desktop shortcuts.

        Its own route rather than keys in WRITABLE, because none of this
        is in config.json -- the answer to "does it start with Windows"
        is whether a .lnk is in the Startup folder, and that is the file
        this writes. Nothing here can reach the token or the client
        either, since it never opens config.json at all.

        A key the body leaves out is left alone, which is what lets the
        page post only the switches it has."""
        body = self.read_body()
        if body is None:
            self.send_json({"ok": False, "error": "expected a JSON body"}, 400)
            return
        wanted = {
            key: (None if body.get(key) is None else bool(body.get(key)))
            for key in ("startup", "start_menu", "desktop")
        }
        result = shortcuts.apply(wanted)
        self.send_json(result, 200 if result.get("ok") else 500)

    def handle_connect(self):
        """Starts the Google sign-in flow in the widget process.

        Answered immediately rather than when consent finishes: the flow
        waits on a human in a browser, and holding this request open for
        minutes would just time out somewhere. The page polls /api/state
        for the result instead."""
        if connect_hook is None:
            self.send_json({"ok": False, "error": "no widget in this process"}, 404)
            return
        # {"add": true} from the switcher's "Add another account". The
        # body is optional -- Reconnect Google sends none at all -- so a
        # missing or unreadable one means an ordinary reconnect.
        add = bool((self.read_body() or {}).get("add"))
        connect_status.update(state="running", message="Waiting for Google sign-in.")
        threading.Thread(target=connect_hook, args=(add,), daemon=True).start()
        self.send_json({"ok": True, "started": True})

    def send_bytes(self, body, content_type="application/json"):
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_json(self, payload, status=200):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def end_headers(self):
        # This dashboard edits its own files constantly during tuning -- a
        # stale browser cache serving an old dashboard.js is a worse bug
        # than the cost of always refetching a few tiny local files.
        self.send_header("Cache-Control", "no-store, must-revalidate")
        super().end_headers()

    def log_message(self, format, *args):
        pass  # keep it quiet


class Server(http.server.ThreadingHTTPServer):
    # HTTPServer defaults this to True, which on Windows lets a second
    # process silently bind the same port on top of a still-running one --
    # requests then get nondeterministically split between zombie
    # instances. Force a loud "port in use" error instead.
    allow_reuse_address = False


def build_server(port=None, attempts=12, delay=0.5):
    """A bound Server, retrying while the port is still occupied.

    allow_reuse_address is False on purpose (see Server), which means a
    previous instance's sockets sitting in TIME_WAIT make the bind fail
    outright rather than quietly stacking two servers on one port. The
    tray's Restart lands inside that window routinely: the old process
    exits and the replacement tries to bind a few milliseconds later.

    Waiting it out is the whole fix -- TIME_WAIT is a timer, not a
    contended lock, so retrying is the correct response and retrying
    faster wouldn't help. Raises if the port never frees up, which is a
    genuinely different situation (something else owns it) and should be
    reported rather than retried forever."""
    port = PORT if port is None else port
    last = None
    for attempt in range(attempts):
        try:
            return Server((LOOPBACK, port), Handler)
        except OSError as e:
            last = e
            if attempt + 1 < attempts:
                time.sleep(delay)
    raise OSError(
        f"could not bind {LOOPBACK}:{port} after {attempts} attempts "
        f"({last}). Another process may be using it."
    )


def serve_in_thread(port=None):
    """Runs the server on a daemon thread and hands back the Server.

    This is how the widget hosts it -- in-process rather than as a
    subprocess. Under a frozen onefile build a child spawned from
    sys.executable would re-extract the entire bundle a second time, and
    as a thread there's also nothing left to orphan: it dies with the
    process that owns it, so no server can outlive its widget and sit on
    the port."""
    httpd = build_server(port)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd


def main():
    with build_server() as httpd:
        print(f"Serving {ASSET_DIR} at http://{LOOPBACK}:{PORT}")
        httpd.serve_forever()


if __name__ == "__main__":
    main()
