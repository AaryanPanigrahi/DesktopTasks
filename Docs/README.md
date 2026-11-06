<p align="center">
  <img src="../logo.png" alt="DesktopTasks" width="100">
</p>

# DesktopTasks

A small pinned desktop widget showing your Google Tasks, built on the
Google Tasks API with user consent.

Sibling to [DesktopCards](https://github.com/AaryanPanigrahi/DesktopCards),
which does the same for bank balances. Most of the window machinery here is
ported from it, and this document notes where the two diverge and why.

This is the full reference: what every file does, and the reasoning behind
every decision that isn't obvious from reading the code.

---

## What it does

- Pulls every task list and its open tasks from Google Tasks, and writes
  `config/tasks.json`.
- Holds more than one Google account, fetches only the active one, and
  switches between them from the settings page. See
  [Several Google accounts](#several-google-accounts).
- Shows each list as a card, with subtasks nested under their parents in
  Google's own ordering.
- Calls out **overdue** and **today** in colour, and reads dates the way a
  person would: `Today`, `Tomorrow`, `Yesterday`, then `Oct 20`, then
  `Oct 10 · 6 days ago` once something has been overdue a while.
- Shows task notes, clamped to two lines so one pasted essay can't push
  everything else off the widget.
- Assembles built-in views -- Due today, Overdue, Due this week, Due in
  order, No due date -- out of the tasks it already has, and draws the
  ones you tick as cards of their own. See
  [Personalised lists](#personalised-lists).
- Deals the lists across one or more columns, in an order you drag, and
  bounds itself with a column width, a height cap and a limit on how many
  task rows it will draw.
- Sits pinned to a fixed spot as a frameless window with no taskbar icon
  and no Alt+Tab entry, and stays visible through Win+D ("show desktop").
- Sizes itself to its content after every render, so the window grows and
  shrinks with the task count rather than scrolling or clipping the last
  task. Up to the screen height, which the OS will not let a pinned window
  exceed. See [The height ceiling](#the-height-ceiling).
- A system tray icon gives you **Reload** (re-fetch now), **Modify**
  (the settings page, which is also where you sign in again. A weekly
  errand, see
  [Testing status](#testing-status-and-the-two-things-it-costs)),
  **Restart** (relaunch, for settings only read when the window is
  created) and **Quit**. The widget itself cannot be clicked at all while
  pinned (see [Pinned and read-only](#pinned-and-read-only)), so this is
  the whole control surface.
- Counts down the minutes until the next scheduled refresh next to the
  time of the last one.

- Installs itself, with a Start-menu entry, an optional Startup shortcut
  and an entry in Settings > Apps, all per-user and none of it needing
  administrator. See [What setup does](#what-setup-does).

A list with nothing open reads **All clear** rather than rendering an empty
card that looks like a failure.

---

## Getting started

Two routes, and they install nothing in common: an installed app comes from
the built exe, a checkout runs in place. See
[Three names, one binary](#three-names-one-binary) for how the built one
is packaged, and [What setup does](#what-setup-does) for what installing
actually writes.

No release has been published yet, so the installed route means building
the installer yourself:

```
pip install -r requirements.txt
pip install pyinstaller
python source/build.py          # writes dist/DesktopTasks-Setup.exe
```

From source:

```
pip install -r requirements.txt
cp config/config.example.json config/config.json   # defaults are fine
python source/desktoptasks.py --connect            # sign in to Google
pythonw source/desktoptasks.py                     # run the widget
```

`python source/google_tasks_setup.py` is the same sign-in, one layer
down; `--connect` is the form that also works from the frozen exe.

A clone needs a Google OAuth client of its own. The one a release would
bundle is deliberately not in the repo. See
[The OAuth client](#the-oauth-client-shipped-with-the-app-never-committed).

`desktoptasks.py` is the only entry point. Every mode is a flag on it:

| Command | What it does |
|---|---|
| `desktoptasks.py` | The widget |
| `desktoptasks.py --fetch` | One fetch, then exit |
| `desktoptasks.py --connect` | Sign in to Google. Takes an optional `client_secret.json` |
| `desktoptasks.py --serve` | Just the HTTP server, for working on the page in a normal browser tab |
| `desktoptasks.py --setup` | Install it, with shortcuts. What `DesktopTasks-Setup.exe` runs |
| `desktoptasks.py --uninstall` | Remove it, its shortcuts and its data. What `Uninstall.exe` runs |
| `desktoptasks.py --help` | The above |

The last two are also selected by the **exe's filename**, which is what
makes one downloaded file land in setup rather than in a widget nobody
installed. See [Three names, one binary](#three-names-one-binary). From
source the filename never matches, so a checkout only reaches them
through the flags.

Imports live inside each branch rather than at the top of the file. The
widget pulls in pywebview, pythonnet and the whole .NET interop layer, and
nothing else here needs any of it. From source that would be a slower
start, and frozen it would be wasted unpacking on every launch.

---

## Pieces

Everything in the first group lives in `source/`, the JSON in `config/`,
and the docs in `Docs/`. Only the build output and the generated icon sit
at the repo root. Paths are given bare for readability.

| File | Role |
|---|---|
| `desktoptasks.py` | The entry point. Every mode is a flag on this one file. Also redirects `stdout`/`stderr` to a log when there's no console. See [No console](#no-console-so-output-goes-to-a-file). |
| `google_tasks.py` | The fetcher. Refresh token to access token, list the task lists, list open tasks in each, write `tasks.json`. One pass and exit, no loop. The only module that talks to Google's API. Also owns the accounts model: which account is active, and the per-account task shelves. Stdlib only. |
| `google_tasks_setup.py` | The consent flow. Starts a loopback listener, opens Google's own consent page, catches the redirect, refuses a sign-in that did not grant the Tasks scope, and files the refresh token under the account's email address. Run again to reconnect, or with `add_account` to add a second one. Stdlib only. |
| `oauth_client.py` | The OAuth client a release signs in with. **Gitignored**, bundled into the exe at build time. See [The OAuth client](#the-oauth-client-shipped-with-the-app-never-committed). |
| `oauth_client.example.py` | The tracked template of the above, with `None` values and instructions for making your own client. |
| `widget.py` | Launches the pinned window: hosts the server, opens a frameless WebView2 window at the configured position, hides it from the taskbar, pins it behind the desktop icons so it survives Win+D, clips it to rounded corners, runs the interval fetch, runs the tray icon, and owns the Reconnect flow. |
| `serve.py` | Minimal local web server so the page can read its JSON. Serves only an explicit allowlist. `config.json`, which holds the refresh token, is never reachable over HTTP. Loopback-bound and behind `net_guard`. Also synthesises `/settings.json` per request. Normally a thread inside `widget.py`; still runnable alone for debugging, where `POST /restart` and `/quit` correctly report there's no widget here to act on. |
| `dashboard.html` / `dashboard.js` | The widget's UI and all its behaviour. Rendering, nesting, date handling, auto-refresh, auto-resize. |
| `settings.html` / `settings.js` | The **Modify** page, opened from the tray. Three tabs: Account, Layout, Appearance, laid out as a two-column grid of cards. The only way to change settings without editing JSON, and the only place Reconnect Google now lives. See [The settings page](#the-settings-page). |
| `paths.py` | Where every file lives. Splits read-only bundled assets from writable per-user data, which a packaged build requires and a source checkout collapses back into one folder. |
| `platform_win.py` | Every Windows-specific call in one file. Rounded-corner clipping, taskbar hiding, desktop pinning, the accent-colour registry read, the single-instance mutex, the shortcut writing, and the dialogs, Add/Remove entry and deferred self-delete that setup and uninstall are built on. Isolated so another platform means writing a sibling, not unpicking this one. |
| `net_guard.py` | The one definition of "did this request really come from this machine?". Loopback binding keeps the server off the network; this is what keeps the local browser from being used as a way in. See [Who can reach this server](#who-can-reach-this-server). |
| `logo_cache.py` | Caches the derived copies of `logo.png`. The tray PNG and a shortcut `.ico`. In the cache folder, rebuilt only when the logo's *contents* change. |
| `shortcuts.py` | The three Windows shortcuts: Startup, Start menu, Desktop. Decides what a shortcut points at (the installed exe when frozen, `pythonw.exe desktoptasks.py` from source) and reads or writes them. `platform_win.py` does the actual `.lnk` writing. Used by both the settings page and setup. |
| `setup_app.py` | Installs the app: copies the binary into `%LOCALAPPDATA%`, seeds the config files, writes the shortcuts, registers the uninstaller, launches the widget. One native dialog, no wizard. See [What setup does](#what-setup-does). |
| `uninstall.py` | Removes all of it, with a tick box that keeps your settings and your signed-in account. See [What uninstall removes](#what-uninstall-removes). |
| `build.py` / `DesktopTasks.spec` / `make_icon.py` / `version_info.txt` | Produce `dist/DesktopTasks.exe` and the setup-named copy beside it. See [Building the executable](#building-the-executable). |
| `logo.png` | The single source of truth for the app's mark: the exe icon and the tray icon both derive from it. At the repo root rather than in `source/`, because it's the project's own identity rather than part of the dashboard. |
| `config.json` | Your refresh token and all your settings. **Gitignored**: never committed. |
| `config.example.json` | A credential-free template of the above, for sharing this tool with someone else: they copy it and fill in their own values rather than yours. |
| `appearance.py` | Owns `appearance.json`: which keys live there, the one-time migration out of `config.json`, the palette and metric defaults, and the merge that lets every other module go on reading one config dict. |
| `appearance.json` | How the widget looks. **Gitignored** (it's yours), but it holds no secrets, so it is the file to open when you want to change something by hand. |
| `appearance.example.json` | The tracked template of the above, with every key and every default spelled out, including the two blocks the settings page never shows. |
| `tasks.json` | The fetcher's output, rewritten every run, and stamped with the account it came from. The single live file the widget and the page read. Gitignored, not data you'd miss. |
| `cache/tasks-<hash>.json` | One shelf per account, so switching accounts shows that account's last-fetched tasks instead of a blank widget. Written beside `tasks.json`, keyed by a hash of the account id. |
| `desktoptasks.log` | Written whenever there's no console to print to. Gitignored. |

Deliberately absent, where DesktopCards has one:

| Not here | Why |
|---|---|
| A setup *page* | DesktopCards runs its setup and settings as a second Flask app on its own port. Here the settings page is two static files served by the widget's own server, and setup is one native dialog, so there is no second process, no second port and no second framework. `setup_app.py` exists but shares nothing with its DesktopCards namesake beyond the name. |
| `accent_color.py` | Folded into `widget.resolve_accent`, which reads the accent at launch and falls back if the registry read fails. |

---

## Where your files live

Running from source, everything is in the checkout. Frozen, the code is
inside the exe and the data moves out to your profile, because the exe may
well sit somewhere unwritable or get moved, and neither should cost you the
Google account you linked.

| | From source | Frozen |
|---|---|---|
| Code and the page | `source/` | inside the exe, unpacked per launch |
| `logo.png` | repo root | bundled flat in the exe |
| `config.json`, `appearance.json`, `tasks.json`, the log | `config/` | `%LOCALAPPDATA%\DesktopTasks\` |
| Per-account task shelves, the logo cache | `config/cache/` | `%LOCALAPPDATA%\DesktopTasks\cache\` |
| `config.example.json`, `appearance.example.json` | `config/` | bundled in the exe |
| The installed app and `Uninstall.exe` | n/a | `%LOCALAPPDATA%\DesktopTasks\` |
| Shortcuts | n/a, unless you tick them | `%APPDATA%\...\Start Menu\`, `...\Startup\`, your Desktop |
| Build output | `dist/`, `build/` | n/a |

The installed exes sit in `DATA_DIR` beside the data, as
`paths.INSTALLED_EXE_PATH` and `paths.UNINSTALL_EXE_PATH`. One per-user
folder rather than Program Files, which is what keeps installing and
uninstalling free of an administrator prompt.

`paths.py` is the only module that knows the difference. Nothing else
derives a path from `__file__`. Under PyInstaller that resolves inside
`sys._MEIPASS`, a temp directory deleted on exit, which would make every
launch look like a fresh install.

The four constants that matter:

- **`ASSET_DIR`**: read-only, ships with the app: `dashboard.html`,
  `dashboard.js`. `source/` from source, `sys._MEIPASS` frozen. Nothing
  writable can live here; under a onefile build it's deleted when the
  process exits.
- **`DATA_DIR`**: writable, per-user, survives upgrades and the exe being
  moved.
- **`EXAMPLES_DIR`**: where `config.example.json` is read from. The
  bundle when frozen, because a frozen first run has no repo folder to copy
  it out of.
- **`REPO_ROOT`**: the checkout. Only meaningful from source, and only for
  things that genuinely live at the top: the generated icon and `dist/`.

`CONFIG_DIR` is an alias for `DATA_DIR`, kept because
`google_tasks_setup.py` imports that name and because "the directory
`config.json` is in" is a thing callers legitimately want to say.

---

## Configuration (`config.json` and `appearance.json`)

Two files, split by what they are rather than by what reads them.
`config.json` is the account: the Google refresh token, the OAuth client,
which lists are fetched, how often, and where the window sits.
`appearance.json` is everything about how the widget looks. Every key in
both has a sane default, so either file can be missing and the widget
still runs.

The split is DesktopCards', and it buys one concrete thing: a settings
file you can open, read top to bottom and hand to someone without ever
showing them a credential. That is what makes the two file-only blocks
below -- `colors` and `metrics` -- reasonable to have at all.

**Nothing to migrate.** The first time `appearance.json` is missing, the
look-and-feel keys are lifted out of `config.json`, written to the new
file and removed from the old one. An older `config.json` keeps working,
and neither file ends up with two copies of the same setting.

### `config.json`

| Key | Default | Meaning |
|---|---|---|
| `accounts` | `[]` | One entry per signed-in Google account: `id`, `email`, `refresh_token`, `tasklist_ids`, `tasklist_order`. Written for you when you sign in. Keep it to yourself: each token grants read access to that account's tasks. |
| `active_account` | `null` | The id of the account being fetched. The one and only account whose tasks are pulled. See [Several Google accounts](#several-google-accounts). |
| `refresh_token` | `null` | Legacy, and still how the rest of the code reads the token: the active account's keys are lifted to the top level on load and folded back on save. A pre-accounts config is migrated on the next save; nobody is signed out. |
| `tasklist_ids` | `[]` | Which lists get a card of their own, as ids. Empty means every list. Tasks are fetched for every list regardless, because the [personalised lists](#personalised-lists) read across all of them. Stored per account, and left alone on a reconnect, so a narrowed selection survives the weekly re-auth. |
| `tasklist_order` | `[]` | The order lists are drawn in, as ids. Any list not named here keeps its position behind the ones that are, so a list created later appears rather than vanishing. Per account. Set by dragging on the Layout tab. |
| `personalised_lists` | `true` | The master switch for the built-in views. Off hides them all without forgetting which were ticked. |
| `personalised_ids` | `["due_today"]` | Which views are drawn, as bare ids: `due_today`, `overdue`, `due_week`, `due_order`, `no_due`. Empty means none -- there is no "empty means all" shorthand here, unlike `tasklist_ids`. Global, not per account. |
| `port` | `5100` | Local port `serve.py` binds. |
| `fetch_interval_minutes` | `15` | How often to re-fetch. Read at launch by the widget's own timer, so a change applies on the next **Restart**: there's no schedule registered with Windows to re-apply. |
| `show_completed` | `false` | Include completed tasks. Applied server-side by the API, not filtered here, which keeps a list with years of history from costing several pages to read. |
| `client_id`, `client_secret` | `null` | Override the bundled OAuth client with your own. Explicit values always win. |
| `window.x`, `window.y` | `100` | Where the widget sits. |

### `appearance.json`

Flat, the way DesktopCards writes it: the four keys that used to sit in
`config.json`'s `window` block are at the top level here, and the widget
folds them back into `window` when it reads them.

| Key | Default | Meaning |
|---|---|---|
| `dark_theme` | `true` | Dark or light palette. |
| `accent` | `null` | Accent colour. `null` means read your Windows accent. |
| `corner_radius` | `16` | Rounded-corner clip radius, in pixels. |
| `survive_show_desktop` | `true` | Pin it behind the desktop icons. `false` makes it an ordinary floating window. |
| `columns` | `1` | How many columns to deal the lists across. The window widens to match. |
| `column_width` | `325` | One column's design width, in real pixels. `scale` does not change it: the page divides the scale back out, so larger text means fewer characters per line rather than a wider window. |
| `max_height` | `0` | A hard ceiling on the window height, in real pixels, `scale` included. `0` grows to fit every task. Unlike `max_tasks` this clips rather than reflowing, so a half-visible task at the bottom edge is the signal that there is more below. |
| `max_tasks` | `0` | Cap on rows drawn, counted across every list and every nesting level. `0` draws everything. |
| `scale` | `1.0` | Zoom on the whole page. The window follows. |
| `spacing` | `0` | Extra padding around the edges, in real pixels, and like `column_width` unaffected by `scale`. Widens and heightens the window. |
| `custom_spacing` | `false` | Use `spacing_sides` instead of the single number. |
| `spacing_sides` | all `0` | `{left, top, right, bottom}`, in pixels, used only while `custom_spacing` is on. A widget in a screen corner wants room on two sides and none on the others. |
| `opacity` | `1.0` | How solid the widget is, with `translucent_background` on. |
| `translucent_background` | `false` | Lets the wallpaper through. Needs a **Restart**, because the OS window itself has to be created transparent. |
| `show_notes` | `true` | Show notes under the title. |
| `group_by_list` | `true` | One card per list, or everything merged into one. |
| `colors` | the palette below | Per-theme colour overrides. **No UI.** |
| `metrics` | the numbers below | Spacing and text sizing. **No UI.** |

### The two blocks with no UI

`colors` and `metrics` are hand-edited only. There is no control for
either on the settings page, and that is enforced rather than merely
unimplemented: both ride on `/settings.json`, which only the widget page
fetches, and both are left out of `/api/state`, which is what the settings
page reads. The page is never told they exist, so it cannot show them and
cannot overwrite them on save.

Edit either and **Reload** from the tray. The file is re-read per request,
so there is no sync step.

**`colors`** overrides the palette token by token, per theme, under
`"light"` and `"dark"`. Anything left out keeps its default, and an
unrecognised token name is ignored:

| Token | Light | Dark | Where you see it |
|---|---|---|---|
| `surface-0` | `#f3f4f6` | `#1d2128` | The page behind the cards |
| `surface-1` | `#ffffff` | `#292e37` | A list card |
| `surface-2` | `#e5e7eb` | `#3e4651` | The task ring, dividers |
| `text-primary` | `#1f2937` | `#f2f4f7` | Task titles |
| `text-secondary` | `#374151` | `#d5dbe3` | Body text on a card |
| `text-muted` | `#6b7280` | `#a2abb8` | List titles, notes |
| `text-faint` | `#9ca3af` | `#7a8391` | The "Tasks" heading, the clock, due dates |
| `overdue` | `#dc2626` | `#f87171` | A past due date |
| `today` | `#b45309` | `#fbbf24` | A due date of today |
| `error` | `#ef4444` | `#fa8585` | The reconnect notice |
| `error-surface` | `#fef2f2` | `#43282d` | That notice's background |

Each override is written to the *raw* tier of its token, the same tier
`accent` uses, so a custom colour still goes through the translucency
layer instead of sitting opaque on top of it. Only the theme in use is
written: setting both would leave the losing theme's values live in the
element's inline style, where the stylesheet could never win them back on
a theme switch.

`accent` is deliberately not in this block. It already has a home of its
own, one table up, and two places to look is one too many when a colour
comes out wrong.

**`metrics`** is spacing and text sizing. Lengths are in real desktop
pixels and are divided back out of `scale`, like `column_width`; the two
scales are plain multipliers.

| Key | Default | Meaning |
|---|---|---|
| `font_scale` | `1.0` | Every piece of text in the widget. Distinct from `scale`, which is a zoom: that one grows the cards, the columns and the spacing along with the text, this one grows only the text, inside a layout that stays exactly where it was. |
| `task_font_scale` | `0.95` | The task title and its note, on top of `font_scale`. The two move together, because they are one block of text to read. |
| `task_indent` | `24` | How far a task sits from the card's left wall. It is the card's own left padding, so the list title steps in with the tasks rather than being left behind. |
| `task_gap` | `6` | Space between one task and the next, wall to wall. Split evenly above and below each row. |
| `task_top` | `7` | Space between the list title (or the card's top edge) and the first task. |

Both blocks' defaults live in `appearance.py` and are repeated in
`dashboard.html`, so the page draws correctly in the moment before
`/settings.json` arrives. The two have to be kept in step.

Most changes in either file land on the next **Reload**, because
`/settings.json` is rebuilt per request from both. Saving from the
settings page triggers that reload for you (see below). The window ones
(`window.x`, `window.y`, `survive_show_desktop`, `corner_radius`,
`translucent_background`) need a **Restart**, since they're only read when
the window is created, and `fetch_interval_minutes` does too, since the
timer reads it at launch. The settings page marks each
of those as applying after a Restart, and carries a **Restart widget**
button next to Save.

### Why two files, split by ownership

An earlier revision split `config/` per service. `google.json` for
credentials plus `settings.json` for the rest. On the reasoning that a
service you never enable should leave no placeholder keys lying around.
That was reversed once the app started shipping its own OAuth client,
because the meaningful line stopped being *which service* a value belongs
to and became *who owns it*:

- The **client credentials belong to the app**, so they live in source
  (`oauth_client.py`) and ride along inside the frozen binary. No copy
  step, and no way for a user to delete them by editing JSON.
- The **refresh token belongs to the user**, so it lives in a gitignored
  `config.json`, matching DesktopCards.
- **How the widget looks belongs to the user too, but is not a secret**,
  so it lives in a second gitignored file, `appearance.json` -- again
  matching DesktopCards. Keeping the two apart is what lets a colour or a
  spacing be edited by hand, and shown to someone, without the file also
  containing a token that grants read access to an inbox's worth of
  tasks.

`load_config()` fills the shipped client in wherever `config.json` leaves
`client_id` null, and `save_config()` strips it back out before writing.
That second half matters: baked in once, a rotated client in a future
release would be silently overridden by the stale copy on disk.

---

## The OAuth client, shipped with the app, never committed

The goal is that a user never opens the Google Cloud console. They click
**Reconnect Google**, consent, and that's it.

Google Tasks has **no** access path that avoids an OAuth client. There's no
CalDAV for Tasks (Calendar only), nothing in the Calendar API or an ICS
export, and a service account has no personal Google Tasks without
Workspace domain-wide delegation, which a `gmail.com` account cannot do. So
the only question was *whose* project, and making it every user's project
was unacceptable.

Hence: the app owns one OAuth client, in `source/oauth_client.py`, which is
**gitignored but bundled into the exe**. A downloaded release carries it; a
clone doesn't and brings its own.

Three consequences, each load-bearing:

1. **`google_tasks.py` imports it in a `try/except ImportError`** with a
   `None`-valued fallback. A fresh clone has no such file, and without the
   guard it's an `ImportError` on line one. "Missing" is a supported state,
   not a crash. `google_tasks_setup.py` prints instructions instead.
2. **`build.py` refuses to build without it.** Put the two facts above
   together and a release built on a machine lacking the file *succeeds*
   and produces an exe that launches, looks correct, and tells every user
   "no client configured". PyInstaller can't detect that. The import is
   conditional by design. See
   [the preflight](#the-preflight-the-one-way-this-build-can-ship-broken).
3. **It's named in the spec's `hiddenimports`** for the same reason: a
   conditional import isn't one PyInstaller reliably follows into a bundle.

### These credentials are not really secret

Google classes this as an **installed app** credential, and says so in its
own documentation: the secret ships inside every copy of the binary and can
be read straight out of it. What actually protects the flow is PKCE. An
authorization code is bound to a `code_verifier` that never leaves the
process, plus the loopback redirect. Possessing the client pair alone
grants nothing.

Bundling rather than committing is therefore about keeping the credential
out of public git history, not about hiding it from a determined user.

### Cloud console configuration

Not reproducible from the code, so it's recorded here.

- **Tasks API** enabled (`tasks.googleapis.com`). Note that searching the
  API library for "tasks" surfaces **Cloud Tasks API** first, which is an
  unrelated job-queue product. Wrong one.
- **OAuth consent screen** configured, user type **External**.
- **Scopes** `https://www.googleapis.com/auth/tasks.readonly`, plus
  `openid email`. Google labels the first *sensitive*, which is expected
  and fine. The second is what lets the account switcher label an account
  with its address instead of "Google account"; the email is read, unverified,
  out of the `id_token` the token endpoint returns, and is never sent anywhere.
- **Publishing status: Testing.** See below.
- **Test users**: the owner's own Gmail.
- **OAuth client type: Desktop app.** Required, not a preference. It's the
  only type Google lets redirect to an unregistered
  `http://127.0.0.1:<port>`, which the ephemeral-port loopback listener
  depends on. A "Web application" client rejects it.

Widening the scope to `.../auth/tasks` would not be only a code edit: a
refresh token carries only the scopes consented to when it was issued, so
every existing install would have to re-consent. Not needed while the
widget stays read-only.

`access_type=offline` **and** `prompt=consent` are both load-bearing in the
auth URL. Without the second, a re-run returns an access token only, and
reconnecting silently fails to produce the refresh token the whole flow
exists to get. `select_account` is on the same `prompt`, so adding a second
account does not silently re-consent as the one already signed in.

**A consent box can be unticked.** Google's screen lists each scope with a
checkbox, and clearing *See your tasks* still issues a perfectly valid
token. Nothing fails until the first API call, which comes back as a bare
`403` with no indication of why. So the granted scopes are checked against
the `scope` field of the token response and a sign-in without
`tasks.readonly` is refused before anything is saved, a `403` from the
fetcher is reported as `NO_TASKS_SCOPE` rather than a generic failure, and
the settings page says to leave the boxes alone before you go.

---

## Testing status, and the two things it costs

The Cloud project is in Google's **Testing** publishing status. That has
two consequences, and the second is the one that's easy to miss.

**1. Refresh tokens expire after 7 days.** So reconnecting is a weekly
errand. The fetcher treats this as an expected state rather than a crash:
`access_token()` raises `AuthExpired` on `invalid_grant`, and `main()`
writes an `AUTH_EXPIRED` error into `tasks.json` while keeping the previous
run's tasks. The widget shows a stale list plus a reconnect prompt instead
of going blank.

**2. Only listed test users can sign in at all.** An External app in
Testing admits only the Gmail addresses on its test-user list. The project
owner included. A stranger who downloads a build gets `access_denied`
before the consent screen means anything. **No code change fixes this**,
and it's the real blocker on handing this to anyone else.

Publishing to production fixes both at once: any Google account may
consent, and refresh tokens stop expiring. What remains after publishing is
the "Google hasn't verified this app" interstitial. One click behind
**Advanced**: and a ~100-user cap. Neither matters for a personal widget.
Full verification removes those and is the only part that needs Google to
review anything.

The blocker on publishing is that the console demands a homepage, a privacy
policy and a terms-of-service URL, all on a domain verified in Search
Console. `github.io` is reported to be inconsistently accepted and is
definitively rejected during formal brand verification, so a domain you own
is the reliable path. **Nothing in the code changes when that happens**:
publish, reconnect once, and `AuthExpired` simply stops firing.

---

## Pinned and read-only

This is the one real architectural fork in the project, and it was a
genuine either/or.

`pin_to_desktop()` reparents the window onto the desktop's own WorkerW
paint layer, which is what makes it survive Win+D. **That layer does not
receive normal mouse input**: the same reason Rainmeter and Wallpaper
Engine skins need a system-wide hook just to be clickable at all.

A tasks widget makes this a real decision, because ticking a task off is
the obvious thing to want. The options were:

- **Pinned and read-only.** Survives Win+D, genuinely looks like part of
  the desktop, and nothing in the page can ever be clicked.
- **Interactive and floating.** Checkboxes work. Doesn't survive Win+D, and
  is a window rather than wallpaper.
- **Both, as a setting.** Not much more work, since pinning is one call.

**Decided: pinned and read-only.** Ticking a task off was judged not worth
giving up Win+D survival and the looks-like-wallpaper quality that is the
entire point of the project. `tasks.readonly` is therefore exactly the
right scope, and it stays.

Everything downstream follows from this:

- No checkboxes, and no in-page controls of any kind.
- The dot beside each task is a **ring, not a checkbox**: deliberately,
  because anything shaped like a control would invite a click that
  silently does nothing.
- `body` sets `user-select: none` and `cursor: default`, so there's no text
  cursor or drag ghost promising interaction the window can't deliver.
- The tray icon isn't a convenience, it's the only control surface.
- `easy_drag` is off on the window. It swallowed clicks meant for the page
  underneath in DesktopCards, since drag-region hit-testing runs before the
  page's own pointer events. Position comes from `window.x`/`y` instead.
  Moot while pinned, and it matters the moment anyone turns pinning off.

### Finding the window again

Worth knowing for anyone debugging this: **a successfully pinned widget is
not findable by `FindWindowW(None, "Tasks")` or by `EnumWindows`.** Once
reparented it is no longer a top-level window, so it vanishes from the
obvious places to look, which looks exactly like "the window never
opened".

To actually find it, enumerate the children of `Progman` and of every
`WorkerW` sibling, filtering by the process id. On this machine it turns up
as a child of **`Progman`** with class `WindowsForms10.Window.8.app.*`.

That last part is `_find_workerw`'s fallback branch, and it is the one that
actually runs here: there's no separate `WorkerW` hosting
`SHELLDLL_DefView` on this build, so Progman itself is the right reparent
target. It is not dead code.

---

## How a refresh actually happens

There are two ways a fetch gets triggered, and they share one lock.

### The interval timer

`widget.fetch_loop` runs on a daemon thread for the life of the widget and
calls `google_tasks.main()` every `fetch_interval_minutes`.

The schedule lives here rather than in a Windows Task Scheduler job. The
job would work, but it's a separate artifact registered with the OS,
pointing at a script path, outliving any particular install, and firing
into a widget that might not be running. Writing a `tasks.json` nobody was
reading. The widget is already a long-lived process that knows the
interval, so the schedule belongs where it starts and stops with the thing
that displays it.

The trade is that tasks only refresh while the widget runs. What makes that
acceptable is the **catch-up**: if `tasks.json` is already older than one
interval, because the machine was off or the widget was closed, the loop
fetches immediately on launch instead of waiting out a full interval while
showing stale tasks.

The loop catches `SystemExit` as well as `Exception`, because
`google_tasks.main()` exits outright when no account is connected and that
must not kill the thread. Someone may connect one while the widget is
running.

### The tray's Reload

Goes through the server's own `POST /refresh` rather than calling the
fetcher directly, so both routes share one code path. `serve.py` calls
`google_tasks.main()` **in this already-running process**. DesktopCards
used to spawn a fresh `python fetch_data.py` per click and paid a cold
interpreter start every time; importing the fetcher as a module pays that
once, at import. It still re-reads `config.json` on every call, so nothing
about *what* gets refreshed changes, only how fast.

An expired token is **not** reported as a failed refresh by `/refresh`.
`main()` handled it, wrote `AUTH_EXPIRED` and kept the previous tasks, so
the fetch did its job; the page renders that error like any other.
Returning 500 there would make Reload look broken during the weekly
reconnect, which is exactly when it needs to look reliable.

### One lock for two callers

`google_tasks.main()` wraps `_main()` in a module-level
`threading.Lock`. Both callers live inside the widget process and can land
at the same moment, and both end by rewriting `tasks.json` wholesale, so
overlapping runs could interleave those writes, and the loser's fetch would
be wasted work anyway. Not reentrant: nothing calls `main()` from inside
`main()`.

---

## The settings page

`settings.html` and `settings.js`, opened by the tray's **Modify**. Served
by the same server the widget already runs, from the same allowlist. There
is no second process and no framework, which is the one real difference
from DesktopCards' Flask-based `setup_app.py`.

Three tabs, grouped by what you are deciding rather than by where the value
is stored:

| Tab | Holds |
|---|---|
| **Account** | Whether Google is connected, the account switcher, **Reconnect Google** / **Edit tasks** / **Remove account**, which task lists to show and which [personalised lists](#personalised-lists) to draw, and the fetch interval. |
| **Layout** | Number of columns, maximum tasks shown, and the drag-to-reorder list order. |
| **Appearance** | Theme, accent, translucency and opacity in one card, the dimensions (column width and max height), scale, breathing room, corner radius, the window position, and the Windows shortcuts. |

Each tab is a two-column grid of cards, packed tallest-first so a short
card does not leave a hole beside a long one, with the two cards that are
really the tab's tail, **Order** and nothing else, pinned full width at
the bottom. **Edit tasks** is a real link to `tasks.google.com` rather than
a button that calls `window.open`, so middle-click opens it in a background
tab like any other link; it is shown whenever an account is attached, since
an expired token is still an account whose tasks you might want to go and
edit.

Position sits under Appearance rather than Layout on purpose. Layout is
about how the lists are arranged *inside* the widget. Where the widget
itself sits on the screen is a property of the window.

### The Windows shortcuts card

Three switches: start with Windows, Start menu, desktop. They are not
settings. They are `.lnk` files, so they have their own route,
`POST /api/shortcuts`, rather than keys in `WRITABLE`, and nothing about
them is stored in `config.json`. The truth is the file on disk: deleting
the shortcut out of the Startup folder *is* turning autostart off, and a
remembered flag would only ever disagree with it.

The ticks are pending until **Save**, like everything else on the page,
and Save posts them only when a tick actually moved. Writing three
shortcuts is not work a save that changed a colour should be doing.
**Redo shortcuts** writes all three immediately, which is the one thing
the switches cannot express: a shortcut that exists but points somewhere
stale is already ticked, so Save sees nothing to do.

The card also draws the destination folder under each label, and disables
itself if `shortcuts.available()` is false. `serve.build_state` sends the
whole thing inside `/api/state` so the page still reads in one request.

### Writes go through an allowlist too

`POST /api/config` merges a patch into `config.json`, and only the keys in
`serve.WRITABLE` and `serve.WRITABLE_WINDOW` can be written, each coerced
to a declared type. The page cannot touch `refresh_token`, `client_id`,
`client_secret` or `port` no matter what it sends. Unknown keys are dropped
and reported back in the response as `ignored`, rather than failing the
whole save: a page from an older build should still be able to save the
settings it does know about.

### Saving applies immediately

`POST /api/config` is followed by `POST /refresh`, and `/refresh` now calls
`serve.reload_hook`, which `widget.py` wires to `evaluate_js("reloadAll()")`.

Both halves are needed, and each was a real bug before it was there:

- **Without the refetch**, which lists are fetched is itself a setting, so
  saving a narrower selection left the old `tasks.json` in place and the
  widget kept drawing lists that were no longer chosen.
- **Without the reload hook**, the page's own poll only re-reads
  `tasks.json`. `/settings.json` is only re-read by `reloadAll()`, so a
  saved column count or scale sat in `config.json`, unused, until the next
  interval fetch or a tray **Reload**.

Either one alone reads to the user as the setting not working.

### Every list is recorded, not only the chosen ones

`tasks.json` carries **every** list the account has, each with a
`selected` flag, and only the selected ones have their tasks fetched. An
unselected list costs one line in the file and no API call. The Layout
tab's **Order** card lists them too, faded and marked *Not shown*, so an
unticked list keeps its place in the order for when you tick it back
rather than silently falling to the end.

Writing only the chosen lists was the obvious thing and it was a dead end.
The Account tab draws its checkboxes from `tasks.json`, so narrowing the
selection deleted the other lists from the very page that had just
unticked them, with no way left to tick them again. `dashboard.js` filters
`selected === false` out before rendering.

A related trap in the same area: an empty `tasklist_ids` means *every
list*, but the page used to render every checkbox **unticked** in that
state. Unticking a list that already looked unticked did nothing, and
saving wrote the same empty list straight back. Now an empty selection
ticks every box, and saving with every box ticked writes `[]` again, which
also means a list created later shows up on its own instead of being
excluded by a stale selection.

### Sign-in reports through the server, not a dialog

`POST /api/connect` answers immediately and the page polls `/api/state`
for the result, which `widget.connect_google` writes into
`serve.connect_status`.

The flow waits on a human in a browser, so holding the request open for
minutes would just time out somewhere. More to the point, a sign-in
started in a browser tab should answer in that tab. The native message box
is still there for the same flow started from somewhere other than the
page, which is what `connect_google`'s `notify` argument selects.

---

## Personalised lists

Five views the widget assembles itself, out of the tasks it has already
fetched: **Due today** (overdue and today), **Overdue**, **Due this
week** (anything due in the next six days, overdue included), **Due in
order** (everything with a date, soonest first) and **No due date**.
They are cards like any other list, and they take their place in the
Layout **Order** alongside the real ones.

They are not Google lists, and they are not Google's **Starred**. The
Tasks API has no starred field at all -- the Task resource is `id`,
`title`, `notes`, `status`, `due`, `completed`, `parent`, `position`,
`links[]`, `webViewLink` and `assignmentInfo`, and starring exists only
in Google's own clients. These views are what can be built from what the
API does return.

**Built from every list, ticked or not.** A view gathers across the
whole account, deduplicated by task id -- ids are unique account-wide,
so a task reached twice is still one task. *Due today* means everything
due today; a view that quietly skipped the lists you keep off the
desktop would be a wrong answer rather than a narrower one. Unticking a
list still keeps its own card off the widget, which is all that tick
was ever about.

This is why the fetcher pulls tasks for every list rather than only the
chosen ones (`_main` in `google_tasks.py`). It costs one API call per
unchosen list per fetch, against a free API on a timer measured in
minutes. It also means the Account tab can print a real count beside a
list you have not ticked.

**A task can appear twice**, once in its own list's card and once in a
view. That is deliberate: a view is a lens over the tasks, not a folder
they are moved into, and a task vanishing from the list you know it
lives in would be the more surprising of the two.

**Flattened, and in their own order.** Subtasks are drawn at the top
level inside a view rather than nested, because a view's heading is a
filter and nesting under it would imply a structure that isn't there.
The order is carried in a synthetic `position` on each copied task,
because `renderList` sorts siblings by `position` -- writing them out in
due order and leaving Google's position in place would just have them
sorted back.

**A name collision is numbered.** A list you have actually called
*Overdue* keeps its name, and the built-in view becomes *Overdue (1)*,
the way a file manager numbers a duplicate. Two identically headed cards
is the one way these views can genuinely mislead.

**Defined twice, on purpose.** `PERSONALISED` exists in `dashboard.js`,
which builds the cards, and again in `serve.py`, which needs the names
and the counts for the settings page. The widget reads `tasks.json` and
`settings.json` straight off disk and never calls `/api/state`, so there
is no one place both could read. The ids and the rules have to be kept
in step by hand; each table says so.

**Two settings, not one.** `personalised_lists` is the master switch and
`personalised_ids` is which views are on. Turning the switch off has to
be different from unticking all five, or switching it back on would come
back empty. The settings page keeps the rows on screen while the switch
is off, faded and inert, so there is something visible to switch back
on, and saving while off still writes whatever was ticked.

**The ids are prefixed where they mix.** A view is `due_today` in
`personalised_ids`, and `virtual:due_today` anywhere it sits beside a
real Google list id -- in `tasklist_order`, and in the Order card's rows.
`tasklist_ids` never holds one: that list is what the fetcher asks
Google for, and a made-up id there is a request for a list that does not
exist.

## Several Google accounts

`config.json` holds an `accounts` list and an `active_account` id. Exactly
one account is fetched: the interval timer, the token refresh and the
settings page were all written against a single `refresh_token` and a
single `tasklist_ids`, and none of them had to change.

### The lift and the fold

`load_config()` ends by copying the active account's `refresh_token`,
`tasklist_ids` and `tasklist_order` up to the top level, and `save_config()`
folds them back onto that entry and removes the top-level copies before
writing. `serve.py` mirrors both halves, because it writes the file too.

So every existing reader still reads one account's worth of config, and
switching accounts is only a question of which entry gets lifted. A config
from before accounts existed is migrated in memory on load, where its bare
token becomes an entry with the id `legacy`, and reaches disk on the next
save.
Nobody is signed out by upgrading.

One ordering trap, found by a test rather than by reading: the fold has to
happen **before** `active_account` is changed. The other way round writes
the departing account's task selection onto the account you just switched
to.

### A shelf per account

Switching without fetching would otherwise show an empty widget, so each
account keeps its last fetch in `cache/tasks-<sha1(id)[:12]>.json`.
A switch stashes the current `tasks.json` onto the outgoing account's shelf
and restores the incoming one's. `tasks.json` stays the one live file the
widget and the page read.

Every one of those files carries an `"account"` stamp, and `stash_tasks`,
`restore_tasks` and `build_state` all refuse a file stamped for a different
account. The leak this guards against is one account's tasks drawn under
another's name, which is the whole reason the stamp exists. It was observed
before it did.

### Switching is a form value

Picking an account in the dropdown changes nothing yet. It is dirty state
like any other control, applied by **Save**, which posts the switch first
and the rest of the settings second. The checkboxes on screen belong to the
account you picked, so that account has to be active before the selection
is folded onto it.

Because the page previews the pick immediately (below), choosing a
different account discards unsaved ticks on the previous account's task
lists. That is no worse than never having saved them, but it happens
without a prompt.

### Previewing an account

`GET /api/state?account=<id>` describes that account instead of the active
one, and writes nothing. That means its shelf for the lists, and its own
entry for the selection and the order. The dropdown's `onchange` redraws only the
account-tied cards from it, so the settings page follows your pick while
the widget stays where it is until Save. An unknown id falls back to the
active account, the per-account `active` flags still report what is really
running, and a reply whose `viewing` is no longer the current pick is
dropped, so two fast switches cannot land out of order.

### Reload recommended

Switching does not fetch, so what you are looking at is whatever was last
pulled for that account. The page says so in a flashing notice, with the
age of that data in words, as *Last fetched 3 hours ago*, because "Reload
recommended" on its own cannot tell you whether it matters. The notice
carries the fix: a **Reload now** button, which reads **Switch and reload**
while a switch is pending and then does both. It is the one path where an
account change takes effect without Save, which is why the label says so.

### Adding and removing

**Add another account...** in the dropdown runs the same consent flow with
an explicit `add` flag. The flag is load-bearing: without it the new token
was matched against, and overwrote, the entry of the account that happened
to be active, which signed the user out of the account they meant to keep.
Accounts are matched by email address; an entry with no email is only
adopted when this is a reconnect rather than an add, and two entries that
turn out to be the same address are merged, keeping the non-empty task
selection.

**Remove account** confirms, drops the entry and deletes its shelf. If it
was the active one, the survivor's tasks are restored in its place; if
there is no survivor, `active_account` becomes `null` and the page goes
back to saying Not connected.

---

## Reconnecting Google

The one thing a user has to do on a schedule, and the action a pinned page
most obviously cannot offer itself.

`widget.connect_google` runs the consent flow **in-process on a daemon
thread**, for the same reason `/refresh` is in-process: a frozen onefile
child would re-extract the whole ~33 MB bundle to run a few seconds of
stdlib, and a detached child would then have to signal its result back. A
thread needs neither.

Feedback goes through a native message box, because there's nowhere else to
put it. The page can't be clicked and pystray has no notification surface.
`google_tasks_setup` reports **every** failure via `sys.exit(message)`, so
`SystemExit` is caught as the ordinary path and `e.code` is the
user-facing string. Treating it as a bug would turn a cancelled sign-in
into a traceback.

Two hazards made this more than a one-liner, both reachable by
double-clicking a menu item:

- **`Callback` keeps `expected_state` and `result` as class attributes**, so
  a second concurrent run overwrites the first's CSRF state and its result.
- Each run binds its own loopback listener and opens its own browser tab,
  so the user would be consenting twice with no way to know which
  half-finished flow wins.

Hence a single-flight `threading.Lock`, acquired non-blocking; a second
click warns instead of starting anything.

### The timeout, and why the CLI doesn't have one

`google_tasks_setup.main()` takes a `timeout`, defaulting to `None`.

`None`. Wait forever. Is correct for the command line. The consent screen
can take a while: picking an account, clicking past the unverified-app
warning, two-factor. Any deadline short enough to be useful would mostly
fire on someone still partway through it, and Ctrl-C is the cancel.

It's wrong inside the widget, which has no Ctrl-C. There, a user who closes
the browser tab without consenting would leave the function spinning on a
daemon thread for the life of the process, holding its ephemeral port and
the single-flight lock, so every later Reconnect would be refused. The
widget passes 300 seconds.

On success there's nothing to do but tell the page: `main()` already ends by
calling `google_tasks.main()`, so `tasks.json` is fresh and carries no
`AUTH_EXPIRED` by then.

### Every tray callback is its own thread

pystray dispatches menu callbacks on the thread running the icon's message
loop, so doing the work inline would freeze the menu. For Reconnect, which
waits minutes for a human, it would wedge the tray for the entire consent
screen.

---

## The page

`dashboard.html` holds the markup and the stylesheet; `dashboard.js` holds
all the behaviour. The whole theme is one block of variable redefinitions
under `:root[data-theme="dark"]`, so nothing downstream needs a dark
variant.

`data-theme` is seeded to `dark` in the markup because that's the shipped
default. Without it the window paints light for the moment before
`dashboard.js` reads `/settings.json` and corrects it. A flash on every
launch.

### Due dates are strings, deliberately

**The single most breakable thing in this project.**

`google_tasks.py` truncates each due date to a bare `YYYY-MM-DD` on
purpose. The API stores midnight UTC, and parsing that into any zone west
of UTC shifts the date back a day. A task due the 17th renders as the
16th and reads as overdue a day early.

So the rule throughout `dashboard.js` is: **compare due dates as strings,
and when a `Date` is unavoidable, build it from the parts in local time.**
`todayKey()` formats the local date the same way the API's dates are
formatted so the two are directly comparable; `parseLocalDate()` splits and
passes `(y, m-1, d)` explicitly. **Never pass a bare date string to
`new Date()`.**

`dayDelta()` goes through those local midnights rather than subtracting
milliseconds off the raw strings, which DST makes wrong twice a year.

`last_updated` is different. It's a full local-time ISO timestamp from
`datetime.isoformat()`, not a bare date, so `new Date()` is correct there.

### Subtask nesting and ordering

Tasks come back flat, each carrying a `parent` (another task's id, or
`null`) and a `position`.

**`position` is sorted as a string**, via `localeCompare`, never parsed as
a number. It's a 20-digit fixed-width lexicographic key, and
`Number('09999999999999999999') === Number('09999999999999999998')` is
`true`. A numeric parse collides and the order silently scrambles.

A subtask whose parent isn't in the response is **promoted to the top
level** rather than dropped. That happens for real: the parent may be
completed, and so filtered out server-side by `show_completed`, while the
child is still open. A task that silently vanishes from the widget is worse
than one shown a level too high.

Children are indented by the dot's width plus its gap, so a child's text
starts where its parent's text does. The nesting reads off the text
column rather than off a rule.

### `textContent`, never `innerHTML`

Every value out of `tasks.json` goes in through `textContent`. Task titles
and notes are arbitrary text you typed on your phone, and a title
containing `<img src=x onerror=...>` would otherwise execute inside a page
that can reach `POST /refresh` and `/quit`. `net_guard` doesn't help here. That would be our own origin asking.

### `/settings.json` is synthetic

There is no `settings.json` on disk. `serve.py` builds it per request from
an **allowlist** of `config.json` keys (`PAGE_SETTINGS` plus
`PAGE_WINDOW_SETTINGS`).

An allowlist for the same reason the file allowlist is one: `config.json`
holds the refresh token and must never be served, so the rule is what *is*
exposed rather than what isn't. A key added to `config.json` stays
invisible to the browser until it's named there.

Rebuilding per request is what makes editing `config.json` take effect on
the next page load with no sync step. DesktopCards' `/appearance.json`
trick, in miniature.

### Fitting the window to the content

`fitWindowToContent()` **computes** width and **measures** height.

Width is arithmetic, not a measurement:

```
ceil((325 * columns + 10 * (columns - 1) + spacing * 2) * scale)
```

Measuring width instead feeds the window its own current width straight
back, so it can grow but never shrink.

> **Three places hardcode the 325px design width and must change
> together:** `--col-width` in `dashboard.html`, `BASE_WIDTH` in
> `dashboard.js`, and `WINDOW_WIDTH` in `widget.py`.

Height has to be measured, because only the page knows how many tasks
there are. It reads `#shell`'s `getBoundingClientRect().height` and rounds
**up**:

- `#shell`, not `documentElement`, because `documentElement.scrollHeight`
  has a viewport floor and so never reports less than the window's current
  height.
- `getBoundingClientRect`, not `scrollHeight`, because it returns
  fractional pixels. `scrollHeight` rounds down, so content measuring
  440.6px asked for a 440px window and left 0.6px unreachable below the
  fold. With `overflow: hidden` that is invisible clipping rather than a
  scrollbar, which is worse.

`scale` is applied with CSS `zoom`, not `transform: scale`. `transform`
leaves the element's layout box at its unscaled size, so the window would
be sized for the wrong content and either clip or leave a gap. `zoom`
changes layout, so the measurement above is already the painted size.

#### The height ceiling

**Windows will not make a desktop-pinned window taller than the screen.**
Measured on a 1440px display, the window refused anything over 1462 device
pixels. Not a pywebview limit: a direct `SetWindowPos` asking for 3200 came
back 1462 as well.

Past that point the extra tasks are simply not painted, and `overflow:
hidden` means there is no scrollbar to hint at it. That is what `max_tasks`
is for: it turns silent clipping into an explicit *"N more tasks"* footer.
It is off by default, because most lists never reach the ceiling, and a cap
on a list that fits would be hiding tasks for no reason.

The call is wrapped in `requestAnimationFrame` so it measures after layout,
and guarded on `window.pywebview` so the page also works in a plain browser
tab under `--serve`, where it falls back to `window.resizeTo` with the
chrome's overhead added back.

`widget.Api.resize_window` re-applies the corner clip after every resize:
`SetWindowRgn` works in device pixels against the window's current size, so
a region from the old size would clip a slice off the new one.

### States the page renders

| State | How it reads |
|---|---|
| A list with no open tasks | **All clear**: a success, not a failure |
| No lists at all | **No task lists**: nothing connected or nothing selected, which is different from being done |
| `AUTH_EXPIRED` | The message, plus *"Tray icon > Modify > Reconnect Google. Tasks below are from the last successful fetch."* |
| `FETCH_FAILED` | The message, plus *"Retrying at the next refresh."* Same promise about the tasks below. |
| No `tasks.json` at all | **No tasks yet**, plus *"Waiting for the first fetch."* |

That last one has its own code (`NO_DATA`, which the fetcher never emits. It's the page's own state) precisely because the other two promise stale
tasks *below* the notice, and on a first launch there aren't any. Any new
notice code needs the same check: does it actually leave tasks on screen?

Notices render above the tasks, because the tasks under them are the
previous fetch's, kept on purpose.

---

## Who can reach this server

`serve.py` binds `127.0.0.1`, and that's what keeps it off the network: the
kernel refuses a connection to a loopback socket from any other host, with
or without a firewall rule. That part was never the hole.

What loopback can't stop is the browser already running on this machine,
and two attacks follow from it. Both arrive from a page someone merely
visited, with no code running locally:

- **DNS rebinding.** `attacker.com` is published with a very short TTL,
  then re-resolved to `127.0.0.1`. The attacker's own JavaScript fetches
  `http://attacker.com:5100/tasks.json`, which the browser now considers
  same-origin, so it can read the reply. Every task title and note you
  have. Loopback is no defence because the connection genuinely is local.
  The giveaway is the `Host` header, which still says `attacker.com`.
- **CSRF.** A cross-origin page POSTs to `/refresh`, `/restart` or `/quit`.
  It can't read the response, but it doesn't need to in order to force a
  fetch or kill the widget.

Hence two rules: the `Host` must name this machine, and anything the
browser itself labels cross-site is refused. One exemption. A cross-site
GET *navigation*, because that becomes a page at our own origin rather than
data handed to someone else's script.

Verified behaviour: the page's own requests pass, `localhost` passes,
plain non-browser clients pass, a rebinding `Host` is refused, cross-site
GET and POST are refused, and a mismatched port is refused.

### What this deliberately does not defend against

Another process running on this machine. A request with neither an `Origin`
nor a `Sec-Fetch-Site` header is allowed through, because that's an
ordinary non-browser client. This app's own `urllib` calls among them, and a hostile local process is not a threat this layer can do anything
about. It could read `config.json` off the disk instead, so a check at the
HTTP layer would be theatre. The attacks above are different in kind: they
need nothing more than a tab being open.

### `net_guard` must not touch the OAuth callback

`google_tasks_setup.Callback` runs its **own** server, and that is the whole
reason it's separate from `serve.py`'s.

The guard refuses anything the browser labels cross-site, and the consent
redirect is cross-site **by construction**: a top-level navigation
arriving from `accounts.google.com`. Applying the guard there would reject
the one request the listener exists to receive.

What stands in for it: the `state` parameter, which an attacker can't
guess, plus a socket bound to loopback and alive only for the few seconds
between opening the browser and the redirect landing.

### Why `127.0.0.1` and not `localhost`

On Windows that name resolves to `::1` before `127.0.0.1`, and since this
server is IPv4-only, every client using the name pays a dead IPv6
connection attempt first. Measured in DesktopCards at 2.08s against 0.02s
for the literal. So the app always *dials* the literal. `net_guard`
*accepts* either spelling, plus any loopback IP in either family, because
whatever spelling the browser happens to use has to pass.

### The file allowlist

`serve.py` serves `dashboard*.html`, `dashboard.js` and `tasks.json`, and
synthesises `/settings.json`. Everything else 404s. An allowlist rather
than a denylist, so a new file in those folders is unreachable until
someone deliberately adds it.

`translate_path` resolves against `ASSET_DIR` first. Letting the base
class do the traversal sanitising, collapsing `..` and dropping drive
letters, and only then re-roots the handful of URLs that belong to the
data side. Re-rooting a path already reduced to a safe relative one can't
reintroduce traversal. Frozen, this also means `config.json` isn't in any
directory a URL can address at all.

---

## Building the executable

```
pip install pyinstaller
python source/build.py
```

Produces `dist/DesktopTasks.exe`, about 31 MB, carrying Python and every
dependency, so it runs on a machine with no Python installed, plus
`dist/DesktopTasks-Setup.exe` beside it. Unsigned, so the first run trips
SmartScreen (**More info**, then **Run anyway**).

`build.py` runs a preflight, regenerates the icon, calls PyInstaller
against `DesktopTasks.spec` from the repo root so `dist/` and `build/`
land there rather than inside `source/`, then writes the setup-named copy.

> **Status.** `DesktopTasks.exe --fetch` has been run frozen: the bundle
> unpacks, `paths.FROZEN` resolves, and it reaches the fetch and reports
> no connected account from the `%LOCALAPPDATA%` data dir. Still
> unverified: the widget window itself under onefile, which is to say
> whether pywebview loads its WebView2 backend, and the setup and
> uninstall dialogs end to end.

### The preflight: the one way this build can ship broken

`preflight()` refuses to build when `oauth_client.py` is **missing**, or
when it's present with `CLIENT_ID = None`, which is exactly what copying
`oauth_client.example.py` leaves behind.

This exists because that is the project's only *quiet* failure. Everything
else fails loudly. Here, PyInstaller exits 0, the exe launches, the widget
appears, and then every single user who clicks Reconnect Google is told no
client is configured. PyInstaller cannot detect it, because the import is
conditional by design and the module is genuinely optional at runtime.

It also checks that PyInstaller is installed and that nothing is holding
the output exe open. Renaming is the test, since Windows refuses it for a
file that's executing and it's harmless when nothing holds it. Otherwise
the build dies as a bare `PermissionError` from deep inside someone else's
code.

### Three names, one binary

`build.py` writes `dist/DesktopTasks.exe` and then copies it to
`dist/DesktopTasks-Setup.exe`. Setup installs a third copy as
`Uninstall.exe`. All three are the same bytes, and the **filename** is
what picks the mode:

| Name | Mode | Also reachable as |
|---|---|---|
| `DesktopTasks.exe` | The widget | |
| `DesktopTasks-Setup.exe` | Setup | `DesktopTasks.exe --setup` |
| `Uninstall.exe` | Uninstall | `DesktopTasks.exe --uninstall` |

`desktoptasks.looks_like_setup_build()` is the test. `"uninstall"`
contains `"install"`, so the uninstall names are checked **first**, which
is why that check is a function rather than one `in` test.

A copy rather than a second build: there is nothing extra to compile and
nothing that can fall out of step between the app and the thing that
installs it. It is also why setup never writes a new `.exe` of its own.
A program that generates an executable is doing what droppers do, and
antivirus treats it accordingly.

### What to ship

**`DesktopTasks-Setup.exe`, and nothing else.** It is the whole app:
running it writes the other two names itself. `dist/DesktopTasks.exe` is
an output of an install, not a download, and publishing it as well would
only be a second copy of the same bytes that lands people in the widget
without installing it. One file also means one SmartScreen warning and no
zip for anyone to half-extract.

Someone who wants to run it without installing can rename it to anything
without `setup`, `install` or `uninstall` in the name. Nothing in the UI
says so, so it belongs in the release notes rather than being discovered.

**The release must keep "Setup" in the filename.** A release asset renamed
to `DesktopTasks-0.1.exe` no longer matches `SETUP_NAMES`, so
double-clicking it runs the widget uninstalled instead of installing
anything. `DesktopTasks-Setup-0.1.exe` is fine. This is the one real cost
of letting the filename select the mode, and the alternative, a download
that installs only when passed `--setup`, makes a double-click do nothing
useful, which is worse for the person who just downloaded it.

### What setup does

`setup_app.py`, in order:

1. Asks a running widget to quit, because Windows holds a running exe
   open and the binary cannot be replaced underneath it.
2. Copies itself to `%LOCALAPPDATA%\DesktopTasks\DesktopTasks.exe`.
3. Seeds `config.json` and `appearance.json` from the bundled examples,
   but only the ones that are **missing**. Reinstalling must not reset
   the look or overwrite the file holding the refresh token.
4. Writes the shortcuts through `shortcuts.apply`. The Start-menu entry
   is not a choice; Startup is the dialog's one tick box; the desktop one
   is left alone here and lives on the settings page.
5. Copies `Uninstall.exe` beside the app and registers it in HKCU, so the
   app appears in **Settings > Apps** with a working Uninstall button.
6. Launches the widget.

It is one native dialog, not a wizard. DesktopCards needs five steps
because nothing of its widget works until Plaid credentials are in and a
bank is linked. The only thing to set up here is a Google sign-in, and the
tray and the settings page already own that. So setup imports no
pywebview, no Flask and no PIL, and the widget takes it from there.

Nothing needs administrator: the app and its data are under
`%LOCALAPPDATA%`, the shortcuts under `%APPDATA%`, the Add/Remove entry in
`HKCU`.

### A checkout and an installed copy on one machine

Installing from a checkout you also run leaves two separate copies of the
app, and they share nothing:

| | Checkout | Installed |
|---|---|---|
| Data | `config/` | `%LOCALAPPDATA%\DesktopTasks\` |
| Sign-in, list selection, appearance | its own | its own |
| Log | `config/desktoptasks.log` | `%LOCALAPPDATA%\DesktopTasks\desktoptasks.log` |

So the installed copy asks you to connect Google even though the checkout
is already signed in. That is `DATA_DIR` doing its job rather than a bug:
see [Where your files live](#where-your-files-live).

**Only one of them runs at a time.** `claim_single_instance` takes
`Local\DesktopTasks_instance`, which is scoped to the login session and
not to the binary, so whichever starts second logs `Already running` and
exits. It is not a port clash, and it is why installing asks the running
widget to quit first.

**The shortcuts belong to whichever copy wrote them.** `launch_exe`
resolves the target from the process that is serving the settings page: an
installed build writes the installed exe, a checkout writes `pythonw.exe
desktoptasks.py`. Both are correct, and neither can know about the other,
so the Windows shortcuts card prints the target it would write.

The two logs are the easiest thing to mix up, since they have the same
name and the same format. The fetch line prints `TASKS_PATH` in full for
that reason: a message reading `config/tasks.json` in the installed log
would describe a file that is not the one it wrote.

### What uninstall removes

`uninstall.py` reverses exactly that list, in the order the pieces depend
on each other: ask the widget to quit (`taskkill` only as a backstop, and
never against itself), remove all three shortcuts, delete the HKCU entry,
then the data.

One tick box, ticked by default, keeps `config.json`, `appearance.json`
and a user-supplied `logo.png`. The last fetch and the log go either way,
because they are rebuilt within a minute of the next launch and a stale
task list is the one thing nobody wants kept.

The exes go last and from outside the process, through
`platform_win.delete_after_exit`: Windows will not delete a running
image, and when run as the installed `Uninstall.exe` this process **is**
one of them. `DATA_DIR` goes the same way but through a plain `rmdir`,
which refuses a folder that still holds the kept settings. That is the
right answer rather than a problem to work around.

Your tasks are never touched. They live in your Google account, the app
only ever read them, and the refresh token is a local file, so removing it
signs this computer out and nothing more.

### The version resource

`source/version_info.txt` is compiled into the exe by the spec's
`version=`. Without it the binary has an icon but no name, and Windows
reads `FileDescription` wherever it has to name a program it did not
launch itself: Task Manager's **Startup** tab, **Settings > Apps >
Startup**, the file's Details tab.

The icon in those lists comes from the exe too. That is why a Startup
entry for a **source** checkout stays generic: its shortcut points at
`pythonw.exe`, and Windows describes the target, not the `.lnk`. Only an
installed build can look right there.

### One entry point

Frozen, `sys.executable` **is** the app: it takes no script argument and
there are no `.py` files on disk to point at. Anything that spawns Python
by name breaks. A single entry point with subcommands means
`sys.executable` plus a flag covers every case, from source and frozen
alike, which is what `widget.spawn_self` relies on for the tray's
Restart.

### No console, so output goes to a file

A windowed build has no console, and PyInstaller sets `sys.stdout` and
`sys.stderr` to `None` rather than to something inert, so every `print()`
in the codebase would raise `AttributeError` on `None.write`. That would
turn harmless progress messages into crashes, in the build where they're
hardest to see. It applies to a source run under `pythonw` too, which is
how the tray's Restart relaunches.

`desktoptasks.redirect_output_to_log()` points them at
`desktoptasks.log` instead, which doubles as the diagnostic channel the
worst failure mode needs: pywebview coming up as a blank window with no
traceback anywhere, and the tray. The only control surface, not
appearing either. Truncated rather than rotated past 512 KB; this is a
debug aid and the last run is the one anyone wants.

If nowhere is writable it falls back to `os.devnull`, so the app still runs
rather than dying for the sake of logging.

### The icon, and everything else derived from the logo

`logo.png` at the repo root is the single source of truth for the mark. The
exe's embedded icon, the tray icon and any shortcut icon all derive from
it, so replacing that one file changes all of them.

`make_icon.py` converts it to `DesktopTasks.ico` at **seven sizes**
(16/24/32/48/64/128/256). All of them go in rather than one scaled at
display time. The shell picks whichever fits the context it's drawing in,
and a single 256px image looks muddy at 16px in a taskbar. PyInstaller's
`--icon` needs a real `.ico` and won't take a PNG, so the conversion has to
happen somewhere.

The conversion itself lives in `logo_cache.write_ico`, which the running
app also uses, so there's **one definition** of what a DesktopTasks icon
looks like rather than two that can drift.

A build step rather than a committed `.ico`, so there's no binary to fall
out of date, which is why `*.ico` is gitignored.

> An earlier version of `make_icon.py` *drew* the icon with Pillow, because
> the project had no mark yet. That's gone now there's a real logo. The
> tray keeps a drawn fallback, for the different case of a logo that can't
> be read at runtime.

### The logo cache

`logo_cache.py` keeps the derived copies in the cache folder: a 64px tray
PNG and a multi-size `.ico` for shortcuts. Both conversions are cheap but
not free, and neither changes between runs.

Staleness is decided by a **content hash, not a modification time**, and
that is the whole subtlety. Under a onefile build the bundled `logo.png` is
extracted to a fresh temp directory on *every launch*, so its mtime is
always newer than anything cached. An mtime comparison would rebuild both
derivatives every single run, which is exactly what the cache exists to
avoid. Hashing the bytes gives a stable answer when frozen and still
notices a genuinely different logo.

`widget.main()` calls `logo_cache.icon_file()` at startup to keep that
cached `.ico` in step. Nothing else rebuilds it, so without that a deleted
cache would leave any shortcut pointing at a missing file and showing a
generic icon, and it means replacing `logo.png` updates those shortcuts on
the next launch, which is as close to live as a shell icon gets.

`paths.logo_path()` prefers a `logo.png` dropped in the **data folder**
over the bundled one. From source they're the same file, so editing the
repo's logo just works. Frozen, the bundled copy is sealed inside the exe,
and this is what makes the mark changeable without a rebuild: drop a
`logo.png` next to `config.json`. It's resolved per call rather than at
import, so a replacement takes effect without restarting anything that
re-reads it.

### Hidden imports

`desktoptasks.py` imports each mode's dependencies inside its own branch,
which is good for startup cost but invisible to PyInstaller's static
analysis. A function-local `import widget` is not one it can follow from
the entry point. The spec names them all, or the non-default subcommands
would be left out of the bundle entirely.

`webview.platforms.winforms` and `clr` are there because pywebview resolves
its backend **by name at runtime**, so neither is reachable statically.
This is the part most likely to need adjusting, and it fails as a blank
window rather than an `ImportError`, which is why
`widget.explain_webview_failure` exists, to say something actionable about
the two causes (an interrupted onefile unpack, which relaunching fixes, and
a genuinely absent WebView2 runtime, which needs a download).

`tkinter` is excluded: it comes with the stdlib, nothing here uses it, and
excluding it saves several MB of Tcl/Tk that would otherwise be unpacked on
every launch.

### Validating the spec without a full build

Exec the spec with `Analysis`, `PYZ` and `EXE` stubbed out. That checks the
entry script and all three `datas` resolve on disk, that every
`hiddenimports` entry actually imports, and that `console=False` and the
icon path hold. Seconds instead of minutes, and it catches path mistakes.
It can't catch a backend that fails at runtime, so it complements a real
build rather than replacing one.

### Frozen-build hazards inherited from DesktopCards

Two things `widget.py` carries that only matter once frozen:

- **`clean_child_env()`**. PyInstaller's onefile bootloader tells child
  processes where it unpacked itself, through `_PYI*` / `_MEIPASS*`
  environment variables. That's right for a child that's part of the same
  run and badly wrong for a replacement meant to outlive us: the child
  skips extraction, uses our temp directory, and then we exit and the
  bootloader deletes it. The new process runs against a directory being
  erased, and the first thing to go missing is the WebView2 interop layer, so it dies with "Cannot find Microsoft.Web.WebView2.Core.dll", a message
  that points nowhere near the actual cause.
- **`force_exit_soon()`**. `window.destroy()` is supposed to end
  `webview.start()` and let `main()` return, and from source it does.
  Frozen it reliably leaves the process alive with its window handle still
  registered. Pywebview's WinForms/pythonnet loop doesn't fully unwind, and every such leftover pins a ~33 MB unpack directory its bootloader
  can't clean up. Three restarts, three orphans. So the clean path gets a
  2.5s head start and this is the backstop. `os._exit`, not `sys.exit`,
  because the point is to skip an interpreter shutdown that is
  demonstrably capable of hanging.

`spawn_self` also starts the replacement from the **exe's own folder**, not
`ASSET_DIR`. Frozen, `ASSET_DIR` is this process's `_MEIPASS` temp
directory, and a process's current directory is locked against deletion
for as long as it lives, so starting the replacement there means our own
bootloader can never remove its temp folder.

### Restart, Quit, and the port

`Server.allow_reuse_address` is **False**, against `HTTPServer`'s default of
True, which on Windows lets a second process silently bind the same port on
top of a still-running one. Requests then get split nondeterministically
between zombie instances.

The cost is that a previous instance's sockets sitting in `TIME_WAIT` make
the bind fail outright, and the tray's Restart lands inside that window
routinely: the old process exits and the replacement tries to bind
milliseconds later. `build_server` retries for about six seconds, because
`TIME_WAIT` is a timer rather than a contended lock. Waiting it out *is*
the fix, and retrying faster wouldn't help. It raises if the port never
frees, which is a genuinely different situation (something else owns it)
and should be reported rather than retried forever.

Restart releases the single-instance lock **before** spawning the
replacement, because the replacement checks that lock on startup and this
process is still alive at that moment. Without it, Restart would quietly
kill the widget instead of restarting it.

`POST /restart` and `POST /quit` both answer **before** acting: the server
is a thread inside the process being torn down, so a reply written
afterwards would never leave. Both 404 when there's no widget in the
process, so a bare `--serve` run reports honestly rather than pretending.

### Only one widget at a time

`claim_single_instance` takes a named mutex (`Local\DesktopTasks_instance`)
rather than a lock file or a port check. The kernel releases it when the
process dies, however it dies, so a crash or a kill can't leave a stale
lock that blocks every future launch. The `Local\` prefix scopes it to the
login session, which is the right boundary. Two users on one machine each
get their own widget.

This matters because the app gets launched from several places: a
Start-menu shortcut, a Startup shortcut, a double-click. A second instance
is an ordinary event rather than a mistake, and it should step aside
quietly rather than race for the port and die with a traceback in a popup.

---

## Why a few of the design choices are what they are

- **WebView2 instead of a Chrome window.** Chrome's `--app` windows always
  paint a small title bar themselves, independent of the OS window style,
  and there's no supported way to remove it. Windows' built-in WebView2
  engine (driven here via pywebview) supports genuinely frameless windows
  natively, and is lighter than spinning up a full Chrome profile to show
  one page.
- **Rounded corners via a window region, not just CSS.** pywebview's
  `transparent` option only makes WebView2's own background transparent
  against the window's paint; it doesn't change the window's actual shape.
  Real rounded corners. Desktop visible through them. Need the OS-level
  `SetWindowRgn` clip. The region is built from the window's *actual client
  rect in device pixels*, not from the CSS numbers, because at any display
  scaling above 100% the real window is physically larger and a region
  built from CSS pixels clips a real slice off the right and bottom edges.
- **Stdlib over `google-api-python-client`.** The entire API surface here
  is a token refresh and two GETs, none of it signed. The official client
  would add a large dependency tree to the bundle for no behaviour this
  needs. `requirements.txt` carries only the widget's three packages; the
  fetch and auth path is dependency-free.
- **Tray icon instead of an in-page button.** See
  [Pinned and read-only](#pinned-and-read-only). The WorkerW layer takes
  no mouse input, so there is nowhere else for a control to go.
- **The tray icon is the logo, with a drawn dot as fallback.** The drawn
  circle came first and had one real advantage: generated from your
  Windows accent colour, it always matched your desktop. The logo doesn't
  track the accent, which is the price of having the tray icon, the exe
  icon and any shortcut be recognisably the same mark. The fallback is not
  dead code. `ASSET_DIR` points inside the unpacked bundle when frozen, so
  a spec that forgot to include `logo.png` would otherwise leave the app
  with **no tray icon at all**, and the tray is this widget's only control
  surface. An icon that can't be produced must never mean a tray that
  can't be produced.
- **Accent colour from the registry, not hardcoded**, for that fallback
  dot. The read can fail on some installs, and a tray icon isn't worth
  failing a launch over, so that falls back too.
- **`tasks.json` separate from any future `data.json`.** Independent
  fetchers each rewriting a file wholesale would race, and one service
  being down has no business blanking another's card.
- **The page's background matches the window's.** `widget.py` sets the
  native window's `background_color` to the same value as the stylesheet's
  `--surface-0` in each theme. pywebview's default is white, which flashes
  as a bright frame on every launch and Restart under a dark page, and the
  value also shows in the sliver between `body`'s rounded box and the
  window's clipped corners. **Keep the two in step.**

### Style

Module docstrings explain *why*; comments go on the non-obvious decision
rather than the obvious line. Use `--`, not em-dashes.

---

## Making the app public

Everything below is required to get out of **Testing** status and let people
who are not on the test-user list sign in. Verified against Google's
developer documentation in October 2026; the rules do change, so check the
links before relying on this.

### Step 0. "Missing domain: github.com"

If the console shows **Missing domain: github.com** under Authorised
domains, that is **not** a verification failure. It means a URL you entered
on the branding page. The home page, privacy policy or terms. Points at
`github.com`, and every domain used anywhere in the project has to be
pre-registered in the Authorised domains list first.

**The fix:** add `github.com` to Authorised domains. Enter the bare
top-level domain only. No `https://`, no `www.`, no path:

```
github.com
```

Once a domain is registered you may use any of its subdomains and any page
under it, so one entry covers every `github.com/...` URL. Google's own
guidance is to **add the authorised domain before** you add the home page,
privacy policy, terms or redirect URIs. Doing it the other way round is
exactly what produces this error. There is a limit of **ten** authorised
domains per project.

That clears the error and is fine while the app is in **Testing**.
Search Console verification of those domains is only required "if your app
needs to go through verification".

**It will not survive verification, though**, which is the next section.

### Step 1. A domain you own

**Short answer: yes, verification needs a domain you own. `github.com` can
never work for it.**

Not because Google dislikes GitHub, but because of *how* domains are
verified. Search Console requires a **Domain property**, verified at the
**DNS level** by adding a TXT record to the domain's DNS configuration, and
the verifying Google account must be an **owner of the Cloud project**. You
cannot add a DNS record to `github.com`. GitHub controls it. The same
applies to `github.io`, `vercel.app`, `netlify.app` and every other shared
provider domain: Google's advice for these is to map the service to a
subdomain of a domain you already own.

So for verification, this is the real blocker, and it gates everything
else. Google requires the app's **home page**, **privacy policy** and
**terms of service** to be live web pages, and the privacy policy must be
**hosted on the same domain as the home page**. The Markdown drafts in this
folder cannot be the URLs you submit. They have to be published.

- The home page must be **publicly accessible** (not behind a login),
  clearly **relevant to the app under review**, and **not** a Play Store
  listing or a social-media profile. A GitHub repository page is a weak
  home page for the same reason: it is someone else's domain and reads as
  a code listing rather than as the app's own site.
- You must **verify ownership of every authorised domain in Google Search
  Console**, as a Domain property, from an account that owns the Cloud
  project.

**The cheap path**, since hosting is not the expensive part:

1. Buy a domain (roughly £10–£15 / \$10–\$15 a year).
2. Host the three pages free on **GitHub Pages**, pointed at that domain as
   a custom domain. You keep using GitHub; the URLs just carry your name.
3. In Search Console, add it as a **Domain property** and verify with the
   DNS TXT record.
4. Put the domain in Authorised domains, and point the home page, privacy
   policy and terms URIs at it.

Suggested layout once you have `example.com`:

| Page | Content |
|---|---|
| `https://example.com/` | What DesktopTasks is, a screenshot, a download link. This is the "home page". |
| `https://example.com/privacy` | `Docs/PRIVACY.md`, published as HTML |
| `https://example.com/terms` | `Docs/TERMS.md`, published as HTML |

Link the privacy policy and terms from the home page's footer. Google
wants the policy "visible to users", not merely reachable by direct URL.

### Do you actually need this?

Only if you want the app **verified**. The three end states again, with
what each one costs:

| Goal | Domain needed? | What to do |
|---|---|---|
| Just you | **No** | Stay in Testing. Register `github.com` as above to clear the error. Accept the weekly reconnect. |
| You and people you know | **Probably** | The console wants home page / privacy / terms URLs before it will let you publish to production. Those URLs need an authorised domain, but **not a verified one**, since you are not submitting for review. Try `github.com` first. It may well be accepted. |
| A public release | **Yes** | Everything in Step 1. There is no way around DNS-level domain verification. |

The middle row is the one worth testing before spending money: publishing
to production **without** submitting for verification already fixes both
problems that bite today. The 7-day token expiry and the test-user
restriction, and it is not certain that the console demands a *verified*
domain to do it. Try it with `github.com` registered; if the console lets
you publish, you have what you need for nothing.



This is the real blocker, and it gates almost everything else. Google
requires the app's **home page**, **privacy policy** and **terms of
service** to be live web pages, and the privacy policy must be
**hosted on the same domain as the home page**. The Markdown drafts in this
folder cannot be the URLs you submit. They have to be published.

- The home page must be **publicly accessible** (not behind a login),
  clearly **relevant to the app under review**, and **not** a Play Store
  listing or a social-media profile.
- You must **verify ownership of every authorized domain in Google Search
  Console**, using an account that is an owner or editor of the Cloud
  project.
- A `github.io` subdomain is reported to be accepted inconsistently and is
  definitively rejected during formal brand verification, so a domain you
  own is the reliable path. GitHub Pages behind your own custom domain is
  fine.

Suggested layout once you have `example.com`:

| Page | Content |
|---|---|
| `https://example.com/` | What DesktopTasks is, a screenshot, a download link. This is the "home page". |
| `https://example.com/privacy` | `Docs/PRIVACY.md`, published as HTML |
| `https://example.com/terms` | `Docs/TERMS.md`, published as HTML |

Link the privacy policy and terms from the home page's footer. Google wants
the policy "visible to users", not merely reachable by direct URL.

### The site, in `site/`

`site/` holds a small static site. `index.html`, `privacy.html`,
`terms.html`, one stylesheet and the logo. Published to GitHub Pages by
`.github/workflows/pages.yml`. It lands at
`https://aaryanpanigrahi.github.io/DesktopTasks/`.

It is its own folder rather than the repo root or `/docs`: the root would
put `index.html` beside the source tree, and `/docs` would collide with
this repo's existing `Docs/`. GitHub paths are case-sensitive, so `Docs/`
and `docs/` are different things, and relying on that distinction is a trap
for whoever looks next.

**What it is worth, and what it is not.** It gives the project a real home
page, privacy policy and terms at URLs that are not a code listing, which
is what the console asks for, and what publishing to production needs. It
does **not** make verification possible, because `github.io` cannot be
DNS-verified (see Step 1).

**Moving it to a domain you own later** is a CNAME file in `site/`, a DNS
record, and the custom-domain box in the repo's Pages settings. Nothing
else changes, and that is the step that unlocks verification.

**Deleting it** is two paths and nothing else:

```
git rm -r site .github/workflows/pages.yml
```

No code imports from it, nothing in `source/` references it, and the build
does not touch it.

### Step 2. Fill in the drafts

`Docs/PRIVACY.md` and `Docs/TERMS.md` are complete drafts that describe this
app's actual behaviour. Both need every `[BRACKETED]` value filled in:

- `[DATE]`. Effective and last-updated dates
- `[YOUR NAME OR ENTITY]`. Who publishes the app
- `[CONTACT EMAIL]`. A contact address. Consider a dedicated alias rather
  than your personal Gmail, since this is published publicly.
- `[YOUR-DOMAIN]`. Your domain, in the cross-links
- `[JURISDICTION]`, `[CURRENCY] [AMOUNT]`, `[LICENSE]`. In the terms

The privacy policy already contains the **Google API Services Limited Use
disclosure**, which is required when a sensitive scope is involved, and it
already discloses how the app accesses, uses, stores and shares Google user
data. The four things Google checks it for.

The app's strongest argument at review is that it is **fully local**: no
server, no telemetry, no onward disclosure. Keep that prominent.

### Step 3. The OAuth consent screen

In the Cloud console, make the branding match the pages above exactly:

- App name identical to the name used on the home page and in the app
- Support email
- App home page URI, privacy policy URI, terms of service URI
- An app logo, if you add one
- Authorized domains matching what you verified in Search Console

Google checks that the consent screen "accurately represents the app's
identity", so a mismatch between the app name here and the name on your
home page is a common rejection.

### Step 4. A demo video

**Required** for sensitive-scope verification, and easy to get wrong:

- Uploaded to YouTube as **Unlisted**
- **In English**
- Shows the **OAuth consent flow** as a user actually experiences it
- Shows the **app name and the OAuth client ID** on screen, legibly
- Demonstrates **how the sensitive scope is actually used**: i.e. the
  widget displaying real tasks after consent

For this app a short screen recording covers it: the tray's Reconnect
Google, the consent screen with the app name visible, then tasks appearing
in the widget. Show the client ID from the consent screen URL or the Cloud
console.

### Step 5. Submit, and expect it to take a while

Publish the app to production in the console, then submit for verification.
Google's published timings:

| Stage | Typical |
|---|---|
| Brand verification | 2–3 business days |
| Sensitive scope verification | 3–5 business days, and up to 10 |

**A security assessment is not required here.** That applies to *restricted*
scopes (Gmail, Drive and similar). `tasks.readonly` is **sensitive**, not
restricted, so there is no third-party assessment and no associated cost, which is the single biggest thing working in your favour.

### What you get at each stage

| State | Who can sign in | Token lifetime | Warning screen |
|---|---|---|---|
| **Testing** (now) | Only listed test users, max 100 | **7 days** | Yes |
| **Production, unverified** | Anyone, up to a ~100-user cap | Normal | Yes. One click behind **Advanced** |
| **Production, verified** | Anyone | Normal | **No** |

Note the middle row: **publishing alone, without verification, already
fixes both of the problems that bite today**: the weekly reconnect and the
test-user restriction. Verification only removes the warning screen and the
user cap.

Staying unverified is a legitimate end state, not a half-finished one.
Google's own documentation says apps "used only by the developer and
personally known users may skip verification and proceed through the
unverified app screen", which is exactly what DesktopTasks is for now.
See [Do you actually need this?](#do-you-actually-need-this) above.

### Nothing in the code changes

Worth repeating: publishing and verification are entirely console-and-web
work. No code change is required, and `AuthExpired` simply stops firing
once the project leaves Testing.

---

## Known rough edges and what's left

- **The exe has never been run.** See the note under
  [Building the executable](#building-the-executable).
- **No installer.** Nothing copies the exe to `%LOCALAPPDATA%`, makes
  Start-menu or Startup shortcuts, or registers an Add/Remove entry.
  `platform_win.py` already has every piece ported and unused:
  `create_shortcut`, `install_autostart`, `register_uninstaller`,
  `unregister_uninstaller`, `delete_after_exit`, `confirm_with_checkbox`,
  `message_box`. That's the natural next step if a release is published.
- **Testing status.** The weekly reconnect, and the fact that nobody
  outside the test-user list can sign in. See
  [Testing status](#testing-status-and-the-two-things-it-costs).
- **A switch discards unsaved ticks.** Picking a different account in the
  dropdown redraws the task-list checkboxes from that account, so anything
  ticked and not saved on the previous one is gone, with no prompt.
- **The height ceiling.** With `max_tasks` at `0`, a long list runs off
  the bottom of the screen and the tasks past the edge are invisible. The
  OS will not grow the window further and there is no scrollbar. See
  [The height ceiling](#the-height-ceiling). A better answer would measure
  the screen and cap itself, instead of asking the user to pick a number.
- **Translucency is only lightly tested.** The token layer and the
  transparent window are both in, but it has been exercised far less than
  the opaque path, and `erase_vacated_area` below becomes live under it.
- **`erase_vacated_area` is unverified.** Ported from DesktopCards, where
  it guards against stale pixels left behind when a transparent window
  shrinks. With `translucent_background` off the window is opaque and its
  own background brush erases what it was painting over, so the function
  is unreachable in practice. Turning translucency on is what makes it
  matter, and that path has not been tested hard.
- **The remote is still named `DesktopTools`.** The local folder was
  renamed; the remote URL was deliberately left alone so an existing push
  doesn't break. After renaming on GitHub:
  `git remote set-url origin https://github.com/AaryanPanigrahi/DesktopTasks.git`

---

## References

- The window machinery. Frameless WebView2 window, WorkerW pinning,
  taskbar hiding, rounded-corner clipping, the tray icon, the local server,
  the loopback request guard, the frozen/source path split and the
  PyInstaller setup. Is ported from
  [DesktopCards](https://github.com/AaryanPanigrahi/DesktopCards), where
  it was worked out first. `net_guard.py` and `platform_win.py` are
  essentially unchanged; `paths.py` and `serve.py` are adapted; `widget.py`
  and the page are rewritten around a different content model.
- What went wrong the first time that project was packaged is carried over
  into [Frozen-build hazards inherited from
  DesktopCards](#frozen-build-hazards-inherited-from-desktopcards), which
  is the thing to read before touching the build here.
- [`Docs/mac_port.md`](https://github.com/AaryanPanigrahi/DesktopCards/blob/main/Docs/mac_port.md)
  in that repo covers what a macOS port would involve. Three of
  `platform_win.py`'s five concerns are *simpler* there, where windows are
  composited and a window level can be set directly instead of reparenting
  onto a layer you first have to go find.
- Google's own documentation is the source for the installed-app credential
  model. That a desktop client's secret is not treated as confidential,
  and that PKCE is what secures the exchange.
