/** Shared facade for the exact SVG map and the optional Navigation Map. */
class MapModeController {
  constructor(canvasId, navigationContainerId) {
    this.navigationContainerId = navigationContainerId;
    this.simple = new MapRenderer(canvasId);
    this.navigation = null;
    this.mapMode = "simple";
    this.requestedMapMode = localStorage.getItem("gps_map_mode") === "navigation" ? "navigation" : "simple";
    this.trackInfo = null;
    this.trackName = "";
    this.environment = null;
    this.activate("simple");
    if (this.requestedMapMode === "navigation") {
      this.setMapMode("navigation", { silent: true });
    }
  }

  get activeRenderer() {
    return this.mapMode === "navigation" && this.navigation ? this.navigation : this.simple;
  }

  get capabilities() {
    return this.mapMode === "navigation" && this.navigation
      ? this.navigation.capabilities
      : { vectorMap: true, offline: true, mapMatching: false, directionDetection: false, routing: false };
  }

  get themeMode() { return this.simple.themeMode; }
  get theme() { return this.simple.theme; }
  get autoZoomEnabled() { return this.activeRenderer.autoZoomEnabled; }
  get orientationMode() { return this.activeRenderer.orientationMode; }
  get is3D() { return this.activeRenderer.is3D; }

  dispatchChange(error = null) {
    window.dispatchEvent(new CustomEvent("gps-map-mode-changed", {
      detail: { mode: this.mapMode, requestedMode: this.requestedMapMode, capabilities: this.capabilities, error },
    }));
  }

  activate(mode) {
    this.mapMode = mode === "navigation" ? "navigation" : "simple";
    const container = document.getElementById("app-container");
    if (container) container.setAttribute("data-map-mode", this.mapMode);
    if (this.navigation) this.navigation.setActive(this.mapMode === "navigation");
    if (this.mapMode === "simple") {
      this.simple.resize();
      this.simple.setTiltAngle(this.simple.tiltAngle, false);
      this.simple.updateRecenterButton(this.simple.isFreeBrowsing);
    }
  }

  async setMapMode(mode, options = {}) {
    const requested = mode === "navigation" ? "navigation" : "simple";
    this.requestedMapMode = requested;
    if (requested === "simple") {
      localStorage.setItem("gps_map_mode", "simple");
      this.activate("simple");
      this.dispatchChange();
      return { mode: this.mapMode, capabilities: this.capabilities };
    }

    try {
      if (!this.navigation) {
        this.navigation = new NavigationMapRenderer(this.navigationContainerId || "navigation-map");
      }
      await this.navigation.readyPromise;
      this.navigation.setTrackInfo(this.trackInfo, this.trackName);
      this.navigation.setTheme(this.simple.theme);
      this.navigation.orientationMode = this.simple.orientationMode;
      this.navigation.setAutoZoom(this.simple.autoZoomEnabled);
      this.navigation.setTiltAngle(this.simple.tiltAngle);
      localStorage.setItem("gps_map_mode", "navigation");
      this.activate("navigation");
      this.dispatchChange();
      return { mode: this.mapMode, capabilities: this.capabilities };
    } catch (error) {
      console.warn("Navigation Map unavailable; returning to Simple Map", error);
      localStorage.setItem("gps_map_mode", "simple");
      this.requestedMapMode = "simple";
      this.activate("simple");
      if (!options.silent) this.dispatchChange(error.message || String(error));
      else this.dispatchChange(error.message || String(error));
      return { mode: "simple", capabilities: this.capabilities, error: error.message || String(error) };
    }
  }

  setTrackInfo(info, trackName) {
    this.trackInfo = info || this.trackInfo;
    this.trackName = trackName || this.trackName;
    this.simple.setTrackInfo(info, trackName);
    if (this.navigation) this.navigation.setTrackInfo(info, trackName);
  }

  setTheme(themeMode) {
    this.simple.setTheme(themeMode);
    if (this.navigation) this.navigation.setTheme(this.simple.theme);
  }

  updateEnvironment(environment) {
    this.environment = environment;
    this.simple.updateEnvironment(environment);
    if (this.navigation) this.navigation.setTheme(this.simple.theme);
  }

  toggleOrientation() {
    const mode = this.activeRenderer.toggleOrientation();
    this.simple.orientationMode = mode;
    if (this.navigation) this.navigation.orientationMode = mode;
    return mode;
  }

  toggleTilt() {
    const is3D = this.activeRenderer.toggleTilt();
    const angle = this.activeRenderer.tiltAngle;
    if (this.activeRenderer !== this.simple) this.simple.setTiltAngle(angle, true);
    if (this.navigation && this.activeRenderer !== this.navigation) this.navigation.setTiltAngle(angle);
    return is3D;
  }

  setAutoZoom(enabled) {
    this.simple.setAutoZoom(enabled);
    if (this.navigation) this.navigation.setAutoZoom(enabled);
    return !!enabled;
  }

  recenter() { this.activeRenderer.recenter(); }

  render(interpolator) { this.activeRenderer.render(interpolator); }
}

window.MapModeController = MapModeController;
