"""
One-time (or run-again-to-reconnect) Google Tasks setup.

Starts a tiny loopback listener, opens Google's own consent page in your
browser, and catches the redirect it sends back. You sign in on
accounts.google.com -- nothing here ever sees your password -- and the
refresh token that comes out is written to config/config.json, which is the
only lasting credential the fetcher needs.

Run again whenever you need to reconnect. While the Cloud project's
publishing status is "Testing", Google expires refresh tokens after 7 days,
so that is expected to be weekly until the project is published. See
the README's "7-day reconnect" section for what publishing involves and
why it is deferred.

Usage:
    python google_tasks_setup.py                     # the app's own client
    python google_tasks_setup.py client_secret.json  # your own Cloud project
"""

import base64
import hashlib
import http.server
import json
import os
import secrets
import sys
import threading
import time
import urllib.parse
import webbrowser

from google_tasks import (
    CONFIG_DIR,
    LOOPBACK,
    SCOPE,
    TOKEN_URL,
    load_config,
    post_form,
    save_config,
)

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"

# Port 0, unlike anything else that will end up binding a socket here.
# Desktop-type OAuth clients are the one kind Google lets redirect to any
# loopback port without registering it, so there is nothing to keep stable
# -- and taking whatever port is free avoids colliding with whatever else
# is already up.
EPHEMERAL = 0


def credentials(client_secret_path=None):
    """The client_id/secret pair to sign in with.

    Normally the app's own, out of oauth_client.py via load_config(), so a
    user never visits the Cloud console. The optional argument is the escape
    hatch for someone running their own project: Google hands them a JSON
    file rather than two strings on screen, so accepting that file directly
    saves copying them by hand and getting one character wrong."""
    gcfg = load_config()

    if client_secret_path:
        with open(client_secret_path, "r") as f:
            blob = json.load(f)
        # Desktop clients land under "installed"; "web" is accepted as a
        # courtesy because it is an easy wrong choice to make in the console
        # and the error it would otherwise produce is about redirect URIs,
        # which does not point at the real mistake.
        section = blob.get("installed") or blob.get("web") or {}
        if not section.get("client_id"):
            sys.exit(
                f"{client_secret_path} does not look like an OAuth client "
                f"file -- expected an 'installed' section with a client_id."
            )
        gcfg["client_id"] = section["client_id"]
        gcfg["client_secret"] = section.get("client_secret", "")

    # Expected in a clone, where oauth_client.py is absent -- a release
    # build bundles one, the repo does not ship it. Not an error state so
    # much as the point at which the user has to supply a client.
    if not gcfg.get("client_id"):
        sys.exit(
            "No Google client_id. A release build bundles one; a clone "
            "does not, so supply your own -- either pass the client secret "
            "JSON from the Cloud console:\n"
            "    python google_tasks_setup.py client_secret.json\n"
            "or set client_id/client_secret in config/config.json. See "
            "source/oauth_client.example.py."
        )
    return gcfg


class Callback(http.server.BaseHTTPRequestHandler):
    """Catches the one redirect Google sends back, then gets torn down.

    net_guard MUST NOT be applied to this handler, and that is the whole
    reason it is a separate server from serve.py's. That guard refuses
    anything the browser labels cross-site, and this request is cross-site
    by construction -- a top-level navigation arriving from
    accounts.google.com -- so the rule would reject the very thing this
    exists to receive. What stands in for it is the state parameter, which
    an attacker cannot guess, plus a socket bound to loopback and only
    alive for the few seconds between opening the browser and the redirect
    landing."""

    result = None
    expected_state = None

    def do_GET(self):
        query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        got = (query.get("state") or [None])[0]
        if got != Callback.expected_state:
            self.reply("Unexpected response. Nothing was saved -- run setup again.")
            return
        error = (query.get("error") or [None])[0]
        if error:
            Callback.result = {"error": error}
            self.reply(f"Google returned an error: {error}. You can close this tab.")
            return
        code = (query.get("code") or [None])[0]
        if not code:
            self.reply("No authorization code in the response. You can close this tab.")
            return
        Callback.result = {"code": code}
        self.reply("Connected. You can close this tab and go back to DesktopTasks.")

    def reply(self, message):
        body = (
            "<!doctype html><html><head><meta charset='utf-8'>"
            "<title>Google Tasks</title><style>"
            "body{font-family:system-ui,sans-serif;background:#111;color:#eee;"
            "display:flex;align-items:center;justify-content:center;"
            "height:100vh;margin:0}div{font-size:1.1rem;text-align:center;"
            "padding:0 2rem}</style></head><body><div>"
            f"{message}</div></body></html>"
        ).encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        """Silence. The handler reports what matters through main()."""


def pkce_pair():
    """A PKCE verifier and its S256 challenge.

    Belt and braces for a desktop app: the client secret is already on this
    machine in plain text and Google knows it, which is why desktop clients
    are allowed to exist at all. PKCE is what stops a code intercepted on
    its way back through the loopback redirect from being redeemable by
    anything that did not start this exchange."""
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


def main(argv=None, timeout=None):
    """argv is the arguments after the subcommand, so that both
    `python google_tasks_setup.py client_secret.json` and
    `DesktopTasks.exe --connect client_secret.json` reach the same place.
    Defaults to reading sys.argv for the direct-script case.

    timeout is seconds to wait for the consent callback, or None to wait
    forever. None is right for the command line, where Ctrl-C is the
    cancel and a deadline would only ever fire on someone still partway
    through the consent screen (see the wait loop below). It is wrong
    inside the widget, which has no Ctrl-C: there, a user who closes the
    browser tab without consenting would otherwise leave this function
    spinning on a daemon thread for the life of the process, holding its
    loopback port and blocking the next Reconnect. widget.connect_google
    passes a generous one."""
    argv = sys.argv[1:] if argv is None else argv
    client_secret_path = argv[0] if argv else None
    gcfg = credentials(client_secret_path)

    verifier, challenge = pkce_pair()
    Callback.expected_state = secrets.token_urlsafe(32)
    Callback.result = None

    server = http.server.HTTPServer((LOOPBACK, EPHEMERAL), Callback)
    redirect_uri = f"http://{LOOPBACK}:{server.server_port}"
    threading.Thread(target=server.serve_forever, daemon=True).start()

    params = {
        "client_id": gcfg["client_id"],
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": SCOPE,
        "state": Callback.expected_state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        # Both are load-bearing. access_type=offline is what asks for a
        # refresh token at all, and prompt=consent forces the consent screen
        # even on a re-run -- without it Google remembers you already
        # agreed, returns an access token only, and reconnecting silently
        # fails to produce the one credential this script exists to get.
        "access_type": "offline",
        "prompt": "consent",
    }
    auth_url = f"{AUTH_URL}?{urllib.parse.urlencode(params)}"

    print("Opening Google sign-in in your browser...")
    print("(unverified-app warning is expected: Advanced > Go to ... (unsafe))")
    print(f"If nothing opens, paste this in yourself:\n{auth_url}\n")
    webbrowser.open(auth_url)

    # Deliberately patient. The consent screen can take a while -- picking
    # an account, the unverified-app warning, two-factor -- so any deadline
    # short enough to be useful would mostly fire on a user who was still
    # partway through it. From the command line there is none at all and
    # Ctrl-C is the cancel; the widget passes one because it has no Ctrl-C
    # and cannot afford to leak the thread. See the docstring.
    deadline = None if timeout is None else time.monotonic() + timeout
    try:
        while Callback.result is None:
            if deadline is not None and time.monotonic() > deadline:
                server.shutdown()
                sys.exit(
                    "Timed out waiting for Google sign-in. Nothing was "
                    "saved -- try Reconnect again."
                )
            threading.Event().wait(0.25)
    except KeyboardInterrupt:
        server.shutdown()
        sys.exit("\nCancelled. Nothing was saved.")

    server.shutdown()
    result = Callback.result

    if "code" not in result:
        sys.exit(f"Sign-in failed: {result.get('error', 'unknown error')}")

    tokens = post_form(
        TOKEN_URL,
        {
            "client_id": gcfg["client_id"],
            "client_secret": gcfg.get("client_secret", ""),
            "code": result["code"],
            "code_verifier": verifier,
            "grant_type": "authorization_code",
            "redirect_uri": redirect_uri,
        },
    )

    refresh_token = tokens.get("refresh_token")
    if not refresh_token:
        sys.exit(
            "Google did not return a refresh token. Revoke this app at "
            "https://myaccount.google.com/permissions and run setup again."
        )

    gcfg["refresh_token"] = refresh_token
    # Empty means every list. Left alone on a reconnect so a narrowed
    # selection survives the weekly re-auth that Testing status forces.
    gcfg.setdefault("tasklist_ids", [])
    os.makedirs(CONFIG_DIR, exist_ok=True)
    save_config(gcfg)

    print("\nConnected. Refresh token saved to config/config.json.")

    # Proves the credential works before anyone goes looking at a widget for
    # an answer, and leaves a tasks.json on disk to build the UI against.
    import google_tasks

    google_tasks.main()


if __name__ == "__main__":
    main()
