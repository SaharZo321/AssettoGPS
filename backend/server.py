"""
Assetto Corsa Waze/GPS Minimap Backend Server
FastAPI + WebSockets + Automatic AC Track & Telemetry Streaming
"""

import argparse
import os
import sys
import json
import asyncio
import ipaddress
import mimetypes
import socket
import threading
import time
from pathlib import Path
from typing import Set, Dict, Any, Optional, Callable

import uvicorn
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles

from ac_shared_memory import AssettoCorsaSharedMemory, ac_shared_memory_available
from ac_track_finder import ACTrackFinder
from navigation import NavigationEngine

# PyInstaller extracts bundled data into sys._MEIPASS. Source runs use the repo root.
if getattr(sys, "frozen", False):
    RUNTIME_ROOT = Path(sys._MEIPASS)
else:
    RUNTIME_ROOT = Path(__file__).resolve().parent.parent
FRONTEND_DIR = RUNTIME_ROOT / "frontend"

# Serve JavaScript consistently when the host MIME database lacks .mjs entries.
mimetypes.add_type("text/javascript", ".js")
mimetypes.add_type("text/javascript", ".mjs")

app = FastAPI(title="Assetto Corsa GPS Minimap Server")

# Core singletons
ac_shm = AssettoCorsaSharedMemory()
track_finder = ACTrackFinder()
nav_engine = NavigationEngine()
telemetry_reader: Callable[[], Optional[Dict[str, Any]]] = ac_shm.read
telemetry_reset: Optional[Callable[[], None]] = None
ac_watchdog_enabled = True

CONTROL_HEADER_NAME = "x-assettogps-control"
CONTROL_HEADER_VALUE = "1"
shutdown_event = threading.Event()
uvicorn_server: Optional[uvicorn.Server] = None

# Active WebSocket connections
active_connections: Set[WebSocket] = set()

# Server state
server_state = {
    "currentTrack": "shutoko_revival_project_beta",
    "currentConfig": "ptb",
    "isGameRunning": False,
    "lastFrame": None,
}

# Environmental lighting state reported by the CSP in-game bridge.
environment_state = {
    "headlights": False,
    "isNight": False,
    "isDark": False,
    "ambient": 1.0,
    "lightSuggestion": 0.0,
    "ambientOcclusion": 1.0,
    "source": "unavailable",
}
environment_updated_at = 0.0
CSP_ENVIRONMENT_TIMEOUT_SECONDS = 3.0


def csp_environment_available(now: Optional[float] = None) -> bool:
    """Return whether fresh ambient-light data is arriving from the CSP app."""
    current_time = time.monotonic() if now is None else now
    return (
        environment_state.get("source") == "csp"
        and environment_updated_at > 0.0
        and current_time - environment_updated_at <= CSP_ENVIRONMENT_TIMEOUT_SECONDS
    )


def get_environment_snapshot(now: Optional[float] = None) -> Dict[str, Any]:
    """Build the public lighting payload, including CSP sensor availability."""
    return {**environment_state, "available": csp_environment_available(now)}


def is_ac_game_active() -> bool:
    """Return True only if Assetto Corsa has created all telemetry buffers."""
    return ac_shared_memory_available()


def request_server_shutdown(delay: float = 0.0):
    """Ask Uvicorn to stop after an optional response-flush delay."""
    def stop_server():
        if delay > 0 and shutdown_event.wait(delay):
            return
        shutdown_event.set()
        if uvicorn_server is not None:
            uvicorn_server.should_exit = True

    threading.Thread(target=stop_server, daemon=True).start()


def ac_watchdog_loop():
    """Monitors Assetto Corsa session. Once active, if AC closes, auto-shuts down server cleanly."""
    has_seen_game = False
    inactive_count = 0

    while not shutdown_event.wait(2.0):
        try:
            is_active = is_ac_game_active()
            if is_active:
                has_seen_game = True
                inactive_count = 0
            elif has_seen_game:
                inactive_count += 1
                # If game was active and now has exited for > 8 seconds
                if inactive_count >= 4:
                    print("[-] Assetto Corsa closed. Auto-shutting down GPS server.")
                    request_server_shutdown()
                    return
        except Exception:
            pass


@app.on_event("startup")
async def on_startup():
    """Start the AC process watchdog when the server is ready."""
    shutdown_event.clear()
    if ac_watchdog_enabled:
        threading.Thread(target=ac_watchdog_loop, daemon=True).start()


def is_loopback_host(host: Optional[str]) -> bool:
    """Return whether a client address is a local loopback address."""
    if not host:
        return False
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def require_local_control(request: Request):
    """Protect server-control endpoints from LAN and cross-site requests."""
    client_host = request.client.host if request.client else None
    control_value = request.headers.get(CONTROL_HEADER_NAME)
    if not is_loopback_host(client_host) or control_value != CONTROL_HEADER_VALUE:
        raise HTTPException(status_code=403, detail="Local AssettoGPS control request required")


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
    print("  ASSETTO CORSA GPS MINIMAP SERVER")
    print("=" * 65)
    print(f"  Local URL : {local_url}")
    print(f"  Phone / Tablet URL : {network_url}")
    print("-" * 65)
    print("  Open on your mobile browser / tablet:")
    try:
        import qrcode

        qr = qrcode.QRCode(box_size=1, border=2)
        qr.add_data(network_url)
        qr.make(fit=True)
        qr.print_ascii(invert=True)
    except Exception:
        print(f"  [QR Code Generator: open {network_url} in mobile browser]")
    print("=" * 65)
    print("  Press [Ctrl + R] or [R] in this terminal to reset the session!")
    print("  Telemetry engine running... Ready for connections!\n")


def reset_session_state():
    """Reset trip/navigation state and the configured telemetry source, if any."""
    if telemetry_reset is not None:
        telemetry_reset()
    nav_engine.trip_distance_m = 0.0
    nav_engine.top_speed_kmh = 0.0
    nav_engine.last_pos = None


def start_keyboard_listener():
    """Listen for Ctrl+R or R in the terminal to reset session statistics."""
    if sys.platform != "win32":
        return

    import msvcrt

    def _listen():
        while True:
            try:
                if msvcrt.kbhit():
                    ch = msvcrt.getch()
                    if ch in (b"\x12", b"r", b"R"):
                        print("\n🔄 [RESET] Resetting trip and navigation statistics...")
                        reset_session_state()
                time.sleep(0.08)
            except Exception:
                break

    t = threading.Thread(target=_listen, daemon=True)
    t.start()


@app.get("/api/status")
async def get_status():
    """Returns server and game connection status"""
    return {
        "isGameRunning": server_state["isGameRunning"],
        "currentTrack": server_state["currentTrack"],
        "currentConfig": server_state["currentConfig"],
        "connectedClients": len(active_connections),
        "localIp": get_local_ip(),
        "cspConnected": csp_environment_available(),
    }


@app.post("/api/reset")
async def reset_session():
    """Reset trip statistics and navigation state."""
    reset_session_state()
    return {"status": "ok", "message": "Session reset"}


@app.get("/api/track")
async def get_track_data():
    """Returns current track calibration and POIs"""
    track_name = server_state["currentTrack"] or "shutoko_revival_project_beta"
    config = server_state["currentConfig"]
    track_info = track_finder.get_track_info(track_name, config)
    return track_info


@app.post("/api/environment")
async def set_environment(payload: Dict[str, Any], request: Request):
    """Receive ambient-light data from the local CSP in-game bridge."""
    global environment_updated_at
    require_local_control(request)
    if "headlights" in payload:
        environment_state["headlights"] = bool(payload["headlights"])
    if "isNight" in payload:
        environment_state["isNight"] = bool(payload["isNight"])
    if "isDark" in payload:
        environment_state["isDark"] = bool(payload["isDark"])
    for key in ("ambient", "lightSuggestion", "ambientOcclusion"):
        if key not in payload:
            continue
        try:
            environment_state[key] = max(0.0, min(1.0, float(payload[key])))
        except (ValueError, TypeError):
            pass
    environment_state["source"] = "csp"
    environment_updated_at = time.monotonic()
    return {"status": "ok", "environment": get_environment_snapshot()}


@app.post("/api/shutdown")
async def shutdown_server(request: Request):
    """Cleanly terminates the server process when stopped from in-game AC UI"""
    require_local_control(request)
    request_server_shutdown(delay=0.3)
    return {"status": "shutting_down"}


@app.get("/api/environment")
async def get_environment():
    """Returns current environmental lighting state"""
    return get_environment_snapshot()


@app.websocket("/ws/telemetry")
async def websocket_endpoint(websocket: WebSocket):
    """Real-time 30-60 Hz telemetry streaming endpoint"""
    await websocket.accept()
    active_connections.add(websocket)

    try:
        while True:
            try:
                telemetry_data = telemetry_reader()
            except Exception:
                telemetry_data = None

            if (
                telemetry_data
                and telemetry_data.get("connected")
                and telemetry_data.get("status", 0) > 0
            ):
                frame = telemetry_data
                server_state["isGameRunning"] = bool(
                    frame.get("isGameRunning", True)
                )
                server_state["currentTrack"] = frame.get("track", "")
                server_state["currentConfig"] = frame.get("trackConfig", "")
            else:
                server_state["isGameRunning"] = False
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
                **get_environment_snapshot(),
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
        if websocket in active_connections:
            active_connections.remove(websocket)


# Mount static frontend directory
if FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="AssettoGPS local telemetry server")
    parser.add_argument("--host", default=os.environ.get("HOST", "0.0.0.0"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8080")))
    return parser.parse_args(argv)


def main(argv=None):
    global uvicorn_server

    args = parse_args(argv)
    print_startup_banner(args.port)
    shutdown_event.clear()
    config = uvicorn.Config(
        app,
        host=args.host,
        port=args.port,
        log_level="warning",
    )
    uvicorn_server = uvicorn.Server(config)
    try:
        uvicorn_server.run()
    finally:
        shutdown_event.set()
        ac_shm.disconnect()
        uvicorn_server = None


if __name__ == "__main__":
    main()
