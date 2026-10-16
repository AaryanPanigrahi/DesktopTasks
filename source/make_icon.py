"""
Generates DesktopTasks.ico for the exe's embedded icon.

Drawn here rather than converted from a logo.png, because this project has
no mark of its own -- DesktopCards converts one, and its make_icon.py is
four lines around logo_cache.write_ico. Drawing it keeps the icon a build
step either way, so there is no committed binary to drift out of date, and
it means the exe icon, the Start-menu shortcut and the tray dot all come
from one description of what a DesktopTasks icon looks like.

A build step rather than a committed .ico: PyInstaller's --icon needs a
real multi-size .ico and will not take a PNG, so something has to produce
one, and a generator is easier to change than a binary.

The accent colour is fixed here on purpose. widget.build_tray_image paints
the live tray dot in the user's own Windows accent, which is right for
something redrawn on every launch; an icon compiled into the exe is shipped
to whoever downloads it, so baking the builder's personal accent into it
would be wrong for everyone else.
"""

import os
import sys

from PIL import Image, ImageDraw

from paths import ICON_PATH

# Windows picks the nearest size from inside the .ico rather than scaling
# one, so a single 256px image would be resampled badly at 16px in the
# taskbar. These are the sizes the shell actually asks for.
ICON_SIZES = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64),
              (128, 128), (256, 256)]

# Drawn large and downsampled, which is what gives the curves and the
# checkmark clean edges at every size above -- drawing directly at 16px
# produces a muddy blur instead.
CANVAS = 256

# Windows' own default accent, so the shipped icon matches a stock desktop.
ACCENT = (0, 120, 212, 255)
MARK = (255, 255, 255, 255)


def draw_icon(size=CANVAS):
    """A rounded square in the accent colour with a white checkmark.

    A checkmark rather than a list of lines: at 16px a three-line glyph
    collapses into a grey smear, where a single stroke stays legible, and
    "done" reads as tasks more immediately than "rows of text" does."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Inset slightly so the shape is not clipped by the icon's own bounds,
    # which is visible as flattened corners at small sizes.
    pad = size * 0.06
    radius = size * 0.22
    draw.rounded_rectangle(
        [pad, pad, size - pad, size - pad],
        radius=radius,
        fill=ACCENT,
    )

    # The checkmark, as two strokes meeting at the low point. Coordinates
    # are fractions of the canvas so this scales with CANVAS.
    stroke = max(2, int(size * 0.085))
    points = [
        (size * 0.29, size * 0.52),
        (size * 0.45, size * 0.68),
        (size * 0.73, size * 0.35),
    ]
    draw.line(points, fill=MARK, width=stroke, joint="curve")
    # Round caps. ImageDraw.line has no cap style, so the ends are squared
    # off and read as chipped against the rounded joint; a dot at each end
    # is the usual way round that.
    for x, y in (points[0], points[-1]):
        r = stroke / 2
        draw.ellipse([x - r, y - r, x + r, y + r], fill=MARK)

    return img


def main():
    img = draw_icon()
    os.makedirs(os.path.dirname(ICON_PATH) or ".", exist_ok=True)
    # Pillow builds every listed size into the one file from this single
    # image, downsampling each with a good filter.
    img.save(ICON_PATH, format="ICO", sizes=ICON_SIZES)
    print(f"Wrote {ICON_PATH} ({len(ICON_SIZES)} sizes, "
          f"{os.path.getsize(ICON_PATH)} bytes)")
    return ICON_PATH


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
