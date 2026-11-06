r"""
appearance.json: everything about how the widget looks.

DesktopCards keeps its look-and-feel in a file of its own, and this is the
same split. config.json is the account file -- the Google refresh token,
the OAuth client, which lists are fetched and how often, and where the
window sits. appearance.json is the one you can open, read top to bottom
and edit by hand without ever seeing a secret.

Two things follow from that split, and they are the reason it is worth
doing:

  * A colour is a file-only setting. The `colors` block below overrides
    the widget's palette token by token, and it is deliberately not on
    the settings page: a full palette editor is a lot of UI for something
    most people never touch, and the page would then need to round-trip
    twelve colours it has no opinion about. The widget reads it through
    /settings.json; /api/state, which is what the settings page reads,
    never mentions it.

  * Nothing else had to change. Rather than teach every caller about a
    second file, `merge_into` folds appearance.json back over the config
    dict in memory -- top-level keys at the top level, and the four
    window-ish ones into the "window" block where they have always been
    read from. So widget.py still asks for config["scale"] and
    win["dark_theme"] and gets the right answer.

Writes go the other way: `split` sorts an incoming settings patch into
the half that belongs in each file, and serve.apply_settings writes each
half to its own place.

The migration is one-way and automatic. The first time appearance.json is
missing, the values are lifted out of config.json, written here, and
removed from there. An older config.json therefore keeps working, and a
newer one never carries two copies of the same setting.
"""

import json
import os

from paths import APPEARANCE_PATH, CONFIG_PATH, DATA_DIR

# The look-and-feel keys that sit at config.json's top level today. Each
# one moves to appearance.json's top level unchanged.
TOP_KEYS = (
    "columns",
    "column_width",
    "max_height",
    "max_tasks",
    "scale",
    "spacing",
    "custom_spacing",
    "spacing_sides",
    "opacity",
    "translucent_background",
    "show_notes",
    "group_by_list",
)

# The look-and-feel keys that live inside config.json's "window" block.
# They move to appearance.json's TOP level -- flat, the way DesktopCards
# writes them -- and merge_into puts them back into "window" in memory, so
# every existing reader is unaffected. The rest of that block (x, y) is
# the window's position on screen, which is not appearance and stays in
# config.json.
WINDOW_KEYS = (
    "dark_theme",
    "accent",
    "corner_radius",
    "survive_show_desktop",
)

# The widget's palette, as the raw tokens dashboard.html declares them,
# minus the "--" and the "-raw". Anything named here can be overridden per
# theme in appearance.json's "colors" block; anything left out keeps the
# value below. These ARE the defaults -- the stylesheet carries the same
# numbers so the page still renders correctly before any JSON is read, and
# the two must be kept in step.
#
# accent is not in here on purpose. It is already a setting of its own,
# the one colour the settings page offers, and giving it a second home
# would mean two places to look when it comes out wrong.
DEFAULT_COLORS = {
    "light": {
        "surface-0": "#f3f4f6",       # the page itself
        "surface-1": "#ffffff",       # a list card
        "surface-2": "#e5e7eb",       # dividers, the task ring
        "text-primary": "#1f2937",    # task titles
        "text-secondary": "#374151",  # the "Tasks" heading
        "text-muted": "#6b7280",      # list titles, notes
        "text-faint": "#9ca3af",      # the clock, due dates
        "error": "#ef4444",
        "error-surface": "#fef2f2",
        "overdue": "#dc2626",
        "today": "#b45309",
    },
    "dark": {
        "surface-0": "#1d2128",
        "surface-1": "#292e37",
        "surface-2": "#3e4651",
        "text-primary": "#f2f4f7",
        "text-secondary": "#d5dbe3",
        "text-muted": "#a2abb8",
        "text-faint": "#7a8391",
        "error": "#fa8585",
        "error-surface": "#43282d",
        "overdue": "#f87171",
        "today": "#fbbf24",
    },
}


# The widget's spacing and text metrics. Like `colors`, this block is
# file-only: there is no control for any of it on the settings page, and
# /api/state does not carry it. Every value is in real CSS pixels except
# task_font_scale, which is a multiplier on the task title and its note.
#
# These are the defaults, and dashboard.html carries the same numbers so
# the page is correct before any JSON arrives. Keep the two in step.
DEFAULT_METRICS = {
    # Every piece of text in the widget, as a multiplier. Distinct from
    # "scale" on the settings page, which is a zoom: that one grows the
    # cards, the column and the spacing along with the text. This grows
    # only the text, inside a card and a column that stay exactly where
    # they were.
    "font_scale": 1.0,
    # Task title and note size, as a fraction of the body size. Below 1
    # the two shrink together: they are one block of text to read, and
    # scaling only the title would just make the note look wrong.
    "task_font_scale": 0.95,
    # How far a task sits from the card's left wall. The card's own
    # padding, so the list title moves with it -- a title that stayed put
    # while the tasks stepped right would read as a misalignment rather
    # than as an indent.
    "task_indent": 24,
    # Space between one task and the next, measured wall to wall. Split
    # evenly above and below each row.
    "task_gap": 6,
    # Space between the card's top edge (or its list title) and the first
    # task.
    "task_top": 7,
}


def _read_json(path):
    try:
        with open(path, "r") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_json(path, data):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def read(migrate=True):
    """appearance.json as a dict, migrating out of config.json once.

    A missing or unreadable file is {} rather than an error: every reader
    below falls back to the same defaults it used before this file
    existed, so a corrupt appearance.json costs you your colours and not
    your widget."""
    if os.path.exists(APPEARANCE_PATH):
        return _read_json(APPEARANCE_PATH)
    if not migrate:
        return {}
    return _migrate()


def _migrate():
    """Lifts the look-and-feel keys out of config.json, once.

    Writes appearance.json first and config.json second. That order is
    deliberate: interrupted between the two, the settings exist in both
    files and the merge below still resolves them to the same values --
    whereas stripping config.json first and failing to write would lose
    them outright."""
    config = _read_json(CONFIG_PATH)
    window = config.get("window") or {}

    moved = {key: config[key] for key in TOP_KEYS if key in config}
    moved.update({key: window[key] for key in WINDOW_KEYS if key in window})
    # The palette is written out in full rather than left implicit. It is
    # the one block here with no control anywhere in the UI, so the file
    # is the only place you could discover it exists -- an empty or absent
    # "colors" would hide the feature from the only person who can use it.
    moved["colors"] = {theme: dict(tokens)
                       for theme, tokens in DEFAULT_COLORS.items()}
    moved["metrics"] = dict(DEFAULT_METRICS)
    if not os.path.exists(CONFIG_PATH):
        # Nothing to migrate from -- a first run. Leave the file unwritten
        # so the defaults stay in one place (here, and the example file)
        # rather than being frozen into a copy on disk.
        return {}

    _write_json(APPEARANCE_PATH, moved)

    for key in TOP_KEYS:
        config.pop(key, None)
    if window:
        config["window"] = {k: v for k, v in window.items()
                            if k not in WINDOW_KEYS}
    _write_json(CONFIG_PATH, config)
    return moved


def merge_into(config):
    """config with appearance.json folded over it, in memory.

    The window-ish keys go back into the "window" block, which is where
    everything in this codebase has always read them from. Returns the
    same dict it was given, mutated, because every caller passes a config
    it has just read and is about to use."""
    data = read()
    for key in TOP_KEYS:
        if key in data:
            config[key] = data[key]
    window = dict(config.get("window") or {})
    for key in WINDOW_KEYS:
        if key in data:
            window[key] = data[key]
    if window or "window" in config:
        config["window"] = window
    return config


def split(patch):
    """Sorts a settings patch into (config_patch, appearance_patch).

    The page sends one flat patch and knows nothing about the two files;
    this is the only place that decides which key goes where. A "window"
    sub-dict is split too, since dark_theme and accent arrive inside it
    while x and y stay behind."""
    to_config, to_appearance = {}, {}
    for key, value in (patch or {}).items():
        if key == "window":
            window = {}
            for wkey, wvalue in (value or {}).items():
                if wkey in WINDOW_KEYS:
                    to_appearance[wkey] = wvalue
                else:
                    window[wkey] = wvalue
            if window:
                to_config["window"] = window
        elif key in TOP_KEYS:
            to_appearance[key] = value
        else:
            to_config[key] = value
    return to_config, to_appearance


def write(patch):
    """Merges a patch into appearance.json and returns the whole file.

    Merged rather than replaced: the file holds settings the page never
    sends -- `colors` above all -- and a save from the settings page must
    not be able to delete something it does not know exists."""
    data = read()
    data.update(patch or {})
    _write_json(APPEARANCE_PATH, data)
    return data


def colors():
    """The full palette for both themes, overrides applied.

    Always both themes and always every token, so the page can write the
    lot without checking which ones were customised."""
    saved = read().get("colors") or {}
    out = {}
    for theme, defaults in DEFAULT_COLORS.items():
        merged = dict(defaults)
        override = saved.get(theme)
        if isinstance(override, dict):
            merged.update({k: v for k, v in override.items()
                           if k in defaults and isinstance(v, str)})
        out[theme] = merged
    return out


def metrics():
    """The spacing and text metrics, overrides applied.

    Numbers only, and clamped to something the page can draw: this block
    is hand-edited by definition, and a string or a negative where a
    length belongs should cost you that one value rather than the
    layout."""
    saved = read().get("metrics") or {}
    out = dict(DEFAULT_METRICS)
    for key, default in DEFAULT_METRICS.items():
        value = saved.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            continue
        out[key] = max(0.0, float(value))
    return out
