#!/usr/bin/env python3
"""Render a layout to a PNG without Kodi or hardware.

    python3 tools/preview.py --layout resources/layouts/default.json \
        --page 0 --out /tmp/page0.png

Useful while designing layouts: it uses the same renderer the add-on runs,
but feeds it demo data.
"""

import argparse
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "resources", "lib"))

from lcd4linux import pngio                      # noqa: E402
from lcd4linux.bmfont import FontCache           # noqa: E402
from lcd4linux.images import ImageCache          # noqa: E402
from lcd4linux.kodidata import DemoProvider      # noqa: E402
from lcd4linux.layout import Layout, Renderer    # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--layout", default=os.path.join(
        ROOT, "resources", "layouts", "default.json"))
    parser.add_argument("--out", default="preview.png")
    parser.add_argument("--page", type=int, default=None,
                        help="force a page index instead of using conditions")
    parser.add_argument("--track", type=int, default=0,
                        help="0 = demo music track, 1 = demo video")
    parser.add_argument("--state", default="playing",
                        choices=("playing", "paused", "stopped"))
    parser.add_argument("--elapsed", type=float, default=97.0)
    parser.add_argument("--rotate", type=int, default=0, choices=(0, 90, 180, 270))
    parser.add_argument("--art", default=os.path.join(
        ROOT, "resources", "media", "demo-cover.jpg"))
    parser.add_argument("--repeat", type=int, default=1,
                        help="render N frames, e.g. to fill a graph widget")
    parser.add_argument("--step", type=float, default=1.0,
                        help="seconds the virtual clock advances per frame")
    arguments = parser.parse_args()

    layout = Layout.load(arguments.layout)
    provider = DemoProvider(arguments.track, arguments.elapsed, arguments.state,
                            arguments.art)
    fonts = FontCache([os.path.join(ROOT, "resources", "fonts")])
    images = ImageCache()
    renderer = Renderer(layout, provider, fonts, images)

    if arguments.page is not None:
        page = layout.pages[arguments.page % len(layout.pages)]
        renderer._active = page
        renderer._visible_signature = (page.index,)
        renderer.select_page = lambda now: page

    # Advance a virtual clock between frames so time based widgets (graphs,
    # scrolling text) have something to show in a still image.
    started = time.time()
    frames = max(1, arguments.repeat)
    for index in range(frames):
        canvas = renderer.render(started + index * arguments.step)
    elapsed = (time.time() - started) / frames

    if arguments.rotate:
        canvas = canvas.rotated(arguments.rotate)
    with open(arguments.out, "wb") as handle:
        handle.write(pngio.encode_rgb(canvas.width, canvas.height,
                                      canvas.to_rgb888()))
    print("%s: page %r rendered to %s in %.1f ms"
          % (layout.name, renderer.active_page.name if renderer.active_page else "-",
             arguments.out, elapsed * 1000))


if __name__ == "__main__":
    main()
