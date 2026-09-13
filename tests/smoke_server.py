"""Verify a source or packaged server, including the actual Lua launch contract."""

import argparse
import asyncio
import json
from pathlib import Path
import re
import secrets
import socket
import ssl
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

import websockets


def unused_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def request_json(url: str, *, method: str = "GET", headers=None, payload=None, context=None):
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(url, data=data, headers=headers or {}, method=method)
    with urllib.request.urlopen(request, timeout=2.0, context=context) as response:
        return response.status, json.loads(response.read().decode("utf-8"))


def wait_until_ready(base_url: str, timeout: float = 30.0, context=None):
    deadline = time.monotonic() + timeout
    last_error = None
    while time.monotonic() < deadline:
        try:
            return request_json(f"{base_url}/api/status", context=context)
        except (OSError, urllib.error.URLError) as error:
            last_error = error
            time.sleep(0.2)
    raise RuntimeError(f"Server did not become ready: {last_error}")


async def receive_telemetry_frame(port: int, context=None):
    scheme = "wss" if context else "ws"
    uri = f"{scheme}://127.0.0.1:{port}/ws/telemetry"
    async with websockets.connect(uri, open_timeout=3.0, **({"ssl": context} if context else {})) as websocket:
        payload = await asyncio.wait_for(websocket.recv(), timeout=3.0)
        return json.loads(payload)


def launcher_arguments(lua_path: Path, port: int):
    """Read the shipped launcher so a test cannot silently use different flags."""
    source = lua_path.read_text(encoding="utf-8")
    match = re.search(r"arguments\s*=\s*\{([^}]+)\}", source)
    if not match:
        raise RuntimeError("Cannot find the Lua server launch arguments")
    control_port = port + 1 if port < 65535 else port - 1
    arguments = json.loads("[" + match[1].replace("tostring(server_port)", f'"{port}"').replace("tostring(controlPort())", f'"{control_port}"') + "]")
    return arguments


def unused_non_ephemeral_port():
    # Avoid Windows' ephemeral client-port range while the executable unpacks.
    for _ in range(100):
        port = 10000 + secrets.randbelow(20000)
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            try:
                sock.bind(("0.0.0.0", port))
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as control:
                    control.bind(("127.0.0.1", port + 1))
                return port
            except OSError:
                continue
    raise RuntimeError("Cannot find a free port for the launcher test")


def assert_mock_flag_rejected(server_command):
    try:
        result = subprocess.run(
            [*server_command, "--mock"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=5.0,
            check=False,
        )
    except subprocess.TimeoutExpired as error:
        raise RuntimeError("Public server accepted --mock and kept running") from error
    if result.returncode == 0:
        raise RuntimeError("Public server accepted the removed --mock flag")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--launcher", type=Path, help="Test this shipped Lua launcher's HTTPS configuration")
    parser.add_argument(
        "server_command",
        nargs="+",
        help="Executable command, for example AssettoGPS.Server.exe or wine AssettoGPS.Server.exe",
    )
    args = parser.parse_args()
    assert_mock_flag_rejected(args.server_command)

    port = unused_non_ephemeral_port() if args.launcher else unused_port()
    command = [
        *args.server_command,
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
    ]
    if args.launcher:
        command = [*args.server_command, *launcher_arguments(args.launcher, port)]
    server_log = tempfile.TemporaryFile(mode="w+", encoding="utf-8")
    process = subprocess.Popen(command, stdout=server_log, stderr=subprocess.STDOUT)
    context = None
    control_port = port + 1 if args.launcher else port
    base_url = f"http://127.0.0.1:{control_port}"
    control_headers = {
        "Content-Type": "application/json",
        "X-AssettoGPS-Control": "1",
    }

    try:
        status_code, status = wait_until_ready(base_url, context=context)
        if status_code != 200 or "mode" in status:
            raise RuntimeError(f"Unexpected status response: {status_code} {status}")

        with urllib.request.urlopen(f"{base_url}/", timeout=2.0, context=context) as response:
            frontend = response.read().decode("utf-8")
        if response.status != 200 or "<html" not in frontend.lower():
            raise RuntimeError("Bundled frontend was not served")
        if "mock" in frontend.lower() or "/api/mode" in frontend:
            raise RuntimeError("Public frontend still exposes generated telemetry")

        frontend_assets = {
            "/js/maplibre-bootstrap.js": {
                "application/javascript",
                "text/javascript",
            },
            "/vendor/maplibre-gl/maplibre-gl.mjs": {
                "application/javascript",
                "text/javascript",
            },
            "/vendor/maplibre-gl/maplibre-gl-shared.mjs": {
                "application/javascript",
                "text/javascript",
            },
            "/vendor/maplibre-gl/maplibre-gl-worker.mjs": {
                "application/javascript",
                "text/javascript",
            },
            "/vendor/maplibre-gl/maplibre-gl.css": {"text/css"},
            "/vendor/maplibre-gl/LICENSE.txt": {"text/plain"},
        }
        for asset_path, expected_content_types in frontend_assets.items():
            with urllib.request.urlopen(f"{base_url}{asset_path}", timeout=2.0, context=context) as response:
                content = response.read()
                content_type = response.headers.get_content_type()
            if (
                response.status != 200
                or not content
                or content_type not in expected_content_types
            ):
                raise RuntimeError(
                    f"Bundled asset is invalid: {asset_path} "
                    f"({response.status}, {content_type}, {len(content)} bytes)"
                )

        frame = asyncio.run(receive_telemetry_frame(control_port))
        if "connected" not in frame or frame.get("isMock"):
            raise RuntimeError(f"Unexpected WebSocket telemetry frame: {frame}")

        try:
            request_json(
                f"{base_url}/api/mode",
                method="POST",
                headers={"Content-Type": "application/json"},
                payload={"mode": "mock"},
                context=context,
            )
        except urllib.error.HTTPError as error:
            if error.code not in (404, 405):
                raise
        else:
            raise RuntimeError("Removed telemetry-mode API is still available")

        try:
            request_json(
                f"{base_url}/api/environment",
                method="POST",
                headers={"Content-Type": "application/json"},
                payload={"headlights": True},
                context=context,
            )
        except urllib.error.HTTPError as error:
            if error.code != 403:
                raise
        else:
            raise RuntimeError("Unprotected environment control request was accepted")

        environment_code, _ = request_json(
            f"{base_url}/api/environment",
            method="POST",
            headers=control_headers,
            payload={"headlights": True},
            context=context,
        )
        if environment_code != 200:
            raise RuntimeError(f"Environment endpoint returned {environment_code}")

        if args.launcher:
            expected_url = f"https://{status['localIp']}:{port}"
            if status.get("httpsUrl") != expected_url or status.get("httpUrl") is not None:
                raise RuntimeError(f"Launcher did not advertise HTTPS: {status}")
            phone_context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
            phone_context.check_hostname = False
            phone_context.verify_mode = ssl.CERT_NONE
            phone_url = f"https://127.0.0.1:{port}"
            _, secure_status = wait_until_ready(phone_url, context=phone_context)
            if not secure_status["cspConnected"]:
                raise RuntimeError(f"HTTPS did not preserve CSP environment state: {secure_status}")
            with urllib.request.urlopen(phone_url, context=phone_context, timeout=3) as response:
                if "<html" not in response.read().decode().lower():
                    raise RuntimeError("HTTPS frontend was not served")
            secure_frame = asyncio.run(receive_telemetry_frame(port, phone_context))
            if "connected" not in secure_frame:
                raise RuntimeError("WSS telemetry was not served")

        shutdown_code, _ = request_json(
            f"{base_url}/api/shutdown",
            method="POST",
            headers=control_headers,
            context=context,
        )
        if shutdown_code != 200:
            raise RuntimeError(f"Shutdown endpoint returned {shutdown_code}")

        return_code = process.wait(timeout=10.0)
        if return_code != 0:
            raise RuntimeError(f"Server exited with code {return_code}")
    except Exception:
        server_log.seek(0)
        print(server_log.read(), file=sys.stderr)
        raise
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5.0)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5.0)
        server_log.close()

    print(f"Server smoke test passed ({'Lua launcher + HTTPS/WSS' if args.launcher else 'loopback HTTP'}).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
