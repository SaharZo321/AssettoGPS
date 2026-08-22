/**
 * Offline MapLibre renderer for SRP.
 *
 * MapLibre renders the OSM extract.  Assetto Corsa coordinates are locally
 * calibrated and then snapped to OSM's directed motorway ways.  This keeps
 * the SDK/rendering concern separate from future route calculation.
 */

class SrpCoordinateCalibration {
  constructor(config) {
    this.longitude = config.affine.longitude;
    this.latitude = config.affine.latitude;
    this.anchors = config.anchors || [];
  }

  affinePoint(x, z) {
    return [
      this.longitude[0] * x + this.longitude[1] * z + this.longitude[2],
      this.latitude[0] * x + this.latitude[1] * z + this.latitude[2],
    ];
  }

  toLngLat(x, z) {
    const base = this.affinePoint(x, z);
    if (!this.anchors.length) return base;

    let longitudeCorrection = 0;
    let latitudeCorrection = 0;
    let totalWeight = 0;
    for (const anchor of this.anchors) {
      const dx = x - anchor.ac[0];
      const dz = z - anchor.ac[1];
      const distanceSquared = dx * dx + dz * dz;
      if (distanceSquared < 1e-6) return [...anchor.osm];

      // Shepard interpolation makes the correction converge continuously on
      // each authoritative control instead of creating a seam around it.
      const weight = 1 / Math.max(distanceSquared, 1);
      longitudeCorrection += anchor.residual[0] * weight;
      latitudeCorrection += anchor.residual[1] * weight;
      totalWeight += weight;
    }
    return [
      base[0] + longitudeCorrection / totalWeight,
      base[1] + latitudeCorrection / totalWeight,
    ];
  }

  headingToBearing(x, z, headingRadians) {
    // Local landmark correction is positional; differentiating it can rotate
    // a heading sharply near an anchor. The global affine basis preserves the
    // game's forward vector and guarantees that h + PI is the opposite road
    // bearing.
    const origin = this.affinePoint(x, z);
    const ahead = this.affinePoint(
      x + Math.sin(headingRadians) * 25,
      z + Math.cos(headingRadians) * 25
    );
    return DirectedRoadMatcher.bearing(origin, ahead);
  }
}

class DirectedRoadMatcher {
  constructor(featureCollection) {
    this.cellSize = 0.004;
    this.cells = new Map();
    this.previousWayId = null;
    this.previousPoint = null;
    this.buildIndex(featureCollection);
  }

  static normalizeAngle(angle) {
    let value = angle % 360;
    if (value > 180) value -= 360;
    if (value < -180) value += 360;
    return value;
  }

  static bearing(from, to) {
    const averageLatitude = ((from[1] + to[1]) * Math.PI) / 360;
    const east = (to[0] - from[0]) * Math.cos(averageLatitude);
    const north = to[1] - from[1];
    return (Math.atan2(east, north) * 180) / Math.PI;
  }

  cellKey(x, y) {
    return `${x}:${y}`;
  }

  buildIndex(featureCollection) {
    for (const feature of featureCollection.features || []) {
      const coordinates = feature.geometry?.coordinates || [];
      for (let index = 0; index < coordinates.length - 1; index += 1) {
        const segment = {
          from: coordinates[index],
          to: coordinates[index + 1],
          wayId: feature.properties.osm_id,
          properties: feature.properties,
        };
        const minX = Math.floor(Math.min(segment.from[0], segment.to[0]) / this.cellSize);
        const maxX = Math.floor(Math.max(segment.from[0], segment.to[0]) / this.cellSize);
        const minY = Math.floor(Math.min(segment.from[1], segment.to[1]) / this.cellSize);
        const maxY = Math.floor(Math.max(segment.from[1], segment.to[1]) / this.cellSize);
        for (let x = minX; x <= maxX; x += 1) {
          for (let y = minY; y <= maxY; y += 1) {
            const key = this.cellKey(x, y);
            if (!this.cells.has(key)) this.cells.set(key, []);
            this.cells.get(key).push(segment);
          }
        }
      }
    }
  }

  project(point, segment) {
    const latitudeRadians = (point[1] * Math.PI) / 180;
    const longitudeScale = 111320 * Math.cos(latitudeRadians);
    const latitudeScale = 111320;
    const ax = (segment.from[0] - point[0]) * longitudeScale;
    const ay = (segment.from[1] - point[1]) * latitudeScale;
    const bx = (segment.to[0] - point[0]) * longitudeScale;
    const by = (segment.to[1] - point[1]) * latitudeScale;
    const dx = bx - ax;
    const dy = by - ay;
    const lengthSquared = dx * dx + dy * dy;
    const amount = lengthSquared ? Math.max(0, Math.min(1, -(ax * dx + ay * dy) / lengthSquared)) : 0;
    const east = ax + dx * amount;
    const north = ay + dy * amount;
    return {
      point: [
        point[0] + east / longitudeScale,
        point[1] + north / latitudeScale,
      ],
      distance: Math.hypot(east, north),
      amount,
    };
  }

  candidates(point, radius = 2) {
    const centerX = Math.floor(point[0] / this.cellSize);
    const centerY = Math.floor(point[1] / this.cellSize);
    const segments = [];
    const seen = new Set();
    for (let x = centerX - radius; x <= centerX + radius; x += 1) {
      for (let y = centerY - radius; y <= centerY + radius; y += 1) {
        for (const segment of this.cells.get(this.cellKey(x, y)) || []) {
          const key = `${segment.wayId}:${segment.from[0]}:${segment.from[1]}`;
          if (!seen.has(key)) {
            seen.add(key);
            segments.push(segment);
          }
        }
      }
    }
    return segments;
  }

  match(point, vehicleBearing) {
    let best = null;
    for (const segment of this.candidates(point)) {
      const projection = this.project(point, segment);
      const roadBearing = DirectedRoadMatcher.bearing(segment.from, segment.to);
      const directionDifference = Math.abs(
        DirectedRoadMatcher.normalizeAngle(vehicleBearing - roadBearing)
      );
      const continuityBonus = segment.wayId === this.previousWayId ? 35 : 0;
      // Distance selects the carriageway. Heading helps at overlaps, while a
      // reverse-driving car can still be matched and explicitly reported.
      const headingPenalty = Math.min(directionDifference, 180 - directionDifference) * 0.35;
      const score = projection.distance + headingPenalty - continuityBonus;
      if (!best || score < best.score) {
        best = {
          ...projection,
          score,
          roadBearing,
          directionDifference,
          wayId: segment.wayId,
          properties: segment.properties,
        };
      }
    }

    if (!best || best.distance > 1200) return null;
    this.previousWayId = best.wayId;
    this.previousPoint = best.point;
    best.withFlow = best.directionDifference <= 90;
    return best;
  }
}

class NavigationMapRenderer {
  constructor(containerId) {
    this.container = document.getElementById(containerId);
    this.map = null;
    this.marker = null;
    this.calibration = null;
    this.matcher = null;
    this.ready = false;
    this.active = false;
    this.trackInfo = null;
    this.currentTrackKey = "";
    this.orientationMode = "headingUp";
    this.autoZoomEnabled = localStorage.getItem("gps_auto_zoom") !== "false";
    this.tiltAngle = localStorage.getItem("gps_3d_tilt") === "false" ? 0 : 49;
    this.is3D = this.tiltAngle > 10;
    this.theme = document.documentElement.getAttribute("data-theme") || "dark";
    this.isFreeBrowsing = false;
    this.lastInteractionTime = 0;
    this.lastCameraUpdate = 0;
    this.statusElement = document.getElementById("road-direction-status");
    this.recenterBtn = document.getElementById("btn-recenter");
    this.readyPromise = this.initialize();
  }

  get capabilities() {
    return {
      vectorMap: true,
      offline: true,
      mapMatching: true,
      directionDetection: true,
      routing: false,
    };
  }

  createStyle(roads) {
    const light = this.theme === "light";
    return {
      version: 8,
      sources: {
        "srp-roads": { type: "geojson", data: roads },
      },
      layers: [
        {
          id: "background",
          type: "background",
          paint: { "background-color": light ? "#e5e7eb" : "#080d16" },
        },
        {
          id: "road-casing",
          type: "line",
          source: "srp-roads",
          layout: { "line-cap": "round", "line-join": "round" },
          paint: {
            "line-color": light ? "#94a3b8" : "#020617",
            "line-width": ["interpolate", ["linear"], ["zoom"], 9, 1.2, 13, 4.5, 17, 14],
          },
        },
        {
          id: "roads",
          type: "line",
          source: "srp-roads",
          layout: { "line-cap": "round", "line-join": "round" },
          paint: {
            "line-color": [
              "case",
              ["==", ["get", "highway"], "motorway_link"],
              light ? "#38bdf8" : "#0ea5e9",
              light ? "#f8fafc" : "#cbd5e1",
            ],
            "line-width": ["interpolate", ["linear"], ["zoom"], 9, 0.8, 13, 3, 17, 10],
          },
        },
      ],
    };
  }

  createArrowImage() {
    const size = 32;
    const canvas = document.createElement("canvas");
    canvas.width = size;
    canvas.height = size;
    const context = canvas.getContext("2d");
    context.clearRect(0, 0, size, size);
    context.strokeStyle = this.theme === "light" ? "#0369a1" : "#38bdf8";
    context.lineWidth = 4;
    context.lineCap = "round";
    context.lineJoin = "round";
    context.beginPath();
    context.moveTo(7, 8);
    context.lineTo(19, 16);
    context.lineTo(7, 24);
    context.stroke();
    return context.getImageData(0, 0, size, size);
  }

  async initialize() {
    if (!this.container) throw new Error("Navigation map container is missing");
    if (!window.maplibregl) throw new Error("MapLibre GL JS is unavailable");

    const [roadsResponse, calibrationResponse] = await Promise.all([
      fetch("/assets/maps/srp-osm-roads.geojson"),
      fetch("/assets/maps/srp-osm-calibration.json"),
    ]);
    if (!roadsResponse.ok || !calibrationResponse.ok) {
      throw new Error("Offline SRP navigation data could not be loaded");
    }
    const [roads, calibration] = await Promise.all([
      roadsResponse.json(),
      calibrationResponse.json(),
    ]);
    this.calibration = new SrpCoordinateCalibration(calibration);
    this.matcher = new DirectedRoadMatcher(roads);

    this.map = new window.maplibregl.Map({
      container: this.container,
      style: this.createStyle(roads),
      center: [139.745, 35.62],
      zoom: 12.5,
      bearing: 0,
      pitch: this.tiltAngle,
      minZoom: 8,
      maxZoom: 18.5,
      attributionControl: false,
      maplibreLogo: false,
      dragRotate: true,
      touchPitch: true,
    });
    this.map.addControl(
      new window.maplibregl.AttributionControl({
        compact: true,
        customAttribution: '<a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">© OpenStreetMap contributors</a>',
      })
    );

    await new Promise((resolve, reject) => {
      const timeout = window.setTimeout(
        () => reject(new Error("Navigation map initialization timed out")),
        10000
      );
      this.map.once("load", () => {
        window.clearTimeout(timeout);
        resolve();
      });
      this.map.once("error", (event) => {
        if (!this.map.loaded()) {
          window.clearTimeout(timeout);
          reject(event.error || new Error("MapLibre failed to initialize"));
        }
      });
    });

    const arrow = this.createArrowImage();
    this.map.addImage("road-direction-arrow", arrow, { pixelRatio: 2 });
    this.map.addLayer({
      id: "road-direction-arrows",
      type: "symbol",
      source: "srp-roads",
      minzoom: 12,
      layout: {
        "symbol-placement": "line",
        "symbol-spacing": 85,
        "icon-image": "road-direction-arrow",
        "icon-size": ["interpolate", ["linear"], ["zoom"], 12, 0.45, 17, 0.8],
        "icon-allow-overlap": false,
        "icon-ignore-placement": false,
        "icon-rotation-alignment": "map",
      },
    });

    const markerElement = document.createElement("div");
    markerElement.className = "navigation-car-marker";
    markerElement.innerHTML = '<span class="navigation-car-arrow"></span>';
    this.marker = new window.maplibregl.Marker({
      element: markerElement,
      anchor: "center",
      rotationAlignment: "map",
      pitchAlignment: "map",
    })
      .setLngLat([139.745, 35.62])
      .addTo(this.map);

    const markBrowsing = (event) => {
      if (event?.originalEvent) {
        this.isFreeBrowsing = true;
        this.lastInteractionTime = Date.now();
        this.updateRecenterButton(true);
      }
    };
    this.map.on("dragstart", markBrowsing);
    this.map.on("zoomstart", markBrowsing);
    this.map.on("rotatestart", markBrowsing);
    this.map.on("pitchstart", markBrowsing);
    this.ready = true;
    this.setTheme(this.theme);
    return this;
  }

  setActive(active) {
    this.active = !!active;
    if (this.container) this.container.classList.toggle("active", this.active);
    if (this.statusElement) this.statusElement.hidden = !this.active;
    if (this.active && this.map) {
      window.setTimeout(() => this.map.resize(), 0);
    }
  }

  setTrackInfo(info, trackName) {
    this.trackInfo = info || this.trackInfo;
    this.currentTrackKey = trackName || this.currentTrackKey;
  }

  setTheme(theme) {
    this.theme = theme === "light" ? "light" : "dark";
    if (!this.map || !this.map.isStyleLoaded()) return;
    const light = this.theme === "light";
    this.map.setPaintProperty("background", "background-color", light ? "#e5e7eb" : "#080d16");
    this.map.setPaintProperty("road-casing", "line-color", light ? "#94a3b8" : "#020617");
    this.map.setPaintProperty("roads", "line-color", [
      "case",
      ["==", ["get", "highway"], "motorway_link"],
      light ? "#38bdf8" : "#0ea5e9",
      light ? "#f8fafc" : "#cbd5e1",
    ]);
  }

  updateEnvironment() {}

  updateRecenterButton(show) {
    if (this.recenterBtn && this.active) {
      this.recenterBtn.style.display = show ? "flex" : "none";
    }
  }

  recenter() {
    this.isFreeBrowsing = false;
    this.updateRecenterButton(false);
  }

  toggleOrientation() {
    this.orientationMode = this.orientationMode === "headingUp" ? "northUp" : "headingUp";
    return this.orientationMode;
  }

  setTiltAngle(angle) {
    this.tiltAngle = Math.max(0, Math.min(60, angle));
    this.is3D = this.tiltAngle > 10;
    if (this.map) this.map.easeTo({ pitch: this.tiltAngle, duration: 250 });
    return this.is3D;
  }

  toggleTilt() {
    return this.setTiltAngle(this.tiltAngle > 15 ? 0 : 49);
  }

  setAutoZoom(enabled) {
    this.autoZoomEnabled = !!enabled;
    return this.autoZoomEnabled;
  }

  setDirectionStatus(match) {
    if (!this.statusElement) return;
    if (!match) {
      this.statusElement.className = "road-direction-status direction-unknown";
      this.statusElement.innerHTML = '<span class="direction-icon">·</span><span>Finding carriageway…</span>';
      return;
    }
    const roadName = match.properties.ref || match.properties.name_en || match.properties.name || "Expressway";
    this.statusElement.className = `road-direction-status ${match.withFlow ? "direction-with-flow" : "direction-against-flow"}`;
    this.statusElement.innerHTML = match.withFlow
      ? `<span class="direction-icon">→</span><span>${roadName} · with traffic</span>`
      : `<span class="direction-icon">↶</span><span>${roadName} · opposite direction</span>`;
  }

  render(interpolator) {
    if (!this.active || !this.ready || !this.map || !this.calibration) return;
    const position = interpolator.currentPos;
    if (!position || position.length < 3) return;

    const longitudeLatitude = this.calibration.toLngLat(position[0], position[2]);
    const vehicleBearing = this.calibration.headingToBearing(
      position[0],
      position[2],
      interpolator.currentHeading
    );
    const match = this.matcher.match(longitudeLatitude, vehicleBearing);
    const markerPoint = match?.point || longitudeLatitude;
    this.marker.setLngLat(markerPoint).setRotation(vehicleBearing);
    this.setDirectionStatus(match);

    if (this.isFreeBrowsing && Date.now() - this.lastInteractionTime > 15000 && interpolator.currentSpeed > 5) {
      this.recenter();
    }
    if (this.isFreeBrowsing) return;

    const now = performance.now();
    if (now - this.lastCameraUpdate < 50) return;
    this.lastCameraUpdate = now;
    const speedRatio = Math.min(Math.max(interpolator.currentSpeed / 250, 0), 1);
    const zoom = this.autoZoomEnabled ? 15.6 - speedRatio * 1.7 : 14.8;
    this.map.jumpTo({
      center: markerPoint,
      bearing: this.orientationMode === "headingUp" ? vehicleBearing : 0,
      pitch: this.tiltAngle,
      zoom,
    });
  }
}

window.SrpCoordinateCalibration = SrpCoordinateCalibration;
window.DirectedRoadMatcher = DirectedRoadMatcher;
window.NavigationMapRenderer = NavigationMapRenderer;
