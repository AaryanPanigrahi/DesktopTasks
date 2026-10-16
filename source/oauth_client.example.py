"""Template for oauth_client.py, which is not in the repo.

`oauth_client.py` holds the OAuth client that release builds sign in with.
It is gitignored and bundled into the exe at build time, so a downloaded
release needs no Cloud console -- the user clicks through Google's consent
screen and nothing else.

A clone of this repo does not get that client. Copy this file to
`oauth_client.py` and either leave the values None, or paste in a client of
your own. With both None, `google_tasks_setup.py` falls back to asking for
a client, which you supply either way:

    python source/google_tasks_setup.py client_secret.json

or by putting `client_id` and `client_secret` in `config/config.json`,
which overrides this module regardless.

To make your own: Cloud console > enable the **Tasks API** (not Cloud
Tasks, a different product) > OAuth consent screen, External > create an
OAuth client of type **Desktop app**. The desktop type is required, not a
preference: it is the only kind Google lets redirect to an unregistered
http://127.0.0.1:<port>, which the ephemeral-port loopback listener needs.

Note these values are not really secret even in a release build. Google
classes this as an "installed app" credential, where the client secret is
acknowledged in Google's own docs as extractable from the binary. PKCE is
what actually protects the flow: an authorization code is bound to a
code_verifier that never leaves the process, so the client pair alone
grants nothing.
"""

CLIENT_ID = None
CLIENT_SECRET = None
