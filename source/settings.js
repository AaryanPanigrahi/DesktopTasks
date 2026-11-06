// The settings page's behaviour.
//
// Reads GET /api/state once on load, writes POST /api/config on Save, and
// starts a sign-in with POST /api/connect. All three are served by
// serve.py inside the widget process, so this page is talking straight to
// the running widget rather than to a second application.
//
// Nothing saves implicitly. Every control marks the form dirty and the
// Save button does the write, because a settings page that writes on
// every keystroke makes a half-typed number a real setting for a moment.

const $ = id => document.getElementById(id);

// Mirrors serve.py's WRITABLE and WRITABLE_WINDOW. The element id is the
// setting name for the top-level ones; the window block names its own,
// because "x" is too generic to be an element id.
const TOGGLES = ['show_completed', 'show_notes', 'group_by_list',
                 'translucent_background', 'custom_spacing',
                 'personalised_lists'];
const NUMBERS = ['fetch_interval_minutes', 'columns', 'max_tasks', 'spacing',
                 'column_width', 'max_height'];
// Kept apart from NUMBERS because these must not be rounded to integers.
const FLOATS = ['scale', 'opacity'];
const WIN_TOGGLES = { survive_show_desktop: 'survive_show_desktop', dark_theme: 'dark_theme' };
const WIN_NUMBERS = { x: 'win_x', y: 'win_y', corner_radius: 'corner_radius' };

// The per-side spacing boxes. Element id -> key in the spacing_sides
// block serve.py writes.
const SIDES = {
  spacing_left: 'left',
  spacing_top: 'top',
  spacing_right: 'right',
  spacing_bottom: 'bottom',
};

// Every slider, and the number box that sits beside it. The two hold one
// value between them, so each spec says how to carry it across:
//
//   toBox    slider value -> what the box shows
//   fromBox  what was typed -> a slider value
//   unit     the words after the box, which is where a value that is not
//            a number ("all") is said
//
// scale and opacity are stored as fractions and shown as percentages,
// because 1.25 is not how anyone asks for a quarter bigger.
const SLIDERS = {
  columns: {
    toBox: v => String(Math.round(Number(v))),
    fromBox: v => Math.round(Number(v)),
    unit: v => Number(v) === 1 ? 'column' : 'columns',
  },
  max_tasks: {
    toBox: v => String(Math.round(Number(v))),
    fromBox: v => Math.round(Number(v)),
    unit: v => Number(v) === 0 ? 'all' : 'tasks',
  },
  scale: {
    toBox: v => String(Math.round(Number(v) * 100)),
    fromBox: v => Number(v) / 100,
    unit: () => '%',
  },
  spacing: {
    toBox: v => String(Math.round(Number(v))),
    fromBox: v => Math.round(Number(v)),
    unit: () => 'px',
  },
  opacity: {
    toBox: v => String(Math.round(Number(v) * 100)),
    fromBox: v => Number(v) / 100,
    unit: () => '%',
  },
};

let state = null;
let dirty = false;
// The working order of list ids, edited by dragging. Separate from the
// checkboxes because a list can be ordered without being shown.
let order = [];

function markDirty() {
  dirty = true;
  $('save').disabled = false;
  setMsg('');
}

// The box and the unit, from whatever the slider currently holds. The
// slider is the one value of record: typing in the box writes it there
// first (see syncFromBox) and everything redraws from that.
function refreshReadouts() {
  for (const [id, spec] of Object.entries(SLIDERS)) {
    const slider = $(id);
    const box = $(id + '-num');
    const unit = $(id + '-unit');
    // Not while it is being typed in: rewriting the box under the caret
    // turns "1" on the way to "12" into "1".
    if (box && document.activeElement !== box) box.value = spec.toBox(slider.value);
    if (unit) unit.textContent = spec.unit(slider.value);
  }
  // Per-side boxes mean nothing while the single number is in charge.
  const sides = $('sides');
  if (sides && sides.hidden === $('custom_spacing').checked) {
    sides.hidden = !$('custom_spacing').checked;
    relayout();          // four fields' worth of height, appearing
  }
  // How the current column count actually divides the chosen lists, so
  // the number means something before the widget redraws.
  const note = $('columns-note');
  if (note && state) {
    const n = Math.max(1, Number($('columns').value) || 1);
    const shown = (chosenIds().length || realLists().length)
                + ($('personalised_lists').checked ? pickedViews().length : 0);
    note.textContent = shown
      ? `${shown} lists across ${n}: ` +
        Array.from({ length: n }, (_, c) =>
          Math.floor(shown / n) + (c < shown % n ? 1 : 0)).join(' / ')
      : 'No lists yet.';
  }
}

// Real Google lists only. These ids go to the fetcher as tasklist_ids,
// and a built-in view's id there would be a request for a list Google
// does not have. The views are collected by pickedViews instead.
function realLists() {
  return (state ? state.lists || [] : []).filter(l => !l.virtual);
}

function viewLists() {
  return (state ? state.lists || [] : []).filter(l => l.virtual);
}

function chosenIds() {
  return realLists()
    .filter(l => { const el = $('list_' + l.id); return el && el.checked; })
    .map(l => l.id);
}

// The views that are on: the master switch and the individual tick. The
// ids are stored bare, without the "virtual:" prefix they carry in the
// order, because nothing else shares that namespace.
// Deliberately not gated on the master switch: switching the feature
// off must not wipe which views were ticked, or ticking it back on would
// come back empty. The switch decides whether they are drawn, here and
// in the widget; this is only which ones.
function pickedViews() {
  return viewLists()
    .filter(l => { const el = $('view_' + l.id); return el && el.checked; })
    .map(l => l.id.replace(/^virtual:/, ''));
}

function setMsg(text, kind) {
  const el = $('msg');
  el.textContent = text || '';
  el.className = 'msg' + (kind ? ' ' + kind : '');
}

// --------------------------------------------------- card packing
//
// The height half of the grid described in settings.html. Widths are
// fixed in CSS (one unit, two for the Order card); heights cannot be,
// because a card's height depends on its text wrapping at the width it
// ended up with, which only the browser knows.
//
// So: measure every card at its real width, round each height up to a
// whole number of --row-unit rows, and hand the grid that span. Tallest
// first, which with `grid-auto-flow: dense` is what closes the gaps --
// the big cards claim their rows while there is still a free column
// beside them, and the short ones drop into whatever is left.
//
// Below the two-column breakpoint there is nothing to pack around, so
// binning is switched off rather than computed and ignored.
const TWO_COLUMN = window.matchMedia('(min-width: 861px)');

function panelMetrics() {
  const style = getComputedStyle(document.documentElement);
  return {
    gap: parseFloat(style.getPropertyValue('--gap')) || 14,
    unit: parseFloat(style.getPropertyValue('--row-unit')) || 4,
  };
}

function layoutPanel(panel) {
  const cards = Array.from(panel.querySelectorAll('.card'));
  if (!cards.length) return;

  if (!TWO_COLUMN.matches) {
    panel.classList.remove('binned');
    for (const card of cards) {
      card.style.removeProperty('--span');
      card.style.removeProperty('order');
      card.style.removeProperty('grid-column');
    }
    return;
  }

  // Measured with the bins off, so each card is its natural height
  // rather than the height of the bin it was last given. The column
  // widths are the same either way, so the measurement holds.
  panel.classList.remove('binned');
  const heights = cards.map(card => card.getBoundingClientRect().height);

  const { gap, unit } = panelMetrics();
  cards.forEach((card, i) => {
    // The gap rides along with every row but the last, so one row of
    // content is worth unit + gap pixels. Rounded up: a card short of
    // its bin shows a few pixels of its own background, a card over it
    // would have its last field clipped.
    const span = Math.max(1, Math.ceil((heights[i] + gap) / (unit + gap)));
    card.style.setProperty('--span', span);
  });

  // Tallest first, with two hand-placed exceptions -- see the comments
  // on the cards themselves in settings.html:
  //
  //   data-col   pinned to that column, whatever its height
  //   data-last  sorted to the end rather than by height
  //
  // `order` and not a DOM move: the markup stays in the order it reads
  // in, which is the order the tab order follows.
  cards
    .map((card, i) => ({ card, h: heights[i], last: card.hasAttribute('data-last') }))
    .sort((a, b) => (a.last - b.last) || (b.h - a.h))
    .forEach((entry, rank) => { entry.card.style.order = rank; });

  for (const card of cards) {
    const col = card.dataset.col;
    // span rather than a start/end pair, so this still says "one unit
    // wide" and the width stays the CSS's business.
    if (col) card.style.gridColumn = col + ' / span 1';
    else card.style.removeProperty('grid-column');
  }

  panel.classList.add('binned');
  evenColumnBottoms(panel, cards, gap, unit);
}

// Squares off the bottom of the grid.
//
// Dense packing has already moved everything it can by this point, so
// whatever ragged edge is left is one no card can fill: the columns ran
// out of cards, not out of room. Rather than leave a strip of page under
// the shorter column, the last card in it grows to the taller column's
// bottom -- it is going to be mostly its own padding either way, and a
// card that ends where its neighbour ends reads as deliberate.
//
// Only one-unit cards take part. A card spanning both columns cannot be
// ragged against anything, and since the only one (Order) is pinned to
// the end of its tab, ignoring them leaves exactly the band of
// side-by-side cards that can be uneven. A full-width card landing in
// the MIDDLE of a tab would split that band in two and this would even
// the halves against each other; worth knowing before pinning a second
// one somewhere else.
function evenColumnBottoms(panel, cards, gap, unit) {
  const panelRect = panel.getBoundingClientRect();
  const colWidth = (panelRect.width - gap) / 2;

  // Reading these forces the layout the spans just asked for, so the
  // positions are the packed ones rather than the previous pass's.
  const placed = cards.map(card => {
    const rect = card.getBoundingClientRect();
    return {
      card,
      bottom: rect.bottom - panelRect.top,
      wide: rect.width > colWidth + gap / 2,
      // Which column, by where the card starts. Half a column of slack,
      // so sub-pixel column widths cannot flip the answer.
      col: rect.left - panelRect.left > colWidth / 2 ? 1 : 0,
    };
  });

  const narrow = placed.filter(p => !p.wide);
  if (narrow.length < 2) return;
  const target = Math.max(...narrow.map(p => p.bottom));

  for (const col of [0, 1]) {
    const inColumn = narrow.filter(p => p.col === col);
    if (!inColumn.length) continue;

    // The bottom-most card in the column is the one with room under it.
    const last = inColumn.reduce((a, b) => (b.bottom > a.bottom ? b : a));
    // Both bottoms sit on row boundaries, so the gap between them is a
    // whole number of rows; rounding just absorbs sub-pixel error.
    const rows = Math.round((target - last.bottom) / (unit + gap));
    if (rows < 1) continue;

    const span = Number(last.card.style.getPropertyValue('--span')) || 1;
    last.card.style.setProperty('--span', span + rows);
  }
}

// Anything that changes what a card contains changes how tall it is, so
// this runs after every redraw rather than once on load. Cheap enough:
// it is one forced reflow over a dozen cards, and only for the panel
// actually on screen -- a hidden one measures zero.
// Coalesced to one pass per frame: a single load calls this from four
// different draws, and each pass costs a forced reflow.
let relayoutQueued = false;

function relayout() {
  if (relayoutQueued) return;
  relayoutQueued = true;
  requestAnimationFrame(() => {
    relayoutQueued = false;
    const panel = document.querySelector('.panel.on');
    if (panel) layoutPanel(panel);
  });
}

// Column widths change with the window, and so does every wrapped line
// inside them.
window.addEventListener('resize', relayout);
// Text measured before the real font arrives is measured at the
// fallback's metrics, which is a card or two out by a line.
if (document.fonts && document.fonts.ready) document.fonts.ready.then(relayout);

// ------------------------------------------------------------- tabs
for (const btn of document.querySelectorAll('.tab')) {
  btn.onclick = () => {
    for (const b of document.querySelectorAll('.tab')) {
      b.classList.toggle('on', b === btn);
    }
    for (const p of document.querySelectorAll('.panel')) {
      p.classList.toggle('on', p.dataset.panel === btn.dataset.tab);
    }
    syncResetButton();
    // A hidden panel has no size to measure, so a panel is packed when
    // it is shown and not before.
    relayout();
  };
}

// ------------------------------------------------- account switcher
//
// One Google account is fetched at a time: the widget's timer pulls the
// active account only, on the interval set under Fetching. Switching is
// therefore not a fetch -- it rewrites which account that timer reads
// and nothing else -- which is why the page then says "Reload
// recommended" instead of quietly going to the network. Adding an
// account is the ordinary sign-in flow; Google's account chooser is
// what picks which one gets added.

// Sentinel option value. Not an id, because an id is an email address
// and an email address cannot contain a space.
const ADD_ACCOUNT = '+ add';

// Sticky until the next successful fetch, not until the next redraw:
// load() runs on every save, and a notice that vanished because you
// changed an unrelated setting would be lost exactly when it mattered.
let switched = false;

// The account picked in the dropdown but not yet saved, or null when the
// box is showing the account the widget is actually on. A switch is a
// form value like any other now: nothing moves until Save.
let pendingAccount = null;

// How old what is on screen is, in words, for the switch notice. The
// point is to make the notice decidable: an hour old is worth a reload,
// two minutes old plainly is not, and "Reload recommended" on its own
// cannot tell you which you are looking at.
function describeAge(s) {
  if (!s.last_updated) return 'This account has not been fetched yet.';
  const mins = Math.round((Date.now() - new Date(s.last_updated)) / 60000);
  if (!isFinite(mins) || mins < 0) return '';
  if (mins < 1) return 'Fetched just now.';
  if (mins < 60) return `Last fetched ${mins} minute${mins === 1 ? '' : 's'} ago.`;
  const hrs = Math.round(mins / 60);
  if (hrs < 24) return `Last fetched ${hrs} hour${hrs === 1 ? '' : 's'} ago.`;
  const days = Math.round(hrs / 24);
  return `Last fetched ${days} day${days === 1 ? '' : 's'} ago.`;
}

function accountQuery() {
  return pendingAccount ? '?account=' + encodeURIComponent(pendingAccount) : '';
}

// Redraws only the parts of the page that belong to an account: the
// connection card, the Task lists checkboxes and the Layout order. Used
// when a switch is picked but not saved, so the settings page shows that
// account while the widget stays on the current one.
//
// Deliberately not load(): that also redraws the appearance controls
// from disk and clears the dirty flag, which would throw away unsaved
// edits on the other tabs and the switch itself.
async function loadAccountView() {
  let next;
  try {
    const res = await fetch('api/state' + accountQuery(), { cache: 'no-store' });
    if (!res.ok) throw new Error('could not read that account');
    next = await res.json();
  } catch (e) {
    setMsg(e.message, 'bad');
    return;
  }
  // A reply for an account that is no longer the pending one is a race
  // between two quick picks; drawing it would show the wrong account.
  if (next.viewing !== (pendingAccount || next.accounts.find(a => a.active)?.id)) return;

  state = next;
  order = (state.settings.tasklist_order || []).slice();
  drawConnection(state);
  drawLists(state);
  drawOrder();
  relayout();
}

function drawAccounts(s) {
  const accounts = s.accounts || [];
  const sel = $('account');
  const row = $('account-row');

  // With no account there is nothing to switch between and the Connect
  // button is the only thing to do. With one, the switcher is still
  // worth showing -- it is the only route to "Add another account".
  row.hidden = !accounts.length;
  $('remove-account').hidden = !accounts.length;
  if (!accounts.length) { $('account-flash').hidden = true; return; }

  // The pending pick wins over the saved one: load() runs after every
  // save and after a reload, and either would otherwise snap the box
  // back to the account the widget is still on and lose the choice.
  const active = accounts.find(a => a.active) || accounts[0];
  const showing = pendingAccount || active.id;
  sel.replaceChildren(...accounts.map(a => {
    const opt = document.createElement('option');
    opt.value = a.id;
    // "(current)" only while a switch is pending, where it is the one
    // thing that distinguishes the account you picked from the one the
    // widget is still on. With nothing pending it is just a word on
    // every row that is already selected.
    opt.textContent = a.label +
      (pendingAccount && a.active ? ' (current)' : '');
    opt.selected = a.id === showing;
    return opt;
  }));
  const add = document.createElement('option');
  add.value = ADD_ACCOUNT;
  add.textContent = 'Add another account...';
  sel.appendChild(add);

  // Shown while a switch is pending AND after one has been applied but
  // not yet fetched. Both are the same statement -- what the widget is
  // drawing is not this account's current tasks -- and both end at the
  // next fetch. Pending says so in the future tense.
  const flash = $('account-flash');
  flash.hidden = !(pendingAccount || switched);
  $('account-when').textContent = pendingAccount
    ? 'Save to switch. The widget will show whatever was last pulled ' +
      'for that account.'
    : 'This is whatever was last pulled for this account.';
  $('account-age').textContent = pendingAccount ? '' : describeAge(s);
  // Shown in both states, with the pending one saying what it will do:
  // it applies the switch and fetches, which is Save's account half on
  // its own, for when you want fresh tasks without saving the rest of
  // the form.
  $('account-reload').textContent = pendingAccount
    ? 'Switch and reload' : 'Reload now';
}

$('account').onchange = () => {
  const sel = $('account');
  const id = sel.value;
  const active = (state.accounts || []).find(a => a.active);

  if (id === ADD_ACCOUNT) {
    // Put the box back before the sign-in starts: it may be cancelled,
    // and a dropdown reading "Add another account..." for the next five
    // minutes is a lie about which account the widget is fetching.
    sel.value = pendingAccount || (active && active.id) || '';
    startSignIn(true);
    return;
  }

  // Nothing is applied here. The switch is part of the form now, like
  // every other control on the page: it happens in the Save handler,
  // after the settings write (so the task selection lands on the
  // account it was edited for) and before the refresh (so the fetch is
  // the new account's).
  pendingAccount = (active && id === active.id) ? null : id;
  markDirty();
  // The task lists and the order are that account's, so they follow the
  // pick immediately -- it is the widget that waits for Save, not the
  // settings page. Any unsaved tick on the previous account's lists goes
  // with it, which is the same thing as not having saved it.
  loadAccountView().then(() => drawAccounts(state));
};

// Applies the pending switch. Called by Save, between the config write
// and the refresh; see the comment in $('account').onchange.
async function applyPendingAccount() {
  if (!pendingAccount) return;
  const res = await fetch('api/account', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ id: pendingAccount }),
  });
  const out = await res.json();
  if (!res.ok || !out.ok) throw new Error(out.error || 'could not switch account');
  pendingAccount = null;
  switched = true;
}

$('remove-account').onclick = async () => {
  const accounts = state.accounts || [];
  const active = accounts.find(a => a.active) || accounts[0];
  // Whatever the dropdown is showing, including a pending pick: the
  // button sits next to it and "remove" plainly means the one on
  // screen, not the one the widget happens to be fetching.
  const id = $('account').value;
  const target = accounts.find(a => a.id === id) || active;
  if (!target) return;

  // Immediate and irreversible, so it asks. The sign-in itself is not
  // revoked -- that is Google's own permissions page -- and saying so
  // is the difference between this looking destructive and looking
  // broken when the account signs back in with its old selection gone.
  const last = accounts.length === 1;
  const ok = confirm(
    [`Remove ${target.label}?`,
     'DesktopTasks forgets its sign-in, its task-list selection and its ' +
     'saved tasks. ' +
     (last ? 'It is your only account, so the widget will have nothing to '
           + 'show until you connect one again.'
           : 'The widget switches to your other account.'),
     'You can add it back at any time by signing in again.',
    ].join('\n\n')
  );
  if (!ok) return;

  setMsg('Removing account...');
  try {
    const res = await fetch('api/account', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ id: target.id, action: 'remove' }),
    });
    const out = await res.json();
    if (!res.ok || !out.ok) throw new Error(out.error || 'could not remove');
    pendingAccount = null;
    switched = false;
    await load();
    setMsg(`Removed ${target.label}.`, 'ok');
  } catch (e) {
    setMsg(e.message === 'Failed to fetch'
             ? 'Could not reach the widget.' : e.message, 'bad');
    await load();
  }
};

$('account-reload').onclick = async () => {
  $('account-reload').disabled = true;
  setMsg(pendingAccount ? 'Switching and fetching...'
                        : 'Fetching this account’s tasks...');
  try {
    // The switch first, so the fetch below is the account you picked.
    // This is the one way an account change applies without Save, and
    // it is explicit: the button says so.
    await applyPendingAccount();
    const res = await fetch('refresh', { method: 'POST' });
    if (!res.ok) throw new Error('the fetch failed');
    switched = false;
    await load();
    setMsg('Tasks reloaded.', 'ok');
  } catch (e) {
    setMsg('Could not reload. ' + e.message, 'bad');
  }
  $('account-reload').disabled = false;
};

// ---------------------------------------------------------- drawing
function drawConnection(s) {
  const dot = $('conn-dot');
  const txt = $('conn-txt');
  const notice = $('conn-notice');

  // An AUTH_EXPIRED error outranks "connected": a refresh token can be
  // present and no longer work, which is exactly the state the weekly
  // reconnect exists for. Reading only `connected` would say everything
  // is fine while the widget shows stale tasks.
  const expired = (s.errors || []).some(e => e.error_code === 'AUTH_EXPIRED');

  if (expired) {
    dot.className = 'dot bad';
    txt.textContent = 'Sign-in expired';
  } else if (s.connected) {
    dot.className = 'dot ok';
    txt.textContent = 'Connected';
  } else {
    dot.className = 'dot warn';
    txt.textContent = 'Not connected';
  }

  const other = (s.errors || []).filter(e => e.error_code !== 'AUTH_EXPIRED');
  if (expired || other.length) {
    notice.hidden = false;
    notice.textContent = expired
      ? 'Google expired this sign-in. Reconnect to start fetching again; the widget is still showing the last tasks it fetched.'
      : other[0].error_message;
  } else {
    notice.hidden = true;
  }

  $('connect').textContent = s.connected ? 'Reconnect Google' : 'Connect Google';
  // Only with an account attached. Keyed off `connected` rather than off
  // `expired`: an expired token still means there is a Google account
  // whose tasks you might want to go and edit, and tasks.google.com will
  // ask you to sign in itself if it has to.
  $('edit-tasks').hidden = !s.connected;
  drawAccounts(s);
  relayout();            // the notice is a card taller when it is shown
}

function drawLists(s) {
  const box = $('lists');
  // An empty selection means every list, so every box is ticked. Showing
  // them all unticked was the old behaviour and it was actively
  // misleading: unticking a list that already looked unticked did
  // nothing, and saving wrote the same empty list straight back.
  const ids = s.settings.tasklist_ids || [];
  const lists = (s.lists || []).filter(l => !l.virtual);
  const chosen = ids.length ? new Set(ids) : new Set(lists.map(l => l.id));

  drawViews(s);

  if (!lists.length) {
    box.replaceChildren(Object.assign(document.createElement('div'), {
      className: 'empty',
      // Not an error. Before the first successful fetch there is simply
      // nothing to list yet.
      textContent: s.connected
        ? 'No lists fetched yet. Use Reload below.'
        : 'Connect your Google account to see your lists.',
    }));
    relayout();
    return;
  }

  box.replaceChildren(...lists.map(list => {
    const row = document.createElement('div');
    row.className = 'lrow';

    const cb = document.createElement('input');
    cb.type = 'checkbox';
    cb.id = 'list_' + list.id;
    cb.checked = chosen.has(list.id);
    // drawOrder as well, so the Layout tab's copy of this list fades or
    // un-fades with the tick rather than waiting for the next load().
    cb.onchange = () => { markDirty(); refreshReadouts(); drawOrder(); };

    const label = document.createElement('label');
    label.htmlFor = cb.id;
    // textContent, not innerHTML: a list title is text the user typed.
    label.textContent = list.title;

    const n = document.createElement('span');
    n.className = 'n';
    // Every list is fetched now, including the unticked ones -- the
    // personalised lists read across all of them -- so the count is
    // real either way and worth printing. Whether the list gets a card
    // of its own is what the tick says, and the Order card is where
    // that is spelled out.
    n.textContent = list.count === 1 ? '1 task' : list.count + ' tasks';

    row.append(cb, label, n);
    return row;
  }));
  relayout();            // one row per list, so the card's height is data
}

// The built-in views, under their own heading in the same card. Ticking
// one is not a fetch setting -- nothing new is downloaded -- so these go
// to personalised_ids rather than to tasklist_ids.
function drawViews(s) {
  const box = $('views');
  const on = s.settings.personalised_lists !== false;
  const picked = new Set(s.settings.personalised_ids || []);
  box.classList.toggle('off', !on);

  box.replaceChildren(...(s.lists || []).filter(l => l.virtual).map(view => {
    const bare = view.id.replace(/^virtual:/, '');
    const row = document.createElement('div');
    row.className = 'lrow';

    const cb = document.createElement('input');
    cb.type = 'checkbox';
    cb.id = 'view_' + view.id;
    cb.checked = picked.has(bare);
    cb.onchange = () => { markDirty(); refreshReadouts(); drawOrder(); };

    const label = document.createElement('label');
    label.htmlFor = cb.id;
    // textContent for the same reason the real lists use it: the title
    // may have been renamed around a list the user named.
    label.textContent = view.title;

    const n = document.createElement('span');
    n.className = 'n';
    n.textContent = view.count === 1 ? '1 task' : view.count + ' tasks';

    row.append(cb, label, n);
    return row;
  }));
}

function drawOrder() {
  const box = $('order');
  const byId = new Map((state.lists || []).map(l => [l.id, l]));
  // Anything ordered but no longer present is dropped; anything present
  // but unordered goes on the end, so a newly created list appears rather
  // than vanishing.
  order = order.filter(id => byId.has(id));
  for (const l of state.lists || []) if (!order.includes(l.id)) order.push(l.id);

  if (!order.length) {
    box.replaceChildren(Object.assign(document.createElement('div'),
      { className: 'empty', textContent: 'No lists to order yet.' }));
    relayout();
    return;
  }

  const columns = Math.max(1, Number($('columns').value) || 1);

  // Read live off the Account tab's checkboxes rather than off the saved
  // tasklist_ids, so unticking a list fades it here immediately instead of
  // after a save. A list with no checkbox yet counts as shown, which is
  // also what an untouched, never-narrowed selection means.
  const master = $('personalised_lists').checked;
  const shown = new Set((state.lists || [])
    .filter(l => {
      // A view is shown when the master switch and its own tick are both
      // on. A real list is shown unless its box is there and unticked.
      if (l.virtual) {
        const el = $('view_' + l.id);
        return master && el && el.checked;
      }
      const el = $('list_' + l.id);
      return !el || el.checked;
    })
    .map(l => l.id));
  // Column positions are counted over the shown lists only, because the
  // widget never deals an unticked list into a column. Counting the faded
  // rows too would print a column number that the widget disagrees with.
  let slot = 0;

  box.replaceChildren(...order.map((id, i) => {
    const list = byId.get(id);
    const on = shown.has(id);
    const row = document.createElement('div');
    row.className = on ? 'orow' : 'orow off';
    row.draggable = true;
    row.dataset.id = id;

    const grip = document.createElement('span');
    grip.className = 'grip';
    grip.textContent = '::';

    const name = document.createElement('span');
    name.className = 'name';
    name.textContent = list.title;

    // Which column this position lands in, by the same modulus the
    // widget uses. Shown because the mapping is not obvious from a
    // vertical list. An unticked list lands in no column, so it gets a
    // badge saying why instead -- the same treatment DesktopCards gives a
    // hidden account.
    const col = document.createElement('span');
    if (on) {
      col.className = 'col';
      col.textContent = columns > 1 ? 'col ' + (slot++ % columns + 1) : '';
    } else {
      col.className = 'why';
      col.textContent = 'Not shown';
    }

    const up = document.createElement('button');
    up.className = 'mv'; up.type = 'button'; up.textContent = '\u2191';
    up.title = 'Move up';
    up.disabled = i === 0;
    up.onclick = () => { move(i, i - 1); };

    const down = document.createElement('button');
    down.className = 'mv'; down.type = 'button'; down.textContent = '\u2193';
    down.title = 'Move down';
    down.disabled = i === order.length - 1;
    down.onclick = () => { move(i, i + 1); };

    row.append(grip, name, col, up, down);
    wireDrag(row);
    return row;
  }));
  relayout();
}

function move(from, to) {
  if (to < 0 || to >= order.length) return;
  order.splice(to, 0, order.splice(from, 1)[0]);
  markDirty();
  drawOrder();
  refreshReadouts();
}

// HTML5 drag and drop. Enough for a short vertical list, and it needs no
// pointer-event bookkeeping of its own.
let dragId = null;

function wireDrag(row) {
  row.ondragstart = e => {
    dragId = row.dataset.id;
    row.classList.add('drag');
    e.dataTransfer.effectAllowed = 'move';
    // Firefox refuses to start a drag without data set.
    e.dataTransfer.setData('text/plain', dragId);
  };
  row.ondragend = () => {
    dragId = null;
    for (const r of document.querySelectorAll('.orow')) {
      r.classList.remove('drag', 'over');
    }
  };
  row.ondragover = e => {
    if (dragId === null || row.dataset.id === dragId) return;
    e.preventDefault();
    row.classList.add('over');
  };
  row.ondragleave = () => row.classList.remove('over');
  row.ondrop = e => {
    e.preventDefault();
    row.classList.remove('over');
    if (dragId === null) return;
    const from = order.indexOf(dragId);
    const to = order.indexOf(row.dataset.id);
    if (from >= 0 && to >= 0 && from !== to) move(from, to);
  };
}

function drawSettings(s) {
  const st = s.settings;
  const win = st.window || {};

  for (const name of TOGGLES) $(name).checked = !!st[name];
  for (const name of NUMBERS) $(name).value = st[name];
  for (const name of FLOATS) $(name).value = st[name];
  const sideValues = st.spacing_sides || {};
  for (const [id, key] of Object.entries(SIDES)) $(id).value = sideValues[key] || 0;
  for (const [key, id] of Object.entries(WIN_TOGGLES)) $(id).checked = !!win[key];
  for (const [key, id] of Object.entries(WIN_NUMBERS)) $(id).value = win[key];

  // The colour input has no empty state, so a null accent is shown as the
  // Windows default and the hint carries the distinction instead.
  $('accent_color').value = win.accent || '#0078d4';
  updateAccentHint(win.accent);

  document.documentElement.dataset.theme = win.dark_theme ? 'dark' : 'light';
  refreshReadouts();
}

// ------------------------------------------------ Windows shortcuts
// Not part of collect(): these three are .lnk files, not config.json
// keys, so they have their own endpoint and their own save step. The
// ticks still only mean something on Save, like everything else here.
const SHORTCUTS = { startup: 'sc_startup', start_menu: 'sc_start_menu',
                    desktop: 'sc_desktop' };

// What the server last told us is actually on disk, which is what a
// pending tick is compared against.
let shortcutState = { available: false, startup: false, start_menu: false,
                      desktop: false, dirs: {} };

function drawShortcuts(s) {
  shortcutState = s.shortcuts || shortcutState;
  const dirs = shortcutState.dirs || {};
  for (const [key, id] of Object.entries(SHORTCUTS)) {
    $(id).checked = !!shortcutState[key];
    // Nothing to tick if the calls that write a .lnk are not there.
    $(id).disabled = !shortcutState.available;
    const where = $(id + '_dir');
    if (where) where.textContent = dirs[key] || '';
  }
  $('sc_unavailable').hidden = !!shortcutState.available;
  $('sc_redo').disabled = !shortcutState.available;
}

// The one place shortcuts are written. Throws, so the caller decides
// whether a failure is the whole message or half of one.
async function writeShortcuts() {
  const res = await fetch('api/shortcuts', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(shortcutsWanted()),
  });
  const out = await res.json().catch(() => ({}));
  if (!res.ok || !out.ok) throw new Error(out.error || 'could not write the shortcuts');
}

function shortcutsWanted() {
  return Object.fromEntries(
    Object.entries(SHORTCUTS).map(([key, id]) => [key, $(id).checked]));
}

// Only when a tick actually moved. Writing three shortcuts is not work a
// Save that changed a colour should be doing.
function shortcutsChanged() {
  if (!shortcutState.available) return false;
  const want = shortcutsWanted();
  return Object.keys(SHORTCUTS).some(key => want[key] !== !!shortcutState[key]);
}

// Save is the only other way these are written. Nothing here acts on a
// tick as it is clicked, so a stray click is still undone by leaving the
// page alone.
$('sc_redo').onclick = async () => {
  const btn = $('sc_redo');
  btn.disabled = true;
  setMsg('Writing shortcuts...');
  try {
    await writeShortcuts();
    setMsg('Shortcuts updated.', 'ok');
  } catch (e) {
    setMsg(e.message === 'Failed to fetch'
             ? 'Could not reach the widget.' : e.message, 'bad');
  }
  // Back to what is really on disk, which is also what makes the next
  // Save see the ticks as unchanged. Only the one card is redrawn: a
  // full load() here would throw away pending edits elsewhere on the
  // tab, which this button never asked to touch.
  await refreshShortcuts();
  // Explicitly, not only through drawShortcuts: a read that failed
  // leaves the card untouched, and a button stuck disabled would be the
  // one state with no way out of it.
  btn.disabled = !shortcutState.available;
};

// Re-reads just the shortcut half of the state. Quietly leaves the card
// as it is if the read fails, since the message already says what
// happened.
async function refreshShortcuts() {
  try {
    const res = await fetch('api/state' + accountQuery(), { cache: 'no-store' });
    if (!res.ok) return;
    drawShortcuts(await res.json());
  } catch (e) { /* the card keeps what it has */ }
}

function updateAccentHint(accent) {
  const clear = $('accent_clear');
  clear.disabled = !accent;
  clear.textContent = accent ? 'Use Windows' : 'Using Windows';
}

// ---------------------------------------------------------- reading
function collect() {
  const patch = { window: {} };
  for (const name of TOGGLES) patch[name] = $(name).checked;
  for (const name of NUMBERS) patch[name] = Math.round(Number($(name).value));
  for (const name of FLOATS) patch[name] = Number($(name).value);
  patch.spacing_sides = Object.fromEntries(
    Object.entries(SIDES).map(([id, key]) => [key, Math.round(Number($(id).value) || 0)]));
  patch.tasklist_order = order.slice();
  for (const [key, id] of Object.entries(WIN_TOGGLES)) patch.window[key] = $(id).checked;
  for (const [key, id] of Object.entries(WIN_NUMBERS)) patch.window[key] = Number($(id).value);

  patch.window.accent = accentValue;

  // All ticked is saved as an empty list, which is what the fetcher reads
  // as "every list". It also means a list created later shows up on its
  // own instead of being silently excluded by a stale selection.
  const picked = chosenIds();
  patch.tasklist_ids = picked.length === realLists().length ? [] : picked;
  // The views are stored as an explicit list, with no "empty means all"
  // shorthand: none ticked is a real choice here, and the master switch
  // is what means "all of this off".
  patch.personalised_ids = pickedViews();

  return patch;
}

// Held separately because an <input type=color> cannot represent "none",
// and clearing it is a button rather than a value.
let accentValue = null;

$('accent_color').oninput = () => { accentValue = $('accent_color').value; updateAccentHint(accentValue); markDirty(); };
$('accent_clear').onclick = () => { accentValue = null; updateAccentHint(null); markDirty(); };

for (const name of [...TOGGLES, ...NUMBERS, ...FLOATS, ...Object.keys(SIDES)]) {
  $(name).onchange = markDirty;
}
// The custom-spacing switch shows and hides the four boxes, so it has to
// redraw as well as mark dirty.
$('custom_spacing').onchange = () => { markDirty(); refreshReadouts(); };

// The master switch fades its own rows and takes every view out of the
// Order, so it redraws both.
$('personalised_lists').onchange = () => {
  markDirty();
  $('views').classList.toggle('off', !$('personalised_lists').checked);
  refreshReadouts();
  drawOrder();
};

// Sliders update their readout while being dragged, not only on release.
for (const id of Object.keys(SLIDERS)) {
  $(id).oninput = () => { afterSlider(id); markDirty(); };

  // And the box drives the slider. input, not change, so the widget
  // preview keeps up with typing the way dragging does; clamping waits
  // for blur, because clamping mid-type makes "5" out of a "50" whose
  // minimum is 10.
  const box = $(id + '-num');
  if (!box) continue;
  box.oninput = () => { syncFromBox(id, false); markDirty(); };
  box.onchange = () => { syncFromBox(id, true); markDirty(); };
}

// Everything that follows a slider move, whichever control caused it.
function afterSlider(id) {
  refreshReadouts();
  if (id === 'columns') drawOrder();
}

// Writes the box's value into the slider. A slider silently clamps
// anything out of range, which is the behaviour wanted here -- but only
// once typing has finished, so `snap` says whether to write the clamped
// value back into the box.
function syncFromBox(id, snap) {
  const box = $(id + '-num');
  if (box.value === '') return;      // mid-edit, nothing to apply yet
  const n = SLIDERS[id].fromBox(box.value);
  if (!Number.isFinite(n)) return;
  $(id).value = n;
  if (snap) box.value = SLIDERS[id].toBox($(id).value);
  afterSlider(id);
}
for (const id of [...Object.values(WIN_TOGGLES), ...Object.values(WIN_NUMBERS)]) $(id).onchange = markDirty;
for (const id of Object.values(SHORTCUTS)) $(id).onchange = markDirty;

// ----------------------------------------------------------- actions
async function load() {
  try {
    // The pending account, if one is picked: the page describes the
    // account you are about to switch to, while the widget carries on
    // with the one you are still on.
    const res = await fetch('api/state' + accountQuery(), { cache: 'no-store' });
    if (!res.ok) throw new Error('could not read settings');
    state = await res.json();
  } catch (e) {
    setMsg('Could not reach the widget. Is it running?', 'bad');
    return;
  }
  accentValue = (state.settings.window || {}).accent || null;
  order = (state.settings.tasklist_order || []).slice();
  drawConnection(state);
  drawLists(state);
  drawSettings(state);
  drawShortcuts(state);
  drawOrder();
  dirty = false;
  $('save').disabled = true;
  relayout();
}

$('save').onclick = async () => {
  $('save').disabled = true;
  setMsg('Saving...');
  try {
    // The switch goes FIRST, because the Task lists and Order cards are
    // already showing the pending account -- the selection about to be
    // written is that account's, so that account has to be the active
    // one before apply_settings folds it onto an account entry.
    await applyPendingAccount();

    const res = await fetch('api/config', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(collect()),
    });
    const out = await res.json();
    if (!res.ok || !out.ok) throw new Error(out.error || 'save failed');
    dirty = false;

    // After the settings, and never instead of them: a shortcut that
    // will not write should not cost someone the save they came for.
    // The message says which half failed, and the state reload below
    // puts the ticks back to what is really on disk.
    if (shortcutsChanged()) {
      setMsg('Saved. Writing shortcuts...');
      try {
        await writeShortcuts();
      } catch (e) {
        setMsg('Settings saved, but the shortcuts failed: ' + e.message, 'bad');
        await load();
        return;
      }
    }

    // Refetch straight away. Which lists are fetched is itself a setting,
    // so saving a new selection and leaving tasks.json alone would leave
    // the widget drawing lists that are no longer chosen until something
    // else happened to refresh. That looked exactly like the setting not
    // working.
    setMsg('Saved. Refreshing the widget...');
    try {
      await fetch('refresh', { method: 'POST' });
      // That fetch used the active account -- the newly switched one if
      // this save switched -- so what the widget shows is now current,
      // which is the condition the reload notice was waiting on. Left
      // standing if the fetch throws, because it would then be true.
      switched = false;
    } catch (e) {
      // The save landed, which is the part that matters.
    }
    setMsg('Saved.', 'ok');
    await load();
  } catch (e) {
    setMsg(e.message, 'bad');
    $('save').disabled = false;
  }
};

// Reloading is no longer a button: every Save reloads the widget, which
// is what the button was mostly used for. What a save cannot do is pick
// up a change that only takes effect at launch -- the window position and
// corner radius -- so the button that remains is the stronger one.
$('restart').onclick = async () => {
  setMsg('Restarting the widget...');
  try {
    const res = await fetch('restart', { method: 'POST' });
    const out = await res.json().catch(() => ({}));
    if (!res.ok || !out.ok) throw new Error(out.error || 'could not restart');
    // The restart tears down the server that just answered, so the new
    // one needs a moment to bind the port before load() can reach it.
    setMsg('Restarting...');
    setTimeout(() => load().then(() => setMsg('Widget restarted.', 'ok')), 2500);
  } catch (e) {
    setMsg(e.message === 'Failed to fetch'
             ? 'Could not reach the widget.' : e.message, 'bad');
  }
};

// ------------------------------------------------- reset to default
// Appearance only, and only the controls on that tab. Resetting the
// account or the task selection from a button labelled "Reset to
// default" would be a nasty surprise, so this list is written out by
// hand rather than derived from everything the page can write.
const APPEARANCE_DEFAULTS = {
  scale: 1.0,
  spacing: 0,
  custom_spacing: false,
  spacing_left: 0, spacing_top: 0, spacing_right: 0, spacing_bottom: 0,
  column_width: 325,
  max_height: 0,
  opacity: 1.0,
  translucent_background: false,
  corner_radius: 16,
  dark_theme: true,
  survive_show_desktop: true,
};

// Only on Appearance. Hidden rather than disabled: a button that cannot
// do anything on this tab is better not shown at all.
function syncResetButton() {
  const panel = document.querySelector('.panel.on');
  $('reset').hidden = !panel || panel.dataset.panel !== 'appearance';
}

$('reset').onclick = () => {
  for (const [id, value] of Object.entries(APPEARANCE_DEFAULTS)) {
    const el = $(id);
    if (!el) continue;
    if (el.type === 'checkbox') el.checked = value;
    else el.value = value;
  }
  // The accent is not in the table above because "default" for it is the
  // Windows accent, which is null rather than a colour the picker holds.
  accentValue = null;
  updateAccentHint(null);
  // Position is left alone on purpose: it is where the user dragged the
  // widget to, not part of its look.
  refreshReadouts();
  markDirty();
  setMsg('Appearance reset. Save to apply.');
};

// add=true tells the widget this sign-in is meant to attach a second
// account rather than renew the current one. The two look identical from
// Google's side, and only the page knows which button was pressed.
async function startSignIn(add) {
  $('connect').disabled = true;
  setMsg(add ? 'Pick the account to add in the new tab.'
             : 'Opening Google sign-in. Finish it in the new tab.');
  try {
    const res = await fetch('api/connect', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ add: !!add }),
    });
    const out = await res.json();
    if (!res.ok || !out.ok) throw new Error(out.error || 'could not start sign-in');
    pollForConnection();
  } catch (e) {
    setMsg(e.message, 'bad');
    $('connect').disabled = false;
  }
}

$('connect').onclick = () => startSignIn(false);

// The sign-in finishes in another tab, so there is no callback to wait
// on. Poll /api/state until the widget reports a working connection, or
// give up well after the flow's own timeout so a cancelled sign-in does
// not leave the button disabled forever.
function pollForConnection() {
  const deadline = Date.now() + 6 * 60 * 1000;
  const tick = setInterval(async () => {
    try {
      const res = await fetch('api/state', { cache: 'no-store' });
      const s = await res.json();
      const status = s.connect || {};

      // The widget reports the outcome through /api/state rather than
      // putting a dialog on screen, because a sign-in started in a
      // browser tab should answer in that tab.
      if (status.state === 'ok') {
        clearInterval(tick);
        $('connect').disabled = false;
        // The sign-in ends by fetching, and the account it signed into
        // is the active one, so there is nothing stale left to warn
        // about even if the sign-in was reached from "Add account".
        switched = false;
        setMsg(status.message || 'Connected.', 'ok');
        await load();
        return;
      }
      if (status.state === 'failed') {
        clearInterval(tick);
        $('connect').disabled = false;
        setMsg(status.message || 'Sign-in did not finish.', 'bad');
        await load();
        return;
      }
    } catch (e) {
      // The widget may be busy mid-fetch. Keep waiting.
    }
    if (Date.now() > deadline) {
      clearInterval(tick);
      $('connect').disabled = false;
      setMsg('Sign-in did not finish. Try again.', 'bad');
    }
  }, 1500);
}

// A dirty form plus a closed tab is a silently lost edit.
window.addEventListener('beforeunload', e => {
  if (!dirty) return;
  e.preventDefault();
  e.returnValue = '';
});

syncResetButton();
// Packed once before the first fetch too: if the widget cannot be
// reached, the page still has to lay itself out around the error.
relayout();
load();
