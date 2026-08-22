/**
 * Main Application Coordinator & WebSocket Manager
 */

class App {
  constructor() {
    this.ws = null;
    this.reconnectTimer = null;
    this.wakeLock = null;

    this.renderer = new NavigationController("navigation-map");
    this.interpolator = window.motionInterpolator;
    this.ui = window.navUI;
    this.audio = window.audioAlerts;

    this.setupEventListeners();
    this.renderer.readyPromise
      .then(() => this.updateNavigationUi())
      .catch((error) => {
        console.error("Navigation Map failed to initialize", error);
        this.updateNavigationUi(error.message || String(error));
        this.showToast("Navigation Map could not start.");
      });
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
      this.updateConnectionStatus(true);
      this.updateServerOfflineNotice(false);
    };

    this.ws.onmessage = (event) => {
      try {
        const frame = JSON.parse(event.data);
        this.interpolator.setTarget(frame);
        this.ui.update(frame);

        if (frame.trackInfo) {
          const supportChanged = this.renderer.setTrackInfo(frame.trackInfo, frame.track);
          if (supportChanged) this.updateNavigationUi();
        }

        if (frame.environment) {
          this.renderer.updateEnvironment(frame.environment);
          this.updateAutoThemeCspNotice(frame.environment.available === true);
        }
      } catch (e) {
        console.error("Frame parse error", e);
      }
    };

    this.ws.onclose = () => {
      console.log("WebSocket disconnected, reconnecting in 2s...");
      this.updateConnectionStatus(false);
      this.updateServerOfflineNotice(true);
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = setTimeout(() => this.connectWebSocket(), 2000);
    };

    this.ws.onerror = () => {
      this.updateConnectionStatus(false);
      this.updateServerOfflineNotice(true);
      this.ws.close();
    };
  }

  updateConnectionStatus(connected, reconnecting = false) {
    const badge = document.getElementById("connection-status-badge");
    const text = document.getElementById("connection-status-text");
    if (!badge || !text) return;

    badge.className = "status-badge";
    if (connected) {
      badge.classList.add("status-connected");
      text.innerText = "Connected";
    } else if (reconnecting) {
      badge.classList.add("status-connecting");
      text.innerText = "Reconnecting...";
    } else {
      badge.classList.add("status-disconnected");
      text.innerText = "Server not running";
    }
  }

  updateServerOfflineNotice(visible) {
    const notice = document.getElementById("server-offline-notice");
    if (!notice) return;
    notice.classList.toggle("visible", visible);
    notice.setAttribute("aria-hidden", visible ? "false" : "true");
  }

  showToast(message) {
    const toast = document.getElementById("app-toast");
    if (!toast) return;
    toast.innerText = message;
    toast.classList.add("show");
    clearTimeout(this.toastTimer);
    this.toastTimer = setTimeout(() => {
      toast.classList.remove("show");
    }, 2400);
  }

  async loadServerStatus() {
    try {
      const res = await fetch("/api/status");
      if (res.ok) {
        const data = await res.json();
        const urlEl = document.getElementById("device-network-url");
        if (urlEl) {
          const port = window.location.port ? `:${window.location.port}` : "";
          const ip = data.localIp || window.location.hostname;
          urlEl.innerText = `http://${ip}${port}`;
        }
        this.updateAutoThemeCspNotice(data.cspConnected === true);
      }
    } catch (e) {
      const urlEl = document.getElementById("device-network-url");
      if (urlEl) {
        urlEl.innerText = window.location.origin;
      }
    }
  }

  updateAutoThemeCspNotice(cspLightAvailable) {
    this.cspLightAvailable = cspLightAvailable;
    const note = document.getElementById("auto-theme-csp-note");
    if (!note) return;
    note.hidden = cspLightAvailable;
  }

  updateSegmentedActive(containerId, attrName, activeValue) {
    const container = document.getElementById(containerId);
    if (!container) return;
    const buttons = container.querySelectorAll(".segmented-btn");
    buttons.forEach((btn) => {
      const isMatch = btn.getAttribute(attrName) === activeValue;
      btn.classList.toggle("active", isMatch);
      btn.setAttribute("aria-checked", isMatch ? "true" : "false");
    });
  }

  updateNavigationUi(error = null) {
    const capabilities = this.renderer.capabilities;
    if (this.ui && typeof this.ui.setMapCapabilities === "function") {
      this.ui.setMapCapabilities(capabilities);
    }
    if (capabilities.routing) {
      this.populateRouteDestinations();
      if (!capabilities.activeRoute) this.updateRouteUi();
    } else {
      const select = document.getElementById("navigation-destination");
      if (select) select.replaceChildren(new Option("Choose a destination...", ""));
      const startButton = document.getElementById("btn-start-route");
      if (startButton) startButton.disabled = true;
    }
    if (capabilities.unsupportedTrack) {
      this.updateRouteUi({ error: "Route guidance is available on SRP tracks only." });
    }
    if (error) this.updateRouteUi({ error: `Navigation Map could not start (${error}).` });
  }

  populateRouteDestinations() {
    const select = document.getElementById("navigation-destination");
    if (!select) return;
    const currentValue = select.value;
    const destinations = this.renderer.getDestinations();
    const existing = Array.from(select.options).slice(1).map((option) => option.value);
    if (existing.length !== destinations.length || existing.some((name, index) => name !== destinations[index])) {
      select.replaceChildren(new Option("Choose a destination...", ""));
      destinations.forEach((name) => select.add(new Option(name, name)));
      if (destinations.includes(currentValue)) select.value = currentValue;
    }
    const startButton = document.getElementById("btn-start-route");
    if (startButton) startButton.disabled = !select.value;
  }

  updateRouteUi(detail = {}) {
    const note = document.getElementById("navigation-route-note");
    const clearButton = document.getElementById("btn-clear-route");
    if (clearButton) clearButton.hidden = detail.active !== true;
    if (!note) return;
    if (detail.error) {
      note.innerText = detail.error;
      return;
    }
    if (detail.active) {
      const distance = detail.distanceM >= 1000
        ? `${(detail.distanceM / 1000).toFixed(1)} km`
        : `${Math.round(detail.distanceM)} m`;
      note.innerText = `Route to ${detail.destination} - ${distance}.`;
    } else {
      note.innerText = "Choose an SRP landmark for game-native directed routing.";
    }
  }

  setupEventListeners() {
    // Recenter the MapLibre camera after manual pan or rotation.
    const btnRecenter = document.getElementById("btn-recenter");
    if (btnRecenter) {
      btnRecenter.addEventListener("click", () => this.renderer.recenter());
    }

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
      const updateOrientationButton = (mode) => {
        btnOrientation.innerHTML = ORIENTATION_ICONS[mode] || ORIENTATION_ICONS.headingUp;
        const label = mode === "northUp" ? "Map orientation: North Up" : "Map orientation: Heading Up";
        btnOrientation.title = label;
        btnOrientation.setAttribute("aria-label", label);
        btnOrientation.classList.toggle("active", mode === "northUp");
      };
      updateOrientationButton(this.renderer.orientationMode);
      btnOrientation.addEventListener("click", () => {
        const mode = this.renderer.toggleOrientation();
        updateOrientationButton(mode);
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

    // Settings Modal / Bottom Sheet
    const btnSettings = document.getElementById("btn-settings");
    const modalSettings = document.getElementById("settings-modal");
    const btnCloseSettings = document.getElementById("close-settings");

    const openSettings = () => {
      if (!modalSettings) return;
      modalSettings.classList.add("open");
      this.loadServerStatus();
    };

    const closeSettings = () => {
      if (!modalSettings) return;
      modalSettings.classList.remove("open");
    };

    if (btnSettings) btnSettings.addEventListener("click", openSettings);
    if (btnCloseSettings) btnCloseSettings.addEventListener("click", closeSettings);

    if (modalSettings) {
      // Close on backdrop tap
      modalSettings.addEventListener("click", (e) => {
        if (e.target === modalSettings) {
          closeSettings();
        }
      });
    }

    // Close on Escape key
    window.addEventListener("keydown", (e) => {
      if (e.key === "Escape" && modalSettings && modalSettings.classList.contains("open")) {
        closeSettings();
      }
    });

    this.updateNavigationUi();
    window.addEventListener("gps-navigation-route-changed", (event) => {
      this.updateRouteUi(event.detail || {});
      if (this.ui && typeof this.ui.setMapCapabilities === "function") {
        this.ui.setMapCapabilities(this.renderer.capabilities);
      }
    });

    const destinationSelect = document.getElementById("navigation-destination");
    const startRouteButton = document.getElementById("btn-start-route");
    const clearRouteButton = document.getElementById("btn-clear-route");
    if (destinationSelect) {
      destinationSelect.addEventListener("change", () => {
        if (startRouteButton) startRouteButton.disabled = !destinationSelect.value;
      });
    }
    if (startRouteButton && destinationSelect) {
      startRouteButton.addEventListener("click", () => {
        const result = this.renderer.startRoute(destinationSelect.value);
        if (result.error) {
          this.updateRouteUi(result);
          this.showToast(result.error);
        } else {
          this.showToast(`Route to ${result.destination} started.`);
        }
      });
    }
    if (clearRouteButton) {
      clearRouteButton.addEventListener("click", () => {
        this.renderer.clearRoute();
        this.showToast("Route cleared.");
      });
    }

    // 1. Display Theme Segmented Control (Night / Day / Auto)
    const currentThemeMode = this.renderer.themeMode || "auto";
    this.updateSegmentedActive("control-theme", "data-theme", currentThemeMode);
    const themeButtons = document.querySelectorAll("#control-theme .segmented-btn");
    themeButtons.forEach((btn) => {
      btn.addEventListener("click", () => {
        const selectedTheme = btn.getAttribute("data-theme");
        this.renderer.setTheme(selectedTheme);
        this.updateSegmentedActive("control-theme", "data-theme", selectedTheme);
      });
    });

    // 2. Speed Units Segmented Control (KM/H / MPH)
    const currentUnit = this.ui.speedUnit || "kmh";
    this.updateSegmentedActive("control-units", "data-unit", currentUnit);
    const unitButtons = document.querySelectorAll("#control-units .segmented-btn");
    unitButtons.forEach((btn) => {
      btn.addEventListener("click", () => {
        const selectedUnit = btn.getAttribute("data-unit");
        this.ui.setUnit(selectedUnit);
        this.updateSegmentedActive("control-units", "data-unit", selectedUnit);
      });
    });

    // 3. Audio Alerts Toggle
    const toggleAudio = document.getElementById("toggle-audio-alerts");
    if (toggleAudio) {
      toggleAudio.checked = this.audio.enabled;
      toggleAudio.addEventListener("change", (e) => {
        this.audio.setSound(e.target.checked);
        if (e.target.checked) {
          this.audio.playPoiChime();
        }
      });
    }

    // 4. Dynamic Auto-Zoom Toggle
    const toggleAutoZoom = document.getElementById("toggle-auto-zoom");
    if (toggleAutoZoom) {
      toggleAutoZoom.checked = this.renderer.autoZoomEnabled;
      toggleAutoZoom.addEventListener("change", (e) => {
        this.renderer.setAutoZoom(e.target.checked);
      });
    }

    // 5. Reset Session Action Button
    const btnReset = document.getElementById("btn-reset-session");
    if (btnReset) {
      btnReset.addEventListener("click", async () => {
        try {
          btnReset.style.opacity = "0.6";
          const res = await fetch("/api/reset", { method: "POST" });
          if (res.ok) {
            this.showToast("Trip and navigation stats reset!");
          }
        } catch (e) {
          console.warn("Reset error", e);
        } finally {
          btnReset.style.opacity = "1";
        }
      });
    }

    // 6. Copy Pairing URL Button
    const btnCopyUrl = document.getElementById("btn-copy-url");
    if (btnCopyUrl) {
      btnCopyUrl.addEventListener("click", async () => {
        const urlText = document.getElementById("device-network-url")?.innerText;
        if (urlText && navigator.clipboard) {
          try {
            await navigator.clipboard.writeText(urlText);
            this.showToast("Pairing URL copied to clipboard!");
          } catch (e) {
            this.showToast("URL: " + urlText);
          }
        }
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
