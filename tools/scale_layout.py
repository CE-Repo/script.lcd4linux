#!/usr/bin/env python3
"""Rescale a layout for a different display size.

    python3 tools/scale_layout.py resources/layouts/xl-player.json 800 480

Writes ``<name>-<width>x<height>.json`` next to the input unless ``-o`` is
given.  Positions and box sizes follow the two axes separately, while
anything measured in "how big does this look" - font sizes, radii, line
thickness - follows the vertical scale so the proportions of the type stay
the same.  Percentage values are left alone because they already scale.

A box that is exactly square keeps its shape instead, because a square box
is a circle, a cover or an icon; scaling 800x480 to 1024x600 moves the two
axes by 1.28 and 1.25, which is just enough to turn the record on the
"vinyl" layout into a visible ellipse.
"""

import argparse
import json
import os
import sys

#: Keys scaled with the horizontal factor.
HORIZONTAL = ("x", "w", "width", "x2")
#: Keys scaled with the vertical factor.
VERTICAL = ("y", "h", "height", "y2")
#: Keys that describe an apparent size rather than a position.
UNIFORM = ("size", "radius", "thickness", "border", "padding", "linespacing",
           "knobsize", "gap", "rimwidth", "scrollspeed", "scrollgap",
           "shadowoffset")
#: Graph history length follows the width, one sample per few pixels.
SAMPLES = ("points", "segments")


def scale_value(value, factor):
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, (int, float)):
        return int(round(value * factor))
    if isinstance(value, str):
        text = value.strip()
        if text.endswith("%"):
            return value            # already relative
        try:
            number = float(text)
        except ValueError:
            return value            # a token or a colour, leave it
        return int(round(number * factor))
    return value


def square_side(widget):
    """The side length of an exactly square box, ``None`` for anything else."""
    width, height = widget.get("w"), widget.get("h")
    for value in (width, height):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
    return width if width == height else None


def scale_widget(widget, sx, sy):
    out = {}
    for key, value in widget.items():
        if key in HORIZONTAL:
            out[key] = scale_value(value, sx)
        elif key in VERTICAL:
            out[key] = scale_value(value, sy)
        elif key in UNIFORM:
            out[key] = scale_value(value, sy)
        elif key in SAMPLES:
            out[key] = max(2, scale_value(value, sx))
        else:
            out[key] = value
    side = square_side(widget)
    if side is not None:
        # The smaller factor, so the box still fits where it did before.
        out["w"] = out["h"] = scale_value(side, min(sx, sy))
    return out


def scale_layout(layout, width, height, name_suffix=True):
    old_width, old_height = layout.get("size", [480, 320])
    sx = float(width) / float(old_width)
    sy = float(height) / float(old_height)

    out = dict(layout)
    out["size"] = [int(width), int(height)]
    if name_suffix and layout.get("name"):
        out["name"] = "%s (%dx%d)" % (layout["name"], width, height)
    defaults = dict(layout.get("defaults", {}))
    if "size" in defaults:
        defaults["size"] = scale_value(defaults["size"], sy)
        out["defaults"] = defaults

    pages = []
    for page in layout.get("pages", []):
        new_page = dict(page)
        new_page["widgets"] = [scale_widget(widget, sx, sy)
                               for widget in page.get("widgets", [])]
        pages.append(new_page)
    out["pages"] = pages
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("layout")
    parser.add_argument("width", type=int)
    parser.add_argument("height", type=int)
    parser.add_argument("-o", "--out")
    arguments = parser.parse_args()

    with open(arguments.layout, "r", encoding="utf-8-sig") as handle:
        layout = json.load(handle)
    scaled = scale_layout(layout, arguments.width, arguments.height)

    path = arguments.out
    if not path:
        stem = os.path.splitext(arguments.layout)[0]
        path = "%s-%dx%d.json" % (stem, arguments.width, arguments.height)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(scaled, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
    print("%s -> %s (%dx%d)" % (arguments.layout, path,
                                arguments.width, arguments.height))
    return 0


if __name__ == "__main__":
    sys.exit(main())
