/**
 * Assetto Corsa Waze/GPS Canvas Map Renderer
 * 60 FPS Smooth Rendering, Touch & Mouse Dragging, Pinch-to-Zoom,
 * Heading-Up rotation, POIs, and Waze-style Auto-Return to car.
 */

class MapRenderer {
  constructor(canvasId) {
    this.canvas = document.getElementById(canvasId);
    this.ctx = this.canvas.getContext("2d");

    this.hudCanvas = document.getElementById("hud-canvas");
    this.hudCtx = this.hudCanvas ? this.hudCanvas.getContext("2d") : null;

    this.mapImage = new Image();
    this.isMapLoaded = false;
    this.currentTrackKey = "";

    // Track calibration parameters (from map.ini)
    this.trackInfo = {
      scaleFactor: 1.0,
      xOffset: 0.0,
      zOffset: 0.0,
      mapWidth: 1024,
      mapHeight: 1024,
      pois: [],
    };

    // Camera settings
    this.orientationMode = "headingUp"; // "headingUp" or "northUp"
    this.manualZoom = 1.0;
    this.autoZoomEnabled = true;

    // Free-Browsing & Pan State (Waze Style)
    this.manualPanOffset = { u: 0, v: 0 };
    this.isFreeBrowsing = false;
    this.lastInteractionTime = 0;
    this.currentHeading = 0;
    this.currentSpeed = 0;

    // Drag / Touch Tracking
    this.isDragging = false;
    this.dragStart = { x: 0, y: 0 };
    this.prevTouch2 = null;
    // 3D Perspective Tilt (Waze Style) & Dynamic Rotation
    this.tiltAngle = localStorage.getItem("gps_3d_tilt") === "false" ? 0 : 49;
    this.is3D = this.tiltAngle > 10;
    this.manualRotation = 0; // Manual rotation angle in radians

    // Theme Mode (Dark / Light)
    this.theme = localStorage.getItem("gps_theme") || "dark";
    this.setTheme(this.theme);

    this.recenterBtn = document.getElementById("btn-recenter");
    if (this.recenterBtn) {
      this.recenterBtn.addEventListener("click", () => this.recenter());
    }

    this.setTiltAngle(this.tiltAngle, false);
    this.resize();
    this.setupInteractions();
    window.addEventListener("resize", () => this.resize());
  }

  resize() {
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    this.screenWidth = window.innerWidth;
    this.screenHeight = window.innerHeight;
    this.width = this.screenWidth * 1.8;
    this.height = this.screenHeight * 1.8;
    this.canvas.width = this.width * dpr;
    this.canvas.height = this.height * dpr;
    this.ctx.scale(dpr, dpr);

    if (this.hudCanvas && this.hudCtx) {
      this.hudCanvas.width = this.screenWidth * dpr;
      this.hudCanvas.height = this.screenHeight * dpr;
      this.hudCtx.scale(dpr, dpr);
    }
  }

  setupInteractions() {
    const canvas = this.canvas;

    // Prevent default context menu for smooth right-click 3D dragging on PC
    canvas.addEventListener("contextmenu", (e) => e.preventDefault());

    // 1. Mouse Drag (Left = Pan, Right / Shift+Left = 3D Tilt & Rotate)
    canvas.addEventListener("mousedown", (e) => {
      if (e.button === 2 || (e.button === 0 && e.shiftKey)) {
        this.is3DDragging = true;
        this.drag3DStart = { x: e.clientX, y: e.clientY };
        if (this.canvas) this.canvas.style.transition = "none";
        this.isFreeBrowsing = true;
        this.lastInteractionTime = Date.now();
        this.updateRecenterButton(true);
      } else if (e.button === 0) {
        this.isDragging = true;
        this.dragStart = { x: e.clientX, y: e.clientY };
        this.isFreeBrowsing = true;
        this.lastInteractionTime = Date.now();
        this.updateRecenterButton(true);
      }
    });

    window.addEventListener("mousemove", (e) => {
      if (this.is3DDragging) {
        const dx = e.clientX - this.drag3DStart.x;
        const dy = e.clientY - this.drag3DStart.y;
        this.drag3DStart = { x: e.clientX, y: e.clientY };

        // Vertical drag -> Tilt angle
        this.setTiltAngle(this.tiltAngle - dy * 0.4, false);

        // Horizontal drag -> Manual Rotation
        this.manualRotation += dx * 0.008;
        this.lastInteractionTime = Date.now();
      } else if (this.isDragging) {
        const dx = e.clientX - this.dragStart.x;
        const dy = e.clientY - this.dragStart.y;
        this.dragStart = { x: e.clientX, y: e.clientY };

        this.applyScreenPan(dx, dy);
        this.lastInteractionTime = Date.now();
      }
    });

    window.addEventListener("mouseup", (e) => {
      if (this.is3DDragging) {
        this.is3DDragging = false;
        if (this.canvas) {
          this.canvas.style.transition = "transform 0.35s cubic-bezier(0.25, 1, 0.5, 1)";
        }
      }
      this.isDragging = false;
    });

    // 2. Mouse Wheel Zoom
    canvas.addEventListener(
      "wheel",
      (e) => {
        e.preventDefault();
        const zoomFactor = e.deltaY < 0 ? 0.2 : -0.2;
        this.adjustZoom(zoomFactor);
        this.isFreeBrowsing = true;
        this.lastInteractionTime = Date.now();
        this.updateRecenterButton(true);
      },
      { passive: false }
    );

    // 3. Multi-Touch Gestures: 1-finger Pan, 2-finger Pinch Zoom, Tilt & Twist Rotation
    canvas.addEventListener(
      "touchstart",
      (e) => {
        if (e.touches.length === 1) {
          this.isDragging = true;
          this.dragStart = { x: e.touches[0].clientX, y: e.touches[0].clientY };
          this.prevTouch2 = null;
        } else if (e.touches.length === 2) {
          this.isDragging = false;
          const t1 = e.touches[0];
          const t2 = e.touches[1];
          this.prevTouch2 = {
            dist: Math.hypot(t2.clientX - t1.clientX, t2.clientY - t1.clientY),
            angle: Math.atan2(t2.clientY - t1.clientY, t2.clientX - t1.clientX),
            midY: (t1.clientY + t2.clientY) / 2,
            t1y: t1.clientY,
            t2y: t2.clientY,
          };
          if (this.canvas) this.canvas.style.transition = "none";
        }
        this.isFreeBrowsing = true;
        this.lastInteractionTime = Date.now();
        this.updateRecenterButton(true);
      },
      { passive: true }
    );

    canvas.addEventListener(
      "touchmove",
      (e) => {
        this.lastInteractionTime = Date.now();
        if (e.touches.length === 1 && this.isDragging) {
          const dx = e.touches[0].clientX - this.dragStart.x;
          const dy = e.touches[0].clientY - this.dragStart.y;
          this.dragStart = { x: e.touches[0].clientX, y: e.touches[0].clientY };
          this.applyScreenPan(dx, dy);
        } else if (e.touches.length === 2 && this.prevTouch2) {
          const t1 = e.touches[0];
          const t2 = e.touches[1];
          const currentDist = Math.hypot(t2.clientX - t1.clientX, t2.clientY - t1.clientY);
          const currentAngle = Math.atan2(t2.clientY - t1.clientY, t2.clientX - t1.clientX);
          const currentMidY = (t1.clientY + t2.clientY) / 2;

          const dDist = currentDist - this.prevTouch2.dist;
          let dAngle = currentAngle - this.prevTouch2.angle;
          while (dAngle > Math.PI) dAngle -= 2 * Math.PI;
          while (dAngle < -Math.PI) dAngle += 2 * Math.PI;

          const t1dy = t1.clientY - this.prevTouch2.t1y;
          const t2dy = t2.clientY - this.prevTouch2.t2y;

          // A. Pinch Zoom
          if (Math.abs(dDist) > 1.2) {
            this.adjustZoom(dDist * 0.008);
          }

          // B. Two-Finger Vertical Drag -> Tilt (Swipe UP = more 3D, Swipe DOWN = flat 2D)
          if ((t1dy > 0 && t2dy > 0) || (t1dy < 0 && t2dy < 0)) {
            const avgDy = (t1dy + t2dy) / 2;
            this.setTiltAngle(this.tiltAngle - avgDy * 0.45, false);
          }

          // C. Two-Finger Twist -> Free Rotation
          if (Math.abs(dAngle) > 0.012) {
            this.manualRotation += dAngle;
          }

          this.prevTouch2 = {
            dist: currentDist,
            angle: currentAngle,
            midY: currentMidY,
            t1y: t1.clientY,
            t2y: t2.clientY,
          };
        }
      },
      { passive: true }
    );

    canvas.addEventListener("touchend", (e) => {
      if (this.canvas) {
        this.canvas.style.transition = "transform 0.35s cubic-bezier(0.25, 1, 0.5, 1)";
      }
      if (e.touches.length === 0) {
        this.isDragging = false;
        this.prevTouch2 = null;
      } else if (e.touches.length === 1) {
        this.isDragging = true;
        this.dragStart = { x: e.touches[0].clientX, y: e.touches[0].clientY };
        this.prevTouch2 = null;
      }
    });
  }

  setTiltAngle(angle, animated = false) {
    this.tiltAngle = Math.max(0, Math.min(65, angle));
    this.is3D = this.tiltAngle > 10;
    localStorage.setItem("gps_3d_tilt", this.is3D);

    const rad = (this.tiltAngle * Math.PI) / 180;
    // Dynamic compensation scale: expands the canvas as tilt increases so edges never clip
    const scaleX = 1.0 + Math.sin(rad) * 0.45;
    const scaleY = 1.0 + (1.0 / Math.max(0.35, Math.cos(rad)) - 1.0) * 0.65;

    if (this.canvas) {
      if (!animated) {
        this.canvas.style.transition = "none";
      } else {
        this.canvas.style.transition = "transform 0.35s cubic-bezier(0.25, 1, 0.5, 1)";
      }
      this.canvas.style.transform = `rotateX(${this.tiltAngle}deg) scale(${scaleX.toFixed(3)}, ${scaleY.toFixed(3)})`;
    }

    const container = document.getElementById("app-container");
    if (container) {
      container.classList.toggle("is-3d", this.is3D);
    }

    const btn = document.getElementById("btn-tilt");
    if (btn) {
      btn.innerText = this.tiltAngle > 15 ? "3D" : "2D";
      btn.classList.toggle("active", this.tiltAngle > 15);
    }
  }

  toggleTilt() {
    const target = this.tiltAngle > 15 ? 0 : 49;
    this.setTiltAngle(target, true);
    return target > 15;
  }

  applyScreenPan(screenDx, screenDy) {
    const zoom = this.manualZoom || 1.0;
    let theta = 0;
    if (this.orientationMode === "headingUp") {
      theta = Math.PI - this.currentHeading + this.manualRotation;
    } else {
      theta = this.manualRotation;
    }

    if (this.is3D) {
      screenDy /= Math.max(0.4, Math.cos((this.tiltAngle * Math.PI) / 180));
    }

    // Rotate screen pan vector to match map orientation
    const cos = Math.cos(-theta);
    const sin = Math.sin(-theta);
    const mapDx = (screenDx * cos - screenDy * sin) / zoom;
    const mapDy = (screenDx * sin + screenDy * cos) / zoom;

    this.manualPanOffset.u -= mapDx;
    this.manualPanOffset.v -= mapDy;
  }

  recenter() {
    this.manualPanOffset = { u: 0, v: 0 };
    this.manualRotation = 0;
    this.isFreeBrowsing = false;
    this.updateRecenterButton(false);
  }

  updateRecenterButton(show) {
    if (this.recenterBtn) {
      this.recenterBtn.style.display = show ? "flex" : "none";
    }
  }

  loadMapImage() {
    this.mapImage.src = `/api/track/map.png?track=${encodeURIComponent(this.currentTrackKey)}&t=${Date.now()}`;
    this.mapImage.onload = () => {
      this.isMapLoaded = true;
    };
    this.mapImage.onerror = () => {
      this.isMapLoaded = false;
    };
  }

  setTrackInfo(info, trackName) {
    if (trackName && trackName !== this.currentTrackKey) {
      this.currentTrackKey = trackName;
      this.loadMapImage();
    }
    if (info) {
      this.trackInfo = Object.assign(this.trackInfo, info);
    }
  }

  setTheme(theme) {
    this.theme = theme === "light" ? "light" : "dark";
    localStorage.setItem("gps_theme", this.theme);
    document.documentElement.setAttribute("data-theme", this.theme);
  }

  toggleOrientation() {
    this.orientationMode = this.orientationMode === "headingUp" ? "northUp" : "headingUp";
    return this.orientationMode;
  }

  adjustZoom(deltaFactor) {
    // Proportional smooth zoom with wide dynamic range
    // Allows zooming all the way out to full track overview (0.03) to extreme close-up (4.5)
    if (typeof deltaFactor === "number") {
      if (Math.abs(deltaFactor) < 1.0) {
        this.manualZoom = Math.min(Math.max(this.manualZoom * (1.0 + deltaFactor), 0.03), 4.5);
      } else {
        this.manualZoom = Math.min(Math.max(this.manualZoom + deltaFactor, 0.03), 4.5);
      }
    }
  }

  toggleAutoZoom() {
    this.autoZoomEnabled = !this.autoZoomEnabled;
    return this.autoZoomEnabled;
  }

  /**
   * Transforms Assetto Corsa 3D world (X, Z) to 2D Track Map pixel coordinates
   * Comfy Map / Assetto Corsa Standard Formula:
   * U = (X + X_OFFSET) / SCALE_FACTOR
   * V = (Z + Z_OFFSET) / SCALE_FACTOR
   */
  worldToMap(x, z) {
    const scale = this.trackInfo.scaleFactor || 1.0;
    const u = (x + (this.trackInfo.xOffset || 0.0)) / scale;
    const v = (z + (this.trackInfo.zOffset || 0.0)) / scale;
    return { u, v };
  }

  /**
   * Projects a 2D map pixel (U, V) to the visible screen coordinates (X, Y)
   * taking into account 2D camera pan/rotation/zoom and 3D perspective pitch.
   */
  projectMapToScreen(mapU, mapV, cameraTarget, currentZoom, cameraRotation) {
    const du = (mapU - cameraTarget.u) * currentZoom;
    const dv = (mapV - cameraTarget.v) * currentZoom;

    const cos = Math.cos(cameraRotation);
    const sin = Math.sin(cameraRotation);

    const isHeadingUp = this.orientationMode === "headingUp";
    const originYRatio = isHeadingUp ? 0.8055 : 0.7222;

    const xCanvas = this.width * 0.5 + (du * cos - dv * sin);
    const yCanvas = this.height * originYRatio + (du * sin + dv * cos);

    const origXCanvas = this.width * 0.5;
    const origYCanvas = this.height * 0.8055;

    const origXScreen = this.screenWidth * 0.5;
    const origYScreen = this.screenHeight * 0.65;

    if (!this.is3D || this.tiltAngle <= 0) {
      // 2D Flat Mode Projection
      return {
        x: origXScreen + (xCanvas - origXCanvas),
        y:
          (isHeadingUp ? this.screenHeight * 0.65 : this.screenHeight * 0.50) +
          (yCanvas - this.height * originYRatio),
        scale: 1.0,
        visible: true,
      };
    }

    // 3D Perspective Projection
    const rad = (this.tiltAngle * Math.PI) / 180;
    const scaleX = 1.0 + Math.sin(rad) * 0.45;
    const scaleY = 1.0 + (1.0 / Math.max(0.35, Math.cos(rad)) - 1.0) * 0.65;

    const dx = (xCanvas - origXCanvas) * scaleX;
    const dy = (yCanvas - origYCanvas) * scaleY;

    const yRot = dy * Math.cos(rad);
    const zRot = dy * Math.sin(rad); // Correct sign: points ahead (dy < 0) have zRot < 0

    const perspective = 1800;
    if (zRot >= perspective - 50) {
      return { x: 0, y: 0, scale: 0, visible: false };
    }

    const k = perspective / (perspective - zRot);
    const xScreen = origXScreen + dx * k;
    const yScreen = origYScreen + yRot * k;

    return {
      x: xScreen,
      y: yScreen,
      scale: Math.max(0.35, Math.min(1.35, k)),
      visible:
        xScreen >= -160 &&
        xScreen <= this.screenWidth + 160 &&
        yScreen >= 5 &&
        yScreen <= this.screenHeight + 60,
    };
  }

  render(interpolator) {
    const ctx = this.ctx;
    const w = this.width;
    const h = this.height;

    // Clear background
    ctx.fillStyle = this.theme === "light" ? "#e2e8f0" : "#090d16";
    ctx.fillRect(0, 0, w, h);

    const carWorld = interpolator.currentPos;
    const heading = interpolator.currentHeading;
    this.currentHeading = heading;
    const currentZoom = (this.autoZoomEnabled ? interpolator.currentZoom : 1.0) * this.manualZoom;

    // 1. Waze Auto-Return Logic (Only returns when driving!)
    if (this.isFreeBrowsing && !this.isDragging) {
      const speed = interpolator.currentSpeed || 0;

      // Only auto-recenter if the car is actively driving (> 10 km/h)
      if (speed > 10) {
        const inactiveTime = Date.now() - this.lastInteractionTime;
        if (inactiveTime > 3000) {
          // Smoothly glide pan offset and manual rotation back to zero
          this.manualPanOffset.u *= 0.88;
          this.manualPanOffset.v *= 0.88;
          this.manualRotation *= 0.88;

          if (
            Math.hypot(this.manualPanOffset.u, this.manualPanOffset.v) < 1.5 &&
            Math.abs(this.manualRotation) < 0.005
          ) {
            this.manualPanOffset = { u: 0, v: 0 };
            this.manualRotation = 0;
            this.isFreeBrowsing = false;
            this.updateRecenterButton(false);
          }
        }
      }
    }

    const carMap = this.worldToMap(carWorld[0], carWorld[2]);
    const cameraTarget = {
      u: carMap.u + this.manualPanOffset.u,
      v: carMap.v + this.manualPanOffset.v,
    };

    ctx.save();

    // Camera Positioning on Extended Horizon Canvas
    const cameraRotation =
      this.orientationMode === "headingUp"
        ? Math.PI - heading + this.manualRotation
        : this.manualRotation;

    if (this.orientationMode === "headingUp") {
      // Position car 65% down the visible screen (which maps to 80.55% of the 1.8x canvas)
      ctx.translate(w * 0.5, h * 0.8055);
      ctx.rotate(cameraRotation); // Aligns forward road direction to screen top + manual twist
      ctx.scale(currentZoom, currentZoom);
      ctx.translate(-cameraTarget.u, -cameraTarget.v);
    } else {
      // North-Up: Center on car in visible screen (72.22% of the 1.8x canvas)
      ctx.translate(w * 0.5, h * 0.7222);
      ctx.rotate(cameraRotation);
      ctx.scale(currentZoom, currentZoom);
      ctx.translate(-cameraTarget.u, -cameraTarget.v);
    }

    // 2. Draw Background Tactical GPS Grid Squares
    const isLight = this.theme === "light";
    ctx.strokeStyle = isLight ? "rgba(15, 23, 42, 0.06)" : "rgba(56, 189, 248, 0.07)";
    ctx.lineWidth = 1;
    const gridSize = 100;

    // Dynamic grid bounds centered around camera target
    const gridRange = 3000;
    const startX = Math.floor((cameraTarget.u - gridRange) / gridSize) * gridSize;
    const endX = Math.ceil((cameraTarget.u + gridRange) / gridSize) * gridSize;
    const startY = Math.floor((cameraTarget.v - gridRange) / gridSize) * gridSize;
    const endY = Math.ceil((cameraTarget.v + gridRange) / gridSize) * gridSize;

    ctx.beginPath();
    for (let x = startX; x <= endX; x += gridSize) {
      ctx.moveTo(x, startY);
      ctx.lineTo(x, endY);
    }
    for (let y = startY; y <= endY; y += gridSize) {
      ctx.moveTo(startX, y);
      ctx.lineTo(endX, y);
    }
    ctx.stroke();

    // Subtle crosshairs at major grid intersections
    ctx.strokeStyle = isLight ? "rgba(15, 23, 42, 0.12)" : "rgba(56, 189, 248, 0.18)";
    ctx.lineWidth = 1.2;
    const crossSize = 4;
    const crossStep = 200;
    const cStartX = Math.floor((cameraTarget.u - gridRange) / crossStep) * crossStep;
    const cEndX = Math.ceil((cameraTarget.u + gridRange) / crossStep) * crossStep;
    const cStartY = Math.floor((cameraTarget.v - gridRange) / crossStep) * crossStep;
    const cEndY = Math.ceil((cameraTarget.v + gridRange) / crossStep) * crossStep;

    ctx.beginPath();
    for (let x = cStartX; x <= cEndX; x += crossStep) {
      for (let y = cStartY; y <= cEndY; y += crossStep) {
        ctx.moveTo(x - crossSize, y);
        ctx.lineTo(x + crossSize, y);
        ctx.moveTo(x, y - crossSize);
        ctx.lineTo(x, y + crossSize);
      }
    }
    ctx.stroke();

    // 3. Draw Track Map Image (Over the background grid)
    if (this.isMapLoaded && this.mapImage.width > 0) {
      ctx.drawImage(this.mapImage, 0, 0, this.trackInfo.mapWidth, this.trackInfo.mapHeight);
    }

    ctx.restore();

    // 4. Multi-Pass HUD Rendering (Ground Pins -> Depth-Sorted Badges -> Topmost Car Cursor)
    if (this.hudCtx) {
      const hctx = this.hudCtx;
      hctx.clearRect(0, 0, this.screenWidth, this.screenHeight);

      // Collect and project all visible POIs
      const pois = this.trackInfo.pois || [];
      const visiblePois = [];

      for (const poi of pois) {
        const poiPos = poi.pos || [0, 0, 0];
        const poiMap = this.worldToMap(poiPos[0], poiPos[2]);

        const proj = this.projectMapToScreen(
          poiMap.u,
          poiMap.v,
          cameraTarget,
          currentZoom,
          cameraRotation
        );
        if (!proj.visible) continue;

        visiblePois.push({ poi, proj, poiMap });
      }

      // PASS 1: Draw ALL ground anchor pin dots & vertical stems FIRST
      // This ensures NO ground pin dot ever renders on top of ANY label badge
      for (const item of visiblePois) {
        const { proj } = item;
        hctx.save();
        hctx.translate(proj.x, proj.y);

        // Billboard scale (zoom-out auto enlargement + perspective depth scaling)
        const zoomOutBoost = Math.min(1.4, Math.max(1.0, 1.0 + (0.7 - currentZoom) * 0.5));
        const sBadge = proj.scale * zoomOutBoost;
        hctx.scale(sBadge, sBadge);

        // Ground anchor pin dot (soft shadow + white anchor dot)
        hctx.beginPath();
        hctx.arc(0, 0, 3.5, 0, 2 * Math.PI);
        hctx.fillStyle = "#ffffff";
        hctx.shadowColor = "rgba(0, 0, 0, 0.6)";
        hctx.shadowBlur = 4;
        hctx.fill();

        // Upright vertical billboard stem line
        hctx.beginPath();
        hctx.moveTo(0, 0);
        hctx.lineTo(0, -10);
        hctx.strokeStyle = "rgba(255, 255, 255, 0.85)";
        hctx.lineWidth = 1.5;
        hctx.shadowBlur = 0;
        hctx.stroke();

        hctx.restore();
      }

      // PASS 2: Sort visible POIs by screen depth (farthest items first, closest in front)
      visiblePois.sort((a, b) => a.proj.y - b.proj.y);

      // Draw ALL billboard badges
      for (const item of visiblePois) {
        const { poi, proj } = item;
        hctx.save();
        hctx.translate(proj.x, proj.y);

        const zoomOutBoost = Math.min(1.4, Math.max(1.0, 1.0 + (0.7 - currentZoom) * 0.5));
        const sBadge = proj.scale * zoomOutBoost;
        hctx.scale(sBadge, sBadge);

        // Measure text
        const text = poi.shortName || poi.name;
        hctx.font = "bold 11px -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif";
        const textWidth = hctx.measureText(text).width;

        const badgeW = textWidth + 18;
        const badgeH = 22;
        const badgeX = -badgeW / 2;
        const badgeY = -32;

        // Badge Container with Shadow
        hctx.shadowColor = "rgba(0, 0, 0, 0.65)";
        hctx.shadowBlur = 8;
        hctx.shadowOffsetY = 3;
        hctx.fillStyle =
          poi.type === "parking"
            ? "#0284c7"
            : poi.type === "junction"
            ? "#d97706"
            : "#8b5cf6";
        hctx.beginPath();
        hctx.roundRect(badgeX, badgeY, badgeW, badgeH, 6);
        hctx.fill();

        // White Border
        hctx.shadowBlur = 0;
        hctx.shadowOffsetY = 0;
        hctx.strokeStyle = "rgba(255, 255, 255, 0.9)";
        hctx.lineWidth = 1.2;
        hctx.stroke();

        // Badge Text
        hctx.fillStyle = "#ffffff";
        hctx.textAlign = "center";
        hctx.textBaseline = "middle";
        hctx.fillText(text, 0, badgeY + badgeH / 2);

        hctx.restore();
      }

      // PASS 3: Draw Player Car Cursor ON TOP OF EVERYTHING (Topmost Z-Index Layer)
      const carProj = this.projectMapToScreen(
        carMap.u,
        carMap.v,
        cameraTarget,
        currentZoom,
        cameraRotation
      );

      if (carProj.visible || !this.isFreeBrowsing) {
        hctx.save();
        hctx.translate(carProj.x, carProj.y);

        // Calculate screen-relative heading
        let screenHeading;
        if (this.orientationMode === "headingUp") {
          // In Heading-Up, car points straight UP (0) plus any manual touch-twist
          screenHeading = this.manualRotation;
        } else {
          // In North-Up, car rotates freely with world heading
          screenHeading = heading - Math.PI + this.manualRotation;
        }
        hctx.rotate(screenHeading);

        // Scale cursor for comfort across resolutions
        const s = 1.05 * (this.is3D ? Math.min(1.25, Math.max(0.85, carProj.scale)) : 1.0);

        // Forward Headlight Beam
        const beamGrad = hctx.createRadialGradient(0, 0, 10 * s, 0, -80 * s, 90 * s);
        beamGrad.addColorStop(0, "rgba(56, 189, 248, 0.50)");
        beamGrad.addColorStop(1, "rgba(56, 189, 248, 0)");

        hctx.beginPath();
        hctx.moveTo(0, 0);
        hctx.lineTo(-45 * s, -110 * s);
        hctx.lineTo(45 * s, -110 * s);
        hctx.closePath();
        hctx.fillStyle = beamGrad;
        hctx.fill();

        // Waze Style Cyan Arrow
        hctx.beginPath();
        hctx.moveTo(0, -22 * s);      // Tip
        hctx.lineTo(16 * s, 16 * s);   // Right wing
        hctx.lineTo(0, 8 * s);         // Center notch
        hctx.lineTo(-16 * s, 16 * s);  // Left wing
        hctx.closePath();

        // Glow effect
        hctx.shadowColor = "#38bdf8";
        hctx.shadowBlur = 18;
        hctx.fillStyle = "#38bdf8";
        hctx.fill();

        // Inner highlight
        hctx.shadowBlur = 0;
        hctx.strokeStyle = "#ffffff";
        hctx.lineWidth = 2.5 * s;
        hctx.stroke();

        hctx.restore();
      }
    }
  }
}
