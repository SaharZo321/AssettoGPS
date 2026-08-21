"""
Assetto Corsa Waze/GPS Minimap Backend Server
FastAPI + WebSockets + Automatic AC Track & Telemetry Streaming
"""

import os
import sys
import json
import asyncio
import socket
import threading
import time
from pathlib import Path
from typing import List, Set, Dict, Any, Optional

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Response
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from ac_shared_memory import AssettoCorsaSharedMemory
from ac_track_finder import ACTrackFinder
from navigation import NavigationEngine
from mock_telemetry import MockTelemetryGenerator

# Base paths
BASE_DIR = Path(__file__).resolve().parent.parent
FRONTEND_DIR = BASE_DIR / "frontend"

app = FastAPI(title="Assetto Corsa GPS Minimap Server")

# Allow CORS for external devices
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Core singletons
ac_shm = AssettoCorsaSharedMemory()
track_finder = ACTrackFinder()
nav_engine = NavigationEngine()
mock_gen = MockTelemetryGenerator()

# Active WebSocket connections
active_connections: Set[WebSocket] = set()

# Server state
server_state = {
    "mode": "auto",  # "auto", "live", "mock"
    "currentTrack": "shutoko_revival_project_beta",
    "currentConfig": "ptb",
    "isGameRunning": False,
    "lastFrame": None,
}

# Environmental lighting state (from CSP bridge, tunnels, or manual overrides)
environment_state = {
    "headlights": False,
    "sunAngle": 1.0,  # 1.0 = noon, 0.0 = sunset, -1.0 = midnight
    "isNight": False,
    "source": "auto",  # "auto", "csp", "manual"
}


def get_local_ip() -> str:
    """Finds the local LAN IP address of this machine"""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
    except Exception:
        ip = "127.0.0.1"
    finally:
        s.close()
    return ip


def print_startup_banner(port: int = 8080):
    """Prints a stylish banner with pairing URL and QR code in terminal"""
    local_ip = get_local_ip()
    local_url = f"http://localhost:{port}"
    network_url = f"http://{local_ip}:{port}"

    print("=" * 65)
    print("  🏁 ASSETTO CORSA WAZE/GPS MINIMAP SERVER")
    print("=" * 65)
    print(f"  🖥️  Local 2nd Screen URL : {local_url}")
    print(f"  📱 Phone / Tablet URL    : {network_url}")
    print("-" * 65)
    print("  👉 Scan with your Phone Camera to open the GPS dashboard:")
    try:
        import qrcode

        qr = qrcode.QRCode(box_size=1, border=2)
        qr.add_data(network_url)
        qr.make(fit=True)
        qr.print_ascii(invert=True)
    except Exception:
        print(f"  [QR Code Generator: open {network_url} in mobile browser]")
    print("=" * 65)
    print("  ⌨️  Press [Ctrl + R] or [R] in this terminal to reset the session!")
    print("  Telemetry engine running... Ready for connections!\n")


def start_keyboard_listener():
    """Listens for Ctrl+R or 'r' in the terminal to reset the server/telemetry"""
    if sys.platform != "win32":
        return

    import msvcrt

    def _listen():
        while True:
            try:
                if msvcrt.kbhit():
                    ch = msvcrt.getch()
                    if ch in (b"\x12", b"r", b"R"):
                        print("\n🔄 [RESET] Resetting telemetry simulator and trip statistics...")
                        mock_gen.start_time = time.time()
                        nav_engine.trip_distance_m = 0.0
                        nav_engine.top_speed_kmh = 0.0
                        nav_engine.last_pos = None
                time.sleep(0.08)
            except Exception:
                break

    t = threading.Thread(target=_listen, daemon=True)
    t.start()


@app.get("/api/status")
async def get_status():
    """Returns server and game connection status"""
    return {
        "mode": server_state["mode"],
        "isGameRunning": server_state["isGameRunning"],
        "currentTrack": server_state["currentTrack"],
        "currentConfig": server_state["currentConfig"],
        "connectedClients": len(active_connections),
        "localIp": get_local_ip(),
    }


@app.post("/api/reset")
async def reset_session():
    """Resets simulator, trip stats, and navigation state"""
    mock_gen.start_time = time.time()
    nav_engine.trip_distance_m = 0.0
    nav_engine.top_speed_kmh = 0.0
    nav_engine.last_pos = None
    return {"status": "ok", "message": "Session reset"}


@app.get("/api/track")
async def get_track_data():
    """Returns current track calibration and POIs"""
    track_name = server_state["currentTrack"] or "shutoko_revival_project_beta"
    config = server_state["currentConfig"]
    track_info = track_finder.get_track_info(track_name, config)
    return track_info


@app.get("/api/track/map.png")
async def get_track_map_image(track: Optional[str] = None):
    """Serves the track map image or a stylized fallback"""
    track_name = track or server_state["currentTrack"] or "shutoko_revival_project_beta"
    config = server_state["currentConfig"]
    track_info = track_finder.get_track_info(track_name, config)

    if track_info.get("hasMapImage") and track_info.get("mapImagePath"):
        img_path = Path(track_info["mapImagePath"])
        if img_path.exists():
            return FileResponse(str(img_path), media_type="image/png")

    # Generate a clean dark vector road map image
    from io import BytesIO
    from PIL import Image, ImageDraw

    img = Image.new("RGBA", (1024, 1024), (11, 15, 25, 255))
    draw = ImageDraw.Draw(img)

    # Grid background
    grid_color = (25, 33, 50, 255)
    for x in range(0, 1024, 64):
        draw.line([(x, 0), (x, 1024)], fill=grid_color, width=1)
    for y in range(0, 1024, 64):
        draw.line([(0, y), (1024, y)], fill=grid_color, width=1)

    # Draw simulated Tokyo Expressway road loops
    scale = track_info.get("scaleFactor", 0.08)
    x_off = track_info.get("xOffset", 512.0)
    z_off = track_info.get("zOffset", 512.0)

    road_glow = (2, 132, 199, 120)
    road_core = (56, 189, 248, 240)

    wps = mock_gen.waypoints
    for i in range(len(wps) - 1):
        p1 = wps[i]
        p2 = wps[i + 1]
        u1 = p1[0] * scale + x_off
        v1 = p1[1] * scale + z_off
        u2 = p2[0] * scale + x_off
        v2 = p2[1] * scale + z_off

        # Glow layer
        draw.line([(u1, v1), (u2, v2)], fill=road_glow, width=16)
        # Main asphalt/neon lane
        draw.line([(u1, v1), (u2, v2)], fill=road_core, width=8)

    buf = BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return Response(content=buf.getvalue(), media_type="image/png")


@app.post("/api/mode")
async def set_mode(payload: Dict[str, str]):
    """Switches between auto, live, and mock modes"""
    mode = payload.get("mode", "auto")
    if mode in ["auto", "live", "mock"]:
        server_state["mode"] = mode
    return {"status": "ok", "mode": server_state["mode"]}


@app.post("/api/environment")
async def set_environment(payload: Dict[str, Any]):
    """Receives in-game environmental lighting, headlights, and night status from CSP or companion mods"""
    if "headlights" in payload:
        environment_state["headlights"] = bool(payload["headlights"])
    if "isNight" in payload:
        environment_state["isNight"] = bool(payload["isNight"])
    if "sunAngle" in payload:
        try:
            environment_state["sunAngle"] = float(payload["sunAngle"])
        except (ValueError, TypeError):
            pass
    environment_state["source"] = "csp"
    return {"status": "ok", "environment": environment_state}


@app.get("/api/environment")
async def get_environment():
    """Returns current environmental lighting state"""
    return environment_state


@app.websocket("/ws/telemetry")
async def websocket_endpoint(websocket: WebSocket):
    """Real-time 30-60 Hz telemetry streaming endpoint"""
    await websocket.accept()
    active_connections.add(websocket)

    async def receive_loop():
        """Background task to listen for client commands without blocking sending"""
        try:
            while True:
                msg = await websocket.receive_text()
                try:
                    data = json.loads(msg)
                    if "setMode" in data:
                        server_state["mode"] = data["setMode"]
                except Exception:
                    pass
        except Exception:
            pass

    receive_task = asyncio.create_task(receive_loop())

    try:
        while True:
            mode = server_state["mode"]
            live_data = None
            if mode in ["auto", "live"]:
                try:
                    live_data = ac_shm.read()
                except Exception:
                    live_data = None

            if live_data and live_data.get("connected") and live_data.get("status", 0) > 0:
                server_state["isGameRunning"] = True
                server_state["currentTrack"] = live_data.get("track", "")
                server_state["currentConfig"] = live_data.get("trackConfig", "")
                frame = live_data
            elif mode in ["mock", "auto"]:
                server_state["isGameRunning"] = False
                frame = mock_gen.get_frame()
                server_state["currentTrack"] = frame.get("track", "shutoko_revival_project_beta")
                server_state["currentConfig"] = frame.get("trackConfig", "ptb")
            else:
                frame = {"connected": False, "isGameRunning": False}

            # Enrich with Navigation & POIs
            track_info = track_finder.get_track_info(
                server_state["currentTrack"], server_state["currentConfig"]
            )
            pois = track_info.get("pois", [])

            car_pos = frame.get("carPosition", [0, 0, 0])
            speed = frame.get("speedKmh", 0.0)
            heading = frame.get("headingRad", 0.0)

            track_name = server_state["currentTrack"]
            car_model = frame.get("carModel", "")
            is_srp = track_info.get("isSRP", False)

            nav_data = nav_engine.update(
                car_pos, speed, heading, pois, track_name, car_model, is_srp
            )
            frame["nav"] = nav_data
            frame["trackInfo"] = {
                "scaleFactor": track_info.get("scaleFactor", 1.0),
                "xOffset": track_info.get("xOffset", 0.0),
                "zOffset": track_info.get("zOffset", 0.0),
                "mapWidth": track_info.get("mapWidth", 1024),
                "mapHeight": track_info.get("mapHeight", 1024),
                "pois": pois,
            }
            frame["environment"] = {
                "inTunnel": bool(nav_data.get("inTunnel", False)),
                "tunnelName": nav_data.get("tunnelName", None),
                "headlights": bool(environment_state.get("headlights", False)),
                "isNight": bool(environment_state.get("isNight", False)),
                "sunAngle": float(environment_state.get("sunAngle", 1.0)),
                "source": str(environment_state.get("source", "auto")),
            }

            server_state["lastFrame"] = frame

            # Send telemetry JSON packet to client
            await websocket.send_text(json.dumps(frame))
            await asyncio.sleep(0.033)  # ~30 Hz broadcast rate
    except WebSocketDisconnect:
        pass
    except Exception as e:
        print(f"WebSocket send error: {e}")
    finally:
        receive_task.cancel()
        if websocket in active_connections:
            active_connections.remove(websocket)


# Mount static frontend directory
if FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")


def main():
    port = int(os.environ.get("PORT", 8080))
    print_startup_banner(port)
    backend_dir = str(Path(__file__).resolve().parent)
    uvicorn.run(
        "server:app",
        host="0.0.0.0",
        port=port,
        reload=True,
        reload_dirs=[backend_dir],
        log_level="warning",
    )


if __name__ == "__main__":
    main()
