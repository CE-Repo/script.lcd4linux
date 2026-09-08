"""Template expansion and condition evaluation for layouts.

Layout files address data through ``${...}`` placeholders::

    "${player.artist} - ${player.title}"
    "${player.time} / ${player.duration}"
    "${info:MusicPlayer.Album|upper|trunc:24}"

Anything the add-on does not know natively can still be reached with the
``info:`` prefix (any Kodi InfoLabel) or ``bool:`` (any Kodi boolean
condition), so a layout is never limited to the built-in token list.

Fixed words are written as ``$LOCALIZE[id]``, the same spelling Kodi skins
use, so the bundled layouts read in the language Kodi is set to.  Ids from
30000 up are the add-on's own strings, lower ones are Kodi's.
"""

import re

from . import localize

TOKEN_RE = re.compile(r"\$\{([^}]*)\}")
LOCALIZE_RE = re.compile(r"\$LOCALIZE\[(\d+)\]")

_TRUE_WORDS = ("1", "true", "yes", "on")


# ---------------------------------------------------------------------------
# filters
# ---------------------------------------------------------------------------

def _to_number(value, default=0.0):
    try:
        return float(str(value).strip().replace(",", "."))
    except (TypeError, ValueError):
        return default


def _format_hms(seconds, force_hours=False):
    try:
        total = int(float(seconds))
    except (TypeError, ValueError):
        return ""
    sign = "-" if total < 0 else ""
    total = abs(total)
    hours, rest = divmod(total, 3600)
    minutes, secs = divmod(rest, 60)
    if hours or force_hours:
        return "%s%d:%02d:%02d" % (sign, hours, minutes, secs)
    return "%s%d:%02d" % (sign, minutes, secs)


def _filter_trunc(value, length="20", suffix=u"…"):
    try:
        length = int(length)
    except ValueError:
        return value
    if length <= 0 or len(value) <= length:
        return value
    return value[:max(0, length - len(suffix))] + suffix


def _filter_pad(value, length="0", char=" "):
    try:
        length = int(length)
    except ValueError:
        return value
    char = char[:1] or " "
    return value.rjust(length, char)


def _filter_round(value, digits="0"):
    try:
        digits = int(digits)
    except ValueError:
        digits = 0
    number = _to_number(value)
    if digits <= 0:
        return str(int(round(number)))
    return ("%%.%df" % digits) % number


FILTERS = {
    "upper": lambda value: value.upper(),
    "lower": lambda value: value.lower(),
    "title": lambda value: value.title(),
    "capitalize": lambda value: value.capitalize(),
    "strip": lambda value: value.strip(),
    "trunc": _filter_trunc,
    "pad": _filter_pad,
    "hms": lambda value: _format_hms(value),
    "hhmmss": lambda value: _format_hms(value, True),
    "int": lambda value: str(int(_to_number(value))),
    "round": _filter_round,
    "abs": lambda value: str(abs(_to_number(value))),
    "default": lambda value, fallback="": value if value else fallback,
    "prefix": lambda value, text="": (text + value) if value else "",
    "suffix": lambda value, text="": (value + text) if value else "",
    "replace": lambda value, old="", new="": value.replace(old, new),
    "first": lambda value, sep=",": value.split(sep)[0].strip() if value else "",
    "escape": lambda value: value,
}


#: How many arguments each filter takes; the argument text may itself
#: contain colons, so the split has to be limited.
FILTER_ARGS = {
    "trunc": 2, "pad": 2, "replace": 2, "round": 1, "default": 1,
    "prefix": 1, "suffix": 1, "first": 1,
}


def apply_filter(value, spec):
    """Apply one ``name:arg:arg`` filter specification."""
    name = spec.split(":", 1)[0].strip().lower()
    handler = FILTERS.get(name)
    if handler is None:
        return value
    parts = spec.split(":", FILTER_ARGS.get(name, 0))
    try:
        return handler(value, *parts[1:])
    except TypeError:
        return value
    except Exception:
        return value


# ---------------------------------------------------------------------------
# expansion
# ---------------------------------------------------------------------------

def localize_text(template):
    """Replace every ``$LOCALIZE[id]`` with its translation."""
    if not template or "$LOCALIZE[" not in template:
        return template or u""
    return LOCALIZE_RE.sub(lambda match: localize.text(match.group(1)), template)


def expand(template, provider):
    """Replace every ``$LOCALIZE[...]`` and ``${...}`` in ``template``.

    The translations go in first so a fixed word can be used as a filter
    argument, as in ``${player.next|prefix:$LOCALIZE[32420]: |trunc:32}``,
    where ``trunc`` has to count the translated text.
    """
    if not template:
        return u""
    template = localize_text(template)
    if "${" not in template:
        return template

    def replace(match):
        expression = match.group(1)
        parts = expression.split("|")
        value = provider.value(parts[0].strip())
        if value is None:
            value = u""
        elif not isinstance(value, str):
            value = str(value)
        for spec in parts[1:]:
            value = apply_filter(value, spec)
        return value

    return TOKEN_RE.sub(replace, template)


def number(template, provider, default=0.0):
    """Expand ``template`` and interpret the result as a number."""
    if template is None:
        return default
    if isinstance(template, (int, float)):
        return float(template)
    text = expand(str(template), provider).strip().rstrip("%")
    return _to_number(text, default)


# ---------------------------------------------------------------------------
# conditions
# ---------------------------------------------------------------------------

_COMPARATORS = (
    (">=", lambda a, b: _to_number(a) >= _to_number(b)),
    ("<=", lambda a, b: _to_number(a) <= _to_number(b)),
    ("!=", lambda a, b: a.strip().lower() != b.strip().lower()),
    ("==", lambda a, b: a.strip().lower() == b.strip().lower()),
    (">", lambda a, b: _to_number(a) > _to_number(b)),
    ("<", lambda a, b: _to_number(a) < _to_number(b)),
    (" contains ", lambda a, b: b.strip().lower() in a.lower()),
    (" startswith ", lambda a, b: a.lower().startswith(b.strip().lower())),
    (" endswith ", lambda a, b: a.lower().endswith(b.strip().lower())),
)


def evaluate(condition, provider):
    """Evaluate a visibility condition.

    Supported forms, combinable with ``+`` (and) and ``|`` (or) and
    negatable with a leading ``!``:

    * ``playing``, ``paused``, ``stopped``, ``audio``, ``video``, ``idle``
      and the other states the data provider exposes
    * any Kodi boolean condition, e.g. ``Player.HasVideo``
    * a comparison such as ``${player.percent} > 50``
    * a bare ``${token}``, true when it expands to something non-empty
    """
    if condition is None:
        return True
    if isinstance(condition, bool):
        return condition
    text = str(condition).strip()
    if not text or text.lower() in ("always", "true", "1"):
        return True
    if text.lower() in ("never", "false", "0"):
        return False

    # '|' also separates filters inside ${...}; only split at top level.
    for separator, combine in ((u"|", any), (u"+", all)):
        parts = _split_top_level(text, separator)
        if len(parts) > 1:
            return combine(evaluate(part, provider) for part in parts)

    if text.startswith("!"):
        return not evaluate(text[1:], provider)

    for operator, compare in _COMPARATORS:
        index = _find_top_level(text, operator)
        if index >= 0:
            left = expand(text[:index], provider)
            right = expand(text[index + len(operator):], provider)
            return bool(compare(left, right))

    if text.startswith("${") and text.endswith("}"):
        return bool(expand(text, provider).strip())

    return provider.condition(text)


def _split_top_level(text, separator):
    """Split on ``separator`` but not inside ``${...}``."""
    parts = []
    depth = 0
    current = []
    index = 0
    while index < len(text):
        char = text[index]
        if text.startswith("${", index):
            depth += 1
            current.append("${")
            index += 2
            continue
        if char == "}" and depth:
            depth -= 1
        if char == separator and depth == 0:
            parts.append("".join(current))
            current = []
        else:
            current.append(char)
        index += 1
    parts.append("".join(current))
    return [part for part in parts if part.strip()] or [text]


def _find_top_level(text, needle):
    depth = 0
    index = 0
    while index < len(text):
        if text.startswith("${", index):
            depth += 1
            index += 2
            continue
        if text[index] == "}" and depth:
            depth -= 1
            index += 1
            continue
        if depth == 0 and text.startswith(needle, index):
            return index
        index += 1
    return -1


def truthy(value):
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in _TRUE_WORDS
