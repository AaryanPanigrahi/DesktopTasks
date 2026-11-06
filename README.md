# DesktopTasks

Your Google Tasks, pinned to a corner of your desktop. It can start with
Windows, keeps itself up to date, survives Win+D, and never shows up in the
taskbar or in Alt+Tab.

<img src="logo.png" alt="" width="96" align="right">

Each list is a card: open tasks with their subtasks nested underneath, notes,
and due dates read the way a person would say them. *Today*, *Tomorrow*, then
*Oct 20*, with overdue and today picked out in colour. A list with nothing
open says **All clear**.

It only ever reads your tasks. A pinned window gets no mouse input at all, so
there is nothing to click on the widget itself. Everything lives in the tray
icon and a settings page in your browser.

### Supports

**Tasks**

- Several Google accounts, with a switcher
- Picking which task lists show, without forgetting the ones you unpick
- Lists of its own: Due today, Overdue, Due this week, Due in order,
  No due date

**Appearance**

- Light/Dark theme, and an accent colour
- Translucency and opacity, rounded corners, scale, and custom spacing
- Several columns, with the lists dealt across them in an order you drag
- Column width, a height cap, and a limit on how many tasks are drawn

**Windows**

- 'Survive' show desktop (Win + D) toggle
- Starting with Windows, and Start-menu or desktop shortcuts

### Before you start

Windows only. You need a Google account, and that is all. No API billing, no
keys to buy. Signing in happens on Google's own page, where DesktopTasks asks
only to **see** your tasks and your email address.

**Google will call it an unverified app.** Choose *Advanced*, then *Go to
DesktopTasks (unsafe)*. Until the project is verified, two things follow:
the sign-in expires every 7 days, so about once a week the widget asks you to
reconnect, and only accounts on the project's test-user list can sign in at
all, which is why you run it with a Cloud project of your own.
[Why, and what it takes to end it](Docs/README.md#testing-status-and-the-two-things-it-costs).

**Everything stays on your computer.** Your tasks and your Google token are
files on this machine. The background server that serves the settings page
binds `127.0.0.1` and refuses anything that did not come from here. Your
password is only ever typed on Google's page.

## Getting started

First, an OAuth client of your own, since a release would bundle one but this
repo deliberately does not. In the
[Cloud console](https://console.cloud.google.com/): enable the **Tasks API**,
set the OAuth consent screen to **External**, add your Google account under
**test users**, and create a client of type **Desktop app**. Copy
`source/oauth_client.example.py` to `source/oauth_client.py` and paste it in.
[Step by step](Docs/README.md#cloud-console-configuration).

Then, either:

**1) Install it.** No release is published yet, so build the installer once:

```
pip install -r requirements.txt
pip install pyinstaller
python source/build.py
```

Run `dist/DesktopTasks-Setup.exe`. One dialog, one tick box for *start with
Windows*, and it installs to `%LOCALAPPDATA%\DesktopTasks`, adds a Start-menu
entry and launches. It isn't signed, so choose *More info*, then *Run anyway*.
Nothing needs administrator.

**2) Or run it from Python.**

```
pip install -r requirements.txt
python source/desktoptasks.py --connect     # sign in to Google
pythonw source/desktoptasks.py              # run the widget
```

Either way, connect your Google account from the tray icon.
`desktoptasks.py --help` lists the other modes.

## Changing things

Right-click the tray icon:

| | |
|---|---|
| **Reload** | Fetch from Google now |
| **Modify** | Open the settings page |
| **Restart** | Relaunch the widget |
| **Quit** | Close it |

**Modify** opens three tabs in your browser:

| | |
|---|---|
| **Account** | Sign in, switch accounts, choose which lists show |
| **Layout** | Columns, and the order lists are dealt in |
| **Appearance** | The look, the window, and the Windows shortcuts |

Saving applies straight away. A few settings are only read when the window is
created. The page marks each one, and **Restart widget** applies them.

Prefer a text editor? `config.json` holds your account and the fetch,
`appearance.json` holds the look. The second has no secrets in it, and a few
things the page does not show, like the widget's colours and text sizing.
[Every key](Docs/README.md#configuration-configjson-and-appearancejson).

## Uninstalling

DesktopTasks is in **Settings > Apps**, and `Uninstall.exe` sits beside the
app in `%LOCALAPPDATA%\DesktopTasks\`. Either works. It asks once whether to
keep your settings and signed-in account, so a reinstall can pick them up.

Your tasks are untouched. They live in your Google account, this app only
read them, and the token it removes is a local file. From a checkout:
`python source/desktoptasks.py --uninstall`.

## What's in this repo

| | |
|---|---|
| `source/` | The code: the widget, the server, both pages, setup and uninstall |
| `config/` | Example settings. Your real ones are made on first run and stay on your machine |
| `Docs/` | The full write-up, plus the privacy policy and terms |
| `site/` | The small public site those two are published from |
| `logo.png` | The app's mark. The exe icon and the tray icon both derive from it |

Nothing secret is tracked: `config/config.json`, `config/appearance.json` and
`source/oauth_client.py` are gitignored.

[`Docs/README.md`](Docs/README.md) is the long version: every setting, how
refreshing works, how the pinned window is done, how installing works, and
why things are built the way they are.
