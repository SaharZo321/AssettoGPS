import asyncio
import json
import sys
import unittest
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest import mock

from fastapi import HTTPException
from starlette.requests import Request


BACKEND_DIR = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND_DIR))

import ac_shared_memory
import ac_track_finder
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

    def test_bundled_srp_map_is_real_vector_geometry(self):
        root = ET.parse(server.SRP_MAP_PATH).getroot()
        namespace = {"svg": "http://www.w3.org/2000/svg"}
        roads = root.find("svg:path[@id='roads']", namespace)

        self.assertEqual(root.attrib["viewBox"], "0 0 5544 8192")
        self.assertIsNotNone(roads)
        self.assertGreater(roads.attrib["d"].count("Q"), 2_000)
        self.assertIsNone(root.find("svg:image", namespace))

    def test_srp_map_endpoint_prefers_svg_over_installed_png(self):
        response = asyncio.run(
            server.get_track_map_image("shutoko_revival_project_beta")
        )

        self.assertEqual(response.media_type, "image/svg+xml")
        self.assertEqual(Path(response.path), server.SRP_MAP_PATH)

    def test_offline_navigation_map_preserves_directed_osm_ways(self):
        roads_path = server.FRONTEND_DIR / "assets" / "maps" / "srp-osm-roads.geojson"
        roads = json.loads(roads_path.read_text(encoding="utf-8"))

        self.assertEqual(roads["type"], "FeatureCollection")
        self.assertIn("OpenStreetMap contributors", roads["attribution"])
        self.assertGreater(len(roads["features"]), 1_500)
        directed = 0
        for feature in roads["features"]:
            self.assertEqual(feature["geometry"]["type"], "LineString")
            self.assertGreaterEqual(len(feature["geometry"]["coordinates"]), 2)
            if feature["properties"]["oneway"] in {"yes", "1", "-1"}:
                directed += 1
        self.assertGreater(directed / len(roads["features"]), 0.98)

    def test_srp_navigation_calibration_has_local_controls(self):
        calibration_path = (
            server.FRONTEND_DIR / "assets" / "maps" / "srp-osm-calibration.json"
        )
        calibration = json.loads(calibration_path.read_text(encoding="utf-8"))

        self.assertEqual(calibration["method"], "affine-with-local-idw-correction")
        self.assertGreaterEqual(len(calibration["anchors"]), 12)
        self.assertEqual(len(calibration["affine"]["longitude"]), 3)
        self.assertEqual(len(calibration["affine"]["latitude"]), 3)

    def test_frontend_exposes_both_map_modes_and_local_maplibre(self):
        index = (server.FRONTEND_DIR / "index.html").read_text(encoding="utf-8")
        controller = (server.FRONTEND_DIR / "js" / "map-mode-controller.js").read_text(
            encoding="utf-8"
        )
        license_text = (
            server.FRONTEND_DIR / "assets" / "maps" / "OSM-LICENSE.txt"
        ).read_text(encoding="utf-8")

        self.assertIn('data-map-mode="simple"', index)
        self.assertIn('data-map-mode="navigation"', index)
        self.assertIn('id="navigation-destination"', index)
        self.assertIn('id="btn-start-route"', index)
        self.assertIn('/vendor/maplibre-gl/maplibre-gl.js', index)
        self.assertIn('localStorage.getItem("gps_map_mode")', controller)
        self.assertIn("OpenStreetMap contributors", license_text)

    def test_navigation_map_includes_directed_route_planning(self):
        renderer = (
            server.FRONTEND_DIR / "js" / "navigation-map-renderer.js"
        ).read_text(encoding="utf-8")

        self.assertIn("class DirectedRoadGraph", renderer)
        self.assertIn("setDestination(destinationName)", renderer)
        self.assertIn('getSource("active-route")', renderer)
        self.assertIn("oneway", renderer)


if __name__ == "__main__":
    unittest.main()
