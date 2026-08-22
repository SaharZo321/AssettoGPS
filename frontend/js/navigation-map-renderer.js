/**
 * Offline MapLibre renderer for SRP.
 *
 * MapLibre renders SRP's own directed traffic lanes in game coordinates.
 */

const SRP_NAVIGATION_AUTO_ZOOM_SCALE = 1.25;

class SrpGameProjection {
  constructor(config) {
    this.origin = config.origin || [139.75, 35.6];
    this.metersPerLongitudeDegree = Number(config.metersPerLongitudeDegree);
    this.metersPerLatitudeDegree = Number(config.metersPerLatitudeDegree);
    if (!this.metersPerLongitudeDegree || !this.metersPerLatitudeDegree) {
      throw new Error('SRP lane projection metadata is invalid');
    }
    if (config.longitudeAxis && config.longitudeAxis !== "+x") {
      throw new Error('SRP lane projection must map +X east');
    }
    if (config.latitudeAxis && config.latitudeAxis !== "-z") {
      throw new Error('SRP lane projection must map -Z north');
    }
  }

  toLngLat(x, z) {
    return [
      this.origin[0] + x / this.metersPerLongitudeDegree,
      this.origin[1] - z / this.metersPerLatitudeDegree,
    ];
  }

  headingToBearing(x, z, headingRadians) {
    const origin = this.toLngLat(x, z);
    const ahead = this.toLngLat(
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
    this.previousSegmentKey = null;
    this.previousPoint = null;
    this.previousInputPoint = null;
    this.buildIndex(featureCollection);
  }

  resetContinuity() {
    this.previousWayId = null;
    this.previousSegmentKey = null;
    this.previousPoint = null;
    this.previousInputPoint = null;
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

  static distance(from, to) {
    const averageLatitude = ((from[1] + to[1]) * Math.PI) / 360;
    return Math.hypot(
      (from[0] - to[0]) * 111320 * Math.cos(averageLatitude),
      (from[1] - to[1]) * 111320
    );
  }

  cellKey(x, y) {
    return `${x}:${y}`;
  }

  buildIndex(featureCollection) {
    for (const feature of featureCollection.features || []) {
      const originalCoordinates = feature.geometry?.coordinates || [];
      const oneway = String(feature.properties?.oneway || "").toLowerCase();
      const coordinates = oneway === "-1" ? [...originalCoordinates].reverse() : originalCoordinates;
      const laneId = feature.properties?.lane_id ?? feature.properties?.osm_id;
      for (let index = 0; index < coordinates.length - 1; index += 1) {
        const segment = {
          from: coordinates[index],
          to: coordinates[index + 1],
          fromElevation: Number(coordinates[index][2]) || 0,
          toElevation: Number(coordinates[index + 1][2]) || 0,
          wayId: laneId,
          key: `${laneId}:${index}:${coordinates[index][0]}:${coordinates[index][1]}`,
          oneWay: ["yes", "1", "true", "-1"].includes(oneway),
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
      elevation: segment.fromElevation + (segment.toElevation - segment.fromElevation) * amount,
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

  match(point, vehicleBearing, vehicleElevation = null) {
    let best = null;
    for (const segment of this.candidates(point)) {
      const projection = this.project(point, segment);
      const roadBearing = DirectedRoadMatcher.bearing(segment.from, segment.to);
      const directionDifference = Math.abs(
        DirectedRoadMatcher.normalizeAngle(vehicleBearing - roadBearing)
      );
      // Native SRP lane geometry is precise enough that proximity must remain
      // the primary signal. Continuity is only a tie-breaker between adjacent
      // segments; a large bonus can pin the match to a stale part of a long
      // lane and make the vehicle appear to teleport.
      const continuityBonus = segment.key === this.previousSegmentKey
        ? 3
        : segment.wayId === this.previousWayId ? 1 : 0;
      // Distance selects the carriageway. Heading helps at overlaps, while a
      // reverse-driving car can still be matched and explicitly reported.
      const headingPenalty = Math.min(directionDifference, 180 - directionDifference) * 0.08;
      const elevationDifference = vehicleElevation === null
        ? 0
        : Math.abs(vehicleElevation - projection.elevation);
      // X/Z can overlap in SRP tunnels and stacked junctions. Elevation keeps
      // those carriageways separate without ever moving the visible marker.
      const elevationPenalty = elevationDifference * 4;
      const score = (projection.distance * 3) + headingPenalty
        + elevationPenalty - continuityBonus;
      if (!best || score < best.score) {
        best = {
          ...projection,
          score,
          roadBearing,
          directionDifference,
          elevationDifference,
          wayId: segment.wayId,
          segmentKey: segment.key,
          segmentFrom: segment.from,
          segmentTo: segment.to,
          oneWay: segment.oneWay,
          properties: segment.properties,
        };
      }
    }

    if (!best || best.distance > 1200) return null;
    this.previousWayId = best.wayId;
    this.previousSegmentKey = best.segmentKey;
    this.previousPoint = best.point;
    this.previousInputPoint = point;
    best.withFlow = !best.oneWay || best.directionDifference <= 90;
    best.alignedBearing = DirectedRoadMatcher.normalizeAngle(
      best.roadBearing + (best.directionDifference > 90 ? 180 : 0)
    );
    return best;
  }

  routeCandidates(point, vehicleBearing, vehicleElevation = null) {
    const candidates = [];
    for (const segment of this.candidates(point)) {
      const projection = this.project(point, segment);
      const roadBearing = DirectedRoadMatcher.bearing(segment.from, segment.to);
      const directionDifference = Math.abs(
        DirectedRoadMatcher.normalizeAngle(vehicleBearing - roadBearing)
      );
      const elevationDifference = vehicleElevation === null
        ? 0
        : Math.abs(vehicleElevation - projection.elevation);
      if (segment.oneWay && directionDifference > 90) continue;
      if (projection.distance > 120 || elevationDifference > 12) continue;
      const score = (projection.distance * 3)
        + (directionDifference * 0.35)
        + (elevationDifference * 4);
      candidates.push({
        ...projection,
        score,
        roadBearing,
        directionDifference,
        elevationDifference,
        wayId: segment.wayId,
        segmentKey: segment.key,
        segmentFrom: segment.from,
        segmentTo: segment.to,
        oneWay: segment.oneWay,
        properties: segment.properties,
        withFlow: true,
        alignedBearing: roadBearing,
      });
    }
    return candidates.sort((left, right) => left.score - right.score);
  }

}

class DirectedRoadGraph {
  constructor(featureCollection) {
    this.nodes = new Map();
    this.disallowedTransitions = new Set(
      (featureCollection.disallowedTransitions || []).map((pair) => pair.join(':'))
    );
    this.build(featureCollection);
  }

  key(point) {
    return `${Number(point[0]).toFixed(7)},${Number(point[1]).toFixed(7)},${Number(point[2] || 0).toFixed(2)}`;
  }

  distance(from, to) {
    const averageLatitude = ((from[1] + to[1]) * Math.PI) / 360;
    return Math.hypot(
      (from[0] - to[0]) * 111320 * Math.cos(averageLatitude),
      (from[1] - to[1]) * 111320
    );
  }

  project(point, from, to) {
    const latitudeRadians = (point[1] * Math.PI) / 180;
    const longitudeScale = 111320 * Math.cos(latitudeRadians);
    const latitudeScale = 111320;
    const ax = (from[0] - point[0]) * longitudeScale;
    const ay = (from[1] - point[1]) * latitudeScale;
    const bx = (to[0] - point[0]) * longitudeScale;
    const by = (to[1] - point[1]) * latitudeScale;
    const dx = bx - ax;
    const dy = by - ay;
    const lengthSquared = dx * dx + dy * dy;
    const amount = lengthSquared
      ? Math.max(0, Math.min(1, -(ax * dx + ay * dy) / lengthSquared))
      : 0;
    return {
      point: [
        point[0] + (ax + dx * amount) / longitudeScale,
        point[1] + (ay + dy * amount) / latitudeScale,
      ],
      amount,
    };
  }

  ensureNode(point) {
    const key = this.key(point);
    if (!this.nodes.has(key)) this.nodes.set(key, { point, edges: [] });
    return key;
  }

  addEdge(from, to, properties) {
    const fromKey = this.ensureNode(from);
    const toKey = this.ensureNode(to);
    this.nodes.get(fromKey).edges.push({
      to: toKey,
      distance: this.distance(from, to),
      properties,
    });
  }

  build(featureCollection) {
    const endpoints = [];
    for (const feature of featureCollection.features || []) {
      const original = feature.geometry?.coordinates || [];
      if (original.length < 2) continue;
      const laneId = feature.properties?.lane_id;
      endpoints.push({
        laneId,
        start: original[0],
        end: original[original.length - 1],
        startBearing: DirectedRoadMatcher.bearing(original[0], original[1]),
        endBearing: DirectedRoadMatcher.bearing(
          original[original.length - 2], original[original.length - 1]
        ),
      });
      const oneway = String(feature.properties?.oneway || "yes").toLowerCase();
      const coordinates = oneway === "-1" ? [...original].reverse() : original;
      for (let index = 0; index < coordinates.length - 1; index += 1) {
        this.addEdge(coordinates[index], coordinates[index + 1], feature.properties);
        if (!["yes", "1", "true", "-1"].includes(oneway)) {
          this.addEdge(coordinates[index + 1], coordinates[index], feature.properties);
        }
      }
    }
    if (Array.isArray(featureCollection.routeConnections)
        && featureCollection.routeConnections.length) {
      this.connectIntersectionRoutes(featureCollection.routeConnections);
    } else {
      this.connectLaneEndpoints(endpoints);
    }
  }

  connectIntersectionRoutes(connections) {
    for (const connection of connections) {
      if (!Array.isArray(connection) || connection.length < 9) continue;
      this.addEdge(
        connection.slice(0, 3),
        connection.slice(3, 6),
        {
          connector: true,
          from_lane_id: connection[6],
          to_lane_id: connection[7],
          intersection_id: connection[8],
        }
      );
    }
  }

  connectLaneEndpoints(endpoints) {
    for (const exit of endpoints) {
      for (const entrance of endpoints) {
        if (exit.laneId === entrance.laneId) continue;
        if (this.disallowedTransitions.has(`${exit.laneId}:${entrance.laneId}`)) continue;
        const distance = this.distance(exit.end, entrance.start);
        if (distance > 24) continue;
        const elevationDifference = Math.abs(
          (Number(exit.end[2]) || 0) - (Number(entrance.start[2]) || 0)
        );
        if (elevationDifference > 8) continue;
        const turn = Math.abs(
          DirectedRoadMatcher.normalizeAngle(entrance.startBearing - exit.endBearing)
        );
        if (turn > 145) continue;
        this.addEdge(exit.end, entrance.start, {
          connector: true,
          from_lane_id: exit.laneId,
          to_lane_id: entrance.laneId,
        });
      }
    }
  }

  nearestNode(point) {
    let nearestKey = null;
    let nearestDistance = Infinity;
    for (const [key, node] of this.nodes) {
      const distance = this.distance(point, node.point);
      if (distance < nearestDistance) {
        nearestDistance = distance;
        nearestKey = key;
      }
    }
    return { key: nearestKey, distance: nearestDistance };
  }

  nearbyDestinationNodes(point, extraDistance = 75) {
    const candidates = [];
    let nearestDistance = Infinity;
    for (const [key, node] of this.nodes) {
      const distance = this.distance(point, node.point);
      candidates.push({ key, distance });
      nearestDistance = Math.min(nearestDistance, distance);
    }
    const threshold = Math.min(1500, nearestDistance + extraDistance);
    return candidates.filter((candidate) => candidate.distance <= threshold);
  }

  pushHeap(heap, item) {
    heap.push(item);
    let index = heap.length - 1;
    while (index > 0) {
      const parent = Math.floor((index - 1) / 2);
      if (heap[parent][0] <= item[0]) break;
      heap[index] = heap[parent];
      index = parent;
    }
    heap[index] = item;
  }

  popHeap(heap) {
    if (!heap.length) return null;
    const root = heap[0];
    const last = heap.pop();
    if (heap.length && last) {
      let index = 0;
      while (true) {
        const left = index * 2 + 1;
        const right = left + 1;
        if (left >= heap.length) break;
        const child = right < heap.length && heap[right][0] < heap[left][0] ? right : left;
        if (heap[child][0] >= last[0]) break;
        heap[index] = heap[child];
        index = child;
      }
      heap[index] = last;
    }
    return root;
  }

  route(startPoint, destinationPoint, startMatch = null) {
    if (!startMatch?.segmentTo) return null;
    const matchedStartKey = this.key(startMatch.segmentTo);
    if (!this.nodes.has(matchedStartKey)) return null;
    const start = {
      key: matchedStartKey,
      distance: this.distance(startPoint, startMatch.segmentTo),
      routeOrigin: startPoint,
    };
    const destinations = this.nearbyDestinationNodes(destinationPoint);
    if (!start.key || !destinations.length || start.distance > 1500) {
      return null;
    }

    const destinationByKey = new Map(
      destinations.map((destination) => [destination.key, destination])
    );
    const distances = new Map([[start.key, start.distance]]);
    const previous = new Map();
    const queue = [];
    this.pushHeap(queue, [start.distance, start.key, start.distance]);
    let destination = null;
    let bestDestinationScore = Infinity;

    while (queue.length) {
      const current = this.popHeap(queue);
      const currentKey = current[1];
      const currentDistance = current[2];
      if (currentDistance !== distances.get(currentKey)) continue;
      if (currentDistance > bestDestinationScore) break;
      if (destinationByKey.has(currentKey)) {
        const candidateDestination = destinationByKey.get(currentKey);
        // Prefer finishing close to the landmark, but allow a nearby
        // reachable carriageway when the geometrically closest one is inbound.
        const destinationScore = currentDistance + candidateDestination.distance * 3;
        if (destinationScore < bestDestinationScore) {
          destination = candidateDestination;
          bestDestinationScore = destinationScore;
        }
      }

      const node = this.nodes.get(currentKey);
      for (const edge of node.edges) {
        const candidate = currentDistance + edge.distance;
        if (candidate >= (distances.get(edge.to) ?? Infinity)) continue;
        distances.set(edge.to, candidate);
        previous.set(edge.to, currentKey);
        this.pushHeap(queue, [candidate, edge.to, candidate]);
      }
    }

    if (!destination || !distances.has(destination.key)) return null;
    const keys = [];
    let key = destination.key;
    while (key) {
      keys.push(key);
      if (key === start.key) break;
      key = previous.get(key);
    }
    if (keys[keys.length - 1] !== start.key) return null;
    keys.reverse();
    const coordinates = keys.map((nodeKey) => this.nodes.get(nodeKey).point);
    const nodeKeys = [...keys];
    if (start.routeOrigin && this.distance(start.routeOrigin, coordinates[0]) > 0.05) {
      coordinates.unshift(start.routeOrigin);
      nodeKeys.unshift(null);
    }
    const remaining = new Array(coordinates.length).fill(0);
    for (let index = coordinates.length - 2; index >= 0; index -= 1) {
      remaining[index] = remaining[index + 1] + this.distance(coordinates[index], coordinates[index + 1]);
    }
    return {
      coordinates,
      nodeKeys,
      remaining,
      distanceM: distances.get(destination.key),
      startSnapDistanceM: Number(startMatch.distance) || 0,
      startSegmentRemainingM: start.distance,
      destinationSnapDistanceM: destination.distance,
    };
  }
}

class NavigationMapRenderer {
  constructor(containerId) {
    this.container = document.getElementById(containerId);
    this.map = null;
    this.marker = null;
    this.projection = null;
    this.matcher = null;
    this.graph = null;
    this.destinations = [];
    this.activeRoute = null;
    this.destination = null;
    this.routeProgressIndex = 0;
    this.routeProgressAmount = 0;
    this.lastRouteProgressUpdate = 0;
    this.offRouteSince = 0;
    this.lastRerouteAttempt = Number.NEGATIVE_INFINITY;
    this.routeRecalculationDelayMs = 1800;
    this.routeRecalculationCooldownMs = 4000;
    this.lastMarkerPoint = null;
    this.lastGamePoint = null;
    this.displayPoint = null;
    this.displayBearing = null;
    this.lastRenderTime = 0;
    this.courseReferencePoint = null;
    this.courseBearing = null;
    this.lastTravelBearing = null;
    this.lastMatch = null;
    this.lastReliableMatch = null;
    this.maxReliableMatchDistance = 45;
    this.maxReliableElevationDifference = 12;
    this.ready = false;
    this.active = false;
    this.trackInfo = null;
    this.currentTrackKey = "";
    this.orientationMode = "headingUp";
    this.autoZoomEnabled = localStorage.getItem("gps_auto_zoom") !== "false";
    this.tiltedAngle = 60;
    this.tiltAngle = localStorage.getItem("gps_3d_tilt") === "false" ? 0 : this.tiltedAngle;
    this.is3D = this.tiltAngle > 10;
    this.theme = document.documentElement.getAttribute("data-theme") || "dark";
    this.isFreeBrowsing = false;
    this.lastInteractionTime = 0;
    this.statusElement = document.getElementById("road-direction-status");
    this.guidanceElement = document.getElementById("route-guidance-status");
    this.recenterBtn = document.getElementById("btn-recenter");
    this.readyPromise = this.initialize();
  }

  get capabilities() {
    return {
      vectorMap: true,
      offline: true,
      mapMatching: true,
      directionDetection: true,
      routing: !!this.graph,
      activeRoute: !!this.activeRoute,
    };
  }

  createStyle(roads) {
    const light = this.theme === "light";
    return {
      version: 8,
      sources: {
        "srp-roads": { type: "geojson", data: roads },
        "active-route": {
          type: "geojson",
          data: { type: "FeatureCollection", features: [] },
        },
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
            "line-width": ["interpolate", ["linear"], ["zoom"], 9, 0.8, 13, 2.8, 17, 7],
          },
        },
        {
          id: "roads",
          type: "line",
          source: "srp-roads",
          layout: { "line-cap": "round", "line-join": "round" },
          paint: {
            "line-color": [
              "match",
              ["get", "role"],
              1, light ? "#64748b" : "#334155",
              2, light ? "#0ea5e9" : "#38bdf8",
              4, light ? "#f8fafc" : "#e2e8f0",
              light ? "#e2e8f0" : "#94a3b8",
            ],
            "line-width": ["interpolate", ["linear"], ["zoom"], 9, 0.5, 13, 1.7, 17, 4.5],
          },
        },
        {
          id: "route-casing",
          type: "line",
          source: "active-route",
          layout: { "line-cap": "round", "line-join": "round" },
          paint: {
            "line-color": "#082f49",
            "line-opacity": 0.95,
            "line-width": ["interpolate", ["linear"], ["zoom"], 9, 3, 13, 9, 17, 22],
          },
        },
        {
          id: "route-line",
          type: "line",
          source: "active-route",
          layout: { "line-cap": "round", "line-join": "round" },
          paint: {
            "line-color": "#22d3ee",
            "line-opacity": 0.95,
            "line-width": ["interpolate", ["linear"], ["zoom"], 9, 1.5, 13, 5.5, 17, 14],
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

    const roadsResponse = await fetch('/assets/maps/srp-traffic-lanes.geojson');
    if (!roadsResponse.ok) {
      throw new Error('Offline SRP traffic lanes could not be loaded');
    }
    const roads = await roadsResponse.json();
    this.projection = new SrpGameProjection(roads.coordinateSpace || {});
    this.matcher = new DirectedRoadMatcher(roads);
    this.graph = new DirectedRoadGraph(roads);
    this.destinations = (roads.destinations || []).map((destination) => ({
      name: destination.name,
      point: this.projection.toLngLat(destination.ac[0], destination.ac[1]),
    }));
    const initialCenter = this.projection.toLngLat(0, 0);

    this.map = new window.maplibregl.Map({
      container: this.container,
      style: this.createStyle(roads),
      center: initialCenter,
      zoom: 12.5,
      bearing: 0,
      pitch: this.tiltAngle,
      minZoom: 8,
      maxZoom: 18.5,
      attributionControl: false,
      maplibreLogo: false,
      dragRotate: true,
      pitchWithRotate: false,
      touchPitch: false,
    });
    this.map.addControl(
      new window.maplibregl.AttributionControl({
        compact: true,
        customAttribution: '<a href="https://www.overtake.gg/downloads/traffic-plan-shutoko-revival-project.57715/" target="_blank" rel="noopener">Prototype lanes: Bardaff</a>',
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
      rotationAlignment: "viewport",
      pitchAlignment: "viewport",
    })
      .setLngLat(initialCenter)
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
    const nextActive = !!active;
    const activating = nextActive && !this.active;
    this.active = nextActive;
    if (activating) {
      // The car may have moved a long way while Simple Map was active. Reset
      // visual and matching continuity so the first Navigation frame starts
      // at the live coordinate instead of sweeping across the map.
      this.displayPoint = null;
      this.displayBearing = null;
      this.lastRenderTime = 0;
      this.courseReferencePoint = null;
      this.courseBearing = null;
      this.lastMatch = null;
      this.lastReliableMatch = null;
      this.matcher?.resetContinuity();
    }
    if (this.container) this.container.classList.toggle("active", this.active);
    if (this.statusElement) this.statusElement.hidden = !this.active;
    if (this.guidanceElement) this.guidanceElement.hidden = !this.active || !this.activeRoute;
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
      "match",
      ["get", "role"],
      1, light ? "#64748b" : "#334155",
      2, light ? "#0ea5e9" : "#38bdf8",
      4, light ? "#f8fafc" : "#e2e8f0",
      light ? "#e2e8f0" : "#94a3b8",
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
    if (this.map && this.displayPoint && this.displayBearing !== null) {
      this.map.jumpTo({
        center: this.displayPoint,
        bearing: this.orientationMode === "headingUp" ? this.displayBearing : 0,
        pitch: this.tiltAngle,
      });
    }
  }

  toggleOrientation() {
    this.orientationMode = this.orientationMode === "headingUp" ? "northUp" : "headingUp";
    // Orientation is a camera command, so it must leave free-browse mode and
    // apply immediately. Otherwise a previous pan/rotate gesture makes the
    // button appear to do nothing until the automatic recenter timeout.
    this.recenter();
    if (this.map && this.displayBearing !== null) {
      this.map.jumpTo({
        bearing: this.orientationMode === "headingUp" ? this.displayBearing : 0,
      });
    }
    return this.orientationMode;
  }

  resolveTravelBearing(point, telemetryBearing) {
    if (!this.courseReferencePoint) {
      this.courseReferencePoint = [...point];
      this.courseBearing = telemetryBearing;
      return telemetryBearing;
    }

    const movement = DirectedRoadMatcher.distance(this.courseReferencePoint, point);
    if (movement > 300) {
      // Session restarts and teleports must not be interpreted as a heading.
      this.courseReferencePoint = [...point];
      this.courseBearing = telemetryBearing;
      this.matcher?.resetContinuity();
    } else if (movement >= 0.8) {
      const measuredBearing = DirectedRoadMatcher.bearing(this.courseReferencePoint, point);
      const bearingDifference = DirectedRoadMatcher.normalizeAngle(
        measuredBearing - this.courseBearing
      );
      if (Math.abs(bearingDifference) > 120) {
        // Some telemetry sources expose the rearward vehicle axis. A nearly
        // opposite course is a convention mismatch, not a 180-degree corner.
        this.courseBearing = measuredBearing;
      } else {
        const factor = Math.min(0.55, Math.max(0.18, movement / 10));
        this.courseBearing = DirectedRoadMatcher.normalizeAngle(
          this.courseBearing + bearingDifference * factor
        );
      }
      this.courseReferencePoint = [...point];
    }

    // Course-over-ground is independent of whether a telemetry provider
    // defines heading as the car's forward or rearward axis. Once measured,
    // retain the last stable course while the vehicle is stopped.
    return this.courseBearing ?? telemetryBearing;
  }

  setTiltAngle(angle) {
    this.tiltAngle = Math.max(0, Math.min(this.tiltedAngle, angle));
    this.is3D = this.tiltAngle > 10;
    if (this.map) this.map.easeTo({ pitch: this.tiltAngle, duration: 250 });
    return this.is3D;
  }

  toggleTilt() {
    return this.setTiltAngle(this.is3D ? 0 : this.tiltedAngle);
  }

  setAutoZoom(enabled) {
    this.autoZoomEnabled = !!enabled;
    return this.autoZoomEnabled;
  }

  setDirectionStatus(match) {
    if (!this.statusElement) return;
    if (!match) {
      this.statusElement.className = "road-direction-status direction-unknown";
      this.statusElement.innerHTML = '<span class="direction-icon">&middot;</span><span>Finding game lane&hellip;</span>';
      return;
    }
    const roleName = match.properties.role_name || 'Expressway';
    const roadName = `${roleName} lane ${match.properties.lane_id ?? ''}`.trim();
    this.statusElement.className = `road-direction-status ${match.withFlow ? "direction-with-flow" : "direction-against-flow"}`;
    this.statusElement.innerHTML = match.withFlow
      ? `<span class="direction-icon">&rarr;</span><span>${roadName} &middot; with traffic</span>`
      : `<span class="direction-icon">&crarr;</span><span>${roadName} &middot; opposite direction</span>`;
  }

  getDestinations() {
    return this.destinations.map((destination) => destination.name);
  }

  routeGeoJson(coordinates) {
    return {
      type: "FeatureCollection",
      features: coordinates.length > 1
        ? [{ type: "Feature", properties: {}, geometry: { type: "LineString", coordinates } }]
        : [],
    };
  }

  dispatchRouteChange(detail) {
    window.dispatchEvent(new CustomEvent("gps-navigation-route-changed", { detail }));
  }

  navigationMatches(point, bearing, elevation) {
    return this.matcher?.routeCandidates(point, bearing, elevation) || [];
  }

  planRoute(point, bearing, elevation, destination = this.destination) {
    if (!destination) return null;
    let best = null;
    const seenStarts = new Set();
    for (const match of this.navigationMatches(point, bearing, elevation)) {
      const startKey = this.graph.key(match.segmentTo);
      if (seenStarts.has(startKey)) continue;
      seenStarts.add(startKey);
      const route = this.graph.route(match.point, destination.point, match);
      if (!route) continue;
      const score = route.distanceM
        + (match.distance * 5)
        + (match.directionDifference * 1.5)
        + (match.elevationDifference * 8);
      if (!best || score < best.score) best = { route, match, score };
    }
    return best;
  }

  applyRoute(route, recalculated = false) {
    this.activeRoute = route;
    this.routeProgressIndex = 0;
    this.routeProgressAmount = 0;
    this.offRouteSince = 0;
    const source = this.map?.getSource("active-route");
    if (source) source.setData(this.routeGeoJson(route.coordinates));
    if (this.guidanceElement) this.guidanceElement.hidden = !this.active;
    const detail = {
      active: true,
      destination: this.destination.name,
      distanceM: route.distanceM,
      nodeCount: route.coordinates.length,
      recalculated,
    };
    this.dispatchRouteChange(detail);
    return detail;
  }

  setDestination(destinationName) {
    const destination = this.destinations.find((item) => item.name === destinationName);
    if (!destination) return { error: "Choose a valid destination." };
    if (!this.graph || !this.lastGamePoint) return { error: "Waiting for a road position." };

    const plan = this.planRoute(
      this.lastGamePoint,
      this.lastTravelBearing,
      this.lastVehicleElevation,
      destination
    );
    if (!plan) return { error: "No directed route is available from nearby with-traffic lanes." };
    this.destination = destination;
    const detail = this.applyRoute(plan.route);
    this.updateRouteProgress([plan.match], true);
    return detail;
  }

  clearDestination() {
    this.destination = null;
    this.activeRoute = null;
    this.routeProgressIndex = 0;
    this.routeProgressAmount = 0;
    this.offRouteSince = 0;
    const source = this.map?.getSource("active-route");
    if (source) source.setData(this.routeGeoJson([]));
    if (this.guidanceElement) this.guidanceElement.hidden = true;
    const detail = { active: false };
    this.dispatchRouteChange(detail);
    return detail;
  }

  findRouteSegment(match) {
    if (!match || !this.activeRoute?.nodeKeys?.length) return null;
    const fromKey = this.graph.key(match.segmentFrom);
    const toKey = this.graph.key(match.segmentTo);
    const nodeKeys = this.activeRoute.nodeKeys;
    const start = Math.max(0, this.routeProgressIndex - 1);
    for (let index = start; index < nodeKeys.length - 1; index += 1) {
      if (nodeKeys[index + 1] !== toKey) continue;
      if (nodeKeys[index] !== null && nodeKeys[index] !== fromKey) continue;
      const projection = this.graph.project(
        match.point,
        this.activeRoute.coordinates[index],
        this.activeRoute.coordinates[index + 1]
      );
      return { index, ...projection };
    }
    return null;
  }

  redrawRemainingRoute(progress) {
    const coordinates = this.activeRoute.coordinates;
    const remainingCoordinates = [
      progress.point,
      ...coordinates.slice(progress.index + 1),
    ];
    const source = this.map?.getSource("active-route");
    if (source) source.setData(this.routeGeoJson(remainingCoordinates));
  }

  recalculateRoute(now) {
    if (now - this.lastRerouteAttempt < this.routeRecalculationCooldownMs) return false;
    this.lastRerouteAttempt = now;
    const plan = this.planRoute(
      this.lastGamePoint,
      this.lastTravelBearing,
      this.lastVehicleElevation
    );
    if (!plan) {
      if (this.guidanceElement) {
        this.guidanceElement.innerText = "Off route - finding a new route...";
        this.guidanceElement.classList.remove("route-arriving");
      }
      return false;
    }
    this.applyRoute(plan.route, true);
    return true;
  }

  updateRouteProgress(matches, force = false) {
    if (!this.activeRoute || !this.destination || !matches?.length) return;
    const now = performance.now();
    if (!force && now - this.lastRouteProgressUpdate < 300) return;
    this.lastRouteProgressUpdate = now;

    let progress = null;
    for (const match of matches) {
      progress = this.findRouteSegment(match);
      if (progress) break;
    }
    if (!progress) {
      if (!this.offRouteSince) this.offRouteSince = now;
      if (now - this.offRouteSince >= this.routeRecalculationDelayMs) {
        this.recalculateRoute(now);
      }
      return;
    }
    this.offRouteSince = 0;
    if (progress.index < this.routeProgressIndex) return;
    if (progress.index === this.routeProgressIndex) {
      progress.amount = Math.max(this.routeProgressAmount, progress.amount);
      const from = this.activeRoute.coordinates[progress.index];
      const to = this.activeRoute.coordinates[progress.index + 1];
      progress.point = [
        from[0] + (to[0] - from[0]) * progress.amount,
        from[1] + (to[1] - from[1]) * progress.amount,
      ];
    } else {
      this.routeProgressIndex = progress.index;
    }
    this.routeProgressAmount = progress.amount;
    this.redrawRemainingRoute(progress);
    const segmentRemaining = this.graph.distance(
      progress.point,
      this.activeRoute.coordinates[progress.index + 1]
    );
    const remaining = segmentRemaining
      + (this.activeRoute.remaining[progress.index + 1] || 0);
    if (!this.guidanceElement) return;
    if (remaining < 80) {
      this.guidanceElement.innerText = `${this.destination.name} - arriving`;
      this.guidanceElement.classList.add("route-arriving");
    } else {
      const distanceText = remaining >= 1000
        ? `${(remaining / 1000).toFixed(1)} km`
        : `${Math.round(remaining)} m`;
      this.guidanceElement.innerText = `${distanceText} to ${this.destination.name}`;
      this.guidanceElement.classList.remove("route-arriving");
    }
  }

  render(interpolator) {
    if (!this.active || !this.ready || !this.map || !this.projection) return;
    const position = interpolator.currentPos;
    if (!position || position.length < 3) return;

    const longitudeLatitude = this.projection.toLngLat(position[0], position[2]);
    const telemetryBearing = this.projection.headingToBearing(
      position[0],
      position[2],
      interpolator.currentHeading
    );
    const travelBearing = this.resolveTravelBearing(
      longitudeLatitude,
      telemetryBearing
    );
    this.lastTravelBearing = travelBearing;
    this.lastVehicleElevation = position[1];
    const match = this.matcher.match(longitudeLatitude, travelBearing, position[1]);
    const reliableMatch = match
      && match.distance <= this.maxReliableMatchDistance
      && match.elevationDifference <= this.maxReliableElevationDifference
      ? match
      : null;
    this.lastMatch = match;
    this.lastReliableMatch = reliableMatch;
    // Matching informs direction and routing, but never relocates the camera
    // or marker. Both already occupy the exact same game coordinate space.
    const targetPoint = longitudeLatitude;
    this.lastGamePoint = targetPoint;
    const targetBearing = reliableMatch?.alignedBearing ?? travelBearing;
    const now = performance.now();
    const deltaSeconds = this.lastRenderTime
      ? Math.min((now - this.lastRenderTime) / 1000, 0.1)
      : 1 / 60;
    this.lastRenderTime = now;
    const displayJump = this.displayPoint
      && DirectedRoadMatcher.distance(this.displayPoint, targetPoint) > 300;
    if (!this.displayPoint || this.displayBearing === null || displayJump) {
      this.displayPoint = [...targetPoint];
      this.displayBearing = targetBearing;
    } else {
      const positionFactor = 1 - Math.exp(-16 * deltaSeconds);
      const bearingFactor = 1 - Math.exp(-12 * deltaSeconds);
      this.displayPoint[0] += (targetPoint[0] - this.displayPoint[0]) * positionFactor;
      this.displayPoint[1] += (targetPoint[1] - this.displayPoint[1]) * positionFactor;
      const bearingDifference = DirectedRoadMatcher.normalizeAngle(targetBearing - this.displayBearing);
      this.displayBearing = DirectedRoadMatcher.normalizeAngle(
        this.displayBearing + bearingDifference * bearingFactor
      );
    }
    this.lastMarkerPoint = reliableMatch?.point || targetPoint;
    this.setDirectionStatus(reliableMatch);
    const routeMatches = this.navigationMatches(targetPoint, travelBearing, position[1]);
    this.updateRouteProgress(routeMatches);

    if (this.isFreeBrowsing && Date.now() - this.lastInteractionTime > 15000 && interpolator.currentSpeed > 5) {
      this.recenter();
    }
    if (!this.isFreeBrowsing) {
      const speedRatio = Math.min(Math.max(interpolator.currentSpeed / 250, 0), 1);
      const zoom = this.autoZoomEnabled
        ? 15.6 + Math.log2(SRP_NAVIGATION_AUTO_ZOOM_SCALE) - speedRatio * 1.7
        : 14.8;
      // Camera and marker must move in the same animation frame. Throttling
      // only the camera makes a centered marker drift and snap back.
      this.map.jumpTo({
        center: this.displayPoint,
        bearing: this.orientationMode === "headingUp" ? this.displayBearing : 0,
        pitch: this.tiltAngle,
        zoom,
      });
    }
    const screenBearing = DirectedRoadMatcher.normalizeAngle(
      this.displayBearing - this.map.getBearing()
    );
    this.marker.setLngLat(this.displayPoint).setRotation(screenBearing);
  }
}

window.SrpGameProjection = SrpGameProjection;
window.DirectedRoadMatcher = DirectedRoadMatcher;
window.DirectedRoadGraph = DirectedRoadGraph;
window.NavigationMapRenderer = NavigationMapRenderer;
