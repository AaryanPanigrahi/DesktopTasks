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
import hashlib
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

import appearance  # noqa: E402  (grouped with the app's own imports)

# Paths all come from paths.py, which is the only module that knows the
# difference between a source run and a frozen one. Nothing here derives a
# path from __file__ -- under PyInstaller that lands in a temp directory
# and would make every launch look like a fresh install.
#
# Re-exported rather than used directly so that google_tasks_setup.py can
# keep importing them from here, which is where its credentials live.
from paths import (  # noqa: E402  (grouped with the app's own imports)
    CACHE_DIR,
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
#
# openid and email are here only so the account switcher can label a
# dropdown entry with the address it belongs to. "Account 1 / Account 2"
# was the alternative and it is unusable the moment the two accounts are
# a personal and a work one. Nothing else reads the address, and it never
# leaves this machine.
TASKS_SCOPE = "https://www.googleapis.com/auth/tasks.readonly"
SCOPE = TASKS_SCOPE + " openid email"

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
    # show_notes and group_by_list are look-and-feel, so they live in
    # appearance.json now. Read from there rather than from config.json,
    # and only for those two -- load_config/save_config below must keep
    # seeing config.json alone, or a save would write the appearance keys
    # straight back into the file they were just moved out of.
    look = appearance.read()
    return {
        "port": settings.get("port", 5100),
        "show_completed": settings.get("show_completed", False),
        "fetch_interval_minutes": settings.get("fetch_interval_minutes", 15),
        "show_notes": look.get("show_notes", True),
        "group_by_list": look.get("group_by_list", True),
    }


# The per-account keys. Everything else in config.json is one setting for
# the whole widget; these three belong to whichever Google account is
# signed in, because a task list id from one account means nothing in
# another and a selection carried across would silently show no lists.
ACCOUNT_KEYS = ("refresh_token", "tasklist_ids", "tasklist_order")


def accounts(cfg):
    """Every signed-in account, oldest first, migrating a legacy config.

    Before the switcher there was one account, stored as a bare
    refresh_token at the top level. That config still exists on every
    machine that has been running this, so it is folded into a
    one-element list here rather than requiring anyone to sign in again.
    The fold is in memory; it reaches disk the next time anything saves.

    No email on the migrated one: the address comes from the `openid
    email` scope, which the old token was never issued with. It shows as
    "Google account" until the next reconnect fills it in."""
    saved = cfg.get("accounts")
    if isinstance(saved, list) and saved:
        return saved
    if not cfg.get("refresh_token"):
        return []
    return [{
        "id": "legacy",
        "email": "",
        **{k: cfg.get(k) for k in ACCOUNT_KEYS},
    }]


def active_account(cfg):
    """The account the widget currently fetches, or None if there is none.

    active_account naming an account that has since been removed falls
    back to the first one rather than to nothing: an unreadable id in a
    hand-edited config should not look like being signed out."""
    accs = accounts(cfg)
    if not accs:
        return None
    wanted = cfg.get("active_account")
    for acc in accs:
        if acc.get("id") == wanted:
            return acc
    return accs[0]


def account_label(acc):
    """What the dropdown calls it."""
    return (acc or {}).get("email") or "Google account"


def account_tasks_path(account_id):
    """Where this account's last fetch is kept while another is active.

    tasks.json stays the one file the widget and the settings page read --
    neither of them should have to know what an account is -- and this is
    the shelf the inactive accounts' copies sit on. Switching swaps the
    two, so a switch shows that account's tasks straight away instead of
    the other account's until the next fetch.

    Named by a hash rather than by the id, because the id is an email
    address and an email address has no business being a filename: it
    would put the user's address in a directory listing and it would
    need escaping on Windows anyway."""
    digest = hashlib.sha1((account_id or "").encode("utf-8")).hexdigest()[:12]
    return os.path.join(CACHE_DIR, f"tasks-{digest}.json")


def stash_tasks(account_id):
    """Copies the live tasks.json onto that account's shelf."""
    if not account_id:
        return
    data = load_json(TASKS_PATH, default=None)
    if data is None:
        return
    # Same stamp check as restore_tasks, from the other side: shelving a
    # file that belongs to a different account would plant the mismatch
    # rather than catch it.
    if data.get("account") not in (None, account_id):
        return
    os.makedirs(CACHE_DIR, exist_ok=True)
    with open(account_tasks_path(account_id), "w") as f:
        json.dump(data, f, indent=2)


def restore_tasks(account_id):
    """Puts that account's shelved tasks back as the live tasks.json.

    Returns whether there were any. A first switch to a freshly added
    account has nothing shelved, and the live file is emptied rather than
    left alone: showing the previous account's tasks under this one's
    name is worse than showing none and saying so."""
    data = load_json(account_tasks_path(account_id), default=None)
    # A shelf stamped with a different account is not this account's
    # tasks, whatever its filename says. It can only happen if a fetch
    # ran under a token that turned out to belong to someone else --
    # which is exactly what the account-clobbering bug used to cause --
    # and showing it would be the failure this stamp exists to prevent.
    if data is not None and data.get("account") not in (None, account_id):
        data = None
    ensure_data_dir()
    with open(TASKS_PATH, "w") as f:
        json.dump(data if data is not None else
                  {"last_updated": None, "account": account_id,
                   "lists": [], "errors": []}, f, indent=2)
    return data is not None


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

    # The active account's keys are lifted to the top level, which is
    # where every reader of this config already looks for them. That is
    # the whole trick behind multiple accounts: the fetcher, the token
    # refresh and the settings page were all written against one
    # refresh_token and one tasklist_ids, and none of them had to change
    # -- switching accounts just changes which account's values get
    # lifted here. save_config puts them back where they came from.
    acc = active_account(cfg)
    if acc:
        cfg["active_account"] = acc.get("id")
        cfg["refresh_token"] = acc.get("refresh_token")
        cfg["tasklist_ids"] = acc.get("tasklist_ids") or []
        cfg["tasklist_order"] = acc.get("tasklist_order") or []
    return cfg


def save_config(cfg):
    """Writes config.json back without the shipped client leaking into it.

    Stripping the defaults matters: baked in once, a rotated client in a
    future release would be silently overridden by the stale copy on disk."""
    cfg = dict(cfg)

    # The mirror of the lift in load_config: whatever the caller changed
    # at the top level goes back onto the account it belongs to, and the
    # top-level copies are dropped so there is exactly one home for each.
    # Without this, saving a task selection on account B would leave a
    # stale tasklist_ids at the top level that outranks nothing and
    # confuses everything.
    accs = [dict(a) for a in accounts(cfg)]
    if accs:
        acc = active_account(cfg) or accs[0]
        for saved in accs:
            if saved.get("id") == acc.get("id"):
                for key in ACCOUNT_KEYS:
                    if key in cfg:
                        saved[key] = cfg[key]
        cfg["accounts"] = accs
        cfg["active_account"] = acc.get("id")
        for key in ACCOUNT_KEYS:
            cfg.pop(key, None)

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
    # Through accounts(), so a config written since the switcher landed --
    # where the token lives inside the accounts list and not at the top
    # level -- still reads as configured.
    return any(a.get("refresh_token") for a in accounts(cfg))


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


def write_tasks(lists, errors, account_id=None):
    data = {
        "last_updated": datetime.datetime.now().isoformat(),
        # Whose tasks these are. Stamped so that nothing downstream has
        # to infer it from timing: a file that says it belongs to another
        # account is discarded rather than drawn, which is the one way to
        # be sure the widget never shows account A's tasks under account
        # B's name. Absent in a file written before the switcher existed,
        # which readers treat as "the active account's".
        "account": account_id,
        "lists": lists,
        "errors": errors,
    }
    ensure_data_dir()
    with open(TASKS_PATH, "w") as f:
        json.dump(data, f, indent=2)
    # And onto the active account's shelf, so switching away and back
    # finds this fetch rather than whatever was there before it.
    if account_id:
        stash_tasks(account_id)
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
    account_id = gcfg.get("active_account")
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
        #
        # Every list the account has is fetched, chosen or not, and
        # `selected` records which of them the widget is allowed to draw
        # as a card. Writing only the chosen lists was a dead end twice
        # over: the settings page reads its checkboxes from this file, so
        # narrowing the selection deleted the other lists from the page
        # with no way left to tick them back -- and the personalised
        # lists read across everything, so a view called "Due today" that
        # quietly skipped half the account would be worse than no view.
        #
        # The cost is one API call per unchosen list per fetch, against a
        # free, generously limited API, on a timer measured in minutes.
        lists = [
            {
                "id": tl.get("id"),
                "title": tl.get("title") or "Tasks",
                "selected": not only or tl.get("id") in only,
                "tasks": list_tasks(token, tl.get("id"),
                                    settings["show_completed"]),
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
            account_id,
        )
    except (urllib.error.HTTPError, urllib.error.URLError, OSError) as e:
        print(f"[google_tasks] fetch failed: {e}", file=sys.stderr)
        # 403 from the Tasks API with a token that refreshed fine is
        # almost always one thing: the consent screen's "See your tasks"
        # checkbox was left unticked. Google issues the token anyway --
        # it just carries no Tasks scope -- so the failure lands here,
        # one API call later, as a bare "Forbidden" that says nothing
        # about the checkbox. Hence the spelled-out message.
        forbidden = isinstance(e, urllib.error.HTTPError) and e.code == 403
        return write_tasks(
            previous_lists(),
            [
                {
                    "error_code": "NO_TASKS_SCOPE" if forbidden else "FETCH_FAILED",
                    "error_message": (
                        "Google did not grant permission to read your tasks. "
                        "Reconnect, and leave every box on the consent screen "
                        "ticked -- unticking \"See your tasks\" is what causes "
                        "this."
                    ) if forbidden else f"Could not reach Google Tasks ({e}).",
                }
            ],
            account_id,
        )

    total = sum(len(lst["tasks"]) for lst in lists)
    shown = sum(1 for lst in lists if lst["selected"])
    data = write_tasks(lists, [], account_id)
    # TASKS_PATH, not a written-out "config/tasks.json": frozen, that
    # file is in %LOCALAPPDATA%, and a log line naming the source path
    # is how an installed run gets mistaken for a checkout run.
    print(
        f"Wrote {total} tasks across {shown} of {len(lists)} lists to "
        f"{TASKS_PATH}"
    )
    return data


if __name__ == "__main__":
    main()
