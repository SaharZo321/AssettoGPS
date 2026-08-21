"""
Assetto Corsa Navigation & GPS Engine
Computes distances, top speed, trip stats, and POI cues.
"""

import math
from typing import Dict, Any, List, Optional


def calculate_distance_2d(p1: List[float], p2: List[float]) -> float:
    """Euclidean distance in meters on the X-Z plane"""
    return math.hypot(p1[0] - p2[0], p1[2] - p2[2])


class NavigationEngine:
    """Manages real-time navigation cues and POI detection"""

    def __init__(self):
        self.top_speed_kmh = 0.0
        self.trip_distance_m = 0.0
        self.last_pos: Optional[List[float]] = None

    def update(
        self,
        car_pos: List[float],
        speed_kmh: float,
        heading_rad: float,
        pois: List[Dict[str, Any]],
        track_name: str = "",
        car_model: str = "",
        is_srp: bool = False,
    ) -> Dict[str, Any]:
        """Processes current car position and returns navigation cues and POIs"""
        if not car_pos or len(car_pos) < 3:
            return {}

        # Update top speed
        if speed_kmh > self.top_speed_kmh:
            self.top_speed_kmh = speed_kmh

        # Update trip distance
        if self.last_pos is not None:
            step_dist = calculate_distance_2d(self.last_pos, car_pos)
            if step_dist < 100:  # Ignore teleport / restart jumps
                self.trip_distance_m += step_dist
        self.last_pos = list(car_pos)

        # 1. Check nearby / upcoming POIs
        nearby_poi = None
        min_poi_dist = float("inf")

        for poi in pois:
            poi_pos = poi.get("pos", [0, 0, 0])
            dist = calculate_distance_2d(car_pos, poi_pos)
            if dist < 2000:  # Within 2 km
                if dist < min_poi_dist:
                    min_poi_dist = dist
                    nearby_poi = {
                        "id": poi["id"],
                        "name": poi["name"],
                        "shortName": poi["shortName"],
                        "icon": poi.get("icon", "📍"),
                        "distanceM": int(dist),
                        "distanceKm": round(dist / 1000.0, 1),
                        "type": poi.get("type", "landmark"),
                        "desc": poi.get("desc", ""),
                    }

        # 2. Formulate Top Navigation Card Banner
        # Clean up car model name
        clean_car = ""
        if car_model and str(car_model).strip() not in ["0", "", "none", "None"]:
            clean_car = str(car_model).replace("ks_", "").replace("_", " ").title().strip()

        # 2. Formulate Top Navigation Card Banner
        nav_instruction = {}
        if nearby_poi and nearby_poi["distanceM"] < 1500:
            if nearby_poi["distanceM"] > 900:
                dist_str = f"{nearby_poi['distanceKm']} km"
            else:
                dist_str = f"{nearby_poi['distanceM']} m"

            nav_instruction = {
                "title": f"{nearby_poi['shortName']} in {dist_str}",
                "subtitle": nearby_poi["desc"] or f"Upcoming {nearby_poi.get('type', 'Point').title()}",
                "icon": nearby_poi["icon"],
                "alertLevel": "info",
            }
        else:
            if is_srp:
                nav_instruction = {
                    "title": "Shutoko Expressway",
                    "subtitle": clean_car if clean_car else "Live Navigation Active",
                    "icon": "🛣️",
                    "alertLevel": "normal",
                }
            elif track_name:
                clean_track = track_name.replace("ks_", "").replace("_", " ").title()
                nav_instruction = {
                    "title": f"{clean_track}",
                    "subtitle": clean_car if clean_car else "Live AC Session",
                    "icon": "🏁",
                    "alertLevel": "normal",
                }
            else:
                nav_instruction = {
                    "title": "Assetto Corsa GPS",
                    "subtitle": "Live Navigation Active",
                    "icon": "🏁",
                    "alertLevel": "normal",
                }

        return {
            "topSpeedKmh": round(self.top_speed_kmh, 1),
            "tripDistanceKm": round(self.trip_distance_m / 1000.0, 2),
            "nearbyPoi": nearby_poi,
            "instruction": nav_instruction,
        }
