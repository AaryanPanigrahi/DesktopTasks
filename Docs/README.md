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
- Shows each list as a card, with subtasks nested under their parents in
  Google's own ordering.
- Calls out **overdue** and **today** in colour, and reads dates the way a
  person would: `Today`, `Tomorrow`, `Yesterday`, then `Oct 20`, then
  `Oct 10 · 6 days ago` once something has been overdue a while.
- Shows task notes, clamped to two lines so one pasted essay can't push
  everything else off the widget.
- Sits pinned to a fixed spot as a frameless window with no taskbar icon
  and no Alt+Tab entry, and stays visible through Win+D ("show desktop").
- Sizes itself to its content after every render, so the window grows and
  shrinks with the task count rather than scrolling or clipping the last
  task.
- A system tray icon gives you **Reload** (re-fetch now), **Reconnect
  Google** (sign in again — a weekly errand, see
  [Testing status](#testing-status-and-the-two-things-it-costs)),
  **Restart** (relaunch, for settings only read at startup) and **Quit**.
  The widget itself cannot be clicked at all while pinned (see
  [Pinned and read-only](#pinned-and-read-only)), so this is the whole
  control surface.
- Counts down the minutes until the next scheduled refresh next to the
  time of the last one.

A list with nothing open reads **All clear** rather than rendering an empty
card that looks like a failure.

---

## Getting started

No release has been published yet, so this runs from source.

```
cp config/config.example.json config/config.json   # defaults are fine
python source/google_tasks_setup.py                # sign in to Google
python source/desktoptasks.py                      # run the widget
```

A clone needs a Google OAuth client of its own — the one a release would
bundle is deliberately not in the repo. See
[The OAuth client](#the-oauth-client-shipped-with-the-app-never-committed).

`desktoptasks.py` is the only entry point. Every mode is a flag on it:

| Command | What it does |
|---|---|
| `desktoptasks.py` | The widget |
| `desktoptasks.py --fetch` | One fetch, then exit |
| `desktoptasks.py --connect` | Sign in to Google. Takes an optional `client_secret.json` |
| `desktoptasks.py --serve` | Just the HTTP server, for working on the page in a normal browser tab |
| `desktoptasks.py --help` | The above |

Imports live inside each branch rather than at the top of the file. The
widget pulls in pywebview, pythonnet and the whole .NET interop layer, and
nothing else here needs any of it — from source that would be a slower
start, and frozen it would be wasted unpacking on every launch.

---

## Pieces

Everything in the first group lives in `source/`, the JSON in `config/`,
and the docs in `Docs/`. Only the build output and the generated icon sit
at the repo root. Paths are given bare for readability.

| File | Role |
|---|---|
| `desktoptasks.py` | The entry point. Every mode is a flag on this one file. Also redirects `stdout`/`stderr` to a log when there's no console — see [No console](#no-console-so-output-goes-to-a-file). |
| `google_tasks.py` | The fetcher. Refresh token → access token, list the task lists, list open tasks in each, write `tasks.json`. One pass and exit, no loop. The only module that talks to Google's API. Stdlib only. |
| `google_tasks_setup.py` | The consent flow. Starts a loopback listener, opens Google's own consent page, catches the redirect, saves the refresh token. Run again to reconnect. Stdlib only. |
| `oauth_client.py` | The OAuth client a release signs in with. **Gitignored**, bundled into the exe at build time. See [The OAuth client](#the-oauth-client-shipped-with-the-app-never-committed). |
| `oauth_client.example.py` | The tracked template of the above, with `None` values and instructions for making your own client. |
| `widget.py` | Launches the pinned window: hosts the server, opens a frameless WebView2 window at the configured position, hides it from the taskbar, pins it behind the desktop icons so it survives Win+D, clips it to rounded corners, runs the interval fetch, runs the tray icon, and owns the Reconnect flow. |
| `serve.py` | Minimal local web server so the page can read its JSON. Serves only an explicit allowlist — `config.json`, which holds the refresh token, is never reachable over HTTP. Loopback-bound and behind `net_guard`. Also synthesises `/settings.json` per request. Normally a thread inside `widget.py`; still runnable alone for debugging, where `POST /restart` and `/quit` correctly report there's no widget here to act on. |
| `dashboard.html` / `dashboard.js` | The widget's UI and all its behaviour — rendering, nesting, date handling, auto-refresh, auto-resize. |
| `paths.py` | Where every file lives. Splits read-only bundled assets from writable per-user data, which a packaged build requires and a source checkout collapses back into one folder. |
| `platform_win.py` | Every Windows-specific call in one file — rounded-corner clipping, taskbar hiding, desktop pinning, the accent-colour registry read, the single-instance mutex, shortcuts, and the dialog / Add-Remove-entry / deferred-self-delete pieces an installer would need. Isolated so another platform means writing a sibling, not unpicking this one. |
| `net_guard.py` | The one definition of "did this request really come from this machine?". Loopback binding keeps the server off the network; this is what keeps the local browser from being used as a way in. See [Who can reach this server](#who-can-reach-this-server). |
| `logo_cache.py` | Caches the derived copies of `logo.png` — the tray PNG and a shortcut `.ico` — in the cache folder, rebuilt only when the logo's *contents* change. |
| `build.py` / `DesktopTasks.spec` / `make_icon.py` | Produce `dist/DesktopTasks.exe` — see [Building the executable](#building-the-executable). |
| `logo.png` | The single source of truth for the app's mark: the exe icon and the tray icon both derive from it. At the repo root rather than in `source/`, because it's the project's own identity rather than part of the dashboard. |
| `config.json` | Your refresh token and all your settings. **Gitignored** — never committed. |
| `config.example.json` | A credential-free template of the above, for sharing this tool with someone else: they copy it and fill in their own values rather than yours. |
| `tasks.json` | The fetcher's output, rewritten every run. Gitignored — not data you'd miss. |
| `desktoptasks.log` | Written whenever there's no console to print to. Gitignored. |

Deliberately absent, where DesktopCards has one:

| Not here | Why |
|---|---|
| `appearance.json` | Not adopted. The handful of look-and-feel values live in `config.json`'s `window` block instead, and reach the page through `/settings.json`. |
| `setup_app.py` | DesktopCards' 155 KB Flask settings page. The one thing here that needs doing on a schedule is reconnecting, and that's a tray item. |
| `uninstall.py`, an installer | Not built yet. `platform_win.py` already has every OS piece it would need. |
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
| `config.json`, `tasks.json`, the log | `config/` | `%LOCALAPPDATA%\DesktopTasks\` |
| `config.example.json` | `config/` | bundled in the exe |
| Build output | `dist/`, `build/` | n/a |

`paths.py` is the only module that knows the difference. Nothing else
derives a path from `__file__` — under PyInstaller that resolves inside
`sys._MEIPASS`, a temp directory deleted on exit, which would make every
launch look like a fresh install.

The four constants that matter:

- **`ASSET_DIR`** — read-only, ships with the app: `dashboard.html`,
  `dashboard.js`. `source/` from source, `sys._MEIPASS` frozen. Nothing
  writable can live here; under a onefile build it's deleted when the
  process exits.
- **`DATA_DIR`** — writable, per-user, survives upgrades and the exe being
  moved.
- **`EXAMPLES_DIR`** — where `config.example.json` is read from. The
  bundle when frozen, because a frozen first run has no repo folder to copy
  it out of.
- **`REPO_ROOT`** — the checkout. Only meaningful from source, and only for
  things that genuinely live at the top: the generated icon and `dist/`.

`CONFIG_DIR` is an alias for `DATA_DIR`, kept because
`google_tasks_setup.py` imports that name and because "the directory
`config.json` is in" is a thing callers legitimately want to say.

---

## Configuration (`config.json`)

One file, holding credentials and settings together. Every key has a sane
default, so a missing file still runs.

| Key | Default | Meaning |
|---|---|---|
| `refresh_token` | `null` | Written for you when you sign in. The only lasting credential. Keep it to yourself — it grants read access to your tasks. |
| `tasklist_ids` | `[]` | Empty means every list. Narrowing it is how you keep one shopping list off a desktop that's mostly for work. Left alone on a reconnect, so a narrowed selection survives the weekly re-auth. |
| `port` | `5100` | Local port `serve.py` binds. |
| `fetch_interval_minutes` | `15` | How often to re-fetch. Read at launch by the widget's own timer, so a change applies on the next **Restart** — there's no schedule registered with Windows to re-apply. |
| `show_completed` | `false` | Include completed tasks. Applied server-side by the API, not filtered here, which keeps a list with years of history from costing several pages to read. |
| `show_notes` | `true` | Show notes under the title. |
| `group_by_list` | `true` | One card per list, or everything merged into one. |
| `client_id`, `client_secret` | `null` | Override the bundled OAuth client with your own. Explicit values always win. |
| `window.x`, `window.y` | `100` | Where the widget sits. |
| `window.corner_radius` | `16` | Rounded-corner clip radius, in pixels. |
| `window.survive_show_desktop` | `true` | Pin it behind the desktop icons. `false` makes it an ordinary floating window. |
| `window.dark_theme` | `true` | Dark or light palette. |
| `window.accent` | `null` | Accent colour. `null` means read your Windows accent. |

Most changes land on the next **Reload**, because `/settings.json` is
rebuilt per request. The three window ones (`x`, `y`,
`survive_show_desktop`) need a **Restart**, since they're only read at
startup.

### Why one file, split by ownership

An earlier revision split `config/` per service — `google.json` for
credentials plus `settings.json` for the rest — on the reasoning that a
service you never enable should leave no placeholder keys lying around.
That was reversed once the app started shipping its own OAuth client,
because the meaningful line stopped being *which service* a value belongs
to and became *who owns it*:

- The **client credentials belong to the app**, so they live in source
  (`oauth_client.py`) and ride along inside the frozen binary. No copy
  step, and no way for a user to delete them by editing JSON.
- The **refresh token and the settings belong to the user**, so they live
  in one gitignored `config.json`, matching DesktopCards.

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
   not a crash — `google_tasks_setup.py` prints instructions instead.
2. **`build.py` refuses to build without it.** Put the two facts above
   together and a release built on a machine lacking the file *succeeds*
   and produces an exe that launches, looks correct, and tells every user
   "no client configured". PyInstaller can't detect that — the import is
   conditional by design. See
   [the preflight](#the-preflight-the-one-way-this-build-can-ship-broken).
3. **It's named in the spec's `hiddenimports`** for the same reason: a
   conditional import isn't one PyInstaller reliably follows into a bundle.

### These credentials are not really secret

Google classes this as an **installed app** credential, and says so in its
own documentation: the secret ships inside every copy of the binary and can
be read straight out of it. What actually protects the flow is PKCE — an
authorization code is bound to a `code_verifier` that never leaves the
process — plus the loopback redirect. Possessing the client pair alone
grants nothing.

Bundling rather than committing is therefore about keeping the credential
out of public git history, not about hiding it from a determined user.

### Cloud console configuration

Not reproducible from the code, so it's recorded here.

- **Tasks API** enabled (`tasks.googleapis.com`). Note that searching the
  API library for "tasks" surfaces **Cloud Tasks API** first, which is an
  unrelated job-queue product. Wrong one.
- **OAuth consent screen** configured, user type **External**.
- **Scope** `https://www.googleapis.com/auth/tasks.readonly`. Google labels
  this *sensitive*, which is expected and fine.
- **Publishing status: Testing.** See below.
- **Test users**: the owner's own Gmail.
- **OAuth client type: Desktop app.** Required, not a preference — it's the
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
exists to get.

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
Testing admits only the Gmail addresses on its test-user list — the project
owner included. A stranger who downloads a build gets `access_denied`
before the consent screen means anything. **No code change fixes this**,
and it's the real blocker on handing this to anyone else.

Publishing to production fixes both at once: any Google account may
consent, and refresh tokens stop expiring. What remains after publishing is
the "Google hasn't verified this app" interstitial — one click behind
**Advanced** — and a ~100-user cap. Neither matters for a personal widget.
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
receive normal mouse input** — the same reason Rainmeter and Wallpaper
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
- The dot beside each task is a **ring, not a checkbox** — deliberately,
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
obvious places to look — which looks exactly like "the window never
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
into a widget that might not be running — writing a `tasks.json` nobody was
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
must not kill the thread — someone may connect one while the widget is
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
at the same moment, and both end by rewriting `tasks.json` wholesale — so
overlapping runs could interleave those writes, and the loser's fetch would
be wasted work anyway. Not reentrant: nothing calls `main()` from inside
`main()`.

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
put it — the page can't be clicked and pystray has no notification surface.
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

`None` — wait forever — is correct for the command line. The consent screen
can take a while: picking an account, clicking past the unverified-app
warning, two-factor. Any deadline short enough to be useful would mostly
fire on someone still partway through it, and Ctrl-C is the cancel.

It's wrong inside the widget, which has no Ctrl-C. There, a user who closes
the browser tab without consenting would leave the function spinning on a
daemon thread for the life of the process, holding its ephemeral port and
the single-flight lock — so every later Reconnect would be refused. The
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
`dashboard.js` reads `/settings.json` and corrects it — a flash on every
launch.

### Due dates are strings, deliberately

**The single most breakable thing in this project.**

`google_tasks.py` truncates each due date to a bare `YYYY-MM-DD` on
purpose. The API stores midnight UTC, and parsing that into any zone west
of UTC shifts the date back a day — a task due the 17th renders as the
16th and reads as overdue a day early.

So the rule throughout `dashboard.js` is: **compare due dates as strings,
and when a `Date` is unavoidable, build it from the parts in local time.**
`todayKey()` formats the local date the same way the API's dates are
formatted so the two are directly comparable; `parseLocalDate()` splits and
passes `(y, m-1, d)` explicitly. **Never pass a bare date string to
`new Date()`.**

`dayDelta()` goes through those local midnights rather than subtracting
milliseconds off the raw strings, which DST makes wrong twice a year.

`last_updated` is different — it's a full local-time ISO timestamp from
`datetime.isoformat()`, not a bare date, so `new Date()` is correct there.

### Subtask nesting and ordering

Tasks come back flat, each carrying a `parent` (another task's id, or
`null`) and a `position`.

**`position` is sorted as a string**, via `localeCompare`, never parsed as
a number. It's a 20-digit fixed-width lexicographic key, and
`Number('09999999999999999999') === Number('09999999999999999998')` is
`true` — a numeric parse collides and the order silently scrambles.

A subtask whose parent isn't in the response is **promoted to the top
level** rather than dropped. That happens for real: the parent may be
completed, and so filtered out server-side by `show_completed`, while the
child is still open. A task that silently vanishes from the widget is worse
than one shown a level too high.

Children are indented by the dot's width plus its gap, so a child's text
starts where its parent's text does — the nesting reads off the text
column rather than off a rule.

### `textContent`, never `innerHTML`

Every value out of `tasks.json` goes in through `textContent`. Task titles
and notes are arbitrary text you typed on your phone, and a title
containing `<img src=x onerror=...>` would otherwise execute inside a page
that can reach `POST /refresh` and `/quit`. `net_guard` doesn't help here —
that would be our own origin asking.

### `/settings.json` is synthetic

There is no `settings.json` on disk. `serve.py` builds it per request from
an **allowlist** of `config.json` keys (`PAGE_SETTINGS` plus
`PAGE_WINDOW_SETTINGS`).

An allowlist for the same reason the file allowlist is one: `config.json`
holds the refresh token and must never be served, so the rule is what *is*
exposed rather than what isn't. A key added to `config.json` stays
invisible to the browser until it's named there.

Rebuilding per request is what makes editing `config.json` take effect on
the next page load with no sync step — DesktopCards' `/appearance.json`
trick, in miniature.

### Fitting the window to the content

`fitWindowToContent()` measures **height** from `document.body.scrollHeight`
and takes **width** from a constant.

Both halves are deliberate. `documentElement.scrollHeight` has a viewport
floor, so it never reports a height smaller than the window already is —
the window could grow but never shrink. And measuring *width* feeds the
window its own current width straight back, with the same result.

> **Three places hardcode the 325px design width and must change
> together:** `#shell { width }` in `dashboard.html`, `BASE_WIDTH` in
> `dashboard.js`, and `WINDOW_WIDTH` in `widget.py`.

Neither dimension is capped. A long task list is a reason for a taller
window, not a reason to hide the last task.

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
| A list with no open tasks | **All clear** — a success, not a failure |
| No lists at all | **No task lists** — nothing connected or nothing selected, which is different from being done |
| `AUTH_EXPIRED` | The message, plus *"Tray icon → Reconnect Google. Tasks below are from the last successful fetch."* |
| `FETCH_FAILED` | The message, plus *"Retrying at the next refresh."* Same promise about the tasks below. |
| No `tasks.json` at all | **No tasks yet**, plus *"Waiting for the first fetch."* |

That last one has its own code (`NO_DATA`, which the fetcher never emits —
it's the page's own state) precisely because the other two promise stale
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
  same-origin, so it can read the reply — every task title and note you
  have. Loopback is no defence because the connection genuinely is local.
  The giveaway is the `Host` header, which still says `attacker.com`.
- **CSRF.** A cross-origin page POSTs to `/refresh`, `/restart` or `/quit`.
  It can't read the response, but it doesn't need to in order to force a
  fetch or kill the widget.

Hence two rules: the `Host` must name this machine, and anything the
browser itself labels cross-site is refused. One exemption — a cross-site
GET *navigation*, because that becomes a page at our own origin rather than
data handed to someone else's script.

Verified behaviour: the page's own requests pass, `localhost` passes,
plain non-browser clients pass, a rebinding `Host` is refused, cross-site
GET and POST are refused, and a mismatched port is refused.

### What this deliberately does not defend against

Another process running on this machine. A request with neither an `Origin`
nor a `Sec-Fetch-Site` header is allowed through, because that's an
ordinary non-browser client — this app's own `urllib` calls among them —
and a hostile local process is not a threat this layer can do anything
about. It could read `config.json` off the disk instead, so a check at the
HTTP layer would be theatre. The attacks above are different in kind: they
need nothing more than a tab being open.

### `net_guard` must not touch the OAuth callback

`google_tasks_setup.Callback` runs its **own** server, and that is the whole
reason it's separate from `serve.py`'s.

The guard refuses anything the browser labels cross-site, and the consent
redirect is cross-site **by construction** — a top-level navigation
arriving from `accounts.google.com`. Applying the guard there would reject
the one request the listener exists to receive.

What stands in for it: the `state` parameter, which an attacker can't
guess, plus a socket bound to loopback and alive only for the few seconds
between opening the browser and the redirect landing.

### Why `127.0.0.1` and not `localhost`

On Windows that name resolves to `::1` before `127.0.0.1`, and since this
server is IPv4-only, every client using the name pays a dead IPv6
connection attempt first — measured in DesktopCards at 2.08s against 0.02s
for the literal. So the app always *dials* the literal. `net_guard`
*accepts* either spelling, plus any loopback IP in either family, because
whatever spelling the browser happens to use has to pass.

### The file allowlist

`serve.py` serves `dashboard*.html`, `dashboard.js` and `tasks.json`, and
synthesises `/settings.json`. Everything else 404s. An allowlist rather
than a denylist, so a new file in those folders is unreachable until
someone deliberately adds it.

`translate_path` resolves against `ASSET_DIR` first — letting the base
class do the traversal sanitising, collapsing `..` and dropping drive
letters — and only then re-roots the handful of URLs that belong to the
data side. Re-rooting a path already reduced to a safe relative one can't
reintroduce traversal. Frozen, this also means `config.json` isn't in any
directory a URL can address at all.

---

## Building the executable

```
pip install pyinstaller
python source/build.py
```

Produces `dist/DesktopTasks.exe`, about 33 MB, carrying Python and every
dependency, so it runs on a machine with no Python installed. Unsigned, so
the first run trips SmartScreen (**More info → Run anyway**).

`build.py` runs a preflight, regenerates the icon, then calls PyInstaller
against `DesktopTasks.spec` from the repo root, so `dist/` and `build/`
land there rather than inside `source/`.

> **Status: the exe builds, but has never been launched.** The frozen
> runtime path is therefore unverified — `paths.FROZEN`, the
> `%LOCALAPPDATA%` data dir, `EXAMPLES_DIR` resolving to the bundle, and
> above all whether pywebview loads its WebView2 backend under onefile.
> Launching it is the first thing to do before trusting a release.

### The preflight: the one way this build can ship broken

`preflight()` refuses to build when `oauth_client.py` is **missing**, or
when it's present with `CLIENT_ID = None` — which is exactly what copying
`oauth_client.example.py` leaves behind.

This exists because that is the project's only *quiet* failure. Everything
else fails loudly. Here, PyInstaller exits 0, the exe launches, the widget
appears, and then every single user who clicks Reconnect Google is told no
client is configured. PyInstaller cannot detect it, because the import is
conditional by design and the module is genuinely optional at runtime.

It also checks that PyInstaller is installed and that nothing is holding
the output exe open — renaming is the test, since Windows refuses it for a
file that's executing and it's harmless when nothing holds it. Otherwise
the build dies as a bare `PermissionError` from deep inside someone else's
code.

### One exe, not two

DesktopCards ships the same binary twice under different names, because its
first run is a Flask setup page and the filename selects the mode. There's
nothing to select here: a first launch brings up the widget, which reports
it has no tasks, and connecting happens from the tray. So the name carries
no meaning, `desktoptasks.py` has no `looks_like_setup_build()` equivalent,
and one output is enough.

### One entry point

Frozen, `sys.executable` **is** the app: it takes no script argument and
there are no `.py` files on disk to point at. Anything that spawns Python
by name breaks. A single entry point with subcommands means
`sys.executable` plus a flag covers every case, from source and frozen
alike — which is what `widget.spawn_self` relies on for the tray's
Restart.

### No console, so output goes to a file

A windowed build has no console, and PyInstaller sets `sys.stdout` and
`sys.stderr` to `None` rather than to something inert — so every `print()`
in the codebase would raise `AttributeError` on `None.write`. That would
turn harmless progress messages into crashes, in the build where they're
hardest to see. It applies to a source run under `pythonw` too, which is
how the tray's Restart relaunches.

`desktoptasks.redirect_output_to_log()` points them at
`desktoptasks.log` instead, which doubles as the diagnostic channel the
worst failure mode needs: pywebview coming up as a blank window with no
traceback anywhere, and the tray — the only control surface — not
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
display time — the shell picks whichever fits the context it's drawing in,
and a single 256px image looks muddy at 16px in a taskbar. PyInstaller's
`--icon` needs a real `.ico` and won't take a PNG, so the conversion has to
happen somewhere.

The conversion itself lives in `logo_cache.write_ico`, which the running
app also uses, so there's **one definition** of what a DesktopTasks icon
looks like rather than two that can drift.

A build step rather than a committed `.ico`, so there's no binary to fall
out of date — which is why `*.ico` is gitignored.

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
always newer than anything cached — an mtime comparison would rebuild both
derivatives every single run, which is exactly what the cache exists to
avoid. Hashing the bytes gives a stable answer when frozen and still
notices a genuinely different logo.

`widget.main()` calls `logo_cache.icon_file()` at startup to keep that
cached `.ico` in step. Nothing else rebuilds it, so without that a deleted
cache would leave any shortcut pointing at a missing file and showing a
generic icon — and it means replacing `logo.png` updates those shortcuts on
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
analysis — a function-local `import widget` is not one it can follow from
the entry point. The spec names them all, or the non-default subcommands
would be left out of the bundle entirely.

`webview.platforms.winforms` and `clr` are there because pywebview resolves
its backend **by name at runtime**, so neither is reachable statically.
This is the part most likely to need adjusting, and it fails as a blank
window rather than an `ImportError` — which is why
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
  erased, and the first thing to go missing is the WebView2 interop layer —
  so it dies with "Cannot find Microsoft.Web.WebView2.Core.dll", a message
  that points nowhere near the actual cause.
- **`force_exit_soon()`**. `window.destroy()` is supposed to end
  `webview.start()` and let `main()` return, and from source it does.
  Frozen it reliably leaves the process alive with its window handle still
  registered — pywebview's WinForms/pythonnet loop doesn't fully unwind —
  and every such leftover pins a ~33 MB unpack directory its bootloader
  can't clean up. Three restarts, three orphans. So the clean path gets a
  2.5s head start and this is the backstop. `os._exit`, not `sys.exit`,
  because the point is to skip an interpreter shutdown that is
  demonstrably capable of hanging.

`spawn_self` also starts the replacement from the **exe's own folder**, not
`ASSET_DIR`. Frozen, `ASSET_DIR` is this process's `_MEIPASS` temp
directory, and a process's current directory is locked against deletion
for as long as it lives — so starting the replacement there means our own
bootloader can never remove its temp folder.

### Restart, Quit, and the port

`Server.allow_reuse_address` is **False**, against `HTTPServer`'s default of
True, which on Windows lets a second process silently bind the same port on
top of a still-running one — requests then get split nondeterministically
between zombie instances.

The cost is that a previous instance's sockets sitting in `TIME_WAIT` make
the bind fail outright, and the tray's Restart lands inside that window
routinely: the old process exits and the replacement tries to bind
milliseconds later. `build_server` retries for about six seconds, because
`TIME_WAIT` is a timer rather than a contended lock — waiting it out *is*
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
login session, which is the right boundary — two users on one machine each
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
  Real rounded corners — desktop visible through them — need the OS-level
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
  [Pinned and read-only](#pinned-and-read-only) — the WorkerW layer takes
  no mouse input, so there is nowhere else for a control to go.
- **The tray icon is the logo, with a drawn dot as fallback.** The drawn
  circle came first and had one real advantage: generated from your
  Windows accent colour, it always matched your desktop. The logo doesn't
  track the accent, which is the price of having the tray icon, the exe
  icon and any shortcut be recognisably the same mark. The fallback is not
  dead code — `ASSET_DIR` points inside the unpacked bundle when frozen, so
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

### Step 0 — "Missing domain: github.com"

If the console shows **Missing domain: github.com** under Authorised
domains, that is **not** a verification failure. It means a URL you entered
on the branding page — the home page, privacy policy or terms — points at
`github.com`, and every domain used anywhere in the project has to be
pre-registered in the Authorised domains list first.

**The fix:** add `github.com` to Authorised domains. Enter the bare
top-level domain only — no `https://`, no `www.`, no path:

```
github.com
```

Once a domain is registered you may use any of its subdomains and any page
under it, so one entry covers every `github.com/...` URL. Google's own
guidance is to **add the authorised domain before** you add the home page,
privacy policy, terms or redirect URIs — doing it the other way round is
exactly what produces this error. There is a limit of **ten** authorised
domains per project.

That clears the error and is fine while the app is in **Testing**.
Search Console verification of those domains is only required "if your app
needs to go through verification".

**It will not survive verification, though**, which is the next section.

### Step 1 — a domain you own

**Short answer: yes, verification needs a domain you own. `github.com` can
never work for it.**

Not because Google dislikes GitHub, but because of *how* domains are
verified. Search Console requires a **Domain property**, verified at the
**DNS level** by adding a TXT record to the domain's DNS configuration, and
the verifying Google account must be an **owner of the Cloud project**. You
cannot add a DNS record to `github.com` — GitHub controls it. The same
applies to `github.io`, `vercel.app`, `netlify.app` and every other shared
provider domain: Google's advice for these is to map the service to a
subdomain of a domain you already own.

So for verification, this is the real blocker, and it gates everything
else. Google requires the app's **home page**, **privacy policy** and
**terms of service** to be live web pages, and the privacy policy must be
**hosted on the same domain as the home page**. The Markdown drafts in this
folder cannot be the URLs you submit — they have to be published.

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

Link the privacy policy and terms from the home page's footer — Google
wants the policy "visible to users", not merely reachable by direct URL.

### Do you actually need this?

Only if you want the app **verified**. The three end states again, with
what each one costs:

| Goal | Domain needed? | What to do |
|---|---|---|
| Just you | **No** | Stay in Testing. Register `github.com` as above to clear the error. Accept the weekly reconnect. |
| You and people you know | **Probably** | The console wants home page / privacy / terms URLs before it will let you publish to production. Those URLs need an authorised domain, but **not a verified one**, since you are not submitting for review. Try `github.com` first — it may well be accepted. |
| A public release | **Yes** | Everything in Step 1. There is no way around DNS-level domain verification. |

The middle row is the one worth testing before spending money: publishing
to production **without** submitting for verification already fixes both
problems that bite today — the 7-day token expiry and the test-user
restriction — and it is not certain that the console demands a *verified*
domain to do it. Try it with `github.com` registered; if the console lets
you publish, you have what you need for nothing.



This is the real blocker, and it gates almost everything else. Google
requires the app's **home page**, **privacy policy** and **terms of
service** to be live web pages, and the privacy policy must be
**hosted on the same domain as the home page**. The Markdown drafts in this
folder cannot be the URLs you submit — they have to be published.

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

Link the privacy policy and terms from the home page's footer — Google wants
the policy "visible to users", not merely reachable by direct URL.

### The site, in `site/`

`site/` holds a small static site — `index.html`, `privacy.html`,
`terms.html`, one stylesheet and the logo — published to GitHub Pages by
`.github/workflows/pages.yml`. It lands at
`https://aaryanpanigrahi.github.io/DesktopTasks/`.

It is its own folder rather than the repo root or `/docs`: the root would
put `index.html` beside the source tree, and `/docs` would collide with
this repo's existing `Docs/`. GitHub paths are case-sensitive, so `Docs/`
and `docs/` are different things, and relying on that distinction is a trap
for whoever looks next.

**What it is worth, and what it is not.** It gives the project a real home
page, privacy policy and terms at URLs that are not a code listing — which
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

### Step 2 — fill in the drafts

`Docs/PRIVACY.md` and `Docs/TERMS.md` are complete drafts that describe this
app's actual behaviour. Both need every `[BRACKETED]` value filled in:

- `[DATE]` — effective and last-updated dates
- `[YOUR NAME OR ENTITY]` — who publishes the app
- `[CONTACT EMAIL]` — a contact address. Consider a dedicated alias rather
  than your personal Gmail, since this is published publicly.
- `[YOUR-DOMAIN]` — your domain, in the cross-links
- `[JURISDICTION]`, `[CURRENCY] [AMOUNT]`, `[LICENSE]` — in the terms

The privacy policy already contains the **Google API Services Limited Use
disclosure**, which is required when a sensitive scope is involved, and it
already discloses how the app accesses, uses, stores and shares Google user
data — the four things Google checks it for.

The app's strongest argument at review is that it is **fully local**: no
server, no telemetry, no onward disclosure. Keep that prominent.

### Step 3 — the OAuth consent screen

In the Cloud console, make the branding match the pages above exactly:

- App name identical to the name used on the home page and in the app
- Support email
- App home page URI, privacy policy URI, terms of service URI
- An app logo, if you add one
- Authorized domains matching what you verified in Search Console

Google checks that the consent screen "accurately represents the app's
identity", so a mismatch between the app name here and the name on your
home page is a common rejection.

### Step 4 — a demo video

**Required** for sensitive-scope verification, and easy to get wrong:

- Uploaded to YouTube as **Unlisted**
- **In English**
- Shows the **OAuth consent flow** as a user actually experiences it
- Shows the **app name and the OAuth client ID** on screen, legibly
- Demonstrates **how the sensitive scope is actually used** — i.e. the
  widget displaying real tasks after consent

For this app a short screen recording covers it: the tray's Reconnect
Google, the consent screen with the app name visible, then tasks appearing
in the widget. Show the client ID from the consent screen URL or the Cloud
console.

### Step 5 — submit, and expect it to take a while

Publish the app to production in the console, then submit for verification.
Google's published timings:

| Stage | Typical |
|---|---|
| Brand verification | 2–3 business days |
| Sensitive scope verification | 3–5 business days, and up to 10 |

**A security assessment is not required here.** That applies to *restricted*
scopes (Gmail, Drive and similar). `tasks.readonly` is **sensitive**, not
restricted, so there is no third-party assessment and no associated cost —
which is the single biggest thing working in your favour.

### What you get at each stage

| State | Who can sign in | Token lifetime | Warning screen |
|---|---|---|---|
| **Testing** (now) | Only listed test users, max 100 | **7 days** | Yes |
| **Production, unverified** | Anyone, up to a ~100-user cap | Normal | Yes — one click behind **Advanced** |
| **Production, verified** | Anyone | Normal | **No** |

Note the middle row: **publishing alone, without verification, already
fixes both of the problems that bite today** — the weekly reconnect and the
test-user restriction. Verification only removes the warning screen and the
user cap.

Staying unverified is a legitimate end state, not a half-finished one.
Google's own documentation says apps "used only by the developer and
personally known users may skip verification and proceed through the
unverified app screen" — which is exactly what DesktopTasks is for now.
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
- **No appearance settings UI.** Editing `config.json` by hand is the only
  way to change the theme, position or corner radius. DesktopCards has a
  Flask page for this; the one thing here that needs doing on a schedule
  is already a tray item, so this is lower value than it looks.
- **No translucency.** DesktopCards supports a see-through card over the
  wallpaper. It needs the page and the native window to agree — the page's
  `rgba` colours can only blend against whatever the *window* paints — so
  it's a both-files change, not a CSS one.
- **`erase_vacated_area` is unverified.** Ported from DesktopCards, where
  it guards against stale pixels left behind when a transparent window
  shrinks. Since this window is opaque, its own background brush erases
  what it was painting over, so the function is currently unreachable in
  practice. It matters only if translucency is ever added.
- **The remote is still named `DesktopTools`.** The local folder was
  renamed; the remote URL was deliberately left alone so an existing push
  doesn't break. After renaming on GitHub:
  `git remote set-url origin https://github.com/AaryanPanigrahi/DesktopTasks.git`

---

## References

- The window machinery — frameless WebView2 window, WorkerW pinning,
  taskbar hiding, rounded-corner clipping, the tray icon, the local server,
  the loopback request guard, the frozen/source path split and the
  PyInstaller setup — is ported from
  [DesktopCards](https://github.com/AaryanPanigrahi/DesktopCards), where
  it was worked out first. `net_guard.py` and `platform_win.py` are
  essentially unchanged; `paths.py` and `serve.py` are adapted; `widget.py`
  and the page are rewritten around a different content model.
- `DesktopCards/Docs/exe_problems.md` is a log of what went wrong the first
  time that project was packaged, and is worth reading before touching the
  build.
- `DesktopCards/Docs/mac_port.md` covers what a macOS port would involve.
  Three of `platform_win.py`'s five concerns are *simpler* there, where
  windows are composited and a window level can be set directly instead of
  reparenting onto a layer you first have to go find.
- Google's own documentation is the source for the installed-app credential
  model — that a desktop client's secret is not treated as confidential,
  and that PKCE is what secures the exchange.
