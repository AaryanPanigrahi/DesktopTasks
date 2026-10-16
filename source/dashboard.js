// The tasks dashboard. Reads tasks.json (written by google_tasks.py) and
// /settings.json (built by serve.py from the page-safe keys of
// config.json), renders, then asks the window to fit the result.
//
// There's no in-page reload control, and no checkboxes. The window is
// reparented onto the desktop's WorkerW layer to survive Win+D, and that
// layer doesn't receive normal mouse input (the same reason
// Rainmeter/Wallpaper Engine skins need a system-wide hook to be clickable
// at all). That's a decision, not a limitation. Manual refresh lives in
// the system tray icon (widget.py), which calls POST /refresh and then
// tells this page to reload -- as does Reconnect Google, which this page
// names in its AUTH_EXPIRED notice but cannot offer itself.

// Re-read tasks.json every 5 minutes. No network calls of our own: the
// actual Google fetch is widget.py's fetch_loop on its own interval, and
// this only picks up whatever that last wrote. Cheap enough to be
// unconditional -- it's a local file read.
const POLL_MS = 5 * 60 * 1000;

const DEFAULT_SETTINGS = {
  show_notes: true,
  group_by_list: true,
  fetch_interval_minutes: 15,
  dark_theme: true,
  accent: null,
};

let settings = { ...DEFAULT_SETTINGS };

// ------------------------------------------------------------- dates
//
// Due dates arrive as a bare "YYYY-MM-DD" string. google_tasks.py
// truncates them on purpose: the API stores midnight UTC, and parsing
// that into a zone west of UTC shifts the date back a day -- a task due
// the 17th shows as the 16th and reads as overdue a day early.
//
// So the rule throughout this file is: compare due dates as strings, and
// when a Date is unavoidable, build it from the parts in local time.
// Never pass a bare date string to new Date().

function todayKey() {
  const d = new Date();
  // Local year/month/day, formatted the same way the API's dates are, so
  // the two are directly comparable as strings.
  return [
    d.getFullYear(),
    String(d.getMonth() + 1).padStart(2, '0'),
    String(d.getDate()).padStart(2, '0'),
  ].join('-');
}

function parseLocalDate(key) {
  // Explicit local construction -- new Date('2026-10-17') would be parsed
  // as UTC midnight. See the note above.
  const [y, m, d] = key.split('-').map(Number);
  return new Date(y, m - 1, d);
}

function dayDelta(key, today) {
  // Whole days between two date keys, via local midnights. Not a
  // millisecond subtraction on the raw strings, which DST makes wrong
  // twice a year.
  const a = parseLocalDate(key);
  const b = parseLocalDate(today);
  return Math.round((a - b) / 86400000);
}

// "Today" and "Tomorrow" rather than a date, because that's how anyone
// reads a due date in the next day or so; further out, the date itself is
// more informative than a day count. The year is added only when it isn't
// this one, so the common case stays short.
function formatDue(key, today) {
  const delta = dayDelta(key, today);
  if (delta === 0) return 'Today';
  if (delta === 1) return 'Tomorrow';
  if (delta === -1) return 'Yesterday';

  const d = parseLocalDate(key);
  const opts = { month: 'short', day: 'numeric' };
  if (d.getFullYear() !== new Date().getFullYear()) opts.year = 'numeric';
  const text = d.toLocaleDateString('en-US', opts);
  // Overdue by more than a day reads better as a count than as a date --
  // "5 days ago" is the fact you act on; the date is just how it's stored.
  return delta < -1 ? `${text} · ${-delta} days ago` : text;
}

function dueClass(key, today) {
  if (!key) return '';
  const delta = dayDelta(key, today);
  if (delta < 0) return 'overdue';
  if (delta === 0) return 'today';
  return '';
}

// --------------------------------------------------------- the tree
//
// Tasks come back flat, each carrying a `parent` (another task's id, or
// null) and a `position` string. Google's position is a fixed-width
// lexicographic key, so sorting by it as a plain string is correct and
// parsing it as a number is not -- it's 20 digits and would lose
// precision as a JS float.

function buildTree(tasks) {
  const byParent = new Map();
  const ids = new Set(tasks.map(t => t.id));

  for (const task of tasks) {
    // A subtask whose parent isn't in this response is promoted to the top
    // level rather than dropped. That happens for real: the parent may be
    // completed (and so filtered out server-side by show_completed) while
    // the child is still open, and a task that silently vanishes from the
    // widget is worse than one shown a level too high.
    const parent = task.parent && ids.has(task.parent) ? task.parent : null;
    if (!byParent.has(parent)) byParent.set(parent, []);
    byParent.get(parent).push(task);
  }

  for (const siblings of byParent.values()) {
    siblings.sort((a, b) =>
      String(a.position || '').localeCompare(String(b.position || '')));
  }
  return byParent;
}

// ------------------------------------------------------- rendering
//
// textContent everywhere, never innerHTML, for anything that came out of
// tasks.json. Task titles and notes are arbitrary text the user typed on
// their phone, and a title containing "<img onerror=...>" would otherwise
// execute inside a page that can reach POST /refresh and /quit. The
// net_guard rules don't help here -- this would be our own origin asking.

function renderTask(task, byParent, today, into) {
  const key = task.due || null;
  const cls = dueClass(key, today);

  const row = document.createElement('div');
  row.className = 'task' + (cls ? ' ' + cls : '');

  const dot = document.createElement('div');
  dot.className = 'dot';
  row.appendChild(dot);

  const body = document.createElement('div');
  body.className = 'body';

  const title = document.createElement('div');
  title.className = 'title';
  title.textContent = task.title || '(untitled)';
  body.appendChild(title);

  if (settings.show_notes && task.notes) {
    const notes = document.createElement('div');
    notes.className = 'notes';
    notes.textContent = task.notes;
    body.appendChild(notes);
  }

  if (key) {
    const due = document.createElement('div');
    due.className = 'due';
    due.textContent = formatDue(key, today);
    body.appendChild(due);
  }

  row.appendChild(body);
  into.appendChild(row);

  const children = byParent.get(task.id) || [];
  if (children.length) {
    const wrap = document.createElement('div');
    wrap.className = 'children';
    for (const child of children) renderTask(child, byParent, today, wrap);
    into.appendChild(wrap);
  }
}

function renderList(list, today, { titled }) {
  const card = document.createElement('div');
  card.className = 'list' + (titled ? '' : ' untitled');

  if (titled) {
    const heading = document.createElement('div');
    heading.className = 'list-title';
    heading.textContent = list.title || 'Tasks';
    card.appendChild(heading);
  }

  const tasks = list.tasks || [];
  if (!tasks.length) {
    // A list with nothing open is a success. Worth saying so rather than
    // rendering an empty card that looks like a loading failure.
    const empty = document.createElement('div');
    empty.className = 'empty';
    empty.textContent = 'All clear';
    card.appendChild(empty);
    return card;
  }

  const byParent = buildTree(tasks);
  for (const task of byParent.get(null) || []) {
    renderTask(task, byParent, today, card);
  }
  return card;
}

// How to recover, per error_code. The fetcher only ever emits these two
// (google_tasks.py), and both are states the user can be told something
// useful about -- which matters more here than in DesktopCards, because a
// pinned page cannot offer a button and the tray is the only way out.
const RECOVERY = {
  AUTH_EXPIRED: 'Tray icon → Reconnect Google. Tasks below are from the last successful fetch.',
  FETCH_FAILED: 'Retrying at the next refresh. Tasks below are from the last successful fetch.',
  // Not a code the fetcher emits -- this page's own state for "tasks.json
  // isn't there at all", which is a first launch before the first fetch
  // lands rather than a failure. It needs its own entry precisely because
  // the two above promise stale tasks below the notice, and here there
  // aren't any: nothing has ever been fetched.
  NO_DATA: 'Waiting for the first fetch. If this stays, connect your Google account from the tray icon.',
};

function renderNotice(err) {
  const box = document.createElement('div');
  box.className = 'notice';

  const head = document.createElement('strong');
  head.textContent = err.error_message || 'Something went wrong';
  box.appendChild(head);

  const how = RECOVERY[err.error_code];
  if (how) {
    const hint = document.createElement('div');
    hint.className = 'how';
    hint.textContent = how;
    box.appendChild(hint);
  }
  return box;
}

// ------------------------------------------------------- the clock
function minutesUntilNextFetch(lastUpdatedIso) {
  if (!lastUpdatedIso || !settings.fetch_interval_minutes) return null;
  // last_updated is a full local-time ISO timestamp from
  // datetime.isoformat(), not a bare date, so new Date() is right here --
  // the date-string hazard above does not apply to it.
  const last = new Date(lastUpdatedIso).getTime();
  if (Number.isNaN(last)) return null;
  const next = last + settings.fetch_interval_minutes * 60 * 1000;
  return Math.round((next - Date.now()) / 60000);
}

function formatCountdown(mins) {
  // Never a flat "0m": the countdown is a lower bound, not a promise the
  // fetch lands exactly on time.
  if (mins < 1) return '<1m';
  if (settings.fetch_interval_minutes > 10 && mins < 5) return '<5m';
  return `${mins}m`;
}

function updatedText(lastUpdatedIso) {
  if (!lastUpdatedIso) return '';
  const d = new Date(lastUpdatedIso);
  if (Number.isNaN(d.getTime())) return '';
  const time = d.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' });
  const mins = minutesUntilNextFetch(lastUpdatedIso);
  // Middle dot rather than a colon, which would collide visually with the
  // colon already inside the time ("10:42 PM").
  return mins !== null ? `${formatCountdown(mins)} · ${time}` : time;
}

// --------------------------------------------------- settings/theme
function applySettings(incoming) {
  settings = { ...DEFAULT_SETTINGS, ...(incoming || {}) };
  document.documentElement.dataset.theme = settings.dark_theme ? 'dark' : 'light';
  if (settings.accent) {
    document.documentElement.style.setProperty('--accent', settings.accent);
  }
}

async function loadSettings() {
  try {
    const res = await fetch('settings.json', { cache: 'no-store' });
    if (!res.ok) throw new Error('settings unavailable');
    applySettings(await res.json());
  } catch (e) {
    // Defaults are survivable -- the page renders, it just might render
    // in the wrong theme for a moment. Not worth failing a load over.
    applySettings(null);
  }
}

// --------------------------------------------------------- the load
async function load() {
  const listsEl = document.getElementById('lists');
  const noticesEl = document.getElementById('notices');
  const updatedEl = document.getElementById('updated');

  let data;
  try {
    const res = await fetch('tasks.json', { cache: 'no-store' });
    if (!res.ok) throw new Error('no tasks.json yet');
    data = await res.json();
  } catch (e) {
    // A fresh install genuinely has no tasks.json until the first fetch
    // lands, and that's the common case on a first launch rather than an
    // error. Say what's happening instead of showing a bare failure.
    noticesEl.replaceChildren(renderNotice({
      error_message: 'No tasks yet',
      error_code: 'NO_DATA',
    }));
    listsEl.replaceChildren();
    updatedEl.textContent = '';
    fitWindowToContent();
    return;
  }

  const today = todayKey();
  const lists = data.lists || [];
  const errors = data.errors || [];

  noticesEl.replaceChildren(...errors.map(renderNotice));
  updatedEl.textContent = updatedText(data.last_updated);

  if (settings.group_by_list) {
    listsEl.replaceChildren(
      ...lists.map(list => renderList(list, today, { titled: true }))
    );
  } else {
    // One card, every task flattened into it. The per-list `parent`
    // relationships still hold because ids are globally unique across
    // lists -- buildTree keys on them, not on list membership.
    const merged = { title: null, tasks: lists.flatMap(l => l.tasks || []) };
    listsEl.replaceChildren(renderList(merged, today, { titled: false }));
  }

  // No lists at all is different from a list with no tasks: it means
  // nothing is connected or nothing is selected, not that you're done.
  if (!lists.length && !errors.length) {
    const box = document.createElement('div');
    box.className = 'list untitled';
    const empty = document.createElement('div');
    empty.className = 'empty';
    empty.textContent = 'No task lists';
    box.appendChild(empty);
    listsEl.replaceChildren(box);
  }

  fitWindowToContent();
}

// ----------------------------------------------------- window fit
const BASE_WIDTH = 325;  // keep in step with #shell width and WINDOW_WIDTH

function fitWindowToContent() {
  requestAnimationFrame(() => {
    // Width is the known design width, not a measurement.
    // scrollWidth/offsetWidth report the window's *current* width rather
    // than the content's true width, so measuring it just feeds the
    // window its own size back and it never shrinks.
    const width = BASE_WIDTH;
    // Height is measured, because only the page knows how many tasks
    // there are. body rather than documentElement: documentElement's
    // scrollHeight has a viewport floor, so it never reports a height
    // smaller than the window already is -- the same reason DesktopCards
    // reads body here.
    const height = document.body.scrollHeight;

    if (window.pywebview && window.pywebview.api) {
      // The frameless window has no browser chrome to account for -- the
      // exposed API resizes the actual OS window directly.
      window.pywebview.api.resize_window(width, height);
      return;
    }

    // Fallback for debugging in a plain browser tab (DesktopTasks.exe
    // --serve), where resizeTo needs the chrome's overhead added back.
    try {
      window.resizeTo(width, height + (window.outerHeight - window.innerHeight));
    } catch (e) {
      // not resizable in this context -- ignore
    }
  });
}

// pywebview injects window.pywebview slightly after page load (firing
// 'pywebviewready') rather than synchronously, so the first resize call
// would otherwise race ahead of the bridge existing. The timeout lets
// this resolve harmlessly in a plain browser tab, where it never fires.
function waitForPywebviewReady() {
  return new Promise(resolve => {
    if (window.pywebview) return resolve();
    window.addEventListener('pywebviewready', resolve, { once: true });
    setTimeout(resolve, 1000);
  });
}

// The name widget.py calls through evaluate_js, after the tray's Reload
// and after every interval fetch. Re-reads settings too, so editing
// config.json's show_notes or dark_theme takes effect on a Reload without
// restarting the widget -- serve.py rebuilds /settings.json per request
// for exactly that reason.
async function reloadAll() {
  await loadSettings();
  await load();
}

async function init() {
  await waitForPywebviewReady();
  await reloadAll();
  setInterval(load, POLL_MS);
}

init();
