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

from paths import ASSET_DIR, CONFIG_PATH, DATA_DIR, LOOPBACK

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
ALLOWED_PATTERNS = ["dashboard*.html", "dashboard.js", "tasks.json"]

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
}

# Same, out of config.json's "window" block. The page needs these two:
# dark_theme picks the palette, and accent is the one colour the user can
# set. widget.py reads the rest of that block independently -- window
# geometry is an OS concern the page can do nothing about.
PAGE_WINDOW_SETTINGS = {
    "dark_theme": True,
    "accent": None,
}


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
        if path_only == "/settings.json":
            body = build_settings()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
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
