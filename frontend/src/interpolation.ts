/** Real-time motion smoothing and interpolation engine (60+ FPS). */

class MotionInterpolator {
  public currentPos: Position3D = [0, 0, 0];
  private targetPos: Readonly<Position3D> = [0, 0, 0];
  public currentHeading = 0;
  private targetHeading = 0;
  public currentSpeed = 0;
  private targetSpeed = 0;
  public currentRpm = 0;
  private targetRpm = 0;
  public currentZoom = 1;
  private targetZoom = 1;
  private isInitialized = false;
  private lastUpdateTime = performance.now();

  setTarget(frame: TelemetryFrame): void {
    const carPosition = frame.carPosition;
    if (!carPosition) return;

    if (!this.isInitialized) {
      this.currentPos = [...carPosition];
      this.targetPos = [...carPosition];
      this.currentHeading = frame.headingRad || 0;
      this.targetHeading = frame.headingRad || 0;
      this.currentSpeed = frame.speedKmh || 0;
      this.targetSpeed = frame.speedKmh || 0;
      this.currentRpm = frame.rpms || 0;
      this.targetRpm = frame.rpms || 0;
      this.isInitialized = true;
      return;
    }

    // Detect a teleport/session restart (jump greater than 300 metres).
    const distanceJump = Math.hypot(
      this.currentPos[0] - carPosition[0],
      this.currentPos[2] - carPosition[2],
    );
    if (distanceJump > 300) {
      this.currentPos = [...carPosition];
      this.targetPos = [...carPosition];
      this.currentHeading = frame.headingRad || 0;
      this.targetHeading = frame.headingRad || 0;
      return;
    }

    this.targetPos = carPosition;
    if (frame.headingRad !== undefined) this.targetHeading = frame.headingRad;
    if (frame.speedKmh !== undefined) this.targetSpeed = frame.speedKmh;
    if (frame.rpms !== undefined) this.targetRpm = frame.rpms;
  }

  update(): void {
    const now = performance.now();
    const deltaSeconds = Math.min((now - this.lastUpdateTime) / 1000, 0.1);
    this.lastUpdateTime = now;
    if (!this.isInitialized) return;

    const smoothFactor = 1 - Math.exp(-18 * deltaSeconds);
    this.currentPos[0] += (this.targetPos[0] - this.currentPos[0]) * smoothFactor;
    this.currentPos[1] += (this.targetPos[1] - this.currentPos[1]) * smoothFactor;
    this.currentPos[2] += (this.targetPos[2] - this.currentPos[2]) * smoothFactor;

    let headingDifference = (this.targetHeading - this.currentHeading) % (2 * Math.PI);
    if (headingDifference > Math.PI) headingDifference -= 2 * Math.PI;
    if (headingDifference < -Math.PI) headingDifference += 2 * Math.PI;
    this.currentHeading += headingDifference * smoothFactor;

    this.currentSpeed += (this.targetSpeed - this.currentSpeed) * smoothFactor;
    this.currentRpm += (this.targetRpm - this.currentRpm) * smoothFactor;

    const speedRatio = Math.min(Math.max(this.currentSpeed / 250, 0), 1);
    this.targetZoom = 1.5 - speedRatio * 0.75;
    this.currentZoom += (this.targetZoom - this.currentZoom) * smoothFactor * 0.5;
  }
}

window.motionInterpolator = new MotionInterpolator();
