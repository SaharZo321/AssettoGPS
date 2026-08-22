/** Navigation-only facade for MapLibre rendering, themes, and route controls. */
class NavigationController {
  private readonly navigation: NavigationMapRenderer;
  private trackInfo: TrackInfo | null;
  private trackName: string;
  private environment: EnvironmentInfo | null;
  themeMode: string;
  private theme: ActiveTheme;
  readonly readyPromise: Promise<this>;

  constructor(navigationContainerId: string) {
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

  async initialize(): Promise<this> {
    await this.navigation.readyPromise;
    this.navigation.setTrackInfo(this.trackInfo, this.trackName);
    this.navigation.setTheme(this.theme);
    return this;
  }

  get capabilities(): MapCapabilities { return this.navigation.capabilities; }
  get autoZoomEnabled(): boolean { return this.navigation.autoZoomEnabled; }
  get orientationMode(): OrientationMode { return this.navigation.orientationMode; }
  get is3D(): boolean { return this.navigation.is3D; }

  setTrackInfo(info: TrackInfo | null | undefined, trackName: string | null | undefined): boolean {
    this.trackInfo = info || this.trackInfo;
    this.trackName = trackName || this.trackName;
    return this.navigation.setTrackInfo(this.trackInfo, this.trackName);
  }

  setTheme(themeMode: string): void {
    this.themeMode = ["dark", "light", "auto"].includes(themeMode) ? themeMode : "auto";
    localStorage.setItem("gps_theme_mode", this.themeMode);
    if (this.themeMode === "auto") this.evaluateAutoTheme(this.environment);
    else this.applyTheme(this.themeMode);
  }

  applyTheme(activeTheme: string): void {
    const nextTheme = activeTheme === "light" ? "light" : "dark";
    if (this.theme === nextTheme
      && document.documentElement.getAttribute("data-theme") === nextTheme) return;
    this.theme = nextTheme;
    document.documentElement.setAttribute("data-theme", this.theme);
    this.navigation.setTheme(this.theme);
  }

  evaluateAutoTheme(environment: EnvironmentInfo | null): void {
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

  updateEnvironment(environment: EnvironmentInfo): void {
    this.environment = environment;
    if (this.themeMode === "auto") this.evaluateAutoTheme(environment);
  }

  toggleOrientation(): OrientationMode { return this.navigation.toggleOrientation(); }
  toggleTilt(): boolean { return this.navigation.toggleTilt(); }
  setAutoZoom(enabled: boolean): boolean { return this.navigation.setAutoZoom(enabled); }
  getDestinations(): string[] { return this.navigation.getDestinations(); }
  startRoute(destinationName: string): RouteChangeDetail {
    return this.navigation.setDestination(destinationName);
  }
  clearRoute(): RouteChangeDetail { return this.navigation.clearDestination(); }
  recenter(): void { this.navigation.recenter(); }
  render(interpolator: MotionInterpolator): void { this.navigation.render(interpolator); }
}

window.NavigationController = NavigationController;
