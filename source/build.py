"""
Builds DesktopTasks.exe.

    python build.py

Regenerates the icon, checks the things that make a build useless rather
than failed, then runs PyInstaller against DesktopTasks.spec. The output
is dist/DesktopTasks.exe -- a single file with Python and every dependency
inside it, so it runs on a machine with no Python installed.

Why a script rather than just the PyInstaller command: the icon has to be
rebuilt first or a change to make_icon.py silently doesn't take effect,
and -- the real reason -- PyInstaller exits 0 on a build that nobody can
sign into. See preflight().
"""

import os
import subprocess
import sys

import make_icon
from paths import ASSET_DIR, DIST_DIR, REPO_ROOT

# The spec sits with the code it builds; the output belongs at the top of
# the checkout, because dist/ is the app rather than part of the source.
SPEC = os.path.join(ASSET_DIR, "DesktopTasks.spec")
EXE = os.path.join(DIST_DIR, "DesktopTasks.exe")

# Gitignored, and the one input whose absence PyInstaller cannot notice.
OAUTH_CLIENT = os.path.join(ASSET_DIR, "oauth_client.py")


def locked_exe():
    """Whether a running process is holding the build output open.

    PyInstaller deletes the old exe before writing the new one, so the
    file being in use turns the build into a bare PermissionError from
    deep inside somebody else's code. Checking first means saying what's
    actually wrong.

    Renaming is the test: Windows refuses it for a file that's executing,
    and it's harmless when nothing holds it."""
    if not os.path.exists(EXE):
        return False
    probe = EXE + ".locktest"
    try:
        os.rename(EXE, probe)
        os.rename(probe, EXE)
    except OSError:
        return True
    return False


def preflight():
    """Refuses builds that would succeed and then not work.

    The one that matters is oauth_client.py. It is gitignored, so a fresh
    clone does not have it, and google_tasks.py imports it in a try/except
    precisely so that a clone still runs -- a user supplies their own
    client instead. Put those two facts together and a release built on a
    machine without the file produces an exe that launches, shows the
    widget, offers Reconnect Google, and then tells every single user who
    clicks it that no client is configured. PyInstaller has no way to know
    that is wrong: the import is conditional by design and the module is
    genuinely optional at runtime.

    So it is checked here, loudly, before anything is built. This is the
    only step in the project that can ship a broken release quietly."""
    problems = []

    if not os.path.exists(OAUTH_CLIENT):
        problems.append(
            f"{OAUTH_CLIENT} is missing.\n"
            "    It is gitignored, so a fresh clone does not have it. Without\n"
            "    it the exe builds fine and then nobody can sign in -- every\n"
            "    user gets 'no client configured' from Reconnect Google.\n"
            "    Copy oauth_client.example.py to oauth_client.py and put the\n"
            "    release OAuth client in it."
        )
    else:
        # Present but empty is the same failure with an extra step, and is
        # exactly what copying the example file leaves behind.
        sys.path.insert(0, ASSET_DIR)
        import oauth_client

        if not getattr(oauth_client, "CLIENT_ID", None):
            problems.append(
                "oauth_client.CLIENT_ID is None.\n"
                "    That is the state oauth_client.example.py ships in. A\n"
                "    build with it would produce an exe nobody can sign into.\n"
                "    Fill in the release client, or build from source only."
            )

    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        problems.append(
            "PyInstaller is not installed.\n"
            "    It is a build-only dependency, commented out in\n"
            "    requirements.txt:  pip install pyinstaller"
        )

    if locked_exe():
        problems.append(
            f"{EXE} is still running and has to be closed first.\n"
            "    Tray icon -> Quit, or: Stop-Process -Name DesktopTasks*\n"
            "    The build replaces that file, and Windows won't allow it\n"
            "    while it is executing."
        )

    if problems:
        sys.exit(
            "Cannot build:\n\n  - "
            + "\n\n  - ".join(problems)
            + "\n"
        )


def main():
    print("1/3  preflight")
    preflight()
    print("     ok -- release OAuth client present, nothing holding the exe")

    print("\n2/3  icon")
    make_icon.main()

    print("\n3/3  PyInstaller")
    # Run from the repo root so PyInstaller's dist/ and build/ land there
    # rather than inside source/. The spec resolves its own inputs from
    # SPECPATH, so it doesn't care where it's invoked from.
    result = subprocess.run(
        [sys.executable, "-m", "PyInstaller", SPEC, "--noconfirm", "--clean"],
        cwd=REPO_ROOT,
    )
    if result.returncode != 0:
        sys.exit(f"PyInstaller failed (exit {result.returncode}).")

    if not os.path.exists(EXE):
        sys.exit("PyInstaller reported success but produced no exe.")
    size_mb = os.path.getsize(EXE) / (1024 * 1024)
    print(f"\n{EXE}  ({size_mb:.1f} MB)")

    print(
        "\nNote: unsigned, so the first run trips SmartScreen "
        "(More info -> Run anyway)."
    )
    print(
        "Worth checking by hand, because PyInstaller cannot:\n"
        "  DesktopTasks.exe --fetch     the fetch path, frozen\n"
        "  DesktopTasks.exe             the widget, and Reconnect Google\n"
        "A blank window means pywebview did not load its backend -- see\n"
        f"the log at %LOCALAPPDATA%{os.sep}DesktopTasks{os.sep}desktoptasks.log."
    )


if __name__ == "__main__":
    main()
