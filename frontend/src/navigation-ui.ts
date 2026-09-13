/** Navigation UI and HUD controller. */

interface NavigationUICapabilities {
  routing: boolean;
  activeRoute: boolean;
  mapMatching: boolean;
  directionDetection: boolean;
}

const NAVIGATION_ICON_PATHS: Readonly<Record<NavigationIconName, string>> = {
  bridge: '<path d="M3 18h18M5 18v-5m14 5v-5M4 13h16M7 13a5 5 0 0 1 10 0"/>',
  city: '<path d="M3 21V9h7v12M10 21V3h11v18M6 12h1m-1 4h1m7-9h1m3 0h1m-5 4h1m3 0h1m-5 4h1m3 0h1"/>',
  finish: '<path d="M5 21V4m0 1c4-3 7 3 14 0v9c-7 3-10-3-14 0"/><path d="M9 5v4m4-2v4m4-5v4M7 10h4m4 0h4"/>',
  junction: '<path d="M6 21V7m0 7c0-4 4-5 7-5h6m-3-3 3 3-3 3M6 12c0 4 4 5 7 5h6m-3-3 3 3-3 3"/>',
  landmark: '<path d="M12 21s6-5.3 6-11a6 6 0 1 0-12 0c0 5.7 6 11 6 11Z"/><circle cx="12" cy="10" r="2"/>',
  parking: '<rect x="4" y="3" width="16" height="18" rx="3"/><path d="M9 17V7h4a3 3 0 0 1 0 6H9"/>',
  pin: '<path d="M12 21s6-5.3 6-11a6 6 0 1 0-12 0c0 5.7 6 11 6 11Z"/><circle cx="12" cy="10" r="2"/>',
  road: '<path d="M5 21 9 3m10 18L15 3M12 5v3m0 4v3m0 4v2"/>',
  tunnel: '<path d="M4 21V11a8 8 0 0 1 16 0v10M8 21V11a4 4 0 0 1 8 0v10M2 21h20"/>',
};

class NavigationUI {
  public speedUnit: SpeedUnit;
  private mapCapabilities: NavigationUICapabilities = {
    routing: false,
    activeRoute: false,
    mapMatching: false,
    directionDetection: false,
  };

  private readonly navBanner: HTMLElement | null;
  private readonly navTitle: HTMLElement | null;
  private readonly navSubtitle: HTMLElement | null;
  private readonly navIcon: HTMLElement | null;
  private readonly speedValue: HTMLElement | null;
  private readonly speedUnitLabel: HTMLElement | null;
  private readonly gearBadge: HTMLElement | null;
  private readonly rpmBarFill: HTMLElement | null;
  private readonly tripDist: HTMLElement | null;
  private readonly tripTime: HTMLElement | null;
  private readonly topSpeed: HTMLElement | null;
  private readonly fuelVal: HTMLElement | null;

  constructor() {
    this.speedUnit = localStorage.getItem("gps_speed_unit") === "mph" ? "mph" : "kmh";

    this.navBanner = document.getElementById("nav-banner");
    this.navTitle = document.getElementById("nav-title");
    this.navSubtitle = document.getElementById("nav-subtitle");
    this.navIcon = document.getElementById("nav-icon-container");
    this.renderNavigationIcon("finish");
    this.speedValue = document.getElementById("speed-value");
    this.speedUnitLabel = document.getElementById("speed-unit");
    this.gearBadge = document.getElementById("gear-badge");
    this.rpmBarFill = document.getElementById("rpm-bar-fill");
    this.tripDist = document.getElementById("trip-dist");
    this.tripTime = document.getElementById("trip-time");
    this.topSpeed = document.getElementById("top-speed");
    this.fuelVal = document.getElementById("fuel-val");

    if (this.speedUnitLabel) {
      this.speedUnitLabel.innerText = this.speedUnit.toUpperCase();
    }
  }

  private renderNavigationIcon(iconName: NavigationIconName): void {
    if (!this.navIcon) return;
    const paths = NAVIGATION_ICON_PATHS[iconName] || NAVIGATION_ICON_PATHS.finish;
    this.navIcon.innerHTML = `<svg class="nav-banner-svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${paths}</svg>`;
  }

  setUnit(unit: string | null): void {
    this.speedUnit = unit === "mph" ? "mph" : "kmh";
    localStorage.setItem("gps_speed_unit", this.speedUnit);
    if (this.speedUnitLabel) {
      this.speedUnitLabel.innerText = this.speedUnit.toUpperCase();
    }
  }

  setMapCapabilities(capabilities: Partial<MapCapabilities> = {}): void {
    this.mapCapabilities = {
      routing: capabilities.routing === true,
      activeRoute: capabilities.activeRoute === true,
      mapMatching: capabilities.mapMatching === true,
      directionDetection: capabilities.directionDetection === true,
    };
  }

  update(frame: TelemetryFrame | null | undefined): void {
    if (!frame) return;

    const speed = this.speedUnit === "kmh" ? frame.speedKmh || 0 : frame.speedMph || 0;
    if (this.speedValue) this.speedValue.innerText = String(Math.round(speed));
    if (this.gearBadge) this.gearBadge.innerText = String(frame.gear || "N");

    if (this.rpmBarFill) {
      const rpmPercent = Math.min(
        Math.max(((frame.rpms || 0) / (frame.maxRpm || 8500)) * 100, 0),
        100,
      );
      this.rpmBarFill.style.width = `${rpmPercent}%`;
    }

    const navigation = frame.nav || {};
    const instruction = navigation.instruction || {};
    const title = instruction.title || "Assetto Corsa GPS";
    let subtitle = instruction.subtitle || "Live Navigation Active";
    const icon = instruction.icon || "finish";

    if (subtitle === "0" || subtitle === "ks_0" || !subtitle || subtitle === "None") {
      const carName = (frame.carModel || "").replace("ks_", "").replace(/_/g, " ").trim();
      if (carName && carName !== "0" && carName !== "none") {
        subtitle = carName.toUpperCase();
      } else {
        subtitle = "Live Navigation Active";
      }
    }

    if ((instruction.alertLevel || "normal") === "normal") {
      if (this.mapCapabilities.activeRoute) {
        subtitle = "Game-lane route active";
      } else if (this.mapCapabilities.routing) {
        subtitle = "Game-aligned lanes - choose a destination";
      } else {
        subtitle = "Game-aligned lanes - routing unavailable";
      }
    }

    if (this.navTitle) this.navTitle.innerText = title;
    if (this.navSubtitle) this.navSubtitle.innerText = subtitle;
    this.renderNavigationIcon(icon);

    if (this.tripDist && navigation.tripDistanceKm !== undefined) {
      const distance = this.speedUnit === "kmh"
        ? `${navigation.tripDistanceKm} km`
        : `${(navigation.tripDistanceKm * 0.621371).toFixed(2)} mi`;
      this.tripDist.innerText = distance;
    }

    if (this.tripTime && frame.currentTime) this.tripTime.innerText = frame.currentTime;

    if (this.topSpeed && navigation.topSpeedKmh !== undefined) {
      const topSpeed = this.speedUnit === "kmh"
        ? `${Math.round(navigation.topSpeedKmh)} km/h`
        : `${Math.round(navigation.topSpeedKmh * 0.621371)} mph`;
      this.topSpeed.innerText = topSpeed;
    }

    if (this.fuelVal && frame.fuelPercent !== undefined) {
      this.fuelVal.innerText = `${Math.round(frame.fuelPercent)}%`;
    }
  }
}

window.navUI = new NavigationUI();
