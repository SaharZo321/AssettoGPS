/** Synthesized Web Audio API sound alerts (no external audio files needed). */

class AudioAlertManager {
  private ctx: AudioContext | null = null;
  public enabled: boolean;
  private lastAlertTime = 0;

  constructor() {
    this.enabled = localStorage.getItem("gps_audio_alerts") !== "false";
    this.initAudioContext();
  }

  private initAudioContext(): void {
    try {
      const AudioCtx = window.AudioContext ?? window.webkitAudioContext;
      if (AudioCtx) this.ctx = new AudioCtx();
    } catch (error: unknown) {
      console.warn("Web Audio API not supported", error);
    }
  }

  unlock(): void {
    if (this.ctx?.state === "suspended") void this.ctx.resume();
  }

  setSound(enabled: boolean): boolean {
    this.enabled = Boolean(enabled);
    localStorage.setItem("gps_audio_alerts", this.enabled ? "true" : "false");
    if (this.enabled) this.unlock();
    return this.enabled;
  }

  toggleSound(): boolean {
    return this.setSound(!this.enabled);
  }

  playSpeedCameraAlert(): void {
    const ctx = this.ctx;
    if (!this.enabled || !ctx) return;
    const now = Date.now();
    if (now - this.lastAlertTime < 8000) return;
    this.lastAlertTime = now;
    this.unlock();
    const startTime = ctx.currentTime;
    this.playTone(880, startTime, 0.18, 0.35);
    this.playTone(1174.66, startTime + 0.22, 0.25, 0.4);
  }

  playOverspeedWarning(): void {
    const ctx = this.ctx;
    if (!this.enabled || !ctx) return;
    const now = Date.now();
    if (now - this.lastAlertTime < 5000) return;
    this.lastAlertTime = now;
    this.unlock();
    const startTime = ctx.currentTime;
    this.playTone(950, startTime, 0.1, 0.4);
    this.playTone(950, startTime + 0.14, 0.1, 0.4);
    this.playTone(950, startTime + 0.28, 0.15, 0.45);
  }

  playPoiChime(): void {
    const ctx = this.ctx;
    if (!this.enabled || !ctx) return;
    this.unlock();
    const startTime = ctx.currentTime;
    this.playTone(523.25, startTime, 0.15, 0.25);
    this.playTone(659.25, startTime + 0.12, 0.25, 0.3);
  }

  private playTone(
    frequency: number,
    startTime: number,
    duration: number,
    gainValue = 0.3,
  ): void {
    const ctx = this.ctx;
    if (!ctx) return;
    try {
      const oscillator = ctx.createOscillator();
      const gain = ctx.createGain();
      oscillator.type = "sine";
      oscillator.frequency.setValueAtTime(frequency, startTime);
      gain.gain.setValueAtTime(0, startTime);
      gain.gain.linearRampToValueAtTime(gainValue, startTime + 0.02);
      gain.gain.exponentialRampToValueAtTime(0.0001, startTime + duration);
      oscillator.connect(gain);
      gain.connect(ctx.destination);
      oscillator.start(startTime);
      oscillator.stop(startTime + duration);
    } catch {
      // Scheduling can fail if the browser suspends or closes the context.
    }
  }
}

window.audioAlerts = new AudioAlertManager();
