"""
Assetto Corsa GPS Companion In-Game Python App
Auto-boots the GPS Minimap Server on session load, displays IP pairing URL in-game,
allows toggling server ON/OFF, and broadcasts real-time headlights and lighting.
"""

import sys
import os
import platform

# Add standard library paths if needed
try:
    current_dir = os.path.dirname(__file__)
    system_dir = os.path.abspath(os.path.join(current_dir, "..", "system"))
    if system_dir not in sys.path:
        sys.path.append(system_dir)
except Exception:
    pass

import ac
import acsys
import time
import socket
import threading
import subprocess

# Application Constants
APP_NAME = "AssettoGPS"
SERVER_PORT = 8080
UDP_PORT = 8088

# Global state
app_window = 0
lbl_title = 0
lbl_status = 0
lbl_ip = 0
btn_toggle = 0

server_process = None
server_running = False
local_ip_str = "127.0.0.1"
last_update_time = 0.0
last_heartbeat_check = 0.0
server_dir = r"C:\Coding\AssettoMiniMap"


def log_debug(msg):
    """Writes debug messages to AC log and local log file"""
    try:
        ac.log("AssettoGPS: " + str(msg))
        log_file = os.path.join(os.path.dirname(__file__), "debug.log")
        with open(log_file, "a") as f:
            f.write(str(time.strftime("%H:%M:%S")) + " - " + str(msg) + "\n")
    except Exception:
        pass


def get_local_ip():
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


def is_server_alive():
    """Checks if the GPS Minimap server is responding on port 8080"""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(0.2)
    try:
        s.connect(("127.0.0.1", SERVER_PORT))
        s.close()
        return True
    except Exception:
        return False


def start_server():
    """Starts the GPS Minimap server as a background process"""
    global server_process, server_running, server_dir

    if is_server_alive():
        server_running = True
        return True

    server_script = os.path.join(server_dir, "backend", "server.py")
    log_debug("Attempting to start server at " + str(server_script))

    try:
        uv_paths = [
            os.path.join(os.path.expanduser("~"), ".local", "bin", "uv.exe"),
            os.path.join(os.path.expanduser("~"), ".cargo", "bin", "uv.exe"),
            os.path.join(os.environ.get("LOCALAPPDATA", ""), "uv", "uv.exe"),
            "uv.exe",
        ]
        uv_cmd = None
        for u in uv_paths:
            if os.path.exists(u):
                uv_cmd = u
                break

        creationflags = 0x08000000 if sys.platform == "win32" else 0

        if uv_cmd:
            cmd = [uv_cmd, "run", "backend/server.py"]
        else:
            cmd = [sys.executable, server_script]

        server_process = subprocess.Popen(
            cmd,
            cwd=server_dir,
            creationflags=creationflags,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        server_running = True
        log_debug("Server process started with PID " + str(server_process.pid))
        return True
    except Exception as e:
        log_debug("Failed to start server: " + str(e))
        return False


def stop_server():
    """Stops the GPS Minimap server process"""
    global server_process, server_running
    try:
        if server_process and server_process.poll() is None:
            server_process.terminate()
            server_process = None
        server_running = False
        log_debug("Server process stopped")
    except Exception as e:
        log_debug("Failed to stop server: " + str(e))


def on_toggle_clicked(*args):
    """Callback when user clicks the in-game Toggle Server button"""
    global server_running
    if is_server_alive():
        stop_server()
        time.sleep(0.3)
        update_ui_state(False)
    else:
        start_server()
        time.sleep(0.5)
        update_ui_state(True)


def update_ui_state(active):
    """Updates in-game AC window labels and button text"""
    global lbl_status, lbl_ip, btn_toggle, local_ip_str

    try:
        if active:
            ac.setText(lbl_status, "Status: ACTIVE (Online)")
            ac.setFontColor(lbl_status, 0.2, 0.9, 0.4, 1.0)
            ac.setText(lbl_ip, "Phone URL: http://" + str(local_ip_str) + ":" + str(SERVER_PORT))
            ac.setFontColor(lbl_ip, 0.22, 0.74, 0.97, 1.0)
            ac.setText(btn_toggle, "Stop Server")
        else:
            ac.setText(lbl_status, "Status: STOPPED (Offline)")
            ac.setFontColor(lbl_status, 0.9, 0.3, 0.3, 1.0)
            ac.setText(lbl_ip, "Local IP: " + str(local_ip_str))
            ac.setFontColor(lbl_ip, 0.6, 0.6, 0.6, 1.0)
            ac.setText(btn_toggle, "Start Server")
    except Exception:
        pass


def send_udp_telemetry(headlights, ambient=1.0, is_dark=False):
    """Sends lighting and headlight state to backend via local UDP"""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(0.02)
        payload = ('{"headlights": ' + str(bool(headlights)).lower() + 
                   ', "ambient": ' + str(float(ambient)) + 
                   ', "isNight": ' + str(bool(is_dark)).lower() + '}').encode("utf-8")
        sock.sendto(payload, ("127.0.0.1", UDP_PORT))
        sock.close()
    except Exception:
        pass


def acMain(ac_version):
    """Assetto Corsa In-Game Plugin Initialization"""
    global app_window, lbl_title, lbl_status, lbl_ip, btn_toggle, local_ip_str

    try:
        log_debug("acMain called with AC version: " + str(ac_version))

        app_window = ac.newApp("Assetto GPS")
        ac.setSize(app_window, 290, 130)
        ac.drawBorder(app_window, 1)
        ac.setBackgroundOpacity(app_window, 0.85)

        lbl_title = ac.addLabel(app_window, "ASSETTO CORSA GPS")
        ac.setPosition(lbl_title, 12, 28)
        ac.setFontSize(lbl_title, 12)
        ac.setFontColor(lbl_title, 1.0, 1.0, 1.0, 1.0)

        lbl_status = ac.addLabel(app_window, "Status: Checking...")
        ac.setPosition(lbl_status, 12, 50)
        ac.setFontSize(lbl_status, 11)

        lbl_ip = ac.addLabel(app_window, "Phone URL: http://...")
        ac.setPosition(lbl_ip, 12, 70)
        ac.setFontSize(lbl_ip, 12)

        btn_toggle = ac.addButton(app_window, "Toggle Server")
        ac.setPosition(btn_toggle, 12, 95)
        ac.setSize(btn_toggle, 266, 24)
        ac.addOnClickedListener(btn_toggle, on_toggle_clicked)

        local_ip_str = get_local_ip()

        # Background auto-boot thread
        t = threading.Thread(target=auto_boot_sequence)
        t.daemon = True
        t.start()

        log_debug("acMain completed successfully")
    except Exception as e:
        log_debug("Error in acMain: " + str(e))

    return "Assetto GPS"


def auto_boot_sequence():
    """Background boot worker to verify and launch server without freezing UI"""
    time.sleep(0.5)
    if not is_server_alive():
        start_server()
        time.sleep(1.0)
    alive = is_server_alive()
    update_ui_state(alive)


def acUpdate(deltaT):
    """Called every frame in Assetto Corsa"""
    global last_update_time, last_heartbeat_check

    now = time.time()

    if now - last_update_time >= 0.066:
        last_update_time = now
        try:
            headlights = False
            try:
                headlights = bool(ac.getCarState(0, acsys.CS.Headlights))
            except Exception:
                pass

            is_dark = bool(headlights)
            send_udp_telemetry(headlights=headlights, ambient=0.2 if is_dark else 1.0, is_dark=is_dark)
        except Exception:
            pass

    if now - last_heartbeat_check >= 2.0:
        last_heartbeat_check = now
        alive = is_server_alive()
        update_ui_state(alive)


def acShutdown():
    """Called when Assetto Corsa session ends"""
    log_debug("acShutdown called")


