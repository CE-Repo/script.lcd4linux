"""Script entry point: the LCD4Linux control menu.

Run without arguments it opens a menu; the individual actions can also be
bound to a key or a favourite, for example::

    RunScript(script.lcd4linux, next_page)
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "resources", "lib"))

from lcd4linux.ui import run  # noqa: E402

if __name__ == "__main__":
    run(sys.argv[1:])
