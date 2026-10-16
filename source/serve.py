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

import fnmatch
import http.server
import json
import os
import threading
import time

import google_tasks
import net_guard

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


# The keys of config.json the page is allowed to see, with their defaults.
# An allowlist for the same reason ALLOWED_PATTERNS is one: config.json
# holds the Google refresh token, so /settings.json is built by naming the
# safe keys rather than by removing the unsafe ones. A key added to
# config.json is invisible to the browser until it is named here.
#
# This is DesktopCards' /appearance.json trick in miniature -- it expands
# the file server-side on every request, so an edit lands on the next page
# load with no sync step. If appearance.json is ever adopted, the
# look-and-feel half of this moves there.
PAGE_SETTINGS = {
    "show_notes": True,
    "group_by_list": True,
    "fetch_interval_minutes": 15,
    "columns": 1,
    "max_tasks": 0,
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
    # many were left out. 0 means no limit. This is what bounds the
    # window height: the window fits its content, so capping the content
    # is the only way to cap the window.
    "max_tasks": int,
    # Ported from DesktopCards' appearance.json.
    "scale": float,
    "spacing": int,
    "custom_spacing": bool,
    "spacing_sides": SpacingSides,
    "opacity": float,
    "translucent_background": bool,
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


def build_settings():
    """The page-safe subset of config.json, as JSON bytes.

    Re-read per request rather than cached at import: the point is that
    editing config.json takes effect on the next page load. A missing or
    broken file falls back to defaults, because a page that renders with
    default settings is recoverable and one that 500s is not."""
    try:
        with open(CONFIG_PATH, "r") as f:
            config = json.load(f)
    except (OSError, ValueError):
        config = {}

    window = config.get("window") or {}
    config["spacing_sides"] = read_spacing_sides(config)
    payload = {key: config.get(key, default)
               for key, default in PAGE_SETTINGS.items()}
    payload.update({key: window.get(key, default)
                    for key, default in PAGE_WINDOW_SETTINGS.items()})
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
    """Merges a patch into config.json, honouring the allowlists.

    Returns (saved_config, rejected_keys). Unknown keys are reported
    rather than silently dropped, so a typo in the page shows up instead
    of quietly doing nothing."""
    config = read_config()
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
    ensure_data_dir()
    with open(CONFIG_PATH, "w") as f:
        json.dump(config, f, indent=2)
    return config, rejected


def build_state():
    """Everything the settings page needs to draw itself, as JSON bytes.

    One request rather than four, because the page has nothing useful to
    show until it has all of it, and three of the four come off the same
    two files anyway.

    Note what is NOT in here: the refresh token itself, and the OAuth
    client. The page needs to know WHETHER an account is connected, never
    the credential that proves it."""
    config = read_config()
    window = config.get("window") or {}
    spacing_sides = read_spacing_sides(config)

    try:
        with open(TASKS_PATH, "r") as f:
            tasks = json.load(f)
    except (OSError, ValueError):
        tasks = {}

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

    return json.dumps({
        "connected": bool(config.get("refresh_token")),
        "connect": dict(connect_status),
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
            "columns": config.get("columns", 1),
            "max_tasks": config.get("max_tasks", 0),
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
            self.send_bytes(build_state())
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

    def handle_connect(self):
        """Starts the Google sign-in flow in the widget process.

        Answered immediately rather than when consent finishes: the flow
        waits on a human in a browser, and holding this request open for
        minutes would just time out somewhere. The page polls /api/state
        for the result instead."""
        if connect_hook is None:
            self.send_json({"ok": False, "error": "no widget in this process"}, 404)
            return
        connect_status.update(state="running", message="Waiting for Google sign-in.")
        threading.Thread(target=connect_hook, daemon=True).start()
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
