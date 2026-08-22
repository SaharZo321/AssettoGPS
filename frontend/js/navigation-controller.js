/** Navigation-only facade for MapLibre rendering, themes, and route controls. */
class NavigationController {
  constructor(navigationContainerId) {
    this.navigation = new NavigationMapRenderer(navigationContainerId || "navigation-map");
    this.trackInfo = null;
    this.trackName = "";
    this.environment = null;
    this.themeMode = localStorage.getItem("gps_theme_mode") || "auto";
    this.theme = "dark";
    this.navigation.setActive(true);
    this.setTheme(this.themeMode);
    this.readyPromise = this.initialize();
  }

  async initialize() {
    await this.navigation.readyPromise;
    this.navigation.setTrackInfo(this.trackInfo, this.trackName);
    this.navigation.setTheme(this.theme);
    return this;
  }

  get capabilities() { return this.navigation.capabilities; }
  get autoZoomEnabled() { return this.navigation.autoZoomEnabled; }
  get orientationMode() { return this.navigation.orientationMode; }
  get is3D() { return this.navigation.is3D; }

  setTrackInfo(info, trackName) {
    this.trackInfo = info || this.trackInfo;
    this.trackName = trackName || this.trackName;
    return this.navigation.setTrackInfo(this.trackInfo, this.trackName);
  }

  setTheme(themeMode) {
    this.themeMode = ["dark", "light", "auto"].includes(themeMode) ? themeMode : "auto";
    localStorage.setItem("gps_theme_mode", this.themeMode);
    if (this.themeMode === "auto") this.evaluateAutoTheme(this.environment);
    else this.applyTheme(this.themeMode);
  }

  applyTheme(activeTheme) {
    const nextTheme = activeTheme === "light" ? "light" : "dark";
    if (this.theme === nextTheme
      && document.documentElement.getAttribute("data-theme") === nextTheme) return;
    this.theme = nextTheme;
    document.documentElement.setAttribute("data-theme", this.theme);
    this.navigation.setTheme(this.theme);
  }

  evaluateAutoTheme(environment) {
    if (this.themeMode !== "auto") return;
    const hasCspLight = environment
      && (environment.available === true
        || (environment.available === undefined && environment.source === "csp"));
    if (hasCspLight && typeof environment.isDark === "boolean") {
      this.applyTheme(environment.isDark ? "dark" : "light");
      return;
    }
    if (hasCspLight && typeof environment.isNight === "boolean") {
      this.applyTheme(environment.isNight ? "dark" : "light");
      return;
    }
    const prefersDark = typeof window.matchMedia === "function"
      && window.matchMedia("(prefers-color-scheme: dark)").matches;
    this.applyTheme(prefersDark ? "dark" : "light");
  }

  updateEnvironment(environment) {
    this.environment = environment;
    if (this.themeMode === "auto") this.evaluateAutoTheme(environment);
  }

  toggleOrientation() { return this.navigation.toggleOrientation(); }
  toggleTilt() { return this.navigation.toggleTilt(); }
  setAutoZoom(enabled) { return this.navigation.setAutoZoom(enabled); }
  getDestinations() { return this.navigation.getDestinations(); }
  startRoute(destinationName) { return this.navigation.setDestination(destinationName); }
  clearRoute() { return this.navigation.clearDestination(); }
  recenter() { this.navigation.recenter(); }
  render(interpolator) { this.navigation.render(interpolator); }
}

window.NavigationController = NavigationController;
