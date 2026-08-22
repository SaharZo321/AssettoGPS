"""Convert CSP Traffic Planner lanes into an offline MapLibre GeoJSON asset.

The input stays in Assetto Corsa's native X/Y/Z coordinate system.  Output
coordinates use a private, locally metric Mercator frame; they are deliberately
not a claim about SRP's real-world geography.  Telemetry uses the same formula
in the browser, so no external calibration or road snapping is required.
"""

from __future__ import annotations

import argparse
import heapq
import json
import math
from pathlib import Path
from typing import Any


ORIGIN_LONGITUDE = 139.75
ORIGIN_LATITUDE = 35.60
METERS_PER_LATITUDE_DEGREE = 111_320.0
METERS_PER_LONGITUDE_DEGREE = METERS_PER_LATITUDE_DEGREE * math.cos(
    math.radians(ORIGIN_LATITUDE)
)

ROLE_DEFAULTS = {
    1: ("Parking", 40),
    2: ("Secondary", 60),
    3: ("Main", 80),
    4: ("Highway", 90),
}

INTERSECTION_Y_THRESHOLD = 5.0

# These game-space landmarks are used as local route destinations.
DESTINATIONS = [
    {"name": "Shibaura PA", "ac": [1099.0, -4657.0]},
    {"name": "Tatsumi PA", "ac": [5850.9, -4644.5]},
    {"name": "Daishi PA", "ac": [-308.4, 6150.8]},
    {"name": "Heiwajima PA North", "ac": [-234.9, 1354.0]},
    {"name": "Heiwajima PA South", "ac": [-141.2, 1463.4]},
    {"name": "Yoyogi PA", "ac": [-4314.3, -8882.8]},
    {"name": "Kinko JCT", "ac": [-10850.2, 13419.3]},
    {"name": "Edobashi JCT", "ac": [2507.7, -9224.5]},
    {"name": "Ginza", "ac": [2179.8, -7541.2]},
    {"name": "Haneda Airport", "ac": [3271.8, 4285.3]},
    {"name": "Kitanomaru", "ac": [775.2, -9918.1]},
    {"name": "Fukuzumi", "ac": [4523.5, -8205.2]},
    {"name": "Shibakoen Outer", "ac": [312.0, -5719.7]},
    {"name": "Shibakoen Inner", "ac": [96.4, -5835.9]},
    {"name": "Honmoku JCT", "ac": [-7077.5, 16312.4]},
]


def game_to_lng_lat(x: float, z: float) -> list[float]:
    return [
        ORIGIN_LONGITUDE + x / METERS_PER_LONGITUDE_DEGREE,
        ORIGIN_LATITUDE - z / METERS_PER_LATITUDE_DEGREE,
    ]


def _finite_number(value: Any, label: str) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{label} must be finite")
    return number


def _point3(value: Any, label: str) -> tuple[float, float, float]:
    if not isinstance(value, list) or len(value) < 3:
        raise ValueError(f"{label} is not X/Y/Z")
    return (
        _finite_number(value[0], f"{label} x"),
        _finite_number(value[1], f"{label} y"),
        _finite_number(value[2], f"{label} z"),
    )


def _geo_point(point: tuple[float, float, float]) -> list[float]:
    longitude, latitude = game_to_lng_lat(point[0], point[2])
    return [round(longitude, 9), round(latitude, 9), round(point[1], 3)]


def _inside_intersection(
    point: tuple[float, float, float],
    polygon: list[tuple[float, float, float]],
) -> bool:
    if abs(point[1] - polygon[0][1]) > INTERSECTION_Y_THRESHOLD:
        return False
    x, z = point[0], point[2]
    inside = False
    previous = polygon[-1]
    for current in polygon:
        x1, z1 = previous[0], previous[2]
        x2, z2 = current[0], current[2]
        if (z1 > z) != (z2 > z):
            crossing_x = (x2 - x1) * (z - z1) / (z2 - z1) + x1
            if x < crossing_x:
                inside = not inside
        previous = current
    return inside


def _segment_intersection_hits(
    start: tuple[float, float, float],
    end: tuple[float, float, float],
    polygon: list[tuple[float, float, float]],
) -> list[tuple[float, tuple[float, float, float]]]:
    y_center = polygon[0][1]
    if (
        abs(start[1] - y_center) > INTERSECTION_Y_THRESHOLD
        or abs(end[1] - y_center) > INTERSECTION_Y_THRESHOLD
    ):
        return []

    dx = end[0] - start[0]
    dz = end[2] - start[2]
    hits: list[tuple[float, tuple[float, float, float]]] = []
    previous = polygon[-1]
    for current in polygon:
        edge_dx = current[0] - previous[0]
        edge_dz = current[2] - previous[2]
        denominator = dx * edge_dz - dz * edge_dx
        if abs(denominator) < 1e-9:
            previous = current
            continue
        offset_x = previous[0] - start[0]
        offset_z = previous[2] - start[2]
        t = (offset_x * edge_dz - offset_z * edge_dx) / denominator
        edge_t = (offset_x * dz - offset_z * dx) / denominator
        if -1e-8 <= t <= 1 + 1e-8 and -1e-8 <= edge_t <= 1 + 1e-8:
            t = min(1.0, max(0.0, t))
            if not any(abs(t - existing[0]) < 1e-7 for existing in hits):
                hits.append(
                    (
                        t,
                        (
                            start[0] + dx * t,
                            start[1] + (end[1] - start[1]) * t,
                            start[2] + dz * t,
                        ),
                    )
                )
        previous = current
    hits.sort(key=lambda item: item[0])
    return hits


def _intersection_links(
    points: list[tuple[float, float, float]],
    polygon: list[tuple[float, float, float]],
) -> tuple[list[dict[str, Any]], list[tuple[int, float, tuple[float, float, float]]]]:
    """Return CSP-style entry/exit pairs and line points to insert."""
    links: list[dict[str, Any]] = []
    insertions: list[tuple[int, float, tuple[float, float, float]]] = []
    inside = _inside_intersection(points[0], polygon)
    current_entry: dict[str, Any] | None = None

    for segment_index in range(len(points) - 1):
        start = points[segment_index]
        end = points[segment_index + 1]
        dx = end[0] - start[0]
        dz = end[2] - start[2]
        magnitude = math.hypot(dx, dz) or 1.0
        direction = (dx / magnitude, dz / magnitude)
        for t, point in _segment_intersection_hits(start, end, polygon):
            insertions.append((segment_index, t, point))
            crossing = {
                "point": point,
                "position": segment_index + t,
                "direction": direction,
            }
            if inside:
                links.append({"entry": current_entry, "exit": crossing})
                current_entry = None
            else:
                current_entry = crossing
            inside = not inside

    if inside:
        links.append({"entry": current_entry, "exit": None})
    return links, insertions


def _coordinates_with_insertions(
    points: list[tuple[float, float, float]],
    insertions: list[tuple[int, float, tuple[float, float, float]]],
) -> list[list[float]]:
    by_segment: dict[int, list[tuple[float, tuple[float, float, float]]]] = {}
    for segment_index, t, point in insertions:
        if 1e-7 < t < 1 - 1e-7:
            by_segment.setdefault(segment_index, []).append((t, point))

    expanded: list[tuple[float, float, float]] = []
    for segment_index, point in enumerate(points[:-1]):
        expanded.append(point)
        additions = sorted(by_segment.get(segment_index, []), key=lambda item: item[0])
        for _, inserted in additions:
            if math.dist(expanded[-1], inserted) > 1e-5:
                expanded.append(inserted)
    expanded.append(points[-1])
    return [_geo_point(point) for point in expanded]


def _route_point_key(point: list[float]) -> tuple[float, float, float]:
    return (round(point[0], 9), round(point[1], 9), round(point[2], 3))


def _route_distance(left: list[float], right: list[float]) -> float:
    latitude = math.radians((left[1] + right[1]) / 2)
    return math.hypot(
        (left[0] - right[0])
        * METERS_PER_LATITUDE_DEGREE
        * math.cos(latitude),
        (left[1] - right[1]) * METERS_PER_LATITUDE_DEGREE,
    )


def _build_mock_route(
    features: list[dict[str, Any]],
    route_connections: list[list[Any]],
) -> list[list[float]]:
    """Build a long closed route inside the largest directed lane component."""
    nodes: dict[tuple[float, float, float], list[float]] = {}
    adjacency: dict[tuple[float, float, float], list[tuple[tuple[float, float, float], float]]] = {}
    reverse: dict[tuple[float, float, float], list[tuple[float, float, float]]] = {}

    def add_edge(start: list[float], end: list[float]) -> None:
        start_key, end_key = _route_point_key(start), _route_point_key(end)
        nodes[start_key], nodes[end_key] = start, end
        adjacency.setdefault(start_key, []).append(
            (end_key, _route_distance(start, end))
        )
        adjacency.setdefault(end_key, [])
        reverse.setdefault(end_key, []).append(start_key)
        reverse.setdefault(start_key, [])

    for feature in features:
        coordinates = feature["geometry"]["coordinates"]
        for start, end in zip(coordinates, coordinates[1:]):
            add_edge(start, end)
    for connection in route_connections:
        add_edge(connection[:3], connection[3:6])

    visited: set[tuple[float, float, float]] = set()
    finish_order: list[tuple[float, float, float]] = []
    for root in nodes:
        if root in visited:
            continue
        visited.add(root)
        stack = [(root, False)]
        while stack:
            current, expanded = stack.pop()
            if expanded:
                finish_order.append(current)
                continue
            stack.append((current, True))
            for following, _ in adjacency[current]:
                if following not in visited:
                    visited.add(following)
                    stack.append((following, False))

    components: list[list[tuple[float, float, float]]] = []
    visited.clear()
    for root in reversed(finish_order):
        if root in visited:
            continue
        component: list[tuple[float, float, float]] = []
        visited.add(root)
        stack = [root]
        while stack:
            current = stack.pop()
            component.append(current)
            for previous in reverse[current]:
                if previous not in visited:
                    visited.add(previous)
                    stack.append(previous)
        components.append(component)

    component = set(max(components, key=len))

    def farthest(origin: tuple[float, float, float]) -> tuple[float, float, float]:
        origin_point = nodes[origin]
        return max(component, key=lambda item: _route_distance(origin_point, nodes[item]))

    def shortest_path(
        start: tuple[float, float, float], destination: tuple[float, float, float]
    ) -> list[tuple[float, float, float]]:
        costs = {start: 0.0}
        previous: dict[tuple[float, float, float], tuple[float, float, float]] = {}
        queue = [(0.0, start)]
        while queue:
            cost, current = heapq.heappop(queue)
            if cost != costs[current]:
                continue
            if current == destination:
                break
            for following, length in adjacency[current]:
                if following not in component:
                    continue
                candidate = cost + length
                if candidate < costs.get(following, math.inf):
                    costs[following] = candidate
                    previous[following] = current
                    heapq.heappush(queue, (candidate, following))
        route = [destination]
        while route[-1] != start:
            route.append(previous[route[-1]])
        route.reverse()
        return route

    first = next(iter(component))
    start = farthest(first)
    opposite = farthest(start)
    outbound = shortest_path(start, opposite)
    returning = shortest_path(opposite, start)
    return [nodes[item] for item in outbound + returning[1:]]


def convert_traffic_plan(data: dict[str, Any]) -> dict[str, Any]:
    lanes = data.get("lanes")
    if not isinstance(lanes, list) or not lanes:
        raise ValueError("Traffic plan must contain a non-empty lanes array")

    lane_records: list[dict[str, Any]] = []
    source_point_count = 0
    all_x: list[float] = []
    all_z: list[float] = []
    seen_lane_ids: set[int] = set()

    for lane_index, lane in enumerate(lanes):
        source_points = lane.get("points") or []
        if len(source_points) < 2:
            continue

        points = [
            _point3(point, f"Lane {lane_index} point {point_index}")
            for point_index, point in enumerate(source_points)
        ]
        length_m = sum(
            math.hypot(end[0] - start[0], end[2] - start[2])
            for start, end in zip(points, points[1:])
        )
        for x, _, z in points:
            all_x.append(x)
            all_z.append(z)

        role = int(lane.get("role") or 3)
        role_name, default_speed = ROLE_DEFAULTS.get(role, (f"Role {role}", 80))
        lane_id = int(lane.get("id", lane_index))
        if lane_id in seen_lane_ids:
            raise ValueError(f"Traffic plan contains duplicate lane ID {lane_id}")
        seen_lane_ids.add(lane_id)
        lane_records.append(
            {
                "id": lane_id,
                "points": points,
                "properties": {
                    "lane_id": lane_id,
                    "name": str(lane.get("name") or f"Lane #{lane_id}"),
                    "role": role,
                    "role_name": role_name,
                    "speed_limit": float(lane.get("speedLimit") or default_speed),
                    "priority_offset": float(lane.get("priorityOffset") or 0),
                    "oneway": "yes",
                    "length_m": round(length_m, 1),
                },
            }
        )
        source_point_count += len(points)

    if not lane_records:
        raise ValueError("Traffic plan did not contain any usable lanes")

    disallowed_transitions: list[list[int]] = []
    route_connections: list[list[Any]] = []
    lane_insertions: dict[int, list[tuple[int, float, tuple[float, float, float]]]] = {
        record["id"]: [] for record in lane_records
    }
    linked_intersection_count = 0
    for intersection_index, intersection in enumerate(data.get("intersections") or []):
        polygon = [
            _point3(point, f"Intersection {intersection_index} point {point_index}")
            for point_index, point in enumerate(intersection.get("points") or [])
        ]
        if len(polygon) < 3:
            continue
        for transition in intersection.get("disallowedTrajectories") or []:
            if isinstance(transition, list) and len(transition) >= 2:
                disallowed_transitions.append([int(transition[0]), int(transition[1])])

        polygon_min_x = min(point[0] for point in polygon)
        polygon_max_x = max(point[0] for point in polygon)
        polygon_min_z = min(point[2] for point in polygon)
        polygon_max_z = max(point[2] for point in polygon)
        links: list[dict[str, Any]] = []
        for record in lane_records:
            points = record["points"]
            if (
                max(point[0] for point in points) < polygon_min_x
                or min(point[0] for point in points) > polygon_max_x
                or max(point[2] for point in points) < polygon_min_z
                or min(point[2] for point in points) > polygon_max_z
            ):
                continue
            lane_links, insertions = _intersection_links(points, polygon)
            lane_insertions[record["id"]].extend(insertions)
            for link in lane_links:
                link["lane_id"] = record["id"]
                links.append(link)

        if links:
            linked_intersection_count += 1
        disallowed = {
            (int(pair[0]), int(pair[1]))
            for pair in intersection.get("disallowedTrajectories") or []
            if isinstance(pair, list) and len(pair) >= 2
        }
        intersection_id = int(intersection.get("id", intersection_index))
        for entry_link in links:
            entry = entry_link["entry"]
            if entry is None:
                continue
            for exit_link in links:
                exit_ = exit_link["exit"]
                if exit_ is None or entry_link["lane_id"] == exit_link["lane_id"]:
                    continue
                lane_pair = (entry_link["lane_id"], exit_link["lane_id"])
                if lane_pair in disallowed:
                    continue
                direction_dot = (
                    entry["direction"][0] * exit_["direction"][0]
                    + entry["direction"][1] * exit_["direction"][1]
                )
                if direction_dot < math.cos(math.radians(145)):
                    continue
                route_connections.append(
                    [
                        *_geo_point(entry["point"]),
                        *_geo_point(exit_["point"]),
                        entry_link["lane_id"],
                        exit_link["lane_id"],
                        intersection_id,
                    ]
                )

    features: list[dict[str, Any]] = []
    expanded_point_count = 0
    for record in lane_records:
        coordinates = _coordinates_with_insertions(
            record["points"], lane_insertions[record["id"]]
        )
        expanded_point_count += len(coordinates)
        features.append(
            {
                "type": "Feature",
                "id": record["id"],
                "properties": record["properties"],
                "geometry": {"type": "LineString", "coordinates": coordinates},
            }
        )

    output = {
        "type": "FeatureCollection",
        "schemaVersion": 1,
        "name": "SRP native traffic lanes (prototype)",
        "coordinateSpace": {
            "type": "srp-local-mercator",
            "origin": [ORIGIN_LONGITUDE, ORIGIN_LATITUDE],
            "metersPerLongitudeDegree": METERS_PER_LONGITUDE_DEGREE,
            "metersPerLatitudeDegree": METERS_PER_LATITUDE_DEGREE,
            "longitudeAxis": "+x",
            "latitudeAxis": "-z",
        },
        "boundsAc": [min(all_x), min(all_z), max(all_x), max(all_z)],
        "destinations": DESTINATIONS,
        "disallowedTransitions": disallowed_transitions,
        "routeConnections": route_connections,
        "attribution": "Prototype lane geometry adapted from Bardaff's SRP Traffic Plan 1.02",
        "sourceUrl": "https://www.overtake.gg/downloads/traffic-plan-shutoko-revival-project.57715/",
        "redistribution": "Prototype evaluation only; confirm permission with the data author before public redistribution.",
        "statistics": {
            "laneCount": len(features),
            "pointCount": expanded_point_count,
            "sourcePointCount": source_point_count,
            "intersectionCount": len(data.get("intersections") or []),
            "linkedIntersectionCount": linked_intersection_count,
            "routeConnectionCount": len(route_connections),
        },
        "features": features,
    }
    return output


def build_development_route_asset(traffic_data: dict[str, Any]) -> dict[str, Any]:
    """Build generated-driving data kept outside the public frontend bundle."""
    route = _build_mock_route(
        traffic_data["features"], traffic_data["routeConnections"]
    )
    route_length_m = sum(
        _route_distance(start, end) for start, end in zip(route, route[1:])
    )
    return {
        "schemaVersion": 1,
        "coordinateSpace": traffic_data["coordinateSpace"],
        "route": route,
        "statistics": {
            "pointCount": len(route),
            "lengthM": round(route_length_m, 1),
        },
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="CSP Traffic Planner traffic.json")
    parser.add_argument("output", type=Path, help="Output MapLibre GeoJSON path")
    parser.add_argument(
        "--development-route-output",
        type=Path,
        help="Optional generated-driving route for the development server",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    data = json.loads(args.input.read_text(encoding="utf-8-sig"))
    output = convert_traffic_plan(data)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(output, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    if args.development_route_output:
        route_output = build_development_route_asset(output)
        args.development_route_output.parent.mkdir(parents=True, exist_ok=True)
        args.development_route_output.write_text(
            json.dumps(route_output, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )
        route_stats = route_output["statistics"]
        print(
            f"Wrote {route_stats['pointCount']} development route points / "
            f"{route_stats['lengthM']} meters to {args.development_route_output}"
        )
    stats = output["statistics"]
    print(
        f"Wrote {stats['laneCount']} directed lanes / {stats['pointCount']} points "
        f"to {args.output}"
    )


if __name__ == "__main__":
    main()
