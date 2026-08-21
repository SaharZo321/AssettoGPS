"""
Assetto Corsa Navigation & GPS Engine
Computes distances, top speed, trip stats, and POI cues.
"""

import math
from typing import Dict, Any, List, Optional


def calculate_distance_2d(p1: List[float], p2: List[float]) -> float:
    """Euclidean distance in meters on the X-Z plane"""
    return math.hypot(p1[0] - p2[0], p1[2] - p2[2])


class TunnelDetector:
    """Detects whether the car is inside an underground/tunnel zone based on track coordinates & elevation"""

    @staticmethod
    def detect_tunnel(track_name: str, car_pos: List[float]) -> Dict[str, Any]:
        if not car_pos or len(car_pos) < 3:
            return {"inTunnel": False, "tunnelName": None}

        x, y, z = car_pos[0], car_pos[1], car_pos[2]
        track_lower = str(track_name).lower()

        # 1. Shutoko Revival Project (SRP / Tokyo Expressway)
        if "shutoko" in track_lower or "srp" in track_lower or "ptb" in track_lower or not track_name:
            # Yamate Tunnel (Deep underground C2 Central Circular segment)
            if y < 8.0 and -6400 < x < -2100 and -12500 < z < -1400:
                return {"inTunnel": True, "tunnelName": "Yamate Tunnel (C2)"}

            # Tokyo Bay / Haneda / Kawasaki Subsea & Underpass Tunnels
            if y < 5.0 and -2500 < x < 4200 and 1200 < z < 9200:
                return {"inTunnel": True, "tunnelName": "Haneda / Tokyo Bay Tunnel"}

            # C1 Inner/Outer Loop subterranean underpasses (Shiodome, Kasumigaseki, Chiyoda)
            if y < 10.5 and -1600 < x < 2600 and -8600 < z < -4200:
                return {"inTunnel": True, "tunnelName": "C1 Underground Segment"}

            # Generic SRP underground elevation (surface viaducts are elevated at y >= 12m to 48m)
            if y < 3.5:
                return {"inTunnel": True, "tunnelName": "Tunnel Underpass"}

        # 2. Monaco / Circuit de Monaco (Fairmont / Larvotto Tunnel)
        elif "monaco" in track_lower or "monte" in track_lower:
            if y < 16.0 and -120 < x < 320 and 180 < z < 620:
                return {"inTunnel": True, "tunnelName": "Monaco Tunnel"}

        # 3. Generic tracks: subterranean elevation trigger
        elif y < -8.0:
            return {"inTunnel": True, "tunnelName": "Tunnel"}

        return {"inTunnel": False, "tunnelName": None}


class NavigationEngine:
    """Manages real-time navigation cues, POI detection, and tunnel sensing"""

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
        """Processes current car position and returns navigation cues, POIs, and tunnel state"""
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

        # 1. Tunnel Detection
        tunnel_info = TunnelDetector.detect_tunnel(track_name, car_pos)
        in_tunnel = tunnel_info["inTunnel"]
        tunnel_name = tunnel_info["tunnelName"]

        # 2. Check nearby / upcoming POIs
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

        # 3. Formulate Top Navigation Card Banner
        clean_car = ""
        if car_model and str(car_model).strip() not in ["0", "", "none", "None"]:
            clean_car = str(car_model).replace("ks_", "").replace("_", " ").title().strip()

        nav_instruction = {}
        if in_tunnel and tunnel_name:
            nav_instruction = {
                "title": tunnel_name,
                "subtitle": "Tunnel Mode Active" if not nearby_poi else f"Approaching {nearby_poi['shortName']}",
                "icon": "🚇",
                "alertLevel": "tunnel",
            }
        elif nearby_poi and nearby_poi["distanceM"] < 1500:
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
            "inTunnel": in_tunnel,
            "tunnelName": tunnel_name,
        }
