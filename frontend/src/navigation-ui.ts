/** Navigation UI and HUD controller. */

interface NavigationUICapabilities {
  routing: boolean;
  activeRoute: boolean;
  mapMatching: boolean;
  directionDetection: boolean;
}

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
    const icon = instruction.icon || "\u{1F3C1}";

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
    if (this.navIcon) this.navIcon.innerText = icon;

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
