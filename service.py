"""Kodi service entry point for script.lcd4linux."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "resources", "lib"))

from lcd4linux.service import main  # noqa: E402

if __name__ == "__main__":
    main()
