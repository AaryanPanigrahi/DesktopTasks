"""
Pulls your Google Tasks lists and their open tasks and writes the result to
config/tasks.json. One pass of work and exit, no loop -- whatever ends up
scheduling this (a widget process holding an interval timer, Task Scheduler)
owns the cadence, not this file.

Stdlib only, no google-api-python-client. The whole surface is a token
refresh and two GETs, none of it signed, and the official client would add
a large dependency tree to an eventual PyInstaller bundle for no behaviour
this needs. requirements.txt stays empty for the fetch path because of it.

One token refresh plus one call per task list each run. The Tasks API is
free with a quota far above anything a sane interval can reach, so nothing
here is cached.
"""

import datetime
import json
import os
import sys
import threading
import urllib.error
import urllib.parse
import urllib.request

# Absent in a fresh clone -- it is gitignored and only a release build
# carries it. Missing is a supported state, not a crash: the user supplies
# their own client through config.json or google_tasks_setup.py instead.
try:
    import oauth_client
except ImportError:
    class oauth_client:
        CLIENT_ID = None
        CLIENT_SECRET = None

# Paths all come from paths.py, which is the only module that knows the
# difference between a source run and a frozen one. Nothing here derives a
# path from __file__ -- under PyInstaller that lands in a temp directory
# and would make every launch look like a fresh install.
#
# Re-exported rather than used directly so that google_tasks_setup.py can
# keep importing them from here, which is where its credentials live.
from paths import (  # noqa: E402  (grouped with the app's own imports)
    CONFIG_DIR,
    CONFIG_PATH,
    LOOPBACK,
    TASKS_PATH,
    ensure_data_dir,
)

TOKEN_URL = "https://oauth2.googleapis.com/token"
API_BASE = "https://tasks.googleapis.com/tasks/v1"

# Read-only: this displays tasks and does not tick them off. Widening it to
# .../auth/tasks is not a code change here, but it does mean re-running the
# setup script, because a refresh token only carries the scopes that were
# consented to when it was issued.
SCOPE = "https://www.googleapis.com/auth/tasks.readonly"

# maxResults is capped at 100 by the API regardless of what we ask for, so
# this is the page size, not a limit on what gets fetched -- list_tasks()
# follows nextPageToken until the list is exhausted.
PAGE_SIZE = 100


class AuthExpired(Exception):
    """The refresh token is dead and no amount of retrying will fix it.

    Distinguished from every other failure because it is the one that needs
    the user to do something (sign in again), and because it
    is expected on a schedule rather than exceptional: a Cloud project whose
    publishing status is still "Testing" is issued refresh tokens that
    expire after 7 days. Publishing the project to production is what makes
    that stop happening; until then this fires weekly by design, which is
    why it surfaces as a reconnect prompt rather than a crash."""


def load_json(path, default=None):
    if not os.path.exists(path):
        return default
    try:
        with open(path, "r") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def load_settings():
    """The non-secret half of config.json, falling back to defaults.

    Missing is not an error: every key here has a sane default, so a fresh
    clone fetches correctly before anyone has copied a template."""
    settings = load_json(CONFIG_PATH, default={}) or {}
    return {
        "port": settings.get("port", 5100),
        "show_completed": settings.get("show_completed", False),
        "fetch_interval_minutes": settings.get("fetch_interval_minutes", 15),
        "show_notes": settings.get("show_notes", True),
        "group_by_list": settings.get("group_by_list", True),
    }


def load_config():
    """config.json, with the shipped OAuth client filled in where absent.

    A missing file is not fatal the way a missing credential file was. The
    client credentials come from oauth_client.py, so the only thing config
    supplies is the refresh token -- and "no refresh token" is a state the
    UI handles (show the connect prompt) rather than an error to exit on."""
    cfg = load_json(CONFIG_PATH, default={}) or {}
    # Explicit values win, so anyone preferring their own Cloud project can
    # override. A null in the example file is not an override.
    if not cfg.get("client_id") and oauth_client.CLIENT_ID:
        cfg["client_id"] = oauth_client.CLIENT_ID
        cfg["client_secret"] = oauth_client.CLIENT_SECRET
    return cfg


def save_config(cfg):
    """Writes config.json back without the shipped client leaking into it.

    Stripping the defaults matters: baked in once, a rotated client in a
    future release would be silently overridden by the stale copy on disk."""
    cfg = dict(cfg)
    if oauth_client.CLIENT_ID and cfg.get("client_id") == oauth_client.CLIENT_ID:
        cfg["client_id"] = None
        cfg["client_secret"] = None
    ensure_data_dir()
    with open(CONFIG_PATH, "w") as f:
        json.dump(cfg, f, indent=2)


def is_configured():
    """Whether a Google account has actually been linked.

    The only thing that answers this is the refresh token: the client
    credentials ship with the app, so their presence says nothing about
    whether anyone has signed in."""
    cfg = load_json(CONFIG_PATH, default={}) or {}
    return bool(cfg.get("refresh_token"))


def post_form(url, fields):
    """A form-encoded POST returning parsed JSON.

    Google's token endpoint is the only thing here that is not a GET, and
    it wants application/x-www-form-urlencoded rather than JSON."""
    body = urllib.parse.urlencode(fields).encode()
    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)


def access_token(gcfg):
    """Trades the stored refresh token for an access token good for an hour.

    Not cached to disk. An access token expires well before the next run in
    every configuration that matters, so storing one would mean writing a
    short-lived secret to disk to save a request that is going to be needed
    anyway."""
    try:
        payload = post_form(
            TOKEN_URL,
            {
                "client_id": gcfg["client_id"],
                "client_secret": gcfg["client_secret"],
                "refresh_token": gcfg["refresh_token"],
                "grant_type": "refresh_token",
            },
        )
    except urllib.error.HTTPError as e:
        body = {}
        try:
            body = json.loads(e.read())
        except Exception:
            pass
        # invalid_grant is the whole family of "this refresh token is no
        # longer usable": expired under Testing status, revoked from the
        # account's permissions page, or invalidated by a password change.
        # They are indistinguishable from here and have the same fix.
        if body.get("error") == "invalid_grant":
            raise AuthExpired(body.get("error_description", "invalid_grant"))
        raise
    return payload["access_token"]


def api_get(path, token, **params):
    url = f"{API_BASE}{path}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)


def list_tasklists(token):
    return api_get("/users/@me/lists", token, maxResults=PAGE_SIZE).get("items") or []


def list_tasks(token, tasklist_id, show_completed=False):
    """Every task in one list, following pagination to the end.

    show_completed is applied server-side rather than fetched and filtered
    here, which keeps a list with years of completed history from costing
    several pages to read."""
    out = []
    page_token = None
    while True:
        params = {
            "maxResults": PAGE_SIZE,
            "showCompleted": "true" if show_completed else "false",
            "showHidden": "false",
        }
        if page_token:
            params["pageToken"] = page_token
        payload = api_get(f"/lists/{tasklist_id}/tasks", token, **params)
        for task in payload.get("items") or []:
            out.append(
                {
                    "id": task.get("id"),
                    "title": task.get("title") or "(untitled)",
                    "notes": task.get("notes"),
                    # RFC 3339, but the API only stores a date: the time is
                    # always midnight UTC and setting one is not supported.
                    # Kept as the bare date so the widget cannot shift a due
                    # date by a day parsing midnight UTC into a local zone
                    # west of it.
                    "due": (task.get("due") or "")[:10] or None,
                    "status": task.get("status"),
                    "parent": task.get("parent"),
                    "position": task.get("position"),
                    "updated": task.get("updated"),
                }
            )
        page_token = payload.get("nextPageToken")
        if not page_token:
            return out


def write_tasks(lists, errors):
    data = {
        "last_updated": datetime.datetime.now().isoformat(),
        "lists": lists,
        "errors": errors,
    }
    ensure_data_dir()
    with open(TASKS_PATH, "w") as f:
        json.dump(data, f, indent=2)
    return data


def previous_lists():
    """Last run's lists, so a failed run can keep showing what it managed to
    fetch last time instead of blanking the card over a dropped
    connection."""
    return (load_json(TASKS_PATH, default={}) or {}).get("lists", [])


# Serializes main(). Two callers live inside the widget process -- the
# tray's Reload (via the server's /refresh) and the interval timer -- and
# they can land at the same moment. Both end by rewriting tasks.json
# wholesale, so overlapping runs could interleave those writes, and the
# loser's fetch would be wasted work anyway. Not reentrant: nothing calls
# main() from inside main().
_fetch_lock = threading.Lock()


def main():
    with _fetch_lock:
        return _main()


def _main():
    gcfg = load_config()
    if not gcfg.get("refresh_token"):
        sys.exit(
            "No Google account connected. Run google_tasks_setup.py to "
            "sign in."
        )

    settings = load_settings()
    only = gcfg.get("tasklist_ids") or []

    try:
        token = access_token(gcfg)
        tasklists = list_tasklists(token)
        # An empty tasklist_ids means every list, which is the default a
        # fresh setup writes. Narrowing it is how you keep one shopping list
        # off a desktop that is mostly for work.
        if only:
            tasklists = [tl for tl in tasklists if tl.get("id") in only]
        lists = [
            {
                "id": tl.get("id"),
                "title": tl.get("title") or "Tasks",
                "tasks": list_tasks(
                    token, tl.get("id"), settings["show_completed"]
                ),
            }
            for tl in tasklists
        ]
    except AuthExpired as e:
        print(
            f"[google_tasks] refresh token rejected ({e}) -- sign in "
            f"again to reconnect",
            file=sys.stderr,
        )
        # Previous tasks kept deliberately. They are stale but they are also
        # still broadly true, and a card showing last week's list with a
        # reconnect prompt is more use than an empty one.
        return write_tasks(
            previous_lists(),
            [
                {
                    "error_code": "AUTH_EXPIRED",
                    "error_message": "Google sign-in expired. Reconnect Google Tasks.",
                }
            ],
        )
    except (urllib.error.HTTPError, urllib.error.URLError, OSError) as e:
        print(f"[google_tasks] fetch failed: {e}", file=sys.stderr)
        return write_tasks(
            previous_lists(),
            [
                {
                    "error_code": "FETCH_FAILED",
                    "error_message": f"Could not reach Google Tasks ({e}).",
                }
            ],
        )

    total = sum(len(lst["tasks"]) for lst in lists)
    data = write_tasks(lists, [])
    print(f"Wrote {total} tasks across {len(lists)} lists to config/tasks.json")
    return data


if __name__ == "__main__":
    main()
