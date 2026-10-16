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
                 'translucent_background', 'custom_spacing'];
const NUMBERS = ['fetch_interval_minutes', 'columns', 'max_tasks', 'spacing'];
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
    const shown = chosenIds().length || (state.lists || []).length;
    note.textContent = shown
      ? `${shown} lists across ${n}: ` +
        Array.from({ length: n }, (_, c) =>
          Math.floor(shown / n) + (c < shown % n ? 1 : 0)).join(' / ')
      : 'No lists yet.';
  }
}

function chosenIds() {
  return (state ? state.lists || [] : [])
    .filter(l => { const el = $('list_' + l.id); return el && el.checked; })
    .map(l => l.id);
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
    // A hidden panel has no size to measure, so a panel is packed when
    // it is shown and not before.
    relayout();
  };
}

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
      ? 'Google expired this sign-in. Reconnect to start fetching again. The widget is still showing the last tasks it fetched.'
      : other[0].error_message;
  } else {
    notice.hidden = true;
  }

  $('connect').textContent = s.connected ? 'Reconnect Google' : 'Connect Google';
  relayout();            // the notice is a card taller when it is shown
}

function drawLists(s) {
  const box = $('lists');
  // An empty selection means every list, so every box is ticked. Showing
  // them all unticked was the old behaviour and it was actively
  // misleading: unticking a list that already looked unticked did
  // nothing, and saving wrote the same empty list straight back.
  const ids = s.settings.tasklist_ids || [];
  const lists = s.lists || [];
  const chosen = ids.length ? new Set(ids) : new Set(lists.map(l => l.id));

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
    cb.onchange = () => { markDirty(); refreshReadouts(); };

    const label = document.createElement('label');
    label.htmlFor = cb.id;
    // textContent, not innerHTML: a list title is text the user typed.
    label.textContent = list.title;

    const n = document.createElement('span');
    n.className = 'n';
    // An unticked list has no tasks fetched for it, so its count is 0 and
    // printing "0 tasks" would read as an empty list rather than an
    // unfetched one.
    n.textContent = list.selected === false
      ? 'Not shown'
      : list.count === 1 ? '1 task' : list.count + ' tasks';

    row.append(cb, label, n);
    return row;
  }));
  relayout();            // one row per list, so the card's height is data
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

  box.replaceChildren(...order.map((id, i) => {
    const list = byId.get(id);
    const row = document.createElement('div');
    row.className = 'orow';
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
    // vertical list.
    const col = document.createElement('span');
    col.className = 'col';
    col.textContent = columns > 1 ? 'col ' + (i % columns + 1) : '';

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
  patch.tasklist_ids = picked.length === (state.lists || []).length ? [] : picked;

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

// ----------------------------------------------------------- actions
async function load() {
  try {
    const res = await fetch('api/state', { cache: 'no-store' });
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
  drawOrder();
  dirty = false;
  $('save').disabled = true;
  relayout();
}

$('save').onclick = async () => {
  $('save').disabled = true;
  setMsg('Saving...');
  try {
    const res = await fetch('api/config', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(collect()),
    });
    const out = await res.json();
    if (!res.ok || !out.ok) throw new Error(out.error || 'save failed');
    dirty = false;

    // Refetch straight away. Which lists are fetched is itself a setting,
    // so saving a new selection and leaving tasks.json alone would leave
    // the widget drawing lists that are no longer chosen until something
    // else happened to refresh. That looked exactly like the setting not
    // working.
    setMsg('Saved. Refreshing the widget...');
    try {
      await fetch('refresh', { method: 'POST' });
    } catch (e) {
      // The save landed, which is the part that matters.
    }
    setMsg('Saved.', 'ok');
    await // Packed once before the first fetch too: if the widget cannot be
// reached, the page still has to lay itself out around the error.
relayout();
load();
  } catch (e) {
    setMsg(e.message, 'bad');
    $('save').disabled = false;
  }
};

$('reload').onclick = async () => {
  setMsg('Reloading...');
  try {
    // The same endpoint the tray's Reload uses, so there is one path.
    const res = await fetch('refresh', { method: 'POST' });
    setMsg(res.ok ? 'Widget reloaded.' : 'Reloaded, but the fetch failed.',
           res.ok ? 'ok' : 'bad');
  } catch (e) {
    setMsg('Could not reach the widget.', 'bad');
  }
  await // Packed once before the first fetch too: if the widget cannot be
// reached, the page still has to lay itself out around the error.
relayout();
load();
};

$('connect').onclick = async () => {
  $('connect').disabled = true;
  setMsg('Opening Google sign-in. Finish it in the new tab.');
  try {
    const res = await fetch('api/connect', { method: 'POST' });
    const out = await res.json();
    if (!res.ok || !out.ok) throw new Error(out.error || 'could not start sign-in');
    pollForConnection();
  } catch (e) {
    setMsg(e.message, 'bad');
    $('connect').disabled = false;
  }
};

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
        setMsg(status.message || 'Connected.', 'ok');
        await // Packed once before the first fetch too: if the widget cannot be
// reached, the page still has to lay itself out around the error.
relayout();
load();
        return;
      }
      if (status.state === 'failed') {
        clearInterval(tick);
        $('connect').disabled = false;
        setMsg(status.message || 'Sign-in did not finish.', 'bad');
        await // Packed once before the first fetch too: if the widget cannot be
// reached, the page still has to lay itself out around the error.
relayout();
load();
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

// Packed once before the first fetch too: if the widget cannot be
// reached, the page still has to lay itself out around the error.
relayout();
load();
