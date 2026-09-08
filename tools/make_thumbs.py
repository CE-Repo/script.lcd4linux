#!/usr/bin/env python3
"""Render the preview picture the layout chooser shows for each design.

    python3 tools/make_thumbs.py

Writes ``resources/thumbs/<design>.png`` for every bundled layout, so the
add-on does not have to render them on a set top box.  The size variants of
one design share a picture; the variant that matches the panel is picked
when the layout is loaded, not when it is chosen.
"""

import argparse
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "resources", "lib"))

from lcd4linux import thumbs                             # noqa: E402
from lcd4linux.layout import discover                    # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default=os.path.join(ROOT, "resources", "thumbs"))
    arguments = parser.parse_args()

    layouts = os.path.join(ROOT, "resources", "layouts")
    available = discover([layouts])
    designs = {}
    for name in sorted(available):
        design = thumbs.design_name(name)
        # Prefer the file without a size suffix: that is the name the layout
        # setting stores, and the size the design was drawn for.
        if design not in designs or name == design + ".json":
            designs[design] = name

    fonts = [os.path.join(ROOT, "resources", "fonts")]
    for design in sorted(designs):
        name = designs[design]
        out = os.path.join(arguments.out, design + ".png")
        thumbs.render(available[name], out, fonts)
        print("  %-16s %s  (%d bytes)"
              % (design, name, os.path.getsize(out)))
    print("%d previews -> %s" % (len(designs), arguments.out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
