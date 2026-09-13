# AssettoGPS

[![CI](https://github.com/SaharZo321/AssettoGPS/actions/workflows/ci.yml/badge.svg)](https://github.com/SaharZo321/AssettoGPS/actions/workflows/ci.yml)

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

    https://<your-PC-address>:8080

Phones use HTTPS on the selected server port. Allow that port through Windows
Firewall on your private network. The in-game companion uses HTTP on a separate
loopback-only control port (selected port + 1, or 65534 when selecting 65535).
That internal port is not a phone URL and requires no firewall rule or CSP TLS support.
The companion targets CSP 0.2.11 and newer; it does not use preview-only
certificate-bypass headers.
The app only displays a phone URL after the server responds. If HTTPS setup
fails, it reports HTTPS as unavailable while retaining local stop/status controls.

The connection is HTTPS with a self-signed, locally-generated certificate -
browsers only grant the Screen Wake Lock API (which keeps a paired phone's
screen from sleeping while navigating) on a secure connection, and plain HTTP
over a LAN address never qualifies. The first connection from a new
phone/browser shows a one-time "connection isn't private" warning - tap
**Advanced -> Proceed**; this is expected, since the certificate is
self-issued for this private server rather than from a public certificate
authority. It won't ask again on that device after the first time.

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
- Fully local MapLibre Game Navigation aligned to SRP's native coordinates
- Native SRP traffic-lane direction detection and directed landmark routing
- SRP points of interest, junction guidance, and speed-camera warnings
- Day/night display behavior and headlight synchronization
- Separate generated-telemetry development server for work without Assetto Corsa

## Development

Install [Node.js](https://nodejs.org/) 22.13 or newer and
[uv](https://docs.astral.sh/uv/), then enable the repository-pinned pnpm version,
install the locked frontend dependencies, and compile the TypeScript sources:

    corepack enable
    pnpm install --frozen-lockfile
    pnpm run build

The frontend build also copies the pinned MapLibre ESM, worker, CSS, and license
files from `node_modules` into ignored offline runtime directories.

Start the development server:

    uv run backend/dev_server.py

Then open http://127.0.0.1:8080.

To pair a phone or tablet against the development server, bind it to the
network instead of loopback-only:

    uv run backend/dev_server.py --host 0.0.0.0

This serves plain HTTP on `--port` (8080 by default) exactly as before, and
additionally serves HTTPS with a self-signed, locally-generated certificate on
`--port + 1` (8081 by default, override with `--https-port`). **Use the
`https://` URL printed in the startup banner for phone pairing, not the
`http://` one** - browsers only grant the Screen Wake Lock API (which keeps a
paired phone's screen from sleeping) on a secure context, and plain HTTP over
a LAN address never qualifies. The first connection from a new phone/browser
shows a one-time "connection isn't private" warning - tap **Advanced ->
Proceed**; this is expected, since the certificate is self-issued for this
private server and isn't from a public certificate authority. It won't ask
again on that device after the first time. Windows Firewall needs an inbound
allow rule for the HTTPS port too, same as the existing one for `--port`.

For frontend development, keep the compiler running in a second terminal:

    pnpm run watch:frontend

Run the tests:

    pnpm run check
    uv run --group test pytest
    uv run python scripts/verify_srp_routing.py

Build and test the drag-and-drop Content Manager ZIP on Windows:

    ./scripts/build_release.ps1

The output is build/AssettoGPS-\<version\>.zip, where \<version\> is the current
version from package.json (kept in sync across files by
scripts/bump_version.py). The build script is only for project maintainers;
players install the resulting ZIP directly through Content Manager.

## Verification notes

The release build performs:

- a clean, strict TypeScript frontend build;
- backend unit tests;
- SRP connector, connectivity, destination-reachability, and golden-route checks;
- a PyInstaller standalone Windows build;
- a real packaged-server startup in live-only mode without requiring AC;
- checks that generated telemetry, its CLI flag, API, and UI are absent;
- HTTP status and protected-control checks;
- graceful HTTP shutdown; and
- ZIP staging in the Content Manager directory layout.

Linux/Proton shared-memory access and CSP process launch cannot be confirmed
without a Linux test machine and are explicitly marked untested.

## Publishing checklist

- Complete the manual Windows in-game test.
- Obtain at least one Linux/Proton beta-tester report.
- Replace this beta version only after those checks are complete.

Licensed under the [MIT License](LICENSE).
