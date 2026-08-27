import asyncio
import contextlib
import io
import json
import math
import re
import sys
import uuid
from pathlib import Path
from unittest import mock

import pytest
from fastapi import HTTPException
from starlette.requests import Request


REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = REPO_ROOT / "backend"
SCRIPTS_DIR = REPO_ROOT / "scripts"
sys.path.insert(0, str(BACKEND_DIR))
sys.path.insert(0, str(SCRIPTS_DIR))

import ac_shared_memory
import ac_track_finder
import mock_telemetry
import server
import verify_srp_routing


def make_request(host: str, control_header: str | None = None) -> Request:
    headers = []
    if control_header is not None:
        headers.append((b"x-assettogps-control", control_header.encode("ascii")))
    return Request(
        {
            "type": "http",
            "method": "POST",
            "scheme": "http",
            "path": "/",
            "raw_path": b"/",
            "query_string": b"",
            "headers": headers,
            "client": (host, 12345),
            "server": ("127.0.0.1", 8080),
        }
    )


def test_missing_mapping_is_not_created_by_connect():
    prefix = f"AssettoGPS.test.{uuid.uuid4()}"
    names = (f"{prefix}.physics", f"{prefix}.graphics", f"{prefix}.static")

    with mock.patch.object(ac_shared_memory, "AC_SHARED_MEMORY_NAMES", names):
        reader = ac_shared_memory.AssettoCorsaSharedMemory()
        assert not reader.connect()
        assert not reader.is_connected
        assert all(not ac_shared_memory.named_mapping_exists(name) for name in names)


def test_heading_matches_forward_motion_and_velocity():
    with mock.patch.object(mock_telemetry.time, "time", return_value=1_000.0):
        generator = mock_telemetry.MockTelemetryGenerator()
    with mock.patch.object(mock_telemetry.time, "time", return_value=1_020.0):
        first = generator.get_frame()
    with mock.patch.object(mock_telemetry.time, "time", return_value=1_020.02):
        second = generator.get_frame()

    dx = second["carPosition"][0] - first["carPosition"][0]
    dz = second["carPosition"][2] - first["carPosition"][2]
    motion_heading = math.atan2(dx, dz)
    velocity_heading = math.atan2(first["velocity"][0], first["velocity"][2])

    def angle_error(left: float, right: float) -> float:
        return abs((left - right + math.pi) % (2 * math.pi) - math.pi)

    assert angle_error(first["headingRad"], motion_heading) < math.radians(2)
    assert angle_error(first["headingRad"], velocity_heading) < math.radians(0.1)


def test_native_mock_route_uses_bundled_game_lanes():
    route_asset = BACKEND_DIR / "dev_assets" / "srp-development-route.json"
    route_data = json.loads(route_asset.read_text(encoding="utf-8"))
    with mock.patch.object(mock_telemetry.time, "time", return_value=1_000.0):
        generator = mock_telemetry.MockTelemetryGenerator(route_asset)
    with mock.patch.object(mock_telemetry.time, "time", return_value=1_020.0):
        frame = generator.get_frame()

    assert generator.native_route_length > 60_000
    assert frame["trackConfig"] == "main_layout"
    assert frame["speedKmh"] == 180.0
    assert math.hypot(frame["velocity"][0], frame["velocity"][2]) == pytest.approx(50.0, abs=0.05)
    assert len(frame["carPosition"]) == 3
    assert all(math.isfinite(value) for value in frame["carPosition"])
    longitude, latitude, _ = route_data["route"][0]
    coordinate_space = route_data["coordinateSpace"]
    origin_longitude, origin_latitude = coordinate_space["origin"]
    assert generator.native_route[0][0] == pytest.approx(
        (longitude - origin_longitude) * coordinate_space["metersPerLongitudeDegree"]
    )
    assert generator.native_route[0][2] == pytest.approx(
        (origin_latitude - latitude) * coordinate_space["metersPerLatitudeDegree"]
    )


@pytest.fixture
def restore_environment_state():
    original_environment = server.environment_state.copy()
    original_environment_updated_at = server.environment_updated_at
    yield
    server.environment_state.clear()
    server.environment_state.update(original_environment)
    server.environment_updated_at = original_environment_updated_at


def test_custom_port_argument():
    args = server.parse_args(["--host", "127.0.0.1", "--port", "9123"])
    assert args.host == "127.0.0.1"
    assert args.port == 9123


def test_public_server_rejects_mock_argument():
    with contextlib.redirect_stderr(io.StringIO()):
        with pytest.raises(SystemExit):
            server.parse_args(["--mock"])


def test_public_server_has_no_mode_api_or_status():
    assert not any(route.path == "/api/mode" for route in server.app.routes)
    with mock.patch.object(server, "get_local_ip", return_value="127.0.0.1"):
        status = asyncio.run(server.get_status())
    assert "mode" not in status
    source = Path(server.__file__).read_text(encoding="utf-8")
    assert "mock_telemetry" not in source


def test_loopback_detection():
    assert server.is_loopback_host("127.0.0.1")
    assert server.is_loopback_host("::1")
    assert not server.is_loopback_host("192.168.1.20")
    assert not server.is_loopback_host("not-an-address")


def test_control_requires_loopback_and_header():
    server.require_local_control(make_request("127.0.0.1", "1"))
    server.require_local_control(make_request("::1", "1"))

    with pytest.raises(HTTPException):
        server.require_local_control(make_request("127.0.0.1"))
    with pytest.raises(HTTPException):
        server.require_local_control(make_request("192.168.1.20", "1"))


def test_shutdown_is_post_only():
    route = next(route for route in server.app.routes if route.path == "/api/shutdown")
    assert route.methods == {"POST"}


def test_wildcard_cors_is_not_enabled():
    middleware_names = {middleware.cls.__name__ for middleware in server.app.user_middleware}
    assert "CORSMiddleware" not in middleware_names


def test_environment_accepts_csp_ambient_light_data(restore_environment_state):
    payload = {
        "headlights": True,
        "isNight": False,
        "isDark": True,
        "ambient": 0.25,
        "lightSuggestion": 0.4,
        "ambientOcclusion": 0.25,
    }

    with mock.patch.object(server.time, "monotonic", return_value=100.0):
        response = asyncio.run(server.set_environment(payload, make_request("127.0.0.1", "1")))

    assert response["environment"]["available"]
    assert response["environment"]["isDark"]
    assert response["environment"]["ambient"] == 0.25
    assert response["environment"]["ambientOcclusion"] == 0.25


def test_csp_environment_data_expires(restore_environment_state):
    server.environment_state["source"] = "csp"
    server.environment_updated_at = 100.0

    assert server.csp_environment_available(102.0)
    assert not server.csp_environment_available(
        100.0 + server.CSP_ENVIRONMENT_TIMEOUT_SECONDS + 0.01
    )


def _parse_map_locations(renderer: str) -> dict[str, tuple[float, float]]:
    block = re.search(
        r"const SRP_MAP_LOCATIONS: SourceMapLocation\[\] = \[(.*?)\n\];",
        renderer,
        re.S,
    )
    assert block is not None, "SRP_MAP_LOCATIONS table is missing"
    entries = re.findall(
        r'name: "([^"]+)".*?ac: \[(-?[\d.]+), (-?[\d.]+)\]', block.group(1)
    )
    return {name: (float(x), float(z)) for name, x, z in entries}


def _parse_map_location_kinds(renderer: str) -> dict[str, str]:
    return dict(re.findall(r'name: "([^"]+)", kind: "([^"]+)"', renderer))


def test_srp_calibration_does_not_require_installed_map_files():
    finder = ac_track_finder.ACTrackFinder()
    finder.ac_root = None
    finder.cached_track_data.clear()

    track = finder.get_track_info("shutoko_revival_project_beta", "main_layout")

    assert track["mapWidth"] == 5544.0
    assert track["mapHeight"] == 8192.0
    assert track["scaleFactor"] == pytest.approx(3.30555129051209)
    assert track["xOffset"] == pytest.approx(11119.814453125)
    assert track["zOffset"] == pytest.approx(10454.576171875)


def test_offline_navigation_map_preserves_native_directed_lanes():
    lanes_path = server.FRONTEND_DIR / "assets" / "maps" / "srp-traffic-lanes.geojson"
    roads = json.loads(lanes_path.read_text(encoding="utf-8"))

    assert roads["type"] == "FeatureCollection"
    assert roads["coordinateSpace"]["type"] == "srp-local-mercator"
    assert roads["coordinateSpace"]["longitudeAxis"] == "+x"
    assert roads["coordinateSpace"]["latitudeAxis"] == "-z"
    assert roads["statistics"]["laneCount"] == 593
    assert roads["statistics"]["pointCount"] > 17_000
    assert roads["statistics"]["sourcePointCount"] == 17_280
    assert roads["statistics"]["linkedIntersectionCount"] == 514
    assert roads["statistics"]["routeConnectionCount"] > 900
    assert "mockRoute" not in roads
    assert "mockRoutePointCount" not in roads["statistics"]
    assert "mockRouteLengthM" not in roads["statistics"]
    assert len(roads["routeConnections"]) == roads["statistics"]["routeConnectionCount"]
    assert len(roads["destinations"]) >= 12
    assert "Bardaff" in roads["attribution"]
    for feature in roads["features"]:
        assert feature["geometry"]["type"] == "LineString"
        assert len(feature["geometry"]["coordinates"]) >= 2
        assert feature["properties"]["oneway"] == "yes"
        assert "lane_id" in feature["properties"]
        assert len(feature["geometry"]["coordinates"][0]) == 3


def test_game_navigation_uses_private_game_projection():
    renderer = (server.FRONTEND_DIR / "src" / "navigation-map-renderer.ts").read_text(
        encoding="utf-8"
    )

    assert "class SrpGameProjection" in renderer
    assert "srp-traffic-lanes.geojson" in renderer
    assert "this.origin[1] - z / this.metersPerLatitudeDegree" in renderer


def test_maplibre_includes_every_named_srp_mini_map_location():
    renderer = (server.FRONTEND_DIR / "src" / "navigation-map-renderer.ts").read_text(
        encoding="utf-8"
    )
    stylesheet = (server.FRONTEND_DIR / "css" / "style.css").read_text(encoding="utf-8")

    expected_labels = (
        "Shinjuku Station",
        "Yoyogi PA",
        "Tokyo Tower",
        "Shibuya Station",
        "Rainbow Bridge",
        "Odaiba",
        "Oi PA",
        "Heiwajima PA",
        "Daishi PA",
        "Haneda Airport",
        "Tsurumi Tsubasa Bridge",
        "Minato Mirai Yokohama",
        "Yokohama Bay Bridge",
    )
    for label in expected_labels:
        assert f'name: "{label}"' in renderer
    assert "SRP_MAP_LOCATIONS" in renderer
    assert "this.addLocationLabels()" in renderer
    assert "srp-location-marker-label" in stylesheet


def test_srp_map_locations_match_the_calibrated_references():
    renderer = (server.FRONTEND_DIR / "src" / "navigation-map-renderer.ts").read_text(
        encoding="utf-8"
    )
    locations = _parse_map_locations(renderer)

    pois = {poi["shortName"]: poi["pos"] for poi in ac_track_finder.SRP_POIS}
    roads = json.loads(
        (server.FRONTEND_DIR / "assets" / "maps" / "srp-traffic-lanes.geojson").read_text(
            encoding="utf-8"
        )
    )
    destinations = {item["name"]: item["ac"] for item in roads["destinations"]}

    heiwajima_north = pois["Heiwajima PA (N)"]
    heiwajima_south = pois["Heiwajima PA (S)"]
    expected = {
        "Shinjuku Station": verify_srp_routing.SHINJUKU_STATION,
        "Yoyogi PA": (pois["Yoyogi PA"][0], pois["Yoyogi PA"][2]),
        "Tokyo Tower": (pois["Tokyo Tower"][0], pois["Tokyo Tower"][2]),
        "Shibuya Station": (pois["Shibuya"][0], pois["Shibuya"][2]),
        "Rainbow Bridge": (pois["Rainbow Bridge"][0], pois["Rainbow Bridge"][2]),
        "Heiwajima PA": (
            (heiwajima_north[0] + heiwajima_south[0]) / 2,
            (heiwajima_north[2] + heiwajima_south[2]) / 2,
        ),
        "Daishi PA": (pois["Daishi PA"][0], pois["Daishi PA"][2]),
        "Haneda Airport": tuple(destinations["Haneda Airport"]),
        "Tsurumi Tsubasa Bridge": (
            pois["Tsurumi Tsubasa Bridge"][0],
            pois["Tsurumi Tsubasa Bridge"][2],
        ),
        "Minato Mirai Yokohama": (
            pois["Minato Mirai Yokohama"][0],
            pois["Minato Mirai Yokohama"][2],
        ),
        "Yokohama Bay Bridge": (
            pois["Yokohama Bay Bridge"][0],
            pois["Yokohama Bay Bridge"][2],
        ),
    }

    for name, (x, z) in expected.items():
        actual = locations[name]
        assert math.dist(actual, (x, z)) < 25.0, (
            f"{name} has drifted from its calibrated reference"
        )

    # Odaiba and Oi PA have no exact reference - they are derived from the
    # surrounding lane geometry. Asserting them against a copy of their own
    # coordinates would prove nothing, so pin them relative to the anchors
    # above instead. In AC space +x runs east and +z runs south.
    rainbow_x, _, rainbow_z = pois["Rainbow Bridge"]
    ariake_x, _, ariake_z = pois["Ariake JCT"]
    haneda_x, haneda_z = destinations["Haneda Airport"]
    heiwajima_x = (heiwajima_north[0] + heiwajima_south[0]) / 2
    heiwajima_z = (heiwajima_north[2] + heiwajima_south[2]) / 2

    odaiba_x, odaiba_z = locations["Odaiba"]
    assert rainbow_x < odaiba_x < ariake_x and rainbow_z < odaiba_z < ariake_z, (
        "Odaiba must sit on the Route 11 corridor between Rainbow Bridge "
        f"and Ariake JCT, got {locations['Odaiba']}"
    )

    oi_x, oi_z = locations["Oi PA"]
    assert heiwajima_x < oi_x < haneda_x, (
        f"Oi PA must sit between Heiwajima PA and Haneda, got x={oi_x}"
    )
    assert ariake_z < oi_z < heiwajima_z < haneda_z, (
        "Oi PA must sit on the Wangan south of Ariake JCT and north of "
        f"Heiwajima PA, got z={oi_z}"
    )

    # The label deliberately does not follow SRP_POIS oi_pa, the one rough
    # estimate in that table. If it is ever recalibrated this fails, so the
    # map label gets revisited alongside it.
    assert (pois["Oi PA"][0], pois["Oi PA"][2]) == (1150.0, 1680.0), (
        "SRP_POIS oi_pa changed - recheck the Oi PA map label against it"
    )


def test_every_srp_map_location_sits_on_the_modelled_map():
    renderer = (server.FRONTEND_DIR / "src" / "navigation-map-renderer.ts").read_text(
        encoding="utf-8"
    )
    locations = _parse_map_locations(renderer)
    kinds = _parse_map_location_kinds(renderer)
    roads = json.loads(
        (server.FRONTEND_DIR / "assets" / "maps" / "srp-traffic-lanes.geojson").read_text(
            encoding="utf-8"
        )
    )
    space = roads["coordinateSpace"]
    origin_lon, origin_lat = space["origin"]
    lon_scale = space["metersPerLongitudeDegree"]
    lat_scale = space["metersPerLatitudeDegree"]

    lane_points = [
        (
            (point[0] - origin_lon) * lon_scale,
            (origin_lat - point[1]) * lat_scale,
        )
        for feature in roads["features"]
        for point in feature["geometry"]["coordinates"]
    ]

    # Anything anchored to a driveable feature has to sit on the network.
    # Landmarks stand beside the road and area names cover a whole district,
    # so those get an explicit larger budget instead of a blanket tolerance.
    lane_budget_m = {"district": 250.0, "landmark": 200.0}
    for name, position in locations.items():
        budget = lane_budget_m.get(kinds[name], 100.0)
        nearest = min(math.dist(position, point) for point in lane_points)
        assert nearest < budget, f"{name} is {nearest:.0f}m from the nearest SRP lane"


def test_frontend_is_navigation_only_and_uses_local_maplibre():
    index = (server.FRONTEND_DIR / "index.html").read_text(encoding="utf-8")
    controller = (server.FRONTEND_DIR / "src" / "navigation-controller.ts").read_text(
        encoding="utf-8"
    )
    assert 'id="navigation-destination"' in index
    assert 'id="btn-start-route"' in index
    assert "/vendor/maplibre-gl/maplibre-gl.mjs?v=6.5.0" in index
    assert "/js/maplibre-bootstrap.js" in index
    assert "/vendor/maplibre-gl/maplibre-gl.js" not in index
    assert "class NavigationController" in controller
    assert "Simple Map" not in index
    assert 'id="map-canvas"' not in index
    assert "/js/map-renderer.js" not in index
    assert "/js/map-mode-controller.js" not in index
    assert "Mock Sim" not in index
    assert "data-mode" not in index
    assert "/api/mode" not in (server.FRONTEND_DIR / "src" / "app.ts").read_text(
        encoding="utf-8"
    )
    assert not (server.FRONTEND_DIR / "src" / "map-renderer.ts").exists()
    assert not (server.FRONTEND_DIR / "assets" / "maps" / "srp.svg").exists()


def test_maplibre_is_pinned_and_generated_for_offline_runtime():
    repository_root = server.FRONTEND_DIR.parent
    package_manifest = json.loads(
        (repository_root / "package.json").read_text(encoding="utf-8")
    )
    copy_script = (repository_root / "scripts" / "copy_frontend_vendor.mjs").read_text(
        encoding="utf-8"
    )

    assert package_manifest["packageManager"] == "pnpm@11.22.0"
    assert package_manifest["dependencies"]["maplibre-gl"] == "6.5.0"
    for asset in (
        "maplibre-gl.mjs",
        "maplibre-gl-shared.mjs",
        "maplibre-gl-worker.mjs",
        "maplibre-gl.css",
        "LICENSE.txt",
    ):
        assert asset in copy_script


def test_navigation_map_includes_directed_route_planning():
    renderer = (server.FRONTEND_DIR / "src" / "navigation-map-renderer.ts").read_text(
        encoding="utf-8"
    )

    assert "class DirectedRoadGraph" in renderer
    assert "connectIntersectionRoutes" in renderer
    assert 'setDestination(destinationName: string)' in renderer
    assert 'getSource<MapLibreGeoJSONSource>("active-route")' in renderer
    assert "oneway" in renderer
    assert 'rotationAlignment: "viewport"' in renderer
    assert 'pitchAlignment: "viewport"' in renderer


def test_navigation_route_progress_and_recalculation_are_enabled():
    renderer = (server.FRONTEND_DIR / "src" / "navigation-map-renderer.ts").read_text(
        encoding="utf-8"
    )

    assert "routeCandidates" in renderer
    assert "planRoute" in renderer
    assert "nodeKeys" in renderer
    assert "redrawRemainingRoute" in renderer
    assert "recalculateRoute" in renderer
    assert "routeRecalculationDelayMs = 1800" in renderer
    assert "this.updateRouteProgress(routeMatches, false, routeNow)" in renderer
    assert "routeNow - this.lastRouteProgressUpdate >= 300" in renderer
    assert "this.updateRouteProgress(this.lastMarkerPoint)" not in renderer


def test_recenter_button_targets_the_active_map_mode():
    app = (server.FRONTEND_DIR / "src" / "app.ts").read_text(encoding="utf-8")
    navigation = (server.FRONTEND_DIR / "src" / "navigation-map-renderer.ts").read_text(
        encoding="utf-8"
    )

    assert 'getElementById("btn-recenter")' in app
    assert 'addEventListener("click", () => this.renderer.recenter())' in app
    assert "center: this.displayPoint" in navigation
    assert 'this.orientationMode === "headingUp" ? this.displayBearing : 0' in navigation


def test_navigation_car_uses_lower_fifth_tracking_position():
    renderer = (server.FRONTEND_DIR / "src" / "navigation-map-renderer.ts").read_text(
        encoding="utf-8"
    )

    # MapLibre centres on the padded box, so a top padding of 3/5 height
    # puts the car at (3/5 + 1) / 2 = 4/5 down the screen.
    assert "getTrackingPadding()" in renderer
    assert "top: Math.round((height * 3) / 5)" in renderer
    assert renderer.count("padding: this.getTrackingPadding()") >= 2


def test_navigation_only_view_settings_are_persisted():
    renderer = (server.FRONTEND_DIR / "src" / "navigation-map-renderer.ts").read_text(
        encoding="utf-8"
    )

    assert 'localStorage.setItem("gps_3d_tilt"' in renderer
    assert 'localStorage.setItem("gps_auto_zoom"' in renderer


def test_navigation_is_gated_to_srp_and_route_matching_is_local():
    renderer = (server.FRONTEND_DIR / "src" / "navigation-map-renderer.ts").read_text(
        encoding="utf-8"
    )
    controller = (server.FRONTEND_DIR / "src" / "navigation-controller.ts").read_text(
        encoding="utf-8"
    )

    assert "this.trackSupported = this.trackInfo.isSRP" in renderer
    assert "this.trackSupported === false" in renderer
    assert "primary.distance + 12" in renderer
    assert "primary.score + 20" in renderer
    assert "if (matches?.length) this.recalculateRoute(now)" in renderer
    assert 'document.documentElement.getAttribute("data-theme")' in controller


def test_navigation_auto_zoom_is_twenty_five_percent_closer():
    renderer = (server.FRONTEND_DIR / "src" / "navigation-map-renderer.ts").read_text(
        encoding="utf-8"
    )

    assert "SRP_NAVIGATION_AUTO_ZOOM_SCALE = 1.25" in renderer
    assert "Math.log2(SRP_NAVIGATION_AUTO_ZOOM_SCALE)" in renderer
    assert "const targetPoint = longitudeLatitude;" in renderer
    assert "const targetPoint = match?.point" not in renderer
    assert "reliableMatch?.alignedBearing" in renderer
    assert "resolveTravelBearing" in renderer
    assert "startMatch?.segmentTo" in renderer
    assert "Waiting for a road position." in renderer
    assert "const displayJump" in renderer
    assert "this.matcher?.resetContinuity();" in renderer
    assert "this.recenter();" in renderer
