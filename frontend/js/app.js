/**
 * Main Application Coordinator & WebSocket Manager
 */

class App {
  constructor() {
    this.ws = null;
    this.reconnectTimer = null;
    this.wakeLock = null;

    this.renderer = new MapRenderer("map-canvas");
    this.interpolator = window.motionInterpolator;
    this.ui = window.navUI;
    this.audio = window.audioAlerts;

    this.setupEventListeners();
    this.requestWakeLock();
    this.connectWebSocket();
    this.startLoop();
  }

  async requestWakeLock() {
    try {
      if ("wakeLock" in navigator) {
        this.wakeLock = await navigator.wakeLock.request("screen");
        document.addEventListener("visibilitychange", async () => {
          if (this.wakeLock !== null && document.visibilityState === "visible") {
            this.wakeLock = await navigator.wakeLock.request("screen");
          }
        });
      }
    } catch (e) {
      console.warn("WakeLock error", e);
    }
  }

  connectWebSocket() {
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    const wsUrl = `${protocol}//${window.location.host}/ws/telemetry`;

    this.ws = new WebSocket(wsUrl);

    this.ws.onopen = () => {
      console.log("Connected to Assetto Corsa GPS Server");
    };

    this.ws.onmessage = (event) => {
      try {
        const frame = JSON.parse(event.data);
        this.interpolator.setTarget(frame);
        this.ui.update(frame);

        if (frame.trackInfo) {
          this.renderer.setTrackInfo(frame.trackInfo, frame.track);
        }
      } catch (e) {
        console.error("Frame parse error", e);
      }
    };

    this.ws.onclose = () => {
      console.log("WebSocket disconnected, reconnecting in 2s...");
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = setTimeout(() => this.connectWebSocket(), 2000);
    };

    this.ws.onerror = () => {
      this.ws.close();
    };
  }

  setupEventListeners() {
    // Orientation button (Heading-up vs North-up) with clean SVGs
    const btnOrientation = document.getElementById("btn-orientation");
    const ORIENTATION_ICONS = {
      headingUp: `
        <svg class="ctrl-svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
          <polygon points="12 3 19 20 12 16.5 5 20 12 3" fill="currentColor" stroke="none" />
        </svg>`,
      northUp: `
        <svg class="ctrl-svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">
          <circle cx="12" cy="12" r="9" stroke="currentColor" stroke-width="1.6" />
          <polygon points="12 4.5 15 12 12 10.5 9 12 12 4.5" fill="#ef4444" stroke="none" />
          <polygon points="12 19.5 9 12 12 13.5 15 12 12 19.5" fill="rgba(255,255,255,0.4)" stroke="none" />
        </svg>`,
    };

    if (btnOrientation) {
      btnOrientation.innerHTML = ORIENTATION_ICONS[this.renderer.orientationMode] || ORIENTATION_ICONS.headingUp;
      btnOrientation.addEventListener("click", () => {
        const mode = this.renderer.toggleOrientation();
        btnOrientation.innerHTML = ORIENTATION_ICONS[mode];
      });
    }

    // 3D Perspective Tilt Toggle button
    const btnTilt = document.getElementById("btn-tilt");
    if (btnTilt) {
      btnTilt.innerText = this.renderer.is3D ? "3D" : "2D";
      btnTilt.classList.toggle("active", this.renderer.is3D);
      btnTilt.addEventListener("click", () => {
        const is3D = this.renderer.toggleTilt();
        btnTilt.innerText = is3D ? "3D" : "2D";
        btnTilt.classList.toggle("active", is3D);
      });
    }





    // Fullscreen button
    const btnFullscreen = document.getElementById("btn-fullscreen");
    if (btnFullscreen) {
      btnFullscreen.addEventListener("click", () => {
        if (!document.fullscreenElement) {
          document.documentElement.requestFullscreen().catch(() => {});
        } else {
          document.exitFullscreen().catch(() => {});
        }
      });
    }

    // Settings Modal
    const btnSettings = document.getElementById("btn-settings");
    const modalSettings = document.getElementById("settings-modal");
    const btnCloseSettings = document.getElementById("close-settings");

    if (btnSettings && modalSettings) {
      btnSettings.addEventListener("click", () => {
        modalSettings.style.display = "flex";
      });
    }
    if (btnCloseSettings && modalSettings) {
      btnCloseSettings.addEventListener("click", () => {
        modalSettings.style.display = "none";
      });
    }

    // Display Theme Selector (Dark / Light)
    const themeSelect = document.getElementById("setting-theme");
    if (themeSelect) {
      themeSelect.value = this.renderer.theme || "dark";
      themeSelect.addEventListener("change", (e) => {
        this.renderer.setTheme(e.target.value);
      });
    }

    // Unit Selector (kmh / mph)
    const unitSelect = document.getElementById("setting-units");
    if (unitSelect) {
      unitSelect.addEventListener("change", (e) => {
        this.ui.setUnit(e.target.value);
      });
    }

    // Mode Selector (auto / live / mock)
    const modeSelect = document.getElementById("setting-mode");
    if (modeSelect) {
      modeSelect.addEventListener("change", (e) => {
        fetch("/api/mode", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ mode: e.target.value }),
        }).catch(() => {});
      });
    }

    // Unlock Audio on first user interaction
    window.addEventListener("pointerdown", () => this.audio.unlock(), { once: true });
  }

  startLoop() {
    const loop = () => {
      this.interpolator.update();
      this.renderer.render(this.interpolator);
      requestAnimationFrame(loop);
    };
    requestAnimationFrame(loop);
  }
}

window.addEventListener("DOMContentLoaded", () => {
  window.app = new App();
});
