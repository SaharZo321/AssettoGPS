"""Audit the shipped SRP directed-road graph and its golden routes."""

from __future__ import annotations

import argparse
import heapq
import json
import math
from collections import defaultdict
from pathlib import Path


DEFAULT_ASSET = Path("frontend/assets/maps/srp-traffic-lanes.geojson")
SHIBUYA_TAKIGICHO = (-2171.6, -6448.0, 36.8)
SHIBUYA_HEADING = 72.0
SHINJUKU_STATION = (-4244.1, -10016.8)


def angular_difference(left: float, right: float) -> float:
    return abs((left - right + 180) % 360 - 180)


class RoutingAudit:
    def __init__(self, asset: Path):
        self.data = json.loads(asset.read_text(encoding="utf-8"))
        space = self.data["coordinateSpace"]
        self.origin_lon, self.origin_lat = space["origin"]
        self.lon_scale = space["metersPerLongitudeDegree"]
        self.lat_scale = space["metersPerLatitudeDegree"]
        self.nodes: dict[str, tuple[float, float, float]] = {}
        self.edges: dict[str, list[tuple[str, float, dict]]] = defaultdict(list)
        self.reverse_edges: dict[str, list[str]] = defaultdict(list)
        self.segments: list[dict] = []
        self.feature_node_keys: set[str] = set()
        self._build()

    def ac(self, point) -> tuple[float, float, float]:
        return (
            (point[0] - self.origin_lon) * self.lon_scale,
            (self.origin_lat - point[1]) * self.lat_scale,
            float(point[2] if len(point) > 2 else 0),
        )

    @staticmethod
    def key(point) -> str:
        elevation = point[2] if len(point) > 2 else 0
        return f"{float(point[0]):.7f},{float(point[1]):.7f},{float(elevation):.2f}"

    @staticmethod
    def distance(left, right) -> float:
        return math.hypot(left[0] - right[0], left[1] - right[1])

    @staticmethod
    def project(point, start, end):
        dx, dz = end[0] - start[0], end[1] - start[1]
        length_squared = dx * dx + dz * dz
        amount = 0.0 if not length_squared else max(
            0.0,
            min(
                1.0,
                ((point[0] - start[0]) * dx + (point[1] - start[1]) * dz)
                / length_squared,
            ),
        )
        projected = (start[0] + dx * amount, start[1] + dz * amount)
        return RoutingAudit.distance(point, projected), amount, projected

    def _add_edge(self, start_geo, end_geo, properties):
        start_key, end_key = self.key(start_geo), self.key(end_geo)
        start, end = self.ac(start_geo), self.ac(end_geo)
        self.nodes[start_key], self.nodes[end_key] = start, end
        self.edges[start_key].append((end_key, self.distance(start, end), properties))
        self.edges.setdefault(end_key, [])
        self.reverse_edges[end_key].append(start_key)
        self.reverse_edges.setdefault(start_key, [])

    def _build(self):
        for feature in self.data["features"]:
            coordinates = feature["geometry"]["coordinates"]
            properties = feature["properties"]
            lane_id = properties["lane_id"]
            for point in coordinates:
                self.feature_node_keys.add(self.key(point))
            for index, (start_geo, end_geo) in enumerate(
                zip(coordinates, coordinates[1:])
            ):
                self._add_edge(start_geo, end_geo, properties)
                start, end = self.ac(start_geo), self.ac(end_geo)
                self.segments.append(
                    {
                        "lane": lane_id,
                        "index": index,
                        "start": start,
                        "end": end,
                        "end_key": self.key(end_geo),
                        "bearing": math.degrees(
                            math.atan2(end[0] - start[0], end[1] - start[1])
                        ),
                    }
                )
        for connection in self.data["routeConnections"]:
            self._add_edge(
                connection[:3],
                connection[3:6],
                {
                    "connector": True,
                    "from_lane_id": connection[6],
                    "to_lane_id": connection[7],
                    "intersection_id": connection[8],
                },
            )

    def route_candidates(self, point, bearing: float, elevation: float):
        candidates = []
        for segment in self.segments:
            distance, amount, projected = self.project(point, segment["start"], segment["end"])
            direction = angular_difference(bearing, segment["bearing"])
            projected_elevation = segment["start"][2] + (
                segment["end"][2] - segment["start"][2]
            ) * amount
            elevation_difference = abs(elevation - projected_elevation)
            if distance > 120 or direction > 90 or elevation_difference > 12:
                continue
            score = distance * 3 + direction * 0.35 + elevation_difference * 4
            candidate = {
                **segment,
                "distance": distance,
                "amount": amount,
                "projected": projected,
                "direction_difference": direction,
                "elevation_difference": elevation_difference,
                "score": score,
            }
            candidates.append(candidate)
        candidates.sort(key=lambda item: item["score"])
        if not candidates:
            return []
        primary = candidates[0]
        return [
            candidate
            for candidate in candidates
            if candidate["distance"] <= min(45, primary["distance"] + 12)
            and candidate["score"] <= primary["score"] + 20
            and candidate["elevation_difference"]
            <= min(12, primary["elevation_difference"] + 3)
            and candidate["direction_difference"]
            <= primary["direction_difference"] + 20
        ]

    def plan_route(self, point, bearing: float, elevation: float, destination):
        best = None
        seen_starts = set()
        for match in self.route_candidates(point, bearing, elevation):
            if match["end_key"] in seen_starts:
                continue
            seen_starts.add(match["end_key"])
            route = self.route(match, destination)
            if route is None:
                continue
            score = (
                route["distance_m"]
                + match["distance"] * 5
                + match["direction_difference"] * 1.5
                + match["elevation_difference"] * 8
            )
            if best is None or score < best["score"]:
                best = {"route": route, "match": match, "score": score}
        return best

    def route(self, start_match, destination):
        candidates = sorted(
            (self.distance(destination, point), node_key)
            for node_key, point in self.nodes.items()
        )
        threshold = min(1500, candidates[0][0] + 75)
        destination_by_key = {
            node_key: snap for snap, node_key in candidates if snap <= threshold
        }
        start_key = start_match["end_key"]
        start_cost = self.distance(start_match["projected"], self.nodes[start_key])
        costs = {start_key: start_cost}
        previous = {}
        queue = [(start_cost, start_key)]
        chosen = None
        best_score = math.inf
        while queue:
            cost, current = heapq.heappop(queue)
            if cost != costs[current]:
                continue
            if cost > best_score:
                break
            if current in destination_by_key:
                score = cost + destination_by_key[current] * 3
                if score < best_score:
                    chosen, best_score = current, score
            for following, length, properties in self.edges[current]:
                candidate = cost + length
                if candidate >= costs.get(following, math.inf):
                    continue
                costs[following] = candidate
                previous[following] = (current, properties)
                heapq.heappush(queue, (candidate, following))
        if chosen is None:
            return None
        keys = [chosen]
        edge_properties = []
        while keys[-1] != start_key:
            prior, properties = previous[keys[-1]]
            keys.append(prior)
            edge_properties.append(properties)
        edge_properties.reverse()
        transitions = [
            (item["from_lane_id"], item["to_lane_id"])
            for item in edge_properties
            if item.get("connector")
        ]
        return {
            "distance_m": costs[chosen],
            "destination_snap_m": destination_by_key[chosen],
            "transitions": transitions,
        }

    def component_sizes(self):
        visited = set()
        finish_order = []
        for root in self.nodes:
            if root in visited:
                continue
            stack = [(root, False)]
            while stack:
                node, expanded = stack.pop()
                if expanded:
                    finish_order.append(node)
                    continue
                if node in visited:
                    continue
                visited.add(node)
                stack.append((node, True))
                stack.extend((target, False) for target, _, _ in self.edges[node])
        visited.clear()
        sizes = []
        for root in reversed(finish_order):
            if root in visited:
                continue
            size = 0
            stack = [root]
            visited.add(root)
            while stack:
                node = stack.pop()
                size += 1
                for source in self.reverse_edges[node]:
                    if source not in visited:
                        visited.add(source)
                        stack.append(source)
            sizes.append(size)
        return sorted(sizes, reverse=True)

    def run(self):
        missing_connector_points = []
        connector_lengths = []
        for index, connection in enumerate(self.data["routeConnections"]):
            if self.key(connection[:3]) not in self.feature_node_keys:
                missing_connector_points.append((index, "from"))
            if self.key(connection[3:6]) not in self.feature_node_keys:
                missing_connector_points.append((index, "to"))
            connector_lengths.append(self.distance(self.ac(connection[:3]), self.ac(connection[3:6])))

        yoyogi = next(item for item in self.data["destinations"] if item["name"] == "Yoyogi PA")
        golden_plan = self.plan_route(
            SHIBUYA_TAKIGICHO,
            SHIBUYA_HEADING,
            SHIBUYA_TAKIGICHO[2],
            tuple(yoyogi["ac"]),
        )
        if golden_plan is None:
            raise AssertionError("Shibuya has no heading/elevation-compatible route origin")
        start = golden_plan["match"]
        local_starts = self.route_candidates(
            SHIBUYA_TAKIGICHO,
            SHIBUYA_HEADING,
            SHIBUYA_TAKIGICHO[2],
        )
        destination_results = {}
        for destination in self.data["destinations"]:
            plan = self.plan_route(
                SHIBUYA_TAKIGICHO,
                SHIBUYA_HEADING,
                SHIBUYA_TAKIGICHO[2],
                tuple(destination["ac"]),
            )
            destination_results[destination["name"]] = (
                None if plan is None else round(plan["route"]["distance_m"], 1)
            )

        golden = golden_plan["route"]
        station_plan = self.plan_route(
            SHIBUYA_TAKIGICHO,
            SHIBUYA_HEADING,
            SHIBUYA_TAKIGICHO[2],
            SHINJUKU_STATION,
        )
        station = None if station_plan is None else station_plan["route"]
        if missing_connector_points:
            raise AssertionError(f"connector endpoints missing from lanes: {missing_connector_points[:5]}")
        if start["lane"] != 271:
            raise AssertionError(f"Shibuya route origin regressed to lane {start['lane']}, expected 271")
        if not local_starts or local_starts[0]["lane"] != 269:
            raise AssertionError(f"Shibuya primary directed match regressed: {local_starts[:1]}")
        if any(item["distance"] > 45 for item in local_starts):
            raise AssertionError(f"route starts escaped the local carriageway band: {local_starts}")
        if golden is None or not 8000 <= golden["distance_m"] <= 9000:
            raise AssertionError(f"unexpected Shibuya to Yoyogi route: {golden}")
        for transition in ((271, 264), (443, 454), (456, 458)):
            if transition not in golden["transitions"]:
                raise AssertionError(f"golden route is missing transition {transition}")
        if station is None or not 11000 <= station["distance_m"] <= 12500:
            raise AssertionError(f"unexpected Shibuya to Shinjuku route: {station}")
        if station["destination_snap_m"] > 20:
            raise AssertionError(f"Shinjuku destination snap regressed: {station}")
        if (443, 454) not in station["transitions"]:
            raise AssertionError("Shibuya to Shinjuku route is missing transition (443, 454)")
        unreachable = [name for name, distance in destination_results.items() if distance is None]
        if unreachable:
            raise AssertionError(f"destinations unreachable from Shibuya: {unreachable}")

        components = self.component_sizes()
        return {
            "nodes": len(self.nodes),
            "directedEdges": sum(len(items) for items in self.edges.values()),
            "routeConnections": len(self.data["routeConnections"]),
            "missingConnectorPoints": 0,
            "maxConnectorLengthM": round(max(connector_lengths), 2),
            "stronglyConnectedComponents": len(components),
            "largestComponentNodes": components[0],
            "shibuyaOrigin": {
                "lane": start["lane"],
                "segment": start["index"],
                "snapM": round(start["distance"], 2),
                "headingDifferenceDeg": round(start["direction_difference"], 2),
                "elevationDifferenceM": round(start["elevation_difference"], 2),
            },
            "shibuyaToYoyogi": {
                "distanceM": round(golden["distance_m"], 1),
                "transitions": [list(item) for item in golden["transitions"]],
            },
            "shibuyaToShinjukuStation": None if station is None else {
                "distanceM": round(station["distance_m"], 1),
                "destinationSnapM": round(station["destination_snap_m"], 1),
            },
            "reachableDestinations": destination_results,
        }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("asset", nargs="?", type=Path, default=DEFAULT_ASSET)
    args = parser.parse_args()
    print(json.dumps(RoutingAudit(args.asset).run(), indent=2))


if __name__ == "__main__":
    main()
