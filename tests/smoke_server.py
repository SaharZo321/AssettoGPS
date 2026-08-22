"""Launch a source or packaged AssettoGPS server and verify its HTTP lifecycle."""

import argparse
import asyncio
import json
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request

import websockets


def unused_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def request_json(url: str, *, method: str = "GET", headers=None, payload=None):
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(url, data=data, headers=headers or {}, method=method)
    with urllib.request.urlopen(request, timeout=2.0) as response:
        return response.status, json.loads(response.read().decode("utf-8"))


def wait_until_ready(base_url: str, timeout: float = 20.0):
    deadline = time.monotonic() + timeout
    last_error = None
    while time.monotonic() < deadline:
        try:
            return request_json(f"{base_url}/api/status")
        except (OSError, urllib.error.URLError) as error:
            last_error = error
            time.sleep(0.2)
    raise RuntimeError(f"Server did not become ready: {last_error}")


async def receive_telemetry_frame(port: int):
    uri = f"ws://127.0.0.1:{port}/ws/telemetry"
    async with websockets.connect(uri, open_timeout=3.0) as websocket:
        payload = await asyncio.wait_for(websocket.recv(), timeout=3.0)
        return json.loads(payload)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "server_command",
        nargs="+",
        help="Executable command, for example AssettoGPS.Server.exe or wine AssettoGPS.Server.exe",
    )
    args = parser.parse_args()

    port = unused_port()
    command = [
        *args.server_command,
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
        "--mock",
    ]
    process = subprocess.Popen(
        command,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    base_url = f"http://127.0.0.1:{port}"
    control_headers = {
        "Content-Type": "application/json",
        "X-AssettoGPS-Control": "1",
    }

    try:
        status_code, status = wait_until_ready(base_url)
        if status_code != 200 or status.get("mode") != "mock":
            raise RuntimeError(f"Unexpected status response: {status_code} {status}")

        with urllib.request.urlopen(f"{base_url}/", timeout=2.0) as response:
            frontend = response.read().decode("utf-8")
        if response.status != 200 or "<html" not in frontend.lower():
            raise RuntimeError("Bundled frontend was not served")

        frame = asyncio.run(receive_telemetry_frame(port))
        if not frame.get("connected") or "carPosition" not in frame:
            raise RuntimeError(f"Unexpected WebSocket telemetry frame: {frame}")

        try:
            request_json(
                f"{base_url}/api/environment",
                method="POST",
                headers={"Content-Type": "application/json"},
                payload={"headlights": True},
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
        )
        if environment_code != 200:
            raise RuntimeError(f"Environment endpoint returned {environment_code}")

        shutdown_code, _ = request_json(
            f"{base_url}/api/shutdown",
            method="POST",
            headers=control_headers,
        )
        if shutdown_code != 200:
            raise RuntimeError(f"Shutdown endpoint returned {shutdown_code}")

        return_code = process.wait(timeout=10.0)
        if return_code != 0:
            raise RuntimeError(f"Server exited with code {return_code}")
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5.0)
            except subprocess.TimeoutExpired:
                process.kill()

    print("Packaged server smoke test passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
