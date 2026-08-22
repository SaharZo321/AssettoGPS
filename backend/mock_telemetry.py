"""
Realistic Assetto Corsa Mock Telemetry Simulator
Generates smooth Catmull-Rom spline driving telemetry along a simulated Shutoko Revival Project route.
"""

import bisect
import json
import math
import time
from pathlib import Path
from typing import Dict, Any, List, Tuple


def catmull_rom_spline(p0: Tuple[float, float], p1: Tuple[float, float], p2: Tuple[float, float], p3: Tuple[float, float], t: float) -> Tuple[float, float]:
    """Computes point on a 2D Catmull-Rom spline at parameter t (0.0 to 1.0)"""
    t2 = t * t
    t3 = t2 * t

    # Catmull-Rom matrix coefficients
    f0 = -0.5 * t3 + t2 - 0.5 * t
    f1 = 1.5 * t3 - 2.5 * t2 + 1.0
    f2 = -1.5 * t3 + 2.0 * t2 + 0.5 * t
    f3 = 0.5 * t3 - 0.5 * t2

    x = p0[0] * f0 + p1[0] * f1 + p2[0] * f2 + p3[0] * f3
    z = p0[1] * f0 + p1[1] * f1 + p2[1] * f2 + p3[1] * f3
    return (x, z)


class MockTelemetryGenerator:
    """Simulates realistic driving telemetry on Shutoko Revival Project"""

    def __init__(self, lane_asset_path: Path | None = None):
        self.start_time = time.time()
        self.t = 0.0
        self.native_route = self._load_native_route(lane_asset_path)
        self.native_route_distances = [0.0]
        for previous, current in zip(self.native_route, self.native_route[1:]):
            self.native_route_distances.append(
                self.native_route_distances[-1]
                + math.hypot(current[0] - previous[0], current[2] - previous[2])
            )
        self.native_route_length = (
            self.native_route_distances[-1] if self.native_route_distances else 0.0
        )

        # Calibrated Tokyo Expressway highway loop waypoints (X, Z)
        self.waypoints = [
            (-5897.0, 14006.5), # Daikoku PA
            (53.0, 10965.4),    # Tsurumi Tsubasa Bridge
            (1150.0, 1680.0),   # Oi PA
            (3490.7, -3314.6),  # Ariake JCT
            (5898.5, -4654.8),  # Tatsumi PA
            (3689.1, -8867.9),  # Hakozaki JCT
            (1110.7, -5727.6),  # Ginza (C1)
            (-3.8, -6053.3),    # Tokyo Tower (C1)
            (-4106.3, -6450.6), # Shibuya Crossing
            (-4345.5, -8875.0), # Yoyogi PA
            (-4899.6, -9770.8), # Shinjuku
            (1099.3, -4680.1),  # Shibaura PA
            (1566.9, -3909.6),  # Rainbow Bridge Center Span
            (-254.7, 1328.6),   # Heiwajima PA
            (-308.7, 6141.9),   # Daishi PA
            (-6756.5, 15196.5), # Yokohama Bay Bridge
            (-5897.0, 14006.5), # Back to Daikoku PA
        ]

    @staticmethod
    def _load_native_route(lane_asset_path: Path | None) -> List[Tuple[float, float, float]]:
        if not lane_asset_path or not lane_asset_path.is_file():
            return []
        data = json.loads(lane_asset_path.read_text(encoding='utf-8'))
        coordinate_space = data['coordinateSpace']
        origin_longitude, origin_latitude = coordinate_space['origin']
        longitude_scale = coordinate_space['metersPerLongitudeDegree']
        latitude_scale = coordinate_space['metersPerLatitudeDegree']
        lanes = {feature['properties']['lane_id']: feature for feature in data['features']}
        route = []
        route_coordinates = data.get('mockRoute')
        if not route_coordinates:
            route_coordinates = [
                coordinate
                for lane_id in (34, 29, 177, 193, 209)
                for coordinate in lanes[lane_id]['geometry']['coordinates']
            ]
        for longitude, latitude, elevation in route_coordinates:
            point = (
                (longitude - origin_longitude) * longitude_scale,
                elevation,
                (latitude - origin_latitude) * latitude_scale,
            )
            if not route or math.hypot(
                point[0] - route[-1][0], point[2] - route[-1][2]
            ) > 0.05:
                route.append(point)
        if len(route) < 2:
            return []
        if math.dist(route[-1], route[0]) > 0.05:
            route.append(route[0])
        return route

    def _sample_native_route(self, progress: float) -> Tuple[float, float, float]:
        target_distance = (progress % 1.0) * self.native_route_length
        index = max(1, bisect.bisect_left(self.native_route_distances, target_distance))
        index = min(index, len(self.native_route) - 1)
        start_distance = self.native_route_distances[index - 1]
        end_distance = self.native_route_distances[index]
        amount = 0.0 if end_distance == start_distance else (
            (target_distance - start_distance) / (end_distance - start_distance)
        )
        start = self.native_route[index - 1]
        end = self.native_route[index]
        return tuple(start[axis] + (end[axis] - start[axis]) * amount for axis in range(3))

    def get_frame(self) -> Dict[str, Any]:
        """Generates the next smooth telemetry packet"""
        self.t = time.time() - self.start_time

        # Native lane cycle runs at an average 180 km/h. The legacy synthetic
        # route remains available for direct unit construction without assets.
        total_loop_time = (
            self.native_route_length / 50.0 if self.native_route_length else 150.0
        )
        progress = (self.t % total_loop_time) / total_loop_time

        if self.native_route_length:
            cur_x, cur_y, cur_z = self._sample_native_route(progress)
            next_progress = progress + min(5.0 / self.native_route_length, 0.001)
            next_x, _, next_z = self._sample_native_route(next_progress)
        else:
            n = len(self.waypoints) - 1
            scaled_t = progress * n
            i = int(scaled_t)
            t_seg = scaled_t - i

            # 4 control points for the legacy closed Catmull-Rom spline.
            p0 = self.waypoints[(i - 1) % n]
            p1 = self.waypoints[i % n]
            p2 = self.waypoints[(i + 1) % n]
            p3 = self.waypoints[(i + 2) % n]
            cur_x, cur_z = catmull_rom_spline(p0, p1, p2, p3, t_seg)
            next_x, next_z = catmull_rom_spline(
                p0, p1, p2, p3, min(t_seg + 0.01, 1.0)
            )

        dx = next_x - cur_x
        dz = next_z - cur_z
        heading_rad = math.atan2(dx, dz)
        heading_deg = math.degrees(heading_rad) % 360

        if not self.native_route_length:
            # Legacy synthetic elevation for direct tests without map assets.
            if -4900 < cur_x < -3600 and -9900 < cur_z < -6000:
                cur_y = -8.0
            elif 200 < cur_x < 2200 and -6500 < cur_z < -4500:
                cur_y = -4.0
            else:
                cur_y = 18.0 + 8.0 * math.sin(self.t * 0.1)

        # Keep native test motion and reported velocity consistent at 180 km/h.
        # The legacy spline retains variable speed for standalone UI demos.
        curvature = abs(math.sin(self.t * 0.3))
        if self.native_route_length:
            speed_kmh = 180.0
        else:
            target_speed = 280.0 - curvature * 150.0
            speed_kmh = max(
                80.0,
                min(315.0, target_speed + 10.0 * math.sin(self.t * 0.8)),
            )

        # Gear & RPM
        if speed_kmh < 90:
            gear = "3"
            raw_gear = 4
            rpm = int(4000 + (speed_kmh / 90.0) * 3500)
        elif speed_kmh < 160:
            gear = "4"
            raw_gear = 5
            rpm = int(4500 + ((speed_kmh - 90) / 70.0) * 3500)
        elif speed_kmh < 230:
            gear = "5"
            raw_gear = 6
            rpm = int(5000 + ((speed_kmh - 160) / 70.0) * 3200)
        else:
            gear = "6"
            raw_gear = 7
            rpm = int(5500 + ((speed_kmh - 230) / 85.0) * 2800)

        fuel = max(5.0, 75.0 - (self.t * 0.015))

        return {
            "connected": True,
            "isMock": True,
            "status": 2,  # Live
            "session": 2,  # Race
            "track": "shutoko_revival_project_beta",
            "trackConfig": "main_layout",
            "carModel": "ks_nissan_gtr_r34",
            "playerName": "Mid Night Club",
            # Dynamics
            "speedKmh": round(speed_kmh, 1),
            "speedMph": round(speed_kmh * 0.621371, 1),
            "gear": gear,
            "rawGear": raw_gear,
            "rpms": min(8500, rpm),
            "maxRpm": 8500,
            "gas": round(0.8 + 0.2 * math.sin(self.t), 2),
            "brake": 0.0 if curvature < 0.6 else round(curvature * 0.8, 2),
            "clutch": 0.0,
            "steerAngle": round(dx * 0.1, 1),
            "headingRad": heading_rad,
            "headingDeg": round(heading_deg, 1),
            "pitch": 0.01,
            "roll": round(0.02 * math.sin(self.t * 0.4), 3),
            "velocity": [round(math.sin(heading_rad) * speed_kmh / 3.6, 2), 0.0, round(math.cos(heading_rad) * speed_kmh / 3.6, 2)],
            # Coordinates
            "carPosition": [round(cur_x, 2), round(cur_y, 2), round(cur_z, 2)],
            # Session & Race Info
            "completedLaps": int(self.t // total_loop_time),
            "position": 1,
            "currentTime": time.strftime("%M:%S", time.gmtime(self.t % 3600)),
            "bestTime": "04:12.450",
            "lastTime": "04:15.820",
            "split": "+0.32",
            "distanceTraveled": round(self.t * (speed_kmh / 3.6), 1),
            "normalizedPosition": round(progress, 4),
            "sessionTimeLeft": 3600.0 - self.t,
            # Flags
            "flag": 0,
            "isInPit": False,
            "isInPitLane": False,
            "pitLimiterOn": False,
            # Health
            "fuel": round(fuel, 1),
            "maxFuel": 80.0,
            "fuelPercent": round((fuel / 80.0) * 100.0, 1),
            "tyreWear": [98.2, 98.4, 97.9, 98.1],
            "tyreTemps": [82.0, 83.5, 85.0, 84.2],
            "avgTyreTemp": 83.7,
            "turboBoost": 1.45,
            "drsAvailable": False,
            "drsEnabled": False,
        }
