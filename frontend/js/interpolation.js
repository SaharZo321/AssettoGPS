/**
 * Real-Time Motion Smoothing & Interpolation Engine (60+ FPS)
 */

class MotionInterpolator {
  constructor() {
    this.currentPos = [0, 0, 0];
    this.targetPos = [0, 0, 0];

    this.currentHeading = 0.0; // Radians
    this.targetHeading = 0.0;

    this.currentSpeed = 0.0;
    this.targetSpeed = 0.0;

    this.currentRpm = 0;
    this.targetRpm = 0;

    this.currentZoom = 1.0;
    this.targetZoom = 1.0;

    this.isInitialized = false;
    this.lastUpdateTime = performance.now();
  }

  setTarget(frame) {
    if (!frame.carPosition) return;

    // First frame initialization or teleport reset
    if (!this.isInitialized) {
      this.currentPos = [...frame.carPosition];
      this.targetPos = [...frame.carPosition];
      this.currentHeading = frame.headingRad || 0.0;
      this.targetHeading = frame.headingRad || 0.0;
      this.currentSpeed = frame.speedKmh || 0.0;
      this.targetSpeed = frame.speedKmh || 0.0;
      this.currentRpm = frame.rpms || 0;
      this.targetRpm = frame.rpms || 0;
      this.isInitialized = true;
      return;
    }

    // Teleport / Session restart detection (jump > 300m)
    const distJump = Math.hypot(
      this.currentPos[0] - frame.carPosition[0],
      this.currentPos[2] - frame.carPosition[2]
    );
    if (distJump > 300) {
      this.currentPos = [...frame.carPosition];
      this.targetPos = [...frame.carPosition];
      this.currentHeading = frame.headingRad || 0.0;
      this.targetHeading = frame.headingRad || 0.0;
      return;
    }

    this.targetPos = frame.carPosition;
    if (frame.headingRad !== undefined) {
      this.targetHeading = frame.headingRad;
    }
    if (frame.speedKmh !== undefined) {
      this.targetSpeed = frame.speedKmh;
    }
    if (frame.rpms !== undefined) {
      this.targetRpm = frame.rpms;
    }
  }

  update() {
    const now = performance.now();
    const dt = Math.min((now - this.lastUpdateTime) / 1000.0, 0.1);
    this.lastUpdateTime = now;

    if (!this.isInitialized) return;

    const smoothFactor = 1.0 - Math.exp(-18.0 * dt); // 18 Hz smooth tracking

    // Interpolate (X, Y, Z)
    this.currentPos[0] += (this.targetPos[0] - this.currentPos[0]) * smoothFactor;
    this.currentPos[1] += (this.targetPos[1] - this.currentPos[1]) * smoothFactor;
    this.currentPos[2] += (this.targetPos[2] - this.currentPos[2]) * smoothFactor;

    // Shortest-path angle interpolation for heading (safe JS angle wrap)
    let diff = (this.targetHeading - this.currentHeading) % (2 * Math.PI);
    if (diff > Math.PI) diff -= 2 * Math.PI;
    if (diff < -Math.PI) diff += 2 * Math.PI;
    this.currentHeading += diff * smoothFactor;

    // Speed & RPM smoothing
    this.currentSpeed += (this.targetSpeed - this.currentSpeed) * smoothFactor;
    this.currentRpm += (this.targetRpm - this.currentRpm) * smoothFactor;

    // Auto-zoom calculation (Speed-adaptive: close in corners, wide on straights)
    const speedRatio = Math.min(Math.max(this.currentSpeed / 250.0, 0.0), 1.0);
    this.targetZoom = 1.5 - speedRatio * 0.75;
    this.currentZoom += (this.targetZoom - this.currentZoom) * (smoothFactor * 0.5);
  }
}

window.motionInterpolator = new MotionInterpolator();
