# 🏁 Assetto Corsa Waze/GPS Minimap (Second-Screen Addon)

A **Waze / Apple CarPlay-style GPS Minimap & Telemetry Companion** for **Assetto Corsa**, designed specifically for **Shutoko Revival Project (SRP)** and circuit racing.

Runs as a lightweight background server on your PC and displays smoothly on any **secondary monitor, Android phone, iPhone, iPad, or tablet** mounted to your sim rig!

---

## ✨ Features

- 🏎️ **Optimized for Shutoko Revival Project (SRP) & Circuit Racing:**
  - **Calibrated Tokyo Expressway POIs & Landmarks:** Accurate pins for **Daikoku PA**, **Tatsumi PA**, **Shibaura PA**, **Yoyogi PA**, **Heiwajima PA (N/S)**, **Daishi PA**, **Oi PA**, **Rainbow Bridge**, **Yokohama Bay Bridge**, **Tsurumi Tsubasa Bridge**, **Minato Mirai Yokohama**, **Shibuya Crossing**, **Shinjuku**, **Tokyo Tower**, **Hakozaki JCT**, and **Ariake JCT**.
  - **Junction & Fork Guidance:** Upcoming exit and interchange cues.
  - **Waze Speed Trap & Camera Alerts:** Audio/visual warning chimes when approaching Tokyo expressway Orbis speed cameras.
  - **Speed-Adaptive Auto-Zoom:** Zooms out at 300+ km/h on the Wangan straight; zooms in close on technical C1 curves.
- 📐 **3D Perspective & Dual Orientation Modes:**
  - **3D Cockpit Perspective Tilt:** Deep 3D horizon tilt with atmospheric fog.
  - **2D Billboard HUD Labels:** Labels remain 100% upright, crisp, and facing the driver with zero perspective distortion.
  - **Heading-Up (Real GPS Mode):** Map smoothly rotates with your car heading (always driving upwards).
  - **North-Up (Overview Mode):** Fixed map with rotating car cursor.
  - **Dynamic Background GPS Grid:** Subtle coordinate grid squares that scale and tilt with the terrain.
- 🌗 **Day & Night Display Themes:**
  - **Midnight Dark Mode:** Obsidian background with glowing cyan telemetry.
  - **Apple Maps Day Mode:** Clean daylight terrain with high-contrast road layouts.
- 🚀 **Zero Game Impact:**
  - Reads Assetto Corsa Windows Shared Memory (`acpmf_physics`, `acpmf_graphics`, `acpmf_static`) in an isolated background thread.
  - **Zero CPU lag** or stuttering in AC.
- 📱 **Universal Cross-Platform Display:**
  - Works on any browser on your local Wi-Fi.
  - Responsive layout optimized for secondary monitors, phones, and landscape rig mounts.
  - **PWA & Wake Lock:** Fullscreen support without browser bars and keeps your mobile screen awake while driving.
- 🎮 **Offline Mock Simulator:**
  - Test and preview the GPS anytime without launching Assetto Corsa!

---

## 🚀 Quick Start (Powered by `uv`)

1. **Double-click `run.bat`:**
   - Automatically installs **`uv`** (if not already installed) in ~2 seconds.
   - `uv` automatically provisions the Python runtime and dependencies in milliseconds.
   - Starts the server and opens `http://localhost:8080` in your browser.
2. **Or run manually from terminal:**
   ```bash
   uv run backend/server.py
   ```
3. **Connect your Phone or Tablet:**
   - Point your phone camera at the **QR Code** in the terminal window, or type `http://<YOUR_PC_IP>:8080` into your phone's browser.
   - Tap **"Add to Home Screen"** on iOS/Android for a fullscreen native app experience!

---

## 🛠️ Project Structure

```
AssettoMiniMap/
├── pyproject.toml             # Modern uv package & dependency configuration
├── backend/
│   ├── server.py              # FastAPI + WebSocket server
│   ├── ac_shared_memory.py    # Windows Shared Memory struct reader
│   ├── ac_track_finder.py     # Automatic AC directory & map parser
│   ├── navigation.py          # Turn, POI, and speed camera detection
│   ├── mock_telemetry.py      # Simulated SRP driving generator
│   └── requirements.txt       # Python dependencies
├── frontend/
│   ├── index.html             # Responsive HTML5 Web App (PWA)
│   ├── manifest.json          # Mobile standalone manifest
│   ├── css/
│   │   ├── waze-theme.css     # Dark-mode Waze / CarPlay theme
│   │   └── style.css          # Responsive layout for mobile & 2nd monitor
│   └── js/
│       ├── app.js             # WebSocket manager & event coordinator
│       ├── map-renderer.js    # Canvas 2D 60fps rotating map engine
│       ├── navigation-ui.js   # Waze turn cards, speedo, trip info
│       ├── audio-alerts.js    # Synthesized Web Audio alert chimes
│       └── interpolation.js   # 60fps motion smoothing
└── run.bat                    # 1-Click Windows Launcher (uv-powered)
```
