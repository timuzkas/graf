"""helper to coordinate mapping and curve sampling for the canvas."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable, Iterable

from otter import ParsedRelation


@dataclass
class Viewport:
    center_x: float = 0.0
    center_y: float = 0.0
    scale: float = 48.0
    min_scale: float = 3.0
    max_scale: float = 800.0

    def screen_to_world(self, px: float, py: float, width: float, height: float) -> tuple[float, float]:
        return (
            self.center_x + (px - width / 2) / self.scale,
            self.center_y - (py - height / 2) / self.scale,
        )

    def world_to_screen(self, x: float, y: float, width: float, height: float) -> tuple[float, float]:
        return (
            width / 2 + (x - self.center_x) * self.scale,
            height / 2 - (y - self.center_y) * self.scale,
        )

    def pan_pixels(self, dx: float, dy: float) -> None:
        self.center_x -= dx / self.scale
        self.center_y += dy / self.scale

    def zoom_at(self, factor: float, px: float, py: float, width: float, height: float) -> None:
        anchor_x, anchor_y = self.screen_to_world(px, py, width, height)
        self.scale = min(self.max_scale, max(self.min_scale, self.scale * factor))
        after_x, after_y = self.screen_to_world(px, py, width, height)
        self.center_x += anchor_x - after_x
        self.center_y += anchor_y - after_y


def _finite_eval(relation: ParsedRelation, x: float, y: float, variables: dict[str, float] | None = None, functions: dict | None = None) -> float | None:
    try:
        if not relation.allows(x, y, variables, functions):
            return None
        value = relation.evaluate(x, y, variables, functions)
        return value if math.isfinite(value) else None
    except (ArithmeticError, ValueError, OverflowError, KeyError):
        return None


def _explicit_value(relation: ParsedRelation, x: float, variables: dict[str, float] | None, functions: dict | None) -> float | None:
    """evaluate y=f(x), then check the domain with that y."""
    try:
        value = relation.evaluate(x, 0.0, variables, functions)
    except (ArithmeticError, ValueError, OverflowError, KeyError):
        return None
    if not math.isfinite(value) or not relation.allows(x, value, variables, functions):
        return None
    return value


def sample_explicit(
    relation: ParsedRelation,
    viewport: Viewport,
    width: int,
    height: int,
    variables: dict[str, float] | None = None,
    functions: dict | None = None,
) -> list[list[tuple[float, float]]]:
    """sample y=f(x), splitting at holes and jumps."""
    if width < 2:
        return []
    polylines: list[list[tuple[float, float]]] = []
    current: list[tuple[float, float]] = []
    previous_y: float | None = None
    jump_limit = max(36.0, width * 0.45)
    for px in range(width + 1):
        x, _ = viewport.screen_to_world(px, 0, width, height)
        value = _explicit_value(relation, x, variables, functions)
        if value is None:
            if len(current) > 1:
                polylines.append(current)
            current, previous_y = [], None
            continue
        _, py = viewport.world_to_screen(x, value, width, height)
        if previous_y is not None and abs(py - previous_y) > jump_limit:
            if len(current) > 1:
                polylines.append(current)
            current = []
        current.append((float(px), py))
        previous_y = py
    if len(current) > 1:
        polylines.append(current)
    return polylines


def _screen_point(viewport: Viewport, x: float, y: float, width: int, height: int) -> tuple[float, float]:
    return viewport.world_to_screen(x, y, width, height)


def _clip_segment(
    first: tuple[float, float],
    second: tuple[float, float],
    width: int,
    height: int,
    margin: float = 48.0,
) -> tuple[tuple[float, float], tuple[float, float]] | None:
    """clip one screen-space segment to the graph and a small outer margin."""
    x1, y1 = first
    dx, dy = second[0] - x1, second[1] - y1
    start, end = 0.0, 1.0
    for direction, distance in (
        (-dx, x1 + margin),
        (dx, width + margin - x1),
        (-dy, y1 + margin),
        (dy, height + margin - y1),
    ):
        if abs(direction) < 1e-12:
            if distance < 0:
                return None
            continue
        ratio = distance / direction
        if direction < 0:
            start = max(start, ratio)
        else:
            end = min(end, ratio)
        if start >= end:
            return None
    return ((x1 + start * dx, y1 + start * dy), (x1 + end * dx, y1 + end * dy))


def _clip_polylines(
    paths: list[list[tuple[float, float]]], width: int, height: int,
) -> list[list[tuple[float, float]]]:
    clipped: list[list[tuple[float, float]]] = []
    for path in paths:
        current: list[tuple[float, float]] = []
        for first, second in zip(path, path[1:]):
            segment = _clip_segment(first, second, width, height)
            if segment is None:
                if len(current) > 1:
                    clipped.append(current)
                current = []
                continue
            start, end = segment
            if current and math.hypot(current[-1][0] - start[0], current[-1][1] - start[1]) < 1e-6:
                current.append(end)
            else:
                if len(current) > 1:
                    clipped.append(current)
                current = [start, end]
        if len(current) > 1:
            clipped.append(current)
    return clipped


def _adaptive_curve(
    evaluator,
    parameter_start: float,
    parameter_end: float,
    viewport: Viewport,
    width: int,
    height: int,
    max_depth: int = 10,
) -> list[list[tuple[float, float]]]:
    """add samples where the midpoint bends off its chord."""
    polylines: list[list[tuple[float, float]]] = []

    def evaluate(parameter: float) -> tuple[float, float] | None:
        try:
            point = evaluator(parameter)
            if point is None or not all(math.isfinite(value) for value in point):
                return None
            return _screen_point(viewport, point[0], point[1], width, height)
        except (ArithmeticError, ValueError, OverflowError, KeyError):
            return None

    def join_paths(
        first: list[list[tuple[float, float]]],
        second: list[list[tuple[float, float]]],
    ) -> list[list[tuple[float, float]]]:
        if not first:
            return second
        if not second:
            return first
        if math.hypot(first[-1][-1][0] - second[0][0][0], first[-1][-1][1] - second[0][0][1]) < 0.01:
            return [*first[:-1], [*first[-1], *second[0][1:]], *second[1:]]
        return first + second

    def refine(
        left_parameter: float,
        left: tuple[float, float] | None,
        right_parameter: float,
        right: tuple[float, float] | None,
        depth: int,
    ) -> list[list[tuple[float, float]]]:
        middle_parameter = (left_parameter + right_parameter) / 2
        middle = evaluate(middle_parameter)

        if left is None and middle is None and right is None:
            return []
        if depth >= max_depth:
            paths: list[list[tuple[float, float]]] = []
            current: list[tuple[float, float]] = []
            for point in (left, middle, right):
                if point is None:
                    if current:
                        paths.append(current)
                    current = []
                elif not current or point != current[-1]:
                    current.append(point)
            if current:
                paths.append(current)
            return paths
        if left is None or middle is None or right is None:
            return join_paths(
                refine(left_parameter, left, middle_parameter, middle, depth + 1),
                refine(middle_parameter, middle, right_parameter, right, depth + 1),
            )
        margin = 48.0

        def metric_point(point: tuple[float, float]) -> tuple[float, float]:
            return (
                min(width + margin, max(-margin, point[0])),
                min(height + margin, max(-margin, point[1])),
            )

        metric_left = metric_point(left)
        metric_middle = metric_point(middle)
        metric_right = metric_point(right)
        chord_x = (metric_left[0] + metric_right[0]) / 2
        chord_y = (metric_left[1] + metric_right[1]) / 2
        deviation = math.hypot(metric_middle[0] - chord_x, metric_middle[1] - chord_y)
        span = math.hypot(metric_right[0] - metric_left[0], metric_right[1] - metric_left[1])
        if deviation < 0.65 and span < 22:
            return [[left, right]]
        return join_paths(
            refine(left_parameter, left, middle_parameter, middle, depth + 1),
            refine(middle_parameter, middle, right_parameter, right, depth + 1),
        )

    intervals = max(12, min(64, width // 20))
    step = (parameter_end - parameter_start) / intervals
    current: list[tuple[float, float]] = []
    for index in range(intervals):
        start = parameter_start + index * step
        end = parameter_start + (index + 1) * step
        paths = refine(start, evaluate(start), end, evaluate(end), 0)
        for path in paths:
            if current and math.hypot(current[-1][0] - path[0][0], current[-1][1] - path[0][1]) < 0.01:
                current.extend(path[1:])
            else:
                if len(current) > 1:
                    polylines.append(current)
                current = path
        if not paths:
            if len(current) > 1:
                polylines.append(current)
            current = []
    if len(current) > 1:
        polylines.append(current)
    return _clip_polylines(polylines, width, height)


def sample_explicit_adaptive(
    relation: ParsedRelation,
    viewport: Viewport,
    width: int,
    height: int,
    variables: dict[str, float] | None = None,
    functions: dict | None = None,
) -> list[list[tuple[float, float]]]:
    variables = variables or {}

    def evaluator(x: float) -> tuple[float, float] | None:
        value = _explicit_value(relation, x, variables, functions)
        return (x, value) if value is not None else None

    left, _ = viewport.screen_to_world(0, 0, width, height)
    right, _ = viewport.screen_to_world(width, 0, width, height)
    return _adaptive_curve(evaluator, left, right, viewport, width, height)


def sample_explicit_inequality(
    relation: ParsedRelation,
    viewport: Viewport,
    width: int,
    height: int,
    variables: dict[str, float] | None = None,
    functions: dict | None = None,
) -> tuple[list[list[tuple[float, float]]], list[list[tuple[float, float]]]] | None:
    """sample y-based inequalities as curves plus fill polygons."""
    boundary = relation.explicit_inequality_boundary()
    if boundary is None:
        return None
    boundary_relation, fill_edge = boundary
    paths = sample_explicit_adaptive(boundary_relation, viewport, width, height, variables, functions)
    edge_y = float(height + 2 if fill_edge == "bottom" else -2)
    polygons = [
        [(path[0][0], edge_y), *path, (path[-1][0], edge_y)]
        for path in paths
        if len(path) > 1
    ]
    return paths, polygons


def sample_polar(
    relation: ParsedRelation,
    viewport: Viewport,
    width: int,
    height: int,
    variables: dict[str, float] | None = None,
    functions: dict | None = None,
) -> list[list[tuple[float, float]]]:
    variables = variables or {}

    def evaluator(theta: float) -> tuple[float, float] | None:
        radius = _finite_eval_polar(relation, theta, variables, functions)
        if radius is None:
            return None
        x, y = radius * math.cos(theta), radius * math.sin(theta)
        return (x, y) if relation.allows(x, y, variables, functions) else None

    return _adaptive_curve(evaluator, -math.pi, math.pi, viewport, width, height)


def sample_parametric(
    relation: ParsedRelation,
    viewport: Viewport,
    width: int,
    height: int,
    variables: dict[str, float] | None = None,
    functions: dict | None = None,
) -> list[list[tuple[float, float]]]:
    variables = variables or {}

    def evaluator(parameter: float) -> tuple[float, float] | None:
        point = relation.evaluate_parametric(parameter, variables, functions)
        return point if relation.allows(point[0], point[1], variables, functions) else None

    return _adaptive_curve(evaluator, 0.0, 2 * math.pi, viewport, width, height)


def _finite_eval_polar(relation: ParsedRelation, theta: float, variables: dict[str, float], functions: dict | None = None) -> float | None:
    try:
        value = relation.evaluate_polar(theta, variables, functions)
        return value if math.isfinite(value) else None
    except (ArithmeticError, ValueError, OverflowError, KeyError):
        return None


def sample_inequality(
    relation: ParsedRelation,
    viewport: Viewport,
    width: int,
    height: int,
    variables: dict[str, float] | None = None,
    step: int = 10,
    functions: dict | None = None,
) -> list[tuple[float, float, float, float]]:
    """merged horizontal fill rectangles for an inequality."""
    variables = variables or {}
    rectangles: list[tuple[float, float, float, float]] = []
    for top in range(0, height, step):
        bottom = min(height, top + step)
        runs: list[tuple[int, int]] = []
        run_start: int | None = None
        for left in range(0, width, step):
            right = min(width, left + step)
            x, y = viewport.screen_to_world((left + right) / 2, (top + bottom) / 2, width, height)
            value = _finite_eval(relation, x, y, variables, functions)
            inside = value is not None and relation.contains_value(value) and relation.allows(x, y, variables, functions)
            if inside and run_start is None:
                run_start = left
            if (not inside or right == width) and run_start is not None:
                runs.append((run_start, right if inside and right == width else left))
                run_start = None
        rectangles.extend((float(left), float(top), float(right), float(bottom)) for left, right in runs if right > left)
    return rectangles


def contour_implicit(
    relation: ParsedRelation,
    viewport: Viewport,
    width: int,
    height: int,
    step: int = 10,
    variables: dict[str, float] | None = None,
    functions: dict | None = None,
) -> list[tuple[tuple[float, float], tuple[float, float]]]:
    if width < 2 or height < 2:
        return []
    xs = list(range(0, width, step))
    ys = list(range(0, height, step))
    if xs[-1] != width:
        xs.append(width)
    if ys[-1] != height:
        ys.append(height)
    values: list[list[float | None]] = []
    for py in ys:
        row = []
        for px in xs:
            x, y = viewport.screen_to_world(px, py, width, height)
            row.append(_finite_eval(relation, x, y, variables, functions))
        values.append(row)

    segments: list[tuple[tuple[float, float], tuple[float, float]]] = []
    for row in range(len(ys) - 1):
        for col in range(len(xs) - 1):
            points = (
                (float(xs[col]), float(ys[row])),
                (float(xs[col + 1]), float(ys[row])),
                (float(xs[col + 1]), float(ys[row + 1])),
                (float(xs[col]), float(ys[row + 1])),
            )
            vals = (
                values[row][col], values[row][col + 1],
                values[row + 1][col + 1], values[row + 1][col],
            )
            if any(v is None for v in vals):
                continue
            numeric = tuple(float(v) for v in vals)
            edges: list[tuple[float, float] | None] = [None, None, None, None]
            for edge, (a, b) in enumerate(((0, 1), (1, 2), (2, 3), (3, 0))):
                va, vb = numeric[a], numeric[b]
                if (va < 0) != (vb < 0):
                    t = va / (va - vb)
                    ax, ay = points[a]
                    bx, by = points[b]
                    edges[edge] = (ax + t * (bx - ax), ay + t * (by - ay))
            crossed = [i for i, point in enumerate(edges) if point is not None]
            if len(crossed) == 2:
                segments.append((edges[crossed[0]], edges[crossed[1]]))  # type: ignore[arg-type]
            elif len(crossed) == 4:
                cx = (points[0][0] + points[2][0]) / 2
                cy = (points[0][1] + points[2][1]) / 2
                wx, wy = viewport.screen_to_world(cx, cy, width, height)
                center = _finite_eval(relation, wx, wy, variables, functions)
                if center is None:
                    continue
                pairs = ((0, 3), (1, 2)) if (center < 0) == (numeric[0] < 0) else ((0, 1), (2, 3))
                for first, second in pairs:
                    segments.append((edges[first], edges[second]))  # type: ignore[arg-type]
    return segments


def nice_tick_step(world_span: float, target_ticks: int = 9) -> float:
    """readable 1/2/5 power-of-ten tick step."""
    raw = max(world_span / max(target_ticks, 1), 1e-12)
    power = 10 ** math.floor(math.log10(raw))
    scaled = raw / power
    multiplier = 1 if scaled <= 1 else 2 if scaled <= 2 else 5 if scaled <= 5 else 10
    return multiplier * power


def flatten_segments(segments: Iterable[tuple[tuple[float, float], tuple[float, float]]]) -> list[float]:
    return [coordinate for segment in segments for point in segment for coordinate in point]


Segment = tuple[tuple[float, float], tuple[float, float]]


def find_axis_crossings(curves: list[list[Segment]], axis_y: float, width: float, merge_distance: float = 5.0) -> list[tuple[float, float]]:
    """visible x-axis crossings interpolated from sampled curve segments."""
    roots: list[tuple[float, float]] = []

    def add(root_x: float) -> None:
        if 0 <= root_x <= width and all(abs(root_x - old_x) > merge_distance for old_x, _ in roots):
            roots.append((root_x, axis_y))

    for curve in curves:
        for (x1, y1), (x2, y2) in curve:
            if y1 == y2:
                continue
            if y1 == axis_y:
                add(x1)
            if y2 == axis_y:
                add(x2)
            if (y1 <= axis_y < y2) or (y2 <= axis_y < y1):
                fraction = (axis_y - y1) / (y2 - y1)
                add(x1 + fraction * (x2 - x1))
    return roots


def snap_to_nearest_point(
    position: tuple[float, float],
    points: list[tuple[float, float]],
    radius: float = 12.0,
) -> tuple[float, float] | None:
    """return a nearby plotted point, if it lies within the screen-space radius."""
    radius_squared = radius * radius
    nearest = min(
        points,
        key=lambda point: (point[0] - position[0]) ** 2 + (point[1] - position[1]) ** 2,
        default=None,
    )
    if nearest is None:
        return None
    distance_squared = (nearest[0] - position[0]) ** 2 + (nearest[1] - position[1]) ** 2
    return nearest if distance_squared <= radius_squared else None


def stitch_segments(segments: list[Segment], precision: int = 4) -> list[list[tuple[float, float]]]:
    """join marching-squares fragments into polylines."""
    if not segments:
        return []

    def key(point: tuple[float, float]) -> tuple[float, float]:
        return (round(point[0], precision), round(point[1], precision))

    endpoints: dict[tuple[float, float], set[int]] = {}
    for index, (first, second) in enumerate(segments):
        endpoints.setdefault(key(first), set()).add(index)
        endpoints.setdefault(key(second), set()).add(index)

    unused = set(range(len(segments)))
    paths: list[list[tuple[float, float]]] = []
    while unused:
        index = unused.pop()
        first, second = segments[index]
        path = [first, second]
        for at_start in (False, True):
            while True:
                endpoint = path[0] if at_start else path[-1]
                candidates = endpoints.get(key(endpoint), set()) & unused
                if not candidates:
                    break
                next_index = candidates.pop()
                unused.remove(next_index)
                next_first, next_second = segments[next_index]
                next_point = next_second if key(next_first) == key(endpoint) else next_first
                if at_start:
                    path.insert(0, next_point)
                else:
                    path.append(next_point)
        paths.append(path)
    return paths


def refine_intersection(
    point: tuple[float, float],
    first: tuple[ParsedRelation, dict, dict],
    second: tuple[ParsedRelation, dict, dict],
    viewport: Viewport,
    width: int,
    height: int,
) -> tuple[float, float]:
    """improve a sampled crossing using the two equations when possible."""
    if first[0].kind not in ("explicit", "implicit", "inequality") or second[0].kind not in ("explicit", "implicit", "inequality"):
        return point

    def residual(source: tuple[ParsedRelation, dict, dict], x: float, y: float) -> float | None:
        relation, variables, functions = source
        try:
            if not relation.allows(x, y, variables, functions):
                return None
            value = relation.evaluate(x, y, variables, functions)
            result = y - value if relation.kind == "explicit" else value
            return result if math.isfinite(result) else None
        except (ArithmeticError, ValueError, OverflowError, KeyError, TypeError):
            return None

    initial_x, initial_y = viewport.screen_to_world(*point, width, height)
    x, y = initial_x, initial_y
    for _ in range(8):
        values = (residual(first, x, y), residual(second, x, y))
        if any(value is None for value in values):
            break
        first_value, second_value = values
        if max(abs(first_value), abs(second_value)) < 1e-9:
            return viewport.world_to_screen(x, y, width, height)
        step_x = 1e-5 * max(1.0, abs(x))
        step_y = 1e-5 * max(1.0, abs(y))
        x_plus = (residual(first, x + step_x, y), residual(second, x + step_x, y))
        x_minus = (residual(first, x - step_x, y), residual(second, x - step_x, y))
        y_plus = (residual(first, x, y + step_y), residual(second, x, y + step_y))
        y_minus = (residual(first, x, y - step_y), residual(second, x, y - step_y))
        if any(value is None for pair in (x_plus, x_minus, y_plus, y_minus) for value in pair):
            break
        a = (x_plus[0] - x_minus[0]) / (2 * step_x)
        b = (y_plus[0] - y_minus[0]) / (2 * step_y)
        c = (x_plus[1] - x_minus[1]) / (2 * step_x)
        d = (y_plus[1] - y_minus[1]) / (2 * step_y)
        determinant = a * d - b * c
        if abs(determinant) < 1e-12:
            break
        x += (-first_value * d + b * second_value) / determinant
        y += (c * first_value - a * second_value) / determinant
        refined_px, refined_py = viewport.world_to_screen(x, y, width, height)
        if not all(math.isfinite(value) for value in (refined_px, refined_py)) or math.hypot(refined_px - point[0], refined_py - point[1]) > 8:
            break
    return point


def find_intersections(
    curves: list[list[Segment]],
    cell_size: int = 24,
    merge_distance: float = 6.0,
    refine: Callable[[int, int, tuple[float, float]], tuple[float, float]] | None = None,
) -> list[tuple[float, float]]:
    """distinct crossings between separately sampled curves."""
    buckets: list[dict[tuple[int, int], list[tuple[int, Segment]]]] = []
    for curve in curves:
        index: dict[tuple[int, int], list[tuple[int, Segment]]] = {}
        for segment_index, segment in enumerate(curve):
            (x1, y1), (x2, y2) = segment
            for cx in range(math.floor(min(x1, x2) / cell_size), math.floor(max(x1, x2) / cell_size) + 1):
                for cy in range(math.floor(min(y1, y2) / cell_size), math.floor(max(y1, y2) / cell_size) + 1):
                    index.setdefault((cx, cy), []).append((segment_index, segment))
        buckets.append(index)

    found: list[tuple[float, float]] = []
    for first_curve in range(len(curves)):
        for second_curve in range(first_curve + 1, len(curves)):
            first_index = buckets[first_curve]
            seen_pairs: set[tuple[int, int]] = set()
            for second_cell, second_records in buckets[second_curve].items():
                for first_record in first_index.get(second_cell, ()):
                    first_id, first_segment = first_record
                    for second_id, second_segment in second_records:
                        pair = (first_id, second_id)
                        if pair in seen_pairs:
                            continue
                        seen_pairs.add(pair)
                        point = _segment_crossing(first_segment, second_segment)
                        if point is not None:
                            found.append(refine(first_curve, second_curve, point) if refine is not None else point)

    merged: list[tuple[float, float]] = []
    threshold2 = merge_distance * merge_distance
    for point in found:
        if all((point[0] - old[0]) ** 2 + (point[1] - old[1]) ** 2 > threshold2 for old in merged):
            merged.append(point)
    return merged


def _segment_crossing(first: Segment, second: Segment) -> tuple[float, float] | None:
    (px, py), (p2x, p2y) = first
    (qx, qy), (q2x, q2y) = second
    rx, ry = p2x - px, p2y - py
    sx, sy = q2x - qx, q2y - qy
    denominator = rx * sy - ry * sx
    if abs(denominator) < 1e-10:
        return None
    qpx, qpy = qx - px, qy - py
    t = (qpx * sy - qpy * sx) / denominator
    u = (qpx * ry - qpy * rx) / denominator
    if -1e-9 <= t <= 1 + 1e-9 and -1e-9 <= u <= 1 + 1e-9:
        return (px + t * rx, py + t * ry)
    return None
