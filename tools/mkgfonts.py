#!/usr/bin/env python3
"""Build the Google Fonts index that ships with script.lcd4linux.

The add-on carries the *list* of families - name, kind and the weights each
one has - so the font dialog can be searched with no network at all.  The
faces themselves are fetched the first time a layout actually uses one, the
same way ``tools/mkicons.py`` and :mod:`~lcd4linux.faicons` split the Font
Awesome set.

Families are written most popular first, which is the order the dialog
shows them in: alphabetical would open on a page of fonts nobody has heard
of.

    python3 tools/mkgfonts.py [output-file]
"""

import json
import os
import sys
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTPUT = os.path.join(ROOT, "resources", "fonts", "googlefonts.json")

#: The public catalogue behind fonts.google.com.  No key, no quota.
METADATA_URL = "https://fonts.google.com/metadata/fonts"

#: One letter per kind, to keep the index small.
CATEGORIES = {
    "Sans Serif": "s",
    "Serif": "f",
    "Display": "d",
    "Handwriting": "h",
    "Monospace": "m",
}

TIMEOUT = 30.0


def fetch():
    """The catalogue as Python, with Google's anti-hijack prefix stripped."""
    request = urllib.request.Request(
        METADATA_URL, headers={"User-Agent": "script.lcd4linux (build tool)"})
    with urllib.request.urlopen(request, timeout=TIMEOUT) as handle:
        raw = handle.read().decode("utf-8")
    return json.loads(raw[raw.index("{"):])


def build(data):
    """Turn the metadata into the compact index the add-on reads."""
    families = []
    skipped = {"no-latin": 0, "not-open": 0}
    # "popularity" is a rank, not a score: 1 is the most used family, so
    # the sort is ascending and anything without one goes to the back.
    for entry in sorted(data["familyMetadataList"],
                        key=lambda item: int(item.get("popularity") or 99999)):
        if "latin" not in (entry.get("subsets") or ()):
            # Nothing the add-on draws is outside Latin, so a family that
            # has no Latin subset would download and then show boxes.
            skipped["no-latin"] += 1
            continue
        if not entry.get("isOpenSource", True):
            # Everything on fonts.google.com is meant to be, but a family
            # that says otherwise is not ours to redistribute or cache.
            skipped["not-open"] += 1
            continue
        weights = sorted({int(key.rstrip("i")) for key in entry["fonts"]})
        families.append([
            entry["family"],
            CATEGORIES.get(entry.get("category"), "s"),
            # One digit per weight: 400 is "4", 700 is "7".  Nothing on
            # Google Fonts sits between the hundreds.
            "".join(str(weight // 100) for weight in weights),
            1 if any(key.endswith("i") for key in entry["fonts"]) else 0,
        ])
    return {
        "generated": time.strftime("%Y-%m-%d", time.gmtime()),
        "source": METADATA_URL,
        "licence": "https://fonts.google.com/attribution",
        "categories": dict((code, name) for name, code in CATEGORIES.items()),
        "fields": ["family", "category", "weights", "italic"],
        "families": families,
    }, skipped


def main(argv):
    output = argv[1] if len(argv) > 1 else OUTPUT
    print("fetching %s" % METADATA_URL)
    index, skipped = build(fetch())
    blob = json.dumps(index, separators=(",", ":"), ensure_ascii=False)
    with open(output, "w", encoding="utf-8") as handle:
        handle.write(blob)
    counts = {}
    for entry in index["families"]:
        counts[entry[1]] = counts.get(entry[1], 0) + 1
    print("%d families, %.1f kB" % (len(index["families"]),
                                    len(blob.encode("utf-8")) / 1024.0))
    for code, name in sorted(index["categories"].items()):
        print("  %-12s %4d" % (name, counts.get(code, 0)))
    print("skipped: %s" % ", ".join("%s %d" % pair
                                    for pair in sorted(skipped.items())))
    print("wrote %s" % output)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
