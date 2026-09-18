"""A small SVG path reader and scanline rasteriser.

Font Awesome ships its icons as a single ``<path d="...">`` per glyph, so the
only thing standing between that file and a pixel on the panel is turning
the path data into polygons and filling them.  Both halves live here:

* :func:`parse` walks the ``d`` attribute and flattens every curve into
  straight segments, returning one point list per subpath.
* :func:`mask` fills those subpaths into an 8 bit coverage map, using the
  non-zero winding rule so that the holes in a glyph stay holes.

Everything is plain Python and only needs the standard library, matching the
rest of the add-on's renderer.
"""

import math
import re

#: Numbers as an SVG path writes them: ``1``, ``-.5``, ``2.5e-3``, ``1-2``.
_NUMBER = re.compile(r"[-+]?(?:\d*\.\d+|\d+\.?)(?:[eE][-+]?\d+)?")
_COMMAND = re.compile(r"[MmZzLlHhVvCcSsQqTtAa]")

#: How many arguments each command consumes per repetition.
_ARGUMENTS = {"m": 2, "z": 0, "l": 2, "h": 1, "v": 1,
              "c": 6, "s": 4, "q": 4, "t": 2, "a": 7}


def tokenize(data):
    """Split path data into ``(command, [numbers])`` pairs.

    A command may be followed by several sets of arguments (and after a
    ``moveto`` the repeats are ``lineto``s), which is unrolled here so the
    parser below only ever sees one set at a time.
    """
    tokens = []
    position = 0
    text = data or ""
    length = len(text)
    while position < length:
        match = _COMMAND.search(text, position)
        if match is None:
            break
        command = match.group()
        position = match.end()
        end = _COMMAND.search(text, position)
        chunk = text[position:end.start() if end else length]
        position = end.start() if end else length
        numbers = [float(value) for value in _NUMBER.findall(chunk)]
        needed = _ARGUMENTS[command.lower()]
        if not needed:
            tokens.append((command, []))
            continue
        if len(numbers) < needed:
            continue
        first = True
        while len(numbers) >= needed:
            arguments = numbers[:needed]
            del numbers[:needed]
            if first:
                tokens.append((command, arguments))
                first = False
            elif command == "M":
                tokens.append(("L", arguments))
            elif command == "m":
                tokens.append(("l", arguments))
            else:
                tokens.append((command, arguments))
    return tokens


def parse(data, flatness=4.0):
    """Flatten path data into ``[[(x, y), ...], ...]``.

    ``flatness`` is the longest straight segment a curve is broken into,
    measured in the path's own units.  Smaller values mean smoother curves
    and more points; the caller picks it from the size the icon is drawn at.
    """
    flatness = max(0.05, float(flatness))
    subpaths = []
    points = []
    x = y = 0.0
    start_x = start_y = 0.0
    # The reflected control point a smooth curve continues from.
    last_control = None
    last_kind = None

    def flush():
        if len(points) > 2:
            subpaths.append(list(points))
        del points[:]

    for command, arguments in tokenize(data):
        upper = command.upper()
        relative = command.islower()
        if upper == "M":
            flush()
            # A relative moveto continues from wherever the pen stopped,
            # which for the very first command is the origin.
            x, y = ((x + arguments[0], y + arguments[1]) if relative
                    else (arguments[0], arguments[1]))
            start_x, start_y = x, y
            points.append((x, y))
            last_control = None
            continue
        if not points:
            # A command after a closed subpath opens a new one at the point
            # the previous one ended on.
            points.append((x, y))
            start_x, start_y = x, y
        if upper == "Z":
            if len(points) > 2:
                points.append((start_x, start_y))
            flush()
            x, y = start_x, start_y
            last_control = None
        elif upper == "L":
            x, y = (x + arguments[0], y + arguments[1]) if relative else tuple(arguments)
            points.append((x, y))
            last_control = None
        elif upper == "H":
            x = x + arguments[0] if relative else arguments[0]
            points.append((x, y))
            last_control = None
        elif upper == "V":
            y = y + arguments[0] if relative else arguments[0]
            points.append((x, y))
            last_control = None
        elif upper in ("C", "S"):
            if upper == "C":
                c1x, c1y, c2x, c2y, ex, ey = arguments
                if relative:
                    c1x, c1y = c1x + x, c1y + y
                    c2x, c2y = c2x + x, c2y + y
                    ex, ey = ex + x, ey + y
            else:
                c2x, c2y, ex, ey = arguments
                if relative:
                    c2x, c2y = c2x + x, c2y + y
                    ex, ey = ex + x, ey + y
                if last_control is not None and last_kind == "C":
                    c1x, c1y = 2 * x - last_control[0], 2 * y - last_control[1]
                else:
                    c1x, c1y = x, y
            _cubic(points, x, y, c1x, c1y, c2x, c2y, ex, ey, flatness)
            last_control = (c2x, c2y)
            last_kind = "C"
            x, y = ex, ey
        elif upper in ("Q", "T"):
            if upper == "Q":
                cx, cy, ex, ey = arguments
                if relative:
                    cx, cy = cx + x, cy + y
                    ex, ey = ex + x, ey + y
            else:
                ex, ey = arguments
                if relative:
                    ex, ey = ex + x, ey + y
                if last_control is not None and last_kind == "Q":
                    cx, cy = 2 * x - last_control[0], 2 * y - last_control[1]
                else:
                    cx, cy = x, y
            _quadratic(points, x, y, cx, cy, ex, ey, flatness)
            last_control = (cx, cy)
            last_kind = "Q"
            x, y = ex, ey
        elif upper == "A":
            rx, ry, rotation, large, sweep, ex, ey = arguments
            if relative:
                ex, ey = ex + x, ey + y
            _arc(points, x, y, rx, ry, rotation, large, sweep, ex, ey, flatness)
            x, y = ex, ey
            last_control = None
    flush()
    return subpaths


def _steps(length, flatness):
    return max(2, min(64, int(length / flatness) + 1))


def _cubic(points, x0, y0, x1, y1, x2, y2, x3, y3, flatness):
    length = (math.hypot(x1 - x0, y1 - y0) + math.hypot(x2 - x1, y2 - y1)
              + math.hypot(x3 - x2, y3 - y2))
    steps = _steps(length, flatness)
    for index in range(1, steps + 1):
        t = index / float(steps)
        u = 1.0 - t
        a = u * u * u
        b = 3 * u * u * t
        c = 3 * u * t * t
        d = t * t * t
        points.append((a * x0 + b * x1 + c * x2 + d * x3,
                       a * y0 + b * y1 + c * y2 + d * y3))


def _quadratic(points, x0, y0, cx, cy, x1, y1, flatness):
    length = math.hypot(cx - x0, cy - y0) + math.hypot(x1 - cx, y1 - cy)
    steps = _steps(length, flatness)
    for index in range(1, steps + 1):
        t = index / float(steps)
        u = 1.0 - t
        a = u * u
        b = 2 * u * t
        c = t * t
        points.append((a * x0 + b * cx + c * x1, a * y0 + b * cy + c * y1))


def _arc(points, x0, y0, rx, ry, rotation, large, sweep, x1, y1, flatness):
    """Endpoint parameterised elliptical arc, as SVG 1.1 appendix F.6."""
    rx, ry = abs(rx), abs(ry)
    if rx < 1e-9 or ry < 1e-9 or (abs(x1 - x0) < 1e-12 and abs(y1 - y0) < 1e-12):
        points.append((x1, y1))
        return
    phi = math.radians(rotation)
    cos_phi, sin_phi = math.cos(phi), math.sin(phi)
    dx2 = (x0 - x1) / 2.0
    dy2 = (y0 - y1) / 2.0
    x1p = cos_phi * dx2 + sin_phi * dy2
    y1p = -sin_phi * dx2 + cos_phi * dy2
    # Grow radii that are too small to join the two endpoints.
    lam = (x1p * x1p) / (rx * rx) + (y1p * y1p) / (ry * ry)
    if lam > 1:
        scale = math.sqrt(lam)
        rx *= scale
        ry *= scale
    numerator = rx * rx * ry * ry - rx * rx * y1p * y1p - ry * ry * x1p * x1p
    denominator = rx * rx * y1p * y1p + ry * ry * x1p * x1p
    factor = math.sqrt(max(0.0, numerator / denominator)) if denominator else 0.0
    if bool(large) == bool(sweep):
        factor = -factor
    cxp = factor * rx * y1p / ry
    cyp = -factor * ry * x1p / rx
    cx = cos_phi * cxp - sin_phi * cyp + (x0 + x1) / 2.0
    cy = sin_phi * cxp + cos_phi * cyp + (y0 + y1) / 2.0

    def angle_of(px, py):
        return math.atan2((py - cyp) / ry, (px - cxp) / rx)

    theta = angle_of(x1p, y1p)
    delta = angle_of(-x1p, -y1p) - theta
    if sweep and delta < 0:
        delta += 2 * math.pi
    elif not sweep and delta > 0:
        delta -= 2 * math.pi
    steps = _steps(abs(delta) * max(rx, ry), flatness)
    for index in range(1, steps + 1):
        angle = theta + delta * index / float(steps)
        px = rx * math.cos(angle)
        py = ry * math.sin(angle)
        points.append((cos_phi * px - sin_phi * py + cx,
                       sin_phi * px + cos_phi * py + cy))


def bounds(subpaths):
    """``(x0, y0, x1, y1)`` around every point, or ``None`` when empty."""
    xs = [point[0] for path in subpaths for point in path]
    ys = [point[1] for path in subpaths for point in path]
    if not xs:
        return None
    return min(xs), min(ys), max(xs), max(ys)


def transform(subpaths, scale_x, scale_y, offset_x, offset_y):
    """Scale and shift every point, e.g. from a viewBox into pixels."""
    return [[(point[0] * scale_x + offset_x, point[1] * scale_y + offset_y)
             for point in path] for path in subpaths]


def mask(subpaths, width, height, samples=4, even_odd=False):
    """Fill ``subpaths`` into a ``width * height`` bytearray of coverage.

    Coordinates are in pixels.  Each pixel row is sampled ``samples`` times
    vertically and the horizontal ends of a span contribute their exact
    fraction, which is what keeps a 16 pixel icon from looking chewed.
    """
    width = max(0, int(width))
    height = max(0, int(height))
    out = bytearray(width * height)
    if width == 0 or height == 0:
        return out
    edges = []
    for path in subpaths:
        count = len(path)
        for index in range(count):
            x0, y0 = path[index]
            x1, y1 = path[(index + 1) % count]
            if y0 == y1:
                continue
            if y0 < y1:
                edges.append((y0, y1, x0, (x1 - x0) / (y1 - y0), 1))
            else:
                edges.append((y1, y0, x1, (x0 - x1) / (y0 - y1), -1))
    if not edges:
        return out
    edges.sort(key=lambda edge: edge[0])
    pending = 0
    active = []
    share = 1.0 / samples
    row = [0.0] * width
    total = len(edges)
    for py in range(height):
        for value in range(width):
            row[value] = 0.0
        touched = False
        for sample in range(samples):
            scan = py + (sample + 0.5) * share
            while pending < total and edges[pending][0] <= scan:
                active.append(edges[pending])
                pending += 1
            if not active:
                continue
            crossings = []
            keep = []
            for edge in active:
                # Scanlines only ever move down, so an edge that ends above
                # this one is done with and can be dropped for good.
                if edge[1] <= scan:
                    continue
                keep.append(edge)
                crossings.append((edge[2] + (scan - edge[0]) * edge[3],
                                  edge[4]))
            active = keep
            if len(crossings) < 2:
                continue
            crossings.sort()
            winding = 0
            span_start = 0.0
            for position, direction in crossings:
                was_inside = (winding % 2) if even_odd else winding
                winding += direction
                is_inside = (winding % 2) if even_odd else winding
                if not was_inside and is_inside:
                    span_start = position
                elif was_inside and not is_inside:
                    if _span(row, span_start, position, share, width):
                        touched = True
        if not touched:
            continue
        base = py * width
        for px in range(width):
            value = row[px]
            if value <= 0.0:
                continue
            out[base + px] = 255 if value >= 1.0 else int(value * 255.0 + 0.5)
    return out


def _span(row, left, right, weight, width):
    """Add ``weight`` coverage for the span between two crossings."""
    if right <= 0 or left >= width or right <= left:
        return False
    if left < 0:
        left = 0.0
    if right > width:
        right = float(width)
    first = int(left)
    last = int(right)
    if first == last:
        row[first] += (right - left) * weight
        return True
    row[first] += (first + 1 - left) * weight
    for index in range(first + 1, min(last, width)):
        row[index] += weight
    if last < width:
        row[last] += (right - last) * weight
    return True
