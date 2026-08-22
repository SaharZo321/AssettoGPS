"""
Assetto Corsa Track Finder & Map Calibration Parser
Directly aligns with official Kunos and Comfy Map standards.
Auto-discovers SRP layouts (main_layout, tatsumi_pa, shibaura_pa, daishi_pa, etc.).
"""

import os
import sys
import json
import configparser
from typing import Optional, Dict, Any, List
from pathlib import Path

# Built-in SRP POIs (Points of Interest) - Calibrated to official Comfy Map & Assetto Corsa SRP standards
SRP_POIS = [
    {
        "id": "daikoku_pa",
        "name": "Daikoku Parking Area",
        "shortName": "Daikoku PA",
        "type": "parking",
        "icon": "🅿️",
        "pos": [-5897.0, 15.0, 14006.5],
        "desc": "Famous Tokyo car meet mecca on Daikoku Futo",
    },
    {
        "id": "tatsumi_pa",
        "name": "Tatsumi PA (Route 9)",
        "shortName": "Tatsumi PA",
        "type": "parking",
        "icon": "🅿️",
        "pos": [5898.5, 25.8, -4654.8],
        "desc": "High-elevation PA with iconic skyscraper backdrop",
    },
    {
        "id": "shibaura_pa",
        "name": "Shibaura Parking Area",
        "shortName": "Shibaura PA",
        "type": "parking",
        "icon": "🅿️",
        "pos": [1099.3, 26.3, -4680.1],
        "desc": "Route 11 Rainbow Bridge approach parking area",
    },
    {
        "id": "yoyogi_pa",
        "name": "Yoyogi Parking Area (Route 4)",
        "shortName": "Yoyogi PA",
        "type": "parking",
        "icon": "🅿️",
        "pos": [-4345.5, 37.3, -8875.0],
        "desc": "Shinjuku Route 4 rest area",
    },
    {
        "id": "heiwajima_pa_n",
        "name": "Heiwajima PA (Northbound)",
        "shortName": "Heiwajima PA (N)",
        "type": "parking",
        "icon": "🅿️",
        "pos": [-254.7, 13.8, 1328.6],
        "desc": "K1 Haneda / Yokohane Northbound rest area",
    },
    {
        "id": "heiwajima_pa_s",
        "name": "Heiwajima PA (Southbound)",
        "shortName": "Heiwajima PA (S)",
        "type": "parking",
        "icon": "🅿️",
        "pos": [-146.4, 9.1, 1451.6],
        "desc": "K1 Haneda / Yokohane Southbound rest area",
    },
    {
        "id": "daishi_pa",
        "name": "Daishi Parking Area",
        "shortName": "Daishi PA",
        "type": "parking",
        "icon": "🅿️",
        "pos": [-308.7, 15.2, 6141.9],
        "desc": "K1 Yokohane start parking area",
    },
    {
        "id": "oi_pa",
        "name": "Oi Parking Area",
        "shortName": "Oi PA",
        "type": "parking",
        "icon": "🅿️",
        "pos": [1150.0, 10.0, 1680.0],
        "desc": "Bayshore Route (Wangan) Southbound rest stop",
    },
    {
        "id": "rainbow_bridge",
        "name": "Rainbow Bridge (Route 11)",
        "shortName": "Rainbow Bridge",
        "type": "landmark",
        "icon": "🌉",
        "pos": [1566.9, 45.0, -3909.6],
        "desc": "Iconic double-deck suspension bridge across Tokyo Bay",
    },
    {
        "id": "tsurumi_bridge",
        "name": "Tsurumi Tsubasa Bridge (Route B)",
        "shortName": "Tsurumi Tsubasa Bridge",
        "type": "landmark",
        "icon": "🌉",
        "pos": [53.0, 45.0, 10965.4],
        "desc": "Iconic single-plane cable-stayed bridge on Bayshore Route North",
    },
    {
        "id": "yokohama_bay_bridge",
        "name": "Yokohama Bay Bridge (Route B)",
        "shortName": "Yokohama Bay Bridge",
        "type": "landmark",
        "icon": "🌉",
        "pos": [-6756.5, 48.0, 15196.5],
        "desc": "Massive 860m suspension bridge on Bayshore Route South",
    },
    {
        "id": "hakozaki_jct",
        "name": "Hakozaki Junction (6/9/C1)",
        "shortName": "Hakozaki JCT",
        "type": "junction",
        "icon": "🔀",
        "pos": [3689.1, 20.0, -8867.9],
        "desc": "Massive multi-level Tokyo interchange and rotary",
    },
    {
        "id": "ariake_jct",
        "name": "Ariake Junction (B/11)",
        "shortName": "Ariake JCT",
        "type": "junction",
        "icon": "🔀",
        "pos": [3490.7, 22.0, -3314.6],
        "desc": "Split between Wangan and Rainbow Bridge",
    },
    {
        "id": "tokyo_tower",
        "name": "Tokyo Tower (C1 Loop)",
        "shortName": "Tokyo Tower",
        "type": "landmark",
        "icon": "🗼",
        "pos": [-3.8, 45.0, -6053.3],
        "desc": "Iconic red-and-white communications tower next to C1 Loop",
    },
    {
        "id": "ginza_c1",
        "name": "Ginza (C1 Inner/Outer Loop)",
        "shortName": "Ginza (C1)",
        "type": "landmark",
        "icon": "🏙️",
        "pos": [1110.7, 18.0, -5727.6],
        "desc": "Heart of the C1 Expressway Loop",
    },
    {
        "id": "shibuya_3",
        "name": "Shibuya Crossing (Route 3)",
        "shortName": "Shibuya",
        "type": "landmark",
        "icon": "🏙️",
        "pos": [-4106.3, 25.0, -6450.6],
        "desc": "Shibuya Crossing and Route 3 Expressway",
    },
    {
        "id": "shinjuku_c2",
        "name": "Shinjuku (Route 4)",
        "shortName": "Shinjuku",
        "type": "landmark",
        "icon": "🏙️",
        "pos": [-4899.6, 32.0, -9770.8],
        "desc": "Route 4 Shinjuku skyscrapers",
    },
    {
        "id": "minato_mirai",
        "name": "Minato Mirai Yokohama (K3/K5)",
        "shortName": "Minato Mirai Yokohama",
        "type": "landmark",
        "icon": "🏙️",
        "pos": [-10954.5, 20.0, 14006.5],
        "desc": "Yokohama waterfront skyline and K3/K5 expressway",
    },
]

# All SRP 0.9.3 layouts use this Comfy Map coordinate space. Keeping the
# calibration keeps the navigation projection aligned even if an installation
# is missing a layout-specific map.ini.
SRP_MAP_CALIBRATION = {
    "mapWidth": 5544.0,
    "mapHeight": 8192.0,
    "scaleFactor": 3.30555129051209,
    "xOffset": 11119.814453125,
    "zOffset": 10454.576171875,
    "margin": 0.0,
    "drawingSize": 10.0,
}


class ACTrackFinder:
    """Finds Assetto Corsa tracks and parses map.ini calibration data."""

    def __init__(self, custom_ac_path: Optional[str] = None):
        self.ac_root = self.find_ac_root(custom_ac_path)
        self.cached_track_data: Dict[str, Any] = {}

    def find_ac_root(self, custom_path: Optional[str] = None) -> Optional[Path]:
        """Detects the Assetto Corsa root installation directory"""
        if custom_path and os.path.exists(custom_path):
            return Path(custom_path)

        env_path = os.environ.get("AC_ROOT") or os.environ.get("ASSETTO_CORSA_DIR")
        if env_path and os.path.exists(env_path):
            return Path(env_path)

        common_paths = [
            r"C:\Program Files (x86)\Steam\steamapps\common\assettocorsa",
            r"C:\Program Files\Steam\steamapps\common\assettocorsa",
            r"D:\SteamLibrary\steamapps\common\assettocorsa",
            r"E:\SteamLibrary\steamapps\common\assettocorsa",
            r"F:\SteamLibrary\steamapps\common\assettocorsa",
            r"G:\SteamLibrary\steamapps\common\assettocorsa",
            r"D:\Games\Steam\steamapps\common\assettocorsa",
            r"E:\Games\Steam\steamapps\common\assettocorsa",
        ]

        for p in common_paths:
            if os.path.exists(p) and os.path.exists(os.path.join(p, "AssettoCorsa.exe")):
                return Path(p)

        # Check Windows Uninstall Registry
        if sys.platform == "win32":
            try:
                import winreg
                for root_key in [winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER]:
                    for sub in [
                        r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\Steam App 244210",
                        r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\Steam App 244210",
                    ]:
                        try:
                            k = winreg.OpenKey(root_key, sub)
                            loc, _ = winreg.QueryValueEx(k, "InstallLocation")
                            winreg.CloseKey(k)
                            if loc and os.path.exists(loc) and os.path.exists(os.path.join(loc, "AssettoCorsa.exe")):
                                return Path(loc)
                        except Exception:
                            pass
            except Exception:
                pass

        # Try to parse Steam libraryfolders.vdf
        if sys.platform == "win32":
            steam_root = self._get_steam_root_from_registry()
            if steam_root:
                ac_dir = self._search_vdf_libraries(steam_root)
                if ac_dir:
                    return ac_dir

        return None

    def _get_steam_root_from_registry(self) -> Optional[Path]:
        if sys.platform != "win32":
            return None
        try:
            import winreg
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam")
            path, _ = winreg.QueryValueEx(key, "SteamPath")
            winreg.CloseKey(key)
            if path and os.path.exists(path):
                return Path(path)
        except Exception:
            pass
        return None

    def _search_vdf_libraries(self, steam_root: Path) -> Optional[Path]:
        vdf_path = steam_root / "steamapps" / "libraryfolders.vdf"
        if not vdf_path.exists():
            return None

        try:
            with open(vdf_path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()

            import re
            paths = re.findall(r'"path"\s+"([^"]+)"', content)
            for lib_path in paths:
                normalized = Path(lib_path.replace(r"\\", "\\"))
                ac_candidate = normalized / "steamapps" / "common" / "assettocorsa"
                if ac_candidate.exists() and (ac_candidate / "AssettoCorsa.exe").exists():
                    return ac_candidate
        except Exception:
            pass
        return None

    def _find_track_dir(self, track_name: str) -> Optional[Path]:
        """Finds track directory with fuzzy matching (e.g. shuto_revival_project_beta)"""
        if not self.ac_root or not track_name:
            return None

        tracks_base = self.ac_root / "content" / "tracks"
        if not tracks_base.exists():
            return None

        # Direct match
        direct = tracks_base / track_name
        if direct.exists():
            return direct

        # Clean name match (e.g. remove _ptb suffix or match shuto)
        cleaned = track_name.lower().replace("_ptb", "").replace("shutoko", "shuto")
        for d in tracks_base.iterdir():
            if d.is_dir():
                d_name = d.name.lower()
                if d_name == cleaned or (("shuto" in cleaned or "srp" in cleaned) and "shuto" in d_name):
                    return d

        return None

    def get_track_info(self, track_name: str, config: Optional[str] = None) -> Dict[str, Any]:
        """Retrieves map.ini calibration parameters and POIs for a track."""
        track_key = f"{track_name}_{config or ''}"
        if track_key in self.cached_track_data:
            return self.cached_track_data[track_key]

        is_srp = "shuto" in track_name.lower() or "srp" in track_name.lower()

        calibration = (
            SRP_MAP_CALIBRATION
            if is_srp
            else {
                "mapWidth": 1024.0,
                "mapHeight": 1024.0,
                "scaleFactor": 1.0,
                "xOffset": 0.0,
                "zOffset": 0.0,
                "margin": 0.0,
                "drawingSize": 10.0,
            }
        )

        track_data: Dict[str, Any] = {
            "trackName": track_name,
            "trackConfig": config or "",
            "isSRP": is_srp,
            **calibration,
            "pois": SRP_POIS if is_srp else [],
        }

        track_dir = self._find_track_dir(track_name)
        if not track_dir:
            self.cached_track_data[track_key] = track_data
            return track_data

        # Find layout / config candidates
        layout_candidates = []
        if config and config.strip():
            c_clean = config.strip().lower()
            layout_candidates.append(c_clean)
            # e.g. tatsumi_pa_traffic -> tatsumi_pa
            c_base = c_clean.replace("_traffic", "").replace("traffic_", "")
            if c_base != c_clean:
                layout_candidates.append(c_base)

        # Common SRP layouts fallback
        if is_srp:
            layout_candidates.extend(["main_layout", "tatsumi_pa", "shibaura_pa", "daishi_pa", "heiwajima_pa_n", "heiwajima_pa_s", "yoyogi_pa"])

        # Collect map.ini candidates
        ini_candidates = []
        for l in layout_candidates:
            l_dir = track_dir / l
            if l_dir.exists():
                ini_candidates.append(l_dir / "data" / "map.ini")
                ini_candidates.append(l_dir / "map.ini")
        ini_candidates.append(track_dir / "data" / "map.ini")
        ini_candidates.append(track_dir / "map.ini")

        # Also search layout subdirectories for map.ini.
        for sub in track_dir.iterdir():
            if sub.is_dir():
                ini_candidates.append(sub / "data" / "map.ini")

        # Parse the first available map.ini.
        for ini_path in ini_candidates:
            if ini_path.exists():
                try:
                    cp = configparser.ConfigParser(strict=False)
                    cp.read(str(ini_path))
                    section = "PARAMETERS" if cp.has_section("PARAMETERS") else (cp.sections()[0] if cp.sections() else None)
                    if section:
                        track_data["mapWidth"] = float(cp.get(section, "WIDTH", fallback=1024))
                        track_data["mapHeight"] = float(cp.get(section, "HEIGHT", fallback=1024))
                        track_data["scaleFactor"] = float(cp.get(section, "SCALE_FACTOR", fallback=1.0))
                        track_data["xOffset"] = float(cp.get(section, "X_OFFSET", fallback=0.0))
                        track_data["zOffset"] = float(cp.get(section, "Z_OFFSET", fallback=0.0))
                        track_data["margin"] = float(cp.get(section, "MARGIN", fallback=0.0))
                        track_data["drawingSize"] = float(cp.get(section, "DRAWING_SIZE", fallback=10.0))
                        break
                except Exception:
                    pass

        self.cached_track_data[track_key] = track_data
        return track_data
