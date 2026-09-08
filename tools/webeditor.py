#!/usr/bin/env python3
"""Run the layout editor on a PC, without Kodi and without a display.

    python3 tools/webeditor.py

Then open http://127.0.0.1:8050/ .  Layouts are read from the add-on's
``resources/layouts`` folder and saved to ``~/.lcd4linux/layouts`` (or to
``--layout-dir``), exactly as they are on the box; copy the file over
afterwards, or edit straight on the box with the editor the service runs.
"""

import argparse
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "resources", "lib"))

from lcd4linux import webui                      # noqa: E402
from lcd4linux.settings import Config            # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--port", type=int, default=8050)
    parser.add_argument("--bind", default="local", choices=("local", "all"),
                        help="'local' only serves 127.0.0.1 (default)")
    parser.add_argument("--password", default="",
                        help="ask for this password (any user name)")
    parser.add_argument("--layout-dir", default="",
                        help="where layouts are saved, default ~/.lcd4linux/layouts")
    arguments = parser.parse_args()

    config = Config({"web_port": arguments.port, "web_bind": arguments.bind,
                     "web_password": arguments.password,
                     "layout_dir": arguments.layout_dir})
    editor = webui.WebEditor(config)
    if not editor.start():
        return 1
    print("layout editor on %s" % editor.url())
    print("layouts are saved to %s" % webui.user_directory())
    print("stop with Ctrl+C")
    try:
        while True:
            # The server runs in its own thread; this one only waits for
            # Ctrl+C, which a plain join() would swallow on some platforms.
            editor._thread.join(0.5)
    except KeyboardInterrupt:
        print("")
    finally:
        editor.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
