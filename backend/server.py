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

import psutil
import uvicorn
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles

import tls
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
uvicorn_https_server: Optional[uvicorn.Server] = None
_startup_started = False

# Set by main() once the server's actual bind configuration is known; used by
# build_pairing_urls() callers so /api/status and the startup banner agree.
# Stays None (and pairing URLs degrade to None) when main() never ran, e.g.
# in unit tests that call get_status() directly.
server_runtime_config: Optional[Dict[str, Any]] = None

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
        if uvicorn_https_server is not None:
            uvicorn_https_server.should_exit = True

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
    """Start the AC process watchdog when the server is ready.

    Dual HTTP+HTTPS mode runs the same FastAPI app under two uvicorn Server
    instances, each of which drives its own ASGI lifespan cycle - so this
    fires once per listener. Guard it so the watchdog thread (and the
    should-run-once startup work) only spawns a single time.
    """
    global _startup_started
    shutdown_event.clear()
    if _startup_started:
        return
    _startup_started = True
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


def get_all_local_ips() -> list:
    """Finds every IPv4 address bound to a local interface (LAN, VPN, etc).

    Resolving the machine's hostname only reports whatever the OS/DNS
    considers primary, which can be a VPN adapter instead of the LAN, so
    this walks the actual interface list via psutil instead.
    """
    ips = set()
    for addrs in psutil.net_if_addrs().values():
        for addr in addrs:
            if addr.family == socket.AF_INET and not addr.address.startswith("127."):
                ips.add(addr.address)
    return sorted(ips) or [get_local_ip()]


def build_pairing_urls(
    ip: str, port: int, https_port: Optional[int], https_only: bool
) -> "tuple[Optional[str], Optional[str]]":
    """Returns (http_url, https_url) for one address, given the server's TLS mode.

    - https_only: no plain-HTTP listener exists at all -> (None, https url on `port`).
    - https_port set (dual mode): both listeners are up -> (http url on `port`,
      https url on `https_port`).
    - Neither (loopback default, no TLS): -> (http url on `port`, None).
    """
    if https_only:
        return None, f"https://{ip}:{port}"
    https_url = f"https://{ip}:{https_port}" if https_port else None
    return f"http://{ip}:{port}", https_url


def print_startup_banner(
    host: str,
    port: int = 8080,
    https_port: Optional[int] = None,
    https_only: bool = False,
):
    """Prints a startup banner with the local and network pairing URLs"""
    print("=" * 65)
    print("  ASSETTO CORSA GPS MINIMAP SERVER")
    print("=" * 65)

    if is_loopback_host(host) and not https_only:
        print(f"  Local URL : http://localhost:{port}")
        print("  Only reachable from this machine (--host 127.0.0.1).")
        print("  Pass --host 0.0.0.0 to allow phone/tablet pairing over your network.")
    else:
        local_http, local_https = build_pairing_urls("localhost", port, https_port, https_only)
        print(f"  Local URL : {local_https or local_http}")

        local_ips = get_all_local_ips() if host == "0.0.0.0" else [host]
        network_urls = []
        for ip in local_ips:
            http_url, https_url = build_pairing_urls(ip, port, https_port, https_only)
            network_urls.append(https_url or http_url)

        if len(network_urls) == 1:
            print(f"  Phone / Tablet URL : {network_urls[0]}")
        else:
            print("  Phone / Tablet URLs (pick the one on your device's network):")
            for url in network_urls:
                print(f"    {url}")

        print('  First connection from a new device shows a one-time "connection')
        print('  isn\'t private" warning - tap Advanced > Proceed. The certificate')
        print("  is self-issued for this private server - this is expected, and")
        print("  is what lets phones keep their screen awake while navigating.")
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
    http_url = https_url = None
    if server_runtime_config is not None:
        http_url, https_url = build_pairing_urls(
            get_local_ip(),
            server_runtime_config["port"],
            server_runtime_config["https_port"],
            server_runtime_config["https_only"],
        )
        if server_runtime_config.get("control_port") is not None:
            http_url = None  # The loopback-only control listener is not a phone URL.
    return {
        "isGameRunning": server_state["isGameRunning"],
        "currentTrack": server_state["currentTrack"],
        "currentConfig": server_state["currentConfig"],
        "connectedClients": len(active_connections),
        "localIp": get_local_ip(),
        "cspConnected": csp_environment_available(),
        "httpUrl": http_url,
        "httpsUrl": https_url,
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
    parser.add_argument("--host", default=os.environ.get("HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8080")))
    parser.add_argument("--control-port", type=int, help="Serve HTTP controls on loopback at this port and HTTPS on --port.")
    parser.add_argument(
        "--https-port",
        type=int,
        default=(int(os.environ["HTTPS_PORT"]) if os.environ.get("HTTPS_PORT") else None),
        help="Port for the HTTPS listener when pairing over a non-loopback --host "
        "(default: --port + 1). Ignored with --https-only.",
    )
    parser.add_argument(
        "--https-only",
        action="store_true",
        help="Serve HTTPS only, on --port, instead of a plain-HTTP + HTTPS pair. "
        "For standalone HTTPS without the packaged launcher's HTTP control listener.",
    )
    args = parser.parse_args(argv)
    if args.control_port is not None:
        if not 1024 <= args.port <= 65535:
            parser.error("--port must be from 1024 to 65535 with --control-port")
        if not 1024 <= args.control_port <= 65535 or args.control_port == args.port:
            parser.error("--control-port must be a distinct port from 1024 to 65535")
        if args.https_only:
            parser.error("--control-port cannot be combined with --https-only")
    return args


async def _serve_both(primary: uvicorn.Server, secondary: uvicorn.Server) -> None:
    """Runs two uvicorn servers on one event loop until either one stops.

    Both must share a single event loop rather than run on separate threads:
    the whole app's shared mutable state (e.g. NavigationEngine) is only safe
    from concurrent WebSocket handlers because today's single event loop
    serializes them - two loops would let a desktop client (http) and a phone
    client (https) actually race. Uvicorn also installs its own SIGINT/SIGTERM
    handler per Server.serve() call, so with two servers only the most
    recently started one would see Ctrl+C; propagating should_exit on whichever
    stops first covers that too.
    """
    tasks = {asyncio.create_task(primary.serve()), asyncio.create_task(secondary.serve())}
    await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    primary.should_exit = True
    secondary.should_exit = True
    await asyncio.gather(*tasks)


def _port_is_available(host: str, port: int) -> bool:
    """Best-effort check for whether a bind would succeed.

    uvicorn.Server.startup() calls sys.exit() (not a catchable OSError) when
    its own bind_socket() fails - e.g. the port is already in use. Under
    _serve_both(), both listeners share one event loop, so a SystemExit
    raised inside the HTTPS task's coroutine propagates out of the whole
    asyncio.run() call and kills the primary HTTP listener too (verified: a
    conflicting port + real dual-mode run exits the whole process with code
    3). Checking with a plain socket first - and never constructing the
    HTTPS Server/task at all if it fails - avoids ever reaching uvicorn's
    sys.exit() path. There's a small unavoidable TOCTOU race against
    whatever binds the port between this check and the real one, but that's
    strictly better than today's unconditional crash-on-conflict.
    """
    family = socket.AF_INET6 if ":" in host else socket.AF_INET
    probe = socket.socket(family, socket.SOCK_STREAM)
    probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        probe.bind((host, port))
        return True
    except OSError:
        return False
    finally:
        probe.close()


def main(argv=None):
    global uvicorn_server, uvicorn_https_server, server_runtime_config, _startup_started

    args = parse_args(argv)
    loopback = is_loopback_host(args.host)
    dual_mode = args.control_port is not None or (not args.https_only and not loopback)
    https_only = args.https_only
    http_port = args.control_port if args.control_port is not None else args.port
    http_host = "127.0.0.1" if args.control_port is not None else args.host

    https_port = None
    if dual_mode:
        https_port = args.port if args.control_port is not None else (args.https_port if args.https_port is not None else args.port + 1)

    cert_path = key_path = None
    if https_only or dual_mode:
        # https-only binds the one HTTPS listener on --port; dual mode binds
        # it on the separate https_port alongside the unchanged HTTP listener.
        bind_port = args.port if https_only else https_port
        ips = get_all_local_ips() if args.host == "0.0.0.0" else [args.host]
        hosts = sorted({"localhost", "127.0.0.1", *ips})
        try:
            cert_path, key_path = tls.ensure_self_signed_certificate(hosts)
            if not _port_is_available(args.host, bind_port):
                raise OSError(f"port {bind_port} is already in use")
            https_config = uvicorn.Config(
                app, host=args.host, port=bind_port,
                ssl_certfile=str(cert_path), ssl_keyfile=str(key_path),
                log_level="warning",
            )
            # Load TLS before starting either listener, inside the fallback
            # handler. Uvicorn otherwise defers this until Server.serve().
            https_config.load()
        except Exception as e:
            # Preserve service over HTTP if certificate setup or the HTTPS
            # port fails. The launcher detects and reports this fallback;
            # release smoke tests require packaged HTTPS to work.
            print(f"[!] Could not set up HTTPS ({e}); continuing with HTTP only.", file=sys.stderr, flush=True)
            dual_mode = False
            https_only = False
            https_port = None

    server_runtime_config = {
        "port": http_port,
        "control_port": args.control_port,
        "https_port": https_port,
        "https_only": https_only,
    }

    print_startup_banner(args.host, http_port, https_port, https_only)
    shutdown_event.clear()
    _startup_started = False

    if https_only:
        uvicorn_server = uvicorn.Server(https_config)
        try:
            uvicorn_server.run()
        finally:
            shutdown_event.set()
            ac_shm.disconnect()
            uvicorn_server = None
        return

    http_config = uvicorn.Config(app, host=http_host, port=http_port, log_level="warning")
    uvicorn_server = uvicorn.Server(http_config)

    if dual_mode:
        uvicorn_https_server = uvicorn.Server(https_config)

    try:
        if dual_mode:
            asyncio.run(_serve_both(uvicorn_server, uvicorn_https_server))
        else:
            uvicorn_server.run()
    finally:
        shutdown_event.set()
        ac_shm.disconnect()
        uvicorn_server = None
        uvicorn_https_server = None


if __name__ == "__main__":
    main()
