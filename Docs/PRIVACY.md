# Privacy Policy for DesktopTasks

**Effective date:** [DATE]
**Last updated:** [DATE]

> **This is a draft, not a published policy.** Before submitting it to
> Google, fill in every `[BRACKETED]` value and publish it as a web page at
> `https://[YOUR-DOMAIN]/privacy` — Google requires the privacy policy to be
> **hosted on the same domain as the app's home page**, so a Markdown file
> in this repository cannot be the URL you submit. See `Docs/README.md`
> under "Making the app public" for the full checklist. This draft describes
> the app's actual behaviour accurately, but it is not legal advice; have it
> reviewed if anything here matters to you beyond passing verification.

---

## Who this covers

DesktopTasks ("the app") is a desktop widget for Windows that displays your
Google Tasks on your desktop. It is published by [YOUR NAME OR ENTITY]
("we", "us").

Contact: **[CONTACT EMAIL]**

## The short version

DesktopTasks runs entirely on your own computer. It reads your Google Tasks
and draws them on your desktop. **We operate no servers and receive no data
from you at any point.** Your tasks and your Google credentials are stored
only on your own device, and nothing is transmitted anywhere except directly
between your computer and Google's own APIs.

## What data the app accesses

The app requests a single Google OAuth scope:

| Scope | Access |
|---|---|
| `https://www.googleapis.com/auth/tasks.readonly` | **Read-only** access to your Google Tasks |

This is the narrowest scope that makes the app function. The app can read
your tasks; it cannot create, edit, complete or delete them, and it cannot
access any other Google service — not your email, not your files, not your
calendar, not your contacts.

Through that scope the app reads:

- Your task lists (their names and identifiers)
- The open tasks in those lists, including each task's title, notes, due
  date, completion status, parent task and sort position

The app also receives and stores an OAuth **refresh token** from Google,
which is what lets it read your tasks again later without asking you to
sign in every time.

## How the app uses that data

Solely to display your tasks in the widget on your own screen. There is no
other use.

Specifically, the app does **not**:

- Transmit your Google user data to us or to any third party
- Send your data to any server we operate — we operate none
- Use your data for advertising, profiling, or any form of marketing
- Sell, rent, or trade your data
- Use your data to train, develop, or improve any machine-learning or
  artificial-intelligence model
- Allow any human to read your data, including us
- Collect analytics, telemetry, crash reports, or usage statistics of any
  kind

## Where that data is stored

Everything is stored locally on your own computer, in files only you and
other programs on your machine can read:

| What | Where |
|---|---|
| Your tasks, as last fetched | `tasks.json` in the app's data folder |
| Your OAuth refresh token and your settings | `config.json` in the same folder |
| A diagnostic log, when the app has no console | `desktoptasks.log` in the same folder |

The data folder is `%LOCALAPPDATA%\DesktopTasks\` for an installed copy, or
the `config\` folder inside the project directory when the app is run from
source.

The app serves your tasks to its own display window over a web server bound
to `127.0.0.1` (your own machine's loopback address). This server is not
reachable from your local network or from the internet, it rejects any
request that does not originate from your own machine, and it never serves
the file containing your refresh token.

## How that data is shared

It is not. There is no onward disclosure of your Google user data to any
party, for any purpose.

The only network connections the app makes are directly from your computer
to Google's own services:

- `accounts.google.com` — when you sign in
- `oauth2.googleapis.com` — to refresh its access token
- `tasks.googleapis.com` — to read your tasks

## How long that data is kept, and how to delete it

Your data stays on your computer until you remove it. Nothing expires on our
side, because nothing is on our side.

**To revoke the app's access to your Google account**, visit
[https://myaccount.google.com/permissions](https://myaccount.google.com/permissions)
and remove DesktopTasks. This immediately invalidates its refresh token; the
app will no longer be able to read your tasks.

**To delete the data stored on your computer**, delete the app's data
folder (`%LOCALAPPDATA%\DesktopTasks\`, or the project's `config\` folder).
That removes your stored tasks, your refresh token, your settings and the
log.

Doing both leaves no trace of your Google data anywhere.

## Google API Services Limited Use disclosure

The app's use of information received from Google APIs adheres to the
[Google API Services User Data Policy](https://developers.google.com/terms/api-services-user-data-policy),
including the Limited Use requirements.

In particular, data obtained through Google APIs is used only to provide and
improve the app's user-facing features, is not transferred to others except
as necessary to provide those features or to comply with applicable law, is
not used for advertising, and is not used to develop, improve, or train
generalized or non-personalized artificial-intelligence or machine-learning
models. No humans read the data except with your affirmative agreement, for
security purposes, or to comply with applicable law.

## Children

The app is not directed to children and does not knowingly collect data
from them. It has no accounts, no profiles and no data collection of its
own.

## Security

Your Google credentials are never seen by the app: you sign in on Google's
own pages, and the app receives only a token afterwards. The sign-in flow
uses PKCE and a one-time `state` parameter, and the token exchange happens
over HTTPS directly with Google.

Your refresh token is stored in plain text in a file in your user profile,
protected by your operating system's file permissions. Anyone with access to
your Windows user account, or to an unencrypted backup of it, could read
that file. If that is a concern for you, enable disk encryption and do not
share your user account.

## Changes to this policy

If this policy changes materially, the updated version will be published at
this same URL with a new "Last updated" date. Significant changes affecting
how Google user data is handled will also be noted in the app's release
notes.

## Your rights

Because we hold none of your data, requests to access, correct, export or
delete it are satisfied entirely by you, on your own machine, using the two
steps under "How long that data is kept". If you believe the app behaves
differently from this policy, please contact **[CONTACT EMAIL]**.

## Not affiliated with Google

DesktopTasks is an independent application. It is not created, endorsed,
sponsored by, or affiliated with Google LLC. "Google", "Google Tasks" and
related marks belong to Google LLC.
