import asyncio
import json
import math
import sys
import unittest
import uuid
from pathlib import Path
from unittest import mock

from fastapi import HTTPException
from starlette.requests import Request


BACKEND_DIR = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND_DIR))

import ac_shared_memory
import ac_track_finder
import mock_telemetry
import server


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


class SharedMemoryTests(unittest.TestCase):
    def test_missing_mapping_is_not_created_by_connect(self):
        prefix = f"AssettoGPS.test.{uuid.uuid4()}"
        names = (f"{prefix}.physics", f"{prefix}.graphics", f"{prefix}.static")

        with mock.patch.object(ac_shared_memory, "AC_SHARED_MEMORY_NAMES", names):
            reader = ac_shared_memory.AssettoCorsaSharedMemory()
            self.assertFalse(reader.connect())
            self.assertFalse(reader.is_connected)
            self.assertTrue(all(not ac_shared_memory.named_mapping_exists(name) for name in names))


class MockTelemetryTests(unittest.TestCase):
    def test_heading_matches_forward_motion_and_velocity(self):
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

        self.assertLess(angle_error(first["headingRad"], motion_heading), math.radians(2))
        self.assertLess(angle_error(first["headingRad"], velocity_heading), math.radians(0.1))

    def test_native_mock_route_uses_bundled_game_lanes(self):
        lane_asset = (
            server.FRONTEND_DIR / "assets" / "maps" / "srp-traffic-lanes.geojson"
        )
        lane_data = json.loads(lane_asset.read_text(encoding="utf-8"))
        with mock.patch.object(mock_telemetry.time, "time", return_value=1_000.0):
            generator = mock_telemetry.MockTelemetryGenerator(lane_asset)
        with mock.patch.object(mock_telemetry.time, "time", return_value=1_020.0):
            frame = generator.get_frame()

        self.assertGreater(generator.native_route_length, 60_000)
        self.assertEqual(frame["trackConfig"], "main_layout")
        self.assertEqual(frame["speedKmh"], 180.0)
        self.assertAlmostEqual(
            math.hypot(frame["velocity"][0], frame["velocity"][2]), 50.0, places=1
        )
        self.assertEqual(len(frame["carPosition"]), 3)
        self.assertTrue(all(math.isfinite(value) for value in frame["carPosition"]))
        longitude, latitude, _ = lane_data["mockRoute"][0]
        coordinate_space = lane_data["coordinateSpace"]
        origin_longitude, origin_latitude = coordinate_space["origin"]
        self.assertAlmostEqual(
            generator.native_route[0][0],
            (longitude - origin_longitude)
            * coordinate_space["metersPerLongitudeDegree"],
        )
        self.assertAlmostEqual(
            generator.native_route[0][2],
            (origin_latitude - latitude)
            * coordinate_space["metersPerLatitudeDegree"],
        )


class ControlEndpointTests(unittest.TestCase):
    def setUp(self):
        self.original_environment = server.environment_state.copy()
        self.original_environment_updated_at = server.environment_updated_at

    def tearDown(self):
        server.environment_state.clear()
        server.environment_state.update(self.original_environment)
        server.environment_updated_at = self.original_environment_updated_at

    def test_custom_port_argument(self):
        args = server.parse_args(["--host", "127.0.0.1", "--port", "9123", "--mock"])
        self.assertEqual(args.host, "127.0.0.1")
        self.assertEqual(args.port, 9123)
        self.assertTrue(args.mock)

    def test_loopback_detection(self):
        self.assertTrue(server.is_loopback_host("127.0.0.1"))
        self.assertTrue(server.is_loopback_host("::1"))
        self.assertFalse(server.is_loopback_host("192.168.1.20"))
        self.assertFalse(server.is_loopback_host("not-an-address"))

    def test_control_requires_loopback_and_header(self):
        server.require_local_control(make_request("127.0.0.1", "1"))
        server.require_local_control(make_request("::1", "1"))

        with self.assertRaises(HTTPException):
            server.require_local_control(make_request("127.0.0.1"))
        with self.assertRaises(HTTPException):
            server.require_local_control(make_request("192.168.1.20", "1"))

    def test_shutdown_is_post_only(self):
        route = next(route for route in server.app.routes if route.path == "/api/shutdown")
        self.assertEqual(route.methods, {"POST"})

    def test_wildcard_cors_is_not_enabled(self):
        middleware_names = {middleware.cls.__name__ for middleware in server.app.user_middleware}
        self.assertNotIn("CORSMiddleware", middleware_names)

    def test_environment_accepts_csp_ambient_light_data(self):
        payload = {
            "headlights": True,
            "isNight": False,
            "isDark": True,
            "ambient": 0.25,
            "lightSuggestion": 0.4,
            "ambientOcclusion": 0.25,
        }

        with mock.patch.object(server.time, "monotonic", return_value=100.0):
            response = asyncio.run(
                server.set_environment(payload, make_request("127.0.0.1", "1"))
            )

        self.assertTrue(response["environment"]["available"])
        self.assertTrue(response["environment"]["isDark"])
        self.assertEqual(response["environment"]["ambient"], 0.25)
        self.assertEqual(response["environment"]["ambientOcclusion"], 0.25)

    def test_csp_environment_data_expires(self):
        server.environment_state["source"] = "csp"
        server.environment_updated_at = 100.0

        self.assertTrue(server.csp_environment_available(102.0))
        self.assertFalse(
            server.csp_environment_available(
                100.0 + server.CSP_ENVIRONMENT_TIMEOUT_SECONDS + 0.01
            )
        )


class SrpVectorMapTests(unittest.TestCase):
    def test_srp_calibration_does_not_require_installed_map_files(self):
        finder = ac_track_finder.ACTrackFinder()
        finder.ac_root = None
        finder.cached_track_data.clear()

        track = finder.get_track_info("shutoko_revival_project_beta", "main_layout")

        self.assertEqual(track["mapWidth"], 5544.0)
        self.assertEqual(track["mapHeight"], 8192.0)
        self.assertAlmostEqual(track["scaleFactor"], 3.30555129051209)
        self.assertAlmostEqual(track["xOffset"], 11119.814453125)
        self.assertAlmostEqual(track["zOffset"], 10454.576171875)

    def test_offline_navigation_map_preserves_native_directed_lanes(self):
        lanes_path = (
            server.FRONTEND_DIR / "assets" / "maps" / "srp-traffic-lanes.geojson"
        )
        roads = json.loads(lanes_path.read_text(encoding="utf-8"))

        self.assertEqual(roads["type"], "FeatureCollection")
        self.assertEqual(roads["coordinateSpace"]["type"], "srp-local-mercator")
        self.assertEqual(roads["coordinateSpace"]["longitudeAxis"], "+x")
        self.assertEqual(roads["coordinateSpace"]["latitudeAxis"], "-z")
        self.assertEqual(roads["statistics"]["laneCount"], 593)
        self.assertGreater(roads["statistics"]["pointCount"], 17_000)
        self.assertEqual(roads["statistics"]["sourcePointCount"], 17_280)
        self.assertEqual(roads["statistics"]["linkedIntersectionCount"], 514)
        self.assertGreater(roads["statistics"]["routeConnectionCount"], 900)
        self.assertGreater(roads["statistics"]["mockRoutePointCount"], 2_000)
        self.assertGreater(roads["statistics"]["mockRouteLengthM"], 80_000)
        self.assertEqual(roads["mockRoute"][0], roads["mockRoute"][-1])
        self.assertEqual(
            len(roads["routeConnections"]),
            roads["statistics"]["routeConnectionCount"],
        )
        self.assertGreaterEqual(len(roads["destinations"]), 12)
        self.assertIn("Bardaff", roads["attribution"])
        for feature in roads["features"]:
            self.assertEqual(feature["geometry"]["type"], "LineString")
            self.assertGreaterEqual(len(feature["geometry"]["coordinates"]), 2)
            self.assertEqual(feature["properties"]["oneway"], "yes")
            self.assertIn("lane_id", feature["properties"])
            self.assertEqual(len(feature["geometry"]["coordinates"][0]), 3)

    def test_game_navigation_does_not_load_osm_calibration(self):
        renderer = (
            server.FRONTEND_DIR / "js" / "navigation-map-renderer.js"
        ).read_text(encoding="utf-8")

        self.assertIn("class SrpGameProjection", renderer)
        self.assertIn("srp-traffic-lanes.geojson", renderer)
        self.assertIn(
            "this.origin[1] - z / this.metersPerLatitudeDegree", renderer
        )
        self.assertNotIn("srp-osm-calibration.json", renderer)
        self.assertNotIn("SrpCoordinateCalibration", renderer)

    def test_frontend_is_navigation_only_and_uses_local_maplibre(self):
        index = (server.FRONTEND_DIR / "index.html").read_text(encoding="utf-8")
        controller = (server.FRONTEND_DIR / "js" / "navigation-controller.js").read_text(
            encoding="utf-8"
        )
        self.assertIn('id="navigation-destination"', index)
        self.assertIn('id="btn-start-route"', index)
        self.assertIn('/vendor/maplibre-gl/maplibre-gl.js', index)
        self.assertIn("class NavigationController", controller)
        self.assertNotIn("Simple Map", index)
        self.assertNotIn('id="map-canvas"', index)
        self.assertNotIn('/js/map-renderer.js', index)
        self.assertNotIn('/js/map-mode-controller.js', index)
        self.assertFalse((server.FRONTEND_DIR / "js" / "map-renderer.js").exists())
        self.assertFalse((server.FRONTEND_DIR / "assets" / "maps" / "srp.svg").exists())

    def test_navigation_map_includes_directed_route_planning(self):
        renderer = (
            server.FRONTEND_DIR / "js" / "navigation-map-renderer.js"
        ).read_text(encoding="utf-8")

        self.assertIn("class DirectedRoadGraph", renderer)
        self.assertIn("connectIntersectionRoutes", renderer)
        self.assertIn("setDestination(destinationName)", renderer)
        self.assertIn('getSource("active-route")', renderer)
        self.assertIn("oneway", renderer)
        self.assertIn('rotationAlignment: "viewport"', renderer)
        self.assertIn('pitchAlignment: "viewport"', renderer)

    def test_navigation_route_progress_and_recalculation_are_enabled(self):
        renderer = (
            server.FRONTEND_DIR / "js" / "navigation-map-renderer.js"
        ).read_text(encoding="utf-8")

        self.assertIn("routeCandidates", renderer)
        self.assertIn("planRoute", renderer)
        self.assertIn("nodeKeys", renderer)
        self.assertIn("redrawRemainingRoute", renderer)
        self.assertIn("recalculateRoute", renderer)
        self.assertIn("routeRecalculationDelayMs = 1800", renderer)
        self.assertIn("this.updateRouteProgress(routeMatches, false, routeNow)", renderer)
        self.assertIn("routeNow - this.lastRouteProgressUpdate >= 300", renderer)
        self.assertNotIn("this.updateRouteProgress(this.lastMarkerPoint)", renderer)

    def test_recenter_button_targets_the_active_map_mode(self):
        app = (server.FRONTEND_DIR / "js" / "app.js").read_text(encoding="utf-8")
        navigation = (
            server.FRONTEND_DIR / "js" / "navigation-map-renderer.js"
        ).read_text(encoding="utf-8")

        self.assertIn('getElementById("btn-recenter")', app)
        self.assertIn('addEventListener("click", () => this.renderer.recenter())', app)
        self.assertIn('center: this.displayPoint', navigation)
        self.assertIn('this.orientationMode === "headingUp" ? this.displayBearing : 0', navigation)

    def test_navigation_car_uses_lower_third_tracking_position(self):
        renderer = (
            server.FRONTEND_DIR / "js" / "navigation-map-renderer.js"
        ).read_text(encoding="utf-8")

        self.assertIn("getTrackingPadding()", renderer)
        self.assertIn("top: Math.round(height / 3)", renderer)
        self.assertGreaterEqual(
            renderer.count("padding: this.getTrackingPadding()"),
            2,
        )

    def test_navigation_only_view_settings_are_persisted(self):
        renderer = (
            server.FRONTEND_DIR / "js" / "navigation-map-renderer.js"
        ).read_text(encoding="utf-8")

        self.assertIn('localStorage.setItem("gps_3d_tilt"', renderer)
        self.assertIn('localStorage.setItem("gps_auto_zoom"', renderer)

    def test_navigation_is_gated_to_srp_and_route_matching_is_local(self):
        renderer = (
            server.FRONTEND_DIR / "js" / "navigation-map-renderer.js"
        ).read_text(encoding="utf-8")
        controller = (
            server.FRONTEND_DIR / "js" / "navigation-controller.js"
        ).read_text(encoding="utf-8")

        self.assertIn('this.trackSupported = this.trackInfo.isSRP', renderer)
        self.assertIn('this.trackSupported === false', renderer)
        self.assertIn('primary.distance + 12', renderer)
        self.assertIn('primary.score + 20', renderer)
        self.assertIn('if (matches?.length) this.recalculateRoute(now)', renderer)
        self.assertIn('document.documentElement.getAttribute("data-theme")', controller)

    def test_navigation_auto_zoom_is_twenty_five_percent_closer(self):
        renderer = (
            server.FRONTEND_DIR / "js" / "navigation-map-renderer.js"
        ).read_text(encoding="utf-8")

        self.assertIn("SRP_NAVIGATION_AUTO_ZOOM_SCALE = 1.25", renderer)
        self.assertIn("Math.log2(SRP_NAVIGATION_AUTO_ZOOM_SCALE)", renderer)
        self.assertIn("const targetPoint = longitudeLatitude;", renderer)
        self.assertNotIn("const targetPoint = match?.point", renderer)
        self.assertIn("reliableMatch?.alignedBearing", renderer)
        self.assertIn("resolveTravelBearing", renderer)
        self.assertIn("startMatch?.segmentTo", renderer)
        self.assertIn("Waiting for a road position.", renderer)
        self.assertIn("const displayJump", renderer)
        self.assertIn("this.matcher?.resetContinuity();", renderer)
        self.assertIn("this.recenter();", renderer)


if __name__ == "__main__":
    unittest.main()
