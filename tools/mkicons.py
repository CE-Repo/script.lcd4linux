#!/usr/bin/env python3
"""Rebuild the bundled Font Awesome Free catalogue.

The add-on ships only the *index* of the icon set - every free name, which
styles it exists in and the words it can be found by.  That keeps the search
dialog working with no network at all, while the far bigger outline data is
fetched once per icon and then kept in the user's cache directory.

Usage::

    python3 tools/mkicons.py                  # latest pinned version
    python3 tools/mkicons.py --version 7.3.1
    python3 tools/mkicons.py --metadata icons.yml   # offline, from a copy

The result is written to ``resources/icons/fontawesome.json``.  Only the
standard library is used so the tool also runs on a Kodi box.
"""

import argparse
import json
import os
import re
import sys
import time

try:
    from urllib.request import Request, urlopen
except ImportError:  # pragma: no cover - Python 2 safety net
    from urllib2 import Request, urlopen  # type: ignore

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "resources", "lib"))

from lcd4linux import faicons  # noqa: E402

METADATA_URL = ("https://cdn.jsdelivr.net/npm/@fortawesome/"
                "fontawesome-free@%s/metadata/icons.yml")

#: Style name to the single letter the index stores.
STYLE_CODES = dict((style, code) for code, style in faicons.STYLE_CODES.items())

#: Words that say nothing about an icon and only pad the index.
NOISE = frozenset(("a", "an", "and", "are", "as", "at", "be", "by", "for",
                   "from", "in", "is", "it", "its", "of", "on", "or", "the",
                   "this", "to", "with"))


# ---------------------------------------------------------------------------
# a very small YAML reader
# ---------------------------------------------------------------------------

def parse_metadata(text):
    """Read ``icons.yml`` into ``{name: {label, styles, terms, aliases}}``.

    Font Awesome's metadata is machine written and always has the same
    shape, so recognising "key at this indent" and "list item at this
    indent" is enough; pulling in a YAML library for it would make the tool
    unusable on a box that only has Kodi's Python.
    """
    icons = {}
    current = None
    path = []          # the chain of keys leading to the current indent
    list_key = None    # where the items of a "- " list are collected
    for raw in text.splitlines():
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip(" "))
        line = raw.strip()
        if line.startswith("- "):
            if list_key is not None:
                list_key.append(_scalar(line[2:]))
            continue
        list_key = None
        key, _, value = line.partition(":")
        key = _scalar(key)
        value = value.strip()
        del path[indent // 2:]
        path.append(key)
        if indent == 0:
            current = {"label": "", "styles": [], "terms": [], "aliases": []}
            icons[key] = current
            continue
        if current is None:
            continue
        if path[1:] == ["label"]:
            current["label"] = _scalar(value)
        elif path[1:] == ["styles"]:
            list_key = current["styles"]
        elif path[1:] == ["search", "terms"]:
            list_key = current["terms"]
        elif path[1:] == ["aliases", "names"]:
            list_key = current["aliases"]
    return icons


def _scalar(value):
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
        value = value[1:-1]
    return value


# ---------------------------------------------------------------------------
# building the index
# ---------------------------------------------------------------------------

def keywords(name, label, terms):
    """The extra words this icon can be searched by.

    Anything already spelled out by the name or the label is dropped: the
    search matches those separately, and 2900 icons worth of repeated words
    would double the size of the file for nothing.
    """
    known = set(re.split(r"[^a-z0-9]+", ("%s %s" % (name, label)).lower()))
    words = []
    for term in terms:
        for word in re.split(r"[^a-z0-9]+", str(term).lower()):
            if word and word not in known and word not in NOISE:
                known.add(word)
                words.append(word)
    return words


def build(metadata, version):
    entries = []
    aliases = {}
    for name in sorted(metadata):
        icon = metadata[name]
        styles = [STYLE_CODES[style] for style in icon["styles"]
                  if style in STYLE_CODES]
        if not styles:
            # Pro-only families (thin, duotone, sharp...) are listed in the
            # same metadata but have no free outline to download.
            continue
        label = icon["label"]
        entry = [name, "".join(sorted(styles))]
        words = keywords(name, label, icon["terms"])
        derived = name.replace("-", " ")
        entry.append("" if label.lower() == derived else label)
        entry.append(" ".join(words))
        while len(entry) > 2 and not entry[-1]:
            entry.pop()
        entries.append(entry)
        for alias in icon["aliases"]:
            if alias and alias != name and alias not in metadata:
                aliases[alias] = name
    return {
        "version": version,
        "generated": time.strftime("%Y-%m-%d"),
        "licence": ("Font Awesome Free %s - icons: CC BY 4.0 - "
                    "https://fontawesome.com/license/free" % version),
        "url": faicons.DOWNLOAD_URL,
        "styles": list(faicons.STYLES),
        "fields": ["name", "styles", "label", "terms"],
        "aliases": aliases,
        "icons": entries,
    }


def fetch(url):
    request = Request(url, headers={"User-Agent": "script.lcd4linux/mkicons"})
    handle = urlopen(request, timeout=60)
    try:
        return handle.read().decode("utf-8")
    finally:
        handle.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", default=faicons.VERSION,
                        help="Font Awesome Free release to index")
    parser.add_argument("--metadata",
                        help="read icons.yml from this file instead of the CDN")
    parser.add_argument("--output", default=faicons.index_path(),
                        help="where to write the index")
    parser.add_argument("--indent", type=int, default=0,
                        help="pretty print the JSON with this indent")
    options = parser.parse_args(argv)

    if options.metadata:
        with open(options.metadata, "r", encoding="utf-8") as handle:
            text = handle.read()
    else:
        url = METADATA_URL % options.version
        print("fetching %s" % url)
        text = fetch(url)

    metadata = parse_metadata(text)
    if not metadata:
        print("no icons found in the metadata", file=sys.stderr)
        return 1
    index = build(metadata, options.version)

    directory = os.path.dirname(options.output)
    if directory and not os.path.isdir(directory):
        os.makedirs(directory)
    separators = (", ", ": ") if options.indent else (",", ":")
    with open(options.output, "w", encoding="utf-8") as handle:
        json.dump(index, handle, ensure_ascii=False, sort_keys=True,
                  indent=options.indent or None, separators=separators)
        handle.write("\n")

    counts = {}
    for entry in index["icons"]:
        for code in entry[1]:
            style = faicons.STYLE_CODES[code]
            counts[style] = counts.get(style, 0) + 1
    print("%s: %d icons (%s), %d aliases, %.1f kB"
          % (options.output, len(index["icons"]),
             ", ".join("%s %d" % item for item in sorted(counts.items())),
             len(index["aliases"]),
             os.path.getsize(options.output) / 1024.0))
    return 0


if __name__ == "__main__":
    sys.exit(main())
