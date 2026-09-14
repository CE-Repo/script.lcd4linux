#!/usr/bin/env python3
"""Render every bundled layout into one labelled overview image.

    python3 tools/contact_sheet.py --state video --out overview-video.png

Each layout is rendered exactly as the add-on would render it in that state,
so the page shown is the one its own conditions select.  Handy to see the
whole collection at a glance, and to regenerate the overview after adding a
layout.
"""

import argparse
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "resources", "lib"))

from lcd4linux import pngio                            # noqa: E402
from lcd4linux.bmfont import FontCache                 # noqa: E402
from lcd4linux.canvas import Canvas, parse_color       # noqa: E402
from lcd4linux.images import Image, ImageCache         # noqa: E402
from lcd4linux.kodidata import DemoProvider            # noqa: E402
from lcd4linux.layout import Layout, Renderer, discover  # noqa: E402

#: state name -> (demo track, player state, elapsed seconds)
STATES = {
    "video": (1, "playing", 2400.0),
    "series": (2, "playing", 900.0),
    "normal": (0, "playing", 97.0),
    "music": (0, "playing", 97.0),
    "idle": (0, "stopped", 0.0),
}


def canvas_to_image(canvas):
    """Turn a rendered canvas into an RGBA image so it can be scaled."""
    rgb = canvas.to_rgb888()
    rgba = bytearray(canvas.width * canvas.height * 4)
    rgba[0::4] = rgb[0::3]
    rgba[1::4] = rgb[1::3]
    rgba[2::4] = rgb[2::3]
    rgba[3::4] = b"\xff" * (canvas.width * canvas.height)
    return Image(canvas.width, canvas.height, rgba)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", default="video", choices=sorted(STATES))
    parser.add_argument("--out", default="overview.png")
    parser.add_argument("--columns", type=int, default=4)
    parser.add_argument("--tile-width", type=int, default=360)
    parser.add_argument("--tile-height", type=int, default=240)
    parser.add_argument("--all-sizes", action="store_true",
                        help="include the -800x480, -1024x600 and portrait "
                             "variants")
    arguments = parser.parse_args()

    directory = os.path.join(ROOT, "resources", "layouts")
    names = sorted(discover([directory]))
    if not arguments.all_sizes:
        names = [name for name in names if "x" not in name.rsplit("-", 1)[-1]
                 or not name.rsplit("-", 1)[-1][:-5].replace("x", "").isdigit()]

    track, state, elapsed = STATES[arguments.state]
    art = os.path.join(ROOT, "resources", "media", "demo-cover.jpg")
    fonts = FontCache([os.path.join(ROOT, "resources", "fonts")])
    label_font = fonts.get("sans-bold", 19)
    note_font = fonts.get("sans", 16)

    tile_w = arguments.tile_width
    tile_h = arguments.tile_height
    label_h = 26
    pad = 12
    columns = arguments.columns
    rows = (len(names) + columns - 1) // columns

    sheet = Canvas(columns * (tile_w + pad) + pad,
                   rows * (tile_h + label_h + pad) + pad,
                   parse_color("#15181f"))

    for index, name in enumerate(names):
        path = os.path.join(directory, name)
        layout = Layout.load(path)
        provider = DemoProvider(track, elapsed, state, art)
        images = ImageCache()
        renderer = Renderer(layout, provider, fonts, images)
        canvas = renderer.render()
        page = renderer.active_page.name if renderer.active_page else "-"

        tile = canvas_to_image(canvas).fitted(tile_w, tile_h, "contain")
        column = index % columns
        row = index // columns
        x = pad + column * (tile_w + pad)
        y = pad + row * (tile_h + label_h + pad)

        sheet.fill_rect(x, y + label_h, tile_w, tile_h, parse_color("#000000"))
        sheet.blit_sprite(x + (tile_w - tile.width) // 2,
                          y + label_h + (tile_h - tile.height) // 2,
                          tile.sprite())
        sheet.rect(x, y + label_h, tile_w, tile_h, parse_color("#2a3040"), 1)

        # Name and details share one line so the tiles stay compact.
        baseline = y + label_font.ascent
        pen = sheet.draw_text(label_font, layout.name, x + 2, baseline,
                              parse_color("#ffffff"))
        detail = "  %s · %s" % (name, page)
        sheet.draw_text(note_font,
                        note_font.ellipsize(detail, x + tile_w - pen - 2),
                        pen, baseline, parse_color("#8b93a8"))
        print("  %-28s %s" % (name, page))

    with open(arguments.out, "wb") as handle:
        handle.write(pngio.encode_rgb(sheet.width, sheet.height,
                                      sheet.to_rgb888()))
    print("%d layouts (%s) -> %s  [%dx%d]"
          % (len(names), arguments.state, arguments.out,
             sheet.width, sheet.height))
    return 0


if __name__ == "__main__":
    sys.exit(main())
