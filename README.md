# AssettoGPS

AssettoGPS is a second-screen GPS, minimap, and telemetry app for Assetto Corsa.
It is designed for phones, tablets, and secondary monitors, with additional
navigation data for Shutoko Revival Project.

> Beta status: the packaged Windows server has automated tests and has been
> launched successfully on Windows. The final in-game CSP launch still needs a
> manual Assetto Corsa test. Linux/Proton support is experimental and has not
> been tested on a Linux machine.

## Install with Content Manager

1. Download the release ZIP. Do not extract it.
2. Drag the ZIP file onto Content Manager.
3. Click **Install** in Content Manager.
4. Make sure Custom Shaders Patch is enabled.
5. Start Assetto Corsa and open **Assetto GPS** from the in-game app sidebar.

That is the complete user installation. Python, uv, VBS scripts, batch files,
and a separate server installation are not required. The ZIP contains this
Content Manager layout:

    apps/
      lua/
        AssettoGPS/
          AssettoGPS.lua
          icon.png
          manifest.ini
          server/
            AssettoGPS.Server.exe

The Lua app uses CSP's process API to launch the bundled server. The server
closes gracefully when requested from the app and is also tied to the Assetto
Corsa process.

## Use

Open the Assetto GPS app in-game and wait for its status to show **ONLINE**.
Open the displayed URL on another device connected to the same local network.
The default address is:

    http://<your-PC-address>:8080

Auto theme uses CSP's live ambient-light and track-occlusion data, so it reacts
to daylight, night, and genuinely dark covered areas without relying on the
car's height or manual headlight switch. If the CSP feed is unavailable, the
settings menu shows the requirement and the display falls back to the device's
color preference.

To use a different port, stop the server from the in-game app, enter a port
from 1024 to 65535, press **Apply**, and start the server again. CSP saves the
selected port for future Assetto Corsa sessions. The setting is disabled while
the server is starting or online.

Windows Firewall might ask whether to allow the server on private networks.
Private-network access is required for a phone or tablet to connect. Do not
allow it on public networks.

## Platform support

### Windows

- Intended and built for the Windows version of Assetto Corsa.
- The standalone release executable and its HTTP lifecycle are tested
  automatically on Windows.
- An in-game launch test is still required before the first public release.

### Linux with Proton or Wine

Assetto Corsa does not have a native Linux release. Linux support therefore
means running the Windows game and this Windows server through Proton/Wine. The
bundled EXE is intentional: launching it in the same compatibility environment
as Assetto Corsa allows it to access AC's Win32 named shared-memory pages.

This path is **beta and currently untested**. It is not a claim of native Linux
support. The CSP launcher is expected to start the bundled EXE automatically.
If that does not work, an experimental manual fallback is:

    protontricks-launch --appid 244210 "/path/to/steamapps/common/assettocorsa/apps/lua/AssettoGPS/server/AssettoGPS.Server.exe"

Please include the Proton version, CSP version, distribution, and server output
when reporting a Linux issue.

Relevant upstream documentation:

- [Valve Proton](https://github.com/ValveSoftware/Proton)
- [Protontricks launcher usage](https://github.com/Matoking/protontricks#usage)
- [Custom Shaders Patch Lua SDK](https://github.com/ac-custom-shaders-patch/acc-lua-sdk)

## Features

- Real-time AC shared-memory telemetry over WebSockets
- Browser UI for phones, tablets, and secondary displays
- Heading-up and north-up map modes
- Selectable exact Simple SVG Map or fully local MapLibre Navigation Map
- Offline OSM carriageway direction detection and directed landmark routing for SRP
- SRP points of interest, junction guidance, and speed-camera warnings
- Day/night display behavior and headlight synchronization
- Mock telemetry mode for development without launching Assetto Corsa

## Development

Install [uv](https://docs.astral.sh/uv/) and run:

    uv run backend/server.py --mock

Then open http://127.0.0.1:8080.

Run the tests:

    uv run python -m unittest discover -s tests -v

Build and test the drag-and-drop Content Manager ZIP on Windows:

    ./scripts/build_release.ps1

The output is build/AssettoGPS-0.2.0-beta.9.zip. The build script is only for
project maintainers; players install the resulting ZIP directly through Content
Manager.

## Verification notes

The release build performs:

- backend unit tests;
- a PyInstaller standalone Windows build;
- a real packaged-server startup in mock mode;
- HTTP status and protected-control checks;
- graceful HTTP shutdown; and
- ZIP staging in the Content Manager directory layout.

Linux/Proton shared-memory access and CSP process launch cannot be confirmed
without a Linux test machine and are explicitly marked untested.

## Publishing checklist

- Complete the manual Windows in-game test.
- Obtain at least one Linux/Proton beta-tester report.
- Select the public author name and an open-source or redistribution license.
- Replace this beta version only after those checks are complete.

No redistribution license has been selected yet. Add a LICENSE file before
publishing the project publicly.
