# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for DesktopTasks. Build with:

    python -m PyInstaller DesktopTasks.spec --noconfirm

A spec file rather than a long command line, because several of the
settings below need explaining and a shell invocation has nowhere to say
why.

Run build.py instead if you want the icon regenerated first, and the
oauth_client.py check -- see the note on it below, which is the one way
this build can produce a working-looking exe that nobody can sign into.

One exe, not two. DesktopCards ships the same binary twice under
different names, because its first run is a Flask setup page and the
filename is what selects it. There is nothing to select here: a first
launch brings up the widget, which says it has no tasks yet, and
connecting happens from the tray's Reconnect Google. So the name carries
no meaning and one output is enough.
"""

import os

# Every input is resolved from SPECPATH (this file's own folder, source/)
# rather than the working directory, so the build can be invoked from the
# repo root -- which is where dist/ and build/ should land.
SOURCE_DIR = SPECPATH
ROOT = os.path.dirname(SPECPATH)

# ---------------------------------------------------------------- assets
# Everything the app reads but never writes. These land next to the
# bundled Python inside the onefile archive, which paths.ASSET_DIR
# resolves to at runtime via sys._MEIPASS -- flattened to one folder,
# which is why paths.py special-cases where each of them comes from when
# running from the repo instead.
#
# config.example.json is here because a frozen first run has no repo
# folder to copy it out of; paths.EXAMPLES_DIR points at the bundle.
datas = [
    (os.path.join(SOURCE_DIR, "dashboard.html"), "."),
    (os.path.join(SOURCE_DIR, "dashboard.js"), "."),
    # The settings page, opened by the tray's Modify item. Easy to forget
    # here, and a build without it has a Modify item that 404s.
    (os.path.join(SOURCE_DIR, "settings.html"), "."),
    (os.path.join(SOURCE_DIR, "settings.js"), "."),
    (os.path.join(ROOT, "logo.png"), "."),
    (os.path.join(ROOT, "config", "config.example.json"), "."),
]

# ---------------------------------------------------------- hidden imports
# desktoptasks.py imports each mode's dependencies inside its own branch,
# which is good for startup cost but invisible to PyInstaller's static
# analysis -- a function-local `import widget` is not a module-level one it
# can follow from the entry point. Naming them here is what keeps the
# non-default subcommands from being left out of the bundle entirely.
hiddenimports = [
    "widget",
    "serve",
    "google_tasks",
    "google_tasks_setup",
    "platform_win",
    "paths",
    "net_guard",
    "logo_cache",
    # NOT optional, despite google_tasks.py importing it in a try/except.
    # That guard exists so a fresh clone (where this file is gitignored and
    # absent) still runs; it also means PyInstaller treats the import as
    # conditional, and a missing module here fails silently at runtime as
    # "no client configured" rather than as a build error. Naming it
    # explicitly is what makes the bundle carry the client that lets a
    # downloaded release sign in at all. build.py refuses to build without
    # it, for the same reason.
    "oauth_client",
    # pywebview resolves its backend by name at runtime, so the winforms
    # module and the pythonnet bridge it needs aren't reachable statically
    # either. This is the part most likely to need adjusting -- pywebview
    # failing to load its backend shows up as a blank window, not an
    # ImportError, which is why widget.explain_webview_failure exists.
    "webview.platforms.winforms",
    "clr",
]

a = Analysis(
    [os.path.join(SOURCE_DIR, "desktoptasks.py")],
    # The entry script's own folder is added automatically, which is what
    # lets `import paths` and friends resolve now that they live in source/.
    pathex=[SOURCE_DIR],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # tkinter comes with the stdlib and nothing here uses it; excluding it
    # saves several MB of Tcl/Tk that would otherwise be unpacked on every
    # launch.
    excludes=["tkinter"],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="DesktopTasks",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,  # UPX-packed exes trip antivirus heuristics far more often
    upx_exclude=[],
    runtime_tmpdir=None,
    # No console. The widget is a desktop ornament -- a console window
    # behind it would defeat the point, and it's pinned to the desktop
    # layer where it can't be focused anyway.
    #
    # This is why desktoptasks.redirect_output_to_log exists: windowed,
    # sys.stdout is None and every print() would raise on None.write. It
    # also means connecting cannot be a terminal prompt -- which is fine,
    # because the consent flow already happens in the browser and reports
    # back through a native message box.
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    # Generated by make_icon.py, at the repo root. An absolute path, not
    # one relative to os.getcwd(): the build is invoked from the root but
    # the spec must not depend on that being true.
    icon=os.path.join(ROOT, "DesktopTasks.ico"),
)
