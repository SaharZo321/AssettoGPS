"""Build the small offline OSM road extract used by SRP Navigation Map.

Input is a JSON response from ``scripts/srp_motorways.overpassql``.  The
generated GeoJSON keeps OSM way direction and the tags needed for future
routing, but excludes unrelated motorways outside the SRP footprint.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


SRP_BOUNDS = {
    "south": 35.425,
    "west": 139.600,
    "north": 35.705,
    "east": 139.840,
}

# AssettoServer documents these as the official SRP teleport locations.  Each
# point is paired with the corresponding named feature in OpenStreetMap.  SRP
# is not a geographically exact copy of Tokyo, so the browser applies a local
# correction around these controls instead of assuming one global transform.
CALIBRATION_ANCHORS = [
    {"name": "Shibaura PA", "ac": [1099.0, -4657.0], "osm": [139.7575705, 35.6439428]},
    {"name": "Tatsumi PA", "ac": [5850.9, -4644.5], "osm": [139.8157161, 35.6452334]},
    {"name": "Daishi PA", "ac": [-308.4, 6150.8], "osm": [139.7417519, 35.5391925]},
    {"name": "Heiwajima PA North", "ac": [-234.9, 1354.0], "osm": [139.7422560, 35.5862328]},
    {"name": "Heiwajima PA South", "ac": [-141.2, 1463.4], "osm": [139.7437855, 35.5842628]},
    {"name": "Yoyogi PA", "ac": [-4314.3, -8882.8], "osm": [139.6981305, 35.6811941]},
    {"name": "Kinko JCT", "ac": [-10850.2, 13419.3], "osm": [139.6218500, 35.4679211]},
    {"name": "Edobashi JCT", "ac": [2507.7, -9224.5], "osm": [139.7770931, 35.6848010]},
    {"name": "Ginza", "ac": [2179.8, -7541.2], "osm": [139.7717151, 35.6712636]},
    {"name": "Haneda Airport", "ac": [3271.8, 4285.3], "osm": [139.7794865, 35.5587246]},
    {"name": "Kitanomaru", "ac": [775.2, -9918.1], "osm": [139.7548780, 35.6909471]},
    {"name": "Fukuzumi", "ac": [4523.5, -8205.2], "osm": [139.7953062, 35.6744747]},
    {"name": "Shibakoen Outer", "ac": [312.0, -5719.7], "osm": [139.7499173, 35.6531722]},
    {"name": "Shibakoen Inner", "ac": [96.4, -5835.9], "osm": [139.7459029, 35.6544714]},
    {"name": "Honmoku JCT", "ac": [-7077.5, 16312.4], "osm": [139.6612276, 35.4400134]},
]


def solve_3x3(matrix: list[list[float]], vector: list[float]) -> list[float]:
    augmented = [matrix[index][:] + [vector[index]] for index in range(3)]
    for column in range(3):
        pivot = max(range(column, 3), key=lambda row: abs(augmented[row][column]))
        augmented[column], augmented[pivot] = augmented[pivot], augmented[column]
        divisor = augmented[column][column]
        if abs(divisor) < 1e-12:
            raise ValueError("Calibration anchors do not define a stable affine transform")
        for item in range(column, 4):
            augmented[column][item] /= divisor
        for row in range(3):
            if row == column:
                continue
            factor = augmented[row][column]
            for item in range(column, 4):
                augmented[row][item] -= factor * augmented[column][item]
    return [augmented[index][3] for index in range(3)]


def fit_affine(target_index: int) -> list[float]:
    inputs = [[anchor["ac"][0], anchor["ac"][1], 1.0] for anchor in CALIBRATION_ANCHORS]
    normal = [
        [sum(row[i] * row[j] for row in inputs) for j in range(3)]
        for i in range(3)
    ]
    target = [
        sum(row[i] * anchor["osm"][target_index] for row, anchor in zip(inputs, CALIBRATION_ANCHORS))
        for i in range(3)
    ]
    return solve_3x3(normal, target)


def build_calibration() -> dict[str, Any]:
    longitude = fit_affine(0)
    latitude = fit_affine(1)
    anchors = []
    for anchor in CALIBRATION_ANCHORS:
        x, z = anchor["ac"]
        predicted = [
            longitude[0] * x + longitude[1] * z + longitude[2],
            latitude[0] * x + latitude[1] * z + latitude[2],
        ]
        anchors.append({**anchor, "residual": [
            anchor["osm"][0] - predicted[0],
            anchor["osm"][1] - predicted[1],
        ]})
    return {
        "schemaVersion": 1,
        "method": "affine-with-local-idw-correction",
        "affine": {"longitude": longitude, "latitude": latitude},
        "anchors": anchors,
        "notes": "SRP road geometry differs locally from present-day Tokyo; map matching remains best-effort.",
    }


def coordinate_in_bounds(coordinate: list[float]) -> bool:
    longitude, latitude = coordinate
    return (
        SRP_BOUNDS["west"] <= longitude <= SRP_BOUNDS["east"]
        and SRP_BOUNDS["south"] <= latitude <= SRP_BOUNDS["north"]
    )


def way_to_feature(way: dict[str, Any]) -> dict[str, Any] | None:
    geometry = way.get("geometry") or []
    coordinates = [[point["lon"], point["lat"]] for point in geometry]
    if len(coordinates) < 2 or not any(coordinate_in_bounds(point) for point in coordinates):
        return None

    tags = way.get("tags") or {}
    properties = {
        "osm_id": way["id"],
        "highway": tags.get("highway", "motorway"),
        "oneway": tags.get("oneway", "yes"),
        "name": tags.get("name") or tags.get("name:en") or "",
        "name_en": tags.get("name:en") or "",
        "ref": tags.get("ref") or "",
        "destination": tags.get("destination") or tags.get("destination:en") or "",
        "maxspeed": tags.get("maxspeed") or "",
        "bridge": tags.get("bridge") or "",
        "tunnel": tags.get("tunnel") or "",
        "layer": tags.get("layer") or "0",
    }
    return {
        "type": "Feature",
        "id": way["id"],
        "properties": properties,
        "geometry": {"type": "LineString", "coordinates": coordinates},
    }


def build_roads(source: Path) -> dict[str, Any]:
    data = json.loads(source.read_text(encoding="utf-8"))
    features = []
    for element in data.get("elements", []):
        if element.get("type") != "way":
            continue
        feature = way_to_feature(element)
        if feature is not None:
            features.append(feature)
    return {
        "type": "FeatureCollection",
        "attribution": "Copyright OpenStreetMap contributors, ODbL 1.0",
        "bounds": SRP_BOUNDS,
        "features": features,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path, help="Overpass JSON response")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("frontend/assets/maps/srp-osm-roads.geojson"),
    )
    parser.add_argument(
        "--calibration-output",
        type=Path,
        default=Path("frontend/assets/maps/srp-osm-calibration.json"),
    )
    args = parser.parse_args()

    roads = build_roads(args.source)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(roads, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    args.calibration_output.write_text(
        json.dumps(build_calibration(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote {len(roads['features'])} directed OSM ways to {args.output}")


if __name__ == "__main__":
    main()
