/**
 * Navigation UI & HUD Controller
 */

class NavigationUI {
  constructor() {
    this.speedUnit = "kmh"; // "kmh" or "mph"

    // DOM cache
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
  }

  setUnit(unit) {
    this.speedUnit = unit;
    if (this.speedUnitLabel) {
      this.speedUnitLabel.innerText = unit.toUpperCase();
    }
  }

  update(frame) {
    if (!frame) return;

    // 1. Update Speedometer & Gear
    const speed = this.speedUnit === "kmh" ? frame.speedKmh || 0 : frame.speedMph || 0;
    if (this.speedValue) {
      this.speedValue.innerText = Math.round(speed);
    }
    if (this.gearBadge) {
      this.gearBadge.innerText = frame.gear || "N";
    }

    // RPM Bar
    if (this.rpmBarFill) {
      const rpmPercent = Math.min(Math.max((frame.rpms / (frame.maxRpm || 8500)) * 100, 0), 100);
      this.rpmBarFill.style.width = `${rpmPercent}%`;
    }

    // 2. Navigation Banner
    const nav = frame.nav || {};
    const instruction = nav.instruction || {};

    let title = instruction.title || "Assetto Corsa GPS";
    let subtitle = instruction.subtitle || "Live Navigation Active";
    let icon = instruction.icon || "🏁";

    // Sanitize invalid or placeholder values
    if (subtitle === "0" || subtitle === "ks_0" || !subtitle || subtitle === "None") {
      const carName = (frame.carModel || "").replace("ks_", "").replace(/_/g, " ").trim();
      if (carName && carName !== "0" && carName !== "none") {
        subtitle = carName.toUpperCase();
      } else {
        subtitle = "Live Navigation Active";
      }
    }

    if (this.navTitle) this.navTitle.innerText = title;
    if (this.navSubtitle) this.navSubtitle.innerText = subtitle;
    if (this.navIcon) this.navIcon.innerText = icon;

    // 3. Trip Stats
    if (this.tripDist && nav.tripDistanceKm !== undefined) {
      const dist = this.speedUnit === "kmh" ? `${nav.tripDistanceKm} km` : `${(nav.tripDistanceKm * 0.621371).toFixed(2)} mi`;
      this.tripDist.innerText = dist;
    }

    if (this.tripTime && frame.currentTime) {
      this.tripTime.innerText = frame.currentTime;
    }

    if (this.topSpeed && nav.topSpeedKmh !== undefined) {
      const top = this.speedUnit === "kmh" ? `${Math.round(nav.topSpeedKmh)} km/h` : `${Math.round(nav.topSpeedKmh * 0.621371)} mph`;
      this.topSpeed.innerText = top;
    }

    if (this.fuelVal && frame.fuelPercent !== undefined) {
      this.fuelVal.innerText = `${Math.round(frame.fuelPercent)}%`;
    }
  }
}

window.navUI = new NavigationUI();
