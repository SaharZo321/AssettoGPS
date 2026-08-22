#!/usr/bin/env python3
"""Trace a transparent raster track map into a compact monochrome SVG.

The tracer follows the boundary of every sufficiently opaque pixel region and
simplifies the resulting contours. It is intentionally based on alpha rather
than color so route-colored Comfy Map images become one neutral road layer
without losing junctions, ramps, or parking-area detail.
"""

from __future__ import annotations

import argparse
import math
from pathlib import Path
from typing import Iterable

from PIL import Image


Point = tuple[int, int]
Edge = tuple[int, int, int]

DIRECTIONS: tuple[Point, ...] = (
    (1, 0),   # east
    (0, 1),   # south
    (-1, 0),  # west
    (0, -1),  # north
)


def foreground_pixels(alpha: Image.Image, threshold: int) -> set[int]:
    """Return flat pixel indexes whose alpha meets ``threshold``."""
    return {
        index
        for index, value in enumerate(alpha.tobytes())
        if value >= threshold
    }


def boundary_edges(foreground: set[int], width: int, height: int) -> set[Edge]:
    """Build clockwise pixel-boundary edges around the foreground regions."""
    edges: set[Edge] = set()
    for index in foreground:
        y, x = divmod(index, width)

        if y == 0 or index - width not in foreground:
            edges.add((x, y, 0))
        if x == width - 1 or index + 1 not in foreground:
            edges.add((x + 1, y, 1))
        if y == height - 1 or index + width not in foreground:
            edges.add((x + 1, y + 1, 2))
        if x == 0 or index - 1 not in foreground:
            edges.add((x, y + 1, 3))

    return edges


def trace_contours(edges: set[Edge]) -> list[list[Point]]:
    """Join directed boundary edges into closed contours."""
    remaining = set(edges)
    contours: list[list[Point]] = []

    while remaining:
        start = min(remaining)
        edge = start
        contour: list[Point] = []

        while edge in remaining:
            x, y, direction = edge
            remaining.remove(edge)
            contour.append((x, y))

            dx, dy = DIRECTIONS[direction]
            next_x, next_y = x + dx, y + dy

            # At a diagonal pixel contact there can be two outgoing edges.
            # Keeping the foreground on the same side means preferring a
            # right turn, then straight, then left, then backtracking.
            candidates = (
                (direction + 1) % 4,
                direction,
                (direction - 1) % 4,
                (direction + 2) % 4,
            )
            next_edge = next(
                (
                    (next_x, next_y, candidate)
                    for candidate in candidates
                    if (next_x, next_y, candidate) in remaining
                ),
                None,
            )
            if next_edge is None:
                break
            edge = next_edge

        if len(contour) >= 3:
            contours.append(contour)

    return contours


def squared_segment_distance(point: Point, start: Point, end: Point) -> float:
    """Squared distance from a point to a finite line segment."""
    px, py = point
    x1, y1 = start
    x2, y2 = end
    dx, dy = x2 - x1, y2 - y1

    if dx == 0 and dy == 0:
        return float((px - x1) ** 2 + (py - y1) ** 2)

    amount = ((px - x1) * dx + (py - y1) * dy) / (dx * dx + dy * dy)
    amount = max(0.0, min(1.0, amount))
    nearest_x = x1 + amount * dx
    nearest_y = y1 + amount * dy
    return (px - nearest_x) ** 2 + (py - nearest_y) ** 2


def simplify_open(points: list[Point], tolerance: float) -> list[Point]:
    """Iterative Ramer-Douglas-Peucker simplification for an open chain."""
    if len(points) <= 2:
        return points

    keep = {0, len(points) - 1}
    stack = [(0, len(points) - 1)]
    tolerance_squared = tolerance * tolerance

    while stack:
        first, last = stack.pop()
        furthest_index = -1
        furthest_distance = tolerance_squared

        for index in range(first + 1, last):
            distance = squared_segment_distance(
                points[index], points[first], points[last]
            )
            if distance > furthest_distance:
                furthest_distance = distance
                furthest_index = index

        if furthest_index >= 0:
            keep.add(furthest_index)
            stack.append((first, furthest_index))
            stack.append((furthest_index, last))

    return [points[index] for index in sorted(keep)]


def remove_collinear(points: list[Point]) -> list[Point]:
    """Remove the long horizontal/vertical runs produced by pixel tracing."""
    if len(points) <= 3:
        return points

    result: list[Point] = []
    count = len(points)
    for index, current in enumerate(points):
        previous = points[index - 1]
        following = points[(index + 1) % count]
        cross = (
            (current[0] - previous[0]) * (following[1] - current[1])
            - (current[1] - previous[1]) * (following[0] - current[0])
        )
        if cross != 0:
            result.append(current)

    return result if len(result) >= 3 else points


def simplify_closed(points: list[Point], tolerance: float) -> list[Point]:
    """Simplify a closed ring without creating an artificial closing seam."""
    points = remove_collinear(points)
    if len(points) <= 4:
        return points

    anchor = min(range(len(points)), key=lambda index: points[index])
    anchor_point = points[anchor]
    opposite = max(
        range(len(points)),
        key=lambda index: (
            (points[index][0] - anchor_point[0]) ** 2
            + (points[index][1] - anchor_point[1]) ** 2
        ),
    )

    if anchor > opposite:
        anchor, opposite = opposite, anchor

    first_arc = points[anchor : opposite + 1]
    second_arc = points[opposite:] + points[: anchor + 1]
    simplified = (
        simplify_open(first_arc, tolerance)[:-1]
        + simplify_open(second_arc, tolerance)[:-1]
    )
    return simplified if len(simplified) >= 3 else points


def signed_area(points: Iterable[Point]) -> float:
    points = list(points)
    return 0.5 * sum(
        x1 * y2 - x2 * y1
        for (x1, y1), (x2, y2) in zip(points, points[1:] + points[:1])
    )


def format_half_coordinate(value: int) -> str:
    """Format an integer divided by two without unnecessary decimals."""
    return str(value // 2) if value % 2 == 0 else f"{value / 2:.1f}"


def svg_path(contours: Iterable[list[Point]]) -> str:
    """Build rounded quadratic paths that smooth residual raster stair-steps."""
    commands: list[str] = []
    for contour in contours:
        first = contour[0]
        last = contour[-1]
        commands.append(
            "M"
            f"{format_half_coordinate(last[0] + first[0])} "
            f"{format_half_coordinate(last[1] + first[1])}"
        )
        for index, (x, y) in enumerate(contour):
            next_x, next_y = contour[(index + 1) % len(contour)]
            commands.append(
                f"Q{x} {y} "
                f"{format_half_coordinate(x + next_x)} "
                f"{format_half_coordinate(y + next_y)}"
            )
        commands.append("Z")
    return " ".join(commands)


def vectorize(
    source: Path,
    output: Path,
    *,
    threshold: int,
    tolerance: float,
    minimum_area: float,
) -> tuple[int, int]:
    with Image.open(source) as image:
        alpha = image.convert("RGBA").getchannel("A")
        width, height = image.size

    foreground = foreground_pixels(alpha, threshold)
    contours = trace_contours(boundary_edges(foreground, width, height))
    contours = [
        simplify_closed(contour, tolerance)
        for contour in contours
        if abs(signed_area(contour)) >= minimum_area
    ]
    contours.sort(key=lambda contour: abs(signed_area(contour)), reverse=True)

    output.parent.mkdir(parents=True, exist_ok=True)
    path_data = svg_path(contours)
    output.write_text(
        "\n".join(
            (
                '<?xml version="1.0" encoding="UTF-8"?>',
                (
                    f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" '
                    f'height="{height}" viewBox="0 0 {width} {height}" '
                    'role="img" aria-labelledby="title description">'
                ),
                "  <title id=\"title\">Shutoko Revival Project road map</title>",
                (
                    "  <desc id=\"description\">Monochrome vector road geometry "
                    "traced from the SRP Comfy Map layout.</desc>"
                ),
                (
                    "  <path id=\"roads\" fill=\"#cbd5e1\" fill-rule=\"evenodd\" "
                    "stroke=\"#111827\" stroke-width=\"1.5\" "
                    f"stroke-linejoin=\"round\" d=\"{path_data}\"/>"
                ),
                "</svg>",
                "",
            )
        ),
        encoding="utf-8",
        newline="\n",
    )
    return len(foreground), len(contours)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="Transparent PNG map to trace")
    parser.add_argument("output", type=Path, help="Destination SVG path")
    parser.add_argument(
        "--alpha-threshold",
        type=int,
        default=128,
        choices=range(1, 256),
        metavar="1-255",
    )
    parser.add_argument("--tolerance", type=float, default=1.25)
    parser.add_argument("--minimum-area", type=float, default=1.0)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    foreground_count, contour_count = vectorize(
        args.source,
        args.output,
        threshold=args.alpha_threshold,
        tolerance=args.tolerance,
        minimum_area=args.minimum_area,
    )
    print(
        f"Traced {foreground_count:,} foreground pixels into "
        f"{contour_count:,} SVG contours: {args.output}"
    )


if __name__ == "__main__":
    main()
